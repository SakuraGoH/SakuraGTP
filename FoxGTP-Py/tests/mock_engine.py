"""Mock GTP engines and an in-memory transport, for tests without subprocesses."""

import re

from foxgtp.transports import Transport


class MockEngine:
    """Pretends to be KataGo / Leela Zero / GNU Go."""

    def __init__(self, mode="katago"):
        self.mode = mode
        self.size = 19
        self.komi = 0.0
        self.board = []                 # [(color, vertex)]
        self.handicap = []
        self.received = []
        self.next_move = {"B": "Q16", "W": "D4"}
        self.reject = set()
        self.prefix = ""
        self.score_result = "B+3.5"
        self.echoes_id = mode in ("katago", "gnugo")
        self.analyze_style = "bare-play"
        self.rules = ""
        self.params = []
        self.time_settings = ""

        base = ["protocol_version", "name", "version", "list_commands",
                "known_command", "boardsize", "clear_board", "komi", "play",
                "genmove", "time_settings", "time_left", "set_free_handicap",
                "final_score"]
        if mode == "katago":
            base += ["kata-genmove_analyze", "kata-set-param", "kata-set-rules",
                     "undo", "stop", "kata-raw-nn"]
            self.name = "KataGo"
            self.version = "1.13.0"
        elif mode == "leela":
            base = [c for c in base if c != "final_score"] + ["undo", "lz-analyze"]
            self.name = "Leela Zero"
            self.version = "0.17"
        elif mode == "gnugo":
            base += ["fixed_handicap"]
            self.name = "GNU Go"
            self.version = "3.8"
        else:
            self.name = "Mock"
            self.version = "1.0"
        self.commands = set(base)

    # ------------------------------------------------------------------
    def handle_line(self, raw):
        self.emitted = []
        raw = (raw or "").strip()
        if not raw:
            return []
        match = re.match(r"^(\d+)\s+(.*)$", raw)
        if match:
            cid, command = int(match.group(1)), match.group(2).strip()
        else:
            cid, command = None, raw
        self.received.append((cid, command))
        name, _, args = command.partition(" ")
        args = args.strip()
        handler = getattr(self, "_cmd_" + name.replace("-", "_"), None)
        if handler is None or name not in self.commands or name in self.reject:
            return self._respond(cid, "unknown command", ok=False)
        return handler(cid, args)

    def _respond(self, cid, body="", ok=True):
        mark = "=" if ok else "?"
        if self.echoes_id and cid is not None:
            head = "%s%d" % (mark, cid) + ((" " + body) if body else "")
        else:
            head = mark + ((" " + body) if body else "")
        return [head, ""]

    def _stream(self, lines):
        return list(lines)

    # ------------------------------------------------------------------
    def _cmd_protocol_version(self, cid, args):
        return self._respond(cid, "2")

    def _cmd_name(self, cid, args):
        return self._respond(cid, self.name)

    def _cmd_version(self, cid, args):
        return self._respond(cid, self.version)

    def _cmd_list_commands(self, cid, args):
        return self._respond(cid, "\n".join(sorted(self.commands)))

    def _cmd_known_command(self, cid, args):
        return self._respond(cid, "true" if args in self.commands else "false")

    def _cmd_boardsize(self, cid, args):
        try:
            self.size = int(args)
        except ValueError:
            return self._respond(cid, "syntax error", ok=False)
        self.board = []
        return self._respond(cid)

    def _cmd_clear_board(self, cid, args):
        self.board = []
        self.handicap = []
        return self._respond(cid)

    def _cmd_komi(self, cid, args):
        try:
            self.komi = float(args)
        except ValueError:
            return self._respond(cid, "syntax error", ok=False)
        return self._respond(cid)

    def _cmd_time_settings(self, cid, args):
        self.time_settings = args
        return self._respond(cid)

    def _cmd_time_left(self, cid, args):
        return self._respond(cid)

    def _cmd_set_free_handicap(self, cid, args):
        self.handicap = args.split()
        for vertex in self.handicap:
            self.board.append(("B", vertex))
        return self._respond(cid)

    def _cmd_fixed_handicap(self, cid, args):
        return self._respond(cid, "D4")

    def _cmd_play(self, cid, args):
        parts = args.split()
        if len(parts) != 2:
            return self._respond(cid, "syntax error", ok=False)
        color, vertex = parts[0].upper(), parts[1]
        if vertex.upper() != "PASS" and not re.match(
                r"^[A-HJ-T](?:[1-9]|1[0-9]|2[0-5])$", vertex.upper()):
            return self._respond(cid, "invalid vertex", ok=False)
        self.board.append((color, vertex))
        return self._respond(cid)

    def _cmd_undo(self, cid, args):
        if self.board:
            self.board.pop()
        return self._respond(cid)

    def _cmd_genmove(self, cid, args):
        color = (args.split() or ["B"])[0].upper()
        move = self.next_move.get(color, "pass")
        if move.upper() != "PASS":
            self.board.append((color, move))
        return self._respond(cid, self.prefix + move)

    def _cmd_kata_genmove_analyze(self, cid, args):
        color = (args.split() or ["B"])[0].upper()
        move = self.next_move.get(color, "pass")
        info = [
            "info move %s visits 120 winrate 0.61 scoreLead 2.4 order 0 pv %s"
            % (move, move),
            "info move D4 visits 80 winrate 0.58 scoreLead 1.9 order 1 pv D4",
        ]
        if self.analyze_style == "bare-play":
            if move.upper() != "PASS":
                self.board.append((color, move))
            ack = self._respond(cid)
            return ack + info + ["play " + move, ""]
        return info + self._respond(cid, "play " + move)

    def _cmd_kata_set_param(self, cid, args):
        self.params.append(args)
        return self._respond(cid)

    def _cmd_kata_set_rules(self, cid, args):
        self.rules = args
        return self._respond(cid)

    def _cmd_lz_analyze(self, cid, args):
        return ["info move Q16 visits 10 winrate 5500", ""]

    def _cmd_final_score(self, cid, args):
        return self._respond(cid, self.score_result)

    def _cmd_stop(self, cid, args):
        return self._respond(cid)

    # ------------------------------------------------------------------ queries
    def commands_named(self, name):
        return [cmd for _cid, cmd in self.received if cmd.split(" ")[0] == name]

    def plays(self):
        return [cmd for _cid, cmd in self.received if cmd.startswith("play ")]

    def clear(self):
        self.received = []


class MockTransport(Transport):
    """In-memory transport: writes go straight to a MockEngine."""

    kind = "mock"

    def __init__(self, engine, on_line=None, on_exit=None):
        super().__init__(on_line, on_exit)
        self.engine = engine
        self.sent = []

    def start(self):
        self._running = True
        return True, "mock engine started"

    def send(self, line):
        self.sent.append(line)
        for chunk in self.engine.handle_line(line):
            for piece in str(chunk).split("\n"):
                self._emit(piece)
        return True

    def stop(self):
        self._running = False

    def describe(self):
        return "MOCK: %s" % self.engine.name
