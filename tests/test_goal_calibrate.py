"""Goal-area calibration store maps A1–A6 / B1–B6 onto GOAL_LINES cabinets."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import simust_goal_calibrate as gc  # noqa: E402


class GoalCalibrateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="simust-goal-cal-")
        self.prev = gc.CALIBRATION_FILE
        gc.CALIBRATION_FILE = os.path.join(self.tmp, "goal_lines_calibration.json")
        gc._cache = None
        gc._cache_mtime = 0.0

    def tearDown(self):
        gc.CALIBRATION_FILE = self.prev
        gc._cache = None
        gc._cache_mtime = 0.0
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_applies_to_cabinet_goal_lines(self):
        goal_lines = {
            "12": {"p0": (1, 1), "p1": (2, 2)},
            "5": {"p0": (3, 3), "p1": (4, 4)},
        }
        gc.save_screens(
            {
                "A1": {"p0": [513, 133], "p1": [541, 142]},
                "B1": {"p0": [1154, 112], "p1": [1180, 122]},
            },
            goal_lines,
        )
        self.assertEqual(goal_lines["12"]["p0"], (513.0, 133.0))
        self.assertEqual(goal_lines["12"]["p1"], (541.0, 142.0))
        self.assertEqual(goal_lines["5"]["p0"], (1154.0, 112.0))
        status = gc.public_status(goal_lines)
        self.assertTrue(status["screens"]["A1"]["calibrated"])
        self.assertEqual(status["screens"]["A1"]["cabinet"], "12")

    def test_rejects_short_junk_lines(self):
        goal_lines = {
            "12": {"p0": (513, 133), "p1": (541, 142)},
            "5": {"p0": (1154, 112), "p1": (1180, 122)},
        }
        gc.save_store(
            {
                "version": 1,
                "screens": {
                    "A1": {"p0": [100, 200], "p1": [110, 210]},
                    "B1": {"p0": [900, 200], "p1": [910, 210]},
                },
            }
        )
        gc.apply_overrides_to(goal_lines)
        self.assertEqual(goal_lines["12"]["p0"], (513, 133))
        self.assertEqual(goal_lines["5"]["p0"], (1154, 112))
        status = gc.public_status(goal_lines)
        self.assertFalse(status["screens"]["A1"]["calibrated"])
        self.assertEqual(status["screens"]["A1"]["p0"], [513.0, 133.0])

    def test_reset_clears_overrides(self):
        goal_lines = {"12": {"p0": (1, 1), "p1": (2, 2)}}
        gc.save_screens({"A1": {"p0": [50, 60], "p1": [90, 100]}}, goal_lines)
        gc.reset_store()
        restored = {"12": {"p0": (1, 1), "p1": (2, 2)}}
        gc.apply_overrides_to(restored)
        self.assertEqual(restored["12"]["p0"], (1, 1))


if __name__ == "__main__":
    unittest.main()
