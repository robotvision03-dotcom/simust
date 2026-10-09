"""World-space finish cylinder from ground-plane homography."""

from __future__ import annotations

import os
import sys
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

import simust_homography as homo  # noqa: E402
import simust_realtime as rt  # noqa: E402


def _identity_store():
    """Pixels map roughly to metres with 0.01 m/px (100 px → 1 m)."""
    # H such that X = 0.01*u, Y = 0.01*v (approx via affine in projective form).
    h = [
        [0.01, 0.0, 0.0],
        [0.0, 0.01, 0.0],
        [0.0, 0.0, 1.0],
    ]
    return {
        "cameras": {
            homo.LEFT_CAMERA: {
                "calibrated": True,
                "H": h,
                "image_width": 640,
            },
            homo.RIGHT_CAMERA: {
                "calibrated": True,
                "H": h,
                "image_width": 640,
            },
        }
    }


class HomographyHelpersTests(unittest.TestCase):
    def test_ball_pixel_to_world_and_scale(self):
        store = _identity_store()
        with patch.object(homo, "load_store", return_value=store):
            world = homo.ball_pixel_to_world(100.0, 200.0, store)
            self.assertIsNotNone(world)
            self.assertAlmostEqual(world[0], 1.0, places=3)
            self.assertAlmostEqual(world[1], 2.0, places=3)
            scale = homo.local_m_per_px(100.0, 200.0, store)
            self.assertIsNotNone(scale)
            self.assertAlmostEqual(scale, 0.01, places=4)


class FinishCylinderWorldTests(unittest.TestCase):
    def setUp(self):
        self.store = _identity_store()
        self.p0 = (100.0, 200.0)
        self.p1 = (140.0, 200.0)
        # Midpoint (120, 200); depth → radius via GOAL_CIRCLE_SCALE.
        self.depth = 100.0
        self.patches = [
            patch.object(homo, "load_store", return_value=self.store),
            patch.object(rt, "simust_homography", homo),
            patch.object(rt, "finish_zone_scale", return_value=1.0),
            patch.object(rt, "_finish_circle_boost", return_value=1.0),
            patch.object(rt, "finish_cylinder_height_sim", return_value=50.0),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_inside_xy_and_height(self):
        cyl = rt.finish_cylinder_world(self.p0, self.p1, self.depth, store=self.store)
        self.assertIsNotNone(cyl)
        mid = rt.goal_circle_center(self.p0, self.p1)
        self.assertTrue(
            rt.in_finish_cylinder_world((mid[0], mid[1], 0.1), self.p0, self.p1, self.depth, store=self.store)
        )

    def test_outside_xy(self):
        mid = rt.goal_circle_center(self.p0, self.p1)
        far = (mid[0] + 400.0, mid[1])
        self.assertFalse(
            rt.in_finish_cylinder_world((far[0], far[1], 0.1), self.p0, self.p1, self.depth, store=self.store)
        )

    def test_above_height_rejected(self):
        mid = rt.goal_circle_center(self.p0, self.p1)
        cyl = rt.finish_cylinder_world(self.p0, self.p1, self.depth, store=self.store)
        self.assertIsNotNone(cyl)
        too_high = float(cyl["height_m"]) + 0.25
        self.assertFalse(
            rt.in_finish_cylinder_world(
                (mid[0], mid[1], too_high), self.p0, self.p1, self.depth, store=self.store
            )
        )
        # Drawn 2D zone still contains the midpoint, but height rejects the volume.
        self.assertTrue(rt.in_finish_cylinder_2d(mid, self.p0, self.p1, self.depth))
        self.assertFalse(
            rt.in_finish_cylinder((mid[0], mid[1], too_high), self.p0, self.p1, self.depth)
        )

    def test_uncalibrated_falls_back_to_2d(self):
        empty = {"cameras": {}}
        with patch.object(homo, "load_store", return_value=empty):
            mid = rt.goal_circle_center(self.p0, self.p1)
            world = rt.in_finish_cylinder_world(mid, self.p0, self.p1, self.depth, store=empty)
            self.assertIsNone(world)
            self.assertTrue(rt.in_finish_cylinder_2d(mid, self.p0, self.p1, self.depth))
            self.assertTrue(rt.in_finish_cylinder(mid, self.p0, self.p1, self.depth))

    def test_bbox_dict_accepted(self):
        mid = rt.goal_circle_center(self.p0, self.p1)
        r = 8
        ball = {
            "center": mid,
            "bbox": [mid[0] - r, mid[1] - r, mid[0] + r, mid[1] + r],
        }
        self.assertTrue(rt.in_goal_area(ball, self.p0, self.p1, self.depth))


if __name__ == "__main__":
    unittest.main()
