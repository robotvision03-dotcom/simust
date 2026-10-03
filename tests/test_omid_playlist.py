"""Foundation omid: High Performance numbers, lowest first, advance on a goal."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import smart_simust_player as player  # noqa: E402


class OmidPlaylistTests(unittest.TestCase):
    def setUp(self):
        self._render = player._render_entry_digit_image
        player._render_entry_digit_image = lambda text, bg=None: f"digit-{text}"

    def tearDown(self):
        player._render_entry_digit_image = self._render

    def test_numbers_run_lowest_to_highest_and_wait_for_the_goal(self):
        playlist = player._build_omid_playlist(["A"])
        self.assertEqual(len(playlist), 30)
        for test_num in range(1, 6):
            steps = [item for item in playlist if item["test_num"] == test_num]
            self.assertEqual(len(steps), 6)
            numbers = []
            for item in steps:
                self.assertTrue(item["advance_on_goal"])
                self.assertTrue(item["skip_gap"])
                self.assertEqual(item["on_ms"], 8000)
                self.assertEqual(item["efficiency_max_sec"], 8.0)
                numbers.append(int(str(item["label"]).split("number ")[1].split()[0]))
            self.assertEqual(numbers, sorted(numbers))
            self.assertNotIn("budget_ms", steps[0])

    def test_omid_2_shares_twelve_seconds_across_six_actions(self):
        playlist = player._build_omid_playlist(["A"], name="omid_2", budget_ms=17000)
        self.assertEqual(len(playlist), 30)
        for test_num in range(1, 6):
            steps = [item for item in playlist if item["test_num"] == test_num]
            self.assertEqual(len(steps), 6)
            self.assertTrue(all(item["budget_ms"] == 17000 for item in steps))
            self.assertTrue(all(item["advance_on_goal"] for item in steps))
            numbers = [
                int(str(item["label"]).split("number ")[1].split()[0])
                for item in steps
            ]
            self.assertEqual(numbers, sorted(numbers))
