"""Elite and World Class: one 12-screen field; one field is enough to start."""

import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import smart_simust_player as player  # noqa: E402


def _fake_digit(text, bg, fg, lift_frac=0.0):
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

    def test_one_field_can_start_combined_play(self):
        decision = player._combined_play_decision(
            ["A"],
            {"A": "L04-Elite/S1.T1"},
        )
        self.assertEqual(decision, ("play", "elite", 1, 1))
        decision = player._combined_play_decision(
            ["B"],
            {"B": "L05-WorldClass/S1.T1"},
        )
        self.assertEqual(decision, ("play", "world-class", 1, 1))
        decision = player._combined_play_decision(
            ["A"],
            {"A": "L04-Elite/S2.T1"},
        )
        self.assertEqual(decision, ("play", "elite", 1, 2))

    def test_both_players_must_share_the_same_set(self):
        mixed = player._combined_play_decision(
            ["A", "B"],
            {"A": "L05-WorldClass/S1.T1", "B": "L04-Elite/S1.T1"},
        )
        self.assertEqual(mixed[0], "block")
        different_sets = player._combined_play_decision(
            ["A", "B"],
            {"A": "L04-Elite/S1.T1", "B": "L04-Elite/S1.T2"},
        )
        self.assertEqual(different_sets[0], "block")
        elite = player._combined_play_decision(
            ["A", "B"],
            {"A": "L04-Elite/S1.T1", "B": "L04-Elite/S1.T1"},
        )
        self.assertEqual(elite, ("play", "elite", 1, 1))
        world = player._combined_play_decision(
            ["A", "B"],
            {"A": "L05-WorldClass/S1.T3", "B": "L05-WorldClass/S1.T3"},
        )
        self.assertEqual(world, ("play", "world-class", 3, 1))
        elite_s2 = player._combined_play_decision(
            ["A", "B"],
            {"A": "L04-Elite/S2.T2", "B": "L04-Elite/S2.T2"},
        )
        self.assertEqual(elite_s2, ("play", "elite", 2, 2))

    def test_twelve_actions_lowest_becomes_orange_00(self):
        playlist = player._build_elite_playlist(1, "elite")
        self.assertEqual(len(playlist), 60)
        first = playlist[0]
        self.assertEqual(first["actions_in_set"], 12)
        first_goal = first["field_screens"][next(iter(first["field_screens"]))][0]
        self.assertEqual(len(first["field_screens"]), 1)
        self.assertIn(first_goal, player._elite_screen_ids())
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
        self.assertTrue(second["screen_images"][first_goal].startswith("00|"))
        self.assertIn(str(player.ELITE_ZERO_COLOR), second["screen_images"][first_goal])
        second_goal = second["field_screens"][next(iter(second["field_screens"]))][0]
        self.assertNotEqual(first_goal, second_goal)
        self.assertTrue(first["advance_on_goal"])
        self.assertTrue(first["finish_balls"])
        self.assertTrue(first["skip_gap"])
        # Every test uses a random 12-screen order (all screens, no repeats).
        for test_num in range(1, 6):
            goals = [
                step["field_screens"][next(iter(step["field_screens"]))][0]
                for step in playlist
                if step["test_num"] == test_num
            ]
            self.assertEqual(len(goals), 12)
            self.assertEqual(set(goals), set(player._elite_screen_ids()))

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

    def test_player_one_field_builds_twelve_screen_playlist(self):
        window = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        window._one_field_build = False
        window._phase_field_directories = {}
        window._level_root = ""
        window.video_directory = ""
        window._phase_mode_id = ""
        window._phase_subdirectory = ""
        window._active_fields = lambda: ["A"]
        window._phase_field_levels = {"A": "L04-Elite/S1.T2"}
        playlist = window._build_image_action_playlist()
        self.assertEqual(len(playlist), 60)
        self.assertTrue(window._label_mode)
        self.assertEqual(window._phase_active, ["A", "B"])
        self.assertEqual(len(playlist[0]["screen_images"]), 12)
        self.assertEqual(playlist[0]["on_ms"], 4050)
        self.assertEqual(playlist[0]["gap_ms"], 500)
        window._active_fields = lambda: ["A", "B"]
        window._phase_field_levels = {
            "A": "L05-WorldClass/S1.T2",
            "B": "L05-WorldClass/S1.T2",
        }
        playlist = window._build_image_action_playlist()
        self.assertEqual(len(playlist), 60)
        self.assertTrue(window._label_mode)
        self.assertEqual(playlist[0]["on_ms"], 4050)
        self.assertEqual(playlist[0]["gap_ms"], 500)

    def test_world_class_changes_colors_every_action(self):
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
        # Goal order is random — the first action's goal becomes 00 on action 2.
        first_goal = first["field_screens"][next(iter(first["field_screens"]))][0]
        origin = first["screen_images"][first_goal].split("|")[2]
        zero = playlist[1]["screen_images"][first_goal]
        self.assertTrue(zero.startswith("00|"))
        self.assertEqual(zero.split("|")[2], origin)
        self.assertNotIn(str(player.ELITE_ZERO_COLOR), zero)
        # Remaining digits get a new palette on the next action.
        live_first = {
            sid: first["screen_images"][sid].split("|")[2]
            for sid in player._elite_screen_ids()
            if sid != first_goal
        }
        live_second = {
            sid: playlist[1]["screen_images"][sid].split("|")[2]
            for sid in player._elite_screen_ids()
            if sid != first_goal
        }
        self.assertNotEqual(live_first, live_second)
        other = "B1" if first_goal != "B1" else "A1"
        bg_first = first["screen_images"][other].split("|")[1]
        bg_second = playlist[1]["screen_images"][other].split("|")[1]
        self.assertNotEqual(bg_first, bg_second)
        by_test = {n: [] for n in range(1, 6)}
        for step in playlist:
            by_test[step["test_num"]].append(
                step["field_screens"][next(iter(step["field_screens"]))][0]
            )
        for line in by_test.values():
            self.assertEqual(len(line), 12)
            self.assertEqual(set(line), set(player._elite_screen_ids()))


if __name__ == "__main__":
    unittest.main()
