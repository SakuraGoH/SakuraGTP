"""Move-list and re-sync planning tests."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from foxgtp.game_state import GameState, PASS, plan_sync


class PlanTest(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(plan_sync(["a"], ["a"]).kind, "none")

    def test_append(self):
        plan = plan_sync([("W", "D16")], [("W", "D16"), ("B", "Q16")])
        self.assertEqual(plan.kind, "append")
        self.assertEqual(plan.events, [("B", "Q16")])

    def test_divergence_rebuilds(self):
        plan = plan_sync([("W", "D16")], [("W", "Q4")])
        self.assertEqual(plan.kind, "rebuild")
        self.assertEqual(plan.events, [("W", "Q4")])

    def test_engine_longer_rebuilds(self):
        plan = plan_sync([("W", "D16"), ("B", "Q16")], [("W", "D16")])
        self.assertEqual(plan.kind, "rebuild")

    def test_dirty_forces_rebuild(self):
        plan = plan_sync([("W", "D16")], [("W", "D16")], dirty=True)
        self.assertEqual(plan.kind, "rebuild")

    def test_empty_both(self):
        self.assertEqual(plan_sync([], []).kind, "none")


class GameStateTest(unittest.TestCase):
    def setUp(self):
        self.state = GameState()
        self.state.board_size = 19
        self.state.handicap = []

    def test_ingest_and_turn(self):
        self.assertEqual(self.state.turn_color(), "B")
        self.assertEqual(self.state.ingest_move(1, "B", "Q16"), "new")
        self.assertEqual(self.state.turn_color(), "W")
        self.assertEqual(self.state.last_move_no, 1)

    def test_echo_of_own_move_is_ignored(self):
        self.state.accept_engine_move("B", "Q16")
        self.assertEqual(self.state.ingest_move(1, "B", "Q16"), "echo")
        self.assertEqual(len(self.state.events), 1)
        self.assertEqual(self.state.engine_events, [("B", "Q16")])

    def test_duplicate_notification(self):
        self.state.ingest_move(1, "B", "Q16")
        self.state.ingest_move(2, "W", "D4")
        self.assertEqual(self.state.ingest_move(1, "B", "Q16"), "duplicate")

    def test_gap_marks_dirty(self):
        self.state.ingest_move(1, "B", "Q16")
        self.assertEqual(self.state.ingest_move(3, "W", "D4"), "gap")
        self.assertTrue(self.state.dirty)
        self.assertTrue(self.state.needs_status)

    def test_pass_recorded(self):
        self.state.ingest_move(1, "B", "Q16")
        self.assertTrue(self.state.ingest_pass("W"))
        self.assertFalse(self.state.ingest_pass("W"))     # duplicate guard
        self.assertEqual(self.state.events[-1], ("W", PASS))

    def test_load_status_strips_handicap(self):
        state = GameState()
        state.handicap = ["D16", "Q4", "D4"]
        moves = [(4, "W", "K10")]
        count = state.load_status("W", moves, state.handicap)
        self.assertEqual(count, 1)
        self.assertEqual(state.events, [("W", "K10")])

    def test_load_status_keeps_real_moves(self):
        state = GameState()
        moves = [(1, "B", "Q16"), (2, "W", "D4")]
        state.load_status("B", moves)
        self.assertEqual(state.events, [("B", "Q16"), ("W", "D4")])
        self.assertEqual(state.last_move_no, 2)
        self.assertIn(1, state.fox_moves)

    def test_engine_move_numbering(self):
        self.state.ingest_move(1, "W", "D16")
        no = self.state.accept_engine_move("B", "Q16")
        self.assertEqual(no, 2)
        self.assertEqual(self.state.last_move_no, 2)
        self.assertEqual(self.state.engine_events[-1], ("B", "Q16"))

    def test_plan_after_echo(self):
        state = GameState()
        state.ingest_move(1, "W", "D16")
        state.mark_synced()
        state.accept_engine_move("B", "Q16")
        # Wild Fox now echoes the engine's move
        self.assertEqual(state.ingest_move(2, "B", "Q16"), "echo")
        self.assertEqual(state.next_plan().kind, "none")


if __name__ == "__main__":
    unittest.main(verbosity=2)
