"""Operator Stop discards the in-progress test and does not keep results."""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("SIMUST_PUBLIC_MODE", "1")
os.environ.setdefault("SIMUST_SESSION_SECRET", "test-session-secret-not-for-production")

import app as simust_app  # noqa: E402


class DiscardAbortedFoldersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="simust-abort-")
        self.prev_dir = simust_app.REALTIME_RECORDINGS_DIR
        self.prev_start = simust_app._realtime_dirs_at_start
        self.prev_results = simust_app.current_results_dir
        simust_app.REALTIME_RECORDINGS_DIR = self.tmp
        os.makedirs(os.path.join(self.tmp, "old_session"), exist_ok=True)
        simust_app._realtime_dirs_at_start = {"old_session"}
        os.makedirs(os.path.join(self.tmp, "new_session"), exist_ok=True)
        with open(os.path.join(self.tmp, "new_session", "results.json"), "w", encoding="utf-8") as f:
            f.write("[]")
        simust_app.current_results_dir = os.path.join(self.tmp, "new_session")
        self.prev_active = simust_app._realtime_session_active
        simust_app._realtime_session_active = True

    def tearDown(self):
        simust_app.REALTIME_RECORDINGS_DIR = self.prev_dir
        simust_app._realtime_dirs_at_start = self.prev_start
        simust_app.current_results_dir = self.prev_results
        simust_app._realtime_session_active = self.prev_active
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_keeps_older_sessions_and_deletes_current(self):
        removed = simust_app.discard_aborted_realtime_folders()
        self.assertEqual(removed, ["new_session"])
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "old_session")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "new_session")))
        self.assertIsNone(simust_app.current_results_dir)

    def test_idle_discard_does_not_delete_folders(self):
        simust_app._realtime_session_active = False
        removed = simust_app.discard_aborted_realtime_folders()
        self.assertEqual(removed, [])
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "new_session")))


class AbortFlagTests(unittest.TestCase):
    def setUp(self):
        self.prev = simust_app.realtime_aborted
        self.prev_active = simust_app._realtime_session_active
        simust_app.realtime_aborted = True
        simust_app._realtime_session_active = True

    def tearDown(self):
        simust_app.realtime_aborted = self.prev
        simust_app._realtime_session_active = self.prev_active

    def test_playback_status_aborted(self):
        import asyncio
        data = asyncio.run(simust_app.get_playback_status())
        self.assertEqual(data["state"], "aborted")

    def test_realtime_results_aborted(self):
        import asyncio
        data = asyncio.run(simust_app.get_realtime_results())
        self.assertEqual(data["status"], "aborted")
        self.assertIsNone(data.get("report"))


class PublishStatusTests(unittest.TestCase):
    def test_publish_lab_status_is_in_process(self):
        pushed = []
        prev = simust_app.simust_push.push_lab_status
        simust_app.simust_push.push_lab_status = pushed.append
        try:
            simust_app._publish_lab_status()
        finally:
            simust_app.simust_push.push_lab_status = prev
        self.assertEqual(len(pushed), 1)
        self.assertTrue(pushed[0].get("lab_online"))
        self.assertIn("playback-status", pushed[0])


class StaleRemoteStopTests(unittest.TestCase):
    def setUp(self):
        self.prev_abort = simust_app.realtime_aborted
        self.prev_active = simust_app._realtime_session_active
        self.prev_started = simust_app._realtime_session_started_at
        simust_app.realtime_aborted = False
        simust_app._realtime_session_active = False
        simust_app._realtime_session_started_at = 0.0

    def tearDown(self):
        simust_app.realtime_aborted = self.prev_abort
        simust_app._realtime_session_active = self.prev_active
        simust_app._realtime_session_started_at = self.prev_started

    def test_idle_remote_abort_is_ignored(self):
        self.assertTrue(simust_app.should_ignore_remote_stop({
            "_remote": True,
            "abort": True,
            "_queued_at": "2020-01-01T00:00:00",
        }))

    def test_idle_abort_without_remote_flag_is_ignored(self):
        self.assertTrue(simust_app.should_ignore_remote_stop({"abort": True}))

    def test_local_operator_stop_is_not_ignored(self):
        simust_app._realtime_session_active = True
        self.assertFalse(simust_app.should_ignore_remote_stop({"abort": True}))

    def test_stale_remote_stop_before_session_is_ignored(self):
        simust_app._realtime_session_active = True
        simust_app._realtime_session_started_at = 2_000_000_000
        self.assertTrue(simust_app.should_ignore_remote_stop({
            "_remote": True,
            "abort": True,
            "_queued_at": "2020-01-01T00:00:00",
        }))


class Screen2DisplayTests(unittest.TestCase):
    def test_player_owned_sequence_does_not_spawn_helpers(self):
        self.assertFalse(simust_app.should_spawn_screen2_display(False))
        self.assertFalse(simust_app.should_spawn_screen2_display("false"))

    def test_operator_can_display_when_player_is_idle(self):
        previous = simust_app.smart_player_process
        simust_app.smart_player_process = None
        try:
            self.assertTrue(simust_app.should_spawn_screen2_display(True))
        finally:
            simust_app.smart_player_process = previous


if __name__ == "__main__":
    unittest.main()
