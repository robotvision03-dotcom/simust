"""Activated S0.T1–T5 Players: C1.T1–T2 30% AP in order / C1.T3–T5 50% random."""

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

    def test_ap_fraction_by_series(self):
        self.assertEqual(player._players_ap_count(10, 1), 3)
        self.assertEqual(player._players_ap_count(10, 2), 3)
        self.assertEqual(player._players_ap_count(10, 3), 5)
        self.assertEqual(player._players_ap_count(10, 5), 5)

    def test_t1_ap_actions_come_in_order(self):
        plan = player._players_ap_plan(10, 1)
        self.assertEqual(plan, [True, True, True, False, False, False, False, False, False, False])

    def test_t3_ap_plan_is_shuffled(self):
        seen = set()
        for _ in range(40):
            plan = tuple(player._players_ap_plan(10, 3))
            self.assertEqual(sum(1 for x in plan if x), 5)
            seen.add(plan)
        self.assertGreater(len(seen), 1)

    def test_about_30_percent_actions_are_ap_on_t1(self):
        playlist = player._build_activated_s0_playlist(1, ["A"])
        self.assertEqual(len(playlist), 50)
        by_test = {}
        for step in playlist:
            by_test.setdefault(int(step.get("test_num") or 0), []).append(step)
        for test_num, steps in by_test.items():
            self.assertEqual(len(steps), 10, f"test {test_num}")
            ap_flags = [bool(s.get("aep_dual_pass")) for s in steps]
            self.assertEqual(sum(1 for x in ap_flags if x), 3)
            # T1–T2: AP block first, then normal.
            self.assertEqual(ap_flags[:3], [True, True, True])
            self.assertEqual(ap_flags[3:], [False] * 7)
            for step in steps:
                self.assertTrue(step.get("finish_balls"))
                self.assertFalse(step.get("side_goals"))
                self.assertEqual(int(step.get("results_on_screen") or 0), 3)
                self.assertEqual(int(step.get("fac_on_screen") or 0), 4)
                images = step.get("screen_images") or {}
                self.assertEqual(len(images), 5, step.get("label"))
                goals = (step.get("field_screens") or {}).get("A") or []
                if step.get("aep_dual_pass"):
                    self.assertEqual(len(goals), 2)
                    halves = {
                        player._activated_s0_side_half(_arena_from_sid(goals[0])),
                        player._activated_s0_side_half(_arena_from_sid(goals[1])),
                    }
                    self.assertEqual(halves, {"L", "R"})
                else:
                    self.assertEqual(len(goals), 1)
                    self.assertFalse(step.get("ap_action"))
                # No pass-left / pass-right on Activated.
                for path in images.values():
                    name = os.path.basename(path).lower()
                    self.assertNotIn("pass-left", name)
                    self.assertNotIn("pass-right", name)

    def test_about_50_percent_actions_are_ap_on_t3(self):
        playlist = player._build_activated_s0_playlist(3, ["A"])
        by_test = {}
        for step in playlist:
            by_test.setdefault(int(step.get("test_num") or 0), []).append(step)
        for test_num, steps in by_test.items():
            ap_n = sum(1 for s in steps if s.get("aep_dual_pass"))
            self.assertEqual(ap_n, 5, f"test {test_num} should have 5/10 AP actions")
            for step in steps:
                self.assertEqual(len(step.get("screen_images") or {}), 5)
                self.assertFalse(step.get("side_goals"))

    def test_pass_and_copy_on_opposite_halves_for_ap_only(self):
        playlist = player._build_activated_s0_playlist(2, ["A"])
        ap_steps = [s for s in playlist if s.get("aep_dual_pass")]
        self.assertTrue(ap_steps)
        for step in ap_steps:
            goals = (step.get("field_screens") or {}).get("A") or []
            self.assertEqual(len(goals), 2)
            halves = {
                player._activated_s0_side_half(_arena_from_sid(goals[0])),
                player._activated_s0_side_half(_arena_from_sid(goals[1])),
            }
            self.assertEqual(halves, {"L", "R"})

    def test_may_light_screens_3_and_4_during_play(self):
        playlist = player._build_activated_s0_playlist(1, ["A"])
        used_3_or_4 = False
        for step in playlist:
            images = step.get("screen_images") or {}
            if "A3" in images or "A4" in images:
                used_3_or_4 = True
                break
        self.assertTrue(used_3_or_4)

    def test_dual_field_independent_side_goals(self):
        playlist = player._build_activated_s0_playlist(3, ["A", "B"])
        self.assertEqual(len(playlist), 50)
        step = playlist[0]
        self.assertIn("A", step.get("field_screens") or {})
        self.assertIn("B", step.get("field_screens") or {})
        self.assertEqual(len(step.get("screen_images") or {}), 10)

    def test_goal_sid_preserves_side_for_cue(self):
        self.assertEqual(player._named_goal_screens(["A2L"])[0], "A2L")
        self.assertEqual(player._sid("A2L"), "A2")

    def test_side_goal_token_match(self):
        # Helper still understands L/R tokens for Elite.
        self.assertTrue(hasattr(player, "_activated_s0_side_for_pass"))


class ApFacMetricTests(unittest.TestCase):
    def test_mode2_sim_na_winning_screen_uses_first_goal(self):
        """Mode 2 Correct + winning_screen=N/A must still yield AP/FAP sides."""
        from app import compute_aep_fac_from_results

        rows = [
            {
                "video_index": 1,
                "field": "A",
                "result": "Correct",
                "winning_screen": "N/A",
                "screens": ["A2", "A5"],
                "aep_dual_pass": True,
                "mode2_sim": True,
            },
            {
                "video_index": 1,
                "field": "A",
                "result": "Correct",
                "winning_screen": "N/A",
                "screens": ["A6", "A1"],
                "aep_dual_pass": True,
                "mode2_sim": True,
            },
            {
                "video_index": 1,
                "field": "A",
                "result": "Correct",
                "winning_screen": "N/A",
                "screens": ["A5"],
                "aep_dual_pass": False,
                "mode2_sim": True,
            },
        ]
        pref = compute_aep_fac_from_results(rows)
        self.assertEqual(pref["aep_total"], 2)
        self.assertEqual(pref["aep_left_n"], 1)  # A2
        self.assertEqual(pref["aep_right_n"], 1)  # A6
        self.assertEqual(pref["fac_display"], "FAP Left")
        self.assertTrue(pref["show_ap_fac"])

    def test_dual_screens_count_as_ap_even_when_flag_false(self):
        from app import compute_aep_fac_from_results

        rows = [
            {
                "video_index": 1,
                "field": "A",
                "result": "Correct",
                "winning_screen": "A1",
                "screens": ["A1", "A6"],
                "aep_dual_pass": False,
                "mode2_sim": True,
            },
            {
                "video_index": 1,
                "field": "A",
                "result": "Correct",
                "winning_screen": "A5",
                "screens": ["A5"],
                "aep_dual_pass": False,
                "mode2_sim": True,
            },
        ]
        pref = compute_aep_fac_from_results(rows)
        self.assertEqual(pref["aep_total"], 1)
        self.assertEqual(pref["aep_left_n"], 1)
        self.assertEqual(pref["fac_display"], "FAP Left")

    def test_labeled_action_cue_writes_aep_dual_pass(self):
        import json
        import tempfile
        from pathlib import Path
        import smart_simust_player as sp

        with tempfile.TemporaryDirectory() as tmp:
            cue_path = str(Path(tmp) / "image_action_cue.json")
            old = sp.IMAGE_ACTION_CUE_FILE
            sp.IMAGE_ACTION_CUE_FILE = cue_path
            try:
                sp._write_image_action_cue(
                    True,
                    {"A": ["A1", "A6"]},
                    seq=3,
                    action="PASS",
                    finish_balls=True,
                    aep_dual_pass=True,
                    ap_action=True,
                    keep_other_fields=False,
                )
                data = json.loads(Path(cue_path).read_text(encoding="utf-8"))
            finally:
                sp.IMAGE_ACTION_CUE_FILE = old
        self.assertTrue(data.get("aep_dual_pass"))
        self.assertTrue(data.get("ap_action"))
        field_a = (data.get("fields") or {}).get("A") or {}
        self.assertTrue(field_a.get("aep_dual_pass"))
        self.assertEqual(field_a.get("screens"), ["A1", "A6"])

    def test_ap_counts_raw_left_right_not_fifty_fifty(self):
        from app import compute_aep_fac_from_results, build_results_ring_panel
        from app import summarize_results_section_metrics, _arena_screen_index
        from smart_simust_player import _result_ring_specs

        self.assertEqual(_arena_screen_index("3", field="A"), 5)
        self.assertEqual(_arena_screen_index("A5", field="A"), 5)
        self.assertEqual(_arena_screen_index("12", field="A"), 1)

        rows = [
            {"video_index": 1, "field": "A", "result": "Correct",
             "winning_screen": "A1", "screens": ["A1", "A5"], "aep_dual_pass": True},
            {"video_index": 1, "field": "A", "result": "Correct",
             "winning_screen": "A2", "screens": ["A2", "A6"], "aep_dual_pass": True},
            {"video_index": 1, "field": "A", "result": "Correct",
             "winning_screen": "12", "screens": ["A1", "A5"], "aep_dual_pass": True},
            {"video_index": 1, "field": "A", "result": "Correct",
             "winning_screen": "13", "screens": ["A2", "A6"], "aep_dual_pass": True},
            {"video_index": 1, "field": "A", "result": "Correct",
             "winning_screen": "3", "screens": ["A1", "A5"], "aep_dual_pass": True},
            {"video_index": 1, "field": "A", "result": "Correct",
             "winning_screen": "4", "screens": ["A2", "A6"], "aep_dual_pass": True},
            {"video_index": 1, "field": "A", "result": "Correct",
             "winning_screen": "A5", "screens": ["A5"], "aep_dual_pass": False},
        ]
        pref = compute_aep_fac_from_results(rows)
        self.assertEqual(pref["aep_left_n"], 4)
        self.assertEqual(pref["aep_right_n"], 2)
        self.assertAlmostEqual(pref["aep_left"], 100.0 * 4 / 6, places=3)
        self.assertAlmostEqual(pref["aep_right"], 100.0 * 2 / 6, places=3)
        self.assertEqual(pref["aep_display"], "R33% / L67%")
        self.assertEqual(pref["fac_display"], "FAP Left")
        self.assertTrue(pref["show_ap_fac"])
        panel = build_results_ring_panel(summarize_results_section_metrics(rows), "A")
        self.assertTrue(panel.get("show_ap_fac"))
        self.assertEqual(panel.get("slice_ap"), "A3")
        self.assertEqual(panel.get("slice_fac"), "A4")
        specs = _result_ring_specs(panel)
        self.assertEqual(specs["A3"]["lines"], ["R33% / L67%"])
        self.assertEqual(specs["A3"]["label"], "AP")
        self.assertEqual(specs["A4"]["lines"], ["FAP Left"])
        self.assertEqual(specs["A4"]["label"], "FAP")


if __name__ == "__main__":
    unittest.main()
