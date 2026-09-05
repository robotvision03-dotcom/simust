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

    def test_peek_then_ack(self):
        item = simust_remote.enqueue("stop-realtime", {}, "james")
        peeked = simust_remote.peek_pending()
        self.assertEqual(len(peeked), 1)
        self.assertEqual(peeked[0]["id"], item["id"])
        self.assertEqual(len(simust_remote.peek_pending()), 1)
        self.assertEqual(simust_remote.ack_ids([item["id"]]), 1)
        self.assertEqual(simust_remote.peek_pending(), [])

    def test_rejects_unknown_action(self):
        with self.assertRaises(ValueError):
            simust_remote.enqueue("cameras", {}, "coach1")

    def test_status_roundtrip(self):
        simust_remote.set_status({"playback-status": {"state": "playing"}})
        status = simust_remote.get_status()
        self.assertTrue(status.get("lab_online"))
        self.assertEqual(status["playback-status"]["state"], "playing")

    def test_stale_commands_are_dropped(self):
        prev_ttl = simust_remote.REMOTE_COMMAND_TTL_SEC
        simust_remote.REMOTE_COMMAND_TTL_SEC = 1
        try:
            item = simust_remote.enqueue("stop-realtime", {"abort": True}, "admin")
            item["created_at"] = "2020-01-01T00:00:00"
            simust_remote.enqueue("start-realtime-playback", {"player_id": "james"}, "admin")
            # Rewrite the first command to an expired timestamp.
            state = simust_remote._load()
            state["pending"][0]["created_at"] = "2020-01-01T00:00:00"
            simust_remote._save(state)
            pending = simust_remote.peek_pending()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["action"], "start-realtime-playback")
        finally:
            simust_remote.REMOTE_COMMAND_TTL_SEC = prev_ttl


if __name__ == "__main__":
    unittest.main()
