"""James Band unlock simulator: Foundation → Entry for Field A, B, and A+B.

Creates a full player profile, books 30-minute credits through SF-30N/60N/110N/180N,
passes SF-180N at the minimum Entry gate (70% accuracy / 60% efficiency), then walks
Entry A-T1..A-T5 at the minimum series gate (80% accuracy / 70% efficiency).

There is no SF-90N in the product; Foundation playlists are SF-30N, SF-60N, SF-110N, SF-180N.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from copy import deepcopy
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("SIMUST_PUBLIC_MODE", "1")
os.environ.setdefault("SIMUST_SESSION_SECRET", "james-band-sim-secret")

import simust_progress  # noqa: E402
from app import ALL_LEVELS, apply_session_progress, get_level_thresholds, get_next_level  # noqa: E402

PLAYER_ID = "james_band"
FOUNDATION_SFS = list(simust_progress.FOUNDATION_PLAYLISTS)  # SF-30N, SF-60N, SF-110N, SF-180N
ENTRY_SERIES = [f"L01-Entry/A-T{n}" for n in range(1, 6)]

# Minimum passing stats (exact gate values).
# SF-180N gate: 70% accuracy, 60% AE → 7 correct + 3 wrong of 10 = 70%.
STATS_SF180_MIN = {"correct": 7, "late": 0, "wrong": 3, "miss": 0, "avg_ae": 60.0}
# Entry series gate: 80% accuracy, 70% AE → 8 correct + 2 wrong of 10 = 80%.
STATS_ENTRY_MIN = {"correct": 8, "late": 0, "wrong": 2, "miss": 0, "avg_ae": 70.0}
# Non-gating Foundation sessions (30/60/110): payment unlocks next SF.
STATS_FOUNDATION_PLAY = {"correct": 9, "late": 0, "wrong": 1, "miss": 0, "avg_ae": 85.0}


def _accuracy(stats: dict) -> float:
    correct = int(stats.get("correct", 0) or 0)
    late = int(stats.get("late", 0) or 0)
    total = correct + late + int(stats.get("wrong", 0) or 0) + int(stats.get("miss", 0) or 0)
    return (correct + late) / total * 100.0 if total else 0.0


def make_james_band() -> Dict[str, Any]:
    """Full player profile for James Band."""
    today = date.today()
    birth = date(1994, 3, 15)
    age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    return {
        "name": "James",
        "surname": "Band",
        "role": "player",
        "club": "SIMUST Academy",
        "team": "Field A / Field B Test",
        "age": str(age),
        "birthday": birth.isoformat(),
        "gender": "male",
        "email": "james.band@simust.test",
        "playerId": "JB-1994-0315",
        "progress": simust_progress.default_progress(),
    }


def book(users: dict, minutes: int, rid: str) -> dict:
    return simust_progress.grant_reservation_credits(
        users, PLAYER_ID, minutes, rid, ALL_LEVELS
    )


def play(
    users: dict,
    level: str,
    subdirectory: str,
    stats: dict,
    field: str,
) -> dict:
    """Record a finished session on a field and return a step row for the report."""
    progress = users[PLAYER_ID]["progress"]
    ok, reason = simust_progress.can_play(progress, level, subdirectory)
    if not ok:
        return {
            "field": field,
            "level": level,
            "subdirectory": subdirectory or "",
            "ok": False,
            "reason": reason,
            "accuracy": None,
            "ae": None,
            "threshold_acc": None,
            "threshold_ae": None,
            "passed": False,
            "unlocked_after": list(progress.get("unlocked_levels") or []),
            "playlists_after": list(progress.get("unlocked_playlists") or []),
            "eligible_after": list(progress.get("eligible_levels") or []),
        }
    th_acc, th_ae = get_level_thresholds(level)
    applied = apply_session_progress(users, PLAYER_ID, level, subdirectory, stats)
    progress = users[PLAYER_ID]["progress"]
    result = (progress.get("challenge_results") or {}).get(level) or {}
    return {
        "field": field,
        "level": level,
        "subdirectory": subdirectory or "",
        "ok": True,
        "applied": applied,
        "accuracy": round(_accuracy(stats), 1),
        "ae": float(stats.get("avg_ae") or 0.0),
        "threshold_acc": th_acc,
        "threshold_ae": th_ae,
        "passed": bool(result.get("passed")),
        "unlocked_after": list(progress.get("unlocked_levels") or []),
        "playlists_after": list(progress.get("unlocked_playlists") or []),
        "eligible_after": list(progress.get("eligible_levels") or []),
        "completed_after": list(progress.get("completed_levels") or []),
        "credits_after": int(progress.get("session_credits") or 0),
        "next_level": get_next_level(level),
    }


def run_pipeline(fields: List[str]) -> Tuple[dict, List[dict]]:
    """Book → play Foundation → Entry on the given field labels (A, B, or both)."""
    users = {PLAYER_ID: make_james_band()}
    log: List[dict] = []
    field_tag = "+".join(fields)

    # Foundation SF chain: each SF needs a 30-minute booking (payment unlock).
    for i, sf in enumerate(FOUNDATION_SFS):
        grant = book(users, 30, f"{field_tag}-book-{sf}")
        log.append({
            "kind": "booking",
            "field": field_tag,
            "minutes": 30,
            "reservation": f"{field_tag}-book-{sf}",
            "unlocked_now": list(grant.get("unlocked_now") or []),
            "playlists": list(grant.get("unlocked_playlists") or []),
            "levels": list(grant.get("unlocked_levels") or []),
        })
        stats = STATS_SF180_MIN if sf == "SF-180N" else STATS_FOUNDATION_PLAY
        # Dual A+B: same session score applies once (progress is per player).
        log.append(play(users, "L00-Foundation", sf, stats, field_tag))

    # After SF-180 pass, Entry A-T1 is eligible — book 30 min to open it, then walk A-T1..A-T5.
    for series in ENTRY_SERIES:
        grant = book(users, 30, f"{field_tag}-book-{series.replace('/', '_')}")
        log.append({
            "kind": "booking",
            "field": field_tag,
            "minutes": 30,
            "reservation": f"{field_tag}-book-{series}",
            "unlocked_now": list(grant.get("unlocked_now") or []),
            "playlists": list(grant.get("unlocked_playlists") or []),
            "levels": list(grant.get("unlocked_levels") or []),
        })
        log.append(play(users, series, "", STATS_ENTRY_MIN, field_tag))

    # Final booking opens Activated A-T1 after Entry A-T5 score made it eligible.
    grant = book(users, 30, f"{field_tag}-book-L02-Activated_A-T1")
    log.append({
        "kind": "booking",
        "field": field_tag,
        "minutes": 30,
        "reservation": f"{field_tag}-book-L02-Activated/A-T1",
        "unlocked_now": list(grant.get("unlocked_now") or []),
        "playlists": list(grant.get("unlocked_playlists") or []),
        "levels": list(grant.get("unlocked_levels") or []),
    })

    return users[PLAYER_ID], log


def summarize(player: dict, log: List[dict], mode: str) -> dict:
    progress = player.get("progress") or {}
    session_rows = [row for row in log if row.get("kind") != "booking" and row.get("ok")]
    failed = [row for row in log if row.get("kind") != "booking" and not row.get("ok")]
    bookings = [row for row in log if row.get("kind") == "booking"]
    return {
        "mode": mode,
        "player": {
            "id": PLAYER_ID,
            "name": player.get("name"),
            "surname": player.get("surname"),
            "age": player.get("age"),
            "birthday": player.get("birthday"),
            "club": player.get("club"),
            "team": player.get("team"),
            "gender": player.get("gender"),
            "email": player.get("email"),
            "playerId": player.get("playerId"),
        },
        "bookings": len(bookings),
        "sessions": len(session_rows),
        "failed_sessions": failed,
        "foundation_playlists": list(progress.get("unlocked_playlists") or []),
        "unlocked_levels": list(progress.get("unlocked_levels") or []),
        "completed_levels": list(progress.get("completed_levels") or []),
        "eligible_levels": list(progress.get("eligible_levels") or []),
        "session_credits": int(progress.get("session_credits") or 0),
        "challenge_results": dict(progress.get("challenge_results") or {}),
        "entry_complete": all(s in (progress.get("completed_levels") or []) for s in ENTRY_SERIES),
        "next_after_entry": get_next_level(ENTRY_SERIES[-1]),
        "steps": log,
    }


def format_report(summaries: List[dict]) -> str:
    lines = []
    lines.append("JAMES BAND - FOUNDATION TO ENTRY UNLOCK REPORT")
    lines.append("=" * 60)
    lines.append("Note: Foundation has SF-30N, SF-60N, SF-110N, SF-180N (no SF-90N).")
    lines.append("Gates: SF-180 opens Entry eligibility at >=70% accuracy and >=60% efficiency.")
    lines.append("       Each Entry series opens the next at >=80% accuracy and >=70% efficiency.")
    lines.append("       Next series opens only after that score AND a 30-minute booking.")
    lines.append("")
    p0 = summaries[0]["player"]
    lines.append(
        f"Player: {p0['name']} {p0['surname']} | id={PLAYER_ID} | "
        f"age={p0['age']} | birthday={p0['birthday']} | "
        f"club={p0['club']} | team={p0['team']} | "
        f"gender={p0['gender']} | email={p0['email']} | playerId={p0['playerId']}"
    )
    lines.append("")

    for summary in summaries:
        lines.append("-" * 60)
        lines.append(f"MODE: {summary['mode']}")
        lines.append(
            f"Bookings={summary['bookings']}  Sessions={summary['sessions']}  "
            f"Credits left={summary['session_credits']}"
        )
        lines.append(f"Foundation playlists unlocked: {', '.join(summary['foundation_playlists']) or '-'}")
        lines.append(f"Levels unlocked: {', '.join(summary['unlocked_levels']) or '-'}")
        lines.append(f"Levels completed: {', '.join(summary['completed_levels']) or '-'}")
        lines.append(f"Eligible (waiting on booking): {', '.join(summary['eligible_levels']) or '-'}")
        lines.append(f"Entry A-T1..A-T5 complete: {summary['entry_complete']}")
        lines.append(f"Next after Entry: {summary['next_after_entry']}")
        lines.append("")
        lines.append("Session accuracy / efficiency:")
        for row in summary["steps"]:
            if row.get("kind") == "booking":
                opened = ", ".join(row.get("unlocked_now") or []) or "(credit held)"
                lines.append(
                    f"  [book {row['minutes']}m] unlocked_now={opened}"
                )
                continue
            if not row.get("ok"):
                lines.append(
                    f"  [FAIL {row['field']}] {row['level']} {row.get('subdirectory') or ''} "
                    f"— {row.get('reason')}"
                )
                continue
            sub = row.get("subdirectory") or ""
            label = f"{row['level']}" + (f"/{sub}" if sub else "")
            lines.append(
                f"  [{row['field']}] {label}: "
                f"acc={row['accuracy']}% (need >={row['threshold_acc']}%)  "
                f"ae={row['ae']}% (need >={row['threshold_ae']}%)  "
                f"passed={row['passed']}"
            )
        if summary["failed_sessions"]:
            lines.append("FAILURES:")
            for row in summary["failed_sessions"]:
                lines.append(f"  {row}")
        lines.append("")

    lines.append("=" * 60)
    all_ok = all(s["entry_complete"] and not s["failed_sessions"] for s in summaries)
    lines.append("OVERALL: PASS" if all_ok else "OVERALL: FAIL")
    lines.append(
        "Field A only, Field B only, and Field A+B all reach the end of Entry "
        "when James Band books each step and hits the minimum score gates."
    )
    return "\n".join(lines)


class JamesBandUnlockSimTests(unittest.TestCase):
    def test_a_only_b_only_and_dual_reach_end_of_entry(self):
        summaries = []
        for fields, mode in (
            (["A"], "Field A only"),
            (["B"], "Field B only"),
            (["A", "B"], "Field A + Field B"),
        ):
            player, log = run_pipeline(fields)
            summary = summarize(player, log, mode)
            summaries.append(summary)
            self.assertFalse(summary["failed_sessions"], msg=summary["failed_sessions"])
            self.assertEqual(summary["foundation_playlists"], FOUNDATION_SFS)
            self.assertTrue(summary["entry_complete"])
            for series in ENTRY_SERIES:
                self.assertIn(series, summary["completed_levels"])
            # After A-T5 pass + booking for next, Activated A-T1 should unlock.
            self.assertIn("L02-Activated/A-T1", summary["unlocked_levels"])
            results = summary["challenge_results"]
            self.assertTrue(results["L00-Foundation"]["passed"])
            self.assertGreaterEqual(results["L00-Foundation"]["aac"], 70.0)
            self.assertGreaterEqual(results["L00-Foundation"]["ae"], 60.0)
            for series in ENTRY_SERIES:
                self.assertTrue(results[series]["passed"], msg=series)
                self.assertGreaterEqual(results[series]["aac"], 80.0)
                self.assertGreaterEqual(results[series]["ae"], 70.0)

        report = format_report(summaries)
        out_path = os.path.join(ROOT, "james_band_unlock_report.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(report)
        print("\n" + report)
        print(f"\nReport written to {out_path}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
