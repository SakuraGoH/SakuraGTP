"""The controller: Wild Fox protocol <-> GTP, the actual "connector" logic.

Structure (mirrors FoxGTP):

    FoxServer  --packets-->  Controller  --commands-->  GtpSession  --lines-->  Transport

The controller owns the game state, the two move lists, the re-sync logic, the
time translation, the genmove watchdog and the heartbeat/recovery machinery.
It is deliberately UI-free: the GUI subscribes through ``listener(topic, data)``.
"""

import re
import threading
import time

from . import gtp_protocol
from .config import build_engine_command, resolve_working_dir
from .dialect import Dialect, DialectOptions
from .engine_profile import EngineProfile, engine_hint, probe
from .fox_protocol import format_move, parse_move
from .fox_server import FoxServer
from .game_state import GameState, SyncPlan, plan_sync
from .gtp_session import GtpResponse, GtpSession
from .logbook import ERROR, IN, INFO, OUT, LogBook
from .transports import build_transport


def _same_vertex_set(left, right):
    return {v.upper() for v in left} == {v.upper() for v in right}


class Controller:
    # -- tuning ---------------------------------------------------------
    GENMOVE_GRACE = 25.0          # seconds on top of max_time before giving up
    SCORE_TIMEOUT = 120.0
    PROBE_RETRY = 0.5

    def __init__(self, config, listener=None):
        self.config = config
        self.listener = listener

        self.logbook = LogBook(on_entry=self._on_log_entry)
        self.session = GtpSession(
            on_line=self._on_gtp_line,
            on_stream=self._on_gtp_stream,
            on_response=self._on_gtp_response,
            on_log=self._log_info,
            on_unsolicited=self._on_gtp_unsolicited,
        )
        self.fox = FoxServer(
            on_packet=self._on_fox_packet,
            on_status=self._on_fox_status,
            on_log=self._on_fox_log,
            on_error=self._on_fox_error,
        )

        self.state = GameState()
        self.profile = EngineProfile()
        self.dialect = Dialect(self.profile, self._dialect_options())

        self.transport = None
        self._lock = threading.RLock()
        self._stopping = False
        self._recovering = False
        self._engine_ready = False
        self._engine_setup_done = False
        self._game_configured = False
        self._probe_thread = None

        # genmove
        self._genmove_pending = False
        self._genmove_started = 0.0
        self._genmove_tries = 0
        self._genmove_mode = "plain"
        self._genmove_color = "B"
        self._genmove_waiting = False

        # final score
        self._score_pending = False
        self._score_started = 0.0
        self._score_opponent = "0"

        # candidates / winrate
        self.candidates = {}
        self._candidates_dirty = False
        self._last_candidate_emit = 0.0
        self.winrate = None
        self.score_lead = None

        # heartbeat
        self._heartbeat_due = 0.0
        self._heartbeat_sent = 0.0

        self._watchdog = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog.start()

    # ================================================================== events
    def _emit(self, topic, **payload):
        if not self.listener:
            return
        try:
            self.listener(topic, payload)
        except Exception:
            pass

    def _log_info(self, text):
        self.logbook.info(text)

    # ================================================================== logging
    def _on_log_entry(self, channel, direction, line):
        self._emit("log", channel=channel, direction=direction, text=line)

    def _on_gtp_line(self, line):
        if line.startswith(">>> "):
            self.logbook.write("gtp", OUT, line[4:])
        else:
            self.logbook.write("gtp", IN, line)

    def _on_gtp_unsolicited(self, text):
        self.logbook.write("gtp", INFO, "引擎输出: %s" % text)

    def _on_fox_log(self, direction, text):
        if direction == "in":
            self.logbook.write("fox", IN, text)
        elif direction == "out":
            self.logbook.write("fox", OUT, text)
        else:
            self.logbook.info(text)

    def _on_fox_error(self, text):
        self.logbook.write("fox", ERROR, text)
        self._emit("error", text=text)

    def _on_fox_status(self, connected, text):
        self._emit("fox", connected=connected, listening=self.fox.is_listening(),
                   peer=self.fox.last_peer, text=text)
        if text:
            self.logbook.info(text)

    # ================================================================== config
    def apply_config(self, config):
        """Re-read settings that do not require reconnecting."""
        self.config = config
        self.logbook.configure(
            enabled=config.get("save_log", False),
            log_dir=config.get("log_dir", "logs"),
            timestamp=config.get("timestamp_in_log", True),
        )
        self.dialect = Dialect(self.profile, self._dialect_options())
        self._sync_times()

    def _dialect_options(self):
        cfg = self.config
        return DialectOptions(
            use_go_byoyomi=bool(cfg.get("use_go_byoyomi")),
            use_data_transfer_time=bool(cfg.get("use_data_transfer_time")),
            data_transfer_time=int(cfg.get("data_transfer_time") or 0),
            use_ai_cal_time=bool(cfg.get("use_ai_cal_time")),
            ai_cal_time=int(cfg.get("ai_cal_time") or 0),
            max_time=float(cfg.get("max_time") or 0),
            max_visits=int(cfg.get("max_visits") or 0),
            max_playouts=int(cfg.get("max_playouts") or 0),
            use_analyze=bool(cfg.get("use_analyze", True)),
            analyze_interval_ms=int(cfg.get("analyze_interval_ms") or 50),
            analyze_max_moves=int(cfg.get("analyze_max_moves") or 12),
            rule=cfg.get("rule") or "",
            handicap_mode=cfg.get("handicap_mode") or "auto",
        )

    def _sync_times(self):
        self.dialect.board_size = self.state.board_size
        self.dialect.main_time = self.state.main_time
        self.dialect.byo_time = self.state.byo_time
        self.dialect.byo_count = self.state.byo_count

    def _apply_profile(self, profile):
        self.profile = profile
        self.dialect = Dialect(profile, self._dialect_options())
        self._sync_times()
        self._emit("profile", profile=profile.as_dict())

    # ================================================================== engine
    def start_engine(self):
        with self._lock:
            if self.transport is not None:
                return False, "AI 引擎已连接"
            self._stopping = False
            config = dict(self.config)
            config["engine_command"] = build_engine_command(config)
            config["working_dir"] = resolve_working_dir(config)
            transport = build_transport(
                config,
                on_exit=self._on_engine_exit,
                on_peer=self._on_engine_peer,
            )
            ok, message = transport.start()
            if not ok:
                return False, message
            self.transport = transport
            self.session.attach(transport)
            self.session.reset("连接引擎")
            self.profile = EngineProfile()
            self._apply_profile(self.profile)
            self._engine_ready = False
            self._engine_setup_done = False
            self.state.engine_events = []
            self.state.mark_dirty()
            self._heartbeat_due = time.time() + float(self.config.get("heartbeat_interval") or 30)

        self._emit("engine", running=True, ready=False, description=transport.describe())
        self.logbook.info("AI 引擎连接方式: %s" % transport.describe())
        self._probe_thread = threading.Thread(target=self._probe_worker, daemon=True)
        self._probe_thread.start()
        return True, message

    def stop_engine(self, intentional=True):
        with self._lock:
            if intentional:
                self._stopping = True
            transport, self.transport = self.transport, None
            self._engine_ready = False
            self._engine_setup_done = False
            self._genmove_pending = False
            self._score_pending = False
            self.session.streaming = False
        if transport is not None:
            try:
                transport.stop()
            except Exception:
                pass
        self.session.reset("断开引擎")
        self.state.engine_events = []
        self.state.mark_dirty()
        self._emit("engine", running=False, ready=False, description="未连接")
        if intentional:
            self.logbook.info("AI 引擎已断开")

    def _on_engine_peer(self, address):
        if address is None:
            self._emit("engine", running=self.transport is not None, ready=False,
                       description="等待 AI 引擎连接")
        else:
            self.logbook.info("AI 引擎已接入: %s:%d" % address)
            self._emit("engine", running=True, ready=self._engine_ready,
                       description="AI 引擎已接入 %s:%d" % address)

    def _on_engine_exit(self, reason=""):
        with self._lock:
            if self._stopping or self.transport is None:
                return
            self.transport = None
            self._engine_ready = False
            self._engine_setup_done = False
            self._genmove_pending = False
            self._score_pending = False
        self.session.reset("引擎退出")
        self._emit("engine", running=False, ready=False, description=reason or "引擎已断开")
        self.logbook.info("AI 引擎已断开: %s" % (reason or "未知原因"))
        if self.config.get("auto_recover", True):
            self._start_recovery()

    def _start_recovery(self):
        with self._lock:
            if self._recovering or self._stopping:
                return
            self._recovering = True
        threading.Thread(target=self._recovery_loop, daemon=True).start()

    def _recovery_loop(self):
        interval = max(1, int(self.config.get("recover_interval") or 5))
        attempts = 0
        while not self._stopping and self.config.get("auto_recover", True):
            attempts += 1
            self.logbook.info("自动恢复：%d 秒后尝试重新连接 AI 引擎（第 %d 次）"
                              % (interval, attempts))
            for _ in range(interval * 10):
                if self._stopping:
                    break
                time.sleep(0.1)
            if self._stopping:
                break
            ok, message = self.start_engine()
            if ok:
                self.logbook.info("自动恢复成功")
                break
            self.logbook.info("自动恢复失败: %s" % message)
        with self._lock:
            self._recovering = False

    def _probe_worker(self):
        timeout = float(self.config.get("engine_ready_timeout") or 120)
        # 引擎可能正在加载权重，先耐心等第一条 protocol_version
        response = self.session.request("protocol_version", timeout=timeout,
                                        purpose="protocol_version")
        if self.transport is None:
            return
        if response is None:
            self.logbook.error("引擎 %.0f 秒内没有响应，按核心 GTP 继续（能力未知）" % timeout)
            with self._lock:
                self._engine_ready = True
            self._emit("engine", running=True, ready=True, description="引擎无响应")
            self._sync_engine()
            return

        profile = probe(self.session, hint=engine_hint(
            self.config.get("engine_path", ""), self.config.get("engine_args", "")),
            timeout=3.0, logger=self._log_info)
        if self.transport is None:
            return
        self.session.echoes_id = profile.echoes_id
        with self._lock:
            self._apply_profile(profile)
            self._engine_ready = True
        self._emit("engine", running=True, ready=True,
                   description=profile.summary())
        if not profile.echoes_id:
            self.logbook.info("该引擎不回显命令号，已切换为「先发先回」匹配")
        # 探测期间可能已经开局，重新下发设置并同步
        if self._game_configured:
            self.logbook.info("能力探测完成，重建引擎局面")
            self._sync_engine(force_rebuild=True)

    # ================================================================== fox server
    def start_fox(self):
        ok, message = self.fox.start(
            host=self.config.get("fox_host", "0.0.0.0"),
            port=int(self.config.get("fox_port") or 6000),
        )
        self.logbook.info(message)
        return ok, message

    def stop_fox(self):
        self.fox.stop()
        self._emit("fox", connected=False, listening=False, peer="", text="已停止监听")
        self.logbook.info("已停止监听野狐客户端")

    # ================================================================== fox packets
    def _on_fox_packet(self, packet):
        handler = {
            "FARULE": self._fox_rule,
            "FASTATUS": self._fox_status,
            "FAMOVE": self._fox_move,
            "FASKIP": self._fox_skip,
            "FATIMELEFT": self._fox_timeleft,
            "FARESULT": self._fox_result,
            "FASCORE": self._fox_score,
        }.get(packet.command)
        if handler is None:
            self.logbook.info("未知野狐命令: %s" % packet.command)
            return
        try:
            handler(packet)
        except Exception as exc:
            self.logbook.error("处理 %s 失败: %s" % (packet.command, exc))

    def _send_fox(self, command, *items):
        if not self.fox.is_connected():
            self.logbook.error("野狐未连接，无法发送 %s" % command)
            return False
        return self.fox.send(command, *items)

    # -- $FARULE --------------------------------------------------------
    def _fox_rule(self, packet):
        items = packet.items
        if len(items) < 5:
            self.logbook.error("$FARULE 字段不足: %r" % (items,))
            return
        try:
            board_size = int(items[0])
            main_time = int(items[1])
            byo_time = int(items[2])
            byo_count = int(items[3])
            komi = int(items[4]) / 100.0
        except ValueError:
            self.logbook.error("$FARULE 解析失败: %r" % (items[:5],))
            return

        handicap = []
        for item in items[5:]:
            parsed = parse_move(item)
            if not parsed:
                continue
            _no, x, y, color = parsed
            if color != "B":
                continue
            vertex = gtp_protocol.xy_to_vertex(x, y, board_size)
            if vertex != "pass":
                handicap.append(vertex)

        with self._lock:
            self.state.board_size = board_size
            self.state.komi = komi
            self.state.main_time = main_time
            self.state.byo_time = byo_time
            self.state.byo_count = byo_count
            self.state.handicap = handicap
            self.state.remaining = (main_time, byo_time, byo_count)
            self.state.reset()
            self._game_configured = True
            self._engine_setup_done = False
            self._sync_times()
            for index, vertex in enumerate(handicap):
                self.state.fox_moves[-index] = ("B", vertex)

        self.logbook.info("对局规则: %d 路, 贴目 %s, 保留 %d 秒, 读秒 %d×%d, 让子 %s"
                          % (board_size, gtp_protocol.format_komi(komi),
                             main_time, byo_time, byo_count, handicap or "无"))
        if self.transport is not None:
            self.session.reset("新对局", orphan_skip=True)
        self._sync_engine(force_rebuild=True)
        self._emit_board()

    # -- $FASTATUS ------------------------------------------------------
    def _fox_status(self, packet):
        items = packet.items
        if not items or items[0] == "0":
            self.logbook.info("野狐处于非对弈状态")
            self._emit("game", status="idle")
            return
        if len(items) < 2:
            return
        ai_color = "B" if items[1].upper().startswith("B") else "W"
        moves = []
        for item in items[2:]:
            parsed = parse_move(item)
            if not parsed:
                continue
            no, x, y, color = parsed
            vertex = gtp_protocol.xy_to_vertex(x, y, self.state.board_size)
            if vertex == "pass":
                continue
            moves.append((no, color, vertex))

        with self._lock:
            self.state.ai_color = ai_color
            self.state.load_status(ai_color, moves, self.state.handicap)
            count = len(self.state.events)
        self.logbook.info("状态同步: AI 执 %s, 共 %d 手" % (ai_color, count))
        self._sync_engine()
        self._emit_board()

    # -- $FAMOVE --------------------------------------------------------
    def _fox_move(self, packet):
        items = packet.items
        if not items:
            return
        is_ai_turn = items[0] == "1"
        if len(items) > 1:
            self.state.ai_color = "B" if items[1].upper().startswith("B") else "W"
        item = items[2] if len(items) > 2 else ""
        parsed = parse_move(item)
        if parsed:
            no, x, y, color = parsed
            vertex = gtp_protocol.xy_to_vertex(x, y, self.state.board_size)
            if vertex != "pass":
                with self._lock:
                    result = self.state.ingest_move(no, color, vertex)
                if result == "gap":
                    self.logbook.info("手数从 %d 跳到 %d，向野狐查询完整状态"
                                      % (no - 1, no))
                    self._request_fox_status()
                elif result == "new":
                    self.logbook.info("野狐落子: %s %s（第 %d 手）" % (color, vertex, no))

        self._sync_engine()
        self._emit_board()
        if is_ai_turn:
            self._start_genmove()

    # -- $FASKIP --------------------------------------------------------
    def _fox_skip(self, packet):
        items = packet.items
        if not items:
            return
        is_ai_turn = items[0] == "1"
        if len(items) > 1:
            self.state.ai_color = "B" if items[1].upper().startswith("B") else "W"
        with self._lock:
            if is_ai_turn:
                opponent = "W" if self.state.ai_color == "B" else "B"
                if self.state.ingest_pass(opponent):
                    self.logbook.info("对手停一手")
            else:
                if self.state.ingest_pass(self.state.ai_color):
                    self.logbook.info("我方停一手")
        self._sync_engine()
        self._emit_board()
        if is_ai_turn:
            self._start_genmove()

    # -- $FATIMELEFT ----------------------------------------------------
    def _fox_timeleft(self, packet):
        items = packet.items
        if len(items) < 3:
            return
        try:
            remaining = (int(items[0]), int(items[1]), int(items[2]))
        except ValueError:
            return
        self.state.remaining = remaining
        self.logbook.info("剩余时间: 保留 %d 秒, 读秒 %d 秒 × %d 次" % remaining)
        self._emit("time", remaining=remaining)

    # -- $FARESULT ------------------------------------------------------
    def _fox_result(self, packet):
        text = packet.items[0] if packet.items else ""
        readable = gtp_protocol.parse_fox_result(text)
        self.logbook.info("对局结束: %s" % readable)
        self._emit("result", text=text, readable=readable)
        with self._lock:
            self._genmove_pending = False
            self._score_pending = False
            self.candidates = {}
            self.state.reset()
            self._game_configured = False
            self._engine_setup_done = False
        self._emit_candidates()
        # FoxGTP 2.6: clear the engine board at the end of a game
        if self.transport is not None:
            self.session.send("clear_board", "clear_board")
        self._emit_board()

    # -- $FASCORE -------------------------------------------------------
    def _fox_score(self, packet):
        opponent = packet.items[0] if packet.items else "0"
        command = self.dialect.final_score_command()
        if command is None or self.transport is None:
            self.logbook.info("引擎不支持 final_score，按协议回复 error")
            self._send_fox("AFSCORE", opponent, "error")
            return
        self._sync_engine()
        with self._lock:
            self._score_pending = True
            self._score_started = time.time()
            self._score_opponent = opponent
        self.session.send(command, "final_score")
        self.logbook.info("向引擎请求点目 final_score")

    # ================================================================== sync
    def _sync_engine(self, force_rebuild=False):
        if self.transport is None:
            return
        if force_rebuild or not self._engine_setup_done:
            self._send_setup()
            for color, vertex in list(self.state.events):
                self.session.send(self.dialect.play_command(color, vertex), "play")
            self.state.mark_synced()
            return

        plan = self.state.next_plan()
        if plan.kind == "none":
            return
        if plan.kind == "rebuild":
            self.logbook.info("重建引擎局面（%s）" % (plan.reason or ""))
            self._send_setup()
        for color, vertex in plan.events:
            self.session.send(self.dialect.play_command(color, vertex), "play")
        self.state.mark_synced()

    def _send_setup(self):
        commands = self.dialect.setup_commands(
            self.state.board_size, self.state.komi, self.state.handicap,
            self.state.main_time, self.state.byo_time, self.state.byo_count)
        for command in commands:
            self.session.send(command, command.split(" ")[0])
        self.state.engine_events = []
        self.state.dirty = False
        self._engine_setup_done = True

    # ================================================================== genmove
    def _start_genmove(self, color=None):
        if self.transport is None:
            self.logbook.error("引擎未连接，无法落子")
            return
        requested = (color or self.state.ai_color).upper()
        if not self._engine_ready:
            self._defer_genmove(requested)
            return
        with self._lock:
            if self._genmove_pending:
                self.logbook.info("上一次 genmove 尚未结束，忽略本次请求")
                return
            self._genmove_pending = True
            self._genmove_started = time.time()
            self._genmove_tries = 1
            self._genmove_color = requested
            self.state.ai_color = requested
        self.candidates = {}
        self.winrate = None
        self.score_lead = None
        self._emit_candidates()
        self._send_genmove()

    def _defer_genmove(self, color):
        """Engine still loading: wait for the probe, then ask for a move."""
        with self._lock:
            if self._genmove_waiting or self._genmove_pending:
                return
            self._genmove_waiting = True

        def worker():
            deadline = time.time() + float(self.config.get("engine_ready_timeout") or 120)
            while time.time() < deadline:
                if self.transport is None or self._engine_ready:
                    break
                time.sleep(0.2)
            with self._lock:
                self._genmove_waiting = False
            if self.transport is None:
                return
            if not self._engine_ready:
                self.logbook.error("引擎迟迟未就绪，放弃本次落子")
                return
            self._start_genmove(color)

        threading.Thread(target=worker, daemon=True).start()

    def _send_genmove(self):
        color = self._genmove_color
        self._sync_times()
        for command in self.dialect.time_left_commands(color):
            self.session.send(command, "time_left")
        if self._genmove_tries == 1:
            for command in self.dialect.param_commands():
                self.session.send(command, "param")
        command, mode = self.dialect.genmove_command(
            color, want_analysis=(self._genmove_tries == 1))
        self._genmove_mode = mode
        self.session.streaming = True
        purpose = "analyze" if mode == "kata-analyze" else "genmove"
        self.session.send(command, purpose)
        self.logbook.info("请求落子: %s（%s）" % (command, mode))

    def _finish_genmove(self, response):
        with self._lock:
            if not self._genmove_pending:
                return
            self._genmove_pending = False
        self.session.streaming = False
        kind, vertex = gtp_protocol.parse_move_reply(response.body)
        if kind is None:
            self.logbook.error("无法解析落子响应: %r（ok=%s）" % (response.body, response.ok))
            self._retry_or_pass()
            return
        self._apply_ai_move(kind, vertex)

    def _apply_ai_move(self, kind, vertex):
        color = self._genmove_color
        if kind == "resign":
            self.logbook.info("引擎认输")
            self._send_fox("AFGIVEUP", color)
            self._emit("move", color=color, vertex="resign", move_no=None)
            return
        if kind == "pass":
            with self._lock:
                no = self.state.accept_engine_move(color, "pass")
                self.state.ingest_pass(color, expect_duplicate=False)
            self.logbook.info("AI 停一手（第 %d 手）" % no)
            self._send_fox("AFSKIP", color)
            self._emit("move", color=color, vertex="pass", move_no=no)
            self._emit_candidates()
            return

        xy = gtp_protocol.vertex_to_xy(vertex, self.state.board_size)
        if xy is None:
            self.logbook.error("引擎落子 %s 无法换算到野狐坐标" % vertex)
            self._retry_or_pass()
            return
        x, y = xy
        with self._lock:
            no = self.state.accept_engine_move(color, vertex)
        move_text = format_move(no, x, y, color)
        if not self._send_fox("AFPLAY", color, move_text):
            self.logbook.error("发送 AFPLAY 失败")
        self.logbook.info("AI 落子: %s %s（第 %d 手）" % (color, vertex, no))
        self._emit("move", color=color, vertex=vertex, move_no=no, x=x, y=y)
        self._emit_board()
        self._emit_candidates()

    def _retry_or_pass(self):
        with self._lock:
            tries = self._genmove_tries
        if tries < 2 and self.transport is not None:
            self.logbook.info("落子失败，重建局面后改用最保守的 genmove 重试")
            with self._lock:
                self.state.mark_dirty()
            self._sync_engine()
            with self._lock:
                self._genmove_pending = True
                self._genmove_started = time.time()
                self._genmove_tries = tries + 1
            self._send_genmove()
            return
        self.logbook.error("genmove 连续失败，向野狐发送停一手以免超时")
        self._send_fox("AFSKIP", self._genmove_color)

    # ================================================================== GTP replies
    def _on_gtp_response(self, response: GtpResponse):
        purpose = response.purpose
        if purpose in ("genmove", "analyze"):
            if purpose == "analyze" and response.ok:
                body = (response.body or "").strip()
                # KataGo answers analyze commands with an empty ack first; the
                # real move arrives later as a bare "play XXX" line.
                if not body or body.isdigit():
                    self.logbook.info("引擎已接受分析请求，等待落子行…")
                    return
            self._finish_genmove(response)
            return
        if purpose == "final_score":
            self._finish_score(response)
            return
        if purpose == "play":
            if not response.ok:
                self.logbook.error("引擎拒绝落子: %r（将重建局面）" % response.body)
                with self._lock:
                    self.state.mark_dirty()
            return
        if purpose == "heartbeat":
            return
        if purpose in ("setup", "clear_board", "boardsize", "komi", "time_settings",
                       "time_left", "set_free_handicap", "fixed_handicap",
                       "place_free_handicap", "kata-set-param", "kata-set-rules",
                       "param", "rules", "stop"):
            if not response.ok:
                self.logbook.error("引擎对 %s 返回错误: %r（已忽略）" % (purpose, response.body))
            return

    def _finish_score(self, response):
        with self._lock:
            if not self._score_pending:
                return
            self._score_pending = False
            opponent = self._score_opponent
        if not response.ok:
            self.logbook.info("点目失败: %r" % response.body)
            self._send_fox("AFSCORE", opponent, "error")
            return
        winner, points, resign = gtp_protocol.parse_score_reply(response.body)
        result = gtp_protocol.fox_score_string(winner, points, resign)
        self.logbook.info("点目结果: %r -> %s" % (response.body, result))
        self._send_fox("AFSCORE", opponent, result)

    # ================================================================== GTP streams
    def _on_gtp_stream(self, purpose, text):
        text = (text or "").strip()
        if not text:
            return
        match = re.match(r"^play\s+(\S+)$", text, re.IGNORECASE)
        if match:
            self.session.complete_pending("genmove", body=match.group(1))
            self.session.complete_pending("analyze", body=match.group(1))
            if self._genmove_pending:
                self._finish_genmove(GtpResponse(True, 0, match.group(1), text, "analyze"))
            return
        if gtp_protocol.is_vertex(text) and self._genmove_pending:
            self._finish_genmove(GtpResponse(True, 0, text, text, "analyze"))
            return
        if text.startswith("info "):
            self._parse_info(text)

    def _parse_info(self, line):
        """Parse ``info move ...`` lines from KataGo / Leela Zero."""
        try:
            matches = list(re.finditer(r"info move ([A-HJ-Ta-hj-t]\d{1,2})", line))
            for index, match in enumerate(matches):
                vertex = match.group(1).upper()
                end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
                segment = line[match.end():end]
                visits = self._search_int(segment, "visits")
                winrate = self._search_float(segment, "winrate")
                score = self._search_float(segment, "scoreLead")
                if score is None:
                    score = self._search_float(segment, "scoreMean")
                order = self._search_int(segment, "order")
                if winrate is not None and winrate > 1.5:
                    winrate = winrate / 10000.0          # Leela Zero scale
                xy = gtp_protocol.vertex_to_xy(vertex, self.state.board_size)
                if xy is None:
                    continue
                self.candidates[vertex] = {
                    "vertex": vertex,
                    "x": xy[0],
                    "y": xy[1],
                    "visits": visits or 0,
                    "winrate": winrate if winrate is not None else 0.0,
                    "score": score if score is not None else 0.0,
                    "order": order if order is not None else 999,
                }
                self._candidates_dirty = True
        except Exception as exc:
            self.logbook.error("info 解析失败: %s" % exc)

    @staticmethod
    def _search_int(text, key):
        match = re.search(r"\b%s (\d+)" % key, text)
        return int(match.group(1)) if match else None

    @staticmethod
    def _search_float(text, key):
        match = re.search(r"\b%s (-?[\d.]+)" % key, text)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    # ================================================================== candidates
    def ordered_candidates(self, limit=20):
        ordered = sorted(self.candidates.values(), key=lambda c: c.get("order", 999))
        return ordered[:limit]

    def _emit_candidates(self):
        ordered = self.ordered_candidates()
        if ordered:
            best = max(ordered, key=lambda c: c.get("visits", 0))
            self.winrate = best.get("winrate")
            self.score_lead = best.get("score")
        self._emit("candidates", candidates=ordered,
                   winrate=self.winrate, score=self.score_lead)
        self._candidates_dirty = False
        self._last_candidate_emit = time.time()

    def _emit_board(self):
        moves = []
        for no, color, vertex in self.state.ordered_moves():
            xy = gtp_protocol.vertex_to_xy(vertex, self.state.board_size)
            if xy is None:
                continue
            moves.append({"no": no, "color": color, "vertex": vertex,
                          "x": xy[0], "y": xy[1]})
        self._emit("board",
                   board_size=self.state.board_size,
                   komi=self.state.komi,
                   ai_color=self.state.ai_color,
                   handicap=list(self.state.handicap),
                   moves=moves,
                   last_move=self.state.last_move_no,
                   candidates=self.ordered_candidates(),
                   winrate=self.winrate,
                   score=self.score_lead)

    # ================================================================== watchdog
    def _watchdog_loop(self):
        while True:
            time.sleep(0.5)
            try:
                self._tick()
            except Exception as exc:
                self.logbook.error("看门狗异常: %s" % exc)

    def _tick(self):
        now = time.time()

        # genmove watchdog
        with self._lock:
            pending = self._genmove_pending
            started = self._genmove_started
            tries = self._genmove_tries
        if pending:
            configured = float(self.config.get("genmove_timeout") or 0)
            if configured > 0:
                limit = configured
            else:
                max_time = float(self.config.get("max_time") or 0)
                byo = int(self.state.byo_time or self.state.remaining[1] or 0)
                limit = max(60.0, byo * 2.0 + 20.0, max_time + 30.0)
            if now - started > limit:
                self.logbook.error("genmove 已等待 %.0f 秒，引擎无响应" % (now - started))
                stop = self.dialect.stop_command()
                if stop:
                    self.session.send(stop, "stop")
                with self._lock:
                    self._genmove_pending = False
                self.session.streaming = False
                if tries < 2:
                    with self._lock:
                        self._genmove_pending = True
                        self._genmove_started = now
                        self._genmove_tries = tries + 1
                    self._send_genmove()
                else:
                    self._send_fox("AFSKIP", self._genmove_color)

        # final score watchdog
        with self._lock:
            score_pending = self._score_pending
            score_started = self._score_started
            opponent = self._score_opponent
        if score_pending and now - score_started > self.SCORE_TIMEOUT:
            with self._lock:
                self._score_pending = False
            self.logbook.info("点目超时，按协议回复 error")
            self._send_fox("AFSCORE", opponent, "error")

        # candidate throttle
        if self._candidates_dirty and now - self._last_candidate_emit > 0.1:
            self._emit_candidates()

        # heartbeat
        if self.transport is not None and self.config.get("heartbeat_enabled"):
            interval = max(1, int(self.config.get("heartbeat_interval") or 30))
            timeout = max(1, int(self.config.get("heartbeat_timeout") or 10))
            if now >= self._heartbeat_due:
                self.session.send("protocol_version", "heartbeat")
                self._heartbeat_due = now + interval
                self._heartbeat_sent = now
            elif self._heartbeat_sent and self.session.has_pending("heartbeat"):
                if now - self._heartbeat_sent > timeout:
                    self.logbook.error("心跳超时，AI 引擎无响应，尝试重连")
                    self._heartbeat_sent = 0.0
                    self.stop_engine(intentional=False)
                    if self.config.get("auto_recover", True):
                        self._start_recovery()
        else:
            self._heartbeat_sent = 0.0

    # ================================================================== misc API
    def _request_fox_status(self):
        self._send_fox("AFSTATUS", self.state.ai_color)

    def request_fox_status(self):
        self._request_fox_status()

    def send_shell(self, command, timeout=8.0):
        """Send an arbitrary GTP command (GTP shell). Returns (ok, text)."""
        if self.transport is None:
            return False, "引擎未连接"
        response = self.session.request(command, timeout=timeout,
                                        purpose="raw", multiline=True)
        if response is None:
            return False, "（超时或引擎无响应）"
        return response.ok, response.body

    def send_shell_async(self, command):
        if self.transport is None:
            return False
        self.session.send(command, "raw", multiline=True)
        return True

    def status(self):
        return {
            "engine_connected": self.transport is not None,
            "engine_ready": self._engine_ready,
            "engine_description": self.transport.describe() if self.transport else "未连接",
            "profile": self.profile.as_dict(),
            "fox_listening": self.fox.is_listening(),
            "fox_connected": self.fox.is_connected(),
            "fox_peer": self.fox.last_peer,
            "board_size": self.state.board_size,
            "komi": self.state.komi,
            "ai_color": self.state.ai_color,
            "last_move": self.state.last_move_no,
            "events": len(self.state.events),
            "engine_events": len(self.state.engine_events),
            "game_configured": self._game_configured,
            "genmove_pending": self._genmove_pending,
            "winrate": self.winrate,
            "score_lead": self.score_lead,
        }

    # ================================================================== test mode
    def test_new_game(self, board_size=19, komi=6.5, handicap_count=0,
                      main_time=0, byo_time=0, byo_count=0):
        handicap = []
        if handicap_count:
            from .dialect import _STANDARD_HANDICAP
            handicap = list(_STANDARD_HANDICAP.get(int(handicap_count), []))
            if board_size != 19:
                handicap = []
        with self._lock:
            self.state.board_size = int(board_size)
            self.state.komi = float(komi)
            self.state.main_time = int(main_time)
            self.state.byo_time = int(byo_time)
            self.state.byo_count = int(byo_count)
            self.state.handicap = handicap
            self.state.remaining = (main_time, byo_time, byo_count)
            self.state.reset()
            self._game_configured = True
            self._engine_setup_done = False
            self._sync_times()
            for index, vertex in enumerate(handicap):
                self.state.fox_moves[-index] = ("B", vertex)
        self._sync_engine(force_rebuild=True)
        self._emit_board()
        return True

    def test_play(self, x, y, color):
        if self.transport is None:
            return False
        vertex = gtp_protocol.xy_to_vertex(x, y, self.state.board_size)
        if vertex == "pass":
            return False
        with self._lock:
            no = self.state.last_move_no + 1
            self.state.ingest_move(no, color.upper(), vertex)
        self._sync_engine()
        self._emit_board()
        return True

    def test_pass(self, color):
        with self._lock:
            self.state.ingest_pass(color.upper(), expect_duplicate=False)
        self._sync_engine()
        self._emit_board()
        return True

    def test_genmove(self, color):
        self._start_genmove(color)
        return True

    def test_undo(self):
        command = self.dialect.undo_command()
        if command is None:
            return False
        self.session.send(command, "undo")
        with self._lock:
            if self.state.events:
                self.state.events.pop()
            self.state.mark_dirty()
        self._emit_board()
        return True

    def test_score(self):
        command = self.dialect.final_score_command()
        if command is None or self.transport is None:
            return False, "引擎不支持 final_score"
        with self._lock:
            self._score_pending = True
            self._score_started = time.time()
            self._score_opponent = "0"
        self.session.send(command, "final_score")
        return True, "已请求 final_score"

    def shutdown(self):
        self._stopping = True
        try:
            self.stop_fox()
        except Exception:
            pass
        try:
            self.stop_engine()
        except Exception:
            pass
        self.session.close()
