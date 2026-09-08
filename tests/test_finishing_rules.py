"""Finishing rules for PASS / PRESS / TARGET / GOAL. No live cameras."""

import math
import os
import sys
import types
import unittest
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

for name in ("ultralytics", "mss"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["ultralytics"].YOLO = object
sys.modules["mss"].mss = lambda *a, **k: None
if "torch" not in sys.modules:
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: False, empty_cache=lambda: None)
    sys.modules["torch"] = torch

import sim_outcome_audit as audit  # noqa: E402
import simust_realtime as rt  # noqa: E402

rt.ArenaSimulator.GOAL_PROBE = False


def _analyze(action, screens, frames, after=None, session_s=3.2):
    start = datetime.strptime("12:00:00.000000", "%H:%M:%S.%f")
    end = start + timedelta(seconds=session_s)
    action_data = {
        "id": f"{action}-{screens[0]}",
        "action": action,
        "screens": screens,
        "start_time": audit.fmt_dt(start),
        "end_time": audit.fmt_dt(end),
        "data": frames,
    }
    all_data = [action_data]
    if after:
        all_data.append({
            "id": "BETWEEN",
            "action": "BETWEEN_SESSIONS",
            "screens": [],
            "start_time": audit.fmt_dt(end),
            "end_time": audit.fmt_dt(end + timedelta(seconds=1.2)),
            "data": after,
        })
    return rt.analyze_action_with_context(action_data, rt.GOAL_LINES, action, all_data, 0)


def _lerp(a, b, u):
    u = max(0.0, min(1.0, u))
    return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)


def _travel(start, dest, arrive_s, hold_s, back=None, back_s=0.65, fps=25.0):
    data = []
    n_go = max(1, int(arrive_s * fps))
    n_hold = max(0, int(hold_s * fps))
    n_back = max(0, int(back_s * fps)) if back is not None else 0
    t = 0.0
    dt = 1.0 / fps
    for i in range(n_go):
        pos = _lerp(start, dest, (i + 1) / n_go)
        data.append({"t": round(t, 3), "b": [[int(pos[0]), int(pos[1])]], "p": [[280, 268]], "hp": [280, 268]})
        t += dt
    for _ in range(n_hold):
        data.append({"t": round(t, 3), "b": [[int(dest[0]), int(dest[1])]], "p": [[280, 268]], "hp": [280, 268]})
        t += dt
    if back is not None:
        for i in range(n_back):
            pos = _lerp(dest, back, (i + 1) / n_back)
            data.append({"t": round(t, 3), "b": [[int(pos[0]), int(pos[1])]], "p": [[280, 268]], "hp": [280, 268]})
            t += dt
    return data


def _outside_start(screen):
    """Real GOAL send origin for that screen."""
    return rt.goal_send_origin([screen])


def _beyond_post(p_end, p_other, extra=10.0):
    vx, vy = p_end[0] - p_other[0], p_end[1] - p_other[1]
    nlen = math.hypot(vx, vy) or 1.0
    return (p_end[0] + (vx / nlen) * extra, p_end[1] + (vy / nlen) * extra)


class FinishingRuleTests(unittest.TestCase):
    def test_pass_press_target_correct_is_arrive_and_return(self):
        for action, screens in (("PASS", ["2"]), ("TARGET", ["9L"]), ("PRESS", ["2"])):
            row = audit.run_case(action, screens, "correct", session_s=3.2, after_s=1.2)
            self.assertEqual(row["actual"], "Correct", msg=(action, row))

    def test_pass_target_miss_is_arrive_and_stay(self):
        for action, screens in (("PASS", ["2"]), ("TARGET", ["9L"])):
            row = audit.run_case(action, screens, "miss", session_s=3.2, after_s=1.2)
            self.assertEqual(row["actual"], "Miss", msg=(action, row))

    def test_press_arrive_without_return_is_correct_not_miss(self):
        """PRESS has no Miss: reaching the zone is Correct even if the player stays."""
        row = audit.run_case("PRESS", ["2"], "miss", session_s=3.2, after_s=1.2)
        self.assertEqual(row["actual"], "Correct", msg=row)
        screen = "3"
        start = (314.0, 110.0)
        dest = (83.0, 142.0)
        session = _travel(start, dest, arrive_s=0.80, hold_s=2.2)
        for row_frame in session:
            row_frame["p"] = row_frame["b"]
            row_frame["b"] = []
        result = _analyze("PRESS", [screen], session)
        self.assertEqual(result.get("Result"), "Correct", msg=result)
        self.assertNotEqual(result.get("Result"), "Miss")

    def test_pass_press_target_late_after_session(self):
        for action, screens in (("PASS", ["2"]), ("TARGET", ["9L"]), ("PRESS", ["2"])):
            row = audit.run_case(action, screens, "late", session_s=3.2, late_s=1.2)
            self.assertEqual(row["actual"], "Late", msg=(action, row))

    def test_pass_press_target_never_arrive_is_wrong(self):
        for action, screens in (("PASS", ["2"]), ("TARGET", ["9L"]), ("PRESS", ["2"])):
            row = audit.run_case(action, screens, "wrong", session_s=3.2, after_s=1.2)
            self.assertEqual(row["actual"], "Wrong", msg=(action, row))

    def test_goal_correct_is_arrive_and_stay(self):
        for screen in ("8", "1"):
            row = audit.run_case("GOAL", [screen], "correct", session_s=3.2, after_s=1.2)
            self.assertEqual(row["actual"], "Correct", msg=(screen, row))

    def test_goal_late_is_arrive_after_and_stay(self):
        for screen in ("8", "1"):
            row = audit.run_case("GOAL", [screen], "late", session_s=3.2, late_s=1.2)
            self.assertEqual(row["actual"], "Late", msg=(screen, row))

    def test_goal_never_arrive_is_wrong(self):
        for screen in ("8", "1"):
            row = audit.run_case("GOAL", [screen], "wrong", session_s=3.2, after_s=1.2)
            self.assertEqual(row["actual"], "Wrong", msg=(screen, row))

    def test_goal_return_during_session_is_wrong(self):
        for screen in ("8", "1"):
            start = _outside_start(screen)
            mid = rt.ArenaSimulator()._line_target([screen])[0]
            session = _travel(start, mid, arrive_s=0.70, hold_s=0.20, back=start, back_s=0.65)
            result = _analyze("GOAL", [screen], session)
            self.assertEqual(result.get("Result"), "Wrong", msg=(screen, result))

    def test_goal_return_after_session_is_wrong(self):
        screen = "8"
        start = _outside_start(screen)
        mid = rt.ArenaSimulator()._line_target([screen])[0]
        session = _travel(start, mid, arrive_s=0.70, hold_s=2.4)
        after = _travel(mid, start, arrive_s=0.65, hold_s=0.40)
        result = _analyze("GOAL", [screen], session, after=after)
        self.assertEqual(result.get("Result"), "Wrong", msg=result)

    def test_goal_late_then_return_is_wrong(self):
        screen = "8"
        start = _outside_start(screen)
        mid = rt.ArenaSimulator()._line_target([screen])[0]
        session = _travel(start, start, arrive_s=0.20, hold_s=3.0)
        after = _travel(start, mid, arrive_s=0.40, hold_s=0.10, back=start, back_s=0.50)
        result = _analyze("GOAL", [screen], session, after=after)
        self.assertEqual(result.get("Result"), "Wrong", msg=result)

    def test_pass_return_after_session_is_correct(self):
        screen = "2"
        start = rt.ArenaSimulator.BALL_HOME
        mid = rt.ArenaSimulator()._line_target([screen])[0]
        session = _travel(start, mid, arrive_s=0.70, hold_s=2.4)
        after = _travel(mid, start, arrive_s=0.65, hold_s=0.40)
        result = _analyze("PASS", [screen], session, after=after)
        self.assertEqual(result.get("Result"), "Correct", msg=result)

    def test_goal_posts_and_center_count_as_correct(self):
        for screen in ("8", "1"):
            line = rt.GOAL_LINES[screen]
            start = _outside_start(screen)
            spots = {
                "center": ((line["p0"][0] + line["p1"][0]) / 2.0, (line["p0"][1] + line["p1"][1]) / 2.0),
                "post_a": line["p0"],
                "post_b": line["p1"],
                "past_a": _beyond_post(line["p0"], line["p1"], 8.0),
                "past_b": _beyond_post(line["p1"], line["p0"], 8.0),
            }
            for label, xy in spots.items():
                session = _travel(start, xy, arrive_s=0.70, hold_s=2.4)
                result = _analyze("GOAL", [screen], session)
                self.assertEqual(result.get("Result"), "Correct", msg=(screen, label, xy, result))
                depth = rt.arrival_depth_for(screen, "GOAL")
                self.assertTrue(rt.in_goal_area(xy, line["p0"], line["p1"], depth), msg=(screen, label, xy))

    def test_goal_upper_net_outside_band_is_wrong(self):
        """Points far above the line fail dist + proj_t. No rectangle scoring."""
        for screen in ("8", "1"):
            start = _outside_start(screen)
            p0, p1 = rt.GOAL_LINES[screen]["p0"], rt.GOAL_LINES[screen]["p1"]
            depth = rt.arrival_depth_for(screen, "GOAL")
            for name in ("upper_center_90", "upper_corner_a", "upper_corner_b"):
                dest = rt.goal_probe_xy(p0, p1, name)
                self.assertFalse(rt.in_goal_area(dest, p0, p1, depth), msg=(screen, name, dest))
                result = _analyze("GOAL", [screen], _travel(start, dest, arrive_s=0.70, hold_s=2.4))
                self.assertEqual(result.get("Result"), "Wrong", msg=(screen, name, result))

    def test_goal_pass_through_line_toward_camera_is_correct(self):
        """From the real origin, a shot that crosses the line and stops past it is a goal."""
        screen = "8"
        start = _outside_start(screen)
        p0, p1 = rt.GOAL_LINES[screen]["p0"], rt.GOAL_LINES[screen]["p1"]
        dest = rt.goal_probe_xy(p0, p1, "outside_40")
        result = _analyze("GOAL", [screen], _travel(start, dest, arrive_s=0.70, hold_s=2.4))
        self.assertEqual(result.get("Result"), "Correct", msg=result)

    def test_goal_pass_through_past_band_toward_camera_is_correct(self):
        """Leaving the 73px band on the camera side is still a finish, not a come-back."""
        screen = "8"
        start = _outside_start(screen)
        p0, p1 = rt.GOAL_LINES[screen]["p0"], rt.GOAL_LINES[screen]["p1"]
        dest = rt.goal_probe_xy(p0, p1, "outside_100")
        result = _analyze("GOAL", [screen], _travel(start, dest, arrive_s=0.70, hold_s=2.4))
        self.assertEqual(result.get("Result"), "Correct", msg=result)

    def test_goal_origin_sidestep_is_wrong(self):
        """Stay near the send origin and never attack the line."""
        start = rt.goal_send_origin(["8"])
        dest = (start[0] - 80.0, start[1] + 10.0)
        result = _analyze("GOAL", ["8"], _travel(start, dest, arrive_s=0.60, hold_s=2.4))
        self.assertEqual(result.get("Result"), "Wrong", msg=result)

    def test_goal_send_origin_is_screen_8_live_point(self):
        self.assertEqual(rt.goal_send_origin(["8"]), (961.0, 82.0))
        self.assertEqual(rt.goal_send_origin(["1"]), (311.0, 103.0))
        sim = rt.ArenaSimulator()
        sim.start_action("GOAL", ["8"])
        self.assertEqual(sim.start_xy, (961.0, 82.0))

    def test_target_6l_6r_9l_9r_start_from_screen8_origin(self):
        origin = (961.0, 82.0)
        for screens in (["6L"], ["6R"], ["9L"], ["9R"]):
            sim = rt.ArenaSimulator()
            sim.start_action("TARGET", screens)
            self.assertEqual(sim.start_xy, origin, msg=screens)
            self.assertEqual(rt.target_send_origin(screens), origin)
            self.assertIsNotNone(sim.line_p0)
        other = rt.ArenaSimulator()
        other.start_action("TARGET", ["2"])
        self.assertEqual(other.start_xy, rt.ArenaSimulator.BALL_HOME)

    def test_goal_aims_rotate_corners_and_upper(self):
        """Live GOAL shots must not all go to the line midpoint."""
        sim = rt.ArenaSimulator()
        seen_in = []
        seen_out = []
        targets = []
        for _ in range(12):
            sim.start_action("GOAL", ["8"])
            targets.append(tuple(round(v, 1) for v in sim.target_xy))
            if sim.intended in ("correct", "late"):
                seen_in.append(sim.aim_name)
            else:
                seen_out.append(sim.aim_name)
        self.assertGreaterEqual(len(set(targets)), 5)
        self.assertTrue({"post_a", "post_b"} & set(seen_in))
        self.assertIn("upper_center_40", seen_in)
        self.assertTrue({"upper_center_90", "upper_corner_a", "upper_corner_b"} & set(seen_out))
        self.assertNotEqual(seen_in[:4], ["line_center"] * len(seen_in[:4]))

    def test_goal_approach_dropout_is_correct(self):
        """Sparse detections that still enter the line + proj_t band stay Correct."""
        screen = "8"
        start = _outside_start(screen)
        p0, p1 = rt.GOAL_LINES[screen]["p0"], rt.GOAL_LINES[screen]["p1"]
        dest = rt.goal_probe_xy(p0, p1, "outside_40")
        session = _travel(start, dest, arrive_s=0.50, hold_s=0.0)
        # Keep every 3rd frame so the track looks like YOLO dropouts.
        session = [row if i % 3 == 0 else {**row, "b": []} for i, row in enumerate(session)]
        result = _analyze("GOAL", [screen], session)
        self.assertEqual(result.get("Result"), "Correct", msg=result)

    def test_goal_physical_ball_grows_blurs_and_drops_frames(self):
        clock = audit.FakeClock(4000.0)
        prev_time = rt.time.time
        rt.time.time = clock.time
        try:
            sim = rt.ArenaSimulator()
            sim.start_action("GOAL", ["8"])
            sim.intended = "correct"
            radii = []
            misses = 0
            detected = 0
            max_blur = 0.0
            for _ in range(50):
                balls, _, _ = sim.step(rt.SIM_FRAME_WIDTH, rt.SIM_FRAME_HEIGHT)
                radii.append(sim.last_ball_radius)
                max_blur = max(max_blur, sim.last_blur)
                if balls:
                    detected += 1
                else:
                    misses += 1
                clock.advance(1.0 / 25.0)
            self.assertGreater(radii[-1], radii[0] + 3.0)
            self.assertGreater(detected, 10)
            self.assertGreaterEqual(misses, 1)
            self.assertGreater(max_blur, 2.0)
            self.assertTrue(sim.last_detected)
            depth = rt.arrival_depth_for("8", "GOAL")
            self.assertTrue(rt.in_goal_area(sim.last_ball, sim.line_p0, sim.line_p1, depth))
        finally:
            rt.time.time = prev_time

    def test_target_physical_blur_and_dropouts_keep_scoring(self):
        clock = audit.FakeClock(5000.0)
        prev_time = rt.time.time
        rt.time.time = clock.time
        try:
            sim = rt.ArenaSimulator()
            sim.start_action("TARGET", ["9L"])
            sim.intended = "correct"
            misses = 0
            detected = 0
            max_blur = 0.0
            for _ in range(50):
                balls, _, _ = sim.step(rt.SIM_FRAME_WIDTH, rt.SIM_FRAME_HEIGHT)
                max_blur = max(max_blur, sim.last_blur)
                if balls:
                    detected += 1
                else:
                    misses += 1
                clock.advance(1.0 / 25.0)
            self.assertGreater(detected, 10)
            self.assertGreaterEqual(misses, 1)
            self.assertGreater(max_blur, 1.5)
            row = audit.run_case("TARGET", ["9L"], "correct", session_s=3.2, after_s=1.2)
            self.assertEqual(row["actual"], "Correct", msg=row)
        finally:
            rt.time.time = prev_time

    def test_pass_static_far_blob_is_not_a_return(self):
        """S5/S10: a persistent junk ball on the far camera must not flip Miss to Correct."""
        screen = "13"
        start = rt.ArenaSimulator.BALL_HOME
        p0, p1 = rt.GOAL_LINES[screen]["p0"], rt.GOAL_LINES[screen]["p1"]
        dest = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
        session = _travel(start, dest, arrive_s=0.80, hold_s=2.2)
        junk = [{"t": round(i * 0.04, 3), "b": [[724, 134]], "p": [[280, 268]], "hp": [280, 268]} for i in range(30)]
        result = _analyze("PASS", [screen], session, after=junk)
        self.assertEqual(result.get("Result"), "Miss", msg=result)

    def test_pass_player_ball_after_long_gap_is_not_a_return(self):
        """Do not treat a later action (t > 2.5s) as this shot bouncing back."""
        screen = "13"
        start = rt.ArenaSimulator.BALL_HOME
        p0, p1 = rt.GOAL_LINES[screen]["p0"], rt.GOAL_LINES[screen]["p1"]
        dest = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
        session = _travel(start, dest, arrive_s=0.80, hold_s=2.2)
        later = _travel((334, 123), (350, 160), arrive_s=0.40, hold_s=0.40)
        for row in later:
            row["t"] = round(row["t"] + 16.0, 3)
        result = _analyze("PASS", [screen], session, after=later)
        self.assertEqual(result.get("Result"), "Miss", msg=result)

    def test_pass_between_motion_after_dropout_is_miss(self):
        """Last-of-video: arrive, disappear, then player-side motion ~2.5s later is Miss."""
        screen = "13"
        start = rt.ArenaSimulator.BALL_HOME
        p0, p1 = rt.GOAL_LINES[screen]["p0"], rt.GOAL_LINES[screen]["p1"]
        dest = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
        session = _travel(start, dest, arrive_s=0.80, hold_s=0.05)
        # BETWEEN starts after session; first ball appears after a long dropout.
        after = []
        for i in range(40):
            t = round(0.05 + i * 0.04, 3)
            after.append({"t": t, "b": [], "p": [[280, 268]], "hp": [280, 268]})
        for i in range(20):
            t = round(2.0 + i * 0.04, 3)
            after.append({"t": t, "b": [[380, 300 - i], [380, 300 - i]], "p": [[280, 268]], "hp": [280, 268]})
            after[-1]["b"] = [[380, 300 - i]]
        result = _analyze("PASS", [screen], session, after=after, session_s=1.0)
        self.assertEqual(result.get("Result"), "Miss", msg=result)

    def test_press_post_graze_50px_is_correct(self):
        """S31: PRESS near screen-3 post (~50px) counts as Correct (no return required)."""
        screen = "3"
        start = (314.0, 110.0)
        p0, p1 = rt.GOAL_LINES[screen]["p0"], rt.GOAL_LINES[screen]["p1"]
        dest = (83.0, 142.0)
        depth = rt.arrival_depth_for(screen, "PRESS")
        self.assertTrue(
            rt.in_goal_area(dest, p0, p1, depth, post_radius=rt.PRESS_POST_RADIUS),
            msg=(dest, depth),
        )
        session = _travel(start, dest, arrive_s=0.80, hold_s=2.2)
        for row in session:
            row["p"] = row["b"]
            row["b"] = []
        result = _analyze("PRESS", [screen], session)
        self.assertEqual(result.get("Result"), "Correct", msg=result)

    def test_compute_distances_by_video_splits_hips(self):
        blocks = [
            {
                "id": "S1",
                "action": "PASS",
                "start_time": "10:00:00.000000",
                "data": [
                    {"t": 0.0, "hp": [100, 200]},
                    {"t": 0.2, "hp": [140, 200]},
                    {"t": 0.4, "hp": [180, 200]},
                    {"t": 0.6, "hp": [220, 200]},
                ],
            },
            {
                "id": "BETWEEN",
                "action": "BETWEEN_SESSIONS",
                "start_time": "10:00:01.000000",
                "data": [{"t": 0.0, "hp": [220, 200]}, {"t": 0.2, "hp": [260, 200]}],
            },
            {
                "id": "S2",
                "action": "PASS",
                "start_time": "10:00:10.000000",
                "data": [
                    {"t": 0.0, "hp": [300, 200]},
                    {"t": 0.2, "hp": [340, 200]},
                    {"t": 0.4, "hp": [380, 200]},
                    {"t": 0.6, "hp": [420, 200]},
                ],
            },
        ]
        results = [
            {"id": "S1", "video_index": 1, "total_distance": 0},
            {"id": "S2", "video_index": 2, "total_distance": 0},
        ]
        by_v = rt.compute_distances_by_video(blocks, results, fallback_m_per_px=0.0259)
        self.assertIn(1, by_v)
        self.assertIn(2, by_v)
        self.assertGreater(by_v[1], 0)
        self.assertGreater(by_v[2], 0)

    def test_pass_late_uses_finish_band_not_tiny_screen_threshold(self):
        """S9/S13: PASS late uses the 100px arrival band, not 10–30px screen gates."""
        screen = "14"
        start = rt.ArenaSimulator.BALL_HOME
        session = _travel(start, start, arrive_s=0.20, hold_s=3.0)
        p0, p1 = rt.GOAL_LINES[screen]["p0"], rt.GOAL_LINES[screen]["p1"]
        dest = ((p0[0] + p1[0]) / 2.0 - 50.0, (p0[1] + p1[1]) / 2.0)
        after = _travel(start, dest, arrive_s=0.50, hold_s=0.50)
        result = _analyze("PASS", [screen], session, after=after)
        self.assertEqual(result.get("Result"), "Late", msg=result)
        self.assertGreater(result.get("Min Distance (px)") or 0, 30)

    def test_pass_post_graze_then_return_is_correct(self):
        """S4/S24: 35–45px from a keypoint still counts as arrival if the ball comes back."""
        screen = "3"
        start = rt.ArenaSimulator.BALL_HOME
        p0 = rt.GOAL_LINES[screen]["p0"]
        dest = (p0[0] + 28.0, p0[1] - 28.0)
        depth = rt.arrival_depth_for(screen, "PASS")
        self.assertTrue(rt.in_goal_area(dest, rt.GOAL_LINES[screen]["p0"], rt.GOAL_LINES[screen]["p1"], depth, post_radius=rt.PASS_POST_RADIUS))
        session = _travel(start, dest, arrive_s=0.70, hold_s=0.15, back=start, back_s=0.80)
        result = _analyze("PASS", [screen], session)
        self.assertEqual(result.get("Result"), "Correct", msg=result)

    def test_pass_near_post_then_disappear_is_miss(self):
        """S19: enter the graze band and never return to the player → Miss."""
        screen = "14"
        start = rt.ArenaSimulator.BALL_HOME
        p0 = rt.GOAL_LINES[screen]["p0"]
        dest = (p0[0] - 20.0, p0[1] - 25.0)
        session = _travel(start, dest, arrive_s=0.80, hold_s=2.2)
        result = _analyze("PASS", [screen], session)
        self.assertEqual(result.get("Result"), "Miss", msg=result)

    def test_displacement_polygon_is_not_drawn_before_detection_hook(self):
        self.assertGreater(rt.LATE_ANALYSIS_DELAY, 2.0)
        src = open(os.path.join(ROOT, "simust_realtime.py"), encoding="utf-8")
        try:
            text = src.read()
        finally:
            src.close()
        self.assertNotIn("cv2.polylines(stitched", text)
        self.assertIn("cv2.polylines(frame", text)


if __name__ == "__main__":
    unittest.main()
