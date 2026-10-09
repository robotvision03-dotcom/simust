"""High Performance / Elite / World Class series-2 playlists."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import smart_simust_player as player  # noqa: E402


class Series2PlaylistTests(unittest.TestCase):
    def setUp(self):
        self._entry = player._render_entry_digit_image
        self._band = player._render_band_digit_image
        self._mid = player._render_middle_colored_text_image
        self._cam = player._render_camouflage_text_image
        self._motion = player._ensure_wc_motion_bg_video
        player._render_entry_digit_image = lambda text, bg=None: f"img:{text}:{bg}"
        player._render_band_digit_image = lambda text, bg, fg: f"img:{text}:{bg}:{fg}"
        player._render_middle_colored_text_image = (
            lambda text, bg, outer_fg, mid_fg: f"mid:{text}:{bg}:{outer_fg}:{mid_fg}"
        )
        self._compose = getattr(player, "_compose_bouncing_flowers_rgb", None)
        self._composite = getattr(player, "_composite_overlay_on_bg", None)
        player._compose_bouncing_flowers_rgb = (
            lambda width, height, seed, frame_i=0, base_rgb=None, fleet=None, kind="flowers": (
                None, fleet
            )
        )
        player._composite_overlay_on_bg = lambda *a, **k: None
        player._render_camouflage_text_image = (
            lambda text, seed=1, camouflage=True, theme="flowers", phase=0.0, fast=True: (
                f"cam:{text}:{seed}:{camouflage}:{theme}"
            )
        )
        player._ensure_wc_motion_bg_video = (
            lambda theme, seed, base_rgb=None, blocking=False: f"motion:{theme}:{seed}.mp4"
        )

    def tearDown(self):
        player._render_entry_digit_image = self._entry
        player._render_band_digit_image = self._band
        player._render_middle_colored_text_image = self._mid
        player._render_camouflage_text_image = self._cam
        player._ensure_wc_motion_bg_video = self._motion
        if self._compose is not None:
            player._compose_bouncing_flowers_rgb = self._compose
        if self._composite is not None:
            player._composite_overlay_on_bg = self._composite

    def test_hp_s2_is_letter_odd_one_out_with_3s_timing(self):
        playlist = player._build_high_performance_s2_playlist(1, ["A", "B"])
        self.assertEqual(len(playlist), 30)
        first = playlist[0]
        self.assertAlmostEqual(first["on_ms"] / 1000.0, 3.0, delta=0.05)
        self.assertTrue(first["finish_balls"])
        self.assertEqual(len(first["screen_images"]), 12)
        self.assertEqual(first.get("motion_theme"), "flowers")
        self.assertTrue(first.get("motion_bg"))
        a_vals = [
            first["screen_images"][f"A{n}"].split(":")[1]
            for n in range(1, 7)
        ]
        self.assertTrue(all(len(v) == 3 and v.isalpha() for v in a_vals))
        self.assertEqual(len(set(a_vals)), 2)
        goal = first["field_screens"]["A"][0]
        odd = first["screen_images"][goal].split(":")[1]
        same = next(v for v in a_vals if v != odd)
        self.assertEqual(same[0], same[2])
        self.assertEqual(odd[0], odd[2])
        self.assertEqual(same[0], odd[0])
        self.assertNotEqual(same[1], odd[1])

    def test_hp_s2_later_sets_get_faster_but_not_under_1_8(self):
        first = player._build_high_performance_s2_playlist(1, ["A"])[0]["on_ms"]
        fifth = player._build_high_performance_s2_playlist(5, ["A"])[0]["on_ms"]
        self.assertLess(fifth, first)
        self.assertGreaterEqual(fifth, player.ENTRY_ON_MIN_MS - 50)
        for series in (1, 3, 5):
            step = player._build_high_performance_s2_playlist(series, ["A"])[0]
            self.assertEqual(step.get("motion_theme"), "flowers")

    def test_elite_s2_has_one_number_among_symbols(self):
        playlist = player._build_elite_s2_playlist(1)
        self.assertEqual(len(playlist), 60)
        first = playlist[0]
        self.assertAlmostEqual(first["on_ms"] / 1000.0, 4.5, delta=0.05)
        self.assertEqual(first["actions_in_set"], 12)
        texts = [path.split(":")[1] for path in first["screen_images"].values()]
        digits = [t for t in texts if t.isdigit()]
        symbols = [t for t in texts if not t.isdigit()]
        self.assertEqual(len(digits), 1)
        self.assertEqual(len(symbols), 11)
        goal = first["field_screens"][next(iter(first["field_screens"]))][0]
        self.assertTrue(first["screen_images"][goal].split(":")[1].isdigit())
        # Level S2.T1 → characters for every timed test in the set.
        self.assertEqual(first.get("distractor_kind"), "characters")
        self.assertTrue(all(s.get("distractor_kind") == "characters" for s in playlist))
        # Level S2.T3 → shapes for the whole set.
        s2t3 = player._build_elite_s2_playlist(3)
        self.assertTrue(all(s.get("distractor_kind") == "shapes" for s in s2t3))
        t3 = s2t3[0]
        t3_texts = [path.split(":")[1] for path in t3["screen_images"].values()]
        self.assertEqual(sum(1 for t in t3_texts if t.isdigit()), 1)
        shape_hits = [t for t in t3_texts if t in player.ELITE_S2_SHAPES]
        self.assertEqual(len(shape_hits), 11)

    def test_symbol_cache_token_is_windows_safe(self):
        for symbol in player.ELITE_S2_SYMBOLS:
            token = player._safe_cache_token(symbol)
            self.assertTrue(token)
            for bad in '<>:"/\\|?*':
                self.assertNotIn(bad, token)

    def test_elite_s2_floor_is_2_6(self):
        on_ms, _ = player._elite_series_timing_ms(5, min_ms=player.ELITE_S2_ON_MIN_MS)
        self.assertGreaterEqual(on_ms, player.ELITE_S2_ON_MIN_MS - 50)
        self.assertLess(on_ms, player.ELITE_ON_START_MS)

    def test_world_s2_has_one_k2_among_camouflaged_digits(self):
        playlist = player._build_world_class_s2_playlist(1)
        self.assertEqual(len(playlist), 60)
        first = playlist[0]
        texts = [path.split(":")[1] for path in first["screen_images"].values()]
        self.assertEqual(texts.count("K2"), 1)
        others = [t for t in texts if t != "K2"]
        self.assertEqual(len(others), 11)
        self.assertTrue(all(len(t) == 2 and t.isdigit() for t in others))
        goal = first["field_screens"][next(iter(first["field_screens"]))][0]
        self.assertEqual(first["screen_images"][goal].split(":")[1], "K2")
        # K2 uses the same camouflage mode/color as the other numbers.
        flags = {
            path.split(":")[3]
            for path in first["screen_images"].values()
        }
        self.assertEqual(flags, {"True"})
        # Level S2.T1 → flowers for every timed test in the set.
        self.assertEqual(first["motion_theme"], "flowers")
        self.assertTrue(all(s.get("motion_theme") == "flowers" for s in playlist))
        self.assertTrue(first.get("motion_bg"))
        self.assertEqual(first["motion_texts"][goal], "K2")
        positions = first.get("motion_text_positions") or {}
        self.assertEqual(set(positions), set(first["motion_texts"]))
        ys = [float(positions[sid][1]) for sid in positions]
        self.assertTrue(all(player.WC_TEXT_EDGE_MARGIN <= y <= 1.0 - player.WC_TEXT_EDGE_MARGIN for y in ys))
        # Numbers are spread: not all stacked on one y.
        self.assertGreater(len(set(round(y, 2) for y in ys)), 1)
        self.assertEqual(player._wc_s2_theme_for_series(1), "flowers")
        self.assertEqual(player._wc_s2_theme_for_series(2), "fruits")
        self.assertEqual(player._wc_s2_theme_for_series(3), "animals")
        self.assertEqual(player._wc_s2_theme_for_series(4), "space")
        self.assertEqual(player._wc_s2_theme_for_series(5), "orbs")
        # Level S2.T2 playlist is fruits throughout.
        s2t2 = player._build_world_class_s2_playlist(2)
        self.assertTrue(all(s.get("motion_theme") == "fruits" for s in s2t2))
        # Each action gets its own bounce start seed (not one shared location).
        flower_seeds = {step["motion_seed"] for step in playlist}
        self.assertGreater(len(flower_seeds), 1)
        self.assertGreaterEqual(player.WORLD_S2_CAMO_SEVERITY, 1.4)

    def test_opening_card_is_black_with_level_colored_text(self):
        bg, fg = player._level_card_colors("L05-WorldClass/S2.T1", "", {})
        self.assertEqual(bg, (0, 0, 0))
        self.assertEqual(fg, player._LEVEL_BRAND_RGB["world-class"])
        bg2, fg2 = player._level_card_colors("L04-Elite/S1.T1", "", {})
        self.assertEqual(bg2, (0, 0, 0))
        self.assertEqual(fg2, player._LEVEL_BRAND_RGB["elite"])
        self.assertAlmostEqual(player.OPENING_LOGO_MAX_WIDTH, 0.52 * 1.4, places=3)
        self.assertEqual(player.OPENING_LOGO_TEXT_GAP_LINES, 0)
        self.assertAlmostEqual(player.OPENING_LOGO_TEXT_DOWN_FRAC, 0.20, places=3)


if __name__ == "__main__":
    unittest.main()
