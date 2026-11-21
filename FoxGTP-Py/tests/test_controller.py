"""End-to-end controller tests: Wild Fox packets in, GTP out, AF* packets back."""

import copy
import os
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from foxgtp.config import DEFAULT_CONFIG
from foxgtp.controller import Controller
from foxgtp.fox_protocol import build_packet, parse_packet
from mock_engine import MockEngine, MockTransport


class FakeFox:
    def __init__(self):
        self.packets = []
        self.connected = True
        self.listening = True
        self.last_peer = "test:1"

    def is_connected(self):
        return self.connected

    def is_listening(self):
        return self.listening

    def send(self, command, *items):
        self.packets.append((command, tuple(items)))
        return True

    def start(self, host="0.0.0.0", port=6000):
        self.listening = True
        return True, "ok"

    def stop(self):
        self.listening = False

    def all(self, command):
        return [items for name, items in self.packets if name == command]

    def first(self, command):
        items = self.all(command)
        return items[0] if items else None


def wait_for(predicate, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class ControllerTest(unittest.TestCase):
    def make(self, mode="katago", **overrides):
        engine = MockEngine(mode)
        transport = MockTransport(engine)
        config = copy.deepcopy(DEFAULT_CONFIG)
        config.update({"engine_ready_timeout": 5, "save_log": False,
                       "heartbeat_enabled": False, "auto_recover": False})
        config.update(overrides)
        events = []
        controller = Controller(config, listener=lambda topic, data: events.append((topic, data)))
        controller.fox = FakeFox()
        with mock.patch("foxgtp.controller.build_transport", return_value=transport):
            ok, message = controller.start_engine()
        self.assertTrue(ok, message)
        self.assertTrue(wait_for(lambda: controller._engine_ready), "probe did not finish")
        return controller, engine, transport, events, config

    def tearDown(self):
        controller = getattr(self, "controller", None)
        if controller is not None:
            controller._stopping = True
            try:
                controller.stop_engine()
            except Exception:
                pass
            controller.session.close()

    def fox(self, controller, command, *items):
        packet = parse_packet(build_packet(command, *items).decode().strip())
        controller._on_fox_packet(packet)

    # ------------------------------------------------------------------ setup
    def test_probe_and_setup(self):
        controller, engine, transport, _events, _cfg = self.make("katago")
        self.controller = controller
        self.assertEqual(controller.profile.family, "katago")
        self.assertTrue(controller.profile.kata_analyze)
        self.assertTrue(controller.profile.echoes_id)

        self.fox(controller, "FARULE", 19, 60, 30, 5, 650)
        commands = [command for _cid, command in engine.received]
        self.assertIn("clear_board", commands)
        self.assertIn("boardsize 19", commands)
        self.assertIn("komi 6.5", commands)
        self.assertIn("time_settings 60 30 1", commands)

    def test_komi_precision(self):
        controller, engine, _transport, _events, _cfg = self.make("katago")
        self.controller = controller
        self.fox(controller, "FARULE", 19, 60, 30, 5, 675)
        commands = [command for _cid, command in engine.received]
        self.assertIn("komi 6.75", commands)

    # ------------------------------------------------------------------ moves
    def test_opponent_move_then_genmove(self):
        controller, engine, _transport, _events, _cfg = self.make("katago")
        self.controller = controller
        self.fox(controller, "FARULE", 19, 60, 30, 5, 650)
        engine.clear()

        self.fox(controller, "FAMOVE", 1, "B", "1^3^3^W")
        self.assertEqual(engine.plays(), ["play W D16"])
        self.assertTrue(engine.commands_named("kata-genmove_analyze"))
        self.assertEqual(controller.fox.first("AFPLAY"), ("B", "2^15^3^B"))

    def test_echo_of_ai_move_is_not_replayed(self):
        controller, engine, _transport, _events, _cfg = self.make("katago")
        self.controller = controller
        self.fox(controller, "FARULE", 19, 60, 30, 5, 650)
        self.fox(controller, "FAMOVE", 1, "B", "1^3^3^W")
        engine.clear()
        self.fox(controller, "FAMOVE", 0, "B", "2^15^3^B")
        self.assertEqual(engine.plays(), [])
        self.assertEqual(controller.state.last_move_no, 2)

    def test_ai_pass_sends_afskip(self):
        controller, engine, _transport, _events, _cfg = self.make("katago")
        self.controller = controller
        engine.next_move = {"B": "pass", "W": "pass"}
        self.fox(controller, "FARULE", 19, 60, 30, 5, 650)
        self.fox(controller, "FAMOVE", 1, "B", "1^3^3^W")
        self.assertEqual(controller.fox.first("AFSKIP"), ("B",))

    def test_ai_resign_sends_afgiveup(self):
        controller, engine, _transport, _events, _cfg = self.make("katago")
        self.controller = controller
        engine.next_move = {"B": "resign", "W": "resign"}
        self.fox(controller, "FARULE", 19, 60, 30, 5, 650)
        self.fox(controller, "FAMOVE", 1, "B", "1^3^3^W")
        self.assertEqual(controller.fox.first("AFGIVEUP"), ("B",))

    def test_opponent_pass_is_synced(self):
        controller, engine, _transport, _events, _cfg = self.make("katago")
        self.controller = controller
        self.fox(controller, "FARULE", 19, 60, 30, 5, 650)
        engine.clear()
        self.fox(controller, "FASKIP", 1, "B")
        self.assertIn("play W pass", engine.plays())
        self.assertEqual(controller.fox.first("AFPLAY"), ("B", "1^15^3^B"))

    # ------------------------------------------------------------------ score
    def test_final_score(self):
        controller, engine, _transport, _events, _cfg = self.make("katago")
        self.controller = controller
        engine.score_result = "B+3.5"
        self.fox(controller, "FARULE", 19, 60, 30, 5, 650)
        self.fox(controller, "FASCORE", 0)
        self.assertEqual(controller.fox.first("AFSCORE"), ("0", "B+350"))

    def test_final_score_unsupported(self):
        controller, _engine, _transport, _events, _cfg = self.make("leela")
        self.controller = controller
        self.fox(controller, "FARULE", 19, 60, 30, 5, 650)
        self.fox(controller, "FASCORE", 1)
        self.assertEqual(controller.fox.first("AFSCORE"), ("1", "error"))

    # ------------------------------------------------------------------ dialects
    def test_leela_without_ids_and_with_prefix(self):
        controller, engine, _transport, _events, _cfg = self.make("leela")
        self.controller = controller
        self.assertFalse(controller.profile.echoes_id)
        engine.prefix = "Leela: "
        self.fox(controller, "FARULE", 19, 60, 30, 5, 650)
        self.fox(controller, "FAMOVE", 1, "B", "1^3^3^W")
        self.assertEqual(controller.fox.first("AFPLAY"), ("B", "2^15^3^B"))
        self.assertEqual(engine.commands_named("kata-genmove-analyze"), [])

    def test_kata_command_rejected_falls_back(self):
        controller, engine, _transport, _events, _cfg = self.make("katago")
        self.controller = controller
        engine.reject.add("kata-genmove_analyze")
        self.fox(controller, "FARULE", 19, 60, 30, 5, 650)
        self.fox(controller, "FAMOVE", 1, "B", "1^3^3^W")
        self.assertTrue(engine.commands_named("genmove"))
        self.assertIsNotNone(controller.fox.first("AFPLAY"))

    # ------------------------------------------------------------------ resync
    def test_fastatus_appends_only_difference(self):
        controller, engine, _transport, _events, _cfg = self.make("katago")
        self.controller = controller
        self.fox(controller, "FARULE", 19, 60, 30, 5, 650)
        self.fox(controller, "FAMOVE", 0, "B", "1^3^3^W")
        clear_before = len(engine.commands_named("clear_board"))
        engine.clear()

        self.fox(controller, "FASTATUS", 1, "B",
                 "1^3^3^W", "2^15^3^B", "3^15^15^W")
        self.assertEqual(len(engine.commands_named("clear_board")), 0,
                         "同一局面不应重建")
        self.assertEqual(engine.plays(), ["play B Q16", "play W Q4"])
        del clear_before

    def test_fastatus_divergence_rebuilds(self):
        controller, engine, _transport, _events, _cfg = self.make("katago")
        self.controller = controller
        self.fox(controller, "FARULE", 19, 60, 30, 5, 650)
        self.fox(controller, "FAMOVE", 0, "B", "1^3^3^W")
        clear_before = len(engine.commands_named("clear_board"))
        engine.clear()

        self.fox(controller, "FASTATUS", 1, "B", "1^15^15^W", "2^3^3^B")
        self.assertGreater(len(engine.commands_named("clear_board")), 0,
                           "棋谱对不上必须重建")
        self.assertIn("play W Q4", engine.plays())
        self.assertIn("play B D16", engine.plays())
        del clear_before

    def test_move_gap_requests_status(self):
        controller, _engine, _transport, _events, _cfg = self.make("katago")
        self.controller = controller
        self.fox(controller, "FARULE", 19, 60, 30, 5, 650)
        self.fox(controller, "FAMOVE", 0, "B", "5^3^3^W")
        self.assertIsNotNone(controller.fox.first("AFSTATUS"))

    # ------------------------------------------------------------------ handicap / board
    def test_handicap_setup_and_status(self):
        controller, engine, _transport, _events, _cfg = self.make("katago")
        self.controller = controller
        self.fox(controller, "FARULE", 19, 60, 30, 5, 650,
                 "0^3^3^B", "0^15^15^B", "0^3^15^B")
        commands = [command for _cid, command in engine.received]
        self.assertIn("set_free_handicap D16 Q4 D4", commands)

        engine.clear()
        self.fox(controller, "FASTATUS", 1, "B",
                 "1^3^3^B", "2^15^15^B", "3^3^15^B", "4^9^9^W")
        self.assertEqual(engine.plays(), ["play W K10"],
                         "让子不能重复 play: %r" % engine.plays())

    def test_9x9_coordinates(self):
        controller, engine, _transport, _events, _cfg = self.make("katago")
        self.controller = controller
        engine.next_move = {"B": "E5", "W": "C3"}
        self.fox(controller, "FARULE", 9, 60, 30, 5, 650)
        commands = [command for _cid, command in engine.received]
        self.assertIn("boardsize 9", commands)

        self.fox(controller, "FAMOVE", 1, "B", "1^4^4^W")
        self.assertIn("play W E5", engine.plays())
        self.assertEqual(controller.fox.first("AFPLAY"), ("B", "2^4^4^B"))

    # ------------------------------------------------------------------ misc
    def test_analysis_candidates(self):
        controller, _engine, _transport, _events, _cfg = self.make("katago")
        self.controller = controller
        self.fox(controller, "FARULE", 19, 60, 30, 5, 650)
        self.fox(controller, "FAMOVE", 1, "B", "1^3^3^W")
        self.assertIn("Q16", controller.candidates)
        self.assertAlmostEqual(controller.candidates["Q16"]["winrate"], 0.61, places=2)
        self.assertEqual(controller.candidates["Q16"]["visits"], 120)

    def test_shell(self):
        controller, _engine, _transport, _events, _cfg = self.make("katago")
        self.controller = controller
        ok, text = controller.send_shell("version")
        self.assertTrue(ok)
        self.assertIn("1.13.0", text)

    def test_test_mode(self):
        controller, engine, _transport, _events, _cfg = self.make("katago")
        self.controller = controller
        controller.test_new_game(19, 6.5, 0)
        self.assertIn("boardsize 19", [c for _i, c in engine.received])
        engine.next_move = {"B": "Q16"}
        controller.test_genmove("B")
        self.assertEqual(controller.fox.first("AFPLAY"), ("B", "1^15^3^B"))
        controller.test_play(3, 3, "W")
        self.assertIn("play W D16", engine.plays())

    def test_result_clears_engine(self):
        controller, engine, _transport, _events, _cfg = self.make("katago")
        self.controller = controller
        self.fox(controller, "FARULE", 19, 60, 30, 5, 650)
        engine.clear()
        self.fox(controller, "FARESULT", "W+350")
        self.assertIn("clear_board", [c for _i, c in engine.received])
        self.assertEqual(controller.state.last_move_no, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
