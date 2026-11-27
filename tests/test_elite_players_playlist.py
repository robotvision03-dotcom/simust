"""Elite S0 Players (operator C1): dual-field pass1 / pass2 / pass3 game."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import smart_simust_player as player  # noqa: E402


def _basename(path: str) -> str:
    return os.path.basename(str(path or ""))


def _goals(row: dict) -> list:
    out = []
    for fid in ("A", "B"):
        out.extend((row.get("field_screens") or {}).get(fid) or [])
    return out


class ElitePlayersPlaylistTests(unittest.TestCase):
    def test_component_label_puts_players_on_c1(self):
        self.assertEqual(
            player._component_set_label("L04-Elite/S0.T1"),
            "C1.T1",
        )
        self.assertEqual(
            player._component_set_label("L04-Elite/S1.T1"),
            "C2.T1",
        )
        self.assertEqual(
            player._component_set_label("L04-Elite/S2.T1"),
            "C3.T1",
        )
        self.assertEqual(
            player._component_set_label("L04-Elite/S3.T1"),
            "C4.T1",
        )
        self.assertEqual(
            player._content_type_label("L04-Elite/S0.T1"),
            "Players 1",
        )
        self.assertEqual(
            player._content_type_label("L04-Elite/S1.T1"),
            "Numbers",
        )

    def test_opening_card(self):
        text = player._level_card_text(
            "L04-Elite/S0.T1",
            "",
            {"test_num": 1, "actions_in_set": 10, "finish_balls": True},
            [],
        )
        self.assertEqual(text.split("\n"), ["Players 1", "C1.T1", "10 Actions"])

    def test_combined_decision_accepts_elite_players(self):
        decision = player._combined_play_decision(
            ["A"],
            {"A": "L04-Elite/S0.T2"},
        )
        self.assertEqual(decision, ("play", "elite", 2, 0))

    def test_ap_fraction_t1_30_t3_50(self):
        for series, want in ((1, 3), (3, 5)):
            playlist = player._build_elite_s0_playlist(series)
            by_test = {}
            for row in playlist:
                by_test.setdefault(int(row.get("test_num") or 0), []).append(row)
            for test_num, rows in by_test.items():
                ap_n = sum(1 for r in rows if r.get("aep_dual_pass"))
                self.assertEqual(ap_n, want, f"C1.T{series} test {test_num}")

    def test_t1_ap_actions_come_in_order(self):
        playlist = player._build_elite_s0_playlist(1)
        by_test = {}
        for row in playlist:
            by_test.setdefault(int(row.get("test_num") or 0), []).append(row)
        for test_num, rows in by_test.items():
            flags = [bool(r.get("aep_dual_pass")) for r in rows]
            self.assertEqual(flags[:3], [True, True, True], f"test {test_num}")
            self.assertEqual(flags[3:], [False] * 7)

    def test_c1_t1_normal_and_ap_layouts(self):
        with patch.object(player.random, "shuffle", side_effect=lambda seq: None):
            with patch.object(
                player.random,
                "choice",
                side_effect=lambda seq: list(seq)[0],
            ):
                playlist = player._build_elite_s0_playlist(1)
        self.assertEqual(len(playlist), 50)
        first = [row for row in playlist if row["test_num"] == 1]
        self.assertEqual(len(first), 10)
        self.assertEqual(sum(1 for r in first if r.get("aep_dual_pass")), 3)
        for row in first:
            self.assertTrue(row["finish_balls"])
            self.assertTrue(row["combined_field"])
            self.assertEqual(int(row.get("results_on_screen") or 0), 3)
            self.assertEqual(int(row.get("fac_on_screen") or 0), 4)
            goals = _goals(row)
            images = row["screen_images"]
            if row.get("aep_dual_pass"):
                self.assertEqual(len(goals), 2)
                self.assertFalse(row.get("require_all_goals"))
                goal_names = {_basename(images[sid]).lower() for sid in goals}
                for name in goal_names:
                    self.assertTrue(name.startswith("teammate-pl-"), name)
                halves = {
                    player._activated_s0_side_half(
                        int("".join(ch for ch in sid if ch.isdigit()) or 0)
                    )
                    for sid in goals
                }
                self.assertEqual(halves, {"L", "R"})
            else:
                self.assertEqual(len(goals), 1)
                self.assertTrue(row.get("require_all_goals"))
                gname = _basename(images[goals[0]]).lower()
                self.assertTrue(gname.startswith("teammate-pl-") and "-02-" in gname)
                self.assertEqual(len(images), 6)
                self.assertFalse(row.get("side_goals"))
            for path in images.values():
                self.assertTrue(
                    os.path.normcase(path).startswith(
                        os.path.normcase(player.PLAYERS_IMAGE_WAREHOUSE_ROOT)
                    ),
                    path,
                )

    def test_image_counts_t1_6_t2_8_t3_to_t5_12(self):
        for series, expect in ((1, 6), (2, 8), (3, 12), (4, 12), (5, 12)):
            with self.subTest(series=series):
                playlist = player._build_elite_s0_playlist(series)
                row = next(
                    r for r in playlist
                    if r["test_num"] == 1
                    and not r.get("aep_dual_pass")
                    and not r.get("side_goals")
                )
                self.assertEqual(len(row["screen_images"]), expect)
                self.assertEqual(
                    len({_basename(p) for p in row["screen_images"].values()}),
                    expect,
                )

    def test_c1_t3_can_use_pass_left_right_side_goals(self):
        playlist = player._build_elite_s0_playlist(3)
        side_rows = [r for r in playlist if r.get("side_goals")]
        # Side goals only when assets exist; otherwise skip gracefully.
        left = player._elite_side_pass_path(player.ELITE_PLAYERS_PASS_LEFT)
        right = player._elite_side_pass_path(player.ELITE_PLAYERS_PASS_RIGHT)
        if left and right:
            self.assertTrue(side_rows)
            for row in side_rows:
                self.assertFalse(row.get("aep_dual_pass"))
                goals = _goals(row)
                self.assertTrue(goals)
                self.assertTrue(
                    any(str(g).upper().endswith(("L", "R")) for g in goals)
                )
        else:
            self.assertEqual(side_rows, [])

    def test_c1_t1_has_no_side_goals(self):
        playlist = player._build_elite_s0_playlist(1)
        self.assertFalse(any(r.get("side_goals") for r in playlist))

    def test_c1_t4_ap_and_multi_pass_mix(self):
        with patch.object(player.random, "shuffle", side_effect=lambda seq: None):
            playlist = player._build_elite_s0_playlist(4)
        first = [row for row in playlist if row["test_num"] == 1]
        self.assertEqual(len(first), 10)
        ap_rows = [row for row in first if row.get("aep_dual_pass")]
        normal = [row for row in first if not row.get("aep_dual_pass")]
        self.assertEqual(len(ap_rows), 5)
        self.assertEqual(len(normal), 5)
        for row in ap_rows:
            self.assertEqual(len(_goals(row)), 2)
            self.assertFalse(row.get("require_all_goals"))
        for row in normal:
            self.assertTrue(1 <= len(_goals(row)) <= 2)
            self.assertTrue(row.get("require_all_goals"))
            if not row.get("side_goals"):
                self.assertEqual(len(row["screen_images"]), 12)
                goal_names = {
                    _basename(row["screen_images"][sid]) for sid in _goals(row)
                }
                self.assertTrue(
                    goal_names <= {"pass1.png", "pass2.png", "pass3.png"}
                )
                basenames = [_basename(p) for p in row["screen_images"].values()]
                self.assertEqual(len(basenames), len(set(basenames)))

    def test_images_exist_on_disk(self):
        playlist = player._build_elite_s0_playlist(1)
        self.assertTrue(playlist)
        for row in playlist[:3]:
            for path in row["screen_images"].values():
                self.assertTrue(os.path.isfile(path), path)


if __name__ == "__main__":
    unittest.main()
