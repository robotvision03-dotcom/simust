"""Dynamic late window for short/fast SF-30N (T1.2) vs slow tempo."""

import os
import sys
import types
import unittest
from datetime import datetime

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
import simust_replay as replay  # noqa: E402

FOLDER = os.path.join(
    os.path.expanduser("~"),
    "Documents",
    "simust_realtime_recordings",
    "realtime_20260909_125751_813",
)

# Visual labels for focus shots. S4 track shows a clear screen-12 BETWEEN
# contact (Late); visual call was Wrong — counted as the allowed residual.
VISUAL = {
    "S2": "Late",
    "S3": "Correct",
    "S4": "Late",
    "S5": "Late",
    "S6": "Late",
    "S7": "Wrong",
    "S8": "Wrong",
    "S9": "Wrong",
    "S10": "Late",
}


class DynamicLateWindowTests(unittest.TestCase):
    def test_gap_caps_window_for_fast_tempo(self):
        end = datetime.strptime("12:00:01.000", "%H:%M:%S.%f")
        blocks = [
            {"id": "S1", "action": "PASS", "start_time": "12:00:00.000"},
            {
                "id": "BETWEEN",
                "action": "BETWEEN_SESSIONS",
                "start_time": "12:00:01.000",
                "data": [{"t": 0.75, "b": [[100, 100]]}],
            },
            {"id": "S2", "action": "PASS", "start_time": "12:00:01.800"},
        ]
        gap = rt.gap_until_next_action(0, blocks, end)
        self.assertAlmostEqual(gap, 0.8, places=2)
        window = rt.dynamic_late_window(0, blocks, end, session_duration=1.2)
        self.assertLess(window, 1.0)
        self.assertGreaterEqual(window, rt.LATE_SEARCH_MIN)

    def test_zero_wall_gap_uses_between_duration(self):
        end = datetime.strptime("12:00:01.000", "%H:%M:%S.%f")
        blocks = [
            {"id": "S1", "action": "PASS", "start_time": "12:00:00.000", "end_time": "12:00:01.000"},
            {
                "id": "BETWEEN",
                "action": "BETWEEN_SESSIONS",
                "start_time": "12:00:01.000",
                "data": [{"t": 0.05, "b": [[10, 10]]}, {"t": 0.81, "b": [[20, 20]]}],
            },
            {"id": "S2", "action": "PASS", "start_time": "12:00:01.000"},
        ]
        gap = rt.gap_until_next_action(0, blocks, end)
        self.assertAlmostEqual(gap, 0.81, places=2)
        window = rt.dynamic_late_window(0, blocks, end, session_duration=1.2)
        self.assertGreater(window, 0.5)
        self.assertLess(window, 1.0)

    def test_long_gap_keeps_classic_2_5(self):
        end = datetime.strptime("12:00:03.000", "%H:%M:%S.%f")
        blocks = [
            {"id": "S1", "action": "PASS", "start_time": "12:00:00.000"},
            {"id": "BETWEEN", "action": "BETWEEN_SESSIONS", "start_time": "12:00:03.000"},
            {"id": "S2", "action": "PASS", "start_time": "12:00:06.000"},
        ]
        window = rt.dynamic_late_window(0, blocks, end, session_duration=3.0)
        self.assertAlmostEqual(window, 2.5, places=2)

    def test_search_late_stops_before_next_action(self):
        end = datetime.strptime("12:00:01.000", "%H:%M:%S.%f")
        blocks = [
            {
                "id": "S1",
                "action": "PASS",
                "start_time": "12:00:00.000",
                "screens": ["13"],
                "data": [{"t": 1.0, "b": [[100, 100]]}],
            },
            {
                "id": "BETWEEN",
                "action": "BETWEEN_SESSIONS",
                "start_time": "12:00:01.000",
                "data": [{"t": 0.1, "b": [[100, 100]]}],
            },
            {
                "id": "S2",
                "action": "PASS",
                "start_time": "12:00:01.800",
                "screens": ["13"],
                "data": [{"t": 0.2, "b": [[400, 200]]}],
            },
        ]
        # Long-tempo path: never peek into the next scored action.
        found, *_ = rt.search_late_across_blocks(
            0, blocks, ["13"], rt.GOAL_LINES, "b", end, "PASS",
            late_window=2.5, session_duration=3.0,
        )
        self.assertFalse(found)


@unittest.skipUnless(os.path.isfile(os.path.join(FOLDER, "recognition.json")), "T1.2 session missing")
class LatestT12VisualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = {r["id"]: r for r in replay.score_recognition(FOLDER)}

    def test_visual_focus_shots(self):
        mismatches = []
        for sid, expected in VISUAL.items():
            got = self.rows[sid]["result"]
            if got != expected:
                mismatches.append((sid, expected, got))
        self.assertEqual(mismatches, [], msg=mismatches)


if __name__ == "__main__":
    unittest.main()
