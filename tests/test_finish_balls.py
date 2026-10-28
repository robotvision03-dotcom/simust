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

    def test_two_fields_keep_their_own_opening_cards(self):
        cards = player._opening_cards_for_fields(
            ["A", "B"],
            {"A": "L00-Foundation", "B": "L01-Entry/S1.T3"},
            {"A": "SF-180N", "B": "S1.T3"},
            {
                "A": [{"test_num": 1, "on_ms": 1800, "actions_in_set": 8}],
                "B": [{"test_num": 1, "on_ms": 2400, "actions_in_set": 6, "budget_ms": 14400, "finish_balls": True}],
            },
            {},
            [],
            1,
        )
        self.assertIn("SF-180N", cards["A"]["text"])
        self.assertNotIn("Entry", cards["A"]["text"])
        self.assertIn("1.80 S", cards["A"]["text"])
        self.assertIn("8 Actions", cards["A"]["text"])
        self.assertEqual(cards["B"]["text"].split("\n"), ["S1.T3", "6 Actions"])
        self.assertNotIn("Entry", cards["B"]["text"])
        self.assertNotIn("14.40", cards["B"]["text"])
        self.assertEqual(cards["A"]["bg"], (0, 0, 0))
        self.assertEqual(cards["B"]["bg"], (0, 0, 0))
        self.assertNotEqual(cards["A"]["fg"], cards["B"]["fg"])

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
        # Any real Wrong/Miss → used = full budget, AET% = 0
        score = finish_balls_clock([
            {"result": "Correct", "finish_balls": True, "balls_budget_sec": 30, "balls_clock_sec": 10, "movement": 20},
            {"result": "Wrong", "finish_balls": True, "balls_budget_sec": 30, "balls_clock_sec": 30, "movement": 40},
        ])
        self.assertEqual(score["aac"], 50.0)
        self.assertEqual(score["aet"], 30.0)
        self.assertEqual(score["aet_percent"], 0.0)

    def test_s3_all_correct_uses_last_ball_over_budget(self):
        # All Correct: used = max(balls_clock_sec); 54/60 → AET% = 10
        score = finish_balls_clock([
            {"result": "Correct", "finish_balls": True, "balls_budget_sec": 60, "balls_clock_sec": 12},
            {"result": "Correct", "finish_balls": True, "balls_budget_sec": 60, "balls_clock_sec": 54},
        ])
        self.assertEqual(score["aet"], 54.0)
        self.assertAlmostEqual(score["aet_percent"], 10.0)

    def test_no_ball_in_goal_uses_full_budget(self):
        score = finish_balls_clock([
            {"result": "Wrong", "finish_balls": True, "balls_budget_sec": 60, "balls_clock_sec": 60, "movement": 10},
            {"result": "Wrong", "finish_balls": True, "balls_budget_sec": 60, "balls_clock_sec": 60, "movement": 10},
        ])
        self.assertEqual(score["aac"], 0.0)
        self.assertEqual(score["aet"], 60.0)
        self.assertEqual(score["aet_percent"], 0.0)

    def test_late_counts_toward_finish_balls_accuracy(self):
        score = finish_balls_clock([
            {"result": "Correct", "finish_balls": True, "balls_budget_sec": 30, "balls_clock_sec": 10},
            {"result": "Late", "finish_balls": True, "balls_budget_sec": 30},
        ])
        self.assertEqual(score["aac"], 100.0)

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
            {"action": "PASS", "result": "Wrong", "movement": 40, "finish_balls": True,
             "balls_budget_sec": 30, "balls_clock_sec": 30},
        ]
        clock = finish_balls_clock(rows)
        self.assertEqual(clock["aet_percent"], 0.0)
        self.assertAlmostEqual(finish_balls_efficiency(rows, clock["aet_percent"]), 32.5)

    def test_real_mode_timeout_leftovers_burn_budget_and_formula_ae(self):
        """Real S3: unplayed T1a* Wrongs count — used=budget, AE from formula (not ~88)."""
        rows = [
            {"id": "S1", "action": "PASS", "result": "Correct", "movement": 194,
             "finish_balls": True, "balls_budget_sec": 60, "balls_clock_sec": 1.65,
             "ae": 87.7},
            {"id": "T1a2", "action": "PASS", "result": "Wrong", "movement": 0,
             "finish_balls": True, "balls_budget_sec": 60, "balls_clock_sec": 60, "ae": 3.0},
            {"id": "T1a3", "action": "PASS", "result": "Wrong", "movement": 0,
             "finish_balls": True, "balls_budget_sec": 60, "balls_clock_sec": 60, "ae": 3.0},
        ]
        clock = finish_balls_clock(rows, mode=1)
        self.assertEqual(clock["aet"], 60.0)
        self.assertEqual(clock["aet_percent"], 0.0)
        self.assertAlmostEqual(clock["aac"], 100.0 / 3.0)
        ae = finish_balls_efficiency(rows, clock["aet_percent"], mode=1)
        # Must not stick at Mode-2-like ~88
        self.assertLess(ae, 50.0)

    def test_mode2_timeout_fillers_excluded_from_aet(self):
        rows = [
            {"id": "S1", "action": "PASS", "result": "Correct", "movement": 100,
             "finish_balls": True, "balls_budget_sec": 60, "balls_clock_sec": 12},
            {"id": "S2", "action": "PASS", "result": "Correct", "movement": 100,
             "finish_balls": True, "balls_budget_sec": 60, "balls_clock_sec": 24},
            {"id": "T1a3", "action": "PASS", "result": "Wrong", "movement": 0,
             "finish_balls": True, "balls_budget_sec": 60, "balls_clock_sec": 60, "ae": 3.0},
        ]
        clock = finish_balls_clock(rows, mode=2)
        self.assertEqual(clock["aet"], 24.0)
        self.assertAlmostEqual(clock["aet_percent"], (1.0 - 24.0 / 60.0) * 100.0)


if __name__ == "__main__":
    unittest.main()
