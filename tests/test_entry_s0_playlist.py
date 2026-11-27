"""Entry S0.T1–T5: warehouse stills — rebound goals, unique person tags, 4 lit."""

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


def _under_warehouse(path: str) -> bool:
    root = os.path.normcase(os.path.normpath(player.PLAYERS_IMAGE_WAREHOUSE_ROOT))
    return os.path.normcase(os.path.normpath(path)).startswith(root)


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

    def test_warehouse_catalog_roles(self):
        cat = player._players_warehouse_catalog()
        for role in (
            "rebound",
            "opponent",
            "teammate",
            "cross_left",
            "cross_right",
            "asking",
            "defender",
        ):
            self.assertGreater(len(cat.get(role) or []), 0, role)

    def test_t1_pool_uses_warehouse_rebound(self):
        pass_path, distractors = player._entry_s0_image_paths(1)
        self.assertTrue(pass_path and os.path.isfile(pass_path))
        self.assertTrue(_under_warehouse(pass_path))
        self.assertIn("teammate-pl-", os.path.basename(pass_path).lower())
        self.assertEqual(len(distractors), 3)
        for path in distractors:
            self.assertTrue(_under_warehouse(path))
            self.assertIn("opponent-pl-", os.path.basename(path).lower())

    def test_t3_pool_can_include_teammate_distractor(self):
        pass_path, distractors = player._entry_s0_image_paths(3)
        self.assertTrue(pass_path)
        self.assertEqual(len(distractors), 3)
        names = [os.path.basename(p).lower() for p in distractors]
        self.assertTrue(any(n.startswith("teammate-pl-") for n in names))
        self.assertTrue(any(n.startswith("opponent-pl-") for n in names))

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
        self.assertTrue(playlist[0].get("warehouse_images"))

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

    def test_always_four_lit_screens_rebound_goals(self):
        playlist = player._build_entry_s0_playlist(1, ["A"])
        for step in playlist:
            self.assertTrue(step.get("finish_balls"))
            self.assertFalse(step.get("entry_digits"))
            self.assertEqual(int(step.get("results_on_screen") or 0), 3)
            self.assertEqual(int(step.get("fac_on_screen") or 0), 4)
            goals = (step.get("field_screens") or {}).get("A") or []
            images = step.get("screen_images") or {}
            self.assertEqual(len(images), 4, step.get("label"))
            for path in images.values():
                self.assertTrue(_under_warehouse(path), path)
                self.assertNotIn("pass.png", os.path.basename(path).lower())
            if step.get("aep_dual_pass"):
                self.assertEqual(len(goals), 2)
                halves = {
                    player._activated_s0_side_half(_arena_from_sid(goals[0])),
                    player._activated_s0_side_half(_arena_from_sid(goals[1])),
                }
                self.assertEqual(halves, {"L", "R"})
            else:
                self.assertEqual(len(goals), 1)
            for sid in goals:
                name = os.path.basename(images[sid]).lower()
                self.assertTrue(
                    name.startswith("teammate-pl-"),
                    f"goal {sid} should be rebound teammate: {name}",
                )
                self.assertTrue("-02-" in name or "-05-" in name, name)

    def test_unique_person_ids_per_action(self):
        for series in (1, 3, 5):
            playlist = player._build_entry_s0_playlist(series, ["A", "B"])
            for step in playlist:
                people = list((step.get("person_ids") or {}).values())
                self.assertEqual(
                    len(people),
                    len(set(people)),
                    f"duplicate person in {step.get('label')}: {people}",
                )
                self.assertEqual(len(people), len(step.get("screen_images") or {}))

    def test_goal_never_opponent_or_neutral_only(self):
        playlist = player._build_entry_s0_playlist(2, ["A"])
        for step in playlist:
            images = step.get("screen_images") or {}
            for sid in (step.get("field_screens") or {}).get("A") or []:
                name = os.path.basename(images[sid]).lower()
                self.assertFalse(name.startswith("opponent-pl-"), name)
                # Neutral teammate without rebound suffix is not a goal.
                if name.startswith("teammate-pl-") and name.count("-") <= 3:
                    self.fail(f"neutral teammate used as goal: {name}")

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
