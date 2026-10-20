"""Player profile level, timed continue, Elite/WC dual booking, trend save."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("SIMUST_PUBLIC_MODE", "1")
os.environ.setdefault("SIMUST_SESSION_SECRET", "test-session-secret-not-for-production")

import simust_progress  # noqa: E402
from app import (  # noqa: E402
    ALL_LEVELS,
    _append_performance_trend_session,
    _clear_overlapping_field_bookings,
    _continue_target,
    _final_progress_field_ids,
    apply_session_progress,
)


class CurrentDevelopmentLevelTests(unittest.TestCase):
    def test_sync_uses_highest_unlocked(self):
        progress = simust_progress.default_progress()
        progress["unlocked_levels"] = [
            "L00-Foundation",
            "L01-Entry/S1.T1",
            "L01-Entry/S1.T2",
        ]
        progress["current_level"] = "L01-Entry/S1.T1"
        simust_progress.sync_current_development_level(progress, ALL_LEVELS)
        self.assertEqual(progress["current_level"], "L01-Entry/S1.T2")

    def test_fail_keeps_same_checkpoint_for_next_attempt(self):
        users = {
            "p1": {
                "role": "player",
                "progress": simust_progress.default_progress(),
            }
        }
        users["p1"]["progress"]["unlocked_levels"] = [
            "L00-Foundation",
            "L01-Entry/S1.T1",
        ]
        users["p1"]["progress"]["current_level"] = "L01-Entry/S1.T1"
        apply_session_progress(
            users,
            "p1",
            "L01-Entry/S1.T1",
            "",
            {"correct": 5, "late": 0, "wrong": 5, "miss": 0, "avg_ae": 50.0},
            from_final=True,
        )
        progress = users["p1"]["progress"]
        self.assertFalse(progress["challenge_results"]["L01-Entry/S1.T1"]["passed"])
        self.assertEqual(progress["current_level"], "L01-Entry/S1.T1")
        self.assertNotIn("L01-Entry/S1.T2", progress["unlocked_levels"])

    def test_pass_moves_current_to_next_unlocked(self):
        users = {
            "p1": {
                "role": "player",
                "progress": simust_progress.default_progress(),
            }
        }
        users["p1"]["progress"]["unlocked_levels"] = [
            "L00-Foundation",
            "L01-Entry/S1.T1",
        ]
        apply_session_progress(
            users,
            "p1",
            "L01-Entry/S1.T1",
            "",
            {"correct": 17, "late": 0, "wrong": 3, "miss": 0, "avg_ae": 80.0},
            from_final=True,
        )
        progress = users["p1"]["progress"]
        self.assertTrue(progress["challenge_results"]["L01-Entry/S1.T1"]["passed"])
        self.assertEqual(progress["current_level"], "L01-Entry/S1.T2")
        target = _continue_target(progress)
        self.assertEqual(target["level"], "L01-Entry/S1.T2")


class EliteBookingFreezeTests(unittest.TestCase):
    def test_clear_overlapping_removes_other_player(self):
        start = datetime(2026, 10, 20, 10, 0, 0)
        end = start + timedelta(minutes=30)
        bookings = [
            {
                "id": "other-b",
                "player_id": "rival",
                "field": "B",
                "start": start.isoformat(timespec="seconds"),
                "end": end.isoformat(timespec="seconds"),
            },
            {
                "id": "keep-a",
                "player_id": "hero",
                "field": "A",
                "start": start.isoformat(timespec="seconds"),
                "end": end.isoformat(timespec="seconds"),
            },
        ]
        remaining = _clear_overlapping_field_bookings(
            bookings, start, end, "B", keep_player_id="hero"
        )
        ids = [row["id"] for row in remaining]
        self.assertIn("keep-a", ids)
        self.assertNotIn("other-b", ids)


class PerformanceTrendSaveTests(unittest.TestCase):
    def test_final_appends_session_for_trend(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.PLAYER_REPORTS_DIR", tmp), patch(
                "app.load_users",
                return_value={"hero": {"name": "Hero", "surname": "One", "role": "player"}},
            ), patch("app.simust_push.push_session_async"):
                session_id = _append_performance_trend_session(
                    "hero",
                    "L01-Entry/S1.T1",
                    "",
                    {
                        "correct": 10,
                        "late": 0,
                        "wrong": 2,
                        "miss": 0,
                        "avg_ae": 82.0,
                        "aac": 83.3,
                    },
                    field="A",
                )
            self.assertTrue(session_id)
            index_path = os.path.join(tmp, "hero", "index.json")
            self.assertTrue(os.path.isfile(index_path))
            import json

            with open(index_path, "r", encoding="utf-8") as handle:
                index = json.load(handle)
            self.assertEqual(len(index), 1)
            self.assertTrue(index[0].get("final_results"))
            self.assertAlmostEqual(float(index[0].get("avg_ae") or 0), 82.0)


class DualFieldFinalSaveTests(unittest.TestCase):
    def test_independent_fields_both_save_even_if_score_field_is_a(self):
        fields = {
            "A": {"player_id": "jj", "level": "L00-Foundation"},
            "B": {"player_id": "christiano", "level": "L01-Entry/S1.T2"},
        }
        metrics = {"A": {"aac": 80}, "B": {"aac": 100}}
        self.assertEqual(
            _final_progress_field_ids(fields, metrics, "A"),
            ["A", "B"],
        )

    def test_elite_combined_only_saves_score_field(self):
        fields = {
            "A": {"player_id": "hero", "level": "L04-Elite/S1.T1"},
            "B": {"player_id": "hero", "level": "L04-Elite/S1.T1"},
        }
        metrics = {"A": {"aac": 90}, "B": {"aac": 90}}
        self.assertEqual(
            _final_progress_field_ids(fields, metrics, "A"),
            ["A"],
        )


if __name__ == "__main__":
    unittest.main()
