"""Manual coach drill: light one screen + cylinder on demand from the operator.

Coach clicks a goal-area button → pass image + cylinder on that screen.
Player scores Correct → screen clears; coach lights the next screen.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

MANUAL_COACH_ARG = "__manual_coach__"
PLAYER_DIR = os.environ.get(
    "SIMUST_PLAYER_DIRECTORY",
    "C:/Users/siama/Documents/simust_player",
)
CMD_FILE = os.path.join(PLAYER_DIR, "manual_coach_cmd.json")
STATUS_FILE = os.path.join(PLAYER_DIR, "manual_coach_status.json")

# Graphical goal-area layout (percent of each field panel).
# A1–A6 use the same positions as B1–B6 (same number → same spot on each half).
FIELD_B_LAYOUT = {
    "B1": {"left": 12, "top": 28},
    "B2": {"left": 50, "top": 16},
    "B3": {"left": 88, "top": 28},
    "B4": {"left": 88, "top": 68},
    "B5": {"left": 50, "top": 78},
    "B6": {"left": 12, "top": 68},
}
FIELD_A_LAYOUT = {
    "A1": dict(FIELD_B_LAYOUT["B1"]),
    "A2": dict(FIELD_B_LAYOUT["B2"]),
    "A3": dict(FIELD_B_LAYOUT["B3"]),
    "A4": dict(FIELD_B_LAYOUT["B4"]),
    "A5": dict(FIELD_B_LAYOUT["B5"]),
    "A6": dict(FIELD_B_LAYOUT["B6"]),
}

VALID_SCREENS = tuple(
    list(FIELD_A_LAYOUT.keys()) + list(FIELD_B_LAYOUT.keys())
)


def normalize_screen(screen) -> Optional[str]:
    raw = str(screen or "").strip().upper()
    if raw in VALID_SCREENS:
        return raw
    match = re.fullmatch(r"([AB])([1-6])", raw)
    if match:
        return f"{match.group(1)}{match.group(2)}"
    return None


def field_for_screen(screen: str) -> str:
    name = normalize_screen(screen) or ""
    return "B" if name.startswith("B") else "A"


def layout_for_operator() -> Dict[str, Any]:
    return {
        "A": [
            {"id": sid, "left": pos["left"], "top": pos["top"]}
            for sid, pos in FIELD_A_LAYOUT.items()
        ],
        "B": [
            {"id": sid, "left": pos["left"], "top": pos["top"]}
            for sid, pos in FIELD_B_LAYOUT.items()
        ],
        "screens": list(VALID_SCREENS),
    }


def _write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    os.replace(tmp, path)


def _read_json(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_status(**fields) -> dict:
    current = _read_json(STATUS_FILE)
    current.update(fields)
    current["timestamp"] = time.time()
    _write_json(STATUS_FILE, current)
    return current


def read_status() -> dict:
    data = _read_json(STATUS_FILE)
    if not data:
        return {
            "active": False,
            "lit_screen": None,
            "lit_screens": [],
            "waiting_hit": False,
            "last_hit": None,
            "seq": 0,
            "message": "Manual coach idle",
        }
    lit = data.get("lit_screens")
    if not isinstance(lit, list):
        one = data.get("lit_screen")
        data["lit_screens"] = [one] if one else []
    return data


def write_command(cmd: str, screen: Optional[str] = None, seq: Optional[int] = None) -> dict:
    current = _read_json(CMD_FILE)
    try:
        next_seq = int(seq if seq is not None else (current.get("seq") or 0)) + (
            0 if seq is not None else 1
        )
    except (TypeError, ValueError):
        next_seq = 1
    if seq is not None:
        next_seq = int(seq)
    payload = {
        "seq": int(next_seq),
        "cmd": str(cmd or "").strip().lower() or "clear",
        "screen": normalize_screen(screen) if screen else None,
        "timestamp": time.time(),
    }
    _write_json(CMD_FILE, payload)
    return payload


def read_command() -> dict:
    return _read_json(CMD_FILE)


def clear_command_files() -> None:
    for path in (CMD_FILE, STATUS_FILE):
        try:
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass
    write_status(
        active=False,
        lit_screen=None,
        waiting_hit=False,
        last_hit=None,
        seq=0,
        message="Manual coach idle",
    )
