"""Operator Pause freezes playback status and is allowed as a remote command."""

import asyncio
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("SIMUST_PUBLIC_MODE", "1")
os.environ.setdefault("SIMUST_SESSION_SECRET", "test-session-secret-not-for-production")

import app as simust_app  # noqa: E402
import simust_remote  # noqa: E402


class PauseSettingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="simust-pause-")
        self.prev_dir = simust_app.SIMUST_PLAYER_DIRECTORY
        self.prev_abort = simust_app.realtime_aborted
        self.prev_active = simust_app._realtime_session_active
        simust_app.SIMUST_PLAYER_DIRECTORY = self.tmp
        simust_app.realtime_aborted = False
        simust_app._realtime_session_active = False

    def tearDown(self):
        simust_app.SIMUST_PLAYER_DIRECTORY = self.prev_dir
        simust_app.realtime_aborted = self.prev_abort
        simust_app._realtime_session_active = self.prev_active
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_write_and_read_pause_file(self):
        simust_app.write_pause_setting(True)
        self.assertTrue(simust_app.read_pause_setting())
        with open(os.path.join(self.tmp, "pause.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), "true")
        simust_app.write_pause_setting(False)
        self.assertFalse(simust_app.read_pause_setting())

    def test_playback_status_shows_paused(self):
        simust_app.write_playback_status("playing", "Video 2/8")
        simust_app.write_pause_setting(True)
        data = asyncio.run(simust_app.get_playback_status())
        self.assertTrue(data["paused"])
        self.assertEqual(data["state"], "paused")

    def test_playback_status_keeps_video_counts(self):
        status_file = os.path.join(self.tmp, "playback_status.json")
        with open(status_file, "w", encoding="utf-8") as f:
            json.dump({"state": "playing", "current_video": 3, "total_videos": 8, "progress": 40}, f)
        simust_app.write_playback_status("paused", "Paused — press Play to continue")
        with open(status_file, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["current_video"], 3)
        self.assertEqual(saved["total_videos"], 8)
        self.assertEqual(saved["state"], "paused")

    def test_aborted_status_wins_over_pause(self):
        simust_app.realtime_aborted = True
        simust_app._realtime_session_active = True
        simust_app.write_pause_setting(True)
        data = asyncio.run(simust_app.get_playback_status())
        self.assertEqual(data["state"], "aborted")
        self.assertFalse(data["paused"])


class CameraPauseShiftTests(unittest.TestCase):
    def test_unfreeze_shifts_pending_timers(self):
        try:
            from simust_realtime import SimustRealtimeCamera
        except Exception as exc:
            self.skipTest("simust_realtime not importable here: %s" % exc)

        cam = SimustRealtimeCamera.__new__(SimustRealtimeCamera)
        cam.operator_paused = False
        cam._pause_lock = __import__("threading").Lock()
        cam._pause_started_at = 0
        cam._paused_analysis_remaining = None
        ch = type("Ch", (), {})()
        ch.analysis_timer = None
        ch.analysis_started_at = 0
        ch._paused_analysis_remaining = None
        ch.pending_start = {"action": "PASS"}
        ch.pending_start_time = 100.0
        ch.pending_end = True
        ch.pending_end_time = 110.0
        ch.pending_end_time_str = ""
        ch.session_active = True
        ch.session_start_timestamp = 90.0
        ch.between_sessions_active = False
        ch.between_session_start_ts = 0
        ch.between_session_start_time = None
        ch.current_qr_block = None
        ch.qr_state = {}
        cam.channels = {"A": ch}
        cam.simulators = {"A": type("Sim", (), {"start_ts": 95.0, "late_start_ts": 0.0})()}
        cam._field_is_active = lambda fid: True

        cam._freeze_for_pause()
        self.assertTrue(cam.operator_paused)
        cam._pause_started_at -= 2.5
        cam._unfreeze_after_pause()
        self.assertFalse(cam.operator_paused)
        self.assertAlmostEqual(ch.pending_start_time, 102.5, places=1)
        self.assertAlmostEqual(ch.pending_end_time, 112.5, places=1)
        self.assertAlmostEqual(ch.session_start_timestamp, 92.5, places=1)
        self.assertAlmostEqual(cam.simulators["A"].start_ts, 97.5, places=1)


class PauseRemoteTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        handle.close()
        os.remove(handle.name)
        self.tmp_name = handle.name
        simust_remote.COMMANDS_FILE = self.tmp_name

    def tearDown(self):
        try:
            os.remove(self.tmp_name)
        except OSError:
            pass

    def test_pause_realtime_is_allowed(self):
        item = simust_remote.enqueue("pause-realtime", {"paused": True}, "admin")
        self.assertEqual(item["action"], "pause-realtime")
        self.assertTrue(item["payload"]["paused"])


if __name__ == "__main__":
    unittest.main()
