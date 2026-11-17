"""Elite / World Class: a ball in the cylinder must switch screens immediately."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

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

import simust_realtime as rt  # noqa: E402
import smart_simust_player as player  # noqa: E402


class CylinderGoalPublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self.tmp.close()
        self.path_patch = patch.object(rt, "LIVE_ACTION_RESULT_FILE", self.tmp.name)
        self.path_patch.start()
        import simust_fields
        import simust_hip_calibrate as hc

        simust_fields.POLYGON_POINTS_A[:] = list(simust_fields._BUILTIN_POLYGON_POINTS_A)
        simust_fields.POLYGON_POINTS_B[:] = list(simust_fields._BUILTIN_POLYGON_POINTS_B)
        self._hip_zone = patch.object(hc, "zone_contains", return_value=None)
        self._hip_zone.start()
        self._hip_reload = patch.object(rt, "reload_hip_zone_calibration", lambda: None)
        self._hip_reload.start()
        cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
        cam.operator_paused = False
        cam._live_file_lock = threading.Lock()
        cam.channels = {}
        cam.session_lock = threading.Lock()
        cam.simulation_enabled = False
        cam.simulators = {}
        self.ended = []

        def fake_end(_s, _t, ch=None):
            target = ch or self.ch
            self.ended.append(True)
            target.session_active = False
            target.active_goal_lines = {}
            target.current_keypoints = []

        cam._end_session_locked = fake_end
        cam._field_is_simulated = lambda fid: False
        self.cam = cam
        line = rt.GOAL_LINES["13"]
        self.ch = types.SimpleNamespace(
            session_active=True,
            current_qr_block={"finish_balls": True},
            _display_seq=4,
            _cylinder_goal_seq=None,
            current_action="PASS",
            active_goal_lines={"13": {"p0": line["p0"], "p1": line["p1"]}},
            current_screens=["13"],
            current_block_id="S4",
            field_id="A",
            current_keypoints=["13"],
            kp_clear_frames_left=40,
            label="A",
        )
        cx, cy = rt.goal_circle_center(line["p0"], line["p1"])
        self.inside = (cx, cy)
        depth = rt.arrival_depth_for("13", "PASS")
        radius = rt.goal_circle_radius(depth, line["p0"], line["p1"])
        # Just outside the drawn cylinder — all screens now use strict 1/6 depth.
        self.near = (cx + radius + 40.0, cy)
        self.assertEqual(rt.approach_finish_depth("13", "PASS"), depth)

    def tearDown(self):
        self._hip_reload.stop()
        self._hip_zone.stop()
        self.path_patch.stop()
        try:
            os.remove(self.tmp.name)
        except OSError:
            pass

    def _ball(self, x, y, r=12.0):
        return {"center": (float(x), float(y)), "bbox": [x - r, y - r, x + r, y + r]}

    def _finish_pass_with_turn(self, sid, cx, cy, hip=True):
        """Approach into goal, then reverse while still in goal paint → Correct."""
        # Keep the approach outside the mouth so the hit frame only starts the watch.
        approach = self._ball(cx, cy + 90.0)
        self.cam._publish_goal_if_in_cylinder(self.ch, [approach])
        hit = self._ball(cx, cy)
        self.cam._publish_goal_if_in_cylinder(self.ch, [hit])
        self.assertIn(sid, getattr(self.ch, "_pass_hip_pending", None) or {})
        # Approach was cy+90 → cy (up). Clear reverse (~180°, ≥15°) still in goal.
        # B1 paint is tight — cy+18 can sit outside and would Wrong on leave.
        turned = self._ball(cx, cy + 12.0)
        self.cam._publish_goal_if_in_cylinder(self.ch, [turned])

    def test_ball_in_cylinder_writes_correct_live_result(self):
        # Goal hit + inbound heading, then ≥15° turn inside goal → Correct.
        cx, cy = self.inside
        self._finish_pass_with_turn("13", cx, cy)
        with open(self.tmp.name, encoding="utf-8") as handle:
            payload = json.load(handle)
        entry = payload["fields"]["A"]
        self.assertEqual(entry["result"], "Correct")
        self.assertEqual(entry["seq"], 4)
        self.assertEqual(self.ch._cylinder_goal_seq, 4)
        self.assertEqual(self.ended, [True])
        self.assertFalse(self.ch.session_active)
        self.assertEqual(self.ch.active_goal_lines, {})

    def test_ball_near_cylinder_does_not_score(self):
        """Mid-field (A2/cabinet 13) matches screens 1/6 — no approach band."""
        self.cam._publish_goal_if_in_cylinder(self.ch, [{"center": self.near}])
        self.assertFalse(os.path.getsize(self.tmp.name))
        self.assertEqual(self.ended, [])
        self.assertTrue(self.ch.session_active)

    def test_live_display_waits_for_hip_watch_on_real_pass(self):
        """A camera pass must not switch screens until the HIP watch accepts it."""
        snap = {
            "finish_balls": True,
            "data": [{"b": [[1, 1, 9]]}, {"b": [[2, 2, 9]]}],
            "screens": ["A1"],
        }
        preview = {"Result": "Correct", "Winning Screen": "A1"}
        with patch.object(rt, "analyze_action_with_context", return_value=preview):
            self.cam._run_live_display("A", snap, "PASS", ["A1"], "S4", [], None, 4)
        self.assertEqual(os.path.getsize(self.tmp.name), 0)
        self.assertTrue(self.ch.session_active)
        snap["pass_hip_result"] = "Correct"
        with patch.object(rt, "analyze_action_with_context", return_value=preview):
            self.cam._run_live_display("A", snap, "PASS", ["A1"], "S4", [], None, 4)
        with open(self.tmp.name, encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["fields"]["A"]["result"], "Correct")
        self.assertTrue(payload["fields"]["A"]["clear_now"])

    def test_ball_outside_does_not_write(self):
        self.cam._publish_goal_if_in_cylinder(self.ch, [{"center": (0.0, 0.0)}])
        self.assertFalse(os.path.getsize(self.tmp.name))
        self.assertEqual(self.ended, [])
        self.assertTrue(self.ch.session_active)

    def test_fast_ball_inside_hip_still_finishes(self):
        """Enter goal, no direction change, leave zone → Wrong try (retry, no advance)."""
        line = rt.GOAL_LINES["12"]
        self.ch.field_id = "A"
        self.ch.session_active = True
        self.ch.active_goal_lines = {"A1": {"p0": line["p0"], "p1": line["p1"]}}
        self.ch.current_screens = ["A1"]
        self.ch.current_action = "PASS"
        self.ch._cylinder_scored_screens = set()
        self.ch.current_qr_block = {"finish_balls": True, "data": []}
        self.ch._pass_hip_pending = {}
        self.ch._goal_ball_trail = []
        cx, cy = rt.goal_circle_center(line["p0"], line["p1"])
        # Straight inbound only — never reverse — then leave goal+HIP.
        self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx, cy + 80)])
        with patch.object(rt, "ball_overlaps_hip", return_value=True):
            self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx, cy + 40)])
            self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx, cy)])
            self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx, cy - 20)])
        self.assertIn("A1", self.ch._pass_hip_pending)
        self.assertNotIn("A1", self.ch.active_goal_lines)
        gone = self._ball(300.0, 20.0)
        with patch.object(rt, "ball_overlaps_hip", return_value=False):
            self.cam._publish_goal_if_in_cylinder(self.ch, [gone])
        self.assertTrue(self.ch.session_active)
        self.assertIn("A1", self.ch.active_goal_lines)
        self.assertEqual(os.path.getsize(self.tmp.name), 0)
        self.assertFalse(self.ch._pass_hip_pending)
        self.assertEqual(self.ended, [])

    def test_small_heading_jitter_in_hip_does_not_correct(self):
        """Manual/real: leave goal without ≥15° heading change → Wrong/retry."""
        line = rt.GOAL_LINES["12"]
        self.ch.field_id = "A"
        self.ch.session_active = True
        self.ch.active_goal_lines = {"A1": {"p0": line["p0"], "p1": line["p1"]}}
        self.ch.current_screens = ["A1"]
        self.ch.current_action = "PASS"
        self.ch._cylinder_scored_screens = set()
        self.ch.current_qr_block = {"finish_balls": True, "data": []}
        self.ch._pass_hip_pending = {}
        self.ch._goal_ball_trail = []
        cx, cy = rt.goal_circle_center(line["p0"], line["p1"])
        self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx, cy + 90)])
        self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx, cy + 40)])
        # Nearly straight inbound (<15°); tiny lateral noise must not Correct.
        self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx + 1.0, cy + 20)])
        self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx + 2.0, cy)])
        self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx + 2.0, cy - 20)])
        self.assertEqual(os.path.getsize(self.tmp.name), 0, "jitter must not Correct")
        self.assertTrue(self.ch.session_active)
        self.assertIn("A1", getattr(self.ch, "_pass_hip_pending", None) or {})
        # Leave goal without a ≥15° bounce → Wrong/retry.
        self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(300.0, 20.0)])
        self.assertTrue(self.ch.session_active)
        self.assertEqual(os.path.getsize(self.tmp.name), 0)
        self.assertEqual(self.ended, [])
        self.assertIn("A1", self.ch.active_goal_lines)
        self.assertFalse(self.ch._pass_hip_pending)

    def test_missed_frames_do_not_auto_correct(self):
        """Missing detections are not an exit and do not Correct without a ≥15° turn."""
        line = rt.GOAL_LINES["12"]
        self.ch.field_id = "A"
        self.ch.session_active = True
        self.ch.active_goal_lines = {"A1": {"p0": line["p0"], "p1": line["p1"]}}
        self.ch.current_screens = ["A1"]
        self.ch.current_action = "PASS"
        self.ch._cylinder_scored_screens = set()
        self.ch.current_qr_block = {"finish_balls": True, "data": []}
        self.ch._pass_hip_pending = {}
        self.ch._goal_ball_trail = []
        cx, cy = rt.goal_circle_center(line["p0"], line["p1"])
        self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx, cy + 40)])
        self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx, cy)])
        for _ in range(5):
            self.cam._publish_goal_if_in_cylinder(self.ch, [])
        self.assertTrue(self.ch.session_active)
        self.assertEqual(os.path.getsize(self.tmp.name), 0)
        self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx, cy + 24)])
        with open(self.tmp.name, encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["fields"]["A"]["result"], "Correct")

    def test_a2_goal_paint_without_hip_turn_does_not_correct(self):
        """Straight travel on A2 paint (<15° turn) must not advance."""
        line = rt.GOAL_LINES["13"]
        self.ch.field_id = "A"
        self.ch.session_active = True
        self.ch.active_goal_lines = {"A2": {"p0": line["p0"], "p1": line["p1"]}}
        self.ch.current_screens = ["A2"]
        self.ch.current_action = "PASS"
        self.ch._cylinder_scored_screens = set()
        self.ch.current_qr_block = {"finish_balls": True, "data": []}
        self.ch._pass_hip_pending = {}
        self.ch._goal_ball_trail = []
        xy = (610.0, 154.0)
        import simust_goal_paint as goal_paint

        self.assertTrue(goal_paint.contains("A2", xy[0], xy[1], radius_x=12, radius_y=12))
        self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(xy[0], xy[1] + 30)])
        self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(xy[0], xy[1])])
        self.assertIn("A2", self.ch._pass_hip_pending)
        # Continue nearly straight on paint (<15°) — still no Correct.
        self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(xy[0] + 1, xy[1] - 20)])
        self.assertEqual(os.path.getsize(self.tmp.name), 0)
        self.assertTrue(self.ch.session_active)

    def test_a1_and_a3_micro_reverse_noise_does_not_correct(self):
        """REAL Manual: sub-min-step reverse blips must Wrong/retry, not Correct."""
        for sid, cabinet, approach in (
            ("A1", "12", "vertical"),
            ("A3", "14", "horizontal"),
        ):
            with self.subTest(sid=sid):
                line = rt.GOAL_LINES[cabinet]
                self.ch.field_id = "A"
                self.ch.label = "A"
                self.ch.session_active = True
                self.ch.active_goal_lines = {sid: {"p0": line["p0"], "p1": line["p1"]}}
                self.ch.current_screens = [sid]
                self.ch.current_action = "PASS"
                self.ch._cylinder_scored_screens = set()
                self.ch.current_qr_block = {
                    "finish_balls": True,
                    "data": [],
                    "manual_coach": True,
                    "screens": [sid],
                }
                self.ch._pass_hip_pending = {}
                self.ch._goal_ball_trail = []
                self.ch._hidden_goal_lines = {}
                self.ended.clear()
                open(self.tmp.name, "w", encoding="utf-8").close()
                cx, cy = rt.goal_circle_center(line["p0"], line["p1"])
                if approach == "vertical":
                    inside = [
                        self._ball(cx, cy + 80.0),
                        self._ball(cx, cy + 40.0),
                        self._ball(cx, cy),
                        # 2px reverse — under PASS_DIR_REVERSE_MIN_STEP_PX.
                        self._ball(cx, cy + 2.0),
                    ]
                    leave = self._ball(cx, cy - 40.0)
                else:
                    inside = [
                        self._ball(cx - 90.0, cy),
                        self._ball(cx - 40.0, cy),
                        self._ball(cx, cy),
                        self._ball(cx + 2.0, cy),
                    ]
                    leave = self._ball(cx + 90.0, cy)
                trail = inside + [leave]
                self.cam._publish_goal_if_in_cylinder(self.ch, [inside[0]])
                for ball in inside[1:]:
                    self.cam._publish_goal_if_in_cylinder(self.ch, [ball])
                    self.assertEqual(
                        os.path.getsize(self.tmp.name),
                        0,
                        f"{sid} must not Correct mid-trail",
                    )
                self.assertIn(sid, getattr(self.ch, "_pass_hip_pending", None) or {})
                # Leave goal → Wrong/retry (no ≥15° turn).
                self.cam._publish_goal_if_in_cylinder(self.ch, [leave])
                self.assertTrue(self.ch.session_active, sid)
                self.assertEqual(os.path.getsize(self.tmp.name), 0, sid)
                self.assertEqual(self.ended, [], sid)
                self.assertIn(sid, self.ch.active_goal_lines)
                self.assertFalse(self.ch._pass_hip_pending)
                depth = rt.arrival_depth_for(sid, "PASS")
                rows = [
                    {
                        "b": [[
                            float(b["center"][0]),
                            float(b["center"][1]),
                            12.0,
                        ]]
                    }
                    for b in trail
                ]
                self.assertEqual(
                    rt.pass_hip_from_block(
                        {"data": rows}, sid, line["p0"], line["p1"], depth
                    ),
                    "Wrong",
                    sid,
                )

    def test_a3_and_b3_angled_bounce_in_hip_corrects(self):
        """Manual: hit screen and return at ~90° (not only 180°) → Correct."""
        for sid, cabinet, fid in (("A3", "14", "A"), ("B3", "7", "B")):
            with self.subTest(sid=sid):
                line = rt.GOAL_LINES[cabinet]
                self.ch.field_id = fid
                self.ch.label = fid
                self.ch.session_active = True
                self.ch.active_goal_lines = {sid: {"p0": line["p0"], "p1": line["p1"]}}
                self.ch.current_screens = [sid]
                self.ch.current_action = "PASS"
                self.ch._cylinder_scored_screens = set()
                self.ch.current_qr_block = {
                    "finish_balls": True,
                    "data": [],
                    "manual_coach": True,
                    "screens": [sid],
                }
                self.ch._pass_hip_pending = {}
                self.ch._goal_ball_trail = []
                self.ch._hidden_goal_lines = {}
                self.ended.clear()
                open(self.tmp.name, "w", encoding="utf-8").close()
                cx, cy = rt.goal_circle_center(line["p0"], line["p1"])
                # East into mouth, then ~90° return (north) while still in goal.
                self.cam._publish_goal_if_in_cylinder(
                    self.ch, [self._ball(cx - 90.0, cy)]
                )
                self.cam._publish_goal_if_in_cylinder(
                    self.ch, [self._ball(cx - 40.0, cy)]
                )
                self.cam._publish_goal_if_in_cylinder(
                    self.ch, [self._ball(cx, cy)]
                )
                self.cam._publish_goal_if_in_cylinder(
                    self.ch, [self._ball(cx + 10.0, cy)]
                )
                self.assertIn(sid, getattr(self.ch, "_pass_hip_pending", None) or {})
                self.cam._publish_goal_if_in_cylinder(
                    self.ch, [self._ball(cx + 10.0, cy - 40.0)]
                )
                with open(self.tmp.name, encoding="utf-8") as handle:
                    payload = json.load(handle)
                self.assertEqual(payload["fields"][fid]["result"], "Correct", sid)
                depth = rt.arrival_depth_for(sid, "PASS")
                rows = [
                    {"b": [[cx - 90.0, cy, 12.0]]},
                    {"b": [[cx - 40.0, cy, 12.0]]},
                    {"b": [[cx, cy, 12.0]]},
                    {"b": [[cx + 10.0, cy, 12.0]]},
                    {"b": [[cx + 10.0, cy - 40.0, 12.0]]},
                ]
                self.assertEqual(
                    rt.pass_hip_from_block(
                        {"data": rows}, sid, line["p0"], line["p1"], depth
                    ),
                    "Correct",
                    sid,
                )

    def test_a3_small_jitter_under_45_then_leave_is_wrong(self):
        """Under-threshold wobble (<15°) then leave goal → Wrong/retry."""
        line = rt.GOAL_LINES["14"]
        self.ch.field_id = "A"
        self.ch.label = "A"
        self.ch.session_active = True
        self.ch.active_goal_lines = {"A3": {"p0": line["p0"], "p1": line["p1"]}}
        self.ch.current_screens = ["A3"]
        self.ch.current_action = "PASS"
        self.ch._cylinder_scored_screens = set()
        self.ch.current_qr_block = {
            "finish_balls": True,
            "data": [],
            "manual_coach": True,
            "screens": ["A3"],
        }
        self.ch._pass_hip_pending = {}
        self.ch._goal_ball_trail = []
        self.ch._hidden_goal_lines = {}
        cx, cy = rt.goal_circle_center(line["p0"], line["p1"])
        self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx - 90.0, cy)])
        self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx - 40.0, cy)])
        self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx, cy)])
        # ~8° wobble still inside A3 paint — under PASS_DIR_CHANGE_DEG (15°).
        self.cam._publish_goal_if_in_cylinder(
            self.ch, [self._ball(cx + 14.0, cy - 2.0)]
        )
        self.assertEqual(os.path.getsize(self.tmp.name), 0)
        self.assertIn("A3", getattr(self.ch, "_pass_hip_pending", None) or {})
        self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx + 90.0, cy)])
        self.assertTrue(self.ch.session_active)
        self.assertEqual(os.path.getsize(self.tmp.name), 0)
        self.assertIn("A3", self.ch.active_goal_lines)
        self.assertFalse(self.ch._pass_hip_pending)

    def test_a3_cabinet_14_straight_through_retries(self):
        """Live path with cabinet id 14 (not A3) must still HIP-watch, not entry-Correct."""
        line = rt.GOAL_LINES["14"]
        self.ch.field_id = "A"
        self.ch.label = "A"
        self.ch.session_active = True
        self.ch.active_goal_lines = {"14": {"p0": line["p0"], "p1": line["p1"]}}
        self.ch.current_screens = ["14"]
        self.ch.current_action = "PASS"
        self.ch._cylinder_scored_screens = set()
        self.ch.current_qr_block = {
            "finish_balls": True,
            "data": [],
            "manual_coach": True,
            "screens": ["14"],
        }
        self.ch._pass_hip_pending = {}
        self.ch._goal_ball_trail = []
        self.ch._hidden_goal_lines = {}
        self.assertTrue(rt.is_pass_main_goal("14"))
        cx, cy = rt.goal_circle_center(line["p0"], line["p1"])
        self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx - 90.0, cy)])
        with patch.object(rt, "ball_overlaps_hip", return_value=True):
            self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx - 40.0, cy)])
            self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx, cy)])
            self.assertIn("14", getattr(self.ch, "_pass_hip_pending", None) or {})
            self.assertEqual(os.path.getsize(self.tmp.name), 0)
        with patch.object(rt, "ball_overlaps_hip", return_value=False):
            self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx + 80.0, cy)])
        self.assertTrue(self.ch.session_active)
        self.assertEqual(os.path.getsize(self.tmp.name), 0)
        self.assertIn("14", self.ch.active_goal_lines)
        self.assertFalse(self.ch._pass_hip_pending)

    def test_finish_balls_live_display_needs_hip_even_without_screens(self):
        """Background analyze must not publish Correct before pass_hip_result."""
        snap = {
            "finish_balls": True,
            "data": [{"b": [[1, 1, 9]]}, {"b": [[2, 2, 9]]}],
            # Missing screens used to skip the mouth check and publish Correct.
        }
        preview = {"Result": "Correct", "Winning Screen": "N/A"}
        with patch.object(rt, "analyze_action_with_context", return_value=preview):
            self.cam._run_live_display("A", snap, "PASS", ["A3"], "S4", [], None, 4)
        self.assertEqual(os.path.getsize(self.tmp.name), 0)
        snap["pass_hip_result"] = "Correct"
        with patch.object(rt, "analyze_action_with_context", return_value=preview):
            self.cam._run_live_display("A", snap, "PASS", ["A3"], "S4", [], None, 4)
        with open(self.tmp.name, encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["fields"]["A"]["result"], "Correct")

    def test_a3_reverse_while_still_in_goal_and_hip_corrects(self):
        """A3 Manual: clear reverse while still in the mouth ∩ HIP → Correct."""
        line = rt.GOAL_LINES["14"]
        self.ch.field_id = "A"
        self.ch.label = "A"
        self.ch.session_active = True
        self.ch.active_goal_lines = {"A3": {"p0": line["p0"], "p1": line["p1"]}}
        self.ch.current_screens = ["A3"]
        self.ch.current_action = "PASS"
        self.ch._cylinder_scored_screens = set()
        self.ch.current_qr_block = {
            "finish_balls": True,
            "data": [],
            "manual_coach": True,
            "screens": ["A3"],
        }
        self.ch._pass_hip_pending = {}
        self.ch._goal_ball_trail = []
        self.ch._hidden_goal_lines = {}
        cx, cy = rt.goal_circle_center(line["p0"], line["p1"])
        self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx - 90.0, cy)])
        with patch.object(rt, "ball_overlaps_hip", return_value=True):
            self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx - 40.0, cy)])
            self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx, cy)])
            # Reverse back toward the field while still on goal paint.
            self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx - 30.0, cy)])
        with open(self.tmp.name, encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["fields"]["A"]["result"], "Correct")
        self.assertEqual(payload["fields"]["A"]["winning_screen"], "A3")

    def test_a6_ball_turns_in_hip_still_finishes(self):
        """A6: inbound then reverse while in HIP Corrects immediately."""
        line = rt.GOAL_LINES["4"]
        self.ch.field_id = "A"
        self.ch.session_active = True
        self.ch.active_goal_lines = {"A6": {"p0": line["p0"], "p1": line["p1"]}}
        self.ch.current_screens = ["A6"]
        self.ch.current_action = "PASS"
        self.ch._cylinder_scored_screens = set()
        self.ch.current_qr_block = {"finish_balls": True, "data": []}
        self.ch._pass_hip_pending = {}
        self.ch._goal_ball_trail = []
        cx, cy = rt.goal_circle_center(line["p0"], line["p1"])
        self._finish_pass_with_turn("A6", cx, cy, hip=True)
        with open(self.tmp.name, encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["fields"]["A"]["result"], "Correct")
        self.assertEqual(payload["fields"]["A"]["winning_screen"], "A6")

    def test_only_goal_area_balls_are_used_for_finish(self):
        """Multi-ball: detections outside the lit goal are ignored for Correct."""
        line = rt.GOAL_LINES["12"]
        self.ch.field_id = "A"
        self.ch.session_active = True
        self.ch.active_goal_lines = {"A1": {"p0": line["p0"], "p1": line["p1"]}}
        self.ch.current_screens = ["A1"]
        self.ch.current_action = "PASS"
        self.ch._cylinder_scored_screens = set()
        self.ch.current_qr_block = {"finish_balls": True, "data": []}
        self.ch._pass_hip_pending = {}
        self.ch._goal_ball_trail = []
        cx, cy = rt.goal_circle_center(line["p0"], line["p1"])
        noise_a = self._ball(80.0, 300.0)
        noise_b = self._ball(200.0, 40.0)
        # Outside-only multi-ball must not start a finish watch.
        self.cam._publish_goal_if_in_cylinder(self.ch, [noise_a, noise_b])
        self.assertEqual(os.path.getsize(self.tmp.name), 0)
        self.assertNotIn("A1", getattr(self.ch, "_pass_hip_pending", None) or {})
        # Enter goal while noise balls remain outside → watch starts on goal ball.
        self.cam._publish_goal_if_in_cylinder(
            self.ch, [noise_a, noise_b, self._ball(cx, cy + 40)]
        )
        self.cam._publish_goal_if_in_cylinder(
            self.ch, [noise_a, noise_b, self._ball(cx, cy)]
        )
        self.assertIn("A1", self.ch._pass_hip_pending)
        # Reverse in goal with outside noise still present → Correct.
        self.cam._publish_goal_if_in_cylinder(
            self.ch, [noise_a, noise_b, self._ball(cx, cy + 12)]
        )
        with open(self.tmp.name, encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["fields"]["A"]["result"], "Correct")

    def test_pass_mouth_outside_hip_is_wrong(self):
        """Goal touch that leaves without a HIP turn retries; later turn+HIP Corrects."""
        line = rt.GOAL_LINES["12"]
        self.ch.field_id = "A"
        self.ch.session_active = True
        self.ch.active_goal_lines = {"A1": {"p0": line["p0"], "p1": line["p1"]}}
        self.ch.current_screens = ["A1"]
        self.ch.current_action = "PASS"
        self.ch._cylinder_scored_screens = set()
        self.ch.current_qr_block = {"finish_balls": True, "data": []}
        self.ch._pass_hip_pending = {}
        self.ch._goal_ball_trail = []
        cx, cy = rt.goal_circle_center(line["p0"], line["p1"])
        self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx, cy + 40)])
        with patch.object(rt, "ball_overlaps_hip", return_value=False):
            self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(cx, cy)])
            self.assertTrue(self.ch.session_active)
            self.assertNotIn("A1", self.ch.active_goal_lines)
            self.cam._publish_goal_if_in_cylinder(self.ch, [self._ball(300.0, 20.0)])
        self.assertTrue(self.ch.session_active)
        self.assertEqual(os.path.getsize(self.tmp.name), 0)
        self.assertEqual(self.ended, [])
        self.assertFalse(self.ch._pass_hip_pending)
        self.assertIn("A1", self.ch.active_goal_lines)
        self._finish_pass_with_turn("A1", cx, cy, hip=True)
        with open(self.tmp.name, encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["fields"]["A"]["result"], "Correct")
        self.assertFalse(self.ch.session_active)

    def test_screen1_and_6_near_ball_does_not_score(self):
        """A1/A6 (and B1/B6): nearby motion must not Correct without cylinder entry."""
        for sid, cabinet in (("A1", "12"), ("A6", "4"), ("B1", "5"), ("B6", "11")):
            with self.subTest(sid=sid):
                line = rt.GOAL_LINES[cabinet]
                fid = "B" if sid.startswith("B") else "A"
                self.ch.field_id = fid
                self.ch.label = fid
                self.ch.session_active = True
                self.ch.active_goal_lines = {sid: {"p0": line["p0"], "p1": line["p1"]}}
                self.ch.current_screens = [sid]
                self.ch.current_action = "PASS"
                self.ch._cylinder_scored_screens = set()
                self.ch.current_qr_block = {"finish_balls": True}
                self.ch._pass_hip_pending = {}
                self.ch._goal_ball_trail = []
                self.ended.clear()
                open(self.tmp.name, "w", encoding="utf-8").close()
                cx, cy = rt.goal_circle_center(line["p0"], line["p1"])
                depth = rt.arrival_depth_for(sid, "PASS")
                radius = rt.goal_circle_radius(depth, line["p0"], line["p1"])
                # Just outside the drawn cylinder — used to score via +95px approach.
                near = (cx + radius + 40.0, cy)
                self.assertFalse(
                    rt.in_goal_area(near, line["p0"], line["p1"], depth),
                    msg=f"{sid} near should be outside drawn cylinder",
                )
                self.assertTrue(rt.requires_strict_cylinder_hit(sid))
                self.assertEqual(
                    rt.approach_finish_depth(sid, "PASS"),
                    depth,
                    msg=f"{sid} must not expand approach depth",
                )
                self.cam._publish_goal_if_in_cylinder(self.ch, [{"center": near}])
                self.assertEqual(os.path.getsize(self.tmp.name), 0, sid)
                self.assertTrue(self.ch.session_active, sid)
                # Reset watch state and re-light the mouth for the real pass.
                self.ch._goal_ball_trail = []
                self.ch._pass_hip_pending = {}
                self.ch._hidden_goal_lines = {}
                self.ch.active_goal_lines = {sid: {"p0": line["p0"], "p1": line["p1"]}}
                self._finish_pass_with_turn(sid, cx, cy, hip=True)
                with open(self.tmp.name, encoding="utf-8") as handle:
                    payload = json.load(handle)
                self.assertEqual(payload["fields"][fid]["result"], "Correct", sid)


class EliteGoalAdvancePollTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self.tmp.close()
        self.path_patch = patch.object(player, "LIVE_ACTION_RESULT_FILE", self.tmp.name)
        self.path_patch.start()
        inst = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        inst.operator_paused = False
        inst.display_phase = "action"
        inst._label_phase = "action"
        inst._goal_arrived = False
        inst.current_video_index = 0
        inst._flash_seq = 4
        inst._field_cue_seq = {}
        inst._field_action_wall = {}
        inst._action_cue_wall = 1.0
        inst.image_canvas = None
        inst._active_fields = lambda: ["A", "B"]
        inst._stop_goal_advance_poll = lambda: None
        inst.finished = []
        inst._finish_label_action = lambda: inst.finished.append(True)
        inst._clear_field_action_now = lambda fid, soft_cue=False: None
        inst.video_files = [{
            "advance_on_goal": True,
            "field_screens": {"A": ["A2"]},
        }]
        self.inst = inst

    def tearDown(self):
        self.path_patch.stop()
        try:
            os.remove(self.tmp.name)
        except OSError:
            pass

    def _write(self, payload):
        with open(self.tmp.name, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_correct_on_current_field_switches_screen(self):
        self._write({
            "fields": {
                "A": {
                    "seq": 4,
                    "ts": 10.0,
                    "result": "Correct",
                    "by_seq": {"4": {"seq": 4, "ts": 10.0, "result": "Correct"}},
                }
            }
        })
        self.inst._poll_goal_advance()
        self.assertTrue(self.inst._goal_arrived)
        self.assertEqual(self.inst.finished, [True])

    def test_other_field_correct_does_not_switch(self):
        self._write({
            "fields": {
                "B": {
                    "seq": 4,
                    "ts": 10.0,
                    "result": "Correct",
                    "by_seq": {"4": {"seq": 4, "ts": 10.0, "result": "Correct"}},
                }
            }
        })
        self.inst._poll_goal_advance()
        self.assertFalse(self.inst._goal_arrived)
        self.assertEqual(self.inst.finished, [])

    def test_miss_does_not_switch(self):
        self._write({
            "fields": {
                "A": {
                    "seq": 4,
                    "ts": 10.0,
                    "result": "Miss",
                    "by_seq": {"4": {"seq": 4, "ts": 10.0, "result": "Miss"}},
                }
            }
        })
        self.inst._poll_goal_advance()
        self.assertFalse(self.inst._goal_arrived)

    def test_clear_now_flag_switches_screen(self):
        """A Correct with clear_now switches the screen without a black flash."""
        self._write({
            "fields": {
                "A": {
                    "seq": 4,
                    "ts": 10.0,
                    "result": "Correct",
                    "clear_now": True,
                    "by_seq": {
                        "4": {
                            "seq": 4,
                            "ts": 10.0,
                            "result": "Correct",
                            "clear_now": True,
                        }
                    },
                }
            }
        })
        cleared = []
        self.inst._clear_field_action_now = (
            lambda fid, soft_cue=False: cleared.append(fid)
        )
        self.inst._poll_goal_advance()
        self.assertTrue(self.inst._goal_arrived)
        self.assertEqual(cleared, [])
        self.assertEqual(self.inst.finished, [True])


if __name__ == "__main__":
    unittest.main()
