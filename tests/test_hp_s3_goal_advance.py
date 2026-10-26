"""High Performance S3: advance only after both sum-goal screens score Correct."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import smart_simust_player as player  # noqa: E402


class HpS3GoalAdvanceTests(unittest.TestCase):
    def test_goal_token_matches_screen_ids_and_digits(self):
        window = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        self.assertTrue(window._goal_token_matches("A3", "A3", "A"))
        self.assertTrue(window._goal_token_matches("A3", "3", "A"))
        self.assertTrue(window._goal_token_matches("B6", "6", "B"))
        self.assertFalse(window._goal_token_matches("A3", "A4", "A"))
        self.assertFalse(window._goal_token_matches("A3", "B3", "A"))
        self.assertFalse(window._goal_token_matches("A3", "N/A", "A"))

    def test_field_goals_complete_needs_both_hits(self):
        window = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        entry = {"field_screens": {"A": ["A2", "A5"]}}
        self.assertFalse(window._field_goals_complete(entry, "A", ["A2"]))
        self.assertFalse(window._field_goals_complete(entry, "A", ["2"]))
        self.assertTrue(window._field_goals_complete(entry, "A", ["A2", "5"]))
        self.assertTrue(window._field_goals_complete(entry, "A", ["2", "5"]))

    def test_sum_layout_has_exactly_one_pair(self):
        for ref in (5, 9, 17, 42, 99):
            nums, (g0, g1) = player._hp_s3_screen_numbers(ref)
            self.assertEqual(len(nums), 6)
            self.assertEqual(nums[g0] + nums[g1], ref)
            pairs = player._hp_s3_pair_sums_to(nums, ref)
            self.assertEqual(len(pairs), 1, (ref, nums, pairs))
        for ref in (17, 42, 73):
            nums, (g0, g1) = player._s3_sum_screen_numbers(ref, 12)
            self.assertEqual(len(nums), 12)
            self.assertEqual(nums[g0] + nums[g1], ref)
            pairs = player._hp_s3_pair_sums_to(nums, ref)
            self.assertEqual(len(pairs), 1, (ref, nums, pairs))

    def test_remaining_goals_and_hold_full_on_budget(self):
        window = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        entry = {"field_screens": {"A": ["A2", "A5"]}, "hold_full_on": True}
        self.assertEqual(
            window._remaining_goal_screens(entry, "A", ["A2"]),
            ["A5"],
        )
        self.assertEqual(
            window._remaining_goal_screens(entry, "A", ["2", "5"]),
            [],
        )
        self.assertEqual(player.HP_S3_ON_MS, 10000)
        self.assertEqual(player.HP_S3_TEST_BUDGET_MS, 60000)

    def test_hold_full_on_uses_on_ms_not_full_budget(self):
        """Mode 2 must advance every 10s — not sit on the whole 60s budget."""
        window = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        window.player_speed = 1.0
        entry = {
            "hold_full_on": True,
            "fixed_timing": True,
            "on_ms": 10000,
            "budget_ms": 60000,
            "timing_scale": 1.0,
        }
        window._budget_started_at = None
        delay = window._label_action_delay_ms(entry)
        self.assertAlmostEqual(delay, 10000, delta=50)

    def test_blackout_only_scored_goal_screens(self):
        window = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        painted = {}

        class Canvas:
            def set_screen_images(self, images, keep_videos=False, replace_fields=None):
                painted.clear()
                painted.update(images)

        window.image_canvas = Canvas()
        player._render_solid_screen_image = lambda bg=(0, 0, 0): f"black:{bg}"
        entry = {
            "field_screens": {"A": ["A2", "A5"]},
            "screen_images": {
                "A1": "n1",
                "A2": "n2",
                "A3": "n3",
                "A4": "n4",
                "A5": "n5",
                "A6": "n6",
            },
        }
        window._blackout_scored_goal_screens(entry, "A", ["A2"])
        self.assertEqual(painted["A2"], "black:(0, 0, 0)")
        self.assertEqual(painted["A5"], "n5")
        self.assertEqual(painted["A1"], "n1")


if __name__ == "__main__":
    unittest.main()
