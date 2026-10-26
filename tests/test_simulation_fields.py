"""Per-field arena simulation flags (real player on one field, simulator on the other)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
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
import app as app_mod  # noqa: E402


class ParseSimulationFieldsTests(unittest.TestCase):
    def test_legacy_true_means_both(self):
        self.assertEqual(rt.parse_simulation_fields("true"), {"A": True, "B": True})

    def test_legacy_false_means_neither(self):
        self.assertEqual(rt.parse_simulation_fields("false"), {"A": False, "B": False})

    def test_json_field_b_only(self):
        self.assertEqual(
            rt.parse_simulation_fields('{"A": false, "B": true}'),
            {"A": False, "B": True},
        )

    def test_csv_a_only(self):
        self.assertEqual(rt.parse_simulation_fields("A"), {"A": True, "B": False})


class WriteSimulationFieldsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="simust-sim-")
        self.patch = patch.object(app_mod, "SIMUST_PLAYER_DIRECTORY", self.tmp)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_write_and_read_one_field(self):
        saved = app_mod.write_simulation_fields({"A": False, "B": True})
        self.assertEqual(saved, {"A": False, "B": True})
        path = os.path.join(self.tmp, "arena_simulation.txt")
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload, {"A": False, "B": True})
        self.assertEqual(app_mod._read_written_simulation_fields(), {"A": False, "B": True})


class SimulatorScoreModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="simust-score-mode-")
        self.patch = patch.object(app_mod, "SIMUST_PLAYER_DIRECTORY", self.tmp)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_default_is_mode2(self):
        self.assertEqual(app_mod.read_simulator_score_mode(), 2)

    def test_write_mode1_and_mode2(self):
        self.assertEqual(app_mod.write_simulator_score_mode(1), 1)
        self.assertEqual(app_mod.read_simulator_score_mode(), 1)
        path = os.path.join(self.tmp, "simulator_score_mode.txt")
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read().strip(), "1")
        self.assertEqual(app_mod.write_simulator_score_mode(2), 2)
        self.assertEqual(app_mod.read_simulator_score_mode(), 2)

    def test_invalid_mode_falls_back_to_2(self):
        self.assertEqual(app_mod.write_simulator_score_mode(99), 2)
        self.assertEqual(app_mod.write_simulator_score_mode("nope"), 2)

    def test_parse_helpers(self):
        self.assertEqual(rt.parse_simulator_score_mode("1"), rt.SIM_SCORE_MODE_FAIL)
        self.assertEqual(rt.parse_simulator_score_mode("2"), rt.SIM_SCORE_MODE_PASS)
        self.assertEqual(rt.parse_simulator_score_mode("x"), rt.SIM_SCORE_MODE_PASS)

    def test_mode2_keeps_true_average_and_force_pass(self):
        """Final AE stays the mean of tests; Mode 2 unlocks via force_pass."""
        app_mod.write_simulation_fields({"A": True, "B": False})
        app_mod.write_simulator_score_mode(2)
        metrics = {"aac": 100.0, "avg_ae": 63.6, "ae_display": "64%"}
        out = app_mod.apply_simulator_score_mode_to_metrics(
            metrics, "A", "L05-WorldClass/S2.T5"
        )
        self.assertEqual(out["aac"], 100.0)
        self.assertAlmostEqual(out["avg_ae"], 63.6)
        self.assertTrue(out.get("force_pass"))
        # Real field B (not simulated) is unchanged
        real = app_mod.apply_simulator_score_mode_to_metrics(
            {"aac": 100.0, "avg_ae": 62.0}, "B", "L05-WorldClass/S2.T5"
        )
        self.assertEqual(real["avg_ae"], 62.0)

    def test_mode2_foundation_keeps_true_average(self):
        app_mod.write_simulation_fields({"A": True, "B": False})
        app_mod.write_simulator_score_mode(2)
        out = app_mod.apply_simulator_score_mode_to_metrics(
            {"aac": 60.0, "avg_ae": 62.0}, "A", "L00-Foundation"
        )
        self.assertEqual(out["aac"], 60.0)
        self.assertEqual(out["avg_ae"], 62.0)
        self.assertTrue(out.get("force_pass"))

    def test_mode1_caps_below_unlock_gate(self):
        app_mod.write_simulation_fields({"A": True, "B": True})
        app_mod.write_simulator_score_mode(1)
        out = app_mod.apply_simulator_score_mode_to_metrics(
            {"aac": 100.0, "avg_ae": 90.0}, "A", "L05-WorldClass/S1.T2"
        )
        # Series unlock is AE-only at 75%; ACC is not capped.
        self.assertEqual(out["aac"], 100.0)
        self.assertLess(out["avg_ae"], 75.0)

    def test_mode2_partner_sim_force_pass_keeps_average(self):
        """WC partner-sim: Mode 2 force-unlocks without faking the AE average."""
        app_mod.write_simulation_fields({"A": False, "B": True})
        app_mod.write_simulator_score_mode(2)
        out = app_mod.apply_simulator_score_mode_to_metrics(
            {"aac": 100.0, "avg_ae": 62.0},
            "A",
            "L05-WorldClass/S2.T5",
            score_field="A",
        )
        self.assertEqual(out["avg_ae"], 62.0)
        self.assertTrue(out.get("force_pass"))
        self.assertTrue(app_mod._simulator_mode2_force_pass("A", score_field="A"))


class MixedDetectionTests(unittest.TestCase):
    def test_real_a_simulated_b_uses_camera_then_sim(self):
        cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
        cam.active_fields = {"A", "B"}
        cam.simulation_fields = {"A": False, "B": True}
        cam.channels = {
            "A": types.SimpleNamespace(session_start_timestamp=0),
            "B": types.SimpleNamespace(session_start_timestamp=0),
        }
        cam.tracker = types.SimpleNamespace(
            detect_objects=lambda frame, active_fields=None: (
                [{"center": [10, 10], "field": "A"}],
                [{"center": [20, 20], "field": "A"}],
            ),
            get_player_tracking_point_for_field=lambda *a, **k: (21, 22),
        )
        cam.simulators = {
            "B": types.SimpleNamespace(
                step=lambda w, h: (
                    [{"center": [900, 40]}],
                    [{"center": [910, 50]}],
                    (910, 50),
                ),
                draw_on_frame=lambda frame, b, p: frame,
            )
        }
        frame = types.SimpleNamespace(shape=(360, 1280, 3))
        out, balls, players, hips = cam._detections_for_frame(frame, 1.0)
        self.assertIs(out, frame)
        self.assertEqual(hips["A"], (21, 22))
        self.assertEqual(hips["B"], (910, 50))
        fields = {item["field"] for item in balls}
        self.assertEqual(fields, {"A", "B"})
        self.assertFalse(cam._field_is_simulated("A"))
        self.assertTrue(cam._field_is_simulated("B"))

    def test_sim_off_field_is_stopped_and_not_stepped(self):
        cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
        cam.active_fields = {"A", "B"}
        cam.simulation_fields = {"A": True, "B": False}
        cam.channels = {
            "A": types.SimpleNamespace(session_start_timestamp=0),
            "B": types.SimpleNamespace(session_start_timestamp=0),
        }
        stepped = []

        class OffSim:
            def __init__(self):
                self.active = True
                self.late_phase = True
                self.hold_finish = True
                self.parked = False
                self.action = "PASS"

            def stop(self):
                rt.ArenaSimulator.stop(self)

            def step(self, w, h):
                stepped.append("B")
                return [], [], (None, None)

            def draw_on_frame(self, frame, balls, players):
                stepped.append("draw")
                return frame

        cam.simulators = {
            "A": types.SimpleNamespace(
                step=lambda w, h: ([{"center": [10, 10]}], [{"center": [12, 12]}], (12, 12)),
                draw_on_frame=lambda frame, balls, players: frame,
                parked=False,
            ),
            "B": OffSim(),
        }
        cam.tracker = types.SimpleNamespace(
            detect_objects=lambda frame, active_fields=None: ([], []),
            get_player_tracking_point_for_field=lambda *a, **k: (None, None),
        )
        frame = types.SimpleNamespace(shape=(360, 1280, 3))
        _out, balls, _players, _hips = cam._detections_for_frame(frame, 1.0)
        self.assertEqual(stepped, [])
        self.assertTrue(cam.simulators["B"].parked)
        self.assertFalse(cam.simulators["B"].active)
        self.assertEqual({item["field"] for item in balls}, {"A"})

    def test_same_screen_cue_rewrite_does_not_restart_the_cylinder(self):
        cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
        cam.active_fields = {"A", "B"}
        cam.simulation_fields = {"A": True, "B": True}
        ch = types.SimpleNamespace(
            session_active=True,
            current_screens=["B1"],
            current_qr_block={"test_num": 1, "action_in_set": 1, "finish_balls": True},
            kp_clear_frames_left=40,
            kp_appear_frames_left=None,
            _frame_sync_cue_raw="IMAGE|1|PASS|B1|t1|a1",
            _pending_cue_info=None,
            _gap_display_sent=False,
            field_id="B",
            label="B",
        )
        cam.channels = {"B": ch}
        cam._read_image_action_cue = lambda: {
            "active": True,
            "finish_balls": True,
            "seq": 9,
            "timestamp": __import__("time").time(),
            "on_sec": 3.0,
            "fields": {
                "B": {
                    "action": "PASS",
                    "screens": ["B1"],
                    "seq": 4,
                    "test_num": 1,
                    "action_in_set": 1,
                    "on_sec": 3.0,
                }
            },
        }
        cam._tick_image_cue_frame_sync("00:00:00.000", 1.0)
        self.assertTrue(ch.session_active)
        self.assertEqual(ch.kp_clear_frames_left, 39)
        self.assertIsNone(ch.kp_appear_frames_left)
        self.assertEqual(ch._frame_sync_cue_raw, "IMAGE|4|PASS|B1|t1|a1")

    def test_real_field_cylinder_stays_on_the_current_screen(self):
        cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
        cam.active_fields = {"A", "B"}
        cam.simulation_fields = {"A": True, "B": False}
        ch = types.SimpleNamespace(
            session_active=True,
            current_screens=["B1"],
            current_qr_block={"test_num": 1, "action_in_set": 1, "finish_balls": True},
            kp_clear_frames_left=40,
            kp_appear_frames_left=None,
            _frame_sync_cue_raw="IMAGE|4|PASS|B1|t1|a1",
            _pending_cue_info=None,
            _gap_display_sent=False,
            field_id="B",
            label="B",
        )
        cam.channels = {"B": ch}
        cam._read_image_action_cue = lambda: {
            "active": True,
            "finish_balls": True,
            "seq": 4,
            "timestamp": __import__("time").time(),
            "on_sec": 3.0,
            "fields": {
                "B": {
                    "action": "PASS",
                    "screens": ["B1"],
                    "seq": 4,
                    "test_num": 1,
                    "action_in_set": 1,
                    "on_sec": 3.0,
                }
            },
        }
        cam._tick_image_cue_frame_sync("00:00:00.000", 1.0)
        self.assertTrue(ch.session_active)
        self.assertEqual(ch.kp_clear_frames_left, 40)


class PartnerPerfectAccuracyTests(unittest.TestCase):
    def test_simulated_field_always_finishes(self):
        cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
        cam.active_fields = {"A", "B"}
        cam.simulation_fields = {"A": False, "B": True}
        cam.simulator_score_mode = rt.SIM_SCORE_MODE_PASS
        sim_a = rt.ArenaSimulator(field_id="A")
        sim_b = rt.ArenaSimulator(field_id="B")
        cam.simulators = {"A": sim_a, "B": sim_b}
        cam._sync_simulator_partner_mode()
        self.assertFalse(sim_a.always_correct)
        self.assertFalse(sim_a.always_fail)
        self.assertTrue(sim_b.always_correct)
        self.assertFalse(sim_b.always_fail)
        self.assertEqual(sim_b._finish_plan(4, 12, 12), "finish")
        self.assertEqual(sim_b._next_outcome("PASS"), "correct")

    def test_both_fields_simulated_are_always_correct(self):
        cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
        cam.active_fields = {"A", "B"}
        cam.simulation_fields = {"A": True, "B": True}
        cam.simulator_score_mode = rt.SIM_SCORE_MODE_PASS
        sim_a = rt.ArenaSimulator(field_id="A")
        sim_b = rt.ArenaSimulator(field_id="B")
        cam.simulators = {"A": sim_a, "B": sim_b}
        cam._sync_simulator_partner_mode()
        self.assertTrue(sim_a.always_correct)
        self.assertTrue(sim_b.always_correct)
        self.assertFalse(sim_a.always_fail)
        self.assertFalse(sim_b.always_fail)
        self.assertEqual(sim_a._finish_plan(4, 3, 10), "finish")
        self.assertEqual(sim_b._finish_plan(2, 9, 10), "finish")
        self.assertEqual(sim_a._next_outcome("GOAL"), "correct")

    def test_mode1_simulated_fields_always_miss(self):
        cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
        cam.active_fields = {"A", "B"}
        cam.simulation_fields = {"A": True, "B": True}
        cam.simulator_score_mode = rt.SIM_SCORE_MODE_FAIL
        sim_a = rt.ArenaSimulator(field_id="A")
        sim_b = rt.ArenaSimulator(field_id="B")
        cam.simulators = {"A": sim_a, "B": sim_b}
        cam._sync_simulator_partner_mode()
        self.assertTrue(sim_a.always_fail)
        self.assertTrue(sim_b.always_fail)
        self.assertFalse(sim_a.always_correct)
        self.assertFalse(sim_b.always_correct)
        self.assertEqual(sim_a._finish_plan(1, 1, 10), "miss")
        self.assertEqual(sim_b._next_outcome("PASS"), "miss")
        self.assertEqual(sim_a._next_outcome("GOAL"), "miss")

    def test_mode1_only_simulated_field_fails(self):
        cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
        cam.active_fields = {"A", "B"}
        cam.simulation_fields = {"A": False, "B": True}
        cam.simulator_score_mode = rt.SIM_SCORE_MODE_FAIL
        sim_a = rt.ArenaSimulator(field_id="A")
        sim_b = rt.ArenaSimulator(field_id="B")
        cam.simulators = {"A": sim_a, "B": sim_b}
        cam._sync_simulator_partner_mode()
        self.assertFalse(sim_a.always_fail)
        self.assertFalse(sim_a.always_correct)
        self.assertTrue(sim_b.always_fail)
        self.assertFalse(sim_b.always_correct)

    def test_both_fields_far_screens_score_correct(self):
        """B1 and B6 used to miss: the only in-goal sample was filtered as static."""
        for fid, name in (("A", "A4"), ("B", "B1"), ("B", "B6")):
            sim = rt.ArenaSimulator(field_id=fid)
            sim.always_correct = True
            sim.start_action(
                "PASS", [name], finish_balls=True,
                action_in_set=9, actions_in_set=10, test_num=4,
            )
            data = []
            for n in range(75):
                t = n / 25.0
                bx, by, px, py = sim._ball_player_for_outcome(t, 0.0)
                bx, by = sim._clip(bx, by)
                data.append({
                    "t": round(t, 3),
                    "b": [[int(bx), int(by)]],
                    "p": [[int(px), int(py)]],
                    "hp": [int(px), int(py)],
                })
            block = {
                "id": "S9",
                "action": "PASS",
                "screens": [name],
                "data": data,
                "finish_balls": True,
                "on_sec": 3.0,
                "field": fid,
            }
            result = rt.analyze_action_with_context(block, rt.GOAL_LINES, "PASS", [block], 0)
            self.assertEqual(result["Result"], "Correct", name)


if __name__ == "__main__":
    unittest.main()
