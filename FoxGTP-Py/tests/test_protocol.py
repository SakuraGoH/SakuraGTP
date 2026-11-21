"""Protocol/parsing unit tests (no threads, no sockets)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from foxgtp import gtp_protocol
from foxgtp.dialect import Dialect, DialectOptions, _STANDARD_HANDICAP
from foxgtp.engine_profile import EngineProfile
from foxgtp.fox_protocol import (build_packet, checksum, format_move, parse_move,
                                 parse_packet, FoxProtocolError)


class FoxPacketTest(unittest.TestCase):
    def test_checksum_is_xor_without_dollar(self):
        packet = build_packet("AFPLAY", "B", "1^3^3^B")
        self.assertTrue(packet.startswith(b"$AFPLAY,B,1^3^3^B*"))
        body = packet[1:packet.index(b"*")]
        declared = int(packet[packet.index(b"*") + 1:][:2], 16)
        self.assertEqual(declared, checksum(body))

    def test_roundtrip(self):
        packet = parse_packet(build_packet("FARULE", 19, 60, 30, 5, 650).decode().strip())
        self.assertEqual(packet.command, "FARULE")
        self.assertEqual(packet.items, ["19", "60", "30", "5", "650"])

    def test_bad_checksum_detected(self):
        with self.assertRaises(FoxProtocolError):
            parse_packet("$AFPLAY,B,1^3^3^B*00")

    def test_missing_checksum_accepted(self):
        packet = parse_packet("$FAMOVE,1,B,1^3^3^W")
        self.assertEqual(packet.command, "FAMOVE")
        self.assertEqual(packet.items[2], "1^3^3^W")

    def test_move_helpers(self):
        self.assertEqual(parse_move("12^3^4^W"), (12, 3, 4, "W"))
        self.assertIsNone(parse_move("0^0^0^N"))
        self.assertIsNone(parse_move("garbage"))
        self.assertEqual(format_move(2, 15, 3, "b"), "2^15^3^B")


class CoordinateTest(unittest.TestCase):
    def test_xy_to_vertex_skips_i(self):
        self.assertEqual(gtp_protocol.xy_to_vertex(0, 18, 19), "A1")
        self.assertEqual(gtp_protocol.xy_to_vertex(8, 18, 19), "J1")
        self.assertEqual(gtp_protocol.xy_to_vertex(15, 3, 19), "Q16")
        self.assertEqual(gtp_protocol.xy_to_vertex(18, 0, 19), "T19")
        self.assertEqual(gtp_protocol.xy_to_vertex(19, 0, 19), "pass")

    def test_vertex_to_xy(self):
        self.assertEqual(gtp_protocol.vertex_to_xy("Q16", 19), (15, 3))
        self.assertEqual(gtp_protocol.vertex_to_xy("j10", 19), (8, 9))
        self.assertIsNone(gtp_protocol.vertex_to_xy("pass", 19))
        self.assertIsNone(gtp_protocol.vertex_to_xy("I5", 19))
        self.assertIsNone(gtp_protocol.vertex_to_xy("K10", 9))

    def test_board_sizes(self):
        self.assertEqual(gtp_protocol.xy_to_vertex(4, 4, 9), "E5")
        self.assertEqual(gtp_protocol.vertex_to_xy("E5", 9), (4, 4))


class KomiTest(unittest.TestCase):
    def test_format(self):
        self.assertEqual(gtp_protocol.format_komi(6.5), "6.5")
        self.assertEqual(gtp_protocol.format_komi(7), "7")
        self.assertEqual(gtp_protocol.format_komi(6.75), "6.75")
        self.assertEqual(gtp_protocol.format_komi(0.5), "0.5")


class ReplyParsingTest(unittest.TestCase):
    def test_move_variants(self):
        cases = {
            "Q16": ("move", "Q16"),
            "play Q16": ("move", "Q16"),
            "Leela: Q16": ("move", "Q16"),
            "pass": ("pass", None),
            "PASS": ("pass", None),
            "resign": ("resign", None),
            "": (None, None),
        }
        for text, expected in cases.items():
            self.assertEqual(gtp_protocol.parse_move_reply(text), expected, text)

    def test_score_variants(self):
        self.assertEqual(gtp_protocol.parse_score_reply("B+3.5"), ("B", 3.5, False))
        winner, points, resign = gtp_protocol.parse_score_reply("W+R")
        self.assertEqual((winner, resign), ("W", True))
        self.assertEqual(gtp_protocol.parse_score_reply("0"), ("D", 0.0, False))
        self.assertEqual(gtp_protocol.parse_score_reply("Draw"), ("D", 0.0, False))
        self.assertEqual(gtp_protocol.parse_score_reply("Black wins by 2.5"),
                         ("B", 2.5, False))
        self.assertIsNone(gtp_protocol.parse_score_reply("")[0])

    def test_fox_score_string(self):
        self.assertEqual(gtp_protocol.fox_score_string("B", 3.5), "B+350")
        self.assertEqual(gtp_protocol.fox_score_string("W", None, True), "W+R")
        self.assertEqual(gtp_protocol.fox_score_string("D", 0.0), "0")
        self.assertEqual(gtp_protocol.fox_score_string(None, None), "error")

    def test_fox_result_text(self):
        self.assertEqual(gtp_protocol.parse_fox_result("W+350"), "白胜 3.50 目")
        self.assertEqual(gtp_protocol.parse_fox_result("B+R"), "黑中盘胜")
        self.assertEqual(gtp_protocol.parse_fox_result("0"), "和棋")


class DialectTest(unittest.TestCase):
    def make(self, mode="katago", **options):
        profile = EngineProfile()
        profile.family = "katago" if mode == "katago" else mode
        if mode == "katago":
            profile.commands = {"kata-genmove_analyze", "kata-set-param",
                                "kata-set-rules", "time_settings", "time_left",
                                "set_free_handicap", "final_score", "undo",
                                "stop", "genmove"}
        elif mode == "gnugo":
            profile.commands = {"time_settings", "time_left", "set_free_handicap",
                                "final_score", "genmove", "fixed_handicap"}
        profile.list_ok = True
        return Dialect(profile, DialectOptions(**options))

    def test_canadian_byoyomi_default(self):
        dialect = self.make()
        dialect.main_time, dialect.byo_time, dialect.byo_count = 60, 30, 5
        self.assertEqual(dialect.time_settings_commands(), ["time_settings 60 30 1"])

    def test_go_byoyomi(self):
        dialect = self.make(use_go_byoyomi=True)
        dialect.main_time, dialect.byo_time, dialect.byo_count = 60, 30, 5
        self.assertEqual(dialect.time_settings_commands(), ["time_settings 60 30 5"])

    def test_data_transfer_time(self):
        dialect = self.make(use_data_transfer_time=True, data_transfer_time=2)
        dialect.byo_time, dialect.byo_count = 30, 3
        self.assertEqual(dialect.time_settings_commands(), ["time_settings 0 28 1"])

    def test_ai_cal_time(self):
        dialect = self.make(use_ai_cal_time=True, ai_cal_time=5)
        dialect.byo_time, dialect.byo_count = 30, 3
        self.assertEqual(dialect.time_settings_commands(), ["time_settings 0 5 1"])

    def test_non_kata_max_time_caps_byo(self):
        dialect = self.make(mode="gnugo", max_time=5)
        dialect.byo_time, dialect.byo_count = 30, 3
        self.assertIn(" 5 1", dialect.time_settings_commands()[0])

    def test_time_left(self):
        dialect = self.make()
        dialect.main_time, dialect.byo_time, dialect.byo_count = 0, 30, 3
        self.assertEqual(dialect.time_left_commands("w"), ["time_left W 0 30"])

    def test_free_handicap(self):
        dialect = self.make()
        self.assertEqual(dialect.handicap_commands(["D16", "Q4", "D4"]),
                         ["set_free_handicap D16 Q4 D4"])

    def test_fixed_handicap_for_standard_points(self):
        dialect = self.make(mode="gnugo", handicap_mode="fixed")
        self.assertEqual(dialect.handicap_commands(_STANDARD_HANDICAP[3]),
                         ["fixed_handicap 3"])

    def test_play_fallback(self):
        dialect = self.make(mode="gnugo")
        dialect.profile.commands.discard("fixed_handicap")
        dialect.profile.commands.discard("set_free_handicap")
        self.assertEqual(dialect.handicap_commands(["D16"]), ["play B D16"])

    def test_genmove_kata_analyze(self):
        dialect = self.make()
        command, mode = dialect.genmove_command("B")
        self.assertEqual(mode, "kata-analyze")
        self.assertTrue(command.startswith("kata-genmove_analyze B"))

    def test_genmove_plain(self):
        dialect = self.make(mode="gnugo")
        self.assertEqual(dialect.genmove_command("B"), ("genmove B", "plain"))

    def test_rules_only_for_kata(self):
        self.assertEqual(self.make().rules_command(), "")
        dialect = self.make(rule="japanese")
        dialect.options.rule = "japanese"
        self.assertEqual(dialect.rules_command(), "kata-set-rules japanese")
        gnugo = self.make(mode="gnugo")
        gnugo.options.rule = "japanese"
        self.assertEqual(gnugo.rules_command(), "")

    def test_setup_order(self):
        dialect = self.make()
        commands = dialect.setup_commands(19, 6.5, [], 60, 30, 5)
        self.assertEqual(commands[0], "clear_board")
        self.assertEqual(commands[1], "boardsize 19")
        self.assertEqual(commands[2], "komi 6.5")
        self.assertIn("time_settings 60 30 1", commands)


if __name__ == "__main__":
    unittest.main(verbosity=2)
