"""QR flicker must not split one action into a ghost Wrong + a real session."""

import os
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class QrFlickerDebounceTests(unittest.TestCase):
    def _make_cam(self):
        from simust_realtime import QR_COOLDOWN, SimustRealtimeCamera

        cam = SimustRealtimeCamera.__new__(SimustRealtimeCamera)
        cam.session_lock = threading.Lock()
        cam.pending_start = None
        cam.pending_start_time = 0
        cam.pending_end = False
        cam.pending_end_time = 0
        cam.session_active = True
        cam.current_qr_block = {
            "id": "S8",
            "action": "PASS",
            "screens": ["13"],
            "keypoints": [],
            "start_time": "13:46:23.878",
            "end_time": "",
            "data": [],
        }
        cam.block_counter = 8
        cam.qr_blocks = []
        cam.qr_state = {
            "last_raw_data": "PASS,13",
            "last_detection_time": 1000.0,
            "cooldown": QR_COOLDOWN,
            "detection_count": 1,
            "missing_since": None,
        }
        cam.qr_roi = None
        cam.visualization_enabled = False
        cam.session_start_timestamp = 1000.0
        cam.scheduled_ends = []
        cam.scheduled_starts = []

        def _schedule_end(time_str, ts):
            cam.pending_end = True
            cam.pending_end_time = ts + 0.84
            cam.scheduled_ends.append(ts)

        def _schedule_start(action, screens, keypoints, block_id, time_str, ts):
            cam.scheduled_starts.append((block_id, action, screens, ts))
            cam.pending_start = {"block_id": block_id}

        cam.schedule_session_end = _schedule_end
        cam.schedule_session_start = _schedule_start
        cam._end_session_locked = lambda *a, **k: None
        cam._execute_end = lambda *a, **k: None
        return cam

    def test_brief_miss_does_not_end_or_spawn_new_session(self):
        from simust_realtime import QR_DISAPPEAR_DEBOUNCE

        cam = self._make_cam()
        frame = object()
        t0 = 2000.0

        with patch("simust_realtime.detect_qr_in_roi", return_value=(None, None)):
            cam.process_qr_detection(frame, "13:46:24.000", t0)
            # Still inside debounce window
            cam.process_qr_detection(frame, "13:46:24.100", t0 + 0.10)

        self.assertIsNotNone(cam.qr_state["missing_since"])
        self.assertFalse(cam.pending_end)
        self.assertEqual(cam.scheduled_ends, [])
        self.assertEqual(cam.scheduled_starts, [])
        self.assertEqual(cam.qr_state["last_raw_data"], "PASS,13")

        # Same QR returns before debounce → flicker recovery
        with patch("simust_realtime.detect_qr_in_roi", return_value=("PASS,13", None)), patch(
            "simust_realtime.parse_qr_data", return_value=("PASS", ["13"], [])
        ):
            cam.process_qr_detection(frame, "13:46:24.200", t0 + 0.20)

        self.assertIsNone(cam.qr_state["missing_since"])
        self.assertFalse(cam.pending_end)
        self.assertEqual(cam.scheduled_starts, [])
        self.assertLess(0.10, QR_DISAPPEAR_DEBOUNCE)

    def test_miss_then_return_during_pending_end_cancels_end(self):
        cam = self._make_cam()
        frame = object()
        t0 = 2000.0

        with patch("simust_realtime.detect_qr_in_roi", return_value=(None, None)):
            cam.process_qr_detection(frame, "13:46:24.000", t0)
            cam.process_qr_detection(frame, "13:46:24.400", t0 + 0.40)

        self.assertTrue(cam.pending_end)
        self.assertEqual(len(cam.scheduled_ends), 1)
        # last_raw_data kept until real end so identical reappearance is not "new"
        self.assertEqual(cam.qr_state["last_raw_data"], "PASS,13")

        with patch("simust_realtime.detect_qr_in_roi", return_value=("PASS,13", None)), patch(
            "simust_realtime.parse_qr_data", return_value=("PASS", ["13"], [])
        ):
            cam.process_qr_detection(frame, "13:46:24.500", t0 + 0.50)

        self.assertFalse(cam.pending_end)
        self.assertEqual(cam.scheduled_starts, [])
        self.assertEqual(cam.block_counter, 8)


if __name__ == "__main__":
    unittest.main()
