"""Paid 30-minute session unlock pipeline."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("SIMUST_PUBLIC_MODE", "1")
os.environ.setdefault("SIMUST_SESSION_SECRET", "test-session-secret-not-for-production")

import simust_progress  # noqa: E402
from app import ALL_LEVELS, apply_session_progress  # noqa: E402


class SessionUnlockPipelineTests(unittest.TestCase):
    def _fresh(self):
        return {
            "cristiano": {
                "name": "Cristiano",
                "surname": "Ronaldo",
                "role": "player",
                "progress": simust_progress.default_progress(),
            }
        }

    def test_new_player_starts_on_sf30_and_later_sets_stay_locked(self):
        users = self._fresh()
        progress = users["cristiano"]["progress"]
        ok, _reason = simust_progress.can_play(progress, "L00-Foundation", "SF-30N")
        self.assertTrue(ok)
        locked, reason = simust_progress.can_play(progress, "L00-Foundation", "SF-60N")
        self.assertFalse(locked)
        self.assertIn("locked", reason.lower())

    def test_booking_does_not_open_the_next_set(self):
        users = self._fresh()
        result = simust_progress.grant_reservation_credits(
            users, "cristiano", 90, "res-90", ALL_LEVELS
        )
        self.assertEqual(result["credits_added"], 3)
        self.assertEqual(result["unlocked_playlists"], ["SF-30N"])
        progress = users["cristiano"]["progress"]
        self.assertFalse(simust_progress.can_play(progress, "L00-Foundation", "SF-60N")[0])

    def test_passing_score_opens_the_next_set_and_keeps_it_open(self):
        users = self._fresh()
        apply_session_progress(
            users,
            "cristiano",
            "L00-Foundation",
            "SF-30N",
            {"correct": 8, "late": 0, "wrong": 2, "miss": 0, "avg_ae": 70.0},
        )
        progress = users["cristiano"]["progress"]
        self.assertTrue(progress["challenge_results"]["L00-Foundation"]["passed"])
        self.assertIn("SF-60N", progress["unlocked_playlists"])
        self.assertIn("SF-30N", progress["unlocked_playlists"])
        self.assertEqual(progress["current_playlist"], "SF-60N")
        self.assertNotIn("L01-Entry/A-T1", progress["unlocked_levels"])

    def test_sf180_pass_opens_entry(self):
        users = self._fresh()
        progress = users["cristiano"]["progress"]
        progress["unlocked_playlists"] = ["SF-30N", "SF-60N", "SF-110N", "SF-180N"]
        apply_session_progress(
            users,
            "cristiano",
            "L00-Foundation",
            "SF-180N",
            {"correct": 3, "late": 0, "wrong": 1, "miss": 0, "avg_ae": 70.0},
        )
        progress = users["cristiano"]["progress"]
        self.assertTrue(progress["challenge_results"]["L00-Foundation"]["passed"])
        self.assertIn("L01-Entry/A-T1", progress["unlocked_levels"])
        self.assertEqual(progress["current_level"], "L01-Entry/A-T1")
        self.assertTrue(simust_progress.can_play(progress, "L01-Entry/A-T1")[0])

    def test_entry_needs_the_higher_score(self):
        users = self._fresh()
        progress = users["cristiano"]["progress"]
        progress["unlocked_levels"] = ["L00-Foundation", "L01-Entry/A-T1"]
        progress["current_level"] = "L01-Entry/A-T1"
        apply_session_progress(
            users,
            "cristiano",
            "L01-Entry/A-T1",
            "",
            {"correct": 8, "late": 0, "wrong": 2, "miss": 0, "avg_ae": 70.0},
        )
        progress = users["cristiano"]["progress"]
        self.assertFalse(progress["challenge_results"]["L01-Entry/A-T1"]["passed"])
        self.assertNotIn("L01-Entry/A-T2", progress["unlocked_levels"])
        apply_session_progress(
            users,
            "cristiano",
            "L01-Entry/A-T1",
            "",
            {"correct": 17, "late": 0, "wrong": 3, "miss": 0, "avg_ae": 80.0},
        )
        progress = users["cristiano"]["progress"]
        self.assertTrue(progress["challenge_results"]["L01-Entry/A-T1"]["passed"])
        self.assertIn("L01-Entry/A-T2", progress["unlocked_levels"])
        self.assertIn("L01-Entry/A-T1", progress["unlocked_levels"])

    def test_grant_is_idempotent_per_reservation(self):
        users = self._fresh()
        simust_progress.grant_reservation_credits(users, "cristiano", 30, "same", ALL_LEVELS)
        again = simust_progress.grant_reservation_credits(
            users, "cristiano", 30, "same", ALL_LEVELS
        )
        self.assertEqual(again["credits_added"], 0)
        self.assertEqual(users["cristiano"]["progress"]["unlocked_playlists"], ["SF-30N"])


class FoundationProgressTests(unittest.TestCase):
    def _player(self):
        users = {
            "james": {
                "name": "James",
                "surname": "Winston",
                "role": "player",
                "progress": simust_progress.default_progress(),
            }
        }
        simust_progress.grant_reservation_credits(users, "james", 120, "setup", ALL_LEVELS)
        return users

    def test_sf30n_does_not_unlock_entry(self):
        users = self._player()
        stats = {"correct": 8, "late": 1, "wrong": 1, "miss": 0, "avg_ae": 82.0}
        changed = apply_session_progress(users, "james", "L00-Foundation", "SF-30N", stats)
        self.assertTrue(changed)
        progress = users["james"]["progress"]
        self.assertTrue(progress["challenge_results"]["L00-Foundation"]["passed"])
        self.assertIn("SF-60N", progress["unlocked_playlists"])
        self.assertNotIn("L01-Entry/A-T1", progress["unlocked_levels"])
        self.assertEqual(progress["challenge_results"]["L00-Foundation"]["subdirectory"], "SF-30N")

    def test_sf180n_opens_entry(self):
        users = self._player()
        progress = users["james"]["progress"]
        progress["unlocked_playlists"] = ["SF-30N", "SF-60N", "SF-110N", "SF-180N"]
        stats = {"correct": 3, "late": 0, "wrong": 1, "miss": 0, "avg_ae": 70.0}
        apply_session_progress(users, "james", "L00-Foundation", "SF-180N", stats)
        progress = users["james"]["progress"]
        self.assertTrue(progress["challenge_results"]["L00-Foundation"]["passed"])
        self.assertIn("L01-Entry/A-T1", progress["unlocked_levels"])


if __name__ == "__main__":
    unittest.main()
