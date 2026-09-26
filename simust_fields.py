"""Dual Field A / Field B geometry and booking helpers for SIMUST.

Field A (left): screens A1–A6. Field B (right): screens B1–B6.
QR ROI (0,0,1920,540) / (1920,0,3840,540) as x1,y1,x2,y2
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Sequence, Set, Tuple

# Stitched / dual-monitor canvas
STITCHED_WIDTH = 3840
STITCHED_HEIGHT = 1080
HALF_WIDTH = STITCHED_WIDTH // 2

# Player polygon for Field A (left half of ~1280-wide processing frame / stitch scale)
POLYGON_POINTS_A: List[Tuple[int, int]] = [
    (12, 297),
    (10, 254),
    (37, 192),
    (58, 171),
    (109, 142),
    (139, 132),
    (204, 103),
    (444, 105),
    (503, 133),
    (532, 147),
    (582, 180),
    (609, 202),
    (634, 261),
    (623, 303),
    (469, 342),
    (79, 321),
    (12, 297),
]

# Player polygon for Field B (right half) — provided by lab calibration
POLYGON_POINTS_B: List[Tuple[int, int]] = [
    (654, 285),
    (652, 242),
    (675, 179),
    (695, 159),
    (748, 124),
    (776, 112),
    (833, 87),
    (1090, 87),
    (1144, 113),
    (1172, 125),
    (1225, 159),
    (1246, 181),
    (1269, 245),
    (1266, 286),
    (1105, 323),
    (717, 302),
    (654, 285),
]

# Back-compat alias used by existing code
POLYGON_POINTS = POLYGON_POINTS_A

# Each field uses screens 1–6. A1 is the old cabinet 12, B1 the old cabinet 5.
FIELD_A_SCREENS: Set[str] = {"A1", "A2", "A3", "A4", "A5", "A6"}
FIELD_B_SCREENS: Set[str] = {"B1", "B2", "B3", "B4", "B5", "B6"}
DISABLED_DISPLAY_SCREENS: Set[str] = set()
LEGACY_HW_TO_SCREEN = {
    "12": "A1", "13": "A2", "14": "A3", "2": "A4", "3": "A5", "4": "A6",
    "5": "B1", "6": "B2", "7": "B3", "9": "B4", "10": "B5", "11": "B6",
}

# QR on the dual-monitor player surface (full 3840×1080 grab)
# detect_qr_in_roi expects (x1, y1, x2, y2) — NOT (x, y, w, h).
QR_ROI_A = (0, 0, 1920, 540)
QR_ROI_B = (1920, 0, 3840, 540)

# Arena simulator homes (1280×360 canvas): A left, B right
SIM_PLAYER_HOME_A = (280, 268)
SIM_BALL_HOME_A = (302, 282)
SIM_PLAYER_HOME_B = (280 + 640, 268)
SIM_BALL_HOME_B = (302 + 640, 282)

FIELD_IDS = ("A", "B")


def normalize_field(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().upper()
    if text in ("A", "FIELD_A", "FIELD-A", "TEAM_A", "TEAM-A", "LEFT"):
        return "A"
    if text in ("B", "FIELD_B", "FIELD-B", "TEAM_B", "TEAM-B", "RIGHT"):
        return "B"
    return None


def canonical_screen(raw) -> Optional[str]:
    """Screen name A1–A6 or B1–B6. Old cabinet numbers still map to these names."""
    text = str(raw or "").strip().upper()
    if text in FIELD_A_SCREENS or text in FIELD_B_SCREENS:
        return text
    if len(text) >= 2 and text[0] in ("A", "B") and text[1:].isdigit():
        name = text[0] + str(int(text[1:]))
        if name in FIELD_A_SCREENS or name in FIELD_B_SCREENS:
            return name
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    try:
        digits = str(int(digits))
    except ValueError:
        return None
    return LEGACY_HW_TO_SCREEN.get(digits)


def field_for_screens(screens: Sequence[str]) -> Optional[str]:
    """Infer field from a screen list (new names or old cabinet numbers)."""
    names = []
    for raw in screens or []:
        name = canonical_screen(raw)
        if name:
            names.append(name)
    if not names:
        return None
    a = sum(1 for s in names if s in FIELD_A_SCREENS)
    b = sum(1 for s in names if s in FIELD_B_SCREENS)
    if a and not b:
        return "A"
    if b and not a:
        return "B"
    if a >= b:
        return "A"
    return "B"


def screens_for_field(field_id: str) -> Set[str]:
    fid = normalize_field(field_id) or "A"
    return set(FIELD_A_SCREENS if fid == "A" else FIELD_B_SCREENS)


def polygon_for_field(field_id: str) -> List[Tuple[int, int]]:
    fid = normalize_field(field_id) or "A"
    return list(POLYGON_POINTS_A if fid == "A" else POLYGON_POINTS_B)


def qr_roi_for_field(field_id: str) -> Tuple[int, int, int, int]:
    fid = normalize_field(field_id) or "A"
    return QR_ROI_A if fid == "A" else QR_ROI_B


def field_label(field_id: str) -> str:
    fid = normalize_field(field_id) or "A"
    return f"Field {fid}"


def field_config(field_id: str) -> Dict:
    fid = normalize_field(field_id) or "A"
    if fid == "B":
        return {
            "id": "B",
            "label": "Field B",
            "screens": set(FIELD_B_SCREENS),
            "qr_roi": QR_ROI_B,
            "polygon": list(POLYGON_POINTS_B),
            "player_half": "right",
            "sim_player_home": SIM_PLAYER_HOME_B,
            "sim_ball_home": SIM_BALL_HOME_B,
            "overlay_side": "right",
            "results_slices": {
                "aet": "B1",
                "accuracy": "B2",
                "efficiency": "B5",
                "displacement": "B6",
                "integration": ("B3", "B4"),
            },
        }
    return {
        "id": "A",
        "label": "Field A",
        "screens": set(FIELD_A_SCREENS),
        "qr_roi": QR_ROI_A,
        "polygon": list(POLYGON_POINTS_A),
        "player_half": "left",
        "sim_player_home": SIM_PLAYER_HOME_A,
        "sim_ball_home": SIM_BALL_HOME_A,
        "overlay_side": "left",
        "results_slices": {
            "aet": "A1",
            "accuracy": "A2",
            "efficiency": "A5",
            "displacement": "A6",
            "integration": ("A3", "A4"),
        },
    }


ALL_FIELDS = {fid: field_config(fid) for fid in FIELD_IDS}


def load_active_fields(players_fields_path: Optional[str] = None) -> Set[str]:
    """Which arena halves have a booked/selected player for this realtime run.

    Reads ``players_fields.json`` written by ``/start-realtime-playback``.
    Prefer explicit ``active`` list (phase override for sequential Field A then B).
    Returns ``{"A"}``, ``{"B"}``, or ``{"A","B"}``. If the file is missing or
    empty, defaults to both fields (legacy dual behaviour).
    """
    path = players_fields_path
    if not path:
        return set(FIELD_IDS)
    try:
        if not os.path.isfile(path):
            return set(FIELD_IDS)
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle) or {}
    except Exception:
        return set(FIELD_IDS)

    active: Set[str] = set()
    # Explicit phase list wins (player writes this when running Field A / B separately)
    raw_active = payload.get("active") if isinstance(payload, dict) else None
    if isinstance(raw_active, (list, tuple)):
        for item in raw_active:
            fid = normalize_field(item)
            if fid:
                active.add(fid)
        if active:
            return active

    fields = payload.get("fields") if isinstance(payload, dict) else None
    if isinstance(fields, dict):
        for fid in FIELD_IDS:
            entry = fields.get(fid)
            if isinstance(entry, dict) and str(entry.get("player_id") or "").strip():
                active.add(fid)
    if not active:
        for entry in (payload.get("players") or []) if isinstance(payload, dict) else []:
            if not isinstance(entry, dict):
                continue
            fid = normalize_field(entry.get("field"))
            pid = str(entry.get("player_id") or "").strip()
            if fid and pid:
                active.add(fid)
    return active if active else set(FIELD_IDS)
