"""High Performance S0 Players (operator C1): Elite passes + offside traps."""

from __future__ import annotations

import os
import re
import sys
import unittest
from collections import Counter
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import smart_simust_player as player  # noqa: E402


def _arena(sid: str) -> int:
    match = re.search(r"(\d+)$", str(sid or ""))
    return int(match.group(1)) if match else 0


class HighPerformancePlayersTests(unittest.TestCase):
    def test_component_label_puts_players_on_c1(self):
        self.assertEqual(
            player._component_set_label("L03-HighPerformance/S0.T1"),
            "C1.T1",
        )
        self.assertEqual(
            player._component_set_label("L03-HighPerformance/S1.T1"),
            "C2.T1",
        )
        self.assertEqual(
            player._component_set_label("L03-HighPerformance/S2.T1"),
            "C3.T1",
        )
        self.assertEqual(
            player._component_set_label("L03-HighPerformance/S3.T1"),
            "C4.T1",
        )
        self.assertEqual(
            player._content_type_label("L03-HighPerformance/S0.T1"),
            "Players",
        )

    def test_opening_card(self):
        text = player._level_card_text(
            "L03-HighPerformance/S0.T1",
            "",
            {"test_num": 1, "actions_in_set": 10, "finish_balls": True},
            [],
        )
        self.assertEqual(text.split("\n"), ["Players", "C1.T1", "10 Actions"])

    def test_offside_table_posts_and_pass_targets(self):
        expected = (
            (5, None, 2, 6, 1, 2),
            (None, 2, 5, 1, 6, 5),
            (5, 2, 6, 1, None, 6),
            (5, 2, 1, 6, None, 1),
            (5, None, 2, 6, 1, 2),
            (None, 2, 5, 1, 6, 5),
        )
        self.assertEqual(player.HP_PLAYERS_OFFSIDE_TABLE, expected)
        for row in expected:
            seat, goal = player._hp_players_offside_seat(row)
            self.assertEqual(seat[3], "left_post.jpeg")
            self.assertEqual(seat[4], "right_post.jpeg")
            self.assertEqual(seat[goal], "Teammate-PL-06-05-B.png")
            self.assertEqual(goal, row[-1])

    def test_t1_has_four_traps_and_t3_has_six(self):
        self.assertEqual(player._hp_players_offside_count(1), 4)
        self.assertEqual(player._hp_players_offside_count(2), 4)
        self.assertEqual(player._hp_players_offside_count(3), 6)
        self.assertEqual(player._hp_players_offside_count(5), 6)

    def test_c1_t1_mixes_ap_traps_and_normal_passes(self):
        with patch.object(player.random, "shuffle", side_effect=lambda seq: None):
            playlist = player._build_high_performance_s0_playlist(1, ["A", "B"])
        self.assertEqual(len(playlist), 50)
        first = [row for row in playlist if row["test_num"] == 1]
        self.assertEqual(len(first), 10)
        trap_count = sum(1 for row in first if row.get("offside_trap"))
        ap_count = sum(1 for row in first if row.get("aep_dual_pass"))
        self.assertEqual(ap_count, 3)
        self.assertEqual(trap_count, 4)
        self.assertEqual(
            sum(
                1
                for row in first
                if not row.get("offside_trap") and not row.get("aep_dual_pass")
            ),
            3,
        )
        # T1: AP block first in order.
        self.assertEqual(
            [bool(r.get("aep_dual_pass")) for r in first[:3]],
            [True, True, True],
        )
        for row in first:
            self.assertTrue(row["finish_balls"])
            self.assertEqual(row["action"], "PASS")
            self.assertEqual(int(row.get("results_on_screen") or 0), 3)
            self.assertEqual(int(row.get("fac_on_screen") or 0), 4)
            self.assertFalse(row.get("offside_trap") and row.get("aep_dual_pass"))
            seats_a = {
                _arena(sid): os.path.basename(path)
                for sid, path in row["screen_images"].items()
                if str(sid).startswith("A")
            }
            seats_b = {
                _arena(sid): os.path.basename(path)
                for sid, path in row["screen_images"].items()
                if str(sid).startswith("B")
            }
            self.assertEqual(seats_a, seats_b)
            goals = [_arena(sid) for sid in row["field_screens"]["A"]]
            if row.get("offside_trap"):
                self.assertEqual(len(goals), 1)
                self.assertEqual(seats_a[3], "left_post.jpeg")
                self.assertEqual(seats_a[4], "right_post.jpeg")
                self.assertEqual(seats_a[goals[0]], "Teammate-PL-06-05-B.png")
            elif row.get("aep_dual_pass"):
                self.assertEqual(len(goals), 2)
                self.assertEqual(len(seats_a), 6)
                self.assertEqual(seats_a[goals[0]], "pass.png")
                self.assertEqual(seats_a[goals[1]], "pass-copy.png")
            else:
                self.assertEqual(len(goals), 1)
                self.assertEqual(len(seats_a), 6)
                self.assertEqual(seats_a[goals[0]], "pass.png")
                names = set(seats_a.values())
                self.assertIn("Teammate-PL-01-B.png", names)
            for path in row["screen_images"].values():
                self.assertTrue(os.path.isfile(path))
            # No pass-left / pass-right on HP.
            for path in row["screen_images"].values():
                name = os.path.basename(path).lower()
                self.assertNotIn("pass-left", name)
                self.assertNotIn("pass-right", name)

    def test_c1_t3_ap_reduces_traps_so_they_never_overlap(self):
        with patch.object(player.random, "shuffle", side_effect=lambda seq: None):
            playlist = player._build_high_performance_s0_playlist(3, ["A"])
        first = [row for row in playlist if row["test_num"] == 1]
        self.assertEqual(len(first), 10)
        traps = [row for row in first if row.get("offside_trap")]
        ap_rows = [row for row in first if row.get("aep_dual_pass")]
        # 50% AP (5) + traps on remaining seats (5), never overlapping.
        self.assertEqual(len(ap_rows), 5)
        self.assertEqual(len(traps), 5)
        for row in first:
            self.assertFalse(row.get("offside_trap") and row.get("aep_dual_pass"))
            if not row.get("offside_trap"):
                self.assertEqual(len(row.get("screen_images") or {}), 6)
        goals = Counter(
            _arena(row["field_screens"]["A"][0]) for row in traps
        )
        # First five table goals: 2,5,6,1,2
        self.assertEqual(goals[2], 2)
        self.assertEqual(goals[5], 1)
        self.assertEqual(goals[6], 1)
        self.assertEqual(goals[1], 1)

    def test_non_offside_may_use_screens_3_and_4(self):
        used = False
        for series in (1, 3, 5):
            playlist = player._build_high_performance_s0_playlist(series, ["A"])
            for row in playlist:
                if row.get("offside_trap"):
                    continue
                images = row.get("screen_images") or {}
                if "A3" in images or "A4" in images:
                    used = True
                    break
            if used:
                break
        self.assertTrue(used)


if __name__ == "__main__":
    unittest.main()
