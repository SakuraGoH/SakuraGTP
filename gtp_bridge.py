"""野狐协议 ↔ GTP 桥接（重写版）。

设计直接照抄 FoxGTP 逆向出来的三条兼容性经验，并在此基础上放宽：

1. **只用核心 GTP**：任何非必要的扩展命令（kata-* / lz-*）都必须先探测，
   探测不到就退回 ``genmove`` 等核心写法；
2. **两套棋谱 + 差异同步**：野狐发来的落子序列是唯一事实来源，引擎侧维护一份
   "我已经同步到第几手"的列表。每次只需补发差异；一旦两边对不上（掉线、重连、
   引擎报 illegal move、换了引擎），直接 ``clear_board`` + 重设规则 + 整盘重放。
   因为不依赖 ``undo``，所以任何引擎都能恢复 —— 这是 FoxGTP 能兼容那么多
   引擎的关键，也是我们保留的核心机制；
3. **每手同步时间**：``time_settings`` 开局给一次，``time_left`` 每手给一次，
   并把野狐的「N 秒 x M 次」读秒换算成引擎认的口径（加拿大读秒 / 常用读秒）。

额外放宽（FoxGTP 做不到的）：

* 引擎不回显命令号也能用（按先发先回匹配）；
* ``= Q16`` / ``=1 Q16`` / 裸 ``play Q16`` 三种响应都认；
* ``Leela: Q16`` 之类引擎前缀自动剥离；
* genmove 失败会自动重建局面重试，仍失败才 pass，不会把野狐挂死。
"""

import re
import threading
import time

from gtp_dialect import (Dialect, EngineProfile, VERTEX_LETTERS, probe)
from gtp_session import GTPResponse, GTPSession, looks_like_vertex


class GTPBridge:
    # 与 FoxGTP 对齐的命令用途（仅作日志可读性）
    def __init__(self, engine_manager, send_to_fox, on_log=None,
                 on_candidate=None, on_engine_raw=None):
        self.engine = engine_manager
        self.send_to_fox = send_to_fox
        self.on_log = on_log
        self.on_candidate = on_candidate
        self.on_engine_raw = on_engine_raw

        # ---- 对局状态（UI/API 会直接读这些属性，保持兼容） ----
        self.board_size = 19
        self.komi = 6.5
        self.ai_color = "B"
        self.rule = ""
        self.handicap_moves = []
        self._handicap_vertices = []

        self.fox_moves = {}          # 手数 -> (颜色, GTP 顶点)
        self.last_move_number = 0

        self.max_time = 5.0
        self.max_visits = 0
        self.max_playouts = 0

        # ---- 内部：棋谱事件（含 pass），两边各一份 ----
        self._events = []            # [(color, vertex or "pass")] 按发生顺序
        self._engine_events = []     # 引擎侧已确认同步到的事件
        self._engine_handicap = []
        self._dirty_engine = False   # 引擎局面可能坏了，下次同步必须整盘重建

        # ---- 时间 ----
        self._time_main = 0
        self._time_byo = 0
        self._time_count = 0
        self._left_main = 0
        self._left_byo = 0
        self._left_count = 0

        # ---- 思考状态 ----
        self._genmove_pending = False
        self._genmove_started = 0.0
        self._genmove_tries = 0
        self._genmove_mode = "plain"
        self._pending_score_opponent = "0"
        self._final_score_pending = False

        # ---- 分析/候选点 ----
        self._candidates = {}
        self._candidates_dirty = False
        self._candidate_flush_interval = 0.05
        self._analyzing = False

        # ---- 引擎方言 ----
        self.profile = EngineProfile()
        self.dialect = Dialect(self.profile)
        self._ready = False
        self._probe_thread = None
        self._game_configured = False    # 是否已经收到过 FARULE
        self._engine_setup_done = False  # 本局棋盘设置是否已下发给当前引擎

        self._lock = threading.RLock()

        self.session = GTPSession(
            write=self._write,
            on_log=self.log,
            on_line=self._on_line,
            on_stream=self._on_stream,
            on_response=self._on_response,
        )

        threading.Thread(target=self._candidate_flush_loop, daemon=True).start()
        threading.Thread(target=self._watchdog_loop, daemon=True).start()

    # ================================================================== 日志/IO
    def log(self, msg):
        if self.on_log:
            self.on_log(msg)

    def _write(self, line):
        try:
            return bool(self.engine.send(line))
        except Exception:
            return False

    def _on_line(self, line):
        if line.startswith(">>> "):
            self.log("GTP发送: " + line[4:])
            return
        if self.on_engine_raw:
            self.on_engine_raw(line)

    def on_engine_output(self, line):
        """引擎 stdout 的一行（由 EngineManager 的回调转进来）。"""
        self.session.on_engine_line(line)

    # ================================================================== 引擎生命周期
    def on_engine_started(self, hint=""):
        """引擎启动后调用：清会话、复位方言、起探测线程。"""
        self.session.reset("引擎启动")
        # 换引擎时不能沿用上一个引擎的画像，否则会先发错命令
        self.profile = EngineProfile()
        self.session.echoes_id = True
        with self._lock:
            self._sync_dialect()
        self._engine_events = []
        self._engine_handicap = []
        self._dirty_engine = True
        self._genmove_pending = False
        self._final_score_pending = False
        self._ready = False
        self._engine_setup_done = False
        self._probe_thread = threading.Thread(
            target=self._probe_worker, args=(hint or "",), daemon=True)
        self._probe_thread.start()

    def on_engine_stopped(self):
        self.session.reset("引擎停止")
        self._ready = False
        self._engine_events = []
        self._engine_handicap = []
        self._genmove_pending = False
        self._final_score_pending = False

    def _probe_worker(self, hint):
        """等引擎就绪 → 探测方言。

        注意：KataGo 加载大权重可能要几十秒，期间不回应任何命令。
        所以这里用「一条命令 + 长超时」等待，而不是频繁重发（重发会在管道里
        堆一串孤儿响应，对不回显 id 的引擎是隐患）。
        """
        if not self.engine.is_running():
            return
        r = self.session.call("protocol_version", timeout=120.0)
        if r is None:
            self.log("引擎 120 秒内没有响应，跳过能力探测（按核心 GTP 继续）")
            with self._lock:
                self._ready = True
                self._sync_dialect()
            return

        prof = probe(self.session, hint=hint, timeout=3.0)
        with self._lock:
            self.profile = prof
            self.session.echoes_id = prof.echoes_id
            self._sync_dialect()
            self._ready = True
        self.log("引擎识别: " + prof.summary())
        if not prof.echoes_id:
            self.log("该引擎不回显命令号，已切换为「先发先回」匹配（FoxGTP 不支持这种引擎）")
        if not prof.list_ok:
            self.log("该引擎不支持 list_commands，能力按默认值处理")

        # 探测期间可能已经开局：补一次同步，让新识别的方言重新下发设置
        with self._lock:
            has_game = self._game_configured or bool(self._handicap_vertices)
        if has_game and self.engine.is_running():
            self.log("探测完成，按新方言重建引擎局面")
            self._rebuild_engine()

    def _sync_dialect(self):
        d = self.dialect
        d.profile = self.profile
        d.board_size = self.board_size
        d.main_time = self._time_main
        d.byo_time = self._time_byo
        d.byo_count = self._time_count
        d.max_time = self.max_time
        d.max_visits = self.max_visits
        d.max_playouts = self.max_playouts

    # ================================================================== 参数设置
    def set_live_winrate(self, enabled):
        self.log("实时胜率由 genmove 的分析输出提供，开关无效")

    def set_max_time(self, seconds):
        self.max_time = float(seconds)
        self._sync_dialect()
        self.log("maxTime = %s" % self.max_time)

    def set_max_visits(self, visits):
        self.max_visits = int(visits)
        self._sync_dialect()
        self.log("maxVisits = %s" % self.max_visits)

    def set_max_playouts(self, playouts):
        self.max_playouts = int(playouts)
        self._sync_dialect()
        self.log("maxPlayouts = %s" % self.max_playouts)

    def set_rules(self, rule):
        self.rule = (rule or "").strip()
        if not self.engine.is_running():
            self.log("引擎未运行，规则已记录，待开局时下发")
            return
        cmd = self.dialect.rules_command(self.rule)
        if cmd:
            self.session.send(cmd, "rules")
            self.log("已切换规则: %s" % self.rule)
        else:
            self.log("引擎不支持规则切换（kata-set-rules），已忽略: %s" % self.rule)

    def set_time_options(self, use_go_byoyomi=False, use_data_transfer_time=False,
                         data_transfer_time=1, specify_ai_byoyomi=False,
                         ai_byoyomi_time=5):
        """对应 FoxGTP 手册 4.4.1 / 4.4.2 的三组读秒选项。"""
        d = self.dialect
        d.use_go_byoyomi = bool(use_go_byoyomi)
        d.use_data_transfer_time = bool(use_data_transfer_time)
        d.data_transfer_time = int(data_transfer_time)
        d.specify_ai_byoyomi = bool(specify_ai_byoyomi)
        d.ai_byoyomi_time = int(ai_byoyomi_time)

    # ================================================================== 野狐命令
    def handle_fox_command(self, command, items):
        handler = {
            "FARULE": self._handle_farule,
            "FASTATUS": self._handle_fastatus,
            "FAMOVE": self._handle_famove,
            "FASKIP": self._handle_faskip,
            "FATIMELEFT": self._handle_fatimeleft,
            "FARESULT": self._handle_faresult,
            "FASCORE": self._handle_fascore,
        }.get(command)
        if handler is None:
            return
        try:
            handler(items)
        except Exception as e:
            self.log("处理 %s 失败: %s" % (command, e))

    # ---------------------------------------------------------------- FARULE
    def _handle_farule(self, items):
        if len(items) < 5:
            self.log("FARULE 字段不足，忽略")
            return
        try:
            size = int(items[0])
            main_time = int(items[1])
            byo_time = int(items[2])
            byo_count = int(items[3])
            komi = int(items[4]) / 100.0
        except ValueError:
            self.log("FARULE 解析失败: %s" % (items[:5],))
            return

        handicap_vertices = []
        for mv in items[5:]:
            try:
                _n, x, y, _c = mv.split("^")
                v = self._xy_to_gtp(int(x), int(y))
                if v and v != "pass":
                    handicap_vertices.append(v)
            except Exception:
                continue

        with self._lock:
            self.board_size = size
            self.komi = komi
            self._game_configured = True
            self._engine_setup_done = False
            self.handicap_moves = list(items[5:])
            self._handicap_vertices = list(handicap_vertices)
            self._time_main = main_time
            self._time_byo = byo_time
            self._time_count = byo_count
            self._left_main = main_time
            self._left_byo = byo_time
            self._left_count = byo_count

            self._events = []
            self._engine_events = []
            self.fox_moves = {}
            self.last_move_number = 0
            self._genmove_tries = 0
            self._genmove_pending = False
            self._candidates = {}
            self._candidates_dirty = False
            self._sync_dialect()

            # 让子用负数手数，避免和正式手数 1、2 冲突（UI 也依赖这个约定）
            for i, vertex in enumerate(handicap_vertices):
                self.fox_moves[-i] = ("B", vertex)

        # 上一局残余的待完成命令必须清掉（引擎可能还在算上一局）
        self.session.reset("新对局", orphan_skip=True)
        self._setup_engine()
        self._notify_candidates([])
        self.log("规则: 棋盘%d, 贴目%s, 让子%s, 时间 %d+%d×%d" % (
            size, self.komi, handicap_vertices or "无", main_time, byo_time, byo_count))

    # ---------------------------------------------------------------- FASTATUS
    def _handle_fastatus(self, items):
        if not items or items[0] == "0":
            self.log("非对弈状态")
            return
        if len(items) < 2:
            return
        ai_color = "B" if items[1].upper() == "B" else "W"

        plays = []
        for mv in items[2:]:
            try:
                n, x, y, c = mv.split("^")
                n = int(n)
                vertex = self._xy_to_gtp(int(x), int(y))
                color = "B" if c.upper() == "B" else "W"
                if vertex == "pass":
                    continue
                plays.append((n, color, vertex))
            except Exception:
                continue

        # 让子：协议里让子也会出现在状态序列里（手数从 1 开始），
        # 但它们已经由 set_free_handicap 下过，必须从落子序列里剔除。
        handi = list(self._handicap_vertices)
        if handi:
            handi_set = set(handi)
            dropped = 0
            while plays and dropped < len(handi):
                _n, color, vertex = plays[0]
                if color == "B" and vertex in handi_set:
                    plays.pop(0)
                    dropped += 1
                else:
                    break

        with self._lock:
            self.ai_color = ai_color
            self.fox_moves = {}
            for i, vertex in enumerate(handi):
                self.fox_moves[-i] = ("B", vertex)
            self._events = [(c, v) for _n, c, v in plays]
            self.last_move_number = max([n for n, _c, _v in plays], default=0)
            for n, c, v in plays:
                self.fox_moves[n] = (c, v)
            self._sync_dialect()

        self._sync_engine()
        self.log("状态同步完成：%d 手，AI 执 %s" % (len(self._events), ai_color))

    # ---------------------------------------------------------------- FAMOVE
    def _handle_famove(self, items):
        if not items:
            return
        is_ai_turn = items[0] == "1"
        if len(items) > 1:
            self.ai_color = "B" if items[1].upper() == "B" else "W"

        move = items[2] if len(items) > 2 else "0^0^0^N"
        if move and move != "0^0^0^N":
            self._ingest_fox_move(move)

        self._sync_engine()
        if is_ai_turn:
            self._ensure_genmove()

    def _ingest_fox_move(self, move_str):
        try:
            n, x, y, c = move_str.split("^")
            n = int(n)
            vertex = self._xy_to_gtp(int(x), int(y))
            color = "B" if c.upper() == "B" else "W"
        except Exception:
            self.log("落子解析失败: %s" % move_str)
            return
        if vertex == "pass":
            return

        with self._lock:
            # 野狐回显 AI 自己刚下的那手：引擎那边已经算落子了，不能重复 play
            if self._events and self._events[-1] == (color, vertex) and n <= self.last_move_number:
                self.fox_moves[n] = (color, vertex)
                return

            if n <= self.last_move_number and n in self.fox_moves:
                # 重复通知，忽略
                return

            gap = n - self.last_move_number
            self._events.append((color, vertex))
            self.fox_moves[n] = (color, vertex)
            if gap > 1:
                self.log("手数从 %d 跳到 %d，可能有落子没收到，稍后整盘重建"
                         % (n - gap, n))
                self._dirty_engine = True
            self.last_move_number = n

            # 让子手数不参与正式手数比较
            self._candidates = {}
            self._candidates_dirty = False

    # ---------------------------------------------------------------- FASKIP
    def _handle_faskip(self, items):
        if not items:
            return
        is_ai_turn = items[0] == "1"
        if len(items) > 1:
            self.ai_color = "B" if items[1].upper() == "B" else "W"

        with self._lock:
            if is_ai_turn:
                # 现在轮到 AI，说明刚才是对手停了一手
                opp = "W" if self.ai_color == "B" else "B"
                if not (self._events and self._events[-1] == (opp, "pass")):
                    self._events.append((opp, "pass"))
                    self.log("对手停一手，已同步到引擎")
            else:
                # AI 自己停一手（我们主动 AFSKIP 的回执）
                color = self.ai_color
                if not (self._events and self._events[-1] == (color, "pass")):
                    self._events.append((color, "pass"))

        self._sync_engine()
        if is_ai_turn:
            self._ensure_genmove()

    # ---------------------------------------------------------------- FATIMELEFT
    def _handle_fatimeleft(self, items):
        if len(items) < 3:
            return
        try:
            self._left_main = int(items[0])
            self._left_byo = int(items[1])
            self._left_count = int(items[2])
        except ValueError:
            return
        self.log("剩余时间: 保留 %d 秒, 读秒 %d 秒 × %d 次"
                 % (self._left_main, self._left_byo, self._left_count))

    # ---------------------------------------------------------------- FARESULT
    def _handle_faresult(self, items):
        self.log("对局结果: %s" % (items,))
        with self._lock:
            self._genmove_pending = False
            self._final_score_pending = False
            self._candidates = {}
            self._candidates_dirty = False
        self._notify_candidates([])
        with self._lock:
            self._events = []
            self._engine_events = []
            self.fox_moves = {}
            self.last_move_number = 0
            self._handicap_vertices = []
            self.handicap_moves = []
            self._game_configured = False
            self._dirty_engine = True
        # 局末清盘（FoxGTP 2.6 加的同样处理，防止引擎把上一局残局带进下一局）
        if self.engine.is_running():
            self.session.send("clear_board", "clear_board")

    # ---------------------------------------------------------------- FASCORE
    def _handle_fascore(self, items):
        is_opponent = items[0] if items else "0"
        cmd = self.dialect.final_score_command()
        if not cmd or not self.engine.is_running():
            self.log("引擎不支持 final_score，按协议回 error")
            self.send_to_fox("AFSCORE", is_opponent, "error")
            return
        self._sync_engine()
        with self._lock:
            self._pending_score_opponent = is_opponent
            self._final_score_pending = True
        self.session.send(cmd, "final_score")

    # ================================================================== 引擎同步
    def _setup_engine(self):
        """(重新)下发棋盘设置。命令顺序与 FoxGTP 一致。"""
        if not self.engine.is_running():
            return
        cmds = self.dialect.setup_commands(
            self.board_size, self.komi, self._handicap_vertices, self.rule)
        for cmd in cmds:
            self.session.send(cmd, cmd.split(" ")[0])
        with self._lock:
            self._engine_events = []
            self._engine_handicap = list(self._handicap_vertices)
            self._engine_setup_done = True
            self._dirty_engine = False

    def _sync_engine(self, force_full=False):
        """把野狐棋谱同步到引擎：只补差异；对不上就整盘重建。"""
        if not self.engine.is_running():
            return
        with self._lock:
            setup_done = self._engine_setup_done
        if not setup_done:
            # 开局时引擎还没起来（或刚重启）：先把棋盘设置补上
            self._setup_engine()
        with self._lock:
            events = list(self._events)
            eng = list(self._engine_events)
            dirty = self._dirty_engine or force_full

        if dirty:
            self._rebuild_engine(events)
            return

        # 公共前缀
        n = 0
        while n < len(events) and n < len(eng) and events[n] == eng[n]:
            n += 1
        if n < len(eng):
            # 两边同一个位置记录不一致 → 引擎局面不可信，整盘重建
            self.log("引擎棋谱与野狐棋谱不一致（第 %d 手），整盘重建" % (n + 1))
            self._rebuild_engine(events)
            return
        if n == len(events):
            return

        for color, vertex in events[n:]:
            self.session.send(self.dialect.play_command(color, vertex), "play")
            self.log("同步落子: %s %s" % (color, vertex))
        with self._lock:
            self._engine_events = events

    def _rebuild_engine(self, events=None):
        if not self.engine.is_running():
            return
        if events is None:
            with self._lock:
                events = list(self._events)
        self.log("重建引擎局面：%d 手" % len(events))
        self._setup_engine()
        for color, vertex in events:
            self.session.send(self.dialect.play_command(color, vertex), "play")
        with self._lock:
            self._engine_events = list(events)
            self._engine_handicap = list(self._handicap_vertices)
            self._dirty_engine = False

    # ================================================================== 思考
    def _ensure_genmove(self):
        if not self.engine.is_running():
            self.log("引擎未运行，无法请求落子（等引擎恢复后野狐会重发）")
            return
        with self._lock:
            if self._genmove_pending:
                self.log("上一次 genmove 尚未返回，跳过本次请求")
                return
            self._genmove_pending = True
            self._genmove_started = time.time()
            self._genmove_tries = 1
            self._analyzing = True
        self._candidates = {}
        self._candidates_dirty = False
        self._notify_candidates([])
        self._send_genmove()

    def _send_genmove(self):
        color = self.ai_color
        self._sync_dialect()

        # 时间：每手同步一次剩余时间（FoxGTP 1.9 起同样每手同步）
        if self.profile.time_left:
            for cmd in self.dialect.time_left_commands(
                    color, self._left_main, self._left_byo, self._left_count):
                self.session.send(cmd, "time_left")

        # 计算量：只有 KataGo 认 kata-set-param
        if self._genmove_tries == 1:
            for cmd in self.dialect.param_commands():
                self.session.send(cmd, "param")

        want_analysis = (self._genmove_tries == 1)
        cmd, mode = self.dialect.genmove_command(color, want_analysis=want_analysis)
        self._genmove_mode = mode
        # analyze 类命令的最终落子是后面一条裸 "play XXX" 行，这里打开流模式
        self.session.streaming = True
        purpose = "analyze" if mode == "kata-analyze" else "genmove"
        self.session.send(cmd, purpose)
        self.log("请求落子: %s（%s）" % (cmd, mode))

    def _finish_genmove(self, resp):
        with self._lock:
            if not self._genmove_pending:
                return
            self._genmove_pending = False
            self._analyzing = False
        self.session.streaming = False
        self._notify_candidates([])

        kind, vertex = self.dialect.parse_genmove(resp.body)
        if kind is None:
            self.log("genmove 响应无法解析: %r（ok=%s）" % (resp.body, resp.ok))
            self._retry_or_giveup()
            return
        self._apply_ai_move(kind, vertex)

    def _retry_or_giveup(self):
        with self._lock:
            tries = self._genmove_tries
        if tries < 2:
            self.log("genmove 失败，重建局面后重试一次（改用最保守的 genmove）")
            self._dirty_engine = True
            self._sync_engine()
            with self._lock:
                self._genmove_pending = True
                self._genmove_started = time.time()
                self._genmove_tries = tries + 1
            self._send_genmove()
            return
        # 两次都失败：宁可停一手也不能让野狐等超时
        self.log("genmove 连续失败，向野狐发送停一手以免超时判负")
        self.send_to_fox("AFSKIP", self.ai_color)

    def _apply_ai_move(self, kind, vertex):
        color = self.ai_color
        if kind == "resign":
            self.log("引擎认输")
            self.send_to_fox("AFGIVEUP", color)
            return
        if kind == "pass":
            with self._lock:
                self._events.append((color, "pass"))
                # 引擎的 genmove pass 已经作用在它自己的盘面上
                self._engine_events.append((color, "pass"))
            self.log("AI 停一手")
            self.send_to_fox("AFSKIP", color)
            return

        xy = self._gtp_to_xy(vertex)
        if xy is None:
            self.log("引擎返回的落子无法换算到野狐坐标: %s，改为停一手" % vertex)
            self._retry_or_giveup()
            return
        x, y = xy
        with self._lock:
            n = self.last_move_number + 1
            self.last_move_number = n
            self.fox_moves[n] = (color, vertex)
            self._events.append((color, vertex))
            # genmove 已经把这一手落在引擎盘面上了，同步记录避免重复 play。
            # 这里只追加自己这一手：如果引擎之前落后，追加后序列不再是野狐
            # 棋谱的前缀，下次同步会自动整盘重建。
            self._engine_events.append((color, vertex))
        move_str = "%d^%d^%d^%s" % (n, x, y, color)
        self.send_to_fox("AFPLAY", color, move_str)
        self.log("AI 落子: %s %s -> AFPLAY %s" % (color, vertex, move_str))

    # ================================================================== 应答分发
    def _on_response(self, resp):
        purpose = resp.purpose
        if purpose in ("genmove", "analyze"):
            if purpose == "analyze" and resp.ok:
                body = (resp.body or "").strip()
                # KataGo 的 analyze 命令会先回一个空 ack（有些版本正文只有命令号），
                # 真正的落子在后面的 "play XXX" 行里，这里不能当结果。
                if not body or body.isdigit():
                    self.log("引擎已接受分析请求，等待落子行…")
                    return
            self._finish_genmove(resp)
            return
        if purpose == "final_score":
            self._finish_final_score(resp)
            return
        if purpose == "play":
            if not resp.ok:
                self.log("引擎拒绝落子: %r → 标记局面重建" % resp.body)
                with self._lock:
                    self._dirty_engine = True
            return
        if purpose in ("setup", "clear_board", "boardsize", "komi",
                       "time_settings", "set_free_handicap", "time_left", "rules", "param"):
            if not resp.ok:
                cmd_name = purpose
                self.log("引擎对 %s 返回错误: %r（已忽略）" % (cmd_name, resp.body))
                if purpose == "boardsize":
                    self.log("该引擎可能不支持当前棋盘尺寸，请检查引擎设置")
            return

    def _finish_final_score(self, resp):
        with self._lock:
            if not self._final_score_pending:
                return
            self._final_score_pending = False
            is_opponent = self._pending_score_opponent
        result = self.dialect.parse_score(resp.body) if resp.ok else "error"
        if result == "error":
            self.log("点目失败或引擎不支持: %r，按协议回 error" % resp.body)
        else:
            self.log("点目结果: %r -> %s" % (resp.body, result))
        self.send_to_fox("AFSCORE", is_opponent, result)

    # ================================================================== 分析流
    def _on_stream(self, purpose, line):
        """引擎的中间输出：KataGo 的 info / play 行，也可能有裸落子。"""
        text = (line or "").strip()
        if not text:
            return

        # KataGo 的 analyze 最后一行是裸 "play D4"，没有 '=' 前缀。
        # 这时要主动把这条待完成命令摘掉，否则后面会错配。
        m = re.match(r"^play\s+(\S+)$", text, re.IGNORECASE)
        if m:
            self.session.complete_pending("genmove", body=m.group(1))
            self.session.complete_pending("analyze", body=m.group(1))
            if self._genmove_pending:
                self._finish_genmove(GTPResponse(ok=True, body=m.group(1), raw=text))
            return

        if looks_like_vertex(text) and self._genmove_pending:
            self._finish_genmove(GTPResponse(ok=True, body=text, raw=text))
            return

        if "info move" in text or text.startswith("info "):
            self._parse_info(text)

    def _parse_info(self, line):
        """解析 info move 行（KataGo 与 LeelaZero 两种口径都吃）。"""
        try:
            matches = list(re.finditer(r"info move ([A-HJ-Ta-hj-t]\d{1,2})", line))
            if not matches:
                return
            for idx, m in enumerate(matches):
                move = m.group(1).upper()
                seg = line[m.end():matches[idx + 1].start() if idx + 1 < len(matches) else len(line)]
                visits = _search_int(seg, "visits")
                winrate = _search_float(seg, "winrate")
                score = _search_float(seg, "scoreLead")
                if score is None:
                    score = _search_float(seg, "scoreMean")
                order = _search_int(seg, "order")
                if winrate is not None and winrate > 1.5:
                    # LeelaZero 的 winrate 是 1/10000
                    winrate = winrate / 10000.0
                xy = self._gtp_to_xy(move)
                if xy is None:
                    continue
                self._candidates[move] = {
                    "move": xy,
                    "vertex": move,
                    "visits": visits or 0,
                    "winrate": winrate or 0.0,
                    "score": score or 0.0,
                    "order": order if order is not None else 999,
                }
                self._candidates_dirty = True
        except Exception as e:
            self.log("info 解析失败: %s" % e)

    def _notify_candidates(self, cands):
        if self.on_candidate:
            try:
                self.on_candidate(cands)
            except Exception:
                pass

    def _candidate_flush_loop(self):
        while True:
            time.sleep(self._candidate_flush_interval)
            if self._candidates_dirty:
                self._candidates_dirty = False
                cands = sorted(self._candidates.values(),
                               key=lambda c: c.get("order", 999))
                self._notify_candidates(cands[:20])

    # ================================================================== 看门狗
    def _watchdog_loop(self):
        while True:
            time.sleep(1.0)
            try:
                self._watchdog_tick()
            except Exception:
                pass

    def _watchdog_tick(self):
        with self._lock:
            pending = self._genmove_pending
            started = self._genmove_started
            tries = self._genmove_tries
        if not pending:
            return
        limit = max(30.0, float(self.max_time or 0) + 25.0)
        if time.time() - started < limit:
            return
        self.log("genmove 已等待 %.0f 秒仍未返回" % (time.time() - started))
        stop_cmd = self.dialect.stop_command()
        if stop_cmd:
            self.session.send(stop_cmd, "stop")
        with self._lock:
            self._genmove_pending = False
            self._analyzing = False
        self.session.streaming = False
        if tries < 2:
            self.log("发送 stop 并重试一次")
            with self._lock:
                self._genmove_pending = True
                self._genmove_started = time.time()
                self._genmove_tries = tries + 1
            self._send_genmove()
        else:
            self.log("引擎无响应，向野狐发送停一手")
            self.send_to_fox("AFSKIP", self.ai_color)

    # ================================================================== 坐标
    def _xy_to_gtp(self, x, y):
        n = self.board_size
        if 0 <= x < len(VERTEX_LETTERS) and 0 <= y < n:
            return "%s%d" % (VERTEX_LETTERS[x], n - y)
        return "pass"

    def _gtp_to_xy(self, vertex):
        """GTP 顶点 → 野狐坐标 (x, y)；pass / 非法返回 None。"""
        if not vertex:
            return None
        v = vertex.strip().upper()
        if v in ("PASS", "RESIGN"):
            return None
        m = re.match(r"^([A-HJ-T])(\d{1,2})$", v)
        if not m:
            return None
        letter, num = m.group(1), int(m.group(2))
        if letter not in VERTEX_LETTERS:
            return None
        x = VERTEX_LETTERS.index(letter)
        y = self.board_size - num
        if not (0 <= x < self.board_size and 0 <= y < self.board_size):
            return None
        return x, y

    # ================================================================== 兼容旧接口
    def _send_move_to_fox(self, move):        # 旧代码可能调用
        kind, vertex = self.dialect.parse_genmove(move)
        if kind:
            self._apply_ai_move(kind, vertex)

    def _stop_analyze(self):                  # 旧接口
        if self._analyzing:
            self._analyzing = False
            cmd = self.dialect.stop_command()
            if cmd:
                self.session.send(cmd, "stop")

    def _commit_live_move(self):
        self.log("落子由 genmove 自动返回，无需本地提交")


# ---------------------------------------------------------------------- 小工具
def _search_int(text, key):
    m = re.search(r"\b%s (\d+)" % key, text)
    return int(m.group(1)) if m else None


def _search_float(text, key):
    m = re.search(r"\b%s (-?[\d.]+)" % key, text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None
