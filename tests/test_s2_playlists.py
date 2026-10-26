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
        player._render_band_digit_image = (
            lambda text, bg, fg, lift_frac=0.0: f"img:{text}:{bg}:{fg}:{lift_frac}"
        )
        player._render_middle_colored_text_image = (
            lambda text, bg, outer_fg, mid_fg, mid_bg=None: (
                f"mid:{text}:{bg}:{outer_fg}:{mid_fg}:{mid_bg}"
            )
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
        # Same solid S1 backgrounds — no motion flowers.
        self.assertIsNone(first.get("motion_theme"))
        self.assertFalse(first.get("motion_bg"))
        self.assertEqual(first.get("test_bg"), player.HP_TEST_BG[1])
        # Background changes per timed test, not per action.
        by_test = {}
        for step in playlist:
            by_test.setdefault(step["test_num"], set()).add(step.get("test_bg"))
        for test_num, bgs in by_test.items():
            self.assertEqual(bgs, {player.HP_TEST_BG[test_num]}, test_num)
        self.assertEqual(len({step.get("test_bg") for step in playlist}), 5)
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
        # No yellow patch — middle letter is painted only (mid_bg=False).
        sample = next(iter(first["screen_images"].values()))
        self.assertTrue(sample.endswith(":False"))

    def test_hp_s2_later_sets_get_faster_but_not_under_1_8(self):
        first = player._build_high_performance_s2_playlist(1, ["A"])[0]["on_ms"]
        fifth = player._build_high_performance_s2_playlist(5, ["A"])[0]["on_ms"]
        self.assertLess(fifth, first)
        self.assertGreaterEqual(fifth, player.ENTRY_ON_MIN_MS - 50)
        for series in (1, 3, 5):
            step = player._build_high_performance_s2_playlist(series, ["A"])[0]
            self.assertIsNone(step.get("motion_theme"))
            self.assertFalse(step.get("motion_bg"))
            self.assertEqual(step.get("test_bg"), player.HP_TEST_BG[1])

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

    def test_world_s2_has_one_letter_token_among_camouflaged_digits(self):
        playlist = player._build_world_class_s2_playlist(1)
        self.assertEqual(len(playlist), 60)
        first = playlist[0]
        texts = [path.split(":")[1] for path in first["screen_images"].values()]
        goal_tokens = [t for t in texts if player._is_wc_s2_goal_token(t)]
        others = [t for t in texts if not player._is_wc_s2_goal_token(t)]
        self.assertEqual(len(goal_tokens), 1)
        self.assertEqual(len(others), 11)
        self.assertTrue(all(len(t) == 2 and t.isdigit() for t in others))
        goal = first["field_screens"][next(iter(first["field_screens"]))][0]
        goal_token = first["screen_images"][goal].split(":")[1]
        self.assertTrue(player._is_wc_s2_goal_token(goal_token))
        self.assertEqual(first.get("goal_token"), goal_token)
        # Letter token uses the same camouflage mode/color as the numbers.
        flags = {
            path.split(":")[3]
            for path in first["screen_images"].values()
        }
        self.assertEqual(flags, {"True"})
        # Level S2.T1 → flowers for every timed test in the set.
        self.assertEqual(first["motion_theme"], "flowers")
        self.assertTrue(all(s.get("motion_theme") == "flowers" for s in playlist))
        self.assertTrue(first.get("motion_bg"))
        self.assertEqual(first["motion_texts"][goal], goal_token)
        positions = first.get("motion_text_positions") or {}
        self.assertEqual(set(positions), set(first["motion_texts"]))
        # Same vertical line as Elite/Entry (results-ring value center).
        expected_y = float(player._ring_value_center_frac(1080))
        for sid, pos in positions.items():
            self.assertAlmostEqual(float(pos[0]), 0.5, places=3, msg=sid)
            self.assertAlmostEqual(float(pos[1]), expected_y, places=3, msg=sid)
        self.assertEqual(player._wc_s2_theme_for_series(1), "flowers")
        self.assertEqual(player._wc_s2_theme_for_series(2), "fruits")
        self.assertEqual(player._wc_s2_theme_for_series(3), "animals")
        self.assertEqual(player._wc_s2_theme_for_series(4), "space")
        self.assertEqual(player._wc_s2_theme_for_series(5), "orbs")
        # Level S2.T2 playlist is fruits throughout.
        s2t2 = player._build_world_class_s2_playlist(2)
        self.assertTrue(all(s.get("motion_theme") == "fruits" for s in s2t2))
        # Motion background seed changes per timed test, not every action.
        flower_seeds = {step["motion_seed"] for step in playlist}
        self.assertEqual(len(flower_seeds), 5)
        for test_num in range(1, 6):
            seeds = {
                step["motion_seed"]
                for step in playlist
                if step["test_num"] == test_num
            }
            self.assertEqual(len(seeds), 1, test_num)
        self.assertGreaterEqual(player.WORLD_S2_CAMO_SEVERITY, 1.4)
        # Goal letter+digit changes across actions (not stuck on K2).
        tokens = [step.get("goal_token") for step in playlist]
        self.assertTrue(all(player._is_wc_s2_goal_token(t) for t in tokens))
        self.assertGreater(len(set(tokens)), 8)
        # Adjacent actions avoid repeating the same token when possible.
        same_neighbors = sum(
            1 for a, b in zip(tokens, tokens[1:]) if a == b
        )
        self.assertEqual(same_neighbors, 0)

    def test_opening_card_text_is_readable_on_level_color(self):
        samples = {
            "L00-Foundation/SF-30N": "foundation",
            "L01-Entry/S1.T1": "entry",
            "L02-Activated/S1.T1": "activated",
            "L03-HighPerformance/S1.T1": "high-performance",
            "L04-Elite/S1.T1": "elite",
            "L05-WorldClass/S2.T1": "world-class",
        }
        for level_id, key in samples.items():
            bg, fg = player._level_card_colors(level_id, "", {})
            self.assertEqual(bg, player._LEVEL_PAGE_BG[key][0], key)
            self.assertEqual(fg, player._LEVEL_PAGE_BG[key][1], key)
            self.assertNotEqual(fg, bg, key)
        # Results fills must match logos even when the L0x- prefix is missing.
        aliases = {
            "Entry/S1.T2": "entry",
            "Activated/S2.T2": "activated",
            "High Performance/S2.T1": "high-performance",
            "C:/simust/L02-Activated/S2.T5": "activated",
            "C:/simust/L01-Entry/S1.T1": "entry",
        }
        for level_id, key in aliases.items():
            self.assertEqual(player._level_brand_key(level_id), key, level_id)
            bg, _fg = player._level_card_colors(level_id, "", {})
            self.assertEqual(bg, player._LEVEL_PAGE_BG[key][0], level_id)
        self.assertAlmostEqual(player.OPENING_LOGO_MAX_WIDTH, 0.52 * 1.4 * 1.3, places=3)
        self.assertAlmostEqual(player.OPENING_LOGO_MAX_HEIGHT, 0.30 * 1.4 * 1.3, places=3)
        self.assertEqual(player.OPENING_LOGO_TEXT_GAP_LINES, 0)
        self.assertAlmostEqual(player.OPENING_LOGO_TEXT_DOWN_FRAC, 0.20, places=3)
        self.assertEqual(player.OPENING_LOGO_TEXT_LIFT_LINES, 3)

    def test_elite_and_world_s2_use_random_goal_order(self):
        elite = player._build_elite_s2_playlist(1)
        world = player._build_world_class_s2_playlist(1)
        for playlist in (elite, world):
            for test_num in range(1, 6):
                goals = [
                    step["field_screens"][next(iter(step["field_screens"]))][0]
                    for step in playlist
                    if step["test_num"] == test_num
                ]
                self.assertEqual(len(goals), 12)
                self.assertEqual(set(goals), set(player._elite_screen_ids()))

    def test_hp_s3_encodes_reference_then_two_sum_goals(self):
        playlist = player._build_high_performance_s3_playlist(1, ["A", "B"])
        # Each S3.Tn series: 5 tests × 6 actions.
        self.assertEqual(len(playlist), 30)
        by_test = {}
        for step in playlist:
            by_test.setdefault(step["test_num"], []).append(step["action_in_set"])
        self.assertEqual(sorted(by_test), [1, 2, 3, 4, 5])
        for test_num, actions in by_test.items():
            self.assertEqual(actions, [1, 2, 3, 4, 5, 6], test_num)
        first = playlist[0]
        self.assertEqual(first.get("encode_ms"), 5000)
        self.assertEqual(first.get("actions_in_set"), 6)
        self.assertEqual(first.get("on_ms"), 10000)
        self.assertEqual(first.get("budget_ms"), 60000)
        self.assertTrue(first.get("cognitive_encode"))
        self.assertTrue(first.get("require_all_goals"))
        self.assertTrue(first.get("hold_full_on"))
        self.assertTrue(first.get("skip_gap"))
        self.assertTrue(first.get("finish_balls"))
        # S1 solid backgrounds — no motion flowers; bg changes per test.
        self.assertIsNone(first.get("motion_theme"))
        self.assertFalse(first.get("motion_bg"))
        self.assertEqual(first.get("test_bg"), player.HP_TEST_BG[1])
        by_test_bg = {}
        for step in playlist:
            by_test_bg.setdefault(step["test_num"], set()).add(step.get("test_bg"))
        for test_num, bgs in by_test_bg.items():
            self.assertEqual(bgs, {player.HP_TEST_BG[test_num]}, test_num)
        # Encode + answers on all 6 screens; cylinders only on the 2 sum screens.
        self.assertEqual(len(first.get("encode_images") or {}), 12)
        self.assertEqual(len(first.get("screen_images") or {}), 12)
        self.assertEqual(len(first["field_screens"]["A"]), 2)
        self.assertEqual(len(first["field_screens"]["B"]), 2)
        # Encode shows one shared red reference on every field screen.
        a_encode = {
            first["encode_images"][f"A{n}"].split(":")[1] for n in range(1, 7)
        }
        self.assertEqual(len(a_encode), 1)
        ref = int(next(iter(a_encode)))
        self.assertEqual(first["reference_numbers"]["A"], ref)
        self.assertTrue(1 <= ref <= 9)
        encode_fg = {
            first["encode_images"][f"A{n}"].split(":")[3] for n in range(1, 7)
        }
        self.assertEqual(encode_fg, {str(player.S3_REFERENCE_FG)})
        a_vals = [
            int(first["screen_images"][f"A{n}"].split(":")[1]) for n in range(1, 7)
        ]
        self.assertEqual(len(set(a_vals)), 6)
        goals = first["field_screens"]["A"]
        g0 = int(first["screen_images"][goals[0]].split(":")[1])
        g1 = int(first["screen_images"][goals[1]].split(":")[1])
        self.assertEqual(g0 + g1, ref)
        self.assertEqual(first["sum_pairs"]["A"], (g0, g1))
        # T3 uses a two-digit reference < 20 for 3 seconds.
        t3 = player._build_high_performance_s3_playlist(3, ["A"])[0]
        self.assertEqual(t3.get("encode_ms"), 3000)
        self.assertEqual(t3.get("actions_in_set"), 6)
        self.assertEqual(t3.get("on_ms"), 10000)
        self.assertEqual(t3.get("budget_ms"), 60000)
        self.assertEqual(len(t3.get("screen_images") or {}), 6)
        ref3 = int(next(iter(t3["encode_images"].values())).split(":")[1])
        self.assertTrue(10 <= ref3 <= 19)
        pair3 = t3["sum_pairs"]["A"]
        self.assertEqual(pair3[0] + pair3[1], ref3)
        self.assertEqual(
            next(iter(t3["encode_images"].values())).split(":")[3],
            str(player.S3_REFERENCE_FG),
        )
        self.assertEqual(
            player._high_performance_s3_series_num("L03-HighPerformance/S3.T4"), 4
        )
        self.assertIsNone(
            player._high_performance_series_num("L03-HighPerformance/S3.T1")
        )
        self.assertEqual(
            player._series_set_label("L03-HighPerformance/S3.T2"), "S3.T2"
        )

    def test_elite_s3_encodes_ref_under_50_on_12_screens(self):
        playlist = player._build_elite_s3_playlist(1)
        # 5 tests × 12 actions.
        self.assertEqual(len(playlist), 60)
        first = playlist[0]
        self.assertTrue(first.get("combined_field"))
        self.assertTrue(first.get("cognitive_encode"))
        self.assertTrue(first.get("require_all_goals"))
        self.assertTrue(first.get("hold_full_on"))
        self.assertEqual(first.get("encode_ms"), 5000)
        self.assertEqual(first.get("actions_in_set"), 12)
        self.assertEqual(first.get("on_ms"), 10000)
        self.assertEqual(first.get("budget_ms"), 120000)
        self.assertEqual(len(first.get("encode_images") or {}), 12)
        self.assertEqual(len(first.get("screen_images") or {}), 12)
        refs = {
            int(path.split(":")[1]) for path in first["encode_images"].values()
        }
        self.assertEqual(len(refs), 1)
        ref = next(iter(refs))
        self.assertTrue(10 <= ref <= 49)
        # Red reference + Elite S1 background/digit styling per timed test.
        self.assertEqual(first.get("test_bg"), player.ELITE_TEST_BG[1])
        encode_fg = {
            path.split(":")[3] for path in first["encode_images"].values()
        }
        self.assertEqual(encode_fg, {str(player.S3_REFERENCE_FG)})
        answer_fg = {
            path.split(":")[3] for path in first["screen_images"].values()
        }
        self.assertEqual(answer_fg, {str(player.ELITE_DIGIT_ON_BG[1])})
        goal_sids = [
            sid
            for goals in (first.get("field_screens") or {}).values()
            for sid in goals
        ]
        self.assertEqual(len(goal_sids), 2)
        g0 = int(first["screen_images"][goal_sids[0]].split(":")[1])
        g1 = int(first["screen_images"][goal_sids[1]].split(":")[1])
        self.assertEqual(g0 + g1, ref)
        t3 = player._build_elite_s3_playlist(3)[0]
        self.assertEqual(t3.get("encode_ms"), 3000)
        self.assertEqual(t3.get("test_bg"), player.ELITE_TEST_BG[1])
        self.assertEqual(
            player._elite_s3_series_num("L04-Elite/S3.T4"), 4
        )
        self.assertEqual(
            player._combined_play_decision(
                ["A"], {"A": "L04-Elite/S3.T2"}
            ),
            ("play", "elite", 2, 3),
        )

    def test_elite_and_wc_s3_goals_can_split_across_fields(self):
        """Sum answers: both on A, both on B, or one on each — all must appear."""
        modes = set()
        for _ in range(60):
            g0, g1 = player._s3_combined_goal_indexes(12)
            screens = player._elite_screen_ids()
            fields = {screens[g0][0], screens[g1][0]}
            if fields == {"A"}:
                modes.add("A")
            elif fields == {"B"}:
                modes.add("B")
            else:
                modes.add("split")
            if modes == {"A", "B", "split"}:
                break
        self.assertEqual(modes, {"A", "B", "split"})
        # Playlist entries also publish both fields when split.
        seen = set()
        for builder in (
            player._build_elite_s3_playlist,
            player._build_world_class_s3_playlist,
        ):
            for step in builder(1):
                keys = tuple(sorted((step.get("field_screens") or {}).keys()))
                if keys == ("A", "B"):
                    seen.add("split")
                    goals = []
                    for sids in step["field_screens"].values():
                        goals.extend(sids)
                    self.assertEqual(len(goals), 2)
                    self.assertEqual({goals[0][0], goals[1][0]}, {"A", "B"})
                elif keys == ("A",):
                    seen.add("A")
                elif keys == ("B",):
                    seen.add("B")
        self.assertIn("split", seen)
        self.assertTrue({"A", "B"} & seen)

    def test_world_class_s3_themes_and_action_counts(self):
        t1 = player._build_world_class_s3_playlist(1)
        # All WC S3 sets: 5 tests × 12 actions / 120s.
        self.assertEqual(len(t1), 60)
        first = t1[0]
        self.assertEqual(first.get("motion_theme"), "flowers")
        self.assertTrue(first.get("motion_bg"))
        self.assertEqual(first.get("encode_ms"), 5000)
        self.assertEqual(first.get("actions_in_set"), 12)
        self.assertEqual(first.get("on_ms"), 10000)
        self.assertEqual(first.get("budget_ms"), 120000)
        self.assertTrue(first.get("combined_field"))
        self.assertTrue(first.get("require_all_goals"))
        refs = {
            int(path.split(":")[1]) for path in first["encode_images"].values()
        }
        ref = next(iter(refs))
        self.assertTrue(51 <= ref <= 99)
        # Red reference at S1 digit size; motion seed stable within a timed test.
        encode_fg = {
            path.split(":")[3] for path in first["encode_images"].values()
        }
        self.assertEqual(encode_fg, {str(player.S3_REFERENCE_FG)})
        for test_num in range(1, 6):
            seeds = {
                step["motion_seed"] for step in t1 if step["test_num"] == test_num
            }
            self.assertEqual(len(seeds), 1, test_num)
        t2 = player._build_world_class_s3_playlist(2)[0]
        self.assertEqual(t2.get("motion_theme"), "fruits")
        self.assertEqual(t2.get("encode_ms"), 5000)
        self.assertEqual(t2.get("actions_in_set"), 12)
        self.assertEqual(t2.get("on_ms"), 10000)
        self.assertEqual(t2.get("budget_ms"), 120000)
        t3 = player._build_world_class_s3_playlist(3)
        self.assertEqual(len(t3), 60)
        step = t3[0]
        self.assertEqual(step.get("motion_theme"), "animals")
        self.assertEqual(step.get("encode_ms"), 3000)
        self.assertEqual(step.get("actions_in_set"), 12)
        self.assertEqual(step.get("on_ms"), 10000)
        self.assertEqual(step.get("budget_ms"), 120000)
        self.assertEqual(player._wc_s2_theme_for_series(4), "space")
        self.assertEqual(player._wc_s2_theme_for_series(5), "orbs")
        self.assertEqual(
            player._world_class_s3_series_num("L05-WorldClass/S3.T5"), 5
        )
        self.assertEqual(
            player._combined_play_decision(
                ["B"], {"B": "L05-WorldClass/S3.T1"}
            ),
            ("play", "world-class", 1, 3),
        )

    def test_hp_s3_skip_gap_still_starts_reference_encode(self):
        """finish-balls skip_gap must not skip the reference encode phase."""
        step = player._build_high_performance_s3_playlist(1, ["A"])[0]
        self.assertTrue(step.get("skip_gap"))
        self.assertTrue(step.get("cognitive_encode"))
        self.assertTrue(step.get("encode_images"))

        started = []

        class Window(player.SmartPlayerWindow):
            def _begin_cognitive_encode(self, entry, fields=None):
                started.append((entry.get("path"), fields))
                self._label_phase = "encode"

            def _apply_label_phase(self):
                started.append("action")

        window = Window.__new__(Window)
        window.video_files = [step]
        window.current_video_index = 0
        window.operator_paused = False
        window.image_based = True
        window._label_mode = True
        window.image_canvas = None
        window.play_delay_timer = None
        window.check_timer = type("T", (), {"start": lambda self: None})()
        window.completion_label = type("L", (), {"hide": lambda self: None})()
        window.progress_label = type("L", (), {"hide": lambda self: None})()
        window.playlist_finished = False
        window.waiting_for_results = False
        window.total_videos = 1
        window._update_status_file = lambda *a, **k: None
        window.video_start_time = 0
        # Same branch as Realtime Play start: skip_gap + cognitive_encode → encode.
        window._start_playback()
        self.assertEqual(window._label_phase, "encode")
        self.assertEqual(started[0][0], step["path"])
        self.assertNotIn("action", started)


if __name__ == "__main__":
    unittest.main()
