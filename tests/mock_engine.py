"""可编程的假 GTP 引擎，用来验证桥接层对各种方言的兼容性。

三种典型画像：

* ``katago``  —— 回显命令号、支持 kata-* 与 final_score，analyze 输出流式 info 行
* ``leela``   —— 不回显命令号、没有 kata-*，genmove 只回 ``= Q16``（还带引擎前缀）
* ``gnugo``   —— 回显命令号、只有核心 GTP，final_score 返回 ``B+3.5``
"""

import re


class MockEngine:
    NAME = "Mock Go"
    VERSION = "1.0"

    def __init__(self, mode="katago"):
        self.mode = mode
        self.echoes_id = mode in ("katago", "gnugo")
        self.size = 19
        self.komi = 0.0
        self.board = []            # [(color, vertex)]，含 pass
        self.handicap = []
        self.undo_count = 0
        self.clear_count = 0
        self.received = []         # [(id, 命令行)]
        self.emitted = []          # 发出的原始响应行
        self.next_move = {"B": "Q16", "W": "D4"}
        self.score_result = "B+3.5"
        self.prefix = ""

        # 对外宣称支持的命令（list_commands）
        base = ["protocol_version", "name", "version", "list_commands", "known_command",
                "boardsize", "clear_board", "komi", "play", "genmove",
                "time_settings", "time_left", "set_free_handicap", "final_score"]
        if mode == "katago":
            base += ["kata-genmove_analyze", "kata-set-param", "kata-set-rules",
                     "undo", "stop", "kata-raw-nn"]
            self.NAME = "KataGo"
            self.VERSION = "1.13.0"
        elif mode == "leela":
            base = [c for c in base if c != "final_score"] + ["undo", "lz-analyze"]
            self.NAME = "Leela Zero"
            self.VERSION = "0.17"
        elif mode == "gnugo":
            base += ["fixed_handicap"]
            self.NAME = "GNU Go"
            self.VERSION = "3.8"
        elif mode == "phoenixgo":
            # PhoenixGo 的真实 list_commands：没有 kata-*，没有 known_command，
            # 不支持 komi 非 7.5，genmove 返回普通坐标。
            base = ["name", "version", "protocol_version", "list_commands", "quit",
                    "clear_board", "boardsize", "komi", "time_settings", "time_left",
                    "place_free_handicap", "set_free_handicap", "play", "genmove",
                    "final_score", "get_debug_info", "get_last_move_debug_info", "undo"]
            self.NAME = "PhoenixGo"
            self.VERSION = "1.0"
            self.score_result = "W+0.5"
        self.commands = set(base)
        # 声称支持但实际会报错的命令（用于测试「探测被骗」后的回退）
        self.reject = set()
        self.analyze_style = "bare-play"   # bare-play / marker

    # ------------------------------------------------------------------ 对外
    def handle_line(self, line):
        """处理一条引擎输入，返回要输出的若干行。"""
        self.emitted = []
        line = (line or "").strip()
        if not line:
            return []
        m = re.match(r"^(\d+)\s+(.*)$", line)
        if m:
            cid, cmd = int(m.group(1)), m.group(2).strip()
        else:
            cid, cmd = None, line
        self.received.append((cid, cmd))

        name, _, args = cmd.partition(" ")
        args = args.strip()
        handler = getattr(self, "_cmd_" + name.replace("-", "_"), None)
        if handler is None or name not in self.commands or name in self.reject:
            return self._respond(cid, "unknown command", ok=False)
        return handler(cid, args)

    # ------------------------------------------------------------------ 响应格式
    def _respond(self, cid, body="", ok=True):
        mark = "=" if ok else "?"
        if self.echoes_id and cid is not None:
            head = "%s%d" % (mark, cid)
            if body:
                head += " " + body
        else:
            head = mark + ((" " + body) if body else "")
        lines = [head] + [""]
        self.emitted.extend(lines)
        return lines

    def _stream(self, lines):
        self.emitted.extend(lines)
        return lines

    # ------------------------------------------------------------------ 命令
    def _cmd_protocol_version(self, cid, args):
        return self._respond(cid, "2")

    def _cmd_name(self, cid, args):
        return self._respond(cid, self.NAME)

    def _cmd_version(self, cid, args):
        return self._respond(cid, self.VERSION)

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
        self.clear_count += 1
        return self._respond(cid)

    def _cmd_komi(self, cid, args):
        try:
            self.komi = float(args)
        except ValueError:
            return self._respond(cid, "syntax error", ok=False)
        if self.mode == "phoenixgo" and abs(self.komi - 7.5) > 1e-9:
            # PhoenixGo 的贴目写死 7.5，其余值直接拒绝
            return self._respond(cid, "unacceptable komi", ok=False)
        return self._respond(cid)

    def _cmd_time_settings(self, cid, args):
        self.time_settings = args
        return self._respond(cid)

    def _cmd_time_left(self, cid, args):
        self.time_left = args
        return self._respond(cid)

    def _cmd_set_free_handicap(self, cid, args):
        self.handicap = args.split()
        for v in self.handicap:
            self.board.append(("B", v))
        return self._respond(cid)

    def _cmd_fixed_handicap(self, cid, args):
        return self._respond(cid, "D4")

    def _cmd_play(self, cid, args):
        parts = args.split()
        if len(parts) != 2:
            return self._respond(cid, "syntax error", ok=False)
        color, vertex = parts[0].upper(), parts[1]
        if vertex.upper() != "PASS":
            if not re.match(r"^[A-HJ-T](?:[1-9]|1[0-9]|2[0-5])$", vertex.upper()):
                return self._respond(cid, "invalid vertex", ok=False)
        self.board.append((color, vertex))
        return self._respond(cid)

    def _cmd_undo(self, cid, args):
        if self.board:
            self.board.pop()
            self.undo_count += 1
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
            "info move %s visits 120 winrate 0.61 scoreLead 2.4 order 0 pv %s" % (move, move),
            "info move D4 visits 80 winrate 0.58 scoreLead 1.9 order 1 pv D4",
        ]
        if self.analyze_style == "bare-play":
            # 真实 KataGo：先回一个空 ack（=id），再流式给 info 行，
            # 最后是裸 "play XXX"，没有 '=' 前缀。
            if move.upper() != "PASS":
                self.board.append((color, move))
            ack = self._respond(cid)
            return self._stream(ack + info + ["play " + move, ""])
        return self._stream(info) + self._respond(cid, "play " + move)

    def _cmd_kata_set_param(self, cid, args):
        self.last_param = args
        return self._respond(cid)

    def _cmd_kata_set_rules(self, cid, args):
        self.rules = args
        return self._respond(cid)

    def _cmd_lz_analyze(self, cid, args):
        return self._stream(["info move Q16 visits 10 winrate 5500"])

    def _cmd_final_score(self, cid, args):
        return self._respond(cid, self.score_result)

    def _cmd_stop(self, cid, args):
        return self._respond(cid)

    def _cmd_quit(self, cid, args):
        return self._respond(cid)

    # ------------------------------------------------------------------ 查询
    def plays(self):
        return [cmd for _cid, cmd in self.received if cmd.startswith("play ")]

    def commands_named(self, name):
        return [cmd for _cid, cmd in self.received if cmd.split(" ")[0] == name]

    def clear(self):
        self.received = []
