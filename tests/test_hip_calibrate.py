"""HIP person-zone calibration stores a closed Field A/B loop."""

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
        hc._zone_key = None
        hc._zone_cache = {}

    def tearDown(self):
        hc.CALIBRATION_FILE = self.prev
        hc._cache = None
        hc._cache_mtime = 0.0
        hc._zone_key = None
        hc._zone_cache = {}
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_close_polygon_connects_the_loop(self):
        pts = [[10, 10], [200, 10], [200, 200], [10, 200]]
        closed = hc._close_polygon(pts)
        self.assertEqual(len(closed), 5)
        self.assertEqual(closed[0], closed[-1])
        self.assertEqual(closed[0], [10.0, 10.0])

    def test_pencil_loop_is_closed_on_save(self):
        strokes = [{
            "erase": False,
            "brush": 12,
            "pts": [[80, 80], [520, 80], [520, 280], [80, 280]],
        }]
        poly_a = [(0, 0)] * 4
        poly_b = [(1, 1)] * 4
        hc.save_fields({"A": {"strokes": strokes}}, poly_a, poly_b)
        self.assertGreaterEqual(len(poly_a), 4)
        self.assertEqual(poly_a[0], poly_a[-1])
        xs = [p[0] for p in poly_a[:-1]]
        ys = [p[1] for p in poly_a[:-1]]
        self.assertLess(min(xs), 200)
        self.assertGreater(max(xs), 400)
        self.assertLess(min(ys), 160)
        self.assertGreater(max(ys), 200)
        status = hc.public_status(poly_a, poly_b)
        self.assertTrue(status["fields"]["A"]["calibrated"])
        self.assertEqual(status["fields"]["A"]["source"], "paint")
        self.assertTrue(status["fields"]["A"]["strokes"])
        kept = hc._clean_strokes([{"erase": False, "brush": 1, "pts": [[0, 0], [1, 1]]}])
        self.assertEqual(kept[0]["brush"], 1.0)

    def test_finish_uses_painted_loop_not_the_17_point_zone(self):
        """A point inside the old 17-point zone but outside the paint is not inside."""
        strokes = [{
            "erase": False,
            "brush": 8,
            "pts": [[420, 240], [560, 240], [560, 320], [420, 320]],
        }]
        hc.save_fields({"A": {"strokes": strokes}}, [(0, 0)] * 4, [(1, 1)] * 4)
        self.assertTrue(hc.zone_contains("A", 490, 280, 0))
        # (200, 200) sits inside the built-in 17-point HIP outline.
        self.assertFalse(hc.zone_contains("A", 200, 200, 12))
        import simust_realtime as rt

        rt.reload_hip_zone_calibration()
        self.assertFalse(rt.ball_overlaps_hip((200, 200), "A1", 12, field="A"))
        self.assertTrue(rt.ball_overlaps_hip((490, 280), "A1", 12, field="A"))

    def test_outer_border_keeps_a_painted_curve(self):
        """A bend in the pencil stays on the HIP line instead of being cut across."""
        strokes = [{
            "erase": False,
            "brush": 4,
            "pts": [
                [80, 220], [180, 220], [230, 90], [280, 220],
                [520, 220], [520, 300], [80, 300],
            ],
        }]
        poly = hc.polygon_from_strokes(strokes)
        ys = [p[1] for p in poly[:-1]]
        self.assertLess(min(ys), 110)
        self.assertIn([230.0, 90.0], poly[:-1])

    def test_saved_loop_stays_on_the_pencil(self):
        """The zone follows the drawn points and does not grow past the brush."""
        strokes = [{
            "erase": False,
            "brush": 4,
            "pts": [
                [80, 220], [180, 220], [230, 90], [280, 220],
                [520, 220], [520, 300], [80, 300],
            ],
        }]
        hc.save_fields({"A": {"strokes": strokes}}, [(0, 0)] * 4, [(1, 1)] * 4)
        self.assertTrue(hc.zone_contains("A", 230, 90, 0))
        self.assertFalse(hc.zone_contains("A", 230, 80, 0))
        kept = hc.zone_strokes("A")
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["pts"][2], [230.0, 90.0])

    def test_new_loop_removes_the_previous_line(self):
        strokes = [{
            "erase": False,
            "brush": 8,
            "pts": [[80, 80], [520, 80], [520, 280], [80, 280]],
        }]
        hc.save_fields({"A": {"strokes": strokes}}, [(0, 0)] * 4, [(1, 1)] * 4)
        self.assertTrue(hc.zone_strokes("A"))
        hc.save_fields({"A": {"clear": True}}, [(0, 0)] * 4, [(1, 1)] * 4)
        self.assertEqual(hc.zone_strokes("A"), [])
        self.assertTrue(hc.zone_hidden("A"))
        self.assertIsNone(hc.zone_contains("A", 200, 160, 0))
        status = hc.public_status([(0, 0)] * 4, [(1, 1)] * 4)
        self.assertEqual(status["fields"]["A"]["strokes"], [])
        self.assertEqual(status["fields"]["A"]["source"], "cleared")

    def test_eraser_removes_previous_pencil_geometry(self):
        """Erasing a red HIP segment deletes those points instead of leaving a ghost."""
        strokes = [
            {
                "erase": False,
                "brush": 10,
                "pts": [[100, 200], [200, 200], [300, 200], [400, 200], [500, 200]],
            },
            {
                "erase": True,
                "brush": 24,
                "pts": [[280, 200], [300, 200], [320, 200]],
            },
        ]
        baked = hc.bake_eraser_strokes(strokes)
        self.assertTrue(baked)
        for stroke in baked:
            self.assertFalse(stroke.get("erase"))
            for pt in stroke["pts"]:
                self.assertFalse(abs(pt[0] - 300) < 15 and abs(pt[1] - 200) < 15)
        poly_a = [(0, 0)] * 4
        poly_b = [(1, 1)] * 4
        # Closed loop after erase still needs a valid zone for save.
        loop = [
            {
                "erase": False,
                "brush": 10,
                "pts": [
                    [80, 80], [520, 80], [520, 280], [80, 280], [80, 80],
                ],
            },
            {
                "erase": True,
                "brush": 30,
                "pts": [[250, 80], [300, 80], [350, 80]],
            },
        ]
        hc.save_fields({"A": {"strokes": loop}}, poly_a, poly_b)
        kept = hc.zone_strokes("A")
        self.assertTrue(kept)
        self.assertFalse(any(s.get("erase") for s in kept))
        # Top edge around x=300 should have been erased from saved strokes.
        top_xs = [p[0] for s in kept for p in s["pts"] if abs(p[1] - 80) < 8]
        self.assertTrue(top_xs)
        self.assertFalse(any(abs(x - 300) < 20 for x in top_xs))

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
