"""Entry S0.T1–T5: pass goal among static player PNGs — 4 lit screens always."""

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
                "Opponent-PL-01-B.png",
                "Opponent-PL-03-B.png",
            },
        )

    def test_t3_pool_adds_extra_players(self):
        pass_path, distractors = player._entry_s0_image_paths(3)
        self.assertTrue(pass_path)
        self.assertEqual(len(distractors), 4)
        names = {os.path.basename(p) for p in distractors}
        self.assertIn("Opponent-PL-02-B.png", names)
        self.assertIn("Teammate-PL-01-B.png", names)

    def test_playlist_has_ten_actions_and_larger_scale(self):
        playlist = player._build_entry_s0_playlist(1, ["A"])
        self.assertEqual(len(playlist), 50)  # 5 tests × 10 actions
        self.assertEqual(playlist[0].get("actions_in_set"), 10)
        self.assertAlmostEqual(
            float(playlist[0].get("pass_image_scale") or 0),
            player.ENTRY_S0_PASS_IMAGE_SCALE,
            places=4,
        )
        self.assertTrue(playlist[0].get("uniform_player_stills"))

    def test_ap_fraction_t1_30_t3_50(self):
        for series, want in ((1, 3), (3, 5)):
            playlist = player._build_entry_s0_playlist(series, ["A"])
            by_test = {}
            for step in playlist:
                by_test.setdefault(int(step.get("test_num") or 0), []).append(step)
            for test_num, steps in by_test.items():
                ap_n = sum(1 for s in steps if s.get("aep_dual_pass"))
                self.assertEqual(ap_n, want, f"C1.T{series} test {test_num}")

    def test_t1_ap_actions_come_in_order(self):
        playlist = player._build_entry_s0_playlist(1, ["A"])
        by_test = {}
        for step in playlist:
            by_test.setdefault(int(step.get("test_num") or 0), []).append(step)
        for test_num, steps in by_test.items():
            flags = [bool(s.get("aep_dual_pass")) for s in steps]
            self.assertEqual(flags[:3], [True, True, True], f"test {test_num}")
            self.assertEqual(flags[3:], [False] * 7)

    def test_always_four_lit_screens(self):
        playlist = player._build_entry_s0_playlist(1, ["A"])
        pass_path = os.path.join(player.ENTRY_S0_IMAGE_DIR, player.ENTRY_S0_PASS_NAME)
        for step in playlist:
            self.assertTrue(step.get("finish_balls"))
            self.assertFalse(step.get("entry_digits"))
            self.assertEqual(int(step.get("results_on_screen") or 0), 3)
            self.assertEqual(int(step.get("fac_on_screen") or 0), 4)
            goals = (step.get("field_screens") or {}).get("A") or []
            images = step.get("screen_images") or {}
            self.assertEqual(len(images), 4, step.get("label"))
            if step.get("aep_dual_pass"):
                self.assertEqual(len(goals), 2)
                halves = {
                    player._activated_s0_side_half(_arena_from_sid(goals[0])),
                    player._activated_s0_side_half(_arena_from_sid(goals[1])),
                }
                self.assertEqual(halves, {"L", "R"})
            else:
                self.assertEqual(len(goals), 1)
                goal = goals[0]
                self.assertEqual(
                    os.path.normcase(images[goal]),
                    os.path.normcase(pass_path),
                )

    def test_may_light_screens_3_and_4_during_play(self):
        used = False
        for series in (1, 3, 5):
            playlist = player._build_entry_s0_playlist(series, ["A"])
            for step in playlist:
                images = step.get("screen_images") or {}
                if "A3" in images or "A4" in images:
                    used = True
                    break
            if used:
                break
        self.assertTrue(used)

    def test_t5_still_four_lit(self):
        playlist = player._build_entry_s0_playlist(5, ["A"])
        self.assertEqual(len(playlist), 50)
        for step in playlist:
            self.assertEqual(len(step.get("screen_images") or {}), 4)

    def test_dual_field_independent_goals(self):
        playlist = player._build_entry_s0_playlist(5, ["A", "B"])
        self.assertEqual(len(playlist), 50)
        step = playlist[0]
        self.assertIn("A", step.get("field_screens") or {})
        self.assertIn("B", step.get("field_screens") or {})
        # 4 lit screens per field × 2 fields.
        self.assertEqual(len(step.get("screen_images") or {}), 8)


if __name__ == "__main__":
    unittest.main()
