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
    apply_final_results_progress,
    apply_session_progress,
    get_next_level,
    propagate_level_status,
    write_simulation_fields,
    write_simulator_score_mode,
)


class ManualLockUnlockCurrentLevelTests(unittest.TestCase):
    def test_unlock_sets_current_to_highest_unlocked(self):
        progress = simust_progress.default_progress()
        progress["unlocked_levels"] = [
            "L00-Foundation",
            "L01-Entry/S1.T1",
            "L01-Entry/S1.T2",
        ]
        progress["current_level"] = "L01-Entry/S1.T1"
        simust_progress.sync_current_development_level(progress, ALL_LEVELS)
        self.assertEqual(progress["current_level"], "L01-Entry/S1.T2")

    def test_lock_drops_current_to_new_highest(self):
        progress = simust_progress.default_progress()
        progress["unlocked_levels"] = [
            "L00-Foundation",
            "L01-Entry/S1.T1",
            "L01-Entry/S1.T2",
        ]
        progress["current_level"] = "L01-Entry/S1.T2"
        progress["unlocked_levels"] = [
            "L00-Foundation",
            "L01-Entry/S1.T1",
        ]
        simust_progress.sync_current_development_level(progress, ALL_LEVELS)
        self.assertEqual(progress["current_level"], "L01-Entry/S1.T1")

    def test_lab_progress_replace_can_lock_on_host(self):
        existing = simust_progress.default_progress()
        existing["unlocked_levels"] = [
            "L00-Foundation",
            "L01-Entry/S1.T1",
            "L02-Activated/S1.T1",
        ]
        existing["current_level"] = "L02-Activated/S1.T1"
        incoming = simust_progress.default_progress()
        incoming["unlocked_levels"] = [
            "L00-Foundation",
            "L01-Entry/S1.T1",
        ]
        incoming["unlocked_playlists"] = ["SF-30N", "SF-60N"]
        incoming["manually_locked_levels"] = ["L02-Activated/S1.T1"]
        merged = simust_progress.apply_lab_progress(existing, incoming, ALL_LEVELS)
        self.assertNotIn("L02-Activated/S1.T1", merged["unlocked_levels"])
        self.assertEqual(merged["current_level"], "L01-Entry/S1.T1")

    def test_merge_progress_keeps_manual_lock_after_host_pull(self):
        lab = simust_progress.default_progress()
        lab["unlocked_levels"] = ["L00-Foundation", "L01-Entry/S1.T1"]
        lab["manually_locked_levels"] = ["L02-Activated/S2.T2"]
        lab["current_level"] = "L01-Entry/S1.T1"
        host = simust_progress.default_progress()
        host["unlocked_levels"] = [
            "L00-Foundation",
            "L01-Entry/S1.T1",
            "L02-Activated/S2.T2",
        ]
        host["current_level"] = "L02-Activated/S2.T2"
        merged = simust_progress.merge_progress(lab, host)
        self.assertIn("L02-Activated/S2.T2", merged["manually_locked_levels"])
        self.assertNotIn("L02-Activated/S2.T2", merged["unlocked_levels"])

    def test_open_level_skips_manually_locked(self):
        from app import _open_level

        progress = simust_progress.default_progress()
        progress["unlocked_levels"] = ["L00-Foundation", "L01-Entry/S1.T1"]
        progress["manually_locked_levels"] = ["L01-Entry/S1.T2"]
        _open_level(progress, "L01-Entry/S1.T2")
        self.assertNotIn("L01-Entry/S1.T2", progress["unlocked_levels"])

    def test_score_pass_clears_sticky_lock_and_opens_next(self):
        """Earned pass opens the next set even if it was admin-locked."""
        from app import _open_level

        progress = simust_progress.default_progress()
        progress["unlocked_levels"] = [
            "L00-Foundation",
            "L05-WorldClass/S2.T3",
        ]
        progress["manually_locked_levels"] = ["L05-WorldClass/S2.T4"]
        _open_level(progress, "L05-WorldClass/S2.T4", from_score_pass=True)
        self.assertIn("L05-WorldClass/S2.T4", progress["unlocked_levels"])
        self.assertNotIn("L05-WorldClass/S2.T4", progress["manually_locked_levels"])
        simust_progress.sync_current_development_level(progress, ALL_LEVELS)
        self.assertEqual(progress["current_level"], "L05-WorldClass/S2.T4")

        users = {
            "jj": {
                "role": "player",
                "progress": simust_progress.default_progress(),
            }
        }
        users["jj"]["progress"]["unlocked_levels"] = [
            "L00-Foundation",
            "L05-WorldClass/S2.T1",
            "L05-WorldClass/S2.T2",
            "L05-WorldClass/S2.T3",
        ]
        users["jj"]["progress"]["unlocked_playlists"] = list(
            simust_progress.FOUNDATION_PLAYLISTS
        )
        users["jj"]["progress"]["manually_locked_levels"] = ["L05-WorldClass/S2.T4"]
        apply_session_progress(
            users,
            "jj",
            "L05-WorldClass/S2.T3",
            "",
            {
                "aac": 85.0,
                "avg_ae": 80.0,
                "correct": 17,
                "late": 0,
                "wrong": 3,
                "miss": 0,
            },
            from_final=True,
        )
        self.assertTrue(
            users["jj"]["progress"]["challenge_results"]["L05-WorldClass/S2.T3"]["passed"]
        )
        self.assertIn("L05-WorldClass/S2.T4", users["jj"]["progress"]["unlocked_levels"])
        self.assertEqual(
            users["jj"]["progress"]["current_level"], "L05-WorldClass/S2.T4"
        )

    def test_foundation_sf_pass_opens_next_playlist(self):
        """SF-30N pass → SF-60N; omid does not level-up; SF-180N → Entry."""
        users = {
            "jj": {
                "role": "player",
                "progress": simust_progress.default_progress(),
            }
        }
        users["jj"]["progress"]["unlocked_playlists"] = ["SF-30N"]
        users["jj"]["progress"]["manually_locked_playlists"] = ["SF-60N"]
        apply_session_progress(
            users,
            "jj",
            "L00-Foundation",
            "SF-30N",
            {
                "aac": 100.0,
                "avg_ae": 86.0,
                "correct": 50,
                "late": 0,
                "wrong": 0,
                "miss": 0,
            },
            from_final=True,
        )
        prog = users["jj"]["progress"]
        self.assertIn("SF-60N", prog["unlocked_playlists"])
        self.assertNotIn("SF-60N", prog.get("manually_locked_playlists") or [])
        self.assertEqual(prog["current_playlist"], "SF-60N")

        # omid is an extra — must not unlock SF or Entry.
        before = list(prog["unlocked_playlists"])
        apply_session_progress(
            users,
            "jj",
            "L00-Foundation",
            "omid",
            {
                "aac": 100.0,
                "avg_ae": 90.0,
                "correct": 10,
                "late": 0,
                "wrong": 0,
                "miss": 0,
                "force_pass": True,
            },
            from_final=True,
        )
        self.assertEqual(users["jj"]["progress"]["unlocked_playlists"], before)
        self.assertNotIn(
            "L01-Entry/S1.T1", users["jj"]["progress"]["unlocked_levels"]
        )

        users["jj"]["progress"]["unlocked_playlists"] = list(
            simust_progress.FOUNDATION_PLAYLISTS
        )
        # Manual Lock on Entry must not block an earned SF-180N pass.
        users["jj"]["progress"]["manually_locked_levels"] = ["L01-Entry/S1.T1"]
        apply_session_progress(
            users,
            "jj",
            "L00-Foundation",
            "SF-180N",
            {
                "aac": 100.0,
                "avg_ae": 86.0,
                "correct": 50,
                "late": 0,
                "wrong": 0,
                "miss": 0,
            },
            from_final=True,
        )
        self.assertIn("L01-Entry/S1.T1", users["jj"]["progress"]["unlocked_levels"])
        self.assertNotIn(
            "L01-Entry/S1.T1",
            users["jj"]["progress"].get("manually_locked_levels") or [],
        )
        self.assertEqual(users["jj"]["progress"]["current_level"], "L01-Entry/S1.T1")


class Mode2S1T3UnlockTests(unittest.TestCase):
    def test_mode2_low_series_ae_does_not_fake_unlock(self):
        """Final AE stays the series average; Mode 2 must not floor it to the gate."""
        users = {
            "jj": {
                "name": "JJ",
                "role": "player",
                "progress": simust_progress.default_progress(),
            }
        }
        users["jj"]["progress"]["unlocked_levels"] = [
            "L00-Foundation",
            "L05-WorldClass/S1.T1",
            "L05-WorldClass/S1.T2",
            "L05-WorldClass/S1.T3",
        ]
        users["jj"]["progress"]["unlocked_playlists"] = list(
            simust_progress.FOUNDATION_PLAYLISTS
        )
        users["jj"]["progress"]["current_level"] = "L05-WorldClass/S1.T3"
        fields_payload = {
            "score_field": "A",
            "level": "L05-WorldClass/S1.T3",
            "fields": {
                "A": {
                    "player_id": "jj",
                    "level": "L05-WorldClass/S1.T3",
                    "subdirectory": "",
                },
                "B": {
                    "player_id": "__sim_B__",
                    "level": "L05-WorldClass/S1.T3",
                    "subdirectory": "",
                    "simulated": True,
                },
            },
        }
        metrics = {
            "A": {
                "aac": 100.0,
                "avg_ae": 64.0,
                "correct": 10,
                "late": 0,
                "wrong": 0,
                "miss": 0,
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            pf = os.path.join(tmp, "players_fields.json")
            with open(pf, "w", encoding="utf-8") as handle:
                import json

                json.dump(fields_payload, handle)
            with patch("app.SIMUST_PLAYER_DIRECTORY", tmp), patch(
                "app.PLAYER_REPORTS_DIR", tmp
            ), patch("app.load_users", return_value=users), patch(
                "app.save_users"
            ), patch("app._booking_seconds_left", return_value=600), patch(
                "app.simust_push.push_session_async"
            ):
                write_simulation_fields({"A": False, "B": True})
                write_simulator_score_mode(2)
                info = apply_final_results_progress(
                    metrics, score_field="A", save_reports=False
                )
        self.assertFalse(info.get("passed"))
        self.assertAlmostEqual(
            users["jj"]["progress"]["challenge_results"]["L05-WorldClass/S1.T3"]["ae"],
            64.0,
        )
        self.assertNotIn(
            "L05-WorldClass/S1.T4", users["jj"]["progress"]["unlocked_levels"]
        )

    def test_mode2_unlocks_when_series_average_meets_gate(self):
        """Mode 2 unlocks only when the true 5-test average AE meets the gate."""
        users = {
            "jj": {
                "name": "JJ",
                "role": "player",
                "progress": simust_progress.default_progress(),
            }
        }
        users["jj"]["progress"]["unlocked_levels"] = [
            "L00-Foundation",
            "L05-WorldClass/S2.T5",
        ]
        users["jj"]["progress"]["unlocked_playlists"] = list(
            simust_progress.FOUNDATION_PLAYLISTS
        )
        users["jj"]["progress"]["current_level"] = "L05-WorldClass/S2.T5"
        fields_payload = {
            "score_field": "A",
            "level": "L05-WorldClass/S2.T5",
            "fields": {
                "A": {
                    "player_id": "jj",
                    "level": "L05-WorldClass/S2.T5",
                    "subdirectory": "",
                },
                "B": {
                    "player_id": "__sim_B__",
                    "level": "L05-WorldClass/S2.T5",
                    "subdirectory": "",
                    "simulated": True,
                },
            },
        }
        # True average of five strong tests (what good Mode 2 sim play earns).
        metrics = {
            "A": {
                "aac": 100.0,
                "avg_ae": 84.0,
                "correct": 12,
                "late": 0,
                "wrong": 0,
                "miss": 0,
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            pf = os.path.join(tmp, "players_fields.json")
            with open(pf, "w", encoding="utf-8") as handle:
                import json

                json.dump(fields_payload, handle)
            with patch("app.SIMUST_PLAYER_DIRECTORY", tmp), patch(
                "app.PLAYER_REPORTS_DIR", tmp
            ), patch("app.load_users", return_value=users), patch(
                "app.save_users"
            ), patch("app._booking_seconds_left", return_value=600), patch(
                "app.simust_push.push_session_async"
            ):
                write_simulation_fields({"A": True, "B": True})
                write_simulator_score_mode(2)
                info = apply_final_results_progress(
                    metrics, score_field="A", save_reports=False
                )
        self.assertTrue(info.get("passed"))
        self.assertAlmostEqual(
            users["jj"]["progress"]["challenge_results"]["L05-WorldClass/S2.T5"]["ae"],
            84.0,
        )
        # Last set: pass and do not loop forever.
        self.assertFalse(info.get("continue_play"))

    def test_final_unlocks_even_if_admin_test_skipped_can_play(self):
        users = {
            "jj": {
                "name": "JJ",
                "role": "player",
                "progress": simust_progress.default_progress(),
            }
        }
        # Only through S1.T2 — admin test started S1.T3 anyway.
        users["jj"]["progress"]["unlocked_levels"] = [
            "L00-Foundation",
            "L01-Entry/S1.T1",
            "L01-Entry/S1.T2",
        ]
        users["jj"]["progress"]["unlocked_playlists"] = list(
            simust_progress.FOUNDATION_PLAYLISTS
        )
        ok = apply_session_progress(
            users,
            "jj",
            "L01-Entry/S1.T3",
            "",
            {
                "aac": 90.0,
                "avg_ae": 85.0,
                "correct": 9,
                "late": 0,
                "wrong": 1,
                "miss": 0,
            },
            from_final=True,
        )
        self.assertTrue(ok)
        self.assertIn("L01-Entry/S1.T3", users["jj"]["progress"]["unlocked_levels"])
        self.assertIn("L01-Entry/S1.T4", users["jj"]["progress"]["unlocked_levels"])


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
        # Request may say Field B finished; booked score_field A still wins.
        payload = {"score_field": "A", "level": "L04-Elite/S1.T1"}
        self.assertEqual(
            _final_progress_field_ids(fields, metrics, "B", payload=payload),
            ["A"],
        )

    def test_worldclass_s2_t3_unlocks_from_field_a_only(self):
        """Player on A: AE>=75 on A unlocks S2.T4; Field B scores ignored."""
        users = {
            "hero": {
                "name": "Hero",
                "role": "player",
                "progress": simust_progress.default_progress(),
            }
        }
        users["hero"]["progress"]["unlocked_levels"] = [
            "L00-Foundation",
            "L05-WorldClass/S2.T1",
            "L05-WorldClass/S2.T2",
            "L05-WorldClass/S2.T3",
        ]
        users["hero"]["progress"]["unlocked_playlists"] = list(
            simust_progress.FOUNDATION_PLAYLISTS
        )
        users["hero"]["progress"]["current_level"] = "L05-WorldClass/S2.T3"
        fields_payload = {
            "score_field": "A",
            "level": "L05-WorldClass/S2.T3",
            "fields": {
                "A": {
                    "player_id": "hero",
                    "level": "L05-WorldClass/S2.T3",
                    "subdirectory": "",
                },
                "B": {
                    "player_id": "hero",
                    "level": "L05-WorldClass/S2.T3",
                    "subdirectory": "",
                },
            },
        }
        # A meets gate; B is below — if B were used, unlock would fail.
        metrics = {
            "A": {
                "aac": 90.0,
                "avg_ae": 80.0,
                "correct": 9,
                "late": 0,
                "wrong": 1,
                "miss": 0,
            },
            "B": {
                "aac": 40.0,
                "avg_ae": 30.0,
                "correct": 4,
                "late": 0,
                "wrong": 6,
                "miss": 0,
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            pf = os.path.join(tmp, "players_fields.json")
            with open(pf, "w", encoding="utf-8") as handle:
                import json

                json.dump(fields_payload, handle)
            with patch("app.SIMUST_PLAYER_DIRECTORY", tmp), patch(
                "app.PLAYER_REPORTS_DIR", tmp
            ), patch("app.load_users", return_value=users), patch(
                "app.save_users"
            ), patch("app._booking_seconds_left", return_value=600), patch(
                "app.simust_push.push_session_async"
            ):
                # Even if caller claims score_field=B, booked A must unlock.
                info = apply_final_results_progress(
                    metrics, score_field="B", save_reports=False
                )
        self.assertTrue(info.get("passed"))
        self.assertEqual(info.get("score_field"), "A")
        self.assertEqual(info.get("level"), "L05-WorldClass/S2.T4")
        self.assertIn(
            "L05-WorldClass/S2.T4", users["hero"]["progress"]["unlocked_levels"]
        )
        self.assertEqual(
            users["hero"]["progress"]["current_level"], "L05-WorldClass/S2.T4"
        )
        self.assertEqual(
            users["hero"]["progress"]["challenge_results"]["L05-WorldClass/S2.T3"]["ae"],
            80.0,
        )

    def test_single_field_final_only_targets_that_field(self):
        fields = {
            "A": {"player_id": "jj", "level": "L00-Foundation"},
            "B": {"player_id": "christiano", "level": "L01-Entry/S1.T2"},
        }
        # Field A finished while B is still playing — only A's metrics arrive.
        self.assertEqual(
            _final_progress_field_ids(fields, {"A": {"aac": 70}}, "A"),
            ["A"],
        )

    def test_apply_final_writes_trend_when_save_reports(self):
        users = {
            "jj": {
                "name": "JJ",
                "surname": "Test",
                "role": "player",
                "progress": simust_progress.default_progress(),
            },
            "christiano": {
                "name": "Christiano",
                "surname": "Test",
                "role": "player",
                "progress": simust_progress.default_progress(),
            },
        }
        users["jj"]["progress"]["unlocked_levels"] = ["L00-Foundation"]
        users["jj"]["progress"]["current_level"] = "L00-Foundation"
        users["christiano"]["progress"]["unlocked_levels"] = [
            "L00-Foundation",
            "L01-Entry/S1.T2",
        ]
        users["christiano"]["progress"]["current_level"] = "L01-Entry/S1.T2"
        fields_payload = {
            "score_field": "A",
            "fields": {
                "A": {"player_id": "jj", "level": "L00-Foundation", "subdirectory": ""},
                "B": {
                    "player_id": "christiano",
                    "level": "L01-Entry/S1.T2",
                    "subdirectory": "",
                },
            },
        }
        metrics = {
            "A": {
                "aac": 80.0,
                "avg_ae": 75.0,
                "correct": 8,
                "late": 0,
                "wrong": 2,
                "miss": 0,
            },
            "B": {
                "aac": 90.0,
                "avg_ae": 85.0,
                "correct": 9,
                "late": 0,
                "wrong": 1,
                "miss": 0,
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            pf = os.path.join(tmp, "players_fields.json")
            with open(pf, "w", encoding="utf-8") as handle:
                import json

                json.dump(fields_payload, handle)
            with patch("app.SIMUST_PLAYER_DIRECTORY", tmp), patch(
                "app.PLAYER_REPORTS_DIR", tmp
            ), patch("app.load_users", return_value=users), patch(
                "app.save_users"
            ), patch("app._booking_seconds_left", return_value=0), patch(
                "app.simust_push.push_session_async"
            ):
                apply_final_results_progress(metrics, score_field="A", save_reports=True)
            for pid in ("jj", "christiano"):
                index_path = os.path.join(tmp, pid, "index.json")
                self.assertTrue(os.path.isfile(index_path), pid)
                import json

                with open(index_path, "r", encoding="utf-8") as handle:
                    index = json.load(handle)
                self.assertEqual(len(index), 1, pid)
                self.assertTrue(index[0].get("final_results"), pid)

    def test_propagate_level_status_updates_players_fields_and_progress_json(self):
        progress = simust_progress.default_progress()
        progress["unlocked_levels"] = [
            "L00-Foundation",
            "L01-Entry/S1.T1",
            "L01-Entry/S1.T2",
        ]
        progress["current_level"] = "L01-Entry/S1.T1"
        simust_progress.sync_current_development_level(progress, ALL_LEVELS)
        fields_payload = {
            "level": "L01-Entry/S1.T1",
            "levels": {"A": "L01-Entry/S1.T1", "B": "L00-Foundation"},
            "players": [
                {
                    "player_id": "jj",
                    "field": "A",
                    "level": "L01-Entry/S1.T1",
                    "subdirectory": "",
                }
            ],
            "fields": {
                "A": {
                    "player_id": "jj",
                    "level": "L01-Entry/S1.T1",
                    "subdirectory": "",
                    "directory": "old-a",
                },
                "B": {
                    "player_id": "other",
                    "level": "L00-Foundation",
                    "subdirectory": "SF-30N",
                    "directory": "old-b",
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            pf = os.path.join(tmp, "players_fields.json")
            with open(pf, "w", encoding="utf-8") as handle:
                import json

                json.dump(fields_payload, handle)
            with patch("app.SIMUST_PLAYER_DIRECTORY", tmp), patch(
                "app.PLAYER_REPORTS_DIR", tmp
            ):
                target = propagate_level_status("jj", progress)
            self.assertEqual(target["level"], "L01-Entry/S1.T2")
            import json

            with open(pf, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(payload["fields"]["A"]["level"], "L01-Entry/S1.T2")
            self.assertEqual(payload["level"], "L01-Entry/S1.T2")
            self.assertEqual(payload["levels"]["A"], "L01-Entry/S1.T2")
            self.assertEqual(payload["players"][0]["level"], "L01-Entry/S1.T2")
            # Other player's field left alone
            self.assertEqual(payload["fields"]["B"]["level"], "L00-Foundation")
            with open(os.path.join(tmp, "jj", "progress.json"), "r", encoding="utf-8") as handle:
                stamp = json.load(handle)
            self.assertEqual(stamp["current_level"], "L01-Entry/S1.T2")
            with open(os.path.join(tmp, "current_level.txt"), "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read().strip(), "L01-Entry/S1.T2")

    def test_apply_final_skips_reports_when_disabled(self):
        users = {
            "jj": {
                "name": "JJ",
                "role": "player",
                "progress": simust_progress.default_progress(),
            },
        }
        users["jj"]["progress"]["unlocked_levels"] = ["L00-Foundation"]
        users["jj"]["progress"]["current_level"] = "L00-Foundation"
        fields_payload = {
            "fields": {
                "A": {"player_id": "jj", "level": "L00-Foundation", "subdirectory": ""},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            pf = os.path.join(tmp, "players_fields.json")
            with open(pf, "w", encoding="utf-8") as handle:
                import json

                json.dump(fields_payload, handle)
            with patch("app.SIMUST_PLAYER_DIRECTORY", tmp), patch(
                "app.PLAYER_REPORTS_DIR", tmp
            ), patch("app.load_users", return_value=users), patch(
                "app.save_users"
            ), patch("app._booking_seconds_left", return_value=0), patch(
                "app.simust_push.push_session_async"
            ) as push:
                apply_final_results_progress(
                    {"A": {"aac": 80, "avg_ae": 70, "correct": 8, "wrong": 2}},
                    score_field="A",
                    save_reports=False,
                )
            # Level stamp still updates; trend session files stay skipped.
            self.assertTrue(os.path.isfile(os.path.join(tmp, "jj", "progress.json")))
            self.assertFalse(os.path.isfile(os.path.join(tmp, "jj", "index.json")))
            push.assert_not_called()


if __name__ == "__main__":
    unittest.main()
