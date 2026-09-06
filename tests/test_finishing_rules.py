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

    def test_pass_press_target_miss_is_arrive_and_stay(self):
        for action, screens in (("PASS", ["2"]), ("TARGET", ["9L"]), ("PRESS", ["2"])):
            row = audit.run_case(action, screens, "miss", session_s=3.2, after_s=1.2)
            self.assertEqual(row["actual"], "Miss", msg=(action, row))

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
                self.assertTrue(rt.point_in_goal_mouth(xy, line["p0"], line["p1"]))

    def test_goal_upper_mouth_is_correct(self):
        for screen in ("8", "1"):
            start = _outside_start(screen)
            p0, p1 = rt.GOAL_LINES[screen]["p0"], rt.GOAL_LINES[screen]["p1"]
            for name in ("upper_center_90", "upper_corner_a", "upper_corner_b"):
                dest = rt.goal_probe_xy(p0, p1, name)
                result = _analyze("GOAL", [screen], _travel(start, dest, arrive_s=0.70, hold_s=2.4))
                self.assertEqual(result.get("Result"), "Correct", msg=(screen, name, result))

    def test_goal_pass_through_line_toward_camera_is_correct(self):
        """From the real origin, a shot that crosses the line and stops past it is a goal."""
        screen = "8"
        start = _outside_start(screen)
        p0, p1 = rt.GOAL_LINES[screen]["p0"], rt.GOAL_LINES[screen]["p1"]
        dest = rt.goal_probe_xy(p0, p1, "outside_40")
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

    def test_goal_approach_dropout_is_correct(self):
        """Ball still heading through the mouth when detections stop."""
        screen = "8"
        start = _outside_start(screen)
        p0, p1 = rt.GOAL_LINES[screen]["p0"], rt.GOAL_LINES[screen]["p1"]
        dest = rt.goal_probe_xy(p0, p1, "outside_40")
        session = _travel(start, dest, arrive_s=0.50, hold_s=0.0)
        result = _analyze("GOAL", [screen], session)
        self.assertEqual(result.get("Result"), "Correct", msg=result)


if __name__ == "__main__":
    unittest.main()
