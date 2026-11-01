"""HIP person-zone calibration stores 17-point Field A/B polygons."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import simust_hip_calibrate as hc  # noqa: E402


class HipCalibrateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="simust-hip-cal-")
        self.prev = hc.CALIBRATION_FILE
        hc.CALIBRATION_FILE = os.path.join(self.tmp, "hip_zone_calibration.json")
        hc._cache = None
        hc._cache_mtime = 0.0

    def tearDown(self):
        hc.CALIBRATION_FILE = self.prev
        hc._cache = None
        hc._cache_mtime = 0.0
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_close_polygon_forces_17(self):
        pts = [[10, 10], [20, 10], [20, 20], [10, 20]]
        closed = hc._close_polygon(pts)
        self.assertEqual(len(closed), 17)
        self.assertEqual(closed[0], closed[-1])

    def test_save_applies_to_polygon_lists(self):
        poly_a = [(0, 0)] * 17
        poly_b = [(1, 1)] * 17
        # Valid span (not degenerate) — fine-adjust from software zone.
        new_a = [
            [12.0, 297.0], [10.0, 254.0], [37.0, 192.0], [58.0, 171.0],
            [109.0, 142.0], [139.0, 132.0], [204.0, 103.0], [444.0, 105.0],
            [503.0, 133.0], [532.0, 147.0], [582.0, 180.0], [609.0, 202.0],
            [634.0, 261.0], [623.0, 303.0], [469.0, 342.0], [79.0, 321.0],
        ]
        hc.save_fields({"A": {"points": new_a}}, poly_a, poly_b)
        self.assertEqual(len(poly_a), 17)
        self.assertEqual(poly_a[0], (12.0, 297.0))
        self.assertEqual(poly_a[-1], poly_a[0])
        status = hc.public_status(poly_a, poly_b)
        self.assertTrue(status["fields"]["A"]["calibrated"])
        self.assertEqual(status["fields"]["A"]["point_count"], 17)

    def test_rejects_degenerate_override(self):
        poly_a = [(12, 297), (10, 254), (37, 192), (58, 171), (109, 142), (139, 132),
                  (204, 103), (444, 105), (503, 133), (532, 147), (582, 180), (609, 202),
                  (634, 261), (623, 303), (469, 342), (79, 321), (12, 297)]
        before = list(poly_a)
        junk = [[float(i), 100.0] for i in range(16)]
        hc.save_store({"version": 1, "fields": {"A": {"points": junk}}})
        hc.apply_overrides_to_polygons(poly_a, [(1, 1)] * 17)
        self.assertEqual(poly_a, before)

    def test_reset_clears_overrides(self):
        poly_a = [(5, 5)] * 17
        poly_b = [(6, 6)] * 17
        hc.save_fields(
            {"A": {"points": [[9, 9]] * 16}},
            poly_a,
            poly_b,
        )
        hc.reset_store()
        # Without re-applying, lists keep last save; apply after reset should no-op.
        restored_a = [(5, 5)] * 17
        restored_b = [(6, 6)] * 17
        hc.apply_overrides_to_polygons(restored_a, restored_b)
        self.assertEqual(restored_a[0], (5, 5))


if __name__ == "__main__":
    unittest.main()
