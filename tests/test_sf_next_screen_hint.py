"""Foundation SF-30N…180N: 1s awareness flash on the next pass screen."""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import smart_simust_player as player  # noqa: E402


class SfNextScreenHintTests(unittest.TestCase):
    def test_scripted_playlist_marks_next_screen_hint(self):
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, "pass.png"), "wb").close()
            playlist = player._build_scripted_sf_playlist(
                "SF-30N", player.SF30N_SCRIPT, ["A", "B"], folder,
            )
            self.assertEqual(len(playlist), 50)
            self.assertTrue(all(item.get("next_screen_hint") for item in playlist))
            self.assertTrue(all(item.get("advance_on_goal") for item in playlist))

    def test_hint_targets_next_same_test_screen(self):
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, "pass.png"), "wb").close()
            playlist = player._build_scripted_sf_playlist(
                "SF-30N", player.SF30N_SCRIPT, ["A"], folder,
            )
            # SF-30N T1: (1,1) then (2,2) …
            fields, arena = player._next_sf_hint_targets(playlist, 0, ["A"])
            self.assertEqual(arena, 2)
            self.assertEqual(fields, {"A": ["A2"]})

            fields, arena = player._next_sf_hint_targets(playlist, 1, ["A"])
            self.assertEqual(arena, 1)
            self.assertEqual(fields, {"A": ["A1"]})

    def test_no_hint_on_last_action_of_test(self):
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, "pass.png"), "wb").close()
            playlist = player._build_scripted_sf_playlist(
                "SF-30N", player.SF30N_SCRIPT, ["A"], folder,
            )
            # Last action of test 1 is index 9; next entry is test 2.
            fields, arena = player._next_sf_hint_targets(playlist, 9, ["A"])
            self.assertEqual(fields, {})
            self.assertIsNone(arena)

    def test_hint_glyph_is_digit_or_letter(self):
        seen = {player._sf_next_hint_glyph(2) for _ in range(40)}
        self.assertTrue(any(g.isdigit() for g in seen))
        self.assertTrue(any(g.isalpha() for g in seen))
        for glyph in seen:
            self.assertEqual(len(glyph), 1)


if __name__ == "__main__":
    unittest.main()
