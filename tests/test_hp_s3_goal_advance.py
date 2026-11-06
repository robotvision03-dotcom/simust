"""High Performance S3: advance only after both sum-goal screens score Correct."""

import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import smart_simust_player as player  # noqa: E402


class HpS3GoalAdvanceTests(unittest.TestCase):
    def test_goal_token_matches_screen_ids_and_digits(self):
        window = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        self.assertTrue(window._goal_token_matches("A3", "A3", "A"))
        # Bare cabinet ids map to tiles (A5↔3, B2↔6), not A1–A6 ordinal digits.
        self.assertTrue(window._goal_token_matches("A5", "3", "A"))
        self.assertTrue(window._goal_token_matches("B2", "6", "B"))
        self.assertFalse(window._goal_token_matches("A3", "3", "A"))
        self.assertFalse(window._goal_token_matches("A3", "A4", "A"))
        self.assertFalse(window._goal_token_matches("A3", "B3", "A"))
        self.assertFalse(window._goal_token_matches("A3", "N/A", "A"))

    def test_field_goals_complete_needs_both_hits(self):
        window = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        entry = {"field_screens": {"A": ["A2", "A5"]}}
        self.assertFalse(window._field_goals_complete(entry, "A", ["A2"]))
        self.assertFalse(window._field_goals_complete(entry, "A", ["13"]))
        self.assertTrue(window._field_goals_complete(entry, "A", ["A2", "A5"]))
        # Cabinet ids: A2↔13, A5↔3.
        self.assertTrue(window._field_goals_complete(entry, "A", ["13", "3"]))

    def test_any_goal_pair_complete_advances_on_one_of_three(self):
        """Elite/WC C3: any one of three A+B pairs finishes the action."""
        window = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        entry = {
            "require_any_goal_pair": True,
            "goal_pairs": [
                ["A1", "B2"],
                ["A3", "B4"],
                ["A5", "B6"],
            ],
            "field_screens": {
                "A": ["A1", "A3", "A5"],
                "B": ["B2", "B4", "B6"],
            },
        }
        self.assertFalse(
            window._any_goal_pair_complete(entry, {"A": ["A1"], "B": []})
        )
        self.assertFalse(
            window._any_goal_pair_complete(
                entry, {"A": ["A1", "A3"], "B": ["B6"]}
            )
        )
        self.assertTrue(
            window._any_goal_pair_complete(
                entry, {"A": ["A3"], "B": ["B4"]}
            )
        )
        self.assertTrue(
            window._any_goal_pair_complete(
                entry, {"A": ["A5"], "B": ["B6"]}
            )
        )

    def test_elite_wc_multi_pair_layout_three_pairs_on_six_screens(self):
        screens = player._elite_screen_ids()
        for ref in (12, 37, 49, 55, 88):
            nums, pairs, field_screens, value_pairs = (
                player._s3_combined_multi_pair_layout(ref, screens, 3)
            )
            self.assertEqual(len(pairs), 3)
            self.assertEqual(len(value_pairs), 3)
            self.assertEqual(len(field_screens.get("A") or []), 3)
            self.assertEqual(len(field_screens.get("B") or []), 3)
            digit_count = sum(1 for n in nums if n is not None)
            self.assertEqual(digit_count, 6)
            for pair, (va, vb) in zip(pairs, value_pairs):
                self.assertEqual({pair[0][0], pair[1][0]}, {"A", "B"})
                self.assertEqual(va + vb, ref)
                ia = screens.index(pair[0])
                ib = screens.index(pair[1])
                self.assertEqual(nums[ia] + nums[ib], ref)

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
            window._remaining_goal_screens(entry, "A", ["A2", "A5"]),
            [],
        )
        self.assertEqual(
            window._remaining_goal_screens(entry, "A", ["13", "3"]),
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

    def test_independent_compose_keeps_s3_multi_goal_flags(self):
        """Dual separate HP S3 must keep require_all_goals (one hit ≠ both done)."""
        step_a = {
            "test_num": 1,
            "action_in_set": 1,
            "actions_in_set": 6,
            "on_ms": 10000,
            "budget_ms": 60000,
            "finish_balls": True,
            "require_all_goals": True,
            "hold_full_on": True,
            "cognitive_encode": True,
            "encode_ms": 5000,
            "entry_digits": True,
            "field_screens": {"A": ["A2", "A5"]},
            "screen_images": {"A1": "a1", "A2": "a2", "A5": "a5"},
            "encode_images": {"A1": "e1", "A2": "e2"},
            "reference_numbers": {"A": 17},
            "sum_pairs": {"A": (8, 9)},
            "label": "A s3",
        }
        step_b = {
            "test_num": 1,
            "action_in_set": 1,
            "actions_in_set": 6,
            "on_ms": 10000,
            "budget_ms": 60000,
            "finish_balls": True,
            "require_all_goals": True,
            "hold_full_on": True,
            "cognitive_encode": True,
            "encode_ms": 5000,
            "entry_digits": True,
            "field_screens": {"B": ["B3", "B6"]},
            "screen_images": {"B1": "b1", "B3": "b3", "B6": "b6"},
            "encode_images": {"B1": "eb1", "B3": "eb3"},
            "reference_numbers": {"B": 42},
            "sum_pairs": {"B": (20, 22)},
            "label": "B s3",
        }
        entry = player._compose_independent_entry(
            {"A": [step_a], "B": [step_b]},
            {"A": 0, "B": 0},
        )
        self.assertIsNotNone(entry)
        self.assertTrue(entry.get("independent_fields"))
        self.assertTrue(entry.get("require_all_goals"))
        self.assertTrue(entry.get("hold_full_on"))
        self.assertTrue(entry.get("cognitive_encode"))
        self.assertEqual(entry.get("field_screens"), {"A": ["A2", "A5"], "B": ["B3", "B6"]})
        self.assertIn("A2", entry.get("screen_images") or {})
        self.assertIn("B3", entry.get("screen_images") or {})
        self.assertNotIn("B1", step_a["screen_images"])  # source isolation sanity
        self.assertEqual((entry.get("encode_images") or {}).get("A1"), "e1")
        self.assertEqual((entry.get("encode_images") or {}).get("B1"), "eb1")
        self.assertEqual(entry.get("reference_numbers"), {"A": 17, "B": 42})

    def test_independent_one_correct_does_not_advance_either_field(self):
        """One cylinder Correct on A must not finish A or touch B."""
        import json
        import tempfile
        from unittest import mock

        window = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        window.operator_paused = False
        window.display_phase = "action"
        window._label_phase = "action"
        window._goal_arrived = False
        window._flash_seq = 1
        window._field_cue_seq = {"A": 1, "B": 1}
        window._action_cue_wall = time.time() - 1.0
        window._field_action_wall = {"A": time.time() - 1.0, "B": time.time() - 1.0}
        window._goal_hits_by_field = {}
        window.current_video_index = 0
        window.video_files = [{
            "advance_on_goal": True,
            "independent_fields": True,
            "require_all_goals": True,
            "hold_full_on": True,
            "field_screens": {"A": ["A2", "A5"], "B": ["B3", "B6"]},
        }]
        finished = {"n": 0}
        window._active_fields = lambda: ["A", "B"]
        window._fields_blocked_from_action = lambda: set()
        window._pause_fields = lambda: {}
        window._player_attr = lambda name, default=None: getattr(window, name, default)
        window._stop_goal_advance_poll = lambda: None
        window._clear_field_action_now = lambda fid: None
        window._blackout_scored_goal_screens = lambda *a, **k: None
        window._finish_label_action = lambda: finished.__setitem__("n", finished["n"] + 1)

        payload = {
            "fields": {
                "A": {
                    "result": "Correct",
                    "winning_screen": "A2",
                    "seq": 1,
                    "ts": time.time(),
                    "by_seq": {
                        "1": {
                            "result": "Correct",
                            "winning_screen": "A2",
                            "seq": 1,
                            "ts": time.time(),
                        }
                    },
                },
                "B": {
                    "result": "",
                    "winning_screen": "",
                    "seq": 0,
                    "ts": 0,
                    "by_seq": {},
                },
            }
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            path = handle.name
        try:
            with mock.patch.object(player, "LIVE_ACTION_RESULT_FILE", path):
                window._poll_goal_advance()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        self.assertEqual(finished["n"], 0)
        self.assertEqual(set(window._goal_hits_by_field.get("A") or []), {"A2"})
        self.assertFalse(window._goal_hits_by_field.get("B"))


if __name__ == "__main__":
    unittest.main()
