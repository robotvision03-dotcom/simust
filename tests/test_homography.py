"""Ground-plane homography for hip displacement."""

import math
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import cv2  # noqa: F401
    import numpy as np  # noqa: F401
    HAS_CV2 = True
except Exception:
    HAS_CV2 = False

import simust_homography as homo  # noqa: E402
from simust_security import is_lab_only_path  # noqa: E402


class HomographyRouteGuardTests(unittest.TestCase):
    def test_lab_only(self):
        self.assertTrue(is_lab_only_path("/homography/save"))
        self.assertTrue(is_lab_only_path("/homography/frame/camera-1"))
        self.assertFalse(is_lab_only_path("/homography/status"))



@unittest.skipUnless(HAS_CV2, "OpenCV required")
class HomographyComputeTests(unittest.TestCase):
    def setUp(self):
        self.image = [(0, 0), (100, 0), (100, 100), (0, 100)]
        self.world = [(0, 0), (2, 0), (2, 5), (0, 5)]

    def test_requires_four_points(self):
        with self.assertRaises(ValueError):
            homo.compute_homography(self.image[:3], self.world[:3])

    def test_maps_corners_to_metres(self):
        result = homo.compute_homography(self.image, self.world)
        self.assertTrue(result["valid"])
        self.assertLess(result["rmse_m"], 0.05)
        mid = homo.pixel_to_world(50, 0, result["H"])
        self.assertIsNotNone(mid)
        self.assertAlmostEqual(mid[0], 1.0, places=2)
        self.assertAlmostEqual(mid[1], 0.0, places=2)

    def test_pairs_meeting_sides_build_rectangle(self):
        pairs = [
            {"a": [0, 0], "b": [100, 0], "distance": 2.0},
            {"a": [0, 0], "b": [0, 100], "distance": 5.0},
        ]
        result = homo.compute_homography_from_pairs(pairs)
        self.assertTrue(result["valid"])
        mid = homo.pixel_to_world(50, 0, result["H"])
        self.assertAlmostEqual(mid[0], 1.0, places=1)
        self.assertAlmostEqual(mid[1], 0.0, places=1)

    def test_pairs_matching_user_segments(self):
        pairs = [
            {"a": [41.3, 187.5], "b": [527.3, 137.5], "distance": 11.87},
            {"a": [131.3, 133.5], "b": [206.3, 95.5], "distance": 7.2},
            {"a": [118.3, 136.5], "b": [610.3, 183.5], "distance": 11.87},
            {"a": [130.3, 131.5], "b": [517.3, 134.5], "distance": 10.9},
        ]
        result = homo.compute_homography_from_pairs(pairs)
        self.assertTrue(result["valid"])
        self.assertLess(result["rmse_m"], 3.0)
        a = homo.pixel_to_world(41.3, 187.5, result["H"])
        b = homo.pixel_to_world(527.3, 137.5, result["H"])
        self.assertAlmostEqual(math.hypot(b[0] - a[0], b[1] - a[1]), 11.87, places=1)
        with self.assertRaises(ValueError):
            homo.compute_homography_from_pairs([
                {"a": [0, 0], "b": [100, 0], "distance": 2.0},
            ])

    def test_path_uses_homography_not_pixel_scale(self):
        computed = homo.compute_homography(self.image, self.world)
        store = {
            "cameras": {
                "camera-1": {
                    "calibrated": True,
                    "H": computed["H"],
                    "image_width": 640,
                    "image_height": 100,
                }
            }
        }
        # Hip stays on camera-1 (u < 640). 100 px along X is 2 metres.
        positions = [(0, 0, 0), (1, 100, 0)]
        dist = homo.path_distance_meters(positions, store=store, fallback_m_per_px=0.0259)
        self.assertAlmostEqual(dist, 2.0, places=2)


@unittest.skipUnless(HAS_CV2, "OpenCV required")
class HomographyStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="simust-h-")
        self.prev_file = homo.CALIBRATION_FILE
        self.prev_dir = homo.FRAME_DIR
        homo.CALIBRATION_FILE = os.path.join(self.tmp.name, "homography_calibration.json")
        homo.FRAME_DIR = os.path.join(self.tmp.name, "frames")
        homo._cache = None
        homo._cache_mtime = 0.0

    def tearDown(self):
        homo.CALIBRATION_FILE = self.prev_file
        homo.FRAME_DIR = self.prev_dir
        homo._cache = None
        homo._cache_mtime = 0.0
        self.tmp.cleanup()

    def test_save_and_status(self):
        saved = homo.save_camera_calibration(
            "camera-1",
            [(0, 0), (100, 0), (100, 100), (0, 100)],
            [(0, 0), (2, 0), (2, 5), (0, 5)],
            100,
            100,
        )
        self.assertTrue(saved["calibrated"])
        self.assertEqual(saved["status"], "Calibrated")
        status = homo.public_camera_status("camera-1")
        self.assertEqual(status["point_count"], 4)
        saved_pairs = homo.save_camera_calibration(
            "camera-8",
            image_width=100,
            image_height=100,
            pairs=[
                {"a": [0, 0], "b": [100, 0], "distance": 2.0},
                {"a": [0, 0], "b": [0, 100], "distance": 5.0},
            ],
        )
        self.assertTrue(saved_pairs["calibrated"])
        self.assertEqual(saved_pairs["pair_count"], 2)
        reset = homo.reset_camera_calibration("camera-1")
        self.assertFalse(reset["calibrated"])
        self.assertEqual(reset["status"], "Not Calibrated")


if __name__ == "__main__":
    unittest.main()
