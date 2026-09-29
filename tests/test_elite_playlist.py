"""Elite and World Class: one 12-screen field, 00 stays, two players required."""

import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import smart_simust_player as player  # noqa: E402


def _fake_digit(text, bg, fg):
    return f"{text}|{tuple(bg)}|{tuple(fg)}"


class ElitePlaylistTests(unittest.TestCase):
    def setUp(self):
        self._render = player._render_band_digit_image
        player._render_band_digit_image = _fake_digit
        self._sample = player.random.sample
        player.random.sample = lambda population, k: list(population)[:k]

    def tearDown(self):
        player._render_band_digit_image = self._render
        player.random.sample = self._sample

    def test_one_player_cannot_start(self):
        decision = player._combined_play_decision(
            ["A"],
            {"A": "L04-Elite/A-T1"},
        )
        self.assertEqual(decision[0], "block")
        decision = player._combined_play_decision(
            ["B"],
            {"B": "L05-WorldClass/A-T1"},
        )
        self.assertEqual(decision[0], "block")

    def test_both_players_must_share_the_same_set(self):
        mixed = player._combined_play_decision(
            ["A", "B"],
            {"A": "L05-WorldClass/A-T1", "B": "L04-Elite/A-T1"},
        )
        self.assertEqual(mixed[0], "block")
        different_sets = player._combined_play_decision(
            ["A", "B"],
            {"A": "L04-Elite/A-T1", "B": "L04-Elite/A-T2"},
        )
        self.assertEqual(different_sets[0], "block")
        elite = player._combined_play_decision(
            ["A", "B"],
            {"A": "L04-Elite/A-T1", "B": "L04-Elite/A-T1"},
        )
        self.assertEqual(elite, ("play", "elite", 1))
        world = player._combined_play_decision(
            ["A", "B"],
            {"A": "L05-WorldClass/A-T3", "B": "L05-WorldClass/A-T3"},
        )
        self.assertEqual(world, ("play", "world-class", 3))

    def test_twelve_actions_lowest_becomes_orange_00(self):
        playlist = player._build_elite_playlist(1, "elite")
        self.assertEqual(len(playlist), 60)
        first = playlist[0]
        self.assertEqual(first["actions_in_set"], 12)
        self.assertEqual(first["field_screens"], {"A": ["A1"]})
        self.assertEqual(len(first["screen_images"]), 12)
        numbers = []
        colors = set()
        backgrounds = set()
        for sid, token in first["screen_images"].items():
            text, bg, fg = token.split("|")
            numbers.append(text)
            colors.add(fg)
            backgrounds.add(bg)
            self.assertNotEqual(text, "00")
        self.assertEqual(len(set(numbers)), 12)
        self.assertTrue(set(numbers).issubset(set(player.ELITE_NUMBER_POOL)))
        self.assertEqual(len(player.ELITE_NUMBER_POOL), 22)
        self.assertEqual(len(colors), 1)
        self.assertEqual(len(backgrounds), 1)
        second = playlist[1]
        self.assertTrue(second["screen_images"]["A1"].startswith("00|"))
        self.assertIn(str(player.ELITE_ZERO_COLOR), second["screen_images"]["A1"])
        self.assertNotIn(str(player.ELITE_ZERO_COLOR), first["screen_images"]["B1"])
        self.assertTrue(second["screen_images"]["B1"].startswith("03|"))
        self.assertEqual(second["field_screens"], {"B": ["B1"]})
        self.assertNotIn("A", second["field_screens"])
        test2 = [step for step in playlist if step["test_num"] == 2]
        self.assertEqual(test2[0]["field_screens"], {"B": ["B6"]})
        self.assertTrue(test2[0]["screen_images"]["B6"].startswith("01|"))
        self.assertEqual(test2[1]["field_screens"], {"A": ["A6"]})
        for test_num, expected in (
            (3, {"A": ["A1"]}),
            (4, {"B": ["B6"]}),
            (5, {"A": ["A1"]}),
        ):
            step = next(item for item in playlist if item["test_num"] == test_num)
            self.assertEqual(step["field_screens"], expected)

    def test_digit_color_changes_with_background_and_stays_readable(self):
        playlist = player._build_elite_playlist(1, "elite")
        by_test = {}
        for step in playlist:
            if step["action_in_set"] != 1:
                continue
            token = step["screen_images"]["A1"]
            _text, bg, fg = token.split("|")
            by_test[step["test_num"]] = (bg, fg)
        self.assertEqual(len(by_test), 5)
        self.assertEqual(len({bg for bg, _fg in by_test.values()}), 5)
        self.assertGreaterEqual(len({fg for _bg, fg in by_test.values()}), 4)
        for test_num, (bg, fg) in by_test.items():
            background = player.ELITE_TEST_BG[test_num]
            digit = player.ELITE_DIGIT_ON_BG[test_num]
            self.assertTrue(player._colors_are_visible(digit, background))
            self.assertTrue(player._colors_are_visible(player.ELITE_ZERO_COLOR, background))
            self.assertNotEqual(digit, background)
            self.assertEqual(fg, str(tuple(digit)))
            self.assertEqual(bg, str(tuple(background)))

    def test_timing_starts_at_4_5_and_gap_stays_half_a_second(self):
        first = player._build_elite_playlist(1, "elite")
        second = player._build_elite_playlist(2, "elite")
        fifth = player._build_elite_playlist(5, "world-class")
        self.assertEqual(first[0]["on_ms"], 4500)
        self.assertEqual(first[0]["gap_ms"], 500)
        self.assertEqual(second[0]["gap_ms"], 500)
        self.assertEqual(fifth[0]["gap_ms"], 500)
        self.assertLess(second[0]["on_ms"], first[0]["on_ms"])
        self.assertAlmostEqual(second[0]["on_ms"] / first[0]["on_ms"], 0.9, delta=0.02)
        self.assertGreaterEqual(fifth[0]["on_ms"], 2500)
        floored_on, floored_gap = player._elite_series_timing_ms(40)
        self.assertGreaterEqual(floored_on, 2500)
        self.assertEqual(floored_gap, 500)
        ons = {step["test_num"]: step["on_ms"] for step in first}
        self.assertEqual(set(ons.values()), {4500})

    def test_player_refuses_one_field_and_builds_both(self):
        window = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        window._one_field_build = False
        window._phase_field_directories = {}
        window._level_root = ""
        window.video_directory = ""
        window._phase_mode_id = ""
        window._phase_subdirectory = ""
        window._active_fields = lambda: ["A"]
        window._phase_field_levels = {"A": "L04-Elite/A-T2"}
        self.assertEqual(window._build_image_action_playlist(), [])
        self.assertIn("two players", window._playlist_block_reason)
        window._active_fields = lambda: ["A", "B"]
        window._phase_field_levels = {
            "A": "L05-WorldClass/A-T2",
            "B": "L05-WorldClass/A-T2",
        }
        playlist = window._build_image_action_playlist()
        self.assertEqual(len(playlist), 60)
        self.assertTrue(window._label_mode)
        self.assertEqual(playlist[0]["on_ms"], 4050)
        self.assertEqual(playlist[0]["gap_ms"], 500)

    def test_world_class_keeps_each_numbers_own_color_on_00(self):
        playlist = player._build_elite_playlist(1, "world-class")
        first = playlist[0]
        colors = []
        for sid in player._elite_screen_ids():
            text, bg, fg = first["screen_images"][sid].split("|")
            colors.append(fg)
            self.assertNotEqual(text, "00")
            self.assertTrue(
                player._colors_are_visible(ast.literal_eval(fg), ast.literal_eval(bg))
            )
        self.assertEqual(len(set(colors)), 12)
        origin = first["screen_images"]["A1"].split("|")[2]
        zero = playlist[1]["screen_images"]["A1"]
        self.assertTrue(zero.startswith("00|"))
        self.assertEqual(zero.split("|")[2], origin)
        self.assertNotIn(str(player.ELITE_ZERO_COLOR), zero)
        goals = []
        for step in playlist:
            if step["test_num"] != 1:
                continue
            goals.append(step["field_screens"][next(iter(step["field_screens"]))][0])
        self.assertEqual(
            goals,
            ["A1", "B1", "A2", "B2", "A3", "B3", "A4", "B4", "A5", "B5", "A6", "B6"],
        )
        test2 = []
        for step in playlist:
            if step["test_num"] != 2:
                continue
            test2.append(step["field_screens"][next(iter(step["field_screens"]))][0])
        self.assertEqual(
            test2,
            ["B1", "A1", "B2", "A2", "B3", "A3", "B4", "A4", "B5", "A5", "B6", "A6"],
        )
        for left, right in zip(goals, goals[1:]):
            self.assertNotEqual(left[0], right[0])
        by_test = {n: [] for n in range(1, 6)}
        for step in playlist:
            by_test[step["test_num"]].append(
                step["field_screens"][next(iter(step["field_screens"]))][0]
            )
        self.assertEqual(by_test[3], goals)
        self.assertEqual(by_test[5], goals)
        self.assertEqual(by_test[4], test2)
        for line in by_test.values():
            for left, right in zip(line, line[1:]):
                self.assertNotEqual(left[0], right[0])


if __name__ == "__main__":
    unittest.main()
