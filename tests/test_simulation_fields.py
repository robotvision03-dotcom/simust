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
    def test_mixed_real_and_sim_always_finishes(self):
        cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
        cam.active_fields = {"A", "B"}
        cam.simulation_fields = {"A": False, "B": True}
        sim_a = rt.ArenaSimulator(field_id="A")
        sim_b = rt.ArenaSimulator(field_id="B")
        cam.simulators = {"A": sim_a, "B": sim_b}
        cam._sync_simulator_partner_mode()
        self.assertTrue(sim_a.always_correct)
        self.assertTrue(sim_b.always_correct)
        self.assertEqual(sim_b._finish_plan(4, 12, 12), "finish")
        self.assertEqual(sim_b._next_outcome("PASS"), "correct")

    def test_both_fields_simulated_keep_graded_plan(self):
        cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
        cam.active_fields = {"A", "B"}
        cam.simulation_fields = {"A": True, "B": True}
        sim_a = rt.ArenaSimulator(field_id="A")
        sim_b = rt.ArenaSimulator(field_id="B")
        cam.simulators = {"A": sim_a, "B": sim_b}
        cam._sync_simulator_partner_mode()
        self.assertFalse(sim_a.always_correct)
        self.assertFalse(sim_b.always_correct)
        self.assertEqual(sim_b._finish_plan(4, 3, 10), "wrong")


if __name__ == "__main__":
    unittest.main()
