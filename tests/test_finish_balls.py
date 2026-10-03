"""Series tests share one clock: session time × action count."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import smart_simust_player as player  # noqa: E402
from app import finish_balls_action_ae, finish_balls_clock, finish_balls_efficiency  # noqa: E402


class FinishBallsTests(unittest.TestCase):
    def test_clock_is_session_time_times_actions(self):
        rows = player._stamp_finish_balls([
            {"on_ms": 3000, "actions_in_set": 10},
            {"on_ms": 4500, "actions_in_set": 12},
        ])
        self.assertEqual(rows[0]["budget_ms"], 30000)
        self.assertEqual(rows[1]["budget_ms"], 54000)
        self.assertTrue(rows[0]["advance_on_goal"])
        self.assertTrue(rows[0]["skip_gap"])
        self.assertTrue(rows[0]["finish_balls"])
        self.assertEqual(rows[0]["efficiency_max_sec"], 30.0)

    def test_opening_card_shows_the_total_clock(self):
        text = player._level_card_text(
            "L00-Foundation",
            "SF-30N",
            {
                "on_ms": 3000,
                "actions_in_set": 10,
                "budget_ms": 30000,
                "finish_balls": True,
                "test_num": 1,
            },
            [],
        )
        self.assertIn("30.00 S", text)
        self.assertIn("10 Actions", text)
        self.assertNotIn("3.00 S", text)

    def test_simulator_accuracy_runs_100_80_50_20_100(self):
        # 10 actions: 10, 8, 5, 2, 10 goals.
        self.assertNotEqual(player.finish_balls_sim_plan(1, 10, 10), "wrong")
        self.assertNotEqual(player.finish_balls_sim_plan(2, 8, 10), "wrong")
        self.assertEqual(player.finish_balls_sim_plan(2, 9, 10), "wrong")
        self.assertNotEqual(player.finish_balls_sim_plan(3, 5, 10), "wrong")
        self.assertEqual(player.finish_balls_sim_plan(3, 6, 10), "wrong")
        self.assertNotEqual(player.finish_balls_sim_plan(4, 2, 10), "wrong")
        self.assertEqual(player.finish_balls_sim_plan(4, 3, 10), "wrong")
        self.assertNotEqual(player.finish_balls_sim_plan(5, 10, 10), "wrong")

    def test_world_class_first_set_is_four_and_a_half_times_twelve(self):
        on_ms, _gap = player._elite_series_timing_ms(1)
        self.assertEqual(on_ms, 4500)
        self.assertEqual(on_ms * 12, 54000)

    def test_all_balls_in_is_full_accuracy_and_speed_against_the_clock(self):
        score = finish_balls_clock([
            {"result": "Correct", "finish_balls": True, "balls_budget_sec": 30, "balls_clock_sec": 12},
            {"result": "Correct", "finish_balls": True, "balls_budget_sec": 30, "balls_clock_sec": 20},
        ])
        self.assertEqual(score["aac"], 100.0)
        self.assertEqual(score["aet"], 20.0)
        self.assertAlmostEqual(score["aet_percent"], (1.0 - 20.0 / 30.0) * 100.0)

    def test_partial_goals_lower_accuracy_and_use_the_whole_clock(self):
        score = finish_balls_clock([
            {"result": "Correct", "finish_balls": True, "balls_budget_sec": 30, "balls_clock_sec": 10},
            {"result": "Wrong", "finish_balls": True, "balls_budget_sec": 30, "balls_clock_sec": 30},
        ])
        self.assertEqual(score["aac"], 50.0)
        self.assertEqual(score["aet"], 30.0)
        self.assertEqual(score["aet_percent"], 0.0)

    def test_efficiency_uses_aet_in_the_action_formula(self):
        # Correct pass, player still, AET 50 → 0.40×70 + 0.30×100 + 0.20×50 = 68
        correct = {"action": "PASS", "result": "Correct", "movement": 0}
        self.assertAlmostEqual(finish_balls_action_ae(correct, 50), 68.0)
        # Same pass marked wrong, AET 0 → 0.40×70 − 25 = 3
        wrong = {"action": "PASS", "result": "Wrong", "movement": 0}
        self.assertAlmostEqual(finish_balls_action_ae(wrong, 0), 3.0)
        # A missed ball uses the whole clock, so both actions share AET 0.
        rows = [
            {"action": "PASS", "result": "Correct", "movement": 0, "finish_balls": True,
             "balls_budget_sec": 30, "balls_clock_sec": 10},
            {"action": "PASS", "result": "Wrong", "movement": 0, "finish_balls": True,
             "balls_budget_sec": 30, "balls_clock_sec": 30},
        ]
        clock = finish_balls_clock(rows)
        self.assertEqual(clock["aet_percent"], 0.0)
        self.assertAlmostEqual(finish_balls_efficiency(rows, clock["aet_percent"]), 30.5)


if __name__ == "__main__":
    unittest.main()
