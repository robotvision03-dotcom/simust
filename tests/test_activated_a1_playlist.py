"""Activated S2.T1..S2.T5 odd-one-out playlists."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import smart_simust_player as player  # noqa: E402


class ActivatedA1PlaylistTests(unittest.TestCase):
    def setUp(self):
        self._render = player._render_entry_digit_image
        player._render_entry_digit_image = lambda text, bg=None: f"img:{text}:{bg}"
        self._randint = player.random.randint
        self._choice = player.random.choice
        self._sample = player.random.sample
        self._random = player.random.random

    def tearDown(self):
        player._render_entry_digit_image = self._render
        player.random.randint = self._randint
        player.random.choice = self._choice
        player.random.sample = self._sample
        player.random.random = self._random

    def test_series_detection_separates_a_t_and_a1(self):
        self.assertEqual(
            player._activated_a1_series_num("L02-Activated/S2.T3"),
            3,
        )
        self.assertIsNone(player._activated_series_num("L02-Activated/S2.T3"))
        self.assertEqual(
            player._activated_series_num("L02-Activated/S1.T3"),
            3,
        )
        self.assertIsNone(player._activated_a1_series_num("L02-Activated/S1.T3"))

    def test_opening_card_shows_a1_label(self):
        name, series = player._level_display_parts("L02-Activated/S2.T2")
        self.assertEqual(name, "Activated")
        self.assertEqual(series, "S2.T2")

    def test_opening_card_shows_s_label_and_actions_only(self):
        text = player._level_card_text(
            "L02-Activated/S1.T1",
            "",
            {"test_num": 2, "on_ms": 3000, "actions_in_set": 6, "budget_ms": 18000, "finish_balls": True},
            [],
        )
        self.assertEqual(text.split("\n"), ["S1.T1", "6 Actions"])
        self.assertNotIn("Activated", text)
        self.assertNotIn("18.00", text)
        a1 = player._level_card_text(
            "L02-Activated/S2.T2",
            "",
            {"test_num": 5, "on_ms": 2700, "actions_in_set": 6},
            [],
        )
        self.assertEqual(a1.split("\n"), ["S2.T2", "6 Actions"])

    def test_opening_logos_exist_for_all_bands(self):
        expected = {
            "L00-Foundation": "logo_video_foundation.mp4",
            "L01-Entry/S1.T1": "logo_video_Entry.mp4",
            "L02-Activated/S1.T1": "logo_video_activated.mp4",
            "L03-HighPerformance/S1.T1": "logo_video_high_performance.mp4",
            "L04-Elite/S1.T1": "logo_video_Elite.mp4",
            "L05-WorldClass/S1.T1": "logo_video_world_class.mp4",
        }
        for level_id, name in expected.items():
            path = player._opening_logo_video_for_level(level_id)
            self.assertIsNotNone(path, level_id)
            self.assertTrue(path.endswith(name), (level_id, path))

    def test_set1_is_single_digit_odd_one_out_with_3s_timing(self):
        digit_n = {"n": 0}

        def randint(a, b):
            if a == 1 and b == 6:
                return 2
            if a == 0 and b == 9:
                digit_n["n"] += 1
                return 3 if digit_n["n"] % 2 else 7
            return a

        player.random.randint = randint
        playlist = player._build_activated_a1_playlist(1, ["A", "B"])
        self.assertEqual(len(playlist), 30)
        first = playlist[0]
        self.assertEqual(first["on_ms"], player._entry_series_timing_ms(1)[0])
        self.assertAlmostEqual(first["on_ms"] / 1000.0, 3.0, delta=0.05)
        self.assertTrue(first["finish_balls"])
        self.assertTrue(first["advance_on_goal"])
        self.assertEqual(first["field_screens"]["A"], ["A2"])
        self.assertEqual(first["field_screens"]["B"], ["B2"])
        self.assertEqual(len(first["screen_images"]), 12)
        a_vals = [
            first["screen_images"][f"A{n}"].split(":")[1]
            for n in range(1, 7)
        ]
        self.assertTrue(all(len(v) == 1 and v.isdigit() for v in a_vals))
        self.assertEqual(len(set(a_vals)), 2)
        odd = a_vals[1]
        same = next(v for v in a_vals if v != odd)
        self.assertEqual(a_vals.count(odd), 1)
        self.assertEqual(a_vals.count(same), 5)
        bg = str(player.ACTIVATED_A1_BG)
        self.assertTrue(first["screen_images"]["A1"].endswith(bg))

    def test_sets_use_digit_widths_then_letters(self):
        playlist1 = player._build_activated_a1_playlist(1, ["A"])
        playlist2 = player._build_activated_a1_playlist(2, ["A"])
        playlist3 = player._build_activated_a1_playlist(3, ["A"])
        playlist4 = player._build_activated_a1_playlist(4, ["A"])
        for step in playlist1[:6] + playlist2[:6]:
            for path in step["screen_images"].values():
                text = path.split(":")[1]
                self.assertEqual(len(text), 1)
                self.assertTrue(text.isdigit())
        for step in playlist3[:6]:
            for path in step["screen_images"].values():
                text = path.split(":")[1]
                self.assertEqual(len(text), 2)
                self.assertTrue(text.isdigit())
        for step in playlist4[:6]:
            for path in step["screen_images"].values():
                text = path.split(":")[1]
                self.assertEqual(len(text), 3)
                self.assertTrue(text.isdigit())
        self.assertLess(playlist2[0]["on_ms"], playlist1[0]["on_ms"])
        self.assertLess(playlist3[0]["on_ms"], playlist2[0]["on_ms"])
        self.assertLess(playlist4[0]["on_ms"], playlist3[0]["on_ms"])

    def test_set5_uses_similar_three_letter_triples(self):
        player.random.sample = lambda population, k: list(population)[:k]
        player.random.choice = lambda seq: seq[0]
        player.random.random = lambda: 0.0
        player.random.randint = lambda a, b: 4 if a == 1 and b == 6 else a
        playlist = player._build_activated_a1_playlist(5, ["A"])
        first = playlist[0]
        vals = [
            first["screen_images"][f"A{n}"].split(":")[1]
            for n in range(1, 7)
        ]
        self.assertTrue(all(len(v) == 3 and v.isalpha() for v in vals))
        self.assertEqual(len(set(vals)), 2)
        odd = vals[3]
        same = next(v for v in vals if v != odd)
        self.assertEqual(vals.count(odd), 1)
        self.assertEqual(vals.count(same), 5)
        self.assertEqual(same[1], odd[1])
        self.assertEqual(first["field_screens"]["A"], ["A4"])

    def test_fields_pick_independent_odd_targets(self):
        screens = {"n": 0}
        digits = {"n": 0}

        def randint(a, b):
            if a == 1 and b == 6:
                screens["n"] += 1
                return 1 if screens["n"] == 1 else 6
            if a == 0 and b == 9:
                digits["n"] += 1
                return 1 if digits["n"] % 2 else 8
            return a

        player.random.randint = randint
        step = player._build_activated_a1_playlist(1, ["A", "B"])[0]
        self.assertEqual(step["field_screens"]["A"], ["A1"])
        self.assertEqual(step["field_screens"]["B"], ["B6"])


if __name__ == "__main__":
    unittest.main()
