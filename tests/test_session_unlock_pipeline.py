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

    def test_unpaid_cannot_play_foundation(self):
        users = self._fresh()
        progress = users["cristiano"]["progress"]
        ok, reason = simust_progress.can_play(progress, "L00-Foundation", "SF-30N")
        self.assertFalse(ok)
        self.assertIn("locked", reason.lower())

    def test_30_minutes_opens_sf30_only(self):
        users = self._fresh()
        result = simust_progress.grant_reservation_credits(
            users, "cristiano", 30, "res-1", ALL_LEVELS
        )
        self.assertEqual(result["credits_added"], 1)
        self.assertEqual(result["unlocked_playlists"], ["SF-30N"])
        self.assertIn("L00-Foundation", result["unlocked_levels"])
        progress = users["cristiano"]["progress"]
        self.assertTrue(simust_progress.can_play(progress, "L00-Foundation", "SF-30N")[0])
        self.assertFalse(simust_progress.can_play(progress, "L00-Foundation", "SF-60N")[0])

    def test_90_minutes_opens_three_foundation_playlists(self):
        users = self._fresh()
        result = simust_progress.grant_reservation_credits(
            users, "cristiano", 90, "res-90", ALL_LEVELS
        )
        self.assertEqual(result["credits_added"], 3)
        self.assertEqual(
            result["unlocked_playlists"], ["SF-30N", "SF-60N", "SF-110N"]
        )

    def test_foundation_score_does_not_open_next_sf(self):
        users = self._fresh()
        simust_progress.grant_reservation_credits(users, "cristiano", 30, "r1", ALL_LEVELS)
        apply_session_progress(
            users,
            "cristiano",
            "L00-Foundation",
            "SF-30N",
            {"correct": 9, "late": 1, "wrong": 0, "miss": 0, "avg_ae": 90.0},
        )
        progress = users["cristiano"]["progress"]
        self.assertEqual(progress["unlocked_playlists"], ["SF-30N"])
        self.assertNotIn("L01-Entry/A-T1/A.T1.C1", progress["unlocked_levels"])

    def test_sf180_pass_then_pay_opens_entry(self):
        users = self._fresh()
        simust_progress.grant_reservation_credits(users, "cristiano", 120, "r-found", ALL_LEVELS)
        progress = users["cristiano"]["progress"]
        self.assertEqual(
            progress["unlocked_playlists"],
            ["SF-30N", "SF-60N", "SF-110N", "SF-180N"],
        )
        apply_session_progress(
            users,
            "cristiano",
            "L00-Foundation",
            "SF-180N",
            {"correct": 8, "late": 1, "wrong": 1, "miss": 0, "avg_ae": 82.0},
        )
        progress = users["cristiano"]["progress"]
        self.assertTrue(progress["challenge_results"]["L00-Foundation"]["passed"])
        self.assertIn("L01-Entry/A-T1/A.T1.C1", progress["eligible_levels"])
        self.assertNotIn("L01-Entry/A-T1/A.T1.C1", progress["unlocked_levels"])

        simust_progress.grant_reservation_credits(users, "cristiano", 30, "r-entry", ALL_LEVELS)
        progress = users["cristiano"]["progress"]
        self.assertIn("L01-Entry/A-T1/A.T1.C1", progress["unlocked_levels"])
        self.assertTrue(
            simust_progress.can_play(progress, "L01-Entry/A-T1/A.T1.C1")[0]
        )

    def test_pending_credit_spent_after_score(self):
        users = self._fresh()
        simust_progress.grant_reservation_credits(users, "cristiano", 120, "r1", ALL_LEVELS)
        # Extra 30 min while waiting on SF-180 score — credit sits unused.
        simust_progress.grant_reservation_credits(users, "cristiano", 30, "r2", ALL_LEVELS)
        progress = users["cristiano"]["progress"]
        self.assertEqual(progress["session_credits"], 1)
        apply_session_progress(
            users,
            "cristiano",
            "L00-Foundation",
            "SF-180N",
            {"correct": 8, "late": 1, "wrong": 1, "miss": 0, "avg_ae": 82.0},
        )
        progress = users["cristiano"]["progress"]
        self.assertEqual(progress["session_credits"], 0)
        self.assertIn("L01-Entry/A-T1/A.T1.C1", progress["unlocked_levels"])

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
        self.assertEqual(progress["current_level"], "L00-Foundation")
        self.assertNotIn("L01-Entry/A-T1/A.T1.C1", progress["unlocked_levels"])
        self.assertFalse(progress["challenge_results"]["L00-Foundation"]["passed"])
        self.assertEqual(progress["challenge_results"]["L00-Foundation"]["subdirectory"], "SF-30N")

    def test_sf180n_marks_entry_eligible_not_unlocked(self):
        users = self._player()
        stats = {"correct": 8, "late": 1, "wrong": 1, "miss": 0, "avg_ae": 82.0}
        apply_session_progress(users, "james", "L00-Foundation", "SF-180N", stats)
        progress = users["james"]["progress"]
        self.assertTrue(progress["challenge_results"]["L00-Foundation"]["passed"])
        self.assertIn("L01-Entry/A-T1/A.T1.C1", progress["eligible_levels"])
        self.assertNotIn("L01-Entry/A-T1/A.T1.C1", progress["unlocked_levels"])


if __name__ == "__main__":
    unittest.main()
