"""Activated and High Performance number playlists."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import smart_simust_player as player  # noqa: E402


class ActivatedPlaylistTests(unittest.TestCase):
    def setUp(self):
        self._render = player._render_entry_digit_image
        player._render_entry_digit_image = lambda text, bg=None: f"img:{text}:{bg}"

    def tearDown(self):
        player._render_entry_digit_image = self._render

    def test_set1_test1_passes_lowest_then_clears_it(self):
        playlist = player._build_activated_playlist(1, ["A", "B"])
        self.assertEqual(len(playlist), 30)
        first = playlist[0]
        self.assertEqual(first["test_num"], 1)
        self.assertEqual(first["field_screens"]["A"], [12])
        self.assertEqual(first["field_screens"]["B"], [5])
        self.assertIn("img:10:", first["screen_images"][12])
        self.assertEqual(first["screen_images"][12], first["screen_images"][5])
        self.assertEqual(len(first["screen_images"]), 12)
        second = playlist[1]
        shown = {path.split(":")[1] for path in second["screen_images"].values()}
        self.assertNotIn("10", shown)
        self.assertIn("20", shown)
        self.assertEqual(second["field_screens"]["A"], [4])

    def test_test2_order_uses_numeric_value_not_text(self):
        playlist = player._build_activated_playlist(1, ["A"])
        test2 = [step for step in playlist if step["test_num"] == 2]
        goals = []
        for step in test2:
            sid = step["field_screens"]["A"][0]
            text = step["screen_images"][sid].split(":")[1]
            goals.append(text)
        self.assertEqual(goals, ["01", "3", "06", "7", "08", "11"])

    def test_test3_keeps_the_same_numbers_when_shuffled(self):
        def reverse(seq):
            seq.reverse()

        original = player.random.shuffle
        player.random.shuffle = reverse
        try:
            playlist = player._build_activated_playlist(1, ["A"])
        finally:
            player.random.shuffle = original
        test3 = [step for step in playlist if step["test_num"] == 3]
        shown = set()
        for step in test3:
            for path in step["screen_images"].values():
                shown.add(path.split(":")[1])
        self.assertEqual(shown, {"22", "16", "12", "17", "21", "13"})
        self.assertEqual(test3[0]["field_screens"]["A"], [2])

    def test_later_sets_repeat_numbers_and_get_faster(self):
        first = player._build_activated_playlist(1, ["A"])
        second = player._build_activated_playlist(2, ["A"])
        fifth = player._build_activated_playlist(5, ["B"])
        self.assertEqual(
            first[0]["screen_images"][12].split(":")[1],
            second[0]["screen_images"][12].split(":")[1],
        )
        self.assertLess(second[0]["on_ms"], first[0]["on_ms"])
        self.assertLess(fifth[0]["on_ms"], second[0]["on_ms"])
        self.assertAlmostEqual(second[0]["on_ms"] / first[0]["on_ms"], 0.9, delta=0.02)
        self.assertEqual(fifth[0]["field_screens"]["B"], [5])
        self.assertNotIn("A", fifth[0]["field_screens"])

    def test_high_performance_clears_lowest_and_changes_color_each_test(self):
        def sample(population, k):
            return list(population)[:k]

        original = player.random.sample
        player.random.sample = sample
        try:
            playlist = player._build_high_performance_playlist(1, ["A", "B"])
        finally:
            player.random.sample = original
        self.assertEqual(len(playlist), 30)
        self.assertIn("img:1:", playlist[0]["screen_images"][12])
        self.assertEqual(playlist[0]["screen_images"][12], playlist[0]["screen_images"][5])
        color_1 = playlist[0]["screen_images"][12].rsplit(":", 1)[-1]
        color_2 = playlist[6]["screen_images"][12].rsplit(":", 1)[-1]
        self.assertNotEqual(color_1, color_2)
        colors = {step["screen_images"][next(iter(step["screen_images"]))].rsplit(":", 1)[-1]
                  for step in playlist if step["action_in_set"] == 1}
        self.assertEqual(len(colors), 5)
        for step in playlist:
            if step["test_num"] != 1:
                continue
            for path in step["screen_images"].values():
                self.assertTrue(path.endswith(color_1))


if __name__ == "__main__":
    unittest.main()
