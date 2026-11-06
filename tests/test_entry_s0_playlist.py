"""Entry S0.T1–T5: pass goal among static player PNGs on 6 screens."""

from __future__ import annotations

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import smart_simust_player as player  # noqa: E402


def _arena_from_sid(sid: str) -> int:
    match = re.search(r"(\d+)$", str(sid or ""))
    return int(match.group(1)) if match else 0


class EntryS0PlaylistTests(unittest.TestCase):
    def test_series_detection(self):
        self.assertEqual(
            player._entry_s0_series_num("L01-Entry", "S0.T3"),
            3,
        )
        self.assertEqual(
            player._entry_s0_series_num(r"C:\simust_player\L01-Entry\S0-T2"),
            2,
        )
        self.assertIsNone(player._entry_s0_series_num("L01-Entry", "S1.T1"))
        self.assertIsNone(player._entry_series_num("L01-Entry", "S0.T1"))

    def test_series_label(self):
        self.assertEqual(player._series_set_label("L01-Entry/S0.T4"), "S0.T4")
        self.assertEqual(player._component_set_label("L01-Entry/S0.T4"), "C1.T4")
        self.assertEqual(player._component_set_label("L01-Entry/S1.T1"), "C2.T1")
        self.assertEqual(player._content_type_label("L01-Entry/S0.T1"), "Players")
        self.assertEqual(player._content_type_label("L01-Entry/S1.T2"), "Numbers")

    def test_opening_card_shows_players_and_component(self):
        text = player._level_card_text(
            "L01-Entry/S0.T1",
            "",
            {"test_num": 1, "actions_in_set": 10, "finish_balls": True},
            [],
        )
        self.assertEqual(text.split("\n"), ["Players", "C1.T1", "10 Actions"])

    def test_t1_pool_has_three_images(self):
        pass_path, distractors = player._entry_s0_image_paths(1)
        self.assertTrue(pass_path and os.path.isfile(pass_path))
        self.assertEqual(len(distractors), 2)
        names = {os.path.basename(p) for p in distractors}
        self.assertEqual(
            names,
            {
                "Male-Opponent-Player-01-01.png",
                "Male-Opponent-Player-02-01.jpeg",
            },
        )

    def test_t3_pool_adds_extra_players(self):
        pass_path, distractors = player._entry_s0_image_paths(3)
        self.assertTrue(pass_path)
        self.assertEqual(len(distractors), 4)
        names = {os.path.basename(p) for p in distractors}
        self.assertIn("Male-Opponent-Player-03-01.png", names)
        self.assertIn("Male-Teamate-Player-01-01.png", names)

    def test_playlist_has_ten_actions_and_larger_scale(self):
        playlist = player._build_entry_s0_playlist(1, ["A"])
        self.assertEqual(len(playlist), 50)  # 5 tests × 10 actions
        self.assertEqual(playlist[0].get("actions_in_set"), 10)
        self.assertAlmostEqual(
            float(playlist[0].get("pass_image_scale") or 0),
            player.ENTRY_S0_PASS_IMAGE_SCALE,
            places=4,
        )

    def test_playlist_pass_is_only_goal(self):
        playlist = player._build_entry_s0_playlist(1, ["A"])
        pass_path = os.path.join(player.ENTRY_S0_IMAGE_DIR, player.ENTRY_S0_PASS_NAME)
        for step in playlist:
            self.assertTrue(step.get("finish_balls"))
            self.assertFalse(step.get("entry_digits"))
            goals = (step.get("field_screens") or {}).get("A") or []
            self.assertEqual(len(goals), 1)
            goal = goals[0]
            images = step.get("screen_images") or {}
            # T1: 3 unique images → 3 lit screens, 3 unused.
            self.assertEqual(len(images), 3)
            paths = list(images.values())
            self.assertEqual(len(paths), len({os.path.normcase(p) for p in paths}))
            self.assertEqual(os.path.normcase(images[goal]), os.path.normcase(pass_path))

    def test_t1_opponents_are_not_adjacent(self):
        pass_path = os.path.join(player.ENTRY_S0_IMAGE_DIR, player.ENTRY_S0_PASS_NAME)
        playlist = player._build_entry_s0_playlist(2, ["A"])
        for step in playlist:
            images = step.get("screen_images") or {}
            goal = ((step.get("field_screens") or {}).get("A") or [None])[0]
            goal_arena = _arena_from_sid(goal)
            opp_screens = sorted(
                _arena_from_sid(sid)
                for sid, path in images.items()
                if os.path.normcase(path) != os.path.normcase(pass_path)
            )
            self.assertEqual(len(opp_screens), 2)
            self.assertGreaterEqual(abs(opp_screens[0] - opp_screens[1]), 2)
            for opp in opp_screens:
                self.assertGreaterEqual(abs(goal_arena - opp), 2)

    def test_t5_uses_five_unique_images(self):
        playlist = player._build_entry_s0_playlist(5, ["A"])
        self.assertEqual(len(playlist), 50)
        for step in playlist:
            images = step.get("screen_images") or {}
            self.assertEqual(len(images), 5)
            paths = [os.path.normcase(p) for p in images.values()]
            self.assertEqual(len(paths), len(set(paths)))

    def test_t5_pass_not_adjacent_to_teammate(self):
        pass_path = os.path.join(player.ENTRY_S0_IMAGE_DIR, player.ENTRY_S0_PASS_NAME)
        playlist = player._build_entry_s0_playlist(5, ["A"])
        for step in playlist:
            images = step.get("screen_images") or {}
            goal = ((step.get("field_screens") or {}).get("A") or [None])[0]
            goal_arena = _arena_from_sid(goal)
            teammate_screens = [
                _arena_from_sid(sid)
                for sid, path in images.items()
                if player._entry_s0_is_teammate_path(path)
            ]
            self.assertEqual(len(teammate_screens), 1)
            self.assertGreaterEqual(abs(goal_arena - teammate_screens[0]), 2)
            self.assertEqual(
                os.path.normcase(images[goal]),
                os.path.normcase(pass_path),
            )

    def test_dual_field_independent_goals(self):
        playlist = player._build_entry_s0_playlist(5, ["A", "B"])
        self.assertEqual(len(playlist), 50)
        step = playlist[0]
        self.assertIn("A", step.get("field_screens") or {})
        self.assertIn("B", step.get("field_screens") or {})
        # 5 unique images per field × 2 fields.
        self.assertEqual(len(step.get("screen_images") or {}), 10)


if __name__ == "__main__":
    unittest.main()
