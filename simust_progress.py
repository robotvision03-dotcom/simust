"""Score unlocks for Foundation playlists and later levels.

Rules:
- A new player starts with Foundation SF-30N unlocked. Everything else stays locked.
- An admin password can unlock a locked level. A passed level stays unlocked.
- Foundation SF-30N → SF-60N → SF-110N → SF-180N → Entry:
  75% accuracy and 70% efficiency on the final results (ACC + AE).
- Entry and every later set: unlock / level-up uses AE only at 75%.
  Accuracy is recorded but does not gate the next set.
- Passing S1.T4 opens the next band (Entry S1.T4 → Activated S1.T1, and so on).
  World Class S1.T4 opens World Class S1.T5. Booking does not open levels.
  Sub-level names: A-T# / A.T# → S1.T#, A1.T# → S2.T#.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


def normalize_level_id(level_id: str) -> str:
    """Map legacy A-T / A1.T theme ids to S1.T / S2.T."""
    cid = str(level_id or "").strip()
    if not cid or "/" not in cid:
        return cid
    parts = cid.split("/")
    main, theme = parts[0], parts[1]
    rest = parts[2:]
    a1 = re.match(r"^A1[.-]?T([1-5])$", theme, re.I)
    if a1:
        theme = f"S2.T{a1.group(1)}"
    else:
        legacy = re.match(r"^A[-.]?T([1-5])$", theme, re.I)
        if legacy:
            theme = f"S1.T{legacy.group(1)}"
    return "/".join([main, theme] + rest)


def _migrate_level_list(values: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in values or []:
        nid = normalize_level_id(str(raw or "").strip())
        if not nid or nid in seen:
            continue
        seen.add(nid)
        out.append(nid)
    return out

FOUNDATION_PLAYLISTS = ["SF-30N", "SF-60N", "SF-110N", "SF-180N"]
# Extra Foundation modes (not in the paid SF unlock chain)
FOUNDATION_MATH_PLAYLISTS = ["sum", "sub", "multiply", "divide"]
FOUNDATION_COGNITIVE_PLAYLISTS = [
    "sequence", "compound", "color_rule", "go_nogo", "stroop",
    "spatial", "memory", "move_memory", "tracking", "tactical",
    "flex", "dual_rule", "peripheral", "emotion", "symbols",
]
FOUNDATION_EXTRA_PLAYLISTS = (
    ["digit", "rotation", "omid", "omid_2"]
    + FOUNDATION_MATH_PLAYLISTS
    + FOUNDATION_COGNITIVE_PLAYLISTS
)
FOUNDATION_ALL_PLAYLISTS = FOUNDATION_PLAYLISTS + FOUNDATION_EXTRA_PLAYLISTS
FOUNDATION_LEVEL = "L00-Foundation"
SESSION_MINUTES = 30
FOUNDATION_SCORE_ACC = 75.0
FOUNDATION_SCORE_AE = 70.0
# Non-Foundation unlock is AE-only; ACC threshold is unused (0).
SERIES_SCORE_ACC = 0.0
SERIES_SCORE_AE = 75.0


def slots_from_minutes(duration_minutes: int) -> int:
    try:
        mins = int(duration_minutes or 0)
    except (TypeError, ValueError):
        mins = 0
    return max(0, mins // SESSION_MINUTES)


def default_progress() -> Dict[str, Any]:
    return {
        "current_level": FOUNDATION_LEVEL,
        "current_playlist": "SF-30N",
        "unlocked_levels": [FOUNDATION_LEVEL],
        "unlocked_playlists": ["SF-30N"],
        "completed_levels": [],
        "passed_playlists": [],
        "eligible_levels": [],
        "manually_locked_levels": [],
        "manually_locked_playlists": [],
        "session_credits": 0,
        "challenge_results": {},
        "granted_reservation_ids": [],
    }


def ensure_progress(user: Dict[str, Any]) -> Dict[str, Any]:
    progress = user.setdefault("progress", default_progress())
    progress.setdefault("current_level", FOUNDATION_LEVEL)
    progress.setdefault("current_playlist", "SF-30N")
    progress.setdefault("unlocked_levels", [])
    progress.setdefault("unlocked_playlists", [])
    progress.setdefault("completed_levels", [])
    progress.setdefault("passed_playlists", [])
    progress.setdefault("eligible_levels", [])
    progress.setdefault("manually_locked_levels", [])
    progress.setdefault("manually_locked_playlists", [])
    progress.setdefault("session_credits", 0)
    progress.setdefault("challenge_results", {})
    progress.setdefault("granted_reservation_ids", [])
    # Every account can start Foundation 30N. Later sets stay locked until a score or an admin unlock.
    levels = list(progress.get("unlocked_levels") or [])
    playlists = list(progress.get("unlocked_playlists") or [])
    if "SF-30N" not in playlists:
        playlists.insert(0, "SF-30N")
        progress["unlocked_playlists"] = playlists
    if FOUNDATION_LEVEL not in levels:
        levels.append(FOUNDATION_LEVEL)
        progress["unlocked_levels"] = levels
    progress["unlocked_levels"] = _migrate_level_list(progress.get("unlocked_levels") or [])
    progress["completed_levels"] = _migrate_level_list(progress.get("completed_levels") or [])
    progress["eligible_levels"] = _migrate_level_list(progress.get("eligible_levels") or [])
    progress["manually_locked_levels"] = _migrate_level_list(
        progress.get("manually_locked_levels") or []
    )
    progress["manually_locked_playlists"] = [
        str(name).strip()
        for name in (progress.get("manually_locked_playlists") or [])
        if str(name).strip()
    ]
    progress["current_level"] = normalize_level_id(str(progress.get("current_level") or FOUNDATION_LEVEL)) or FOUNDATION_LEVEL
    results = dict(progress.get("challenge_results") or {})
    if results:
        migrated = {}
        for key, value in results.items():
            migrated[normalize_level_id(str(key))] = value
        progress["challenge_results"] = migrated
    if not progress.get("current_level"):
        progress["current_level"] = FOUNDATION_LEVEL
    # Operator locks must stick across pulls / score opens.
    apply_manual_locks(progress)
    # Keep current_level inside the unlocked set (full sync needs ALL_LEVELS order).
    unlocked = {normalize_level_id(x) for x in (progress.get("unlocked_levels") or [])}
    unlocked.add(FOUNDATION_LEVEL)
    cur = normalize_level_id(str(progress.get("current_level") or FOUNDATION_LEVEL))
    if cur not in unlocked:
        progress["current_level"] = FOUNDATION_LEVEL
    if progress.get("current_level") == FOUNDATION_LEVEL:
        progress["current_playlist"] = highest_foundation_playlist(progress)
    return progress


def apply_manual_locks(progress: Dict[str, Any]) -> Dict[str, Any]:
    """Strip operator-locked sets/playlists out of the open lists."""
    locked_levels = {
        normalize_level_id(x)
        for x in (progress.get("manually_locked_levels") or [])
        if normalize_level_id(x)
    }
    locked_playlists = {
        str(name).strip()
        for name in (progress.get("manually_locked_playlists") or [])
        if str(name).strip()
    }
    if locked_levels:
        progress["unlocked_levels"] = [
            lvl
            for lvl in (progress.get("unlocked_levels") or [])
            if normalize_level_id(lvl) not in locked_levels
        ]
        progress["completed_levels"] = [
            lvl
            for lvl in (progress.get("completed_levels") or [])
            if normalize_level_id(lvl) not in locked_levels
        ]
        progress["eligible_levels"] = [
            lvl
            for lvl in (progress.get("eligible_levels") or [])
            if normalize_level_id(lvl) not in locked_levels
        ]
    if locked_playlists:
        progress["unlocked_playlists"] = [
            name
            for name in (progress.get("unlocked_playlists") or [])
            if str(name).strip() not in locked_playlists
        ]
        # SF-30N is the day-one floor — never leave a player with zero SF access.
        if "SF-30N" not in locked_playlists and "SF-30N" not in (
            progress.get("unlocked_playlists") or []
        ):
            playlists = list(progress.get("unlocked_playlists") or [])
            playlists.insert(0, "SF-30N")
            progress["unlocked_playlists"] = playlists
    return progress


def is_manually_locked(progress: Dict[str, Any], level_id: str = "", playlist: str = "") -> bool:
    level = normalize_level_id(str(level_id or "").strip())
    if level and level in {
        normalize_level_id(x) for x in (progress.get("manually_locked_levels") or [])
    }:
        return True
    name = str(playlist or "").strip()
    if name and name in {
        str(x).strip() for x in (progress.get("manually_locked_playlists") or [])
    }:
        return True
    return False


def mark_manual_lock(progress: Dict[str, Any], level_id: str = "", playlist: str = "") -> None:
    if playlist:
        name = str(playlist).strip()
        locked = list(progress.get("manually_locked_playlists") or [])
        if name and name not in locked:
            locked.append(name)
        progress["manually_locked_playlists"] = locked
    if level_id:
        nid = normalize_level_id(str(level_id).strip())
        locked = _migrate_level_list(progress.get("manually_locked_levels") or [])
        if nid and nid not in locked:
            locked.append(nid)
        progress["manually_locked_levels"] = locked
    apply_manual_locks(progress)


def clear_manual_lock(progress: Dict[str, Any], level_id: str = "", playlist: str = "") -> None:
    if playlist:
        name = str(playlist).strip()
        progress["manually_locked_playlists"] = [
            item
            for item in (progress.get("manually_locked_playlists") or [])
            if str(item).strip() != name
        ]
    if level_id:
        nid = normalize_level_id(str(level_id).strip())
        progress["manually_locked_levels"] = [
            item
            for item in _migrate_level_list(progress.get("manually_locked_levels") or [])
            if item != nid
        ]


def highest_foundation_playlist(progress: Dict[str, Any]) -> str:
    """The furthest Foundation set that is open. SF-30N if nothing later is open."""
    have = set(progress.get("unlocked_playlists") or [])
    latest = "SF-30N"
    for name in FOUNDATION_PLAYLISTS:
        if name in have:
            latest = name
    return latest


def next_foundation_playlist_after(subdirectory: str) -> Optional[str]:
    name = str(subdirectory or "").strip()
    if name not in FOUNDATION_PLAYLISTS:
        return None
    index = FOUNDATION_PLAYLISTS.index(name)
    if index + 1 < len(FOUNDATION_PLAYLISTS):
        return FOUNDATION_PLAYLISTS[index + 1]
    return None


def score_gate(level_id: str) -> Tuple[float, float]:
    """Return (accuracy, efficiency) thresholds for the level.

    Foundation requires both. Entry and later use AE only (ACC threshold is 0).
    """
    main = str(level_id or "").split("/")[0]
    if main == FOUNDATION_LEVEL:
        return FOUNDATION_SCORE_ACC, FOUNDATION_SCORE_AE
    return SERIES_SCORE_ACC, SERIES_SCORE_AE


def passes_score_gate(level_id: str, aac: float, ae: float) -> bool:
    """True when finals meet the unlock / level-up gate for this set."""
    th_acc, th_ae = score_gate(level_id)
    try:
        aac_v = float(aac or 0.0)
    except (TypeError, ValueError):
        aac_v = 0.0
    try:
        ae_v = float(ae or 0.0)
    except (TypeError, ValueError):
        ae_v = 0.0
    main = str(level_id or "").split("/")[0]
    if main == FOUNDATION_LEVEL:
        return aac_v >= float(th_acc) and ae_v >= float(th_ae)
    # Entry / Activated / High Performance / Elite / World Class: AE only.
    return ae_v >= float(th_ae)


def highest_unlocked_level(progress: Dict[str, Any], all_levels: List[str]) -> str:
    """Furthest open level. Foundation while only SF sets are open."""
    unlocked = {normalize_level_id(x) for x in (progress.get("unlocked_levels") or [])}
    best = ""
    for level_id in all_levels or []:
        nid = normalize_level_id(level_id)
        if nid in unlocked and nid != FOUNDATION_LEVEL:
            best = nid
    return best or FOUNDATION_LEVEL


def sync_current_development_level(progress: Dict[str, Any], all_levels: List[str]) -> Dict[str, Any]:
    """CURRENT DEVELOPMENT LEVEL = latest unlocked set (and Foundation playlist).

    Call after every unlock / final save so My SIMUST and operator always show
    where the player continues next time (like a game save checkpoint).
    """
    progress = progress or default_progress()
    progress.setdefault("manually_locked_levels", [])
    progress.setdefault("manually_locked_playlists", [])
    apply_manual_locks(progress)
    level = highest_unlocked_level(progress, all_levels or [])
    progress["current_level"] = level
    if level == FOUNDATION_LEVEL:
        playlist = highest_foundation_playlist(progress)
        progress["current_playlist"] = playlist
    else:
        # Leave Foundation — clear SF stamp so operator / My SIMUST show the series set.
        progress["current_playlist"] = ""
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
    """Booking credits do not open levels. Scores and the admin password do."""
    return None


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
    sub = (subdirectory or "").strip()
    if is_manually_locked(progress, level_id, sub):
        return False, f"{level_id}{('/' + sub) if sub else ''} is locked by an operator"
    if level_id == FOUNDATION_LEVEL:
        sub = (subdirectory or "").strip()
        if not sub:
            return False, "Select a Foundation playlist (SF / digit / math / cognitive)"
        # Extra modes: open once any SF playlist is unlocked
        if sub.lower() in {p.lower() for p in FOUNDATION_EXTRA_PLAYLISTS}:
            if not unlocked_playlists:
                return False, f"{sub} opens after any Foundation SF playlist is unlocked"
            return True, ""
        if sub not in unlocked_playlists:
            return False, f"{sub} is locked until the previous set is passed, or an admin unlocks it"
        return True, ""
    want = normalize_level_id(level_id)
    unlocked = {normalize_level_id(x) for x in unlocked_levels}
    if want not in unlocked:
        return False, f"{level_id} is locked until the previous set is passed, or an admin unlocks it"
    return True, ""


def merge_progress(local_progress: Optional[Dict[str, Any]], remote_progress: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Union unlock / eligibility fields from two progress blobs.

    Operator manual locks are also unioned, then stripped from open sets so a
    host pull cannot re-open a level the lab just locked.
    """
    dst = dict(local_progress or default_progress())
    src = remote_progress or {}
    if not src:
        apply_manual_locks(dst)
        return dst
    for key in (
        "unlocked_playlists",
        "unlocked_levels",
        "eligible_levels",
        "completed_levels",
        "granted_reservation_ids",
        "manually_locked_levels",
        "manually_locked_playlists",
    ):
        merged = []
        for value in list(dst.get(key) or []) + list(src.get(key) or []):
            if value and value not in merged:
                merged.append(value)
        if key in ("unlocked_levels", "eligible_levels", "completed_levels", "manually_locked_levels"):
            merged = _migrate_level_list(merged)
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
    apply_manual_locks(dst)
    # Prefer lab current when locks removed a remote "highest" set.
    if src.get("current_level") and not is_manually_locked(dst, str(src.get("current_level") or "")):
        remote_cur = normalize_level_id(str(src.get("current_level") or ""))
        unlocked = {normalize_level_id(x) for x in (dst.get("unlocked_levels") or [])}
        if remote_cur in unlocked:
            dst["current_level"] = remote_cur
    return dst


def apply_lab_progress(
    existing: Optional[Dict[str, Any]],
    incoming: Optional[Dict[str, Any]],
    all_levels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Apply lab operator unlock/lock as the source of truth for open sets.

    Union-merge cannot remove a locked level on the public host. Lab pushes after
    manual lock/unlock therefore replace unlocked / completed lists, then stamp
    CURRENT DEVELOPMENT LEVEL to the highest unlocked set.
    """
    dst = dict(default_progress())
    dst.update(existing or {})
    src = incoming or {}
    if not src:
        return sync_current_development_level(dst, all_levels or [])
    for key in (
        "unlocked_playlists",
        "unlocked_levels",
        "eligible_levels",
        "completed_levels",
        "passed_playlists",
        "manually_locked_levels",
        "manually_locked_playlists",
    ):
        if key in src:
            values = list(src.get(key) or [])
            if key in (
                "unlocked_levels",
                "eligible_levels",
                "completed_levels",
                "manually_locked_levels",
            ):
                values = _migrate_level_list(values)
            dst[key] = values
    if "current_playlist" in src:
        dst["current_playlist"] = str(src.get("current_playlist") or "")
    if "session_credits" in src:
        try:
            dst["session_credits"] = int(src.get("session_credits") or 0)
        except (TypeError, ValueError):
            dst["session_credits"] = 0
    granted: List[str] = []
    for value in list(dst.get("granted_reservation_ids") or []) + list(
        src.get("granted_reservation_ids") or []
    ):
        if value and value not in granted:
            granted.append(value)
    dst["granted_reservation_ids"] = granted
    results = dict(dst.get("challenge_results") or {})
    results.update(src.get("challenge_results") or {})
    dst["challenge_results"] = results
    # Always recompute CURRENT DEVELOPMENT LEVEL from the open sets.
    return sync_current_development_level(dst, all_levels or [])


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
    progress = sync_current_development_level(
        dict(progress or default_progress()), all_levels or []
    )
    nxt = peek_next_unlock_target(progress, all_levels)
    return {
        "current_level": progress.get("current_level") or FOUNDATION_LEVEL,
        "current_playlist": progress.get("current_playlist") or "",
        "unlocked_levels": list(progress.get("unlocked_levels") or []),
        "unlocked_playlists": list(progress.get("unlocked_playlists") or []),
        "completed_levels": list(progress.get("completed_levels") or []),
        "eligible_levels": list(progress.get("eligible_levels") or []),
        "session_credits": int(progress.get("session_credits") or 0),
        "next_unlock": (
            {"kind": nxt[0], "id": nxt[1]} if nxt else None
        ),
        "foundation_playlists": list(FOUNDATION_ALL_PLAYLISTS),
    }
