"""Dual fields stay independent except Elite / World Class."""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import smart_simust_player as player  # noqa: E402


class IndependentComposeTests(unittest.TestCase):
    def test_compose_keeps_each_fields_own_goal(self):
        parts = {
            "A": [
                {
                    "test_num": 1,
                    "action_in_set": 1,
                    "actions_in_set": 2,
                    "on_ms": 3000,
                    "finish_balls": True,
                    "advance_on_goal": True,
                    "field_screens": {"A": ["A2"]},
                    "screen_images": {"A2": "a2.png", "A3": "a3.png"},
                    "budget_ms": 6000,
                },
                {
                    "test_num": 1,
                    "action_in_set": 2,
                    "actions_in_set": 2,
                    "on_ms": 3000,
                    "finish_balls": True,
                    "advance_on_goal": True,
                    "field_screens": {"A": ["A3"]},
                    "screen_images": {"A2": "a2.png", "A3": "a3.png"},
                    "budget_ms": 6000,
                },
            ],
            "B": [
                {
                    "test_num": 1,
                    "action_in_set": 1,
                    "actions_in_set": 2,
                    "on_ms": 2400,
                    "finish_balls": True,
                    "advance_on_goal": True,
                    "field_screens": {"B": ["B1"]},
                    "screen_images": {"B1": "b1.png", "B2": "b2.png"},
                    "budget_ms": 4800,
                },
                {
                    "test_num": 1,
                    "action_in_set": 2,
                    "actions_in_set": 2,
                    "on_ms": 2400,
                    "finish_balls": True,
                    "advance_on_goal": True,
                    "field_screens": {"B": ["B2"]},
                    "screen_images": {"B1": "b1.png", "B2": "b2.png"},
                    "budget_ms": 4800,
                },
            ],
        }
        first = player._compose_independent_entry(parts, {"A": 0, "B": 0})
        self.assertEqual(first["field_screens"], {"A": ["A2"], "B": ["B1"]})
        self.assertTrue(first["independent_fields"])
        advanced_a = player._compose_independent_entry(parts, {"A": 1, "B": 0})
        self.assertEqual(advanced_a["field_screens"], {"A": ["A3"], "B": ["B1"]})
        self.assertEqual(advanced_a["field_meta"]["A"]["action_in_set"], 2)
        self.assertEqual(advanced_a["field_meta"]["B"]["action_in_set"], 1)

    def test_zip_seeds_one_live_entry(self):
        parts = {
            "A": [{"test_num": 1, "field_screens": {"A": ["A1"]}, "screen_images": {"A1": "x"}}],
            "B": [{"test_num": 1, "field_screens": {"B": ["B1"]}, "screen_images": {"B1": "y"}}],
        }
        merged = player._zip_field_action_playlists(parts)
        self.assertEqual(len(merged), 1)
        self.assertTrue(merged[0]["independent_fields"])

    def test_opening_card_puts_band_and_test_on_own_lines(self):
        text = player._level_card_text(
            "L04-Elite/S1.T2",
            "",
            {"test_num": 3, "budget_ms": 54000, "actions_in_set": 12, "finish_balls": True},
            [],
        )
        self.assertEqual(text.split("\n"), ["S1.T2", "12 Actions"])
        self.assertNotIn("Elite", text)
        self.assertNotIn("54.00", text)


class IndependentAdvanceTests(unittest.TestCase):
    def test_advancing_field_a_does_not_move_field_b(self):
        inst = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        parts = {
            "A": [
                {
                    "test_num": 1,
                    "action_in_set": 1,
                    "actions_in_set": 2,
                    "finish_balls": True,
                    "advance_on_goal": True,
                    "field_screens": {"A": ["A1"]},
                    "screen_images": {"A1": "a1", "A2": "a2"},
                },
                {
                    "test_num": 1,
                    "action_in_set": 2,
                    "actions_in_set": 2,
                    "finish_balls": True,
                    "advance_on_goal": True,
                    "field_screens": {"A": ["A2"]},
                    "screen_images": {"A1": "a1", "A2": "a2"},
                },
            ],
            "B": [
                {
                    "test_num": 1,
                    "action_in_set": 1,
                    "actions_in_set": 2,
                    "finish_balls": True,
                    "advance_on_goal": True,
                    "field_screens": {"B": ["B3"]},
                    "screen_images": {"B3": "b3", "B4": "b4"},
                },
                {
                    "test_num": 1,
                    "action_in_set": 2,
                    "actions_in_set": 2,
                    "finish_balls": True,
                    "advance_on_goal": True,
                    "field_screens": {"B": ["B4"]},
                    "screen_images": {"B3": "b3", "B4": "b4"},
                },
            ],
        }
        inst._field_opening_playlists = parts
        inst._independent_index = {"A": 0, "B": 0}
        inst._independent_done = {"A": False, "B": False}
        inst._goal_arrived_fields = set()
        inst.video_files = player._zip_field_action_playlists(parts)
        inst.current_video_index = 0
        inst.display_phase = "action"
        inst._action_phase = "label"
        inst._label_phase = "action"
        inst._goal_arrived = False
        inst.action_timer = None
        calls = []
        inst._apply_label_phase = lambda: calls.append("reload")
        inst._stop_action_timer = lambda: None
        inst._advance_independent_field("A")
        self.assertEqual(inst._independent_index["A"], 1)
        self.assertEqual(inst._independent_index["B"], 0)
        entry = inst.video_files[0]
        self.assertEqual(entry["field_screens"]["A"], ["A2"])
        self.assertEqual(entry["field_screens"]["B"], ["B3"])
        self.assertEqual(calls, ["reload"])


if __name__ == "__main__":
    unittest.main()
