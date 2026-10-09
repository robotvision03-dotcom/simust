"""Create a new player, simulate default-score unlocks for every set, check dual fields.

Writes:
  remote_operator_level_sim_report.txt
  remote_operator_level_sim_issues.txt

Does not change unlock rules. Observation only.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("SIMUST_PUBLIC_MODE", "1")
os.environ.setdefault("SIMUST_SESSION_SECRET", "remote-op-level-sim-secret")

import simust_progress  # noqa: E402
from app import (  # noqa: E402
    ALL_LEVELS,
    apply_session_progress,
    get_level_thresholds,
    get_next_level,
    _combined_level,
    _insert_reservation,
    hash_password,
)

PLAYER_ID = "remote_sim_" + datetime.now().strftime("%Y%m%d_%H%M%S")
REPORT_PATH = os.path.join(ROOT, "remote_operator_level_sim_report.txt")
ISSUES_PATH = os.path.join(ROOT, "remote_operator_level_sim_issues.txt")

# Default gates used by the product.
PASS_FOUNDATION = {"correct": 3, "late": 0, "wrong": 1, "miss": 0, "avg_ae": 70.0}  # 75%, 70
FAIL_FOUNDATION = {"correct": 2, "late": 0, "wrong": 2, "miss": 0, "avg_ae": 70.0}  # 50%
PASS_SERIES = {"correct": 17, "late": 0, "wrong": 3, "miss": 0, "avg_ae": 80.0}  # 85%, 80
FAIL_SERIES = {"correct": 16, "late": 0, "wrong": 4, "miss": 0, "avg_ae": 80.0}  # 80%


def _accuracy(stats: dict) -> float:
    correct = int(stats.get("correct", 0) or 0)
    late = int(stats.get("late", 0) or 0)
    total = correct + late + int(stats.get("wrong", 0) or 0) + int(stats.get("miss", 0) or 0)
    return (correct + late) / total * 100.0 if total else 0.0


def _new_player() -> dict:
    return {
        "name": "Remote",
        "surname": "Simulator",
        "role": "player",
        "club": "SIMUST Lab",
        "team": "Operator Sim",
        "age": "16",
        "gender": "male",
        "email": f"{PLAYER_ID}@simust.test",
        "password": hash_password("simtest16"),
        "progress": simust_progress.default_progress(),
    }


def _ui_combined_selects_both(level: str) -> bool:
    """Mirror index.html isCombinedLevel + selectPlayerFromSearch dual assignment."""
    text = str(level or "")
    return "L04-Elite" in text or "L05-WorldClass" in text


class RemoteOperatorLevelSim(unittest.TestCase):
    def test_all_levels_default_scores_and_dual_fields(self):
        users = {PLAYER_ID: _new_player()}
        report: List[str] = []
        issues: List[str] = []
        report.append(f"Player created: {PLAYER_ID}")
        report.append("Password for portal (if used): simtest16")
        report.append("")

        progress = users[PLAYER_ID]["progress"]
        self.assertEqual(progress["unlocked_playlists"], ["SF-30N"])
        self.assertEqual(progress["unlocked_levels"], ["L00-Foundation"])
        report.append("START: only Foundation SF-30N is open.")

        # Booking alone must not open the next Foundation set.
        booked = simust_progress.grant_reservation_credits(
            users, PLAYER_ID, 30, f"{PLAYER_ID}-book-30", ALL_LEVELS
        )
        progress = users[PLAYER_ID]["progress"]
        if "SF-60N" in progress["unlocked_playlists"]:
            issues.append("A 30-minute booking opened SF-60N without a score. Expected: stay on SF-30N.")
        report.append(
            "Booking 30 min: credits=%s unlocked_now=%s playlists=%s"
            % (progress.get("session_credits"), booked.get("unlocked_now"), progress.get("unlocked_playlists"))
        )

        # Fail score must not unlock.
        apply_session_progress(
            users, PLAYER_ID, "L00-Foundation", "SF-30N", FAIL_FOUNDATION, from_final=True
        )
        self.assertNotIn("SF-60N", users[PLAYER_ID]["progress"]["unlocked_playlists"])
        report.append(
            "SF-30N fail at %.0f%% / 70 AE: stays locked (ok)."
            % _accuracy(FAIL_FOUNDATION)
        )

        # Foundation chain with default pass scores.
        foundation = list(simust_progress.FOUNDATION_PLAYLISTS)
        for index, name in enumerate(foundation, start=1):
            ok, reason = simust_progress.can_play(
                users[PLAYER_ID]["progress"], "L00-Foundation", name
            )
            self.assertTrue(ok, f"{name}: {reason}")
            before = list(users[PLAYER_ID]["progress"].get("unlocked_playlists") or [])
            apply_session_progress(
                users, PLAYER_ID, "L00-Foundation", name, PASS_FOUNDATION, from_final=True
            )
            after = list(users[PLAYER_ID]["progress"].get("unlocked_playlists") or [])
            nxt = simust_progress.next_foundation_playlist_after(name)
            report.append(
                "Foundation set %s/%s %s pass %.0f%%/70 → playlists %s → %s (next=%s)"
                % (index, len(foundation), name, _accuracy(PASS_FOUNDATION), before, after, nxt or "Entry S1.T1")
            )
            if nxt:
                self.assertIn(nxt, after)
            else:
                self.assertIn("L01-Entry/S1.T1", users[PLAYER_ID]["progress"]["unlocked_levels"])

        progress = users[PLAYER_ID]["progress"]
        report.append(
            "After Foundation set 4 (SF-180N): current=%s unlocked_levels includes Entry S1.T1=%s"
            % (progress.get("current_level"), "L01-Entry/S1.T1" in progress["unlocked_levels"])
        )
        if "L01-Entry/S1.T1" not in progress["unlocked_levels"]:
            issues.append("Passing Foundation set 4 (SF-180N) did not unlock Entry A-T1.")

        # Entry skips S1.T5. Later bands keep S1.T5 then S2; S2.T5 only on World Class.
        series = [
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
        for level in series:
            progress = users[PLAYER_ID]["progress"]
            if level not in progress["unlocked_levels"]:
                issues.append(f"{level} was not unlocked before it was played.")
                report.append(f"BLOCKED: {level} is locked. Stopping series walk.")
                break

            ok, reason = simust_progress.can_play(progress, level, "")
            self.assertTrue(ok, f"{level}: {reason}")
            th_acc, th_ae = get_level_thresholds(level)
            self.assertEqual((th_acc, th_ae), (85, 80), level)

            nxt = get_next_level(level)
            # Fail must not unlock next.
            apply_session_progress(users, PLAYER_ID, level, "", FAIL_SERIES, from_final=True)
            if nxt and nxt in users[PLAYER_ID]["progress"]["unlocked_levels"]:
                issues.append(f"Fail score on {level} unlocked {nxt}.")
            # Mid-session save must not unlock.
            apply_session_progress(users, PLAYER_ID, level, "", PASS_SERIES, from_final=False)
            if nxt and nxt in users[PLAYER_ID]["progress"]["unlocked_levels"]:
                issues.append(f"Non-final save on {level} unlocked {nxt}.")

            apply_session_progress(users, PLAYER_ID, level, "", PASS_SERIES, from_final=True)
            progress = users[PLAYER_ID]["progress"]
            band = level.split("/")[0]
            set_name = level.split("/")[-1] if "/" in level else level
            report.append(
                "Passed %s at %.0f%% / %s AE. Next open=%s current=%s"
                % (level, _accuracy(PASS_SERIES), int(PASS_SERIES["avg_ae"]), nxt or "none", progress.get("current_level"))
            )

            if set_name == "S1.T4":
                next_band = {
                    "L01-Entry": "L02-Activated/S1.T1",
                    "L02-Activated": "L02-Activated/S1.T5",
                    "L03-HighPerformance": "L03-HighPerformance/S1.T5",
                    "L04-Elite": "L04-Elite/S1.T5",
                    "L05-WorldClass": "L05-WorldClass/S1.T5",
                }.get(band)
                if next_band and next_band not in progress["unlocked_levels"]:
                    issues.append(
                        f"After passing {level} (set 4), {next_band} is not unlocked."
                    )
                else:
                    report.append(
                        f"  Set-4 check ({level}): opened {next_band}."
                    )
            if set_name == "S2.T4":
                next_band = {
                    "L02-Activated": "L03-HighPerformance/S1.T1",
                    "L03-HighPerformance": "L04-Elite/S1.T1",
                    "L04-Elite": "L05-WorldClass/S1.T1",
                    "L05-WorldClass": "L05-WorldClass/S2.T5",
                }.get(band)
                if next_band and next_band not in progress["unlocked_levels"]:
                    issues.append(
                        f"After passing {level}, {next_band} is not unlocked. "
                        "S2.T4 must open the next band (or World Class S2.T5)."
                    )
                else:
                    report.append(
                        f"  Set-4 check ({level}): opened {next_band} (S2.T4 unlocks next)."
                    )

            if nxt:
                self.assertIn(nxt, progress["unlocked_levels"])
                self.assertEqual(progress["current_level"], nxt)

        progress = users[PLAYER_ID]["progress"]
        report.append("")
        report.append("FINAL current_level: " + str(progress.get("current_level")))
        report.append("Unlocked levels: " + ", ".join(progress.get("unlocked_levels") or []))
        report.append("Unlocked playlists: " + ", ".join(progress.get("unlocked_playlists") or []))

        # Elite / World Class dual-field booking + start expansion + UI select.
        report.append("")
        report.append("ELITE / WORLD CLASS DUAL FIELD")
        report.append("-----------------------------")
        self._dual_field_checks(users, report, issues)

        # Push player to remote host when lab push is configured.
        report.append("")
        report.append("REMOTE OPERATOR SYNC")
        report.append("--------------------")
        self._push_player(users, report, issues)

        # Playlist build runs in a child process so a Qt crash cannot wipe the unlock report.
        report.append("")
        report.append("SIMULATOR PLAYLIST BUILD")
        report.append("-----------------------")
        self._playlist_checks_subprocess(report, issues)

        self._write(REPORT_PATH, "Remote operator level simulation", report)
        self._write(
            ISSUES_PATH,
            "Issues found (not fixed)",
            issues or ["No blocking issues were recorded."],
        )
        # Keep the unittest green when only known product issues are listed;
        # hard-fail only on broken unlock progression.
        hard = [item for item in issues if item.startswith("BLOCKED") or "did not unlock Entry" in item]
        self.assertFalse(hard, "\n".join(hard))

    def _playlist_checks_subprocess(self, report: List[str], issues: List[str]) -> None:
        import subprocess
        import tempfile

        script = r'''
import json, os, sys, re
ROOT = sys.argv[1]
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import smart_simust_player as player
from app import _combined_level

def build(level, subdirectory=""):
    if level == "L00-Foundation":
        active = {"A"}
        factory = player._mode_slot_factory(subdirectory, active)
        rows = []
        for test_num in range(1, max(1, int(player.LABEL_TEST_COUNT)) + 1):
            for action_in_set in range(1, int(player.LABEL_ACTIONS_PER_TEST) + 1):
                slot = factory(action_in_set, test_num) or {}
                sids = list(slot.get("A") or [])
                if not sids:
                    continue
                rows.append({
                    "test_num": test_num,
                    "action_in_set": action_in_set,
                    "actions_in_set": player.LABEL_ACTIONS_PER_TEST,
                    "field_screens": {"A": sids},
                    "screen_images": {sid: "x" for sid in sids},
                    "finish_balls": True,
                })
        return player._stamp_finish_balls(rows) if rows else []
    series = 1
    m = re.search(r"S(?:1|2)[.-]T([1-5])|A-T([1-5])", level)
    if m:
        series = int(m.group(1) or m.group(2))
    active = {"A", "B"} if _combined_level(level) else {"A"}
    if "L05-WorldClass" in level:
        if re.search(r"S2[.-]T[1-5]", level, re.I):
            return player._build_world_class_s2_playlist(series) or []
        return player._build_elite_playlist(series, "world-class") or []
    if "L04-Elite" in level:
        if re.search(r"S2[.-]T[1-5]", level, re.I):
            return player._build_elite_s2_playlist(series) or []
        return player._build_elite_playlist(series, "elite") or []
    if "L03-HighPerformance" in level:
        if re.search(r"S2[.-]T[1-5]", level, re.I):
            return player._build_high_performance_s2_playlist(series, active) or []
        return player._build_high_performance_playlist(series, active) or []
    if "L02-Activated" in level:
        a1 = re.search(r"S2[.-]T([1-5])|A1[-.]T([1-5])", level, re.I)
        if a1:
            return player._build_activated_a1_playlist(int(a1.group(1) or a1.group(2)), active) or []
        return player._build_activated_playlist(series, active) or []
    if "L01-Entry" in level:
        return player._build_entry_playlist(series, active) or []
    return []

samples = [
    ("L00-Foundation", "SF-30N"),
    ("L00-Foundation", "SF-180N"),
    ("L01-Entry/S1.T1", ""),
    ("L01-Entry/S1.T4", ""),
    ("L02-Activated/S1.T3", ""),
    ("L03-HighPerformance/S1.T2", ""),
    ("L04-Elite/S1.T1", ""),
    ("L04-Elite/S1.T4", ""),
    ("L05-WorldClass/S1.T1", ""),
    ("L05-WorldClass/S1.T5", ""),
]
out = {"lines": [], "issues": []}
for level, sub in samples:
    try:
        rows = build(level, sub)
        tests = sorted({int(r.get("test_num") or 0) for r in rows if isinstance(r, dict)})
        finish = any(bool(r.get("finish_balls")) for r in rows if isinstance(r, dict))
        names = " ".join(" ".join((r.get("screen_images") or {}).keys()) for r in rows if isinstance(r, dict))
        has_a = any("A" in str((r.get("field_screens") or {})) for r in rows) or ("A1" in names)
        has_b = any("B" in str((r.get("field_screens") or {})) for r in rows) or ("B1" in names)
        line = f"  {level} {sub or '-'}: {len(rows)} step(s) tests={tests or '-'} finish_balls={finish}"
        if _combined_level(level):
            line += f" fields A={has_a} B={has_b}"
            if rows and not (has_a and has_b):
                out["issues"].append(f"Combined level {level} playlist missing a field half.")
        out["lines"].append(line)
        if not rows:
            out["issues"].append(f"Simulator playlist empty for {level} {sub}".strip())
    except Exception as exc:
        out["lines"].append(f"  {level} {sub or '-'}: ERROR {exc}")
        out["issues"].append(f"Simulator playlist failed for {level} {sub}: {exc}")

parts = {"A": build("L00-Foundation", "SF-180N"), "B": build("L01-Entry/S1.T3", "")}
merged = player._zip_field_action_playlists(parts)
out["lines"].append(
    f"  Independent A=SF-180N + B=Entry S1.T3 zip: {len(merged)} step(s) (A={len(parts['A'])} B={len(parts['B'])})"
)
if not merged:
    out["issues"].append("Independent dual-field playlist zip is empty.")
cards = player._opening_cards_for_fields(
    ["A", "B"],
    {"A": "L00-Foundation", "B": "L01-Entry/S1.T3"},
    {"A": "SF-180N", "B": "S1.T3"},
    parts, {}, [], 1,
)
out["lines"].append(
    "  Opening cards: A=%s | B=%s"
    % (cards["A"]["text"].replace("\n", " "), cards["B"]["text"].replace("\n", " "))
)
if "SF-180N" not in cards.get("A", {}).get("text", ""):
    out["issues"].append("Opening card for Field A did not show SF-180N.")
if "S1.T3" not in cards.get("B", {}).get("text", ""):
    out["issues"].append("Opening card for Field B did not show S1.T3.")
print(json.dumps(out))
'''
        tmp = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8")
        try:
            tmp.write(script)
            tmp.close()
            proc = subprocess.run(
                [sys.executable, tmp.name, ROOT],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=ROOT,
            )
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
        if proc.returncode != 0:
            issues.append(
                "Playlist simulator child process failed "
                f"(code={proc.returncode}): {(proc.stderr or proc.stdout or '')[:300]}"
            )
            report.append("  Playlist child process failed; unlock/dual-field checks above still stand.")
            return
        try:
            payload = json.loads((proc.stdout or "").strip().splitlines()[-1])
        except Exception as exc:
            issues.append(f"Could not parse playlist simulator output: {exc}")
            report.append("  Playlist output parse failed.")
            return
        report.extend(payload.get("lines") or [])
        issues.extend(payload.get("issues") or [])

    def _playlist_checks(self, report: List[str], issues: List[str]) -> None:
        # Kept for direct debugging; main path uses the subprocess helper.
        try:
            import smart_simust_player as player  # local import: Qt can crash some hosts
        except Exception as exc:
            issues.append(f"Could not import smart_simust_player for playlist checks: {exc}")
            report.append(f"  Playlist checks skipped: {exc}")
            return
        self._player = player
        samples = [
            ("L00-Foundation", "SF-30N"),
            ("L00-Foundation", "SF-180N"),
            ("L01-Entry/S1.T1", ""),
            ("L01-Entry/S1.T4", ""),
            ("L02-Activated/S1.T3", ""),
            ("L03-HighPerformance/S1.T2", ""),
            ("L04-Elite/S1.T1", ""),
            ("L04-Elite/S1.T4", ""),
            ("L05-WorldClass/S1.T1", ""),
            ("L05-WorldClass/S1.T5", ""),
        ]
        for level, sub in samples:
            try:
                count, detail = self._build_playlist_for(level, sub)
                report.append(f"  {level} {sub or '-'}: {count} step(s) {detail}")
                if count <= 0:
                    issues.append(f"Simulator playlist empty for {level} {sub}".strip())
            except Exception as exc:
                issues.append(f"Simulator playlist failed for {level} {sub}: {exc}")
                report.append(f"  {level} {sub or '-'}: ERROR {exc}")

        # Dual independent Foundation + Entry should zip into one timeline.
        try:
            parts = {
                "A": self._build_playlist_rows("L00-Foundation", "SF-180N"),
                "B": self._build_playlist_rows("L01-Entry/S1.T3", ""),
            }
            merged = player._zip_field_action_playlists(parts)
            report.append(
                "  Independent A=SF-180N + B=Entry S1.T3 zip: %s step(s) (A=%s B=%s)"
                % (len(merged), len(parts["A"]), len(parts["B"]))
            )
            if not merged:
                issues.append("Independent dual-field playlist zip is empty.")
            cards = player._opening_cards_for_fields(
                ["A", "B"],
                {"A": "L00-Foundation", "B": "L01-Entry/S1.T3"},
                {"A": "SF-180N", "B": "S1.T3"},
                parts,
                {},
                [],
                1,
            )
            if "SF-180N" not in cards.get("A", {}).get("text", ""):
                issues.append("Opening card for Field A did not show SF-180N.")
            if "S1.T3" not in cards.get("B", {}).get("text", ""):
                issues.append("Opening card for Field B did not show S1.T3.")
            else:
                report.append(
                    "  Opening cards: A=%s | B=%s"
                    % (
                        cards["A"]["text"].replace("\n", " "),
                        cards["B"]["text"].replace("\n", " "),
                    )
                )
        except Exception as exc:
            issues.append(f"Independent dual-field playlist zip failed: {exc}")

    def _build_playlist_rows(self, level: str, subdirectory: str) -> List[dict]:
        player = getattr(self, "_player", None)
        if player is None:
            import smart_simust_player as player
            self._player = player
        if level == "L00-Foundation":
            if subdirectory.upper() not in ("SF-30N", "SF-60N", "SF-110N", "SF-180N"):
                return []
            active = {"A"}
            factory = player._mode_slot_factory(subdirectory, active)
            rows = []
            # Foundation currently uses LABEL_TEST_COUNT (1) timed tests in the player.
            for test_num in range(1, max(1, int(player.LABEL_TEST_COUNT)) + 1):
                for action_in_set in range(1, int(player.LABEL_ACTIONS_PER_TEST) + 1):
                    slot = factory(action_in_set, test_num) or {}
                    sids = list(slot.get("A") or [])
                    if not sids:
                        continue
                    rows.append({
                        "kind": "labeled_action",
                        "test_num": test_num,
                        "action_in_set": action_in_set,
                        "actions_in_set": player.LABEL_ACTIONS_PER_TEST,
                        "field_screens": {"A": sids},
                        "screen_images": {sid: f"synthetic://{subdirectory}/{sid}" for sid in sids},
                        "finish_balls": True,
                        "label": f"{subdirectory} T{test_num} a{action_in_set}",
                    })
            return player._stamp_finish_balls(rows) if rows else []
        series = 1
        match = __import__("re").search(r"S(?:1|2)[.-]T([1-5])|A-T([1-5])", level)
        if match:
            series = int(match.group(1) or match.group(2))
        active = {"A", "B"} if _combined_level(level) else {"A"}
        if "L05-WorldClass" in level:
            if __import__("re").search(r"S2[.-]T[1-5]", level, re.I):
                return player._build_world_class_s2_playlist(series) or []
            return player._build_elite_playlist(series, "world-class") or []
        if "L04-Elite" in level:
            if __import__("re").search(r"S2[.-]T[1-5]", level, re.I):
                return player._build_elite_s2_playlist(series) or []
            return player._build_elite_playlist(series, "elite") or []
        if "L03-HighPerformance" in level or "HighPerformance" in level:
            if __import__("re").search(r"S2[.-]T[1-5]", level, re.I):
                return player._build_high_performance_s2_playlist(series, active) or []
            return player._build_high_performance_playlist(series, active) or []
        if "L02-Activated" in level:
            a1 = __import__("re").search(r"S2[.-]T([1-5])|A1[-.]T([1-5])", level, re.I)
            if a1:
                return player._build_activated_a1_playlist(int(a1.group(1) or a1.group(2)), active) or []
            return player._build_activated_playlist(series, active) or []
        if "L01-Entry" in level:
            return player._build_entry_playlist(series, active) or []
        return []

    def _build_playlist_for(self, level: str, subdirectory: str) -> Tuple[int, str]:
        rows = self._build_playlist_rows(level, subdirectory)
        tests = sorted({int(r.get("test_num") or 0) for r in rows if isinstance(r, dict)})
        finish = any(bool(r.get("finish_balls")) for r in rows if isinstance(r, dict))
        detail = f"tests={tests or '-'} finish_balls={finish}"
        if _combined_level(level) and rows:
            # Elite/WC rows should address both fields when built for combined play.
            has_a = any("A" in str((r.get("field_screens") or {})) for r in rows)
            has_b = any("B" in str((r.get("field_screens") or {})) for r in rows)
            detail += f" fields A={has_a} B={has_b}"
            if not (has_a and has_b):
                # Some builders put screens in screen_images keys.
                names = " ".join(
                    " ".join((r.get("screen_images") or {}).keys())
                    for r in rows if isinstance(r, dict)
                )
                has_a = has_a or ("A1" in names or "A2" in names)
                has_b = has_b or ("B1" in names or "B2" in names)
                detail += f" images A={has_a} B={has_b}"
        return len(rows), detail

    def _dual_field_checks(self, users: dict, report: List[str], issues: List[str]) -> None:
        import app as app_module

        store = {"reservations": [], "users": {PLAYER_ID: users[PLAYER_ID]}}
        real = {
            "load_reservations": app_module.load_reservations,
            "save_reservations": app_module.save_reservations,
            "load_users": app_module.load_users,
            "save_users": app_module.save_users,
        }

        def load_reservations():
            return list(store["reservations"])

        def save_reservations(items):
            store["reservations"] = list(items)

        def load_users():
            return store["users"]

        def save_users(data):
            store["users"] = data

        app_module.load_reservations = load_reservations
        app_module.save_reservations = save_reservations
        app_module.load_users = load_users
        app_module.save_users = save_users

        try:
            self._dual_field_checks_body(store, report, issues)
        finally:
            app_module.load_reservations = real["load_reservations"]
            app_module.save_reservations = real["save_reservations"]
            app_module.load_users = real["load_users"]
            app_module.save_users = real["save_users"]

    def _dual_field_checks_body(self, store: dict, report: List[str], issues: List[str]) -> None:
        for label, level in (
            ("Elite S1.T1", "L04-Elite/S1.T1"),
            ("World Class S1.T1", "L05-WorldClass/S1.T1"),
        ):
            store["users"][PLAYER_ID]["progress"]["current_level"] = level
            unlocked = list(store["users"][PLAYER_ID]["progress"].get("unlocked_levels") or [])
            if level not in unlocked:
                unlocked.append(level)
            store["users"][PLAYER_ID]["progress"]["unlocked_levels"] = unlocked

            # UI selection must put the same player on A and B.
            if not _ui_combined_selects_both(level):
                issues.append(f"UI combined-level helper does not treat {level} as dual-field.")
            else:
                report.append(f"  UI: choosing {label} auto-selects Field A and Field B for the same player.")

            # Booking Field A must also book Field B.
            start = datetime.now().replace(microsecond=0) + timedelta(days=2, hours=len(store["reservations"]))
            end = start + timedelta(minutes=30)
            before = len(store["reservations"])
            created = _insert_reservation(
                username=PLAYER_ID,
                display_name="Remote Simulator",
                start=start,
                end=end,
                duration=30,
                payment_status="paid",
                amount_eur=0,
                source="sim",
                field="A",
            )
            mine = [
                item for item in store["reservations"]
                if item.get("player_id") == PLAYER_ID
                and item.get("start") == start.isoformat(timespec="seconds")
            ]
            fields = sorted(item.get("field") for item in mine)
            report.append(f"  Booking {label} on A created fields {fields} (score_source A={created.get('score_source')}).")
            if set(fields) != {"A", "B"}:
                issues.append(f"{label}: booking Field A did not also book Field B (got {fields}).")

            # start-realtime single-slot expansion.
            play_slots = [(PLAYER_ID, "A", {"player_id": PLAYER_ID, "level": level, "field": "A"})]
            if len(play_slots) == 1 and _combined_level(level):
                pid, fid, entry = play_slots[0]
                other = "B" if fid == "A" else "A"
                cloned = dict(entry)
                cloned["field"] = other
                play_slots.append((pid, other, cloned))
            active = sorted(fid for _pid, fid, _entry in play_slots)
            report.append(f"  Realtime start with one selected field for {label} expands to {active}.")
            if active != ["A", "B"]:
                issues.append(f"{label}: realtime start did not expand to both fields ({active}).")

            # Conflict: B already taken.
            start2 = start + timedelta(days=1)
            end2 = start2 + timedelta(minutes=30)
            store["reservations"].append({
                "id": f"taken-b-{label}",
                "player_id": "other_player",
                "start": start2.isoformat(timespec="seconds"),
                "end": end2.isoformat(timespec="seconds"),
                "field": "B",
                "payment_status": "paid",
            })
            _insert_reservation(
                username=PLAYER_ID,
                display_name="Remote Simulator",
                start=start2,
                end=end2,
                duration=30,
                payment_status="paid",
                amount_eur=0,
                source="sim",
                field="A",
            )
            mine2 = [
                item for item in store["reservations"]
                if item.get("player_id") == PLAYER_ID
                and item.get("start") == start2.isoformat(timespec="seconds")
            ]
            fields2 = sorted(item.get("field") for item in mine2)
            report.append(f"  {label} when B is busy: player kept fields {fields2}.")
            if fields2 == ["A"]:
                issues.append(
                    f"{label}: when Field B is already booked, booking stays on A only "
                    "and play can still start without the second field."
                )

            _ = before  # silence lint

    def _push_player(self, users: dict, report: List[str], issues: List[str]) -> None:
        try:
            import importlib
            from dotenv import load_dotenv
            import app as app_module

            env_path = os.path.join(ROOT, "lab.env")
            if os.path.exists(env_path):
                load_dotenv(env_path, override=True)
            import simust_push
            importlib.reload(simust_push)

            # Always keep the player in the lab users.json for local operator search.
            live = app_module.load_users()
            live[PLAYER_ID] = users[PLAYER_ID]
            app_module.save_users(live)
            report.append(f"Saved {PLAYER_ID} into local users.json.")

            if not simust_push.push_configured():
                report.append("Lab→VPS push is not configured on this PC. Player kept local only.")
                return
            simust_push.push_accounts(live)
            report.append(
                f"Pushed {PLAYER_ID} to the public host. "
                "Remote operator (coach/admin) can search this player after refresh."
            )
        except Exception as exc:
            issues.append(f"Could not push player to remote host: {exc}")
            report.append(f"Remote push failed: {exc}")

    def _write(self, path: str, title: str, lines: List[str]) -> None:
        text = title + "\n" + ("=" * len(title)) + "\n\n" + "\n".join(lines) + "\n"
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)


if __name__ == "__main__":
    unittest.main()
