"""New player, Foundation through World Class. Writes a test report and an issue list.

The issue list is observation only. This file does not change unlock or booking rules.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("SIMUST_PUBLIC_MODE", "1")
os.environ.setdefault("SIMUST_SESSION_SECRET", "unlock-sim-secret")

import simust_progress  # noqa: E402
from app import (  # noqa: E402
    ALL_LEVELS,
    apply_session_progress,
    get_level_thresholds,
    get_next_level,
    _continue_target,
    _insert_reservation,
)

PLAYER_ID = "nova_start"
REPORT_PATH = os.path.join(ROOT, "unlock_to_worldclass_report.txt")
ISSUES_PATH = os.path.join(ROOT, "unlock_to_worldclass_issues.txt")

PASS_FOUNDATION = {"correct": 3, "late": 0, "wrong": 1, "miss": 0, "avg_ae": 70.0}
FAIL_FOUNDATION = {"correct": 2, "late": 0, "wrong": 2, "miss": 0, "avg_ae": 70.0}
PASS_SERIES = {"correct": 17, "late": 0, "wrong": 3, "miss": 0, "avg_ae": 80.0}
FAIL_SERIES_ACC = {"correct": 16, "late": 0, "wrong": 4, "miss": 0, "avg_ae": 80.0}
FAIL_SERIES_AE = {"correct": 17, "late": 0, "wrong": 3, "miss": 0, "avg_ae": 79.0}


def _accuracy(stats: dict) -> float:
    correct = int(stats.get("correct", 0) or 0)
    late = int(stats.get("late", 0) or 0)
    total = correct + late + int(stats.get("wrong", 0) or 0) + int(stats.get("miss", 0) or 0)
    return (correct + late) / total * 100.0 if total else 0.0


def _new_player() -> dict:
    return {
        "name": "Nova",
        "surname": "Start",
        "role": "player",
        "progress": simust_progress.default_progress(),
    }


class UnlockToWorldClassSim(unittest.TestCase):
    def test_new_player_reaches_world_class_only_by_score(self):
        users = {PLAYER_ID: _new_player()}
        progress = users[PLAYER_ID]["progress"]
        report = []
        issues = []

        self.assertEqual(progress["unlocked_playlists"], ["SF-30N"])
        self.assertEqual(progress["unlocked_levels"], ["L00-Foundation"])
        self.assertEqual(progress["current_level"], "L00-Foundation")
        self.assertEqual(progress["current_playlist"], "SF-30N")
        report.append("New player starts with Foundation SF-30N only. Every later set is locked.")

        booked = simust_progress.grant_reservation_credits(
            users, PLAYER_ID, 90, "nova-book-90", ALL_LEVELS
        )
        progress = users[PLAYER_ID]["progress"]
        self.assertEqual(booked["unlocked_now"], [])
        self.assertEqual(progress["unlocked_playlists"], ["SF-30N"])
        self.assertGreater(progress["session_credits"], 0)
        report.append(
            "A 90 minute booking added %s credit(s) and opened nothing."
            % progress["session_credits"]
        )
        if progress["session_credits"] and not booked["unlocked_now"]:
            issues.append(
                "Bookings still add session credits, and those credits are never spent. "
                "A 90 minute booking does not open the next set, which is correct, "
                "but the credit balance keeps growing on every booking."
            )

        self.assertFalse(
            apply_session_progress(
                users, PLAYER_ID, "L00-Foundation", "SF-30N", PASS_FOUNDATION, from_final=False
            )
            and "SF-60N" in users[PLAYER_ID]["progress"]["unlocked_playlists"]
        )
        self.assertNotIn("SF-60N", users[PLAYER_ID]["progress"]["unlocked_playlists"])
        report.append("Saving a passing SF-30N score before the final results video does not open SF-60N.")

        apply_session_progress(
            users, PLAYER_ID, "L00-Foundation", "SF-30N", FAIL_FOUNDATION, from_final=True
        )
        self.assertNotIn("SF-60N", users[PLAYER_ID]["progress"]["unlocked_playlists"])
        report.append(
            "SF-30N at %.0f%% accuracy and 70 efficiency stays on SF-30N."
            % _accuracy(FAIL_FOUNDATION)
        )

        short_ae = {"correct": 3, "late": 0, "wrong": 1, "miss": 0, "avg_ae": 69.0}
        apply_session_progress(
            users, PLAYER_ID, "L00-Foundation", "SF-30N", short_ae, from_final=True
        )
        self.assertNotIn("SF-60N", users[PLAYER_ID]["progress"]["unlocked_playlists"])
        report.append("SF-30N at 75% accuracy and 69 efficiency does not open SF-60N.")

        chain = ["SF-30N", "SF-60N", "SF-110N", "SF-180N"]
        for name in chain:
            ok, reason = simust_progress.can_play(
                users[PLAYER_ID]["progress"], "L00-Foundation", name
            )
            self.assertTrue(ok, reason)
            apply_session_progress(
                users, PLAYER_ID, "L00-Foundation", name, PASS_FOUNDATION, from_final=True
            )
            report.append(
                "Passed %s at %.0f%% accuracy and 70 efficiency."
                % (name, _accuracy(PASS_FOUNDATION))
            )
        progress = users[PLAYER_ID]["progress"]
        self.assertEqual(progress["unlocked_playlists"], chain)
        self.assertEqual(progress["passed_playlists"], chain)
        self.assertIn("L01-Entry/S1.T1", progress["unlocked_levels"])
        self.assertEqual(progress["current_level"], "L01-Entry/S1.T1")
        report.append("Passing SF-180N opens Entry A-T1. SF-30N through SF-180N stay open.")

        stored = (progress.get("challenge_results") or {}).get("L00-Foundation") or {}
        if stored.get("subdirectory") == "SF-180N" and "SF-30N" not in str(stored):
            issues.append(
                "Foundation scores are stored under one key, L00-Foundation. "
                "After SF-180N is passed, the saved score shows only SF-180N. "
                "The earlier SF-30N, SF-60N, and SF-110N scores are no longer in challenge_results. "
                "passed_playlists still lists every Foundation set that was passed."
            )

        # Entry skips S1.T5. Later bands keep S1.T5 then S2.T1..S2.T4 (S2.T5 skipped
        # except World Class, where S2.T4 opens S2.T5 as the final set).
        series_levels = [
            level for level in ALL_LEVELS
            if level != "L00-Foundation"
            and (
                not level.endswith("/S2.T5")
                or level.startswith("L05-")
            )
            and (
                not level.endswith("/S1.T5")
                or not level.startswith("L01-Entry")
            )
        ]
        self.assertEqual(series_levels[0], "L01-Entry/S1.T1")
        self.assertEqual(series_levels[-1], "L05-WorldClass/S2.T5")
        self.assertNotIn("L01-Entry/S1.T5", series_levels)
        self.assertIn("L02-Activated/S1.T5", series_levels)
        self.assertIn("L02-Activated/S2.T1", series_levels)
        self.assertNotIn("L02-Activated/S2.T5", series_levels)
        self.assertIn("L03-HighPerformance/S2.T1", series_levels)
        self.assertIn("L04-Elite/S2.T1", series_levels)
        self.assertEqual(get_next_level("L01-Entry/S1.T4"), "L02-Activated/S1.T1")
        self.assertEqual(get_next_level("L02-Activated/S1.T4"), "L02-Activated/S1.T5")
        self.assertEqual(get_next_level("L02-Activated/S1.T5"), "L02-Activated/S2.T1")
        self.assertEqual(get_next_level("L02-Activated/S2.T4"), "L03-HighPerformance/S1.T1")
        self.assertEqual(get_next_level("L03-HighPerformance/S2.T4"), "L04-Elite/S1.T1")
        self.assertEqual(get_next_level("L04-Elite/S2.T4"), "L05-WorldClass/S1.T1")
        self.assertEqual(get_next_level("L05-WorldClass/S2.T4"), "L05-WorldClass/S2.T5")

        for level in series_levels:
            progress = users[PLAYER_ID]["progress"]
            self.assertIn(level, progress["unlocked_levels"], level)
            nxt = get_next_level(level)
            if nxt:
                self.assertNotIn(nxt, progress["unlocked_levels"])
                apply_session_progress(
                    users, PLAYER_ID, level, "", FAIL_SERIES_ACC, from_final=True
                )
                self.assertNotIn(nxt, users[PLAYER_ID]["progress"]["unlocked_levels"])
                apply_session_progress(
                    users, PLAYER_ID, level, "", FAIL_SERIES_AE, from_final=True
                )
                self.assertNotIn(nxt, users[PLAYER_ID]["progress"]["unlocked_levels"])
                apply_session_progress(
                    users, PLAYER_ID, level, "", PASS_SERIES, from_final=False
                )
                self.assertNotIn(nxt, users[PLAYER_ID]["progress"]["unlocked_levels"])
            th_acc, th_ae = get_level_thresholds(level)
            self.assertEqual((th_acc, th_ae), (85, 80))
            apply_session_progress(
                users, PLAYER_ID, level, "", PASS_SERIES, from_final=True
            )
            progress = users[PLAYER_ID]["progress"]
            self.assertIn(level, progress["unlocked_levels"])
            if nxt:
                self.assertIn(nxt, progress["unlocked_levels"])
                self.assertEqual(progress["current_level"], nxt)
            report.append(
                "Passed %s at %.0f%% accuracy and 80 efficiency. Next is %s."
                % (level, _accuracy(PASS_SERIES), nxt or "none")
            )

        progress = users[PLAYER_ID]["progress"]
        self.assertEqual(progress["current_level"], "L05-WorldClass/S2.T5")
        self.assertEqual(get_next_level("L05-WorldClass/S2.T5"), None)
        report.append("The player is on World Class S2.T5. There is no set after it.")
        report.append("Unlocked levels: " + ", ".join(progress["unlocked_levels"]))

        # A later short final must not lock the set again.
        apply_session_progress(
            users, PLAYER_ID, "L05-WorldClass/S2.T5", "", FAIL_SERIES_ACC, from_final=True
        )
        progress = users[PLAYER_ID]["progress"]
        self.assertIn("L05-WorldClass/S2.T5", progress["unlocked_levels"])
        self.assertEqual(progress["current_level"], "L05-WorldClass/S2.T5")
        passed_flag = (progress.get("challenge_results") or {}).get("L05-WorldClass/S2.T5", {}).get("passed")
        report.append(
            "A later short World Class S2.T5 result leaves the set unlocked. "
            "The stored passed flag is %s." % passed_flag
        )
        if passed_flag is False:
            issues.append(
                "A later final result below the gate clears the stored passed flag. "
                "World Class S2.T5 stays unlocked, but challenge_results says passed is false. "
                "The latest score replaces the success flag instead of keeping the pass."
            )

        target_after_fail = _continue_target(progress)
        report.append(
            "After that short result the next play target is %s %s."
            % (target_after_fail["level"], target_after_fail["subdirectory"])
        )

        late_only = {"correct": 0, "late": 17, "wrong": 3, "miss": 0, "avg_ae": 80.0}
        if _accuracy(late_only) >= 85:
            issues.append(
                "Late finishes count toward accuracy. "
                "17 late and 3 wrong is %.0f%% accuracy, so it meets the 85%% gate "
                "with no correct finishes."
                % _accuracy(late_only)
            )

        aac_overrides = {"correct": 20, "late": 0, "wrong": 0, "miss": 0, "avg_ae": 90.0, "aac": 10}
        probe = {PLAYER_ID: _new_player()}
        apply_session_progress(
            probe, PLAYER_ID, "L00-Foundation", "SF-30N", aac_overrides, from_final=True
        )
        if "SF-60N" not in probe[PLAYER_ID]["progress"]["unlocked_playlists"]:
            issues.append(
                "When a result includes an aac value, that value replaces the count-based accuracy. "
                "20 correct actions with aac 10 do not open the next Foundation set."
            )

        self._reservation_scenarios(issues, report)
        self._write(REPORT_PATH, "Unlock simulation", report)
        self._write(ISSUES_PATH, "Issues found, not fixed", issues or ["No issues were recorded."])

    def _reservation_scenarios(self, issues, report):
        import app as app_module

        store = {"reservations": [], "users": {PLAYER_ID: _new_player()}}

        def load_reservations():
            return list(store["reservations"])

        def save_reservations(items):
            store["reservations"] = list(items)

        def load_users():
            return store["users"]

        def save_users(users):
            store["users"] = users

        app_module.load_reservations = load_reservations
        app_module.save_reservations = save_reservations
        app_module.load_users = load_users
        app_module.save_users = save_users

        start = datetime.now().replace(microsecond=0) + timedelta(days=3)
        end = start + timedelta(minutes=30)
        created = _insert_reservation(
            username=PLAYER_ID,
            display_name="Nova Start",
            start=start,
            end=end,
            duration=30,
            payment_status="paid",
            amount_eur=0,
            source="sim",
            field="A",
        )
        fields = sorted(item.get("field") for item in store["reservations"])
        self.assertEqual(fields, ["A"])
        report.append("A Foundation player booking Field A does not book Field B.")

        for level in ALL_LEVELS:
            if level.startswith("L04-Elite"):
                store["users"][PLAYER_ID]["progress"]["unlocked_levels"].append(level)
        store["users"][PLAYER_ID]["progress"]["current_level"] = "L04-Elite/S1.T1"
        start2 = start + timedelta(days=1)
        end2 = start2 + timedelta(minutes=30)
        created = _insert_reservation(
            username=PLAYER_ID,
            display_name="Nova Start",
            start=start2,
            end=end2,
            duration=30,
            payment_status="paid",
            amount_eur=0,
            source="sim",
            field="A",
        )
        by_field = {item.get("field"): item for item in store["reservations"] if item.get("start") == start2.isoformat(timespec="seconds")}
        self.assertEqual(set(by_field), {"A", "B"})
        self.assertTrue(by_field["A"].get("score_source"))
        self.assertFalse(by_field["B"].get("score_source"))
        report.append(
            "When the highest open set is Elite, booking Field A also books Field B. "
            "Field A keeps the score."
        )

        start3 = start2 + timedelta(days=1)
        end3 = start3 + timedelta(minutes=30)
        store["reservations"].append({
            "id": "taken-b",
            "player_id": "someone_else",
            "start": start3.isoformat(timespec="seconds"),
            "end": end3.isoformat(timespec="seconds"),
            "field": "B",
        })
        created = _insert_reservation(
            username=PLAYER_ID,
            display_name="Nova Start",
            start=start3,
            end=end3,
            duration=30,
            payment_status="paid",
            amount_eur=0,
            source="sim",
            field="A",
        )
        mine = [
            item for item in store["reservations"]
            if item.get("player_id") == PLAYER_ID and item.get("start") == start3.isoformat(timespec="seconds")
        ]
        self.assertEqual([item.get("field") for item in mine], ["A"])
        report.append(
            "If Field B is already taken, an Elite booking on Field A stays on Field A only."
        )
        if len(mine) == 1:
            issues.append(
                "Elite and World Class are supposed to use both fields. "
                "If the other field is already booked, the original booking is kept on one field "
                "and play can still be started without the second field."
            )
        if created.get("field") != "A":
            issues.append("The field that was booked first did not stay the score field.")

    def _write(self, path, title, lines):
        text = title + "\n" + ("=" * len(title)) + "\n\n" + "\n".join(lines) + "\n"
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)


if __name__ == "__main__":
    unittest.main()
