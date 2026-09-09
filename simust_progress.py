"""Paid 30-minute session unlocks for Foundation playlists and later levels.

Rules:
- Unpaid players cannot play (no unlocked playlists / levels).
- Each paid 30 minutes = 1 session credit.
- Credits unlock the next eligible item; previous unlocks stay open.
- Foundation SF-30N → SF-60N → SF-110N → SF-180N: payment only (no score gate).
- After SF-180N: need min score to become eligible for Entry, then pay to open it.
- Later challenges: score makes next eligible; pay opens it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

FOUNDATION_PLAYLISTS = ["SF-30N", "SF-60N", "SF-110N", "SF-180N"]
FOUNDATION_LEVEL = "L00-Foundation"
SESSION_MINUTES = 30


def slots_from_minutes(duration_minutes: int) -> int:
    try:
        mins = int(duration_minutes or 0)
    except (TypeError, ValueError):
        mins = 0
    return max(0, mins // SESSION_MINUTES)


def default_progress() -> Dict[str, Any]:
    return {
        "current_level": FOUNDATION_LEVEL,
        "unlocked_levels": [],
        "unlocked_playlists": [],
        "completed_levels": [],
        "eligible_levels": [],
        "session_credits": 0,
        "challenge_results": {},
        "granted_reservation_ids": [],
    }


def ensure_progress(user: Dict[str, Any]) -> Dict[str, Any]:
    progress = user.setdefault("progress", default_progress())
    progress.setdefault("current_level", FOUNDATION_LEVEL)
    progress.setdefault("unlocked_levels", [])
    progress.setdefault("unlocked_playlists", [])
    progress.setdefault("completed_levels", [])
    progress.setdefault("eligible_levels", [])
    progress.setdefault("session_credits", 0)
    progress.setdefault("challenge_results", {})
    progress.setdefault("granted_reservation_ids", [])
    # Migrate older accounts that had Foundation always unlocked with no playlists.
    if (
        FOUNDATION_LEVEL in (progress.get("unlocked_levels") or [])
        and not (progress.get("unlocked_playlists") or [])
        and int(progress.get("session_credits") or 0) == 0
        and not (progress.get("granted_reservation_ids") or [])
    ):
        # Keep level umbrella only after at least one playlist unlocks via payment.
        progress["unlocked_levels"] = [
            lvl for lvl in progress["unlocked_levels"] if lvl != FOUNDATION_LEVEL
        ]
    return progress


def next_foundation_playlist(unlocked_playlists: List[str]) -> Optional[str]:
    have = set(unlocked_playlists or [])
    for name in FOUNDATION_PLAYLISTS:
        if name not in have:
            return name
    return None


def _unique_append(seq: List[str], value: str) -> bool:
    if not value or value in seq:
        return False
    seq.append(value)
    return True


def peek_next_unlock_target(progress: Dict[str, Any], all_levels: List[str]) -> Optional[Tuple[str, str]]:
    """
    Return ("playlist", SF-xx) or ("level", level_id) for the next payable unlock,
    or None if waiting on score eligibility.
    """
    playlists = list(progress.get("unlocked_playlists") or [])
    nxt_sf = next_foundation_playlist(playlists)
    if nxt_sf:
        return ("playlist", nxt_sf)

    unlocked = list(progress.get("unlocked_levels") or [])
    eligible = list(progress.get("eligible_levels") or [])
    for level_id in eligible:
        if level_id not in unlocked:
            return ("level", level_id)

    # If Foundation SF-180N is done and Entry is eligible but list empty, derive from ALL_LEVELS.
    if "SF-180N" in playlists:
        try:
            idx = all_levels.index(FOUNDATION_LEVEL)
            entry = all_levels[idx + 1] if idx + 1 < len(all_levels) else None
        except ValueError:
            entry = None
        if entry and entry not in unlocked and entry in eligible:
            return ("level", entry)
    return None


def unlock_one_with_credit(progress: Dict[str, Any], all_levels: List[str]) -> Optional[str]:
    """Spend one credit if a next target is available. Returns unlocked label or None."""
    credits = int(progress.get("session_credits") or 0)
    if credits <= 0:
        return None
    target = peek_next_unlock_target(progress, all_levels)
    if not target:
        return None
    kind, value = target
    progress["session_credits"] = credits - 1
    if kind == "playlist":
        playlists = list(progress.get("unlocked_playlists") or [])
        _unique_append(playlists, value)
        progress["unlocked_playlists"] = playlists
        levels = list(progress.get("unlocked_levels") or [])
        _unique_append(levels, FOUNDATION_LEVEL)
        progress["unlocked_levels"] = levels
        progress["current_level"] = FOUNDATION_LEVEL
        return f"L00-Foundation/{value}"
    levels = list(progress.get("unlocked_levels") or [])
    _unique_append(levels, value)
    progress["unlocked_levels"] = levels
    eligible = [e for e in (progress.get("eligible_levels") or []) if e != value]
    progress["eligible_levels"] = eligible
    progress["current_level"] = value
    return value


def consume_credits(progress: Dict[str, Any], all_levels: List[str]) -> List[str]:
    """Spend as many credits as possible on next unlocks. Returns labels unlocked now."""
    opened: List[str] = []
    while int(progress.get("session_credits") or 0) > 0:
        label = unlock_one_with_credit(progress, all_levels)
        if not label:
            break
        opened.append(label)
    return opened


def grant_reservation_credits(
    users: Dict[str, Any],
    player_id: str,
    duration_minutes: int,
    reservation_id: str,
    all_levels: List[str],
) -> Dict[str, Any]:
    """
    Idempotently grant session credits from a paid/waived reservation and unlock.
    Returns {credits_added, unlocked_now, session_credits, unlocked_playlists, unlocked_levels}.
    """
    empty = {
        "credits_added": 0,
        "unlocked_now": [],
        "session_credits": 0,
        "unlocked_playlists": [],
        "unlocked_levels": [],
    }
    if not player_id or player_id not in users:
        return empty
    user = users[player_id]
    progress = ensure_progress(user)
    granted = list(progress.get("granted_reservation_ids") or [])
    rid = str(reservation_id or "").strip()
    if rid and rid in granted:
        return {
            "credits_added": 0,
            "unlocked_now": [],
            "session_credits": int(progress.get("session_credits") or 0),
            "unlocked_playlists": list(progress.get("unlocked_playlists") or []),
            "unlocked_levels": list(progress.get("unlocked_levels") or []),
        }
    slots = slots_from_minutes(duration_minutes)
    if slots <= 0:
        return empty
    progress["session_credits"] = int(progress.get("session_credits") or 0) + slots
    if rid:
        granted.append(rid)
        progress["granted_reservation_ids"] = granted[-200:]
    unlocked_now = consume_credits(progress, all_levels)
    user["progress"] = progress
    return {
        "credits_added": slots,
        "unlocked_now": unlocked_now,
        "session_credits": int(progress.get("session_credits") or 0),
        "unlocked_playlists": list(progress.get("unlocked_playlists") or []),
        "unlocked_levels": list(progress.get("unlocked_levels") or []),
    }


def mark_score_eligible(
    progress: Dict[str, Any],
    level_played: str,
    next_level: Optional[str],
    all_levels: List[str],
) -> List[str]:
    """After a passing score, mark next level eligible and spend pending credits."""
    if next_level:
        eligible = list(progress.get("eligible_levels") or [])
        _unique_append(eligible, next_level)
        progress["eligible_levels"] = eligible
    return consume_credits(progress, all_levels)


def can_play(
    progress: Dict[str, Any],
    level_id: str,
    subdirectory: Optional[str] = None,
) -> Tuple[bool, str]:
    """Return (ok, reason) for starting a session."""
    progress = progress or {}
    unlocked_levels = list(progress.get("unlocked_levels") or [])
    unlocked_playlists = list(progress.get("unlocked_playlists") or [])
    if level_id == FOUNDATION_LEVEL:
        sub = (subdirectory or "").strip()
        if not sub:
            return False, "Select a Foundation playlist (SF-30N … SF-180N)"
        if sub not in unlocked_playlists:
            return False, f"{sub} is locked — book and pay a 30-minute session to unlock"
        return True, ""
    if level_id not in unlocked_levels:
        return False, f"{level_id} is locked — achieve the previous score, then book 30 minutes"
    return True, ""


def merge_progress(local_progress: Optional[Dict[str, Any]], remote_progress: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Union unlock / eligibility fields from two progress blobs."""
    dst = dict(local_progress or default_progress())
    src = remote_progress or {}
    if not src:
        return dst
    for key in (
        "unlocked_playlists",
        "unlocked_levels",
        "eligible_levels",
        "completed_levels",
        "granted_reservation_ids",
    ):
        merged = []
        for value in list(dst.get(key) or []) + list(src.get(key) or []):
            if value and value not in merged:
                merged.append(value)
        dst[key] = merged
    local_depth = len(dst.get("unlocked_playlists") or []) + len(dst.get("unlocked_levels") or [])
    remote_depth = len(src.get("unlocked_playlists") or []) + len(src.get("unlocked_levels") or [])
    # Keep remaining credits from the more advanced side to avoid double-spending after sync.
    if remote_depth > local_depth:
        dst["session_credits"] = int(src.get("session_credits") or 0)
    elif remote_depth < local_depth:
        dst["session_credits"] = int(dst.get("session_credits") or 0)
    else:
        dst["session_credits"] = max(
            int(dst.get("session_credits") or 0), int(src.get("session_credits") or 0)
        )
    results = dict(dst.get("challenge_results") or {})
    results.update(src.get("challenge_results") or {})
    dst["challenge_results"] = results
    if src.get("current_level"):
        dst["current_level"] = src.get("current_level")
    return dst


def sync_unlocks_from_reservations(
    users: Dict[str, Any],
    reservations: List[Dict[str, Any]],
    all_levels: List[str],
) -> int:
    """Grant credits for every paid/waived/lab booking not yet applied. Returns unlocks count."""
    opened = 0
    for item in reservations or []:
        status = str((item or {}).get("payment_status") or "").strip().lower()
        if status not in ("paid", "admin_waived", "lab"):
            continue
        player_id = str((item or {}).get("player_id") or "").strip()
        if not player_id:
            continue
        duration = (item or {}).get("duration_minutes")
        if duration is None:
            try:
                start = (item or {}).get("start") or ""
                end = (item or {}).get("end") or ""
                # ISO durations without importing datetime here — minutes from reservation field preferred
                from datetime import datetime as _dt

                s = _dt.fromisoformat(str(start).replace("Z", "+00:00").split("+")[0])
                e = _dt.fromisoformat(str(end).replace("Z", "+00:00").split("+")[0])
                duration = int((e - s).total_seconds() // 60)
            except Exception:
                duration = SESSION_MINUTES
        result = grant_reservation_credits(
            users,
            player_id,
            int(duration or 0),
            str((item or {}).get("id") or ""),
            all_levels,
        )
        opened += len(result.get("unlocked_now") or [])
    return opened


def public_progress_view(progress: Dict[str, Any], all_levels: List[str]) -> Dict[str, Any]:
    progress = progress or default_progress()
    nxt = peek_next_unlock_target(progress, all_levels)
    return {
        "current_level": progress.get("current_level") or FOUNDATION_LEVEL,
        "unlocked_levels": list(progress.get("unlocked_levels") or []),
        "unlocked_playlists": list(progress.get("unlocked_playlists") or []),
        "completed_levels": list(progress.get("completed_levels") or []),
        "eligible_levels": list(progress.get("eligible_levels") or []),
        "session_credits": int(progress.get("session_credits") or 0),
        "next_unlock": (
            {"kind": nxt[0], "id": nxt[1]} if nxt else None
        ),
        "foundation_playlists": list(FOUNDATION_PLAYLISTS),
    }
