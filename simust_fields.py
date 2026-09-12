"""Dual Field A / Field B geometry and booking helpers for SIMUST.

Field A (left): screens 1,2,3,4,12,13,14 — QR ROI (0,0,1920,540) as x1,y1,x2,y2
Field B (right): screens 8,9,10,11,5,6,7 — QR ROI (1920,0,3840,540) as x1,y1,x2,y2
"""

from __future__ import annotations

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

FIELD_A_SCREENS: Set[str] = {"1", "2", "3", "4", "12", "13", "14"}
FIELD_B_SCREENS: Set[str] = {"8", "9", "10", "11", "5", "6", "7"}

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


def field_for_screens(screens: Sequence[str]) -> Optional[str]:
    """Infer field from QR screen list (majority / first known)."""
    cleaned = []
    for s in screens or []:
        digits = "".join(ch for ch in str(s) if ch.isdigit())
        if digits:
            cleaned.append(digits)
    if not cleaned:
        return None
    a = sum(1 for s in cleaned if s in FIELD_A_SCREENS)
    b = sum(1 for s in cleaned if s in FIELD_B_SCREENS)
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
                "aet": 5,
                "accuracy": 6,
                "efficiency": 10,
                "displacement": 11,
                "integration": (7, 9),
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
            "aet": 12,
            "accuracy": 13,
            "efficiency": 3,
            "displacement": 4,
            "integration": (14, 1, 2),
        },
    }


ALL_FIELDS = {fid: field_config(fid) for fid in FIELD_IDS}
