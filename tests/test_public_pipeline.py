"""Pipeline checks for My SIMUST sync: calendar merge and Foundation SF-30N progress."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("SIMUST_PUBLIC_MODE", "1")
os.environ.setdefault("SIMUST_SESSION_SECRET", "test-session-secret-not-for-production")

import simust_push  # noqa: E402
from app import apply_session_progress  # noqa: E402


class ReservationMergeTests(unittest.TestCase):
    def test_adds_new_public_booking(self):
        local = [{"id": "lab-1", "source": "lab", "player_id": "a"}]
        remote = [{"id": "pub-1", "source": "public", "player_id": "james"}]
        added = simust_push.merge_remote_reservations(local, remote, prune_source="public")
        self.assertEqual(added, 1)
        self.assertEqual({row["id"] for row in local}, {"lab-1", "pub-1"})

    def test_prunes_cancelled_public_booking(self):
        local = [
            {"id": "pub-1", "source": "public", "player_id": "james"},
            {"id": "lab-1", "source": "lab", "player_id": "a"},
        ]
        added = simust_push.merge_remote_reservations(local, [], prune_source="public")
        self.assertEqual(added, 0)
        self.assertEqual([row["id"] for row in local], ["lab-1"])

    def test_deleted_ids_removed_on_lab_push(self):
        local = [{"id": "keep"}, {"id": "gone"}]
        added = simust_push.merge_remote_reservations(local, [], deleted_ids=["gone"])
        self.assertEqual(added, 0)
        self.assertEqual([row["id"] for row in local], ["keep"])


class FoundationProgressTests(unittest.TestCase):
    def _player(self):
        return {
            "james": {
                "name": "James",
                "surname": "Winston",
                "role": "player",
                "progress": {
                    "current_level": "L00-Foundation",
                    "unlocked_levels": ["L00-Foundation"],
                    "completed_levels": [],
                    "challenge_results": {},
                },
            }
        }

    def test_sf30n_does_not_unlock_entry(self):
        users = self._player()
        stats = {"correct": 8, "late": 1, "wrong": 1, "miss": 0, "avg_ae": 82.0}
        changed = apply_session_progress(users, "james", "L00-Foundation", "SF-30N", stats)
        self.assertTrue(changed)
        progress = users["james"]["progress"]
        self.assertEqual(progress["current_level"], "L00-Foundation")
        self.assertNotIn("L01-Entry", progress["unlocked_levels"])
        self.assertFalse(progress["challenge_results"]["L00-Foundation"]["passed"])
        self.assertEqual(progress["challenge_results"]["L00-Foundation"]["subdirectory"], "SF-30N")
        self.assertEqual(progress["challenge_results"]["L00-Foundation"]["aac"], 90.0)

    def test_sf180n_unlocks_entry(self):
        users = self._player()
        stats = {"correct": 8, "late": 1, "wrong": 1, "miss": 0, "avg_ae": 82.0}
        apply_session_progress(users, "james", "L00-Foundation", "SF-180N", stats)
        progress = users["james"]["progress"]
        self.assertTrue(progress["challenge_results"]["L00-Foundation"]["passed"])
        self.assertIn("L01-Entry/A-T1/A.T1.C1", progress["unlocked_levels"])


class SanitizeSessionTests(unittest.TestCase):
    def test_strips_lab_paths_and_photos(self):
        clean = simust_push.sanitize_session({
            "session": {"directory": "C:\\\\lab", "level": "L00-Foundation", "subdirectory": "SF-30N"},
            "player": {"image": "data:image/png;base64,xxxx", "name": "James"},
            "statistics": {"correct": 1},
        })
        self.assertNotIn("directory", clean["session"])
        self.assertEqual(clean["player"]["image"], "")
        self.assertEqual(clean["session"]["subdirectory"], "SF-30N")


if __name__ == "__main__":
    unittest.main()
