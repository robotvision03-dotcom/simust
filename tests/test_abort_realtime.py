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

    def tearDown(self):
        simust_app.REALTIME_RECORDINGS_DIR = self.prev_dir
        simust_app._realtime_dirs_at_start = self.prev_start
        simust_app.current_results_dir = self.prev_results
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_keeps_older_sessions_and_deletes_current(self):
        removed = simust_app.discard_aborted_realtime_folders()
        self.assertEqual(removed, ["new_session"])
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "old_session")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "new_session")))
        self.assertIsNone(simust_app.current_results_dir)


class AbortFlagTests(unittest.TestCase):
    def setUp(self):
        self.prev = simust_app.realtime_aborted
        simust_app.realtime_aborted = True

    def tearDown(self):
        simust_app.realtime_aborted = self.prev

    def test_playback_status_aborted(self):
        import asyncio
        data = asyncio.run(simust_app.get_playback_status())
        self.assertEqual(data["state"], "aborted")

    def test_realtime_results_aborted(self):
        import asyncio
        data = asyncio.run(simust_app.get_realtime_results())
        self.assertEqual(data["status"], "aborted")
        self.assertIsNone(data.get("report"))


if __name__ == "__main__":
    unittest.main()
