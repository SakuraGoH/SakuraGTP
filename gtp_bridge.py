import threading
import re
import time


class GTPBridge:
    def __init__(self, engine_manager, send_to_fox, on_log=None,
                 on_candidate=None, on_engine_raw=None):
        self.engine = engine_manager
        self.send_to_fox = send_to_fox
        self.on_log = on_log
        self.on_candidate = on_candidate
        self.on_engine_raw = on_engine_raw

        self.board_size = 19
        self.komi = 6.5
        self.ai_color = "B"
        self.handicap_moves = []

        self.fox_moves = {}
        self.ai_moves = {}
        self.last_move_number = 0

        self.live_winrate = False
        self.max_time = 5.0
        self.max_visits = 0
        self.max_playouts = 0

        self._pending_genmove = False
        self._pending_final_score = False
        self._analyzing = False
        self._analyze_start = 0
        self._analyze_color = "B"
        self._candidates = {}
        self._candidates_dirty = False
        self._candidate_flush_interval = 0.03
        self._pending_score_opponent = "0"

        self._cmd_id = 0
        self._id_lock = threading.Lock()
        self._lock = threading.Lock()
        self._id_purpose = {}

        self._flush_thread = threading.Thread(target=self._candidate_flush_loop, daemon=True)
        self._flush_thread.start()
        self._timer_thread = threading.Thread(target=self._timer_loop, daemon=True)
        self._timer_thread.start()

    def log(self, msg):
        if self.on_log:
            self.on_log(msg)

    def set_live_winrate(self, enabled):
        self.live_winrate = bool(enabled)
        self.log(f"实时胜率模式: {'开' if self.live_winrate else '关'}")

    def set_max_time(self, seconds):
        self.max_time = float(seconds)
        self.log(f"maxTime = {self.max_time}")

    def set_max_visits(self, visits):
        self.max_visits = int(visits)
        self.log(f"maxVisits = {self.max_visits}")

    def set_max_playouts(self, playouts):
        self.max_playouts = int(playouts)
        self.log(f"maxPlayouts = {self.max_playouts}")

    def set_rules(self, rule):
        if not self.engine.is_running():
            self.log("引擎未运行，无法切换规则")
            return
        cmd = f"kata-set-rules {rule}"
        self.engine.send(cmd)
        self.log(f"GTP发送: {cmd}")
        self.log(f"已切换规则: {rule}")

    def _next_id(self, purpose=""):
        with self._id_lock:
            self._cmd_id += 1
            cid = self._cmd_id
        if purpose:
            self._id_purpose[cid] = purpose
        return cid

    def _send_gtp(self, command, purpose=""):
        cid = self._next_id(purpose)
        line = f"{cid} {command}"
        self.engine.send(line)
        self.log(f"GTP发送: {line}")
        return cid

    def handle_fox_command(self, command, items):
        if command == "FARULE":
            self._handle_farule(items)
        elif command == "FASTATUS":
            self._handle_fastatus(items)
        elif command == "FAMOVE":
            self._handle_famove(items)
        elif command == "FASKIP":
            self._handle_faskip(items)
        elif command == "FATIMELEFT":
            self._handle_fatimeleft(items)
        elif command == "FARESULT":
            self._handle_faresult(items)
        elif command == "FASCORE":
            self._handle_fascore(items)

    def _handle_farule(self, items):
        if len(items) < 5:
            return
        self.board_size = int(items[0])
        main_time = items[1]
        byo_time = items[2]
        byo_count = items[3]
        self.komi = int(items[4]) / 100.0
        self.handicap_moves = items[5:] if len(items) > 5 else []

        handicap_vertices = []
        for mv in self.handicap_moves:
            try:
                n, x, y, c = mv.split("^")
                vertex = self._xy_to_gtp(int(x), int(y))
                if vertex:
                    handicap_vertices.append(vertex)
            except Exception:
                pass

        self._send_gtp("clear_board", "clear_board")
        self._send_gtp(f"boardsize {self.board_size}", "boardsize")
        self._send_gtp(f"time_settings {main_time} {byo_time} {byo_count}", "time_settings")
        self._send_gtp(f"komi {self.komi}", "komi")
        if handicap_vertices:
            self._send_gtp("set_free_handicap " + " ".join(handicap_vertices), "set_free_handicap")

        self.fox_moves = {}
        self.ai_moves = {}
        self.last_move_number = 0
        self._candidates = {}
        self._candidates_dirty = False
        if self.on_candidate:
            self.on_candidate([])

        self.log(f"规则: 棋盘{self.board_size}, 贴目{self.komi}, 让子{handicap_vertices}")

    def _handle_fastatus(self, items):
        if not items or items[0] == "0":
            self.log("非对弈状态")
            return

        self.ai_color = items[1]
        self.fox_moves = {}
        self.ai_moves = {}
        self.last_move_number = 0

        for mv in items[2:]:
            try:
                n, x, y, c = mv.split("^")
                n = int(n)
                vertex = self._xy_to_gtp(int(x), int(y))
                color = "B" if c == "B" else "W"
                self._send_gtp(f"play {color} {vertex}", "play")
                self.fox_moves[n] = (color, vertex)
                self.ai_moves[n] = (color, vertex)
                self.last_move_number = n
            except Exception as e:
                self.log(f"重放落子失败: {mv} {e}")

        self.log(f"重连重放完成，已同步到第 {self.last_move_number} 手")

    def _handle_famove(self, items):
        if not items:
            return
        is_ai_turn = items[0] == "1"
        self.ai_color = items[1] if len(items) > 1 else "B"

        if len(items) > 2 and items[2] != "0^0^0^N":
            try:
                n, x, y, c = items[2].split("^")
                n = int(n)
                vertex = self._xy_to_gtp(int(x), int(y))
                color = "B" if c == "B" else "W"
                move = (color, vertex)

                if is_ai_turn:
                    self.fox_moves[n] = move
                    if n not in self.ai_moves:
                        self._send_gtp(f"play {color} {vertex}", "play")
                        self.ai_moves[n] = move
                        self.last_move_number = max(self.last_move_number, n)
                        time.sleep(0.05)
                else:
                    self.fox_moves[n] = move
                    self.log(f"野狐确认落子: {color} {vertex}（第 {n} 手），跳过")
            except Exception as e:
                self.log(f"落子解析失败: {items[2]} {e}")

        if is_ai_turn:
            self._start_thinking()

    def _handle_faskip(self, items):
        if not items:
            return
        is_ai_turn = items[0] == "1"
        self.ai_color = items[1] if len(items) > 1 else "B"
        if is_ai_turn:
            self._start_thinking()

    def _handle_fatimeleft(self, items):
        color = "B" if self.ai_color == "B" else "W"
        self._send_gtp(f"time_left {color} 999999 0", "time_left")

    def _handle_faresult(self, items):
        self.log(f"对局结果: {items}")
        self._stop_analyze()
        self._send_gtp("clear_board", "clear_board")
        self.fox_moves = {}
        self.ai_moves = {}
        self.last_move_number = 0
        self._candidates = {}
        self._candidates_dirty = False
        if self.on_candidate:
            self.on_candidate([])

    def _handle_fascore(self, items):
        is_opponent = items[0] if items else "0"
        with self._lock:
            self._pending_final_score = True
            self._pending_score_opponent = is_opponent
        self._send_gtp("final_score", "final_score")

    def _start_thinking(self):
        color = "B" if self.ai_color == "B" else "W"
        self._candidates = {}
        self._candidates_dirty = False
        self._analyze_color = color
        self._pending_genmove = False

        if self.live_winrate:
            self._analyzing = True
            self._analyze_start = time.time()
            if self.max_time > 0:
                self._send_gtp(f"kata-set-param maxTime {self.max_time}", "set_param")
            self._send_gtp(f"kata-analyze {color} interval 50 maxmoves 10", "analyze")
            self.log(f"开始实时分析 {color}")
        else:
            with self._lock:
                if not self._pending_genmove:
                    self._pending_genmove = True
                    self._send_gtp(f"genmove {color}", "genmove")
                    self.log(f"请求 genmove {color}")

    def _stop_analyze(self):
        if not self._analyzing:
            return
        self._analyzing = False
        self._candidates_dirty = False
        self._send_gtp("stop", "stop")
        self._candidates = {}
        if self.on_candidate:
            self.on_candidate([])

    def _timer_loop(self):
        while True:
            time.sleep(0.1)
            if not self._analyzing:
                continue
            elapsed = time.time() - self._analyze_start
            if elapsed >= self.max_time:
                self._commit_live_move()

    def _commit_live_move(self):
        if not self._candidates:
            self.log("无候选，无法落子")
            return
        cands = sorted(self._candidates.values(), key=lambda c: c.get("order", 999))
        best = cands[0]
        gtp_vertex = best["vertex"]
        x, y = best["move"]
        color = self._analyze_color

        self._analyzing = False
        self._candidates_dirty = False
        self._send_gtp("stop", "stop")
        self._candidates = {}
        if self.on_candidate:
            self.on_candidate([])

        self._send_gtp(f"play {color} {gtp_vertex}", "play")

        self.last_move_number += 1
        n = self.last_move_number
        move_str = f"{n}^{x}^{y}^{color}"
        self.send_to_fox("AFPLAY", color, move_str)
        self.log(f"发送落子: {gtp_vertex} -> AFPLAY {color} {move_str}")
        self.fox_moves[n] = (color, gtp_vertex)
        self.ai_moves[n] = (color, gtp_vertex)

    def _candidate_flush_loop(self):
        while True:
            time.sleep(self._candidate_flush_interval)
            if self._candidates_dirty and self._analyzing:
                self._candidates_dirty = False
                if self.on_candidate:
                    cands = sorted(self._candidates.values(),
                                   key=lambda c: c.get("order", 999))
                    self.on_candidate(cands[:20])

    def on_engine_output(self, line):
        line = line.rstrip("\r\n")
        if not line:
            return

        stripped = line.strip()

        m = re.search(r"=(\d+)\s+([A-Ta-t]\d+|pass|resign|PASS|RESIGN)", stripped)
        if m:
            resp_id = int(m.group(1))
            body = m.group(2)
            purpose = self._id_purpose.pop(resp_id, "")
            self.log(f"GTP响应(交错): id={resp_id}, purpose={purpose}, body={body!r}")
            if purpose == "genmove":
                with self._lock:
                    self._pending_genmove = False
                self._send_move_to_fox(body)
                return
            if purpose == "final_score":
                with self._lock:
                    self._pending_final_score = False
                self._send_score_to_fox(body)
                return

        if stripped.startswith("info move"):
            self._parse_info_move(stripped)
            return

        if self.on_engine_raw:
            self.on_engine_raw(line)

        if not stripped or stripped[0] not in "=?":
            return

        body = stripped[1:].strip()
        resp_id = None
        if body and body[0].isdigit():
            parts = body.split(" ", 1)
            try:
                resp_id = int(parts[0])
            except ValueError:
                resp_id = None
            body = parts[1].strip() if len(parts) > 1 else ""

        purpose = self._id_purpose.pop(resp_id, "") if resp_id else ""
        self.log(f"GTP响应: id={resp_id}, purpose={purpose}, body={body!r}")

        if purpose == "genmove":
            with self._lock:
                self._pending_genmove = False
            self._send_move_to_fox(body)
            return
        if purpose == "final_score":
            with self._lock:
                self._pending_final_score = False
            self._send_score_to_fox(body)
            return

    def _parse_info_move(self, line):
        try:
            m = re.search(r"info move ([A-T]\d+)", line)
            if not m:
                return
            move = m.group(1)

            visits = 0
            winrate = 0.0
            score = 0.0
            order = 999

            m = re.search(r"visits (\d+)", line)
            if m:
                visits = int(m.group(1))
            m = re.search(r"winrate ([\d.]+)", line)
            if m:
                winrate = float(m.group(1))
            m = re.search(r"scoreLead (-?[\d.]+)", line)
            if m:
                score = float(m.group(1))
            m = re.search(r"order (\d+)", line)
            if m:
                order = int(m.group(1))

            v = self._gtp_to_xy(move)
            if not v:
                return

            cand = {
                "move": v,
                "vertex": move,
                "visits": visits,
                "winrate": winrate,
                "score": score,
                "order": order,
            }
            self._candidates[move] = cand
            self._candidates_dirty = True

            if order == 0:
                if self.max_visits > 0 and visits >= self.max_visits:
                    self._commit_live_move()
                elif self.max_playouts > 0 and visits >= self.max_playouts:
                    self._commit_live_move()
        except Exception as e:
            self.log(f"info move 解析失败: {e}")

    def _send_move_to_fox(self, move):
        move = move.strip()
        if not move:
            self.log("genmove 返回空，忽略")
            return
        if move.lower() == "resign":
            self.send_to_fox("AFGIVEUP", self.ai_color)
            return
        if move.lower() == "pass":
            self.send_to_fox("AFSKIP", self.ai_color)
            return

        vertex = self._gtp_to_xy(move)
        if vertex is None:
            self.log(f"无法解析落子: {move}")
            return
        x, y = vertex
        self.last_move_number += 1
        n = self.last_move_number
        color = self.ai_color
        move_str = f"{n}^{x}^{y}^{color}"
        self.send_to_fox("AFPLAY", color, move_str)
        self.log(f"发送落子: {move} -> AFPLAY {color} {move_str}")

        gtp_vertex = self._xy_to_gtp(x, y)
        self.fox_moves[n] = (color, gtp_vertex)
        self.ai_moves[n] = (color, gtp_vertex)
        self._candidates = {}
        self._candidates_dirty = False
        if self.on_candidate:
            self.on_candidate([])

    def _send_score_to_fox(self, score):
        score = score.strip()
        result = "0"
        if score == "0" or score.lower() == "draw":
            result = "0"
        elif len(score) >= 3 and score[0].upper() in "WB" and score[1] == "+":
            color = score[0].upper()
            rest = score[2:].strip()
            if rest.upper() in ("R", "RESIGN"):
                result = f"{color}+R"
            else:
                try:
                    num = float(rest)
                    result = f"{color}+{int(num * 100)}"
                except ValueError:
                    result = score
        else:
            result = score
        is_opponent = getattr(self, "_pending_score_opponent", "0")
        self.send_to_fox("AFSCORE", is_opponent, result)

    def _xy_to_gtp(self, x, y):
        letters = "ABCDEFGHJKLMNOPQRST"
        if 0 <= x < len(letters) and 0 <= y < 19:
            return f"{letters[x]}{19 - y}"
        return "pass"

    def _gtp_to_xy(self, vertex):
        vertex = vertex.upper()
        if vertex == "PASS":
            return None
        letters = "ABCDEFGHJKLMNOPQRST"
        m = re.match(r"^([A-HJ-T])(\d{1,2})$", vertex)
        if not m:
            return None
        l = m.group(1)
        num = int(m.group(2))
        if l not in letters:
            return None
        x = letters.index(l)
        y = 19 - num
        if not (0 <= x < 19 and 0 <= y < 19):
            return None
        return x, y