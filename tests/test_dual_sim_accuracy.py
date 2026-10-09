"""Both-sim SF-30N and mixed Entry/HP keep independent Correct counts."""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import smart_simust_player as player  # noqa: E402


def _accuracy(correct: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(100.0 * correct / total, 1)


class DualSimFinishPlanAccuracyTests(unittest.TestCase):
    def test_sf30n_both_fields_same_plan_when_all_actions_finish(self):
        """If each field finishes every action, both share the graded plan rate."""
        actions = 10
        for test_num, rate in ((1, 1.00), (2, 0.80), (3, 0.50)):
            goals = int(round(actions * rate))
            a_correct = sum(
                1
                for i in range(1, actions + 1)
                if player.finish_balls_sim_plan(test_num, i, actions) != "wrong"
            )
            b_correct = sum(
                1
                for i in range(1, actions + 1)
                if player.finish_balls_sim_plan(test_num, i, actions) != "wrong"
            )
            self.assertEqual(a_correct, goals)
            self.assertEqual(b_correct, goals)
            self.assertEqual(_accuracy(a_correct, actions), _accuracy(b_correct, actions))

    def test_early_shared_advance_would_starve_field_b(self):
        """Regression: advancing on A's first Correct leaves B short of finishes."""
        actions = 10
        # Model the old bug: each step A finishes, B only finishes 6/10.
        a_correct = actions
        b_correct = 6
        self.assertEqual(_accuracy(a_correct, actions), 100.0)
        self.assertEqual(_accuracy(b_correct, actions), 60.0)
        # With wait-for-both, B also reaches every action on test 1.
        both_correct = sum(
            1
            for i in range(1, actions + 1)
            if player.finish_balls_sim_plan(1, i, actions) != "wrong"
        )
        self.assertEqual(both_correct, actions)
        self.assertEqual(_accuracy(both_correct, actions), 100.0)


class IndependentEntryHpAccuracyTests(unittest.TestCase):
    def _mini_parts(self):
        return {
            "A": [
                {
                    "test_num": 1,
                    "action_in_set": 1,
                    "actions_in_set": 3,
                    "finish_balls": True,
                    "advance_on_goal": True,
                    "field_screens": {"A": ["A1"]},
                    "screen_images": {"A1": "a1", "A2": "a2", "A3": "a3"},
                    "budget_ms": 9000,
                    "on_ms": 3000,
                },
                {
                    "test_num": 1,
                    "action_in_set": 2,
                    "actions_in_set": 3,
                    "finish_balls": True,
                    "advance_on_goal": True,
                    "field_screens": {"A": ["A2"]},
                    "screen_images": {"A1": "a1", "A2": "a2", "A3": "a3"},
                    "budget_ms": 9000,
                    "on_ms": 3000,
                },
                {
                    "test_num": 1,
                    "action_in_set": 3,
                    "actions_in_set": 3,
                    "finish_balls": True,
                    "advance_on_goal": True,
                    "field_screens": {"A": ["A3"]},
                    "screen_images": {"A1": "a1", "A2": "a2", "A3": "a3"},
                    "budget_ms": 9000,
                    "on_ms": 3000,
                },
            ],
            "B": [
                {
                    "test_num": 1,
                    "action_in_set": 1,
                    "actions_in_set": 2,
                    "finish_balls": True,
                    "advance_on_goal": True,
                    "field_screens": {"B": ["B1"]},
                    "screen_images": {"B1": "b1", "B2": "b2"},
                    "budget_ms": 4800,
                    "on_ms": 2400,
                },
                {
                    "test_num": 1,
                    "action_in_set": 2,
                    "actions_in_set": 2,
                    "finish_balls": True,
                    "advance_on_goal": True,
                    "field_screens": {"B": ["B2"]},
                    "screen_images": {"B1": "b1", "B2": "b2"},
                    "budget_ms": 4800,
                    "on_ms": 2400,
                },
            ],
        }

    def test_entry_and_hp_lengths_stay_independent(self):
        parts = self._mini_parts()
        live = player._zip_field_action_playlists(parts)
        self.assertEqual(len(live), 1)
        self.assertTrue(live[0]["independent_fields"])
        self.assertEqual(live[0]["field_screens"], {"A": ["A1"], "B": ["B1"]})

        inst = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        inst._field_opening_playlists = parts
        inst._independent_index = {"A": 0, "B": 0}
        inst._independent_done = {"A": False, "B": False}
        inst._goal_arrived_fields = set()
        inst._goal_arrived = False
        inst.video_files = live
        inst.current_video_index = 0
        inst.display_phase = "action"
        inst._action_phase = "label"
        inst._label_phase = "action"
        inst.action_timer = None
        inst._stop_action_timer = lambda: None
        inst._stop_goal_advance_poll = lambda: None
        finished = []
        inst._finish_label_action = lambda: finished.append(True)
        reloads = []
        inst._apply_label_phase = lambda: reloads.append(
            dict(inst.video_files[0].get("field_screens") or {})
        )

        # A finishes first two actions while B stays on action 1.
        inst._advance_independent_field("A")
        self.assertEqual(inst._independent_index, {"A": 1, "B": 0})
        self.assertEqual(inst.video_files[0]["field_screens"], {"A": ["A2"], "B": ["B1"]})
        self.assertEqual(inst.video_files[0]["field_meta"]["A"]["action_in_set"], 2)
        self.assertEqual(inst.video_files[0]["field_meta"]["B"]["action_in_set"], 1)

        inst._advance_independent_field("B")
        self.assertEqual(inst._independent_index, {"A": 1, "B": 1})
        self.assertEqual(inst.video_files[0]["field_screens"], {"A": ["A2"], "B": ["B2"]})

        # Each field's sim plan uses its own action_in_set / actions_in_set.
        a_meta = inst.video_files[0]["field_meta"]["A"]
        b_meta = inst.video_files[0]["field_meta"]["B"]
        self.assertNotEqual(
            player.finish_balls_sim_plan(
                a_meta["test_num"], a_meta["action_in_set"], a_meta["actions_in_set"]
            ),
            "wrong",
        )
        self.assertNotEqual(
            player.finish_balls_sim_plan(
                b_meta["test_num"], b_meta["action_in_set"], b_meta["actions_in_set"]
            ),
            "wrong",
        )

        # Finish remaining actions; playlist ends only when both are done.
        inst._advance_independent_field("A")  # A -> 3
        inst._advance_independent_field("B")  # B done
        self.assertTrue(inst._independent_done["B"])
        self.assertFalse(finished)
        inst._advance_independent_field("A")  # A done → finish
        self.assertTrue(inst._independent_done["A"])
        self.assertEqual(finished, [True])
        self.assertEqual(len(reloads), 4)


if __name__ == "__main__":
    unittest.main()
