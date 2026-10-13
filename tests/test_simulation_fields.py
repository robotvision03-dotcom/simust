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


class PartnerPerfectAccuracyTests(unittest.TestCase):
    def test_simulated_field_always_finishes(self):
        cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
        cam.active_fields = {"A", "B"}
        cam.simulation_fields = {"A": False, "B": True}
        sim_a = rt.ArenaSimulator(field_id="A")
        sim_b = rt.ArenaSimulator(field_id="B")
        cam.simulators = {"A": sim_a, "B": sim_b}
        cam._sync_simulator_partner_mode()
        self.assertFalse(sim_a.always_correct)
        self.assertTrue(sim_b.always_correct)
        self.assertEqual(sim_b._finish_plan(4, 12, 12), "finish")
        self.assertEqual(sim_b._next_outcome("PASS"), "correct")

    def test_both_fields_simulated_are_always_correct(self):
        cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
        cam.active_fields = {"A", "B"}
        cam.simulation_fields = {"A": True, "B": True}
        sim_a = rt.ArenaSimulator(field_id="A")
        sim_b = rt.ArenaSimulator(field_id="B")
        cam.simulators = {"A": sim_a, "B": sim_b}
        cam._sync_simulator_partner_mode()
        self.assertTrue(sim_a.always_correct)
        self.assertTrue(sim_b.always_correct)
        self.assertEqual(sim_a._finish_plan(4, 3, 10), "finish")
        self.assertEqual(sim_b._finish_plan(2, 9, 10), "finish")
        self.assertEqual(sim_a._next_outcome("GOAL"), "correct")

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
