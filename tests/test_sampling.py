"""Sampling zones: red A/B loops and Start/Stop control."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import simust_sampling as samp


class SamplingZoneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cal = os.path.join(self.tmp.name, "sampling_calibration.json")
        self.ctrl = os.path.join(self.tmp.name, "sampling_control.json")
        self.rec = os.path.join(self.tmp.name, "recordings")
        os.makedirs(self.rec, exist_ok=True)
        self._env = patch.dict(
            os.environ,
            {
                "SIMUST_SAMPLING_FILE": self.cal,
                "SIMUST_SAMPLING_CONTROL": self.ctrl,
                "SIMUST_REALTIME_DIR": self.rec,
            },
            clear=False,
        )
        self._env.start()
        samp._cache = None
        samp._cache_mtime = 0.0
        samp._zones = {}
        samp._zones_key = None
        samp.reset_store()

    def tearDown(self):
        self._env.stop()
        self.tmp.cleanup()

    def test_save_zone_and_hit(self):
        strokes = [
            {
                "erase": False,
                "brush": 12,
                "pts": [[40, 40], [120, 40], [120, 120], [40, 120], [40, 40]],
            }
        ]
        samp.save_fields({"A": {"strokes": strokes}})
        self.assertTrue(samp.zone_contains("A", 80, 80, 0))
        self.assertEqual(samp.point_in_any_zone(80, 80, 0), "A")
        self.assertIsNone(samp.point_in_any_zone(900, 80, 0))

    def test_start_stop_and_raw_save(self):
        strokes = [
            {
                "erase": False,
                "brush": 12,
                "pts": [[40, 40], [120, 40], [120, 120], [40, 120]],
            }
        ]
        samp.save_fields({"A": {"strokes": strokes}})
        frame = np.zeros((360, 1280, 3), dtype=np.uint8)
        # Fake a captured stitch so Start Sample can write a test image.
        import base64
        import cv2

        ok, buf = cv2.imencode(".jpg", frame)
        self.assertTrue(ok)
        data_url = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")
        samp._preview = {"data_url": data_url, "width": 1280, "height": 360}
        ctrl = samp.start_sample()
        self.assertTrue(samp.is_active())
        self.assertTrue(ctrl.get("force_save_once"))
        test_path = ctrl.get("test_path") or ctrl.get("last_path")
        self.assertTrue(test_path and os.path.isfile(test_path))
        self.assertIn("data_samples", test_path)
        self.assertRegex(os.path.basename(test_path), r"^\d{8}_\d{6}_\d{4}\.jpg$")
        self.assertTrue(samp.consume_force_save_once())
        self.assertFalse(samp.consume_force_save_once())
        path = samp.save_raw_frame(frame)
        self.assertTrue(path and os.path.isfile(path))
        saved = cv2.imread(path)
        self.assertIsNotNone(saved)
        self.assertEqual(tuple(saved.shape[:2]), (samp.SAVE_HEIGHT, samp.SAVE_WIDTH))
        samp.stop_sample()
        self.assertFalse(samp.is_active())

    def test_save_raw_frame_is_always_3840x1080(self):
        small = np.zeros((360, 1280, 3), dtype=np.uint8)
        path = samp.save_raw_frame(small)
        self.assertTrue(path and os.path.isfile(path))
        import cv2

        saved = cv2.imread(path)
        self.assertEqual(saved.shape[1], 3840)
        self.assertEqual(saved.shape[0], 1080)


if __name__ == "__main__":
    unittest.main()
