"""兼容性回归测试：不需要真引擎，用 tests/mock_engine.py 模拟各种方言。"""

import os
import sys
import unittest

import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def wait_for(predicate, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False

from sakura.engine.bridge import GTPBridge          # noqa: E402
from mock_engine import MockEngine        # noqa: E402


class FakeEngineManager:
    """把 bridge 发的命令直接喂给 MockEngine，并把输出回灌。"""

    def __init__(self, mock):
        self.mock = mock
        self.running = True
        self.on_output = None
        self.sent = []

    def send(self, text):
        if not self.running:
            return False
        self.sent.append(text)
        for chunk in self.mock.handle_line(text):
            for piece in str(chunk).split("\n"):
                if self.on_output:
                    self.on_output(piece)
        return True

    def is_running(self):
        return self.running


class FoxSink:
    def __init__(self):
        self.packets = []

    def send(self, command, *items):
        self.packets.append((command, tuple(items)))
        return True

    def first(self, command):
        for cmd, items in self.packets:
            if cmd == command:
                return items
        return None

    def all(self, command):
        return [items for cmd, items in self.packets if cmd == command]


def make_bridge(mode="katago", candidate_sink=None, on_restart_engine=None,
                on_heartbeat_dead=None, **kwargs):
    mock = MockEngine(mode=mode)
    for key, value in kwargs.items():
        setattr(mock, key, value)
    mgr = FakeEngineManager(mock)
    sink = FoxSink()
    logs = []
    bridge = GTPBridge(
        engine_manager=mgr,
        send_to_fox=sink.send,
        on_log=logs.append,
        on_candidate=(candidate_sink.append if candidate_sink is not None
                      else (lambda c: None)),
        on_engine_raw=lambda line: None,
        on_restart_engine=on_restart_engine,
        on_heartbeat_dead=on_heartbeat_dead,
    )
    mgr.on_output = bridge.on_engine_output
    bridge.on_engine_started(mode)
    if bridge._probe_thread is not None:
        bridge._probe_thread.join(5.0)
    return bridge, mgr, sink, logs


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.bridge = None

    def tearDown(self):
        if self.bridge is not None:
            self.bridge.session.stop()

    # ------------------------------------------------------------------ 基础
    def test_probe_katago(self):
        bridge, mgr, _sink, _logs = make_bridge("katago")
        self.bridge = bridge
        self.assertEqual(bridge.profile.family, "katago")
        self.assertTrue(bridge.profile.kata_analyze)
        self.assertTrue(bridge.profile.echoes_id)
        self.assertIn("kata-genmove_analyze", bridge.profile.commands)

    def test_probe_leela_no_id(self):
        bridge, _mgr, _sink, _logs = make_bridge("leela")
        self.bridge = bridge
        self.assertEqual(bridge.profile.family, "leela")
        self.assertFalse(bridge.profile.echoes_id)
        self.assertFalse(bridge.profile.kata)
        self.assertFalse(bridge.session.echoes_id)

    # ------------------------------------------------------------------ PhoenixGo
    def test_probe_phoenixgo(self):
        bridge, _mgr, _sink, _logs = make_bridge("phoenixgo")
        self.bridge = bridge
        self.assertEqual(bridge.profile.family, "phoenixgo")
        self.assertFalse(bridge.profile.kata)
        self.assertTrue(bridge.profile.final_score)
        self.assertTrue(bridge.profile.time_settings)

    def test_phoenixgo_hint_with_katago_path_does_not_misfire(self):
        """配置文件名里带 katago 时，不能把 PhoenixGo 误判成 KataGo。"""
        bridge, _mgr, _sink, _logs = make_bridge("phoenixgo")
        self.bridge = bridge
        bridge.on_engine_started(r"C:\PhoenixGo\etc\mcts_onnx_katago.conf")
        bridge._probe_thread.join(5.0)
        self.assertEqual(bridge.profile.family, "phoenixgo")
        self.assertFalse(bridge.profile.kata)

    def test_phoenixgo_only_core_gtp(self):
        bridge, mgr, _sink, _logs = make_bridge("phoenixgo")
        self.bridge = bridge
        bridge.handle_fox_command("FARULE", ["19", "600", "30", "5", "750"])
        moves = ["%d^%d^%d^%s" % (i, (i - 1) // 19, (i - 1) % 19,
                                  "B" if i % 2 else "W") for i in range(1, 11)]
        bridge.handle_fox_command("FASTATUS", ["1", "B"] + moves)
        bridge.handle_fox_command("FAMOVE", ["1", "W", "11^5^5^W"])

        sent = [cmd for _cid, cmd in mgr.mock.received]
        self.assertFalse([c for c in sent if c.startswith("kata-")],
                         "非 KataGo 引擎不能收到 kata-* 命令")
        self.assertTrue([c for c in sent if c.startswith("genmove")])
        self.assertTrue(any(c == "komi 7.5" for c in sent))

    def test_phoenixgo_komi_rejection_is_logged(self):
        bridge, _mgr, _sink, logs = make_bridge("phoenixgo")
        self.bridge = bridge
        bridge.handle_fox_command("FARULE", ["19", "600", "30", "5", "650"])
        self.assertTrue(any("贴目" in m and "7.5" in m for m in logs),
                        "引擎拒绝贴目时应给出明确提示")

    def test_phoenixgo_final_score(self):
        bridge, _mgr, sink, _logs = make_bridge("phoenixgo")
        self.bridge = bridge
        bridge.handle_fox_command("FARULE", ["19", "600", "30", "5", "750"])
        bridge.handle_fox_command("FASCORE", ["0"])
        self.assertTrue(wait_for(lambda: sink.first("AFSCORE") is not None, 3))
        self.assertEqual(sink.first("AFSCORE"), ("0", "W+50"))

    # ------------------------------------------------------------------ 开局设置
    def test_farule_setup(self):
        bridge, mgr, _sink, _logs = make_bridge("katago")
        self.bridge = bridge
        bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])

        cmds = mgr.mock.received
        names = [c.split(" ")[0] for _i, c in cmds]
        self.assertIn("clear_board", names)
        self.assertIn("boardsize", names)
        self.assertIn("komi", names)
        self.assertIn("time_settings", names)

        self.assertIn("boardsize 19", [c for _i, c in cmds])
        self.assertIn("komi 6.5", [c for _i, c in cmds])
        # 默认读秒口径：加拿大读秒 → 每周期 1 子
        self.assertTrue(any(c.startswith("time_settings 60 30 1") for _i, c in cmds),
                        "time_settings 应为 '60 30 1'，实际 %r" % cmds)

    def test_komi_precision(self):
        bridge, mgr, _sink, _logs = make_bridge("katago")
        self.bridge = bridge
        bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "675"])
        cmds = [c for _i, c in mgr.mock.received]
        self.assertIn("komi 6.75", cmds, "贴目不能像 FoxGTP 那样被 %.1f 截断")

    def test_go_byoyomi_option(self):
        bridge, mgr, _sink, _logs = make_bridge("katago")
        self.bridge = bridge
        bridge.set_time_options(use_go_byoyomi=True)
        bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])
        cmds = [c for _i, c in mgr.mock.received]
        self.assertTrue(any(c.startswith("time_settings 60 30 5") for c in cmds),
                        "常用读秒规则下 s 应为次数 5，实际 %r" % cmds)

    def test_handicap_and_status_drops_handicap_stones(self):
        bridge, mgr, _sink, _logs = make_bridge("katago")
        self.bridge = bridge
        bridge.handle_fox_command(
            "FARULE", ["19", "60", "30", "5", "650",
                       "0^3^3^B", "0^15^15^B", "0^3^15^B"])
        cmds = [c for _i, c in mgr.mock.received]
        self.assertIn("set_free_handicap D16 Q4 D4", cmds)

        mgr.mock.clear()
        bridge.handle_fox_command(
            "FASTATUS", ["1", "B",
                         "1^3^3^B", "2^15^15^B", "3^3^15^B",
                         "4^9^9^W"])
        plays = mgr.mock.plays()
        self.assertEqual(plays, ["play W K10"],
                         "让子已由 set_free_handicap 下过，不能再 play 一遍：%r" % plays)

    # ------------------------------------------------------------------ 行棋
    def test_opponent_move_then_genmove(self):
        bridge, mgr, sink, _logs = make_bridge("katago")
        self.bridge = bridge
        bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])
        mgr.mock.clear()

        bridge.handle_fox_command("FAMOVE", ["1", "B", "1^3^3^W"])
        self.assertEqual(mgr.mock.plays(), ["play W D16"])
        self.assertTrue(mgr.mock.commands_named("kata-genmove_analyze"))

        played = sink.first("AFPLAY")
        self.assertIsNotNone(played, "应给野狐回 AFPLAY")
        self.assertEqual(played[0], "B")
        self.assertEqual(played[1], "2^15^3^B")

    def test_candidates_cleared_when_opponent_to_move(self):
        """对手回合不能在棋盘上留下 AI 的候选点。"""
        seen = []
        bridge, _mgr, _sink, _logs = make_bridge("katago", candidate_sink=seen)
        self.bridge = bridge

        bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])
        bridge.handle_fox_command("FAMOVE", ["1", "B", "1^3^3^W"])
        # AI 落子完成后：内部候选表清空，并且通知了界面
        self.assertEqual(bridge._candidates, {})
        self.assertEqual(seen[-1], [])

        # 模拟一次「落子后仍有残余分析数据」的竞态，再让对手落子
        bridge._candidates = {"Q16": {"move": (15, 3), "vertex": "Q16"}}
        bridge._candidates_dirty = True
        bridge.handle_fox_command("FAMOVE", ["0", "B", "2^15^3^B"])
        self.assertEqual(bridge._candidates, {}, "对手回合必须清空候选点")
        self.assertEqual(seen[-1], [], "对手回合必须通知界面撤掉候选点")

    def test_echoed_own_move_not_replayed(self):
        bridge, mgr, sink, _logs = make_bridge("katago")
        self.bridge = bridge
        bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])
        bridge.handle_fox_command("FAMOVE", ["1", "B", "1^3^3^W"])
        mgr.mock.clear()
        # 野狐回显 AI 自己刚下的那手
        bridge.handle_fox_command("FAMOVE", ["0", "B", "2^15^3^B"])
        self.assertEqual(mgr.mock.plays(), [], "自己下的手不能被重复 play")
        self.assertEqual(bridge.last_move_number, 2)

    def test_pass_result(self):
        bridge, mgr, sink, _logs = make_bridge("katago")
        self.bridge = bridge
        mgr.mock.next_move = {"B": "pass", "W": "pass"}
        bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])
        bridge.handle_fox_command("FAMOVE", ["1", "B", "1^3^3^W"])
        self.assertEqual(sink.first("AFSKIP"), ("B",))

    def test_resign_result(self):
        bridge, mgr, sink, _logs = make_bridge("katago")
        self.bridge = bridge
        mgr.mock.next_move = {"B": "resign", "W": "resign"}
        bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])
        bridge.handle_fox_command("FAMOVE", ["1", "B", "1^3^3^W"])
        self.assertEqual(sink.first("AFGIVEUP"), ("B",))

    def test_long_game_sequence(self):
        """连续多手：引擎收到的 play 序列必须与野狐棋谱逐手一致，且不重建。"""
        bridge, mgr, sink, logs = make_bridge("katago")
        self.bridge = bridge
        bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])
        clear_after_setup = mgr.mock.clear_count

        expected = []
        n = 0
        for i in range(5):
            # 轮到 AI：对手这一手必须同步给引擎
            mgr.mock.next_move = {"B": bridge._xy_to_gtp(10 + i, 10), "W": "pass"}
            n += 1
            x, y = 2 * i, 3
            vertex = bridge._xy_to_gtp(x, y)
            bridge.handle_fox_command("FAMOVE", ["1", "B", "%d^%d^%d^W" % (n, x, y)])
            expected.append("play W " + vertex)
            self.assertTrue(sink.all("AFPLAY"), "AI 应落子（第 %d 手）" % n)

            # 野狐回显 AI 的落子（轮到对手）：不能重复 play
            n += 1
            ai_move = sink.all("AFPLAY")[-1][1]
            _an, ax, ay, _ac = ai_move.split("^")
            bridge.handle_fox_command("FAMOVE", ["0", "B", ai_move])

        self.assertEqual(mgr.mock.plays(), expected)
        self.assertEqual(mgr.mock.clear_count, clear_after_setup,
                         "正常连续行棋不应重建棋盘")
        self.assertEqual(len(bridge._events), 10)
        self.assertEqual(bridge._events, bridge._engine_events)

    # ------------------------------------------------------------------ 方言差异
    def test_leela_prefix_and_no_id(self):
        bridge, mgr, sink, _logs = make_bridge("leela")
        self.bridge = bridge
        mgr.mock.prefix = "Leela: "
        bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])
        bridge.handle_fox_command("FAMOVE", ["1", "B", "1^3^3^W"])
        played = sink.first("AFPLAY")
        self.assertIsNotNone(played, "Leela 前缀 + 无 id 也要能落子")
        self.assertEqual(played[1], "2^15^3^B")

    def test_genmove_fallback_when_kata_command_rejected(self):
        bridge, mgr, sink, _logs = make_bridge("katago")
        self.bridge = bridge
        mgr.mock.reject.add("kata-genmove_analyze")
        bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])
        bridge.handle_fox_command("FAMOVE", ["1", "B", "1^3^3^W"])
        self.assertTrue(mgr.mock.commands_named("genmove"),
                        "kata-genmove_analyze 报错后必须退回 genmove")
        self.assertIsNotNone(sink.first("AFPLAY"))

    def test_genmove_double_failure_passes(self):
        bridge, mgr, sink, logs = make_bridge("gnugo")
        self.bridge = bridge
        mgr.mock.reject.add("genmove")
        bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])
        bridge.handle_fox_command("FAMOVE", ["1", "B", "1^3^3^W"])
        self.assertEqual(sink.first("AFSKIP"), ("B",),
                         "两次失败必须停一手，不能把野狐挂死")

    def test_gnugo_final_score(self):
        bridge, mgr, sink, _logs = make_bridge("gnugo")
        self.bridge = bridge
        bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])
        mgr.mock.score_result = "B+3.5"
        bridge.handle_fox_command("FASCORE", ["0"])
        self.assertEqual(sink.first("AFSCORE"), ("0", "B+350"))

    def test_final_score_unsupported_returns_error(self):
        bridge, _mgr, sink, _logs = make_bridge("leela")
        self.bridge = bridge
        bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])
        bridge.handle_fox_command("FASCORE", ["1"])
        self.assertEqual(sink.first("AFSCORE"), ("1", "error"))

    # ------------------------------------------------------------------ 断线重连
    def test_resync_rebuild_on_divergence(self):
        bridge, mgr, sink, _logs = make_bridge("katago")
        self.bridge = bridge
        bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])
        bridge.handle_fox_command("FAMOVE", ["0", "B", "1^3^3^W"])
        bridge.handle_fox_command("FAMOVE", ["1", "B", "2^15^3^B"])
        before = mgr.mock.clear_count

        # 野狐重连后给出一份「前几手不一样」的棋谱
        bridge.handle_fox_command(
            "FASTATUS", ["1", "B", "1^15^15^W", "2^3^3^B"])
        self.assertGreater(mgr.mock.clear_count, before, "棋谱对不上必须 clear_board 重建")
        self.assertIn("play W Q4", mgr.mock.plays())
        self.assertIn("play B D16", mgr.mock.plays())

    def test_resync_appends_only_difference(self):
        bridge, mgr, sink, _logs = make_bridge("katago")
        self.bridge = bridge
        bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])
        bridge.handle_fox_command("FAMOVE", ["0", "B", "1^3^3^W"])
        clear_before = mgr.mock.clear_count
        mgr.mock.clear()

        # 同一局面 + 多两手：只补落子，不应重开棋盘
        bridge.handle_fox_command(
            "FASTATUS", ["1", "B", "1^3^3^W", "2^15^3^B", "3^15^15^W"])
        self.assertEqual(mgr.mock.clear_count, clear_before)
        self.assertEqual(mgr.mock.plays(), ["play B Q16", "play W Q4"])

    def test_no_undo_needed(self):
        bridge, mgr, _sink, _logs = make_bridge("katago")
        self.bridge = bridge
        bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])
        bridge.handle_fox_command("FAMOVE", ["0", "B", "1^3^3^W"])
        bridge.handle_fox_command("FASTATUS", ["1", "B", "1^15^15^W"])
        self.assertEqual(mgr.mock.undo_count, 0, "恢复局面不应依赖 undo")

    # ------------------------------------------------------------------ 棋盘尺寸
    def test_9x9_coordinates(self):
        bridge, mgr, sink, _logs = make_bridge("katago")
        self.bridge = bridge
        mgr.mock.next_move = {"B": "E5", "W": "C3"}
        bridge.handle_fox_command("FARULE", ["9", "60", "30", "5", "650"])
        self.assertIn("boardsize 9", [c for _i, c in mgr.mock.received])

        bridge.handle_fox_command("FAMOVE", ["1", "B", "1^4^4^W"])
        self.assertIn("play W E5", mgr.mock.plays())
        self.assertEqual(sink.first("AFPLAY"), ("B", "2^4^4^B"))
        self.assertEqual(bridge._gtp_to_xy("E5"), (4, 4))

    # ------------------------------------------------------------------ 分析
    def test_analyze_candidates_parsed(self):
        bridge, _mgr, _sink, _logs = make_bridge("katago")
        self.bridge = bridge
        # 直接喂一行 KataGo 的 info 数据，验证解析
        bridge._parse_info(
            "info move Q16 visits 120 winrate 0.61 scoreLead 2.4 order 0 pv Q16")
        cand = bridge._candidates["Q16"]
        self.assertAlmostEqual(cand["winrate"], 0.61, places=2)
        self.assertEqual(cand["visits"], 120)
        self.assertEqual(cand["move"], (15, 3))

    def test_lz_winrate_scaled(self):
        bridge, _mgr, _sink, _logs = make_bridge("katago")
        self.bridge = bridge
        bridge._parse_info("info move Q16 visits 10 winrate 5500 scoreMean -1.2")
        self.assertAlmostEqual(bridge._candidates["Q16"]["winrate"], 0.55, places=2)

    # ------------------------------------------------------------------ 规则
    def test_rules_only_for_katago(self):
        bridge, mgr, _sink, logs = make_bridge("gnugo")
        self.bridge = bridge
        bridge.set_rules("chinese")
        self.assertFalse(mgr.mock.commands_named("kata-set-rules"))
        self.assertTrue(any("不支持规则切换" in m for m in logs))

    def test_rules_sent_for_katago(self):
        bridge, mgr, _sink, _logs = make_bridge("katago")
        self.bridge = bridge
        bridge.set_rules("japanese")
        self.assertTrue(mgr.mock.commands_named("kata-set-rules"))

    # ------------------------------------------------------------------ 重连重放
    def test_large_replay_sent_immediately(self):
        """断线重连补 120 手：直接全部入队，不等回执、不阻塞 Fox 线程。"""
        bridge, mgr, _sink, logs = make_bridge("katago")
        self.bridge = bridge
        bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])
        moves = ["%d^%d^%d^%s" % (i, i % 19, (i * 7) % 19, "B" if i % 2 else "W")
                 for i in range(1, 121)]

        t0 = time.time()
        bridge.handle_fox_command("FASTATUS", ["1", "B"] + moves)
        elapsed = time.time() - t0

        self.assertLess(elapsed, 1.0, "重放必须在 Fox 线程里瞬间完成")
        self.assertEqual(len(mgr.mock.plays()), 120)
        self.assertEqual(bridge._engine_events, bridge._events)
        self.assertFalse(bridge._dirty_engine)

    def test_genmove_follows_replay_immediately(self):
        """补子后立刻发 genmove，且顺序在所有 play 之后。"""
        bridge, mgr, _sink, _logs = make_bridge("katago")
        self.bridge = bridge
        bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])
        moves = ["%d^%d^%d^%s" % (i, i % 19, (i * 7) % 19, "B" if i % 2 else "W")
                 for i in range(1, 41)]
        bridge.handle_fox_command("FASTATUS", ["1", "B"] + moves)
        # 轮到 AI 走第 41 手
        bridge.handle_fox_command("FAMOVE", ["1", "W", "41^5^5^W"])

        received = [cmd for _cid, cmd in mgr.mock.received]
        play_idx = [i for i, c in enumerate(received) if c.startswith("play ")]
        gen_idx = [i for i, c in enumerate(received)
                   if "genmove" in c.split(" ")[0] or "genmove_analyze" in c]
        self.assertTrue(gen_idx, "应立刻发出 genmove")
        self.assertGreater(min(gen_idx), max(play_idx),
                           "genmove 必须排在所有补子之后")

    def test_engine_stopped_is_safe(self):
        """停引擎时清理状态不能抛异常（曾因调用已删除方法把整个界面 abort 掉）。"""
        bridge, _mgr, _sink, _logs = make_bridge("katago")
        self.bridge = bridge
        bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])
        bridge.on_engine_stopped()
        self.assertFalse(bridge._ready)
        self.assertEqual(bridge._engine_events, [])

    def test_restart_after_game_invokes_callback(self):
        calls = []
        bridge, _mgr, _sink, logs = make_bridge(
            "katago", on_restart_engine=lambda: calls.append(True))
        self.bridge = bridge
        bridge.set_restart_after_game(True)
        bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])
        bridge.handle_fox_command("FARESULT", ["W+350"])
        self.assertTrue(wait_for(lambda: calls, 5), "对局结束后应请求重启引擎")

    def test_restart_after_game_disabled_does_nothing(self):
        calls = []
        bridge, _mgr, _sink, _logs = make_bridge(
            "katago", on_restart_engine=lambda: calls.append(True))
        self.bridge = bridge
        bridge.set_restart_after_game(False)
        bridge.handle_fox_command("FARULE", ["19", "60", "30", "5", "650"])
        bridge.handle_fox_command("FARESULT", ["W+350"])
        time.sleep(1.2)
        self.assertEqual(calls, [])


class EngineWriteQueueTest(unittest.TestCase):
    """send() 必须立即返回：真正写管道在后台线程完成。

    断线重连时 FoxGTP 式的一次性补几百手，靠的就是这一点不会卡住 Fox 线程。
    """

    def test_send_never_blocks_on_full_pipe(self):
        from sakura.engine.manager import EngineManager

        class SlowStdin:
            def write(self, _data):
                time.sleep(0.02)

            def flush(self):
                pass

        class DummyProc:
            stdin = SlowStdin()

            def poll(self):
                return None

        manager = EngineManager()
        manager.proc = DummyProc()
        manager._running = True
        manager._start_writer()
        try:
            start = time.time()
            for i in range(100):
                manager.send("play B Q%d" % (i % 19))
            elapsed = time.time() - start
            self.assertLess(elapsed, 0.5, "send() 不能等管道，必须毫秒级返回")
        finally:
            manager._drain_writes()
            manager._write_queue.put(None)
            manager._running = False
            if manager._writer_thread is not None:
                manager._writer_thread.join(1.0)


class HeartbeatTest(unittest.TestCase):
    """心跳统一在桥接层：一套 protocol_version，不再和引擎层各发一套。"""

    def tearDown(self):
        if getattr(self, "bridge", None) is not None:
            self.bridge.set_heartbeat(False)
            self.bridge.session.stop()

    def test_heartbeat_alive_engine_no_false_alarm(self):
        calls = []
        bridge, _mgr, _sink, _logs = make_bridge(
            "katago", on_heartbeat_dead=lambda: calls.append(True))
        self.bridge = bridge
        bridge.set_heartbeat(True, 1, 1)
        time.sleep(2.6)
        self.assertEqual(calls, [], "引擎有响应时不能误判假死")

    def test_heartbeat_dead_engine_fires_callback(self):
        calls = []

        class SilentEngine:
            def __init__(self):
                self.running = True

            def send(self, _text):
                return True

            def is_running(self):
                return True

        bridge = GTPBridge(SilentEngine(), send_to_fox=lambda *a: True,
                           on_log=lambda _m: None,
                           on_heartbeat_dead=lambda: calls.append(True))
        self.bridge = bridge
        bridge.set_heartbeat(True, 1, 1)
        self.assertTrue(wait_for(lambda: calls, 6), "无响应时应触发假死回调")


class ParseTest(unittest.TestCase):
    """纯解析单元测试（不起引擎）。"""

    def setUp(self):
        from sakura.engine.dialect import Dialect, EngineProfile
        prof = EngineProfile()
        self.dialect = Dialect(prof)

    def test_parse_genmove_variants(self):
        d = self.dialect
        self.assertEqual(d.parse_genmove("Q16"), ("move", "Q16"))
        self.assertEqual(d.parse_genmove("play Q16"), ("move", "Q16"))
        self.assertEqual(d.parse_genmove("= Q16"), ("move", "Q16"))
        self.assertEqual(d.parse_genmove("Leela: q4"), ("move", "Q4"))
        self.assertEqual(d.parse_genmove("pass"), ("pass", None))
        self.assertEqual(d.parse_genmove("PASS"), ("pass", None))
        self.assertEqual(d.parse_genmove("resign"), ("resign", None))
        self.assertEqual(d.parse_genmove(""), (None, None))

    def test_parse_score_variants(self):
        d = self.dialect
        self.assertEqual(d.parse_score("B+3.5"), "B+350")
        self.assertEqual(d.parse_score("W+R"), "W+R")
        self.assertEqual(d.parse_score("W+resign"), "W+R")
        self.assertEqual(d.parse_score("0"), "0")
        self.assertEqual(d.parse_score("Draw"), "0")
        self.assertEqual(d.parse_score("Black wins by 2.5"), "B+250")
        self.assertEqual(d.parse_score(""), "error")

    def test_komi_format(self):
        from sakura.engine.dialect import Dialect
        self.assertEqual(Dialect.format_komi(6.5), "6.5")
        self.assertEqual(Dialect.format_komi(7), "7")
        self.assertEqual(Dialect.format_komi(6.75), "6.75")
        self.assertEqual(Dialect.format_komi(0.5), "0.5")


if __name__ == "__main__":
    unittest.main(verbosity=2)
