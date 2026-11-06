"""Activated S0.T1–T5 Players: center passes then L/R side-goal passes."""

from __future__ import annotations

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import smart_simust_player as player  # noqa: E402


def _arena_from_sid(sid: str) -> int:
    text = str(sid or "")
    match = re.search(r"[AB](\d+)", text, re.I)
    return int(match.group(1)) if match else 0


def _side_from_sid(sid: str) -> str:
    text = str(sid or "").strip().upper()
    if text.endswith("L") or text.endswith("R"):
        return text[-1]
    return ""


class ActivatedS0PlaylistTests(unittest.TestCase):
    def test_series_detection(self):
        self.assertEqual(
            player._activated_s0_series_num("L02-Activated", "S0.T3"),
            3,
        )
        self.assertIsNone(player._activated_s0_series_num("L01-Entry", "S0.T1"))
        self.assertIsNone(player._activated_series_num("L02-Activated", "S0.T1"))
        self.assertIsNone(player._activated_a1_series_num("L02-Activated", "S0.T2"))

    def test_operator_labels(self):
        self.assertEqual(player._component_set_label("L02-Activated/S0.T1"), "C1.T1")
        self.assertEqual(player._component_set_label("L02-Activated/S1.T2"), "C2.T2")
        self.assertEqual(player._component_set_label("L02-Activated/S2.T3"), "C3.T3")
        self.assertEqual(player._content_type_label("L02-Activated/S0.T1"), "Players")
        self.assertEqual(player._content_type_label("L02-Activated/S1.T1"), "Numbers")
        self.assertEqual(player._content_type_label("L02-Activated/S2.T1"), "Divergent")

    def test_opening_card_shows_players_and_component(self):
        text = player._level_card_text(
            "L02-Activated/S0.T1",
            "",
            {"test_num": 1, "actions_in_set": 10, "finish_balls": True},
            [],
        )
        self.assertEqual(text.split("\n"), ["Players", "C1.T1", "10 Actions"])

    def test_t1_uses_center_pass_five_images(self):
        playlist = player._build_activated_s0_playlist(1, ["A"])
        self.assertEqual(len(playlist), 50)
        center = {
            os.path.normcase(os.path.join(player.ACTIVATED_S0_IMAGE_DIR, name))
            for name in player.ACTIVATED_S0_PASS_CENTER
        }
        for step in playlist:
            self.assertTrue(step.get("finish_balls"))
            images = step.get("screen_images") or {}
            self.assertEqual(len(images), 5)
            goals = (step.get("field_screens") or {}).get("A") or []
            self.assertEqual(len(goals), 1)
            goal = goals[0]
            parent = player._sid(goal)
            self.assertIn(parent, images)
            # C1.T1 tests 1–2 stay center-only; tests 3–5 add L/R.
            if int(step.get("test_num") or 0) <= 2:
                self.assertFalse(step.get("side_goals"))
                self.assertFalse(_side_from_sid(goal))
                self.assertIn(os.path.normcase(images[parent]), center)

    def test_t1_pass_not_adjacent_to_teammate(self):
        teammate = os.path.normcase(
            os.path.join(player.ACTIVATED_S0_IMAGE_DIR, player.ACTIVATED_S0_TEAMMATE)
        )
        playlist = player._build_activated_s0_playlist(2, ["A"])
        for step in playlist:
            images = step.get("screen_images") or {}
            goal = ((step.get("field_screens") or {}).get("A") or [None])[0]
            goal_arena = _arena_from_sid(goal)
            mate = [
                _arena_from_sid(sid)
                for sid, path in images.items()
                if os.path.normcase(path) == teammate
            ]
            self.assertEqual(len(mate), 1)
            self.assertGreaterEqual(abs(goal_arena - mate[0]), 2)

    def test_t3_mixes_five_center_and_five_side_per_test(self):
        playlist = player._build_activated_s0_playlist(3, ["A"])
        self.assertEqual(len(playlist), 50)
        left = os.path.normcase(
            os.path.join(player.ACTIVATED_S0_IMAGE_DIR, player.ACTIVATED_S0_PASS_LEFT)
        )
        right = os.path.normcase(
            os.path.join(player.ACTIVATED_S0_IMAGE_DIR, player.ACTIVATED_S0_PASS_RIGHT)
        )
        center = {
            os.path.normcase(os.path.join(player.ACTIVATED_S0_IMAGE_DIR, name))
            for name in player.ACTIVATED_S0_PASS_CENTER
        }
        by_test = {}
        for step in playlist:
            by_test.setdefault(int(step.get("test_num") or 0), []).append(step)
        self.assertEqual(sorted(by_test), [1, 2, 3, 4, 5])
        for test_num, steps in by_test.items():
            self.assertEqual(len(steps), 10, f"test {test_num}")
            center_n = 0
            side_n = 0
            for step in steps:
                images = step.get("screen_images") or {}
                self.assertEqual(len(images), 5)
                goals = (step.get("field_screens") or {}).get("A") or []
                self.assertEqual(len(goals), 1)
                goal = goals[0]
                side = _side_from_sid(goal)
                parent = player._sid(goal)
                pass_path = os.path.normcase(images[parent])
                if side:
                    side_n += 1
                    self.assertTrue(step.get("side_goals"))
                    self.assertIn(side, ("L", "R"))
                    arena = _arena_from_sid(goal)
                    if side == "L":
                        self.assertIn(arena, (1, 2, 3, 4, 5))
                        self.assertEqual(pass_path, left)
                    else:
                        self.assertIn(arena, (2, 3, 4, 5, 6))
                        self.assertEqual(pass_path, right)
                else:
                    center_n += 1
                    self.assertFalse(step.get("side_goals"))
                    self.assertIn(pass_path, center)
            self.assertEqual(center_n, 5, f"test {test_num} center")
            self.assertEqual(side_n, 5, f"test {test_num} side")

    def test_c1_t1_includes_side_targets_from_test_3(self):
        """Even on C1.T1, in-session tests T3–T5 must include pass-left/right."""
        playlist = player._build_activated_s0_playlist(1, ["A"])
        by_test = {}
        for step in playlist:
            by_test.setdefault(int(step.get("test_num") or 0), []).append(step)
        for test_num in (1, 2):
            sided = sum(1 for s in by_test[test_num] if s.get("side_goals"))
            self.assertEqual(sided, 0, f"test {test_num} should be center-only")
        for test_num in (3, 4, 5):
            sided = sum(1 for s in by_test[test_num] if s.get("side_goals"))
            self.assertEqual(sided, 5, f"test {test_num} needs 5 L/R targets")

    def test_dual_field_independent_side_goals(self):
        playlist = player._build_activated_s0_playlist(4, ["A", "B"])
        # Find a sided action — both fields should carry L/R goals on that step.
        sided = [s for s in playlist if s.get("side_goals")]
        self.assertTrue(sided)
        step = sided[0]
        self.assertIn("A", step.get("field_screens") or {})
        self.assertIn("B", step.get("field_screens") or {})
        self.assertEqual(len(step.get("screen_images") or {}), 10)
        for fid in ("A", "B"):
            goal = ((step.get("field_screens") or {}).get(fid) or [None])[0]
            self.assertIn(_side_from_sid(goal), ("L", "R"))

    def test_goal_sid_preserves_side_for_cue(self):
        self.assertEqual(player._goal_sid("A2R"), "A2R")
        self.assertEqual(player._goal_sid("A1L"), "A1L")
        self.assertEqual(player._goal_sid("A6R"), "A6R")
        self.assertEqual(player._sid("A2R"), "A2")
        self.assertEqual(player._named_goal_screens(["A2R", "B3L"]), ["A2R", "B3L"])
        # Cue path must not collapse A2R → A2 (that drew the full A2 mouth).
        self.assertEqual(player._named_screens(["A2R"]), ["A2"])

    def test_side_goal_token_match(self):
        match = player.SmartPlayerWindow._goal_token_matches
        self.assertTrue(match(None, "A2R", "A2R", "A"))
        self.assertTrue(match(None, "A2R", "13R", "A"))
        self.assertFalse(match(None, "A2R", "A2L", "A"))
        self.assertTrue(match(None, "A2R", "A2", "A"))


if __name__ == "__main__":
    unittest.main()
