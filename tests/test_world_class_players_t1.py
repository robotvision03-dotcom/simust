"""Elite Players 2 (S4 / C5): scripted dual-field 5×9 (ex–World Class Players)."""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _idx(test_num: int, action_in_set: int) -> int:
    return (int(test_num) - 1) * 9 + (int(action_in_set) - 1)


class ElitePlayers2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import smart_simust_player as ssp

        cls.ssp = ssp

    def test_s4_series_detection(self):
        self.assertEqual(
            self.ssp._elite_s4_series_num("L04-Elite/S4.T1"), 1
        )
        group, num = self.ssp._combined_series_group_and_num(
            "L04-Elite/S4.T2", "elite"
        )
        self.assertEqual(group, 4)
        self.assertEqual(num, 2)

    def test_image_dir_elite_players2(self):
        expected = os.path.join(
            ROOT, "static", "players", "Elite", "players2"
        )
        self.assertEqual(
            os.path.normpath(self.ssp.ELITE_PLAYERS2_IMAGE_DIR),
            os.path.normpath(expected),
        )
        paths = self.ssp._wc_players_image_paths()
        self.assertIn(self.ssp.WC_PLAYERS_PASS, paths)
        self.assertTrue(
            paths[self.ssp.WC_PLAYERS_PASS]
            .replace("\\", "/")
            .endswith("Elite/players2/pass.png")
        )

    def test_wc_video_root_static_players_videos(self):
        expected = os.path.join(ROOT, "static", "Players-Videos")
        self.assertEqual(
            os.path.normpath(self.ssp.WC_PLAYERS_VIDEO_ROOT),
            os.path.normpath(expected),
        )
        stills = self.ssp._wc_players_still_paths()
        self.assertTrue(stills.get("left_post"))
        self.assertTrue(stills.get("right_post"))

    def test_wc_crossball_goals_match_side(self):
        pl = self.ssp._build_world_class_s0_playlist(1)
        a2 = pl[_idx(1, 2)]
        a5 = pl[_idx(1, 5)]
        self.assertEqual((a2.get("field_screens") or {}).get("A"), ["A5R"])
        path2 = os.path.basename((a2.get("screen_images") or {}).get("A5") or "").lower()
        self.assertTrue("right" in path2 and "cross" in path2, path2)
        self.assertEqual((a5.get("field_screens") or {}).get("A"), ["A2L"])
        path5 = os.path.basename((a5.get("screen_images") or {}).get("A2") or "").lower()
        self.assertTrue("left" in path5 and "cross" in path5, path5)
        # Remapped tests keep Cross-Right on a right-half seat (A or B).
        for test_num in range(2, 6):
            entry = pl[_idx(test_num, 2)]
            fs = entry.get("field_screens") or {}
            goals = list(fs.get("A") or []) + list(fs.get("B") or [])
            self.assertTrue(goals, f"t{test_num} a2")
            g = goals[0]
            parent = self.ssp._sid(g)
            self.assertTrue(str(g).endswith("R"), f"t{test_num} {g}")
            arena = int(parent[1:])
            self.assertIn(arena, self.ssp.WC_CROSSBALL_RIGHT_ARENAS)
            media = os.path.basename(
                (entry.get("screen_images") or {}).get(parent) or ""
            ).lower()
            self.assertTrue("right" in media and "cross" in media, media)

    def test_content_label_players2(self):
        self.assertEqual(
            self.ssp._content_type_label("L04-Elite/S4.T1"), "Players 2"
        )
        self.assertEqual(
            self.ssp._component_set_label("L04-Elite/S4.T1"), "C5.T1"
        )

    def test_playlist_forty_five(self):
        pl = self.ssp._build_elite_players2_playlist(1)
        self.assertEqual(len(pl), 45)
        for test_num in range(1, 6):
            chunk = pl[_idx(test_num, 1) : _idx(test_num, 1) + 9]
            self.assertEqual(len(chunk), 9)
            for i, entry in enumerate(chunk, start=1):
                self.assertEqual(int(entry.get("test_num") or 0), test_num)
                self.assertEqual(int(entry.get("action_in_set") or 0), i)
                self.assertTrue(entry.get("elite_players2_scenario"))
                self.assertFalse(entry.get("wc_players_press_goal"))

    def test_test1_goals_no_press(self):
        pl = self.ssp._build_elite_players2_playlist(1)
        expect = [
            (1, "PASS", ["A5"], []),
            (2, "PASS", ["A5R"], []),  # CrossBall-Right → right half
            (3, "PASS", [], ["B6"]),
            (4, "PASS", [], ["B2"]),
            (5, "PASS", ["A2L"], []),  # CrossBall-Left → left half
            (6, "PASS", ["A3"], []),
            (7, "PASS", ["A1", "A5"], []),
            (8, "PASS", ["A1"], ["B7"]),
            (9, "PASS", [], ["B7"]),
        ]
        for entry, (anum, action, goals_a, goals_b) in zip(pl[:9], expect):
            self.assertEqual(entry.get("action"), action)
            fs = entry.get("field_screens") or {}
            self.assertEqual(list(fs.get("A") or []), goals_a, f"a{anum}")
            self.assertEqual(list(fs.get("B") or []), goals_b, f"a{anum}")

    def test_no_running_image(self):
        pl = self.ssp._build_elite_players2_playlist(1)
        for entry in pl:
            for path in (entry.get("screen_images") or {}).values():
                self.assertNotIn(
                    "running",
                    os.path.basename(path).lower(),
                    entry.get("label"),
                )

    def test_pass_goals_not_gray(self):
        pl = self.ssp._build_elite_players2_playlist(1)
        for anum in (3, 6):
            entry = pl[anum - 1]
            imgs = entry.get("screen_images") or {}
            sid = "B6" if anum == 3 else "A3"
            self.assertTrue(
                os.path.basename(imgs.get(sid) or "").lower().endswith("pass.png"),
                f"a{anum} {sid}",
            )
            self.assertNotIn("solid_bg_", os.path.basename(imgs.get(sid) or ""))

    def test_actions_8_9_fixed_across_tests(self):
        pl = self.ssp._build_elite_players2_playlist(1)
        a8_t1 = pl[_idx(1, 8)]
        a9_t1 = pl[_idx(1, 9)]
        for test_num in range(2, 6):
            a8 = pl[_idx(test_num, 8)]
            a9 = pl[_idx(test_num, 9)]
            self.assertEqual(
                a8.get("field_screens"), a8_t1.get("field_screens"), f"t{test_num} a8"
            )
            self.assertEqual(
                a9.get("field_screens"), a9_t1.get("field_screens"), f"t{test_num} a9"
            )
            self.assertEqual(
                a8.get("screen_images"), a8_t1.get("screen_images"), f"t{test_num} a8 imgs"
            )
            # Posts stay on Field B (never flipped onto A3/A4)
            imgs = a8.get("screen_images") or {}
            self.assertIn("left_post", os.path.basename(imgs.get("B3") or "").lower())
            self.assertIn("right_post", os.path.basename(imgs.get("B4") or "").lower())
            self.assertNotIn(
                "post", os.path.basename(imgs.get("A3") or "").lower()
            )
            self.assertNotIn(
                "post", os.path.basename(imgs.get("A4") or "").lower()
            )

    def test_test2_a1_clockwise_from_test1(self):
        pl = self.ssp._build_elite_players2_playlist(1)
        t1 = pl[_idx(1, 1)]
        t2 = pl[_idx(2, 1)]
        t1_imgs = t1.get("screen_images") or {}
        t2_imgs = t2.get("screen_images") or {}
        for sid, path in t1_imgs.items():
            nxt = self.ssp._wc_ellipse_next(sid, 1)
            self.assertEqual(t2_imgs.get(nxt), path, f"{sid}→{nxt}")
        fs = t2.get("field_screens") or {}
        self.assertEqual(list(fs.get("A") or []), ["A6"])

    def test_timing_decay_and_series_reuse(self):
        on1, _ = self.ssp._wc_players_series_timing_ms(1)
        on2, _ = self.ssp._wc_players_series_timing_ms(2)
        self.assertLess(on2, on1)
        t1 = self.ssp._build_elite_players2_playlist(1)
        t3 = self.ssp._build_elite_players2_playlist(3)
        self.assertEqual(len(t3), 45)
        self.assertEqual(
            t1[_idx(2, 1)].get("field_screens"),
            t3[_idx(2, 1)].get("field_screens"),
        )
        self.assertLess(int(t3[0].get("on_ms") or 0), int(t1[0].get("on_ms") or 0))

    def test_world_class_c1t1_timing_doubled(self):
        base_on, base_gap = self.ssp._wc_players_series_timing_ms(1)
        scale = float(self.ssp.WC_PLAYERS_C1T1_TIME_SCALE)
        want_on, _ = self.ssp._snap_ms_to_display_fps(float(base_on) * scale)
        want_gap, _ = self.ssp._snap_ms_to_display_fps(float(base_gap) * scale)
        pl = self.ssp._build_world_class_s0_playlist(1)
        self.assertEqual(len(pl), 45)
        for entry in pl:
            self.assertEqual(int(entry.get("on_ms") or 0), want_on)
            self.assertEqual(int(entry.get("gap_ms") or 0), want_gap)
        # Later WC sub-levels are not doubled.
        pl2 = self.ssp._build_world_class_s0_playlist(2)
        on2, gap2 = self.ssp._wc_players_series_timing_ms(2)
        self.assertEqual(int(pl2[0].get("on_ms") or 0), on2)
        self.assertEqual(int(pl2[0].get("gap_ms") or 0), gap2)

    def test_world_class_s0_video_playlist(self):
        pl = self.ssp._build_world_class_s0_playlist(1)
        self.assertEqual(len(pl), 45)
        for entry in pl:
            self.assertTrue(entry.get("wc_players_video"))
            self.assertTrue(entry.get("wc_players_scenario"))
            imgs = entry.get("screen_images") or {}
            videos = [
                p
                for p in imgs.values()
                if str(p).lower().endswith((".mp4", ".mov", ".avi", ".mkv", ".webm"))
            ]
            self.assertGreater(len(videos), 0, entry.get("label"))
            people = list((entry.get("person_ids") or {}).values())
            self.assertEqual(
                len(people),
                len(set(people)),
                f"duplicate person in {entry.get('label')}: {people}",
            )

    def test_world_class_video_catalog_roles(self):
        cat = self.ssp._wc_players_video_catalog()
        for role in (
            "teammate",
            "defender",
            "defender_06",
            "duo",
            "opponent",
            "asking",
            "pass",
            "cross_left",
            "cross_right",
            "offside_right",
        ):
            self.assertGreater(len(cat.get(role) or []), 0, role)

    def test_world_class_stills_from_players_videos(self):
        stills = self.ssp._wc_players_still_paths()
        root = os.path.normpath(self.ssp.WC_PLAYERS_VIDEO_ROOT)
        for key in ("left_post", "right_post"):
            path = stills.get(key) or ""
            self.assertTrue(path, key)
            self.assertEqual(os.path.normpath(os.path.dirname(path)), root)

    def test_world_class_a8_9_fixed_and_posts_on_b(self):
        pl = self.ssp._build_world_class_s0_playlist(1)
        a8_t1 = pl[_idx(1, 8)]
        a9_t1 = pl[_idx(1, 9)]
        a8_imgs = a8_t1.get("screen_images") or {}
        a9_imgs = a9_t1.get("screen_images") or {}
        self.assertIn(
            "players-neutral-duo",
            os.path.basename(a8_imgs.get("B2") or "").lower(),
        )
        self.assertIn(
            "cross-offside-trap-right",
            os.path.basename(a8_imgs.get("B5") or "").lower(),
        )
        self.assertIn(
            "players-neutral-duo",
            os.path.basename(a9_imgs.get("B1") or "").lower(),
        )
        self.assertIn(
            "defender-neutral-06",
            os.path.basename(a9_imgs.get("B6") or "").lower(),
        )
        self.assertFalse(bool(a8_t1.get("require_all_goals")))
        for test_num in range(2, 6):
            a8 = pl[_idx(test_num, 8)]
            a9 = pl[_idx(test_num, 9)]
            self.assertEqual(
                a8.get("field_screens"), a8_t1.get("field_screens")
            )
            self.assertEqual(
                a9.get("field_screens"), a9_t1.get("field_screens")
            )
            self.assertEqual(a8.get("screen_images"), a8_t1.get("screen_images"))
            self.assertEqual(a9.get("screen_images"), a9_t1.get("screen_images"))
            imgs = a8.get("screen_images") or {}
            self.assertIn("left_post", os.path.basename(imgs.get("B3") or "").lower())
            self.assertIn("right_post", os.path.basename(imgs.get("B4") or "").lower())
            self.assertTrue(
                os.path.normpath(imgs["B3"]).startswith(
                    os.path.normpath(self.ssp.WC_PLAYERS_VIDEO_ROOT)
                )
            )


    def test_no_gray_filler_seats(self):
        ep = self.ssp._build_elite_players2_playlist(1)
        wc = self.ssp._build_world_class_s0_playlist(1)
        for entry in ep + wc:
            for path in (entry.get("screen_images") or {}).values():
                name = os.path.basename(str(path or "")).lower()
                self.assertNotIn("solid_bg_", name, entry.get("label"))
                self.assertFalse(name.startswith("gray"), entry.get("label"))
            # Action 5 must leave A3 empty (no gray tile).
            if int(entry.get("action_in_set") or 0) == 5 and int(
                entry.get("test_num") or 0
            ) == 1:
                self.assertNotIn("A3", entry.get("screen_images") or {})

    def test_release_screens_from_videos_keeps_peers(self):
        class FakeCanvas:
            def __init__(self):
                self._video_groups = [
                    {"cap": type("C", (), {"release": lambda self: None})(), "screens": {"A1", "A5"}},
                    {"cap": type("C", (), {"release": lambda self: None})(), "screens": {"A2"}},
                ]
                self._video_screens = {"A1", "A2", "A5"}
                self._video_fill_screens = set()

        # Bind helper onto a plain object like ImageCanvas.
        canvas = FakeCanvas()
        fn = self.ssp.ImageActionCanvas._release_screens_from_videos
        fn(canvas, ["A1"])
        seats = set()
        for group in canvas._video_groups:
            seats |= set(group.get("screens") or [])
        self.assertNotIn("A1", seats)
        self.assertIn("A5", seats)
        self.assertIn("A2", seats)

    def test_world_class_pass_goals_use_teammate_asking_video(self):
        pl = self.ssp._build_world_class_s0_playlist(1)
        # Center goals use Teammate-AskingForBall video (never pass.png / opponents).
        for anum, sid in ((1, "A5"), (3, "B6"), (6, "A3"), (7, "A1"), (8, "A1")):
            entry = pl[_idx(1, anum)]
            name = os.path.basename(
                (entry.get("screen_images") or {}).get(sid) or ""
            ).lower()
            self.assertTrue(
                name.startswith("teammate-askingforball"),
                f"a{anum} {sid}: {name}",
            )
            self.assertFalse(name.startswith("pass."), f"a{anum} {sid}")
            self.assertFalse(name.startswith("opponent-"), f"a{anum} {sid}")

    def test_world_class_no_duplicate_video_in_action(self):
        pl = self.ssp._build_world_class_s0_playlist(1)
        for entry in pl:
            paths = [
                p
                for p in (entry.get("screen_images") or {}).values()
                if str(p).lower().endswith((".mp4", ".mov", ".avi", ".mkv", ".webm"))
            ]
            self.assertEqual(
                len(paths),
                len(set(paths)),
                f"duplicate video in {entry.get('label')}",
            )


class GoalMouthA7B7(unittest.TestCase):
    def test_calibrate_order_includes_a7_b7(self):
        import simust_goal_calibrate as cal

        self.assertIn("A7", cal.FIELD_A_ORDER)
        self.assertIn("B7", cal.FIELD_B_ORDER)
        self.assertEqual(cal.SCREEN_TO_CABINET["A7"], "1")
        self.assertEqual(cal.SCREEN_TO_CABINET["B7"], "8")


if __name__ == "__main__":
    unittest.main()
