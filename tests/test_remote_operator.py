"""Public tablet operator command queue."""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import simust_remote  # noqa: E402


class RemoteQueueTests(unittest.TestCase):
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

    def test_enqueue_and_take(self):
        item = simust_remote.enqueue(
            "start-realtime-playback",
            {"player_id": "james", "level": "L00-Foundation", "subdirectory": "SF-30N", "simulation_enabled": True},
            "coach1",
        )
        self.assertEqual(item["action"], "start-realtime-playback")
        taken = simust_remote.take_pending()
        self.assertEqual(len(taken), 1)
        self.assertEqual(taken[0]["payload"]["subdirectory"], "SF-30N")
        self.assertEqual(simust_remote.take_pending(), [])

    def test_rejects_unknown_action(self):
        with self.assertRaises(ValueError):
            simust_remote.enqueue("cameras", {}, "coach1")

    def test_status_roundtrip(self):
        simust_remote.set_status({"playback-status": {"state": "playing"}})
        status = simust_remote.get_status()
        self.assertTrue(status.get("lab_online"))
        self.assertEqual(status["playback-status"]["state"], "playing")


if __name__ == "__main__":
    unittest.main()
