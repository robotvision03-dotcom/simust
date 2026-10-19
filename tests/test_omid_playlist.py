"""Foundation omid: same scenario as SF-30N, coded pass .ssav (not the mp4)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import smart_simust_player as player  # noqa: E402


class OmidPlaylistTests(unittest.TestCase):
    def _fake_ssav(self, folder):
        path = os.path.join(folder, "pass_pixels.ssav")
        with open(path, "wb") as handle:
            handle.write(b"SSAV1")
            handle.write(b"\x00" * 16)
        return path

    def test_omid_matches_sf30n_scenario_with_ssav(self):
        with tempfile.TemporaryDirectory() as folder:
            ssav = self._fake_ssav(folder)
            playlist = player._build_omid_playlist(["A"], directory=folder)
            self.assertEqual(len(playlist), 50)
            self.assertTrue(all(item.get("screen_ssav") == ssav for item in playlist))
            self.assertTrue(all(item.get("screen_video") is None for item in playlist))
            self.assertTrue(
                all(
                    str(path).endswith(".ssav")
                    for item in playlist
                    for path in (item.get("screen_images") or {}).values()
                )
            )
            first = playlist[0]
            self.assertEqual(first["on_ms"], player.SF_SCRIPTED_ON_MS)
            self.assertEqual(first["gap_ms"], player.SF_SCRIPTED_GAP_MS)
            self.assertEqual(first["arena_pair"], (1, 1))
            self.assertEqual(
                [item["arena_pair"] for item in playlist if item["test_num"] == 1],
                list(player._SF30_T1),
            )
            # Same finish-balls stamp as SF-30N scripted playlists.
            self.assertTrue(first.get("finish_balls"))
            self.assertEqual(first.get("budget_ms"), 30000)

    def test_sf30n_still_uses_pass_image_not_ssav(self):
        with tempfile.TemporaryDirectory() as folder:
            jpeg = os.path.join(folder, "pass.jpeg")
            open(jpeg, "wb").close()
            self._fake_ssav(folder)
            playlist = player._build_scripted_sf_playlist(
                "SF-30N", player.SF30N_SCRIPT, ["A"], folder,
            )
            self.assertEqual(len(playlist), 50)
            self.assertTrue(
                all(
                    str(path).endswith((".jpeg", ".jpg", ".png"))
                    for item in playlist
                    for path in (item.get("screen_images") or {}).values()
                )
            )
            self.assertTrue(all(not item.get("screen_ssav") for item in playlist))


class PassSsavConvertTests(unittest.TestCase):
    def test_convert_writes_readable_ssav(self):
        import screen_saver_anim as anim

        sample = os.path.join(
            os.path.expanduser("~"),
            "Documents",
            "simust_player",
            "L00-Foundation-Challenge",
            "omid",
            "pass.mp4",
        )
        if not os.path.isfile(sample):
            self.skipTest("omid pass.mp4 not on this machine")
        with tempfile.TemporaryDirectory() as folder:
            dest = os.path.join(folder, "pass_pixels.ssav")
            out = anim.convert_video_to_ssav(sample, dest)
            self.assertEqual(out, dest)
            frames, interval = anim.load_ssav_pixels_file(dest)
            self.assertGreater(len(frames), 10)
            self.assertGreaterEqual(interval, 16)


if __name__ == "__main__":
    unittest.main()
