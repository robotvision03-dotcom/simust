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

    def test_require_all_goals_waits_on_shared_test_clock(self):
        """S3 answers wait for both cylinders or the 60s test clock (not 10s slices)."""
        window = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        window.player_speed = 1.0
        entry = {
            "require_all_goals": True,
            "hold_full_on": True,
            "fixed_timing": True,
            "on_ms": 10000,
            "budget_ms": 60000,
            "test_num": 1,
            "timing_scale": 1.0,
        }
        window._budget_started_at = None
        window._budget_test = None
        delay = window._label_action_delay_ms(entry)
        self.assertAlmostEqual(delay, 60000, delta=200)
        # After ~20s of the shared clock, still wait for the remainder — not on_ms.
        window._budget_started_at = __import__("time").perf_counter() - 20.0
        window._budget_test = 1
        delay2 = window._label_action_delay_ms(entry)
        self.assertAlmostEqual(delay2, 40000, delta=500)

    def test_finish_without_both_goals_keeps_waiting_while_budget_remains(self):
        window = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        window.display_phase = "action"
        window._action_phase = "label"
        window.operator_paused = False
        window.player_speed = 1.0
        window._goal_arrived = False
        window._pass_shown_at = __import__("time").perf_counter() - 1.0
        window._pass_on_ms = 1000
        window.video_files = [{
            "require_all_goals": True,
            "advance_on_goal": True,
            "budget_ms": 60000,
            "test_num": 1,
            "field_screens": {"A": ["A2", "A5"]},
        }]
        window.current_video_index = 0
        window._budget_started_at = __import__("time").perf_counter()
        window._budget_test = 1
        window._run_phases = []
        window._phase_index = 0
        calls = {"abandon": 0, "poll": 0}

        window._stop_action_timer = lambda: None
        window._stop_goal_advance_poll = lambda: None
        window._cancel_next_screen_hint = lambda: None
        window._abandon_budget_rest = lambda: calls.__setitem__("abandon", calls["abandon"] + 1)
        window._start_goal_advance_poll = lambda: calls.__setitem__("poll", calls["poll"] + 1)
        window._finish_independent_step = lambda: None
        window.image_canvas = None
        window.action_timer = None

        class _Timer:
            def __init__(self, *a, **k):
                self.timeout = type("Sig", (), {"connect": lambda self, fn: None})()
            def setTimerType(self, *_a):
                return None
            def start(self, ms):
                self.ms = ms

        import smart_simust_player as mod
        real_qtimer = mod.QtCore.QTimer
        mod.QtCore.QTimer = _Timer
        try:
            window._finish_label_action()
        finally:
            mod.QtCore.QTimer = real_qtimer
        self.assertEqual(calls["abandon"], 0)
        self.assertEqual(calls["poll"], 1)
        self.assertGreater(getattr(window.action_timer, "ms", 0), 1000)

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
