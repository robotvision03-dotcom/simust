"""GOAL zone probe: visual catalog only. Scoring is unchanged."""

import os
import sys
import types
import unittest

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


class GoalProbeCatalogTests(unittest.TestCase):
    def test_zone_catalog_has_line_corners_and_outside(self):
        names = set(rt.GOAL_PROBE_ZONES)
        self.assertTrue({"line_center", "post_a", "post_b", "upper_corner_a", "upper_corner_b"} <= names)
        self.assertTrue({"outside_20", "outside_73", "outside_140", "wide_a", "wide_b"} <= names)

    def test_line_band_contains_center_not_upper_or_far(self):
        p0, p1 = rt.GOAL_LINES["8"]["p0"], rt.GOAL_LINES["8"]["p1"]
        depth = rt.arrival_depth_for("8", "GOAL")
        mid = rt.goal_probe_xy(p0, p1, "line_center")
        upper = rt.goal_probe_xy(p0, p1, "upper_center_90")
        far = rt.goal_probe_xy(p0, p1, "outside_140")
        self.assertTrue(rt.in_goal_area(mid, p0, p1, depth))
        self.assertFalse(rt.in_goal_area(upper, p0, p1, depth))
        self.assertFalse(rt.in_goal_area(far, p0, p1, depth))

    def test_probe_cycles_named_zones_and_does_not_change_scoring_api(self):
        prev = rt.ArenaSimulator.GOAL_PROBE
        rt.ArenaSimulator.GOAL_PROBE = True
        try:
            sim = rt.ArenaSimulator()
            seen = []
            for _ in range(len(rt.GOAL_PROBE_ZONES)):
                sim.start_action("GOAL", ["8"])
                seen.append(sim.probe_name)
                self.assertEqual(sim.start_xy, (961.0, 82.0))
                self.assertEqual(sim.intended, "correct")
                self.assertGreaterEqual(sim.travel_s, 1.5)
            self.assertEqual(seen, list(rt.GOAL_PROBE_ZONES))
        finally:
            rt.ArenaSimulator.GOAL_PROBE = prev


if __name__ == "__main__":
    unittest.main()
