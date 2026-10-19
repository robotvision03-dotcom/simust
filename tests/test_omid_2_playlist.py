"""Foundation omid_2: same scenario as SF-30N / omid, coded .player (not .ssav)."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import smart_simust_player as player  # noqa: E402


class Omid2PlaylistTests(unittest.TestCase):
    def _sample_player(self):
        for path in (
            os.path.join(ROOT, "static", "players", "teammate_asking.player"),
            os.path.join(ROOT, "static", "siamak_files", "teammate_asking.player"),
        ):
            if os.path.isfile(path):
                return path
        return None

    def test_omid_2_matches_sf30n_with_player(self):
        sample = self._sample_player()
        if not sample:
            self.skipTest("teammate_asking.player not in static/")
        with tempfile.TemporaryDirectory() as folder:
            dest = os.path.join(folder, "teammate_asking.player")
            shutil.copy2(sample, dest)
            playlist = player._build_omid_2_playlist(["A"], directory=folder)
            self.assertEqual(len(playlist), 50)
            self.assertTrue(all(item.get("screen_player") == dest for item in playlist))
            self.assertTrue(all(item.get("screen_ssav") in (None, "") for item in playlist))
            self.assertTrue(all(item.get("player_loop") for item in playlist))
            self.assertTrue(
                all(
                    str(path).endswith(".player")
                    for item in playlist
                    for path in (item.get("screen_images") or {}).values()
                )
            )
            first = playlist[0]
            self.assertEqual(first["on_ms"], player.SF_SCRIPTED_ON_MS)
            self.assertEqual(first["gap_ms"], player.SF_SCRIPTED_GAP_MS)
            self.assertEqual(first["foundation_sf"], "omid_2")
            self.assertEqual(
                [item["arena_pair"] for item in playlist if item["test_num"] == 1],
                list(player._SF30_T1),
            )
            self.assertTrue(first.get("finish_balls"))
            self.assertEqual(first.get("budget_ms"), 30000)

    def test_find_pass_player_falls_back_to_static(self):
        sample = self._sample_player()
        if not sample:
            self.skipTest("teammate_asking.player not in static/")
        with tempfile.TemporaryDirectory() as folder:
            hit = player._find_pass_player(folder)
            self.assertTrue(hit and hit.lower().endswith(".player"))
            self.assertTrue(os.path.isfile(hit))

    def test_omid_2_mode_detected_before_omid(self):
        self.assertEqual(
            player._detect_foundation_extra_mode(r"C:\x\L00-Foundation-Challenge\omid_2"),
            "omid_2",
        )
        self.assertEqual(
            player._detect_foundation_extra_mode(r"C:\x\L00-Foundation-Challenge\omid"),
            "omid",
        )


if __name__ == "__main__":
    unittest.main()
