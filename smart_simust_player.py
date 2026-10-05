"""
smart_simust_player.py - Screen 2 coach band for image-based labeled actions.
  Foundation SF-30/60/110/180N: degree-spaced screens; digit/random: random
  screens; rotation: spin then hold; sum/sub/multiply/divide: equations on all
  screens with 2 correct targets per field. 5 tests × 10 actions, On/Gap then
  −10% each test. Fields are independent.
  Missing filler/gap → black.
"""

import sys
import os
import time
import json
import atexit
import signal
import gc
import logging
import threading
import random
import math
import re
from pathlib import Path
from typing import List, Optional, Tuple
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt, QTimer, QRect, pyqtSignal, QUrl
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QFont
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
try:
    import vlc
except ImportError:
    vlc = None
try:
    from simust_display_layout import (
        CHART_CENTER_Y,
        RESULTS_BAND_DROP,
        RING_RADIUS,
        RING_THICKNESS,
        COACH_BAND_WIDTH,
        COACH_BAND_HEIGHT,
        DISPLAY_SLICE_ORDER,
        slice_x_span,
        content_x_box,
        screen_content_offset,
        screen_content_offset_y,
    )
except ImportError:
    CHART_CENTER_Y = 140
    RESULTS_BAND_DROP = 0.10
    RING_RADIUS = 63
    RING_THICKNESS = 15
    COACH_BAND_WIDTH = 3840
    COACH_BAND_HEIGHT = 512
    DISPLAY_SLICE_ORDER = [12, 13, 14, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

    def slice_x_span(index, width=None, count=None):
        width = COACH_BAND_WIDTH if width is None else int(width)
        count = len(DISPLAY_SLICE_ORDER) if count is None else max(1, int(count))
        x0 = (int(index) * width) // count
        x1 = ((int(index) + 1) * width) // count
        return x0, max(x0 + 1, x1)

    def content_x_box(index, screen_id, width=None, count=None):
        width = COACH_BAND_WIDTH if width is None else int(width)
        count = len(DISPLAY_SLICE_ORDER) if count is None else max(1, int(count))
        x0, x1 = slice_x_span(index, width, count)
        rect_w = max(8, int((x1 - x0) * 0.92))
        center = (x0 + x1) // 2
        return center - rect_w // 2, center + rect_w // 2, rect_w

    def screen_content_offset(screen_id):
        return 0

    def screen_content_offset_y(screen_id):
        return 0
try:
    import simust_fields
except ImportError:
    simust_fields = None


def _sid(value):
    """Screen name A1–A6 or B1–B6. Old cabinet numbers are accepted too."""
    if value is None:
        return None
    text = str(value).strip().upper()
    if len(text) >= 2 and text[0] in ("A", "B") and text[1:].isdigit():
        number = int(text[1:])
        if 1 <= number <= 6:
            return f"{text[0]}{number}"
        return None
    if simust_fields is not None:
        return simust_fields.canonical_screen(value)
    return None


def _screen_sort_key(screen_id):
    """Sort A1..A6 then B1..B6. Unknown ids stay last."""
    name = _sid(screen_id) or ""
    if len(name) >= 2 and name[0] in ("A", "B") and name[1:].isdigit():
        return (0 if name[0] == "A" else 1, int(name[1:]))
    return (2, 0)


def _named_screens(values):
    """Canonical screen names. Empty gaps and unknown ids are dropped."""
    names = []
    for value in values or []:
        name = _sid(value)
        if name and name not in names and name not in DISABLED_DISPLAY_SCREENS:
            names.append(name)
    return names


def _named_image_map(mapping, active=None):
    """Screen-name → image. Legacy cabinet numbers are renamed; A1 is never int()'d."""
    out = {}
    allowed = None if active is None else set(active or [])
    for raw, path in (mapping or {}).items():
        name = _sid(raw)
        if not name or name in DISABLED_DISPLAY_SCREENS:
            continue
        if allowed is not None and _field_for_screen(name) not in allowed:
            continue
        out[name] = path
    return out


class _NullVlcPlayer:
    """No-op stand-in so image-based mode never loads/plays videos via VLC."""

    def audio_set_volume(self, *_a, **_k):
        pass

    def stop(self):
        pass

    def play(self):
        pass

    def pause(self):
        pass

    def release(self):
        pass

    def set_media(self, *_a, **_k):
        pass

    def set_time(self, *_a, **_k):
        pass

    def set_rate(self, *_a, **_k):
        pass

    def set_pause(self, *_a, **_k):
        pass

    def get_rate(self):
        return 1.0

    def get_time(self):
        return 0

    def get_length(self):
        return 0

    def get_state(self):
        return None

    def is_playing(self):
        return False

    def video_set_aspect_ratio(self, *_a, **_k):
        pass

    def video_set_scale(self, *_a, **_k):
        pass

    def video_set_crop_geometry(self, *_a, **_k):
        pass

    def set_hwnd(self, *_a, **_k):
        pass

    def set_xwindow(self, *_a, **_k):
        pass

    def set_nsobject(self, *_a, **_k):
        pass


class _NullVlcInstance:
    def media_player_new(self):
        return _NullVlcPlayer()

    def media_new(self, *_a, **_k):
        return None

    def release(self):
        pass

# ============================================================
# SETUP LOGGING
# ============================================================
LOG_DIR = "C:/Users/siama/Documents/simust_player"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "smart_player.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)
logger.info("===== SMART PLAYER STARTED (with integrated final video) =====")


def _reset_live_action_results():
    """A new play starts cue numbers again at 1. Drop the previous play's scores."""
    try:
        os.makedirs(os.path.dirname(LIVE_ACTION_RESULT_FILE), exist_ok=True)
        with open(LIVE_ACTION_RESULT_FILE, "w", encoding="utf-8") as handle:
            json.dump({"fields": {}}, handle)
    except Exception as exc:
        logger.warning("Could not reset live action results: %s", exc)

WAIT_ANIMATION_MS = 5000
PER_VIDEO_RESULTS_MS = 20000
# Level intro clip played before every test (replaces "starting" ring animation).
LEVEL_INTRO_MS = 4000
LEVEL_CARD_MS = 5000
LEVEL_INTRO_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
# Key → candidate filenames (elite file is currently misspelled "eite.mp4").
LEVEL_INTRO_FILES = {
    "foundation": ("foundation.mp4",),
    "entry": ("entry.mp4",),
    "activated": ("activated.mp4",),
    "high-performance": ("high-performance.mp4",),
    "elite": ("eite.mp4", "elite.mp4"),
    "world-class": ("world-class.mp4",),
}
_LEVEL_INTRO_PATH_RULES = (
    (re.compile(r"L00-Foundation|Foundation-Challenge", re.I), "foundation"),
    (re.compile(r"L01-Entry", re.I), "entry"),
    (re.compile(r"L02-Activated", re.I), "activated"),
    (re.compile(r"L03-HighPerformance|High[-_ ]?Performance", re.I), "high-performance"),
    (re.compile(r"L04-Elite", re.I), "elite"),
    (re.compile(r"L05-WorldClass|World[-_ ]?Class", re.I), "world-class"),
)
CURRENT_LEVEL_FILE = "C:/Users/siama/Documents/simust_player/current_level.txt"

# Image-based player: labeled assets in the foundation folder (e.g. SF-30N).
# Filenames: 1_pass_14_3.png, filler_3.png, gap_1.png
IMAGE_BASED_ACTIONS = True
FLASH_ON_MS = 1200
FLASH_OFF_MS = 500
FLASH_REPEAT = 5  # legacy teammate-flash fallback only
# Same clock as image-cue keypoints and the saved video (1.0s = 20 frames).
DISPLAY_FPS = 20.0
# 1 test × 3 actions for Foundation (SF / sum / extras) — short lab runs.
LABEL_TEST_COUNT = 1
LABEL_TIMING_DECAY = 0.90
LABEL_ACTIONS_PER_TEST = 3
# Foundation SF degree → screens-between on the field arc (30° per step).
# SF-30N: adjacent (e.g. 2,3); SF-60N: +1 between; SF-110N: +2; SF-180N: +3.
FOUNDATION_SF_GAPS = {
    "SF-30N": 0,
    "SF-60N": 1,
    "SF-110N": 2,
    "SF-180N": 3,
}
# Working arcs. Each field is screens 1–6: A4→A5→A6→A1→A2→A3 and B6→B5→B4→B3→B2→B1.
FOUNDATION_ARC_A = ["A4", "A5", "A6", "A1", "A2", "A3"]
FOUNDATION_ARC_B = ["B6", "B5", "B4", "B3", "B2", "B1"]
DISABLED_DISPLAY_SCREENS = set()
# Arena index 1–6 is the screen name on that field. Index 7 does not exist.
def _screen_name(fid: str, number) -> Optional[str]:
    try:
        n = int(number)
    except (TypeError, ValueError):
        return None
    if n < 1 or n > 6:
        return None
    return f"{str(fid).upper()[:1]}{n}"
# Scripted SF: 3 tests × 10 actions. On=3.0s, Gap=0.5s, fixed (no speed scale).
SF_SCRIPTED_ON_MS = 3000
SF_SCRIPTED_GAP_MS = 500
SF110N_GAP_MS = SF_SCRIPTED_GAP_MS  # alias

_SF30_T1 = [(1, 1), (2, 2)] * 5
_SF30_T2 = [(3, 3), (2, 2)] * 5
_SF60_T1 = [(1, 1), (3, 3)] * 5
_SF60_T2 = [(6, 6), (4, 4)] * 5
_SF110_T1 = [
    (5, 5), (3, 3), (6, 6), (3, 3), (1, 1),
    (3, 3), (5, 5), (2, 2), (5, 5), (2, 2),
]
_SF180_T1 = [
    (1, 1), (3, 3), (4, 4), (3, 3), (5, 5),
    (3, 3), (5, 5), (2, 2), (5, 5), (2, 2),
]


def _sf_three_tests(*pair_lists):
    """3 tests, 10 actions each. Extra tests reuse the last stored pair list."""
    lists = [list(p)[:10] for p in pair_lists if p]
    if not lists:
        return {}
    while len(lists) < 3:
        lists.append(list(lists[-1]))
    return {
        i: {"on_ms": SF_SCRIPTED_ON_MS, "pairs": lists[i - 1]}
        for i in range(1, 4)
    }


SF30N_SCRIPT = _sf_three_tests(_SF30_T1, _SF30_T2, _SF30_T1)
SF60N_SCRIPT = _sf_three_tests(_SF60_T1, _SF60_T2, _SF60_T1)
SF110N_SCRIPT = _sf_three_tests(_SF110_T1)
SF180N_SCRIPT = _sf_three_tests(_SF180_T1)
# Entry: 5 tests × 12 actions. Screens are named 1–6 per field.
# On starts at 3.0s and gap at 1.0s; each later test is 10% shorter.
# Floors: on 1.8s, gap 0.5s. Same pass-image / keypoint clock as Foundation.
ENTRY_TEST_COUNT = 5
ENTRY_ACTIONS_PER_TEST = 6
ENTRY_ON_START_MS = 3000
ENTRY_GAP_START_MS = 1000
ENTRY_ON_MIN_MS = 1800
ENTRY_GAP_MIN_MS = 500
ENTRY_TIMING_DECAY = 0.90
# Activated A-T1..A-T5: same 5 tests × 6 screens as Entry.
# Tests 1, 2, 4 and 5 use this order on screens 1–6. Test 3 shuffles these numbers.
# Every set repeats the numbers. Set 1 uses Entry A-T1 timing; each later set is 10% faster.
ACTIVATED_TEST_NUMBERS = {
    1: ["10", "30", "50", "60", "40", "20"],
    2: ["08", "06", "01", "11", "7", "3"],
    3: ["22", "16", "12", "17", "21", "13"],
    4: ["25", "05", "18", "07", "13", "23"],
    5: ["20", "15", "11", "17", "19", "13"],
}
# High Performance: six numbers drawn from 1..100. Lowest is passed and cleared,
# then the next lowest, for all 5 tests. One background color per test, shared
# by every screen, and a different color on the next test.
HP_NUMBER_MIN = 1
HP_NUMBER_MAX = 100
# Foundation "omid": same numbers as High Performance. The screen changes when
# the ball reaches the goal, and a faster arrival scores higher efficiency.
OMID_ON_MS = 8000
OMID_GAP_MS = 80
OMID2_BUDGET_MS = 17000
HP_TEST_BG = {
    1: (21, 101, 192),
    2: (46, 125, 50),
    3: (239, 108, 0),
    4: (106, 27, 154),
    5: (183, 28, 28),
}
# Elite and World Class: Field A and Field B are one field, screens 1–12.
# Each test places 12 of these 22 numbers. The lowest remaining number is the pass.
ELITE_NUMBER_POOL = (
    "01", "03", "05", "07", "08", "10", "11", "12", "13", "15",
    "16", "17", "18", "19", "20", "21", "22", "23", "25", "30",
    "40", "50",
)
ELITE_ACTIONS_PER_TEST = 12
ELITE_ON_START_MS = 4500
ELITE_ON_MIN_MS = 2500
ELITE_GAP_MS = 500
ELITE_ZERO_COLOR = (255, 152, 0)
# Background changes every test. The digit color changes with it and stays readable.
ELITE_TEST_BG = {
    1: (8, 24, 90),
    2: (0, 55, 28),
    3: (48, 8, 72),
    4: (90, 8, 12),
    5: (0, 48, 52),
}
ELITE_DIGIT_ON_BG = {
    1: (255, 235, 59),
    2: (255, 255, 255),
    3: (0, 229, 255),
    4: (187, 222, 251),
    5: (178, 255, 89),
}
WORLD_DIGIT_COLORS = (
    (255, 255, 255),
    (255, 235, 59),
    (0, 229, 255),
    (255, 64, 129),
    (178, 255, 89),
    (255, 152, 0),
    (224, 64, 251),
    (129, 212, 250),
    (255, 241, 118),
    (128, 222, 234),
    (244, 143, 177),
    (255, 112, 67),
    (179, 157, 219),
    (174, 213, 129),
)
SF_SCRIPTED_PLAYLISTS = {
    "SF-30N": SF30N_SCRIPT,
    "SF-60N": SF60N_SCRIPT,
    "SF-110N": SF110N_SCRIPT,
    "SF-180N": SF180N_SCRIPT,
}
FOUNDATION_MATH_MODES = ("sum", "sub", "multiply", "divide")
try:
    from simust_cognitive import (
        FOUNDATION_COGNITIVE_MODES,
        COG_ENCODE_MS,
        COG_BLANK_MS,
        build_cognitive_playlist,
    )
except ImportError:
    FOUNDATION_COGNITIVE_MODES = ()
    COG_ENCODE_MS = 1200
    COG_BLANK_MS = 400

    def build_cognitive_playlist(*_a, **_k):
        return []

FOUNDATION_EXTRA_MODES = (
    ("digit", "random", "rotation", "omid", "omid_2")
    + FOUNDATION_MATH_MODES
    + tuple(FOUNDATION_COGNITIVE_MODES)
)
_FOUNDATION_SF_RE = re.compile(r"(SF-30N|SF-60N|SF-110N|SF-180N)", re.IGNORECASE)
_cog_alt = "|".join(
    re.escape(m) for m in (
        ("digit", "random", "rotation", "omid", "omid_2")
        + FOUNDATION_MATH_MODES
        + tuple(FOUNDATION_COGNITIVE_MODES)
    )
)
_FOUNDATION_EXTRA_RE = re.compile(
    rf"(?:^|[/\\])({_cog_alt})(?:[/\\]?)$",
    re.IGNORECASE,
)
TEAMATE_IMAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "teamate.png")
SLICE_ORDER = list(DISPLAY_SLICE_ORDER)
IMAGE_ACTION_CUE_FILE = "C:/Users/siama/Documents/simust_player/image_action_cue.json"
LIVE_ACTION_RESULT_FILE = "C:/Users/siama/Documents/simust_player/live_action_result.json"
STOP_SAVE_FILE = "C:/Users/siama/Documents/simust_player/stop_save.txt"
FLASH_TIMING_FILE = "C:/Users/siama/Documents/simust_player/teammate_flash_timing.json"
PLAYERS_FIELDS_FILE = "C:/Users/siama/Documents/simust_player/players_fields.json"
# Rotation mode: fast pass-image spin around the field arc, then hold on one screen.
ROTATION_ARC_A = list(FOUNDATION_ARC_A)  # A4→A5→A6→A1→A2→A3
ROTATION_ARC_B = list(FOUNDATION_ARC_B)  # B6→B5→B4→B3→B2→B1
ROTATION_STEP_MS = 45
ROTATION_MIN_LAPS = 2
# Math modes: equations on every field screen; exactly 2 correct targets per field.
MATH_CORRECT_PER_FIELD = 2
MATH_EQ_CACHE_DIR = "C:/Users/siama/Documents/simust_player/math_eq_cache"
MATH_OP_SYMBOL = {
    "sum": "+",
    "sub": "-",
    "multiply": "x",
    "divide": "/",
}


def _foundation_challenge_root(path: str) -> str:
    """Parent L00-Foundation-Challenge folder, even if path is …/SF-30N or …/random."""
    if not path:
        return path
    cur = os.path.normpath(str(path))
    base = os.path.basename(cur.rstrip("\\/"))
    low = base.lower()
    if low in FOUNDATION_EXTRA_MODES or _FOUNDATION_SF_RE.fullmatch(base):
        return os.path.dirname(cur)
    # Already the challenge root (or unknown)
    return cur


def _resolve_foundation_mode_dir(level_root: str, subdirectory: str = "") -> Tuple[str, str]:
    """Return (directory, mode_id) for a Foundation playlist.

    mode_id is 'random' / 'digit' / 'SF-30N' / … from the subdirectory name,
    not from whatever folder the process was launched in.
    """
    root = _foundation_challenge_root(level_root)
    sub = str(subdirectory or "").strip()
    if not sub:
        base = os.path.basename(os.path.normpath(level_root).rstrip("\\/"))
        low = base.lower()
        if low in FOUNDATION_EXTRA_MODES:
            return os.path.normpath(level_root), low
        sf = _detect_foundation_sf(level_root)
        if sf:
            return os.path.normpath(level_root), sf
        return root, ""
    cand = os.path.join(root, sub)
    if not os.path.isdir(cand):
        try:
            os.makedirs(cand, exist_ok=True)
        except Exception:
            pass
    if os.path.isdir(cand):
        return cand, sub
    return root, sub


def _read_players_fields_payload():
    try:
        if os.path.isfile(PLAYERS_FIELDS_FILE):
            with open(PLAYERS_FIELDS_FILE, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception as exc:
        logger.warning("Could not read players_fields.json: %s", exc)
    return {}


def _write_players_fields_active(active_fields):
    """Tell realtime which halves are live for this phase (A, B, or both)."""
    try:
        payload = _read_players_fields_payload()
        payload["active"] = [str(f).upper() for f in (active_fields or []) if str(f).strip()]
        os.makedirs(os.path.dirname(PLAYERS_FIELDS_FILE), exist_ok=True)
        with open(PLAYERS_FIELDS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception as exc:
        logger.warning("Could not write players_fields active: %s", exc)


def _build_separate_field_phases(level_root: str) -> List[dict]:
    """Build run phases for selected fields.

    - One field → one phase for that half only.
    - Both fields → one dual phase (both halves lit together).
      Same playlist: shared SF/random rules.
      Different playlists: independent screen rules per half in the same tests.
    """
    payload = _read_players_fields_payload()
    fields = payload.get("fields") if isinstance(payload, dict) else {}
    if not isinstance(fields, dict):
        fields = {}
    root = _foundation_challenge_root(level_root)
    slots = []
    for fid in ("A", "B"):
        entry = fields.get(fid)
        if not isinstance(entry, dict):
            continue
        if not str(entry.get("player_id") or "").strip():
            continue
        sub = str(entry.get("subdirectory") or "").strip()
        level_id = str(entry.get("level") or "").strip()
        stored_dir = str(entry.get("directory") or "").strip()
        directory, mode_id = _resolve_foundation_mode_dir(root, sub)
        if stored_dir and os.path.isdir(stored_dir) and "foundation" not in level_id.lower():
            directory = stored_dir
            mode_id = sub or os.path.basename(stored_dir)
        elif stored_dir and os.path.isdir(stored_dir) and sub:
            directory = stored_dir
            mode_id = sub
        slots.append({
            "field": fid,
            "directory": directory,
            "subdirectory": sub or mode_id,
            "mode_id": mode_id or sub,
            "level": level_id,
            "player_id": str(entry.get("player_id") or ""),
        })
    if not slots:
        try:
            import simust_fields
            active = sorted(simust_fields.load_active_fields(PLAYERS_FIELDS_FILE))
        except Exception:
            active = ["A", "B"]
        directory, mode_id = _resolve_foundation_mode_dir(level_root, "")
        return [{
            "active": active,
            "directory": directory,
            "subdirectory": mode_id,
            "mode_id": mode_id,
            "field_modes": {fid: mode_id for fid in active},
            "label": "Fields " + "+".join(active),
            "player_id": "",
        }]

    if len(slots) == 1:
        s = slots[0]
        return [{
            "active": [s["field"]],
            "directory": s["directory"],
            "subdirectory": s["subdirectory"],
            "mode_id": s["mode_id"],
            "field_modes": {s["field"]: s["mode_id"]},
            "field_levels": {s["field"]: s.get("level") or ""},
            "label": f"Field {s['field']}" + (f" [{s['subdirectory']}]" if s["subdirectory"] else ""),
            "player_id": s["player_id"],
        }]

    # Both A and B — always together so neither half stays dark.
    modes = {s["field"]: s["mode_id"] for s in slots}
    dirs = {s["field"]: s["directory"] for s in slots}
    levels = {s["field"]: s.get("level") or "" for s in slots}
    same_mode = len(set(m for m in modes.values() if m)) == 1 and all(modes.values())
    same_level = len(set(lv for lv in levels.values() if lv)) <= 1
    label_parts = [
        f"{s['field']}[{s.get('level') or s['subdirectory'] or s['mode_id'] or '?'}]"
        for s in slots
    ]
    return [{
        "active": [s["field"] for s in slots],
        "directory": dirs.get("A") or dirs.get("B") or root,
        "subdirectory": (modes.get("A") if same_mode and same_level else ""),
        "mode_id": (modes.get("A") if same_mode and same_level else "dual"),
        "field_modes": modes,
        "field_directories": dirs,
        "field_levels": levels,
        "dual_independent": (not same_mode) or (not same_level),
        "label": " + ".join(label_parts),
        "player_id": "",
    }]


def _mode_slot_factory(mode_id: str, active_fields):
    """Return make_slot(action_in_set, test_num) for SF degree or extra modes."""
    active = set(active_fields or [])
    mode = str(mode_id or "").strip()
    mode_low = mode.lower()
    if mode_low in FOUNDATION_MATH_MODES:
        return lambda *_: _math_correct_slot(active)
    if mode_low == "rotation":
        return lambda *_: _rotation_field_slot(active)
    if mode_low in FOUNDATION_EXTRA_MODES or not mode or mode_low == "dual":
        return lambda *_: _random_field_slot(active)
    sf_id = None
    if mode.upper() in FOUNDATION_SF_GAPS:
        for name in FOUNDATION_SF_GAPS:
            if name.upper() == mode.upper():
                sf_id = name
                break
    if not sf_id:
        return lambda *_: _random_field_slot(active)
    slots = _foundation_action_slots(sf_id, active, LABEL_ACTIONS_PER_TEST)
    if not slots:
        return lambda *_: _random_field_slot(active)

    def _sf_slot(action_in_set, _test_num):
        return slots[(int(action_in_set) - 1) % len(slots)]

    return _sf_slot


def _band_series_num(*paths, band: str) -> Optional[int]:
    """A-T1..A-T5 inside a level band → series 1..5. Timing uses this index."""
    blob = " ".join(str(p or "") for p in paths)
    if not re.search(band, blob, re.I):
        return None
    match = re.search(r"A[-.]T([1-5])", blob, re.I)
    if not match:
        return None
    return int(match.group(1))


def _entry_series_num(*paths) -> Optional[int]:
    """A-T1..A-T5 (also A.T1.C1) → series 1..5. Time reduction uses this index."""
    return _band_series_num(*paths, band=r"L01-Entry")


def _activated_series_num(*paths) -> Optional[int]:
    return _band_series_num(*paths, band=r"L02-Activated")


def _high_performance_series_num(*paths) -> Optional[int]:
    return _band_series_num(*paths, band=r"L03-HighPerformance|High[-_ ]?Performance")


def _elite_series_num(*paths) -> Optional[int]:
    return _band_series_num(*paths, band=r"L04-Elite")


def _world_class_series_num(*paths) -> Optional[int]:
    return _band_series_num(*paths, band=r"L05-WorldClass|World[-_ ]?Class")


def _combined_level_band(text) -> Optional[str]:
    """Elite and World Class use both fields as one. World Class is checked first."""
    blob = str(text or "")
    if re.search(r"L05-WorldClass|World[-_ ]?Class", blob, re.I):
        return "world-class"
    if re.search(r"L04-Elite", blob, re.I):
        return "elite"
    return None


COMBINED_PLAY_MESSAGE = (
    "Elite and World Class need two players, one on Field A and one on Field B, "
    "both on the same Elite set or both on the same World Class set."
)


def _combined_play_decision(active, field_levels=None, field_directories=None, *extra):
    """None when this play is not Elite or World Class.

    Otherwise ("play", band, series) or ("block", message).
    One player cannot start. The two players must share one set.
    """
    active = {str(fid).upper() for fid in (active or [])}
    levels = field_levels or {}
    dirs = field_directories or {}
    found = []
    for fid in ("A", "B"):
        if fid not in active:
            continue
        text = " ".join(str(part or "") for part in (
            levels.get(fid),
            dirs.get(fid),
        ))
        band = _combined_level_band(text)
        if not band:
            continue
        series = (
            _world_class_series_num(text)
            if band == "world-class"
            else _elite_series_num(text)
        )
        found.append((band, series))
    if not found:
        blob = " ".join(str(part or "") for part in extra)
        band = _combined_level_band(blob)
        if not band:
            return None
        series = (
            _world_class_series_num(blob)
            if band == "world-class"
            else _elite_series_num(blob)
        )
        found = [(band, series)]
    bands = {band for band, _series in found}
    series_nums = {series for _band, series in found}
    ready = (
        active == {"A", "B"}
        and len(found) == 2
        and len(bands) == 1
        and len(series_nums) == 1
        and None not in series_nums
    )
    if not ready:
        return ("block", COMBINED_PLAY_MESSAGE)
    return ("play", next(iter(bands)), next(iter(series_nums)))


def _level_context_bits(level_root, video_directory, field_levels, active) -> List[str]:
    """Paths and selected level ids, so A-T timing still works if the folder was flattened."""
    bits = [str(level_root or ""), str(video_directory or "")]
    levels = field_levels or {}
    chosen = [str(levels.get(fid) or "") for fid in (active or [])]
    if any(chosen):
        bits.extend(chosen)
    else:
        bits.extend(str(value or "") for value in levels.values())
    return bits


def _entry_series_timing_ms(series_num: int) -> Tuple[int, int]:
    """A-T1 is 3.0s / 1.0s. Each later series is 10% shorter, floored at 1.8s / 0.5s."""
    decay = ENTRY_TIMING_DECAY ** (max(1, int(series_num)) - 1)
    on = max(float(ENTRY_ON_MIN_MS), float(ENTRY_ON_START_MS) * decay)
    gap = max(float(ENTRY_GAP_MIN_MS), float(ENTRY_GAP_START_MS) * decay)
    on_ms, _ = _snap_ms_to_display_fps(on)
    gap_ms, _ = _snap_ms_to_display_fps(gap)
    if on_ms < ENTRY_ON_MIN_MS:
        on_ms, _ = _snap_ms_to_display_fps(ENTRY_ON_MIN_MS)
    if gap_ms < ENTRY_GAP_MIN_MS:
        gap_ms, _ = _snap_ms_to_display_fps(ENTRY_GAP_MIN_MS)
    return on_ms, gap_ms


def _entry_test_layout(test_num: int) -> Tuple[dict, List[int]]:
    """Screen → digit, and goal screens in lowest-digit order.

    Test 1: digit N on screen N. Test 2: digit N on screen (7-N).
    Tests 3–5: digits 1–6 shuffled onto the six screens.
    """
    screens = list(range(1, 7))
    if int(test_num) == 1:
        placement = {s: s for s in screens}
    elif int(test_num) == 2:
        placement = {s: 7 - s for s in screens}
    else:
        digits = screens[:]
        random.shuffle(digits)
        placement = {screens[i]: digits[i] for i in range(6)}
    screen_of_digit = {digit: screen for screen, digit in placement.items()}
    goals = [screen_of_digit[d] for d in range(1, 7)]
    return placement, goals


def _activated_test_layout(test_num: int) -> dict:
    """Screen 1–6 → display number. Test 3 shuffles; the other tests stay in order."""
    numbers = list(ACTIVATED_TEST_NUMBERS[int(test_num)])
    if int(test_num) == 3:
        random.shuffle(numbers)
    return {screen: numbers[screen - 1] for screen in range(1, 7)}


def _high_performance_test_layout(test_num: int) -> Tuple[dict, Tuple[int, int, int]]:
    """Six different numbers from 1 to 100, and that test's shared background."""
    picked = random.sample(range(HP_NUMBER_MIN, HP_NUMBER_MAX + 1), ENTRY_ACTIONS_PER_TEST)
    placement = {screen: str(picked[screen - 1]) for screen in range(1, 7)}
    bg = HP_TEST_BG[int(test_num)]
    return placement, bg


def _lowest_first_screens(placement: dict) -> List[int]:
    """Pass order: smallest number first. Ties keep the lower screen number."""
    return sorted(placement, key=lambda screen: (int(placement[screen]), int(screen)))


def _build_number_band_playlist(
    series_num: int,
    active_fields,
    layout_for_test,
    label_prefix: str,
    bg_for_test=None,
) -> List[dict]:
    """5 tests × 6 passes. The lowest remaining number is the pass, then that screen clears.

    Field B repeats the same numbers on its own screens. Timing follows Entry:
    set 1 is 3.0s / 1.0s, and each later set is 10% faster.
    """
    active = [f for f in ("A", "B") if f in set(active_fields or [])]
    if not active:
        return []
    on_ms, gap_ms = _entry_series_timing_ms(series_num)
    playlist = []
    for test_num in range(1, ENTRY_TEST_COUNT + 1):
        laid = layout_for_test(test_num)
        if isinstance(laid, tuple):
            placement, bg = laid
        else:
            placement = laid
            bg = bg_for_test(test_num) if bg_for_test else None
        order = _lowest_first_screens(placement)
        rendered = {}
        for screen, text in placement.items():
            png = _render_entry_digit_image(str(text), bg=bg)
            if png:
                rendered[screen] = png
        for action_in_set, goal_screen in enumerate(order, start=1):
            still_up = set(order[action_in_set - 1:])
            images = {}
            for screen in still_up:
                png = rendered.get(screen)
                if not png:
                    continue
                for fid in active:
                    sid = _hw_screen_for_field(fid, (screen, screen))
                    if sid is not None:
                        images[sid] = png
            field_screens = {}
            for fid in active:
                sid = _hw_screen_for_field(fid, (goal_screen, goal_screen))
                if sid is not None:
                    field_screens[fid] = [sid]
            if not field_screens or not images:
                continue
            playlist.append({
                "kind": "labeled_action",
                "index": len(playlist) + 1,
                "test_num": test_num,
                "action_in_set": action_in_set,
                "actions_in_set": ENTRY_ACTIONS_PER_TEST,
                "is_last_in_set": action_in_set == ENTRY_ACTIONS_PER_TEST,
                "timing_scale": 1.0,
                "fixed_timing": True,
                "on_ms": on_ms,
                "gap_ms": gap_ms,
                "action_num": action_in_set,
                "action": "PASS",
                "no_fillers": True,
                "entry_digits": True,
                "arena_pair": (goal_screen, goal_screen),
                "field_screens": field_screens,
                "screen_images": dict(images),
                "gap_screen_images": dict(images),
                "label": (
                    f"{label_prefix} A-T{series_num} T{test_num}/{ENTRY_TEST_COUNT} "
                    f"a{action_in_set}/{ENTRY_ACTIONS_PER_TEST} "
                    f"goal screen {goal_screen} number {placement.get(goal_screen)} "
                    f"on={on_ms}ms gap={gap_ms}ms"
                ),
                "path": f"image://{label_prefix}/A-T{series_num}/test{test_num}/{action_in_set}",
            })
    return playlist


def finish_balls_sim_plan(test_num, action_in_set, actions_in_set) -> str:
    """Tests land 100%, 80%, 50%, 20%, then 100% of the balls."""
    try:
        number = int(test_num or 1)
        index = int(action_in_set or 0)
        total = int(actions_in_set or 0)
    except (TypeError, ValueError):
        number, index, total = 1, 0, 0
    rates = (1.00, 0.80, 0.50, 0.20, 1.00)
    rate = rates[(max(1, number) - 1) % len(rates)]
    if total <= 0:
        total = 1
    goals = int(round(total * rate))
    goals = max(0, min(total, goals))
    if index > goals:
        return "wrong"
    if index and index % 3 == 0:
        return "slow"
    return "finish"


def _stamp_finish_balls(playlist: List[dict]) -> List[dict]:
    """One clock for the test: session time × action count. The next screen starts when the ball arrives."""
    for entry in playlist or []:
        if not isinstance(entry, dict):
            continue
        try:
            actions = int(entry.get("actions_in_set") or 0)
            on_ms = int(entry.get("on_ms") or 0)
        except (TypeError, ValueError):
            continue
        if actions <= 0 or on_ms <= 0:
            continue
        budget = on_ms * actions
        entry["advance_on_goal"] = True
        entry["skip_gap"] = True
        entry["finish_balls"] = True
        entry["budget_ms"] = budget
        entry["efficiency_max_sec"] = budget / 1000.0
    return playlist


def _build_activated_playlist(series_num: int, active_fields) -> List[dict]:
    return _stamp_finish_balls(_build_number_band_playlist(
        series_num,
        active_fields,
        _activated_test_layout,
        "Activated",
    ))


def _build_high_performance_playlist(series_num: int, active_fields) -> List[dict]:
    return _stamp_finish_balls(_build_number_band_playlist(
        series_num,
        active_fields,
        _high_performance_test_layout,
        "HighPerformance",
    ))


def _build_omid_playlist(active_fields, name="omid", budget_ms=None) -> List[dict]:
    """High Performance numbers, lowest first. The next screen starts on a goal.

    budget_ms is one clock for all 6 actions. Time that runs out leaves the
    remaining actions as Wrong.
    """
    playlist = _build_number_band_playlist(
        1,
        active_fields,
        _high_performance_test_layout,
        name,
    )
    on_ms = int(budget_ms) if budget_ms else OMID_ON_MS
    for entry in playlist:
        entry["on_ms"] = on_ms
        entry["gap_ms"] = OMID_GAP_MS
        entry["advance_on_goal"] = True
        entry["skip_gap"] = True
        entry["efficiency_max_sec"] = on_ms / 1000.0
        if budget_ms:
            entry["budget_ms"] = int(budget_ms)
    return playlist


def _elite_screen_ids() -> List[str]:
    """Screens 1–12: Field A 1–6, then Field B 1–6."""
    return [f"A{n}" for n in range(1, 7)] + [f"B{n}" for n in range(1, 7)]


def _color_channel(value: float) -> float:
    value = float(value) / 255.0
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _contrast_ratio(fg, bg) -> float:
    def lum(color):
        r, g, b = (_color_channel(color[0]), _color_channel(color[1]), _color_channel(color[2]))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    light, dark = lum(fg), lum(bg)
    if dark > light:
        light, dark = dark, light
    return (light + 0.05) / (dark + 0.05)


def _colors_are_visible(fg, bg) -> bool:
    """Digit and background must differ enough to read by eye."""
    if tuple(int(v) for v in fg[:3]) == tuple(int(v) for v in bg[:3]):
        return False
    return _contrast_ratio(fg, bg) >= 4.5


def _elite_series_timing_ms(series_num: int) -> Tuple[int, int]:
    """A-T1 is 4.5s. Each later set of tests is 10% shorter, never under 2.5s. Gap stays 0.5s."""
    decay = ENTRY_TIMING_DECAY ** (max(1, int(series_num)) - 1)
    on = max(float(ELITE_ON_MIN_MS), float(ELITE_ON_START_MS) * decay)
    on_ms, _ = _snap_ms_to_display_fps(on)
    if on_ms < ELITE_ON_MIN_MS:
        on_ms, _ = _snap_ms_to_display_fps(ELITE_ON_MIN_MS)
    gap_ms, _ = _snap_ms_to_display_fps(ELITE_GAP_MS)
    return on_ms, gap_ms


def _elite_alternating_screens() -> List[str]:
    """Field A screen, then the matching Field B screen, from 1 through 6."""
    order = []
    for number in range(1, 7):
        order.append(f"A{number}")
        order.append(f"B{number}")
    return order


def _world_ordered_goals(test_num: int) -> List[str]:
    """Tests 1 and 2: screen 1, then 2, then 3, switching field every action.

    Test 1 starts on Field A. Test 2 starts on Field B, so it is not A then B again.
    """
    order = []
    for number in range(1, 7):
        if int(test_num) == 2:
            order.extend((f"B{number}", f"A{number}"))
        else:
            order.extend((f"A{number}", f"B{number}"))
    return order


def _ordered_combined_goals(test_num: int, mode: str = "elite") -> List[str]:
    """Every test follows the test 1 or test 2 line. Nothing is shuffled.

    Odd tests match test 1. Even tests match test 2.
    World Class test 2 starts on Field B and walks forward (B1, A1, B2, A2, ...).
    Elite test 2 walks that same alternating line in reverse, so it starts on B6.
    """
    pattern = 2 if int(test_num) % 2 == 0 else 1
    if str(mode) == "world-class":
        return _world_ordered_goals(pattern)
    if pattern == 2:
        return list(reversed(_elite_alternating_screens()))
    return _elite_alternating_screens()


def _elite_test_layout(test_num: int, mode: str = "elite") -> Tuple[dict, Tuple[int, int, int]]:
    """Place the first 12 pool numbers along the ordered goal line for this test."""
    order = _ordered_combined_goals(test_num, mode)
    numbers = list(ELITE_NUMBER_POOL)[:ELITE_ACTIONS_PER_TEST]
    placement = {order[i]: numbers[i] for i in range(ELITE_ACTIONS_PER_TEST)}
    bg = ELITE_TEST_BG[int(test_num)]
    return placement, bg


def _world_digit_colors(bg) -> List[Tuple[int, int, int]]:
    """Twelve colors, each different, each readable on this background."""
    chosen = []
    for color in WORLD_DIGIT_COLORS:
        if not _colors_are_visible(color, bg):
            continue
        if color in chosen:
            continue
        chosen.append(color)
        if len(chosen) == ELITE_ACTIONS_PER_TEST:
            break
    return chosen


def _build_elite_playlist(series_num: int, mode: str = "elite") -> List[dict]:
    """12 screens, one field. Lowest number is the pass, then that screen becomes 00.

    Elite: every number on a test shares one color, and 00 is always orange.
    World Class: every number has its own color, and 00 keeps that color.
    """
    world = str(mode) == "world-class"
    label_prefix = "WorldClass" if world else "Elite"
    on_ms, gap_ms = _elite_series_timing_ms(series_num)
    screens = _elite_screen_ids()
    playlist = []
    for test_num in range(1, ENTRY_TEST_COUNT + 1):
        placement, bg = _elite_test_layout(test_num, "world-class" if world else "elite")
        shared = ELITE_DIGIT_ON_BG[int(test_num)]
        if not _colors_are_visible(shared, bg) or not _colors_are_visible(ELITE_ZERO_COLOR, bg):
            logger.error("Elite colors are not readable on test %s", test_num)
            return []
        per_screen = _world_digit_colors(bg) if world else []
        if world and len(per_screen) < len(screens):
            logger.error("World Class could not color every screen on test %s", test_num)
            return []
        order = _ordered_combined_goals(test_num, "world-class" if world else "elite")
        number_png = {}
        zero_png = {}
        for index, sid in enumerate(screens):
            fg = per_screen[index] if world else shared
            zero_fg = fg if world else ELITE_ZERO_COLOR
            number_png[sid] = _render_band_digit_image(placement[sid], bg, fg)
            zero_png[sid] = _render_band_digit_image("00", bg, zero_fg)
        if any(not number_png[sid] or not zero_png[sid] for sid in screens):
            return []
        for action_in_set, goal_sid in enumerate(order, start=1):
            finished = set(order[:action_in_set - 1])
            images = {}
            for sid in screens:
                images[sid] = zero_png[sid] if sid in finished else number_png[sid]
            fid = "B" if str(goal_sid).startswith("B") else "A"
            playlist.append({
                "kind": "labeled_action",
                "index": len(playlist) + 1,
                "test_num": test_num,
                "action_in_set": action_in_set,
                "actions_in_set": ELITE_ACTIONS_PER_TEST,
                "is_last_in_set": action_in_set == ELITE_ACTIONS_PER_TEST,
                "timing_scale": 1.0,
                "fixed_timing": True,
                "on_ms": on_ms,
                "gap_ms": gap_ms,
                "action_num": action_in_set,
                "action": "PASS",
                "no_fillers": True,
                "entry_digits": True,
                "combined_field": True,
                "field_screens": {fid: [goal_sid]},
                "screen_images": dict(images),
                "gap_screen_images": dict(images),
                "label": (
                    f"{label_prefix} A-T{series_num} T{test_num}/{ENTRY_TEST_COUNT} "
                    f"a{action_in_set}/{ELITE_ACTIONS_PER_TEST} "
                    f"goal screen {goal_sid} number {placement.get(goal_sid)} "
                    f"on={on_ms}ms gap={gap_ms}ms"
                ),
                "path": f"image://{label_prefix}/A-T{series_num}/test{test_num}/{action_in_set}",
            })
    return _stamp_finish_balls(playlist)


def _script_for_mode(mode_id: str):
    key = str(mode_id or "").strip().upper()
    for name, script in SF_SCRIPTED_PLAYLISTS.items():
        if name.upper() == key:
            return script
    return None


def _hw_screen_for_field(fid: str, pair) -> Optional[str]:
    """Arena pair (A index, B index) → this field's screen name, A1–A6 or B1–B6."""
    a_arena, b_arena = int(pair[0]), int(pair[1])
    if str(fid).upper() == "A":
        return _screen_name("A", a_arena)
    return _screen_name("B", b_arena)


def _build_entry_playlist(series_num: int, active_fields) -> List[dict]:
    """5 tests × 6 actions. Digits stay up; only the finished goal number is cleared."""
    active = [f for f in ("A", "B") if f in set(active_fields or [])]
    if not active:
        return []
    on_ms, gap_ms = _entry_series_timing_ms(series_num)
    playlist = []
    for test_num in range(1, ENTRY_TEST_COUNT + 1):
        placement, goals = _entry_test_layout(test_num)
        for action_in_set, goal_screen in enumerate(goals, start=1):
            visible = {
                screen: digit
                for screen, digit in placement.items()
                if digit >= action_in_set
            }
            images = {}
            for screen, digit in visible.items():
                png = _render_entry_digit_image(str(int(digit)))
                if not png:
                    continue
                for fid in active:
                    sid = _hw_screen_for_field(fid, (screen, screen))
                    if sid is not None:
                        images[sid] = png
            field_screens = {}
            for fid in active:
                sid = _hw_screen_for_field(fid, (goal_screen, goal_screen))
                if sid is not None:
                    field_screens[fid] = [sid]
            if not field_screens or not images:
                continue
            goal_digit = placement.get(goal_screen)
            playlist.append({
                "kind": "labeled_action",
                "index": len(playlist) + 1,
                "test_num": test_num,
                "action_in_set": action_in_set,
                "actions_in_set": ENTRY_ACTIONS_PER_TEST,
                "is_last_in_set": action_in_set == ENTRY_ACTIONS_PER_TEST,
                "timing_scale": 1.0,
                "fixed_timing": True,
                "on_ms": on_ms,
                "gap_ms": gap_ms,
                "action_num": action_in_set,
                "action": "PASS",
                "no_fillers": True,
                "entry_digits": True,
                "arena_pair": (goal_screen, goal_screen),
                "field_screens": field_screens,
                "screen_images": dict(images),
                "gap_screen_images": dict(images),
                "label": (
                    f"A-T{series_num} T{test_num}/{ENTRY_TEST_COUNT} "
                    f"a{action_in_set}/{ENTRY_ACTIONS_PER_TEST} "
                    f"goal screen {goal_screen} digit {goal_digit} "
                    f"on={on_ms}ms gap={gap_ms}ms"
                ),
                "path": f"image://A-T{series_num}/test{test_num}/{action_in_set}",
            })
    return _stamp_finish_balls(playlist)


def _zip_field_action_playlists(parts: dict) -> List[dict]:
    """One timeline. Each step keeps the screens and images of every field that still has an action."""
    fields = [fid for fid in ("A", "B") if parts.get(fid)]
    if not fields:
        return []
    length = max(len(parts[fid]) for fid in fields)
    merged = []
    for index in range(length):
        field_screens = {}
        screen_images = {}
        gap_screen_images = {}
        on_ms = None
        gap_ms = None
        labels = []
        entry_digits = False
        test_num = 1
        action_in_set = index + 1
        for fid in fields:
            playlist = parts[fid]
            if index >= len(playlist):
                continue
            step = playlist[index] or {}
            owned = step.get("field_screens") or {}
            if fid in owned:
                field_screens[fid] = list(owned[fid])
            elif len(owned) == 1:
                field_screens[fid] = list(next(iter(owned.values())))
            screen_images.update(step.get("screen_images") or {})
            gap_screen_images.update(step.get("gap_screen_images") or {})
            if step.get("entry_digits"):
                entry_digits = True
            if step.get("on_ms") is not None:
                on_ms = int(step["on_ms"]) if on_ms is None else max(int(on_ms), int(step["on_ms"]))
            if step.get("gap_ms") is not None:
                gap_ms = int(step["gap_ms"]) if gap_ms is None else max(int(gap_ms), int(step["gap_ms"]))
            if step.get("label"):
                labels.append(str(step["label"]))
            test_num = step.get("test_num") or test_num
            action_in_set = step.get("action_in_set") or action_in_set
        if not field_screens or not screen_images:
            continue
        merged.append({
            "kind": "labeled_action",
            "index": len(merged) + 1,
            "test_num": test_num,
            "action_in_set": action_in_set,
            "actions_in_set": length,
            "is_last_in_set": index == length - 1,
            "timing_scale": 1.0,
            "fixed_timing": on_ms is not None,
            "on_ms": on_ms,
            "gap_ms": gap_ms,
            "action_num": action_in_set,
            "action": "PASS",
            "no_fillers": True,
            "entry_digits": entry_digits,
            "field_screens": field_screens,
            "screen_images": screen_images,
            "gap_screen_images": gap_screen_images or None,
            "advance_on_goal": any(bool((step or {}).get("advance_on_goal")) for step in (
                (parts[fid][index] if index < len(parts[fid]) else {}) for fid in fields
            )),
            "skip_gap": any(bool((step or {}).get("skip_gap")) for step in (
                (parts[fid][index] if index < len(parts[fid]) else {}) for fid in fields
            )),
            "finish_balls": any(bool((step or {}).get("finish_balls")) for step in (
                (parts[fid][index] if index < len(parts[fid]) else {}) for fid in fields
            )),
            "budget_ms": max(
                [int((step or {}).get("budget_ms") or 0) for step in (
                    (parts[fid][index] if index < len(parts[fid]) else {}) for fid in fields
                )] or [0]
            ) or None,
            "efficiency_max_sec": max(
                [float((step or {}).get("efficiency_max_sec") or 0) for step in (
                    (parts[fid][index] if index < len(parts[fid]) else {}) for fid in fields
                )] or [0]
            ) or None,
            "label": " | ".join(labels) if labels else f"fields {','.join(fields)} a{index + 1}",
            "path": f"image://independent/{index + 1}",
        })
    return merged


def _build_dual_field_playlist(
    field_modes: dict,
    field_directories: dict,
    active_fields,
    gaps: dict = None,
) -> List[dict]:
    """One shared 5×10 timeline; each field uses its own challenge screen rules."""
    active = [f for f in ("A", "B") if f in set(active_fields or [])]
    if not active:
        return []
    gaps = gaps or {}
    factories = {}
    images = {}
    for fid in active:
        mode = (field_modes or {}).get(fid) or ""
        mode_low = str(mode).strip().lower()
        directory = (field_directories or {}).get(fid) or ""
        factories[fid] = _mode_slot_factory(mode, [fid])
        if mode_low in FOUNDATION_MATH_MODES:
            images[fid] = None
            continue
        if mode_low in FOUNDATION_COGNITIVE_MODES:
            images[fid] = None
            continue
        images[fid] = _find_any_foundation_pass_image(directory)
        if not images[fid] and TEAMATE_IMAGE and os.path.isfile(TEAMATE_IMAGE):
            images[fid] = TEAMATE_IMAGE
    non_math = [
        f for f in active
        if str((field_modes or {}).get(f) or "").strip().lower()
        not in FOUNDATION_MATH_MODES
        and str((field_modes or {}).get(f) or "").strip().lower()
        not in FOUNDATION_COGNITIVE_MODES
    ]
    if non_math and not any(images.get(f) for f in non_math):
        return []

    scripts = {fid: _script_for_mode((field_modes or {}).get(fid)) for fid in active}
    if scripts and all(scripts.values()):
        test_ids = sorted(set().union(*(set(s.keys()) for s in scripts.values())))
        playlist = []
        for test_num in test_ids:
            n_actions = max(
                len((scripts[fid].get(test_num) or {}).get("pairs") or [])
                for fid in active
            )
            for action_in_set in range(1, n_actions + 1):
                field_screens = {}
                screen_images = {}
                mode_bits = []
                for fid in active:
                    pairs = list((scripts[fid].get(test_num) or {}).get("pairs") or [])
                    if action_in_set > len(pairs):
                        continue
                    sid = _hw_screen_for_field(fid, pairs[action_in_set - 1])
                    img = images.get(fid)
                    if sid is None or not img:
                        continue
                    field_screens[fid] = [sid]
                    screen_images[_sid(sid)] = img
                    mode_bits.append(f"{fid}:{(field_modes or {}).get(fid) or '?'}")
                if not screen_images:
                    continue
                lit = "_".join(
                    str(s) for sids in field_screens.values() for s in sids
                )
                playlist.append({
                    "kind": "labeled_action",
                    "index": len(playlist) + 1,
                    "test_num": test_num,
                    "action_in_set": action_in_set,
                    "actions_in_set": n_actions,
                    "is_last_in_set": action_in_set == n_actions,
                    "timing_scale": 1.0,
                    "fixed_timing": True,
                    "on_ms": SF_SCRIPTED_ON_MS,
                    "gap_ms": SF_SCRIPTED_GAP_MS,
                    "action_num": action_in_set,
                    "action": "PASS",
                    "no_fillers": True,
                    "field_screens": field_screens,
                    "screen_images": screen_images,
                    "gap_path": (
                        gaps.get(action_in_set)
                        if gaps.get(action_in_set) and os.path.isfile(gaps[action_in_set])
                        else None
                    ),
                    "label": (
                        f"dual({'|'.join(mode_bits)}) T{test_num}/{len(test_ids)} "
                        f"a{action_in_set}/{n_actions} hw_{lit}"
                    ),
                    "path": f"image://dual/test{test_num}/{action_in_set}",
                    "foundation_sf": "dual",
                })
        return _stamp_finish_balls(playlist)

    playlist = []
    for test_num in range(1, LABEL_TEST_COUNT + 1):
        scale = LABEL_TIMING_DECAY ** (test_num - 1)
        for action_in_set in range(1, LABEL_ACTIONS_PER_TEST + 1):
            field_screens = {}
            screen_images = {}
            mode_bits = []
            for fid in active:
                mode = str((field_modes or {}).get(fid) or "").strip()
                mode_low = mode.lower()
                if mode_low in FOUNDATION_MATH_MODES:
                    correct, imgs = _math_screen_layout(mode_low, fid)
                    if not correct or not imgs:
                        continue
                    field_screens[fid] = correct
                    screen_images.update(imgs)
                    mode_bits.append(f"{fid}:{mode_low}")
                    continue
                if mode_low in FOUNDATION_COGNITIVE_MODES:
                    try:
                        from simust_cognitive import build_cognitive_layout
                        correct, probe, encode, meta = build_cognitive_layout(
                            mode_low, fid, action_in_set
                        )
                    except Exception:
                        continue
                    if not probe:
                        continue
                    field_screens[fid] = _named_screens(correct or [])
                    screen_images.update(_named_image_map({k: v for k, v in probe.items() if v}))
                    mode_bits.append(f"{fid}:{mode_low}")
                    continue
                slot = factories[fid](action_in_set, test_num) or {}
                sids = _named_screens(slot.get(fid) or [])
                if not sids:
                    continue
                img = images.get(fid)
                if not img:
                    continue
                field_screens[fid] = sids
                for s in sids:
                    screen_images[s] = img
                mode_bits.append(f"{fid}:{(field_modes or {}).get(fid) or '?'}")
            if not screen_images:
                continue
            rotation_fields = [
                fid for fid in active
                if str((field_modes or {}).get(fid) or "").strip().lower() == "rotation"
            ]
            math_fields = [
                fid for fid in active
                if str((field_modes or {}).get(fid) or "").strip().lower() in FOUNDATION_MATH_MODES
            ]
            cog_fields = [
                fid for fid in active
                if str((field_modes or {}).get(fid) or "").strip().lower() in FOUNDATION_COGNITIVE_MODES
            ]
            lit = "_".join(str(s) for s in sorted(screen_images.keys(), key=_screen_sort_key)
                           if any(s in (field_screens.get(f) or []) for f in field_screens))
            # Prefer listing only correct/target screens in label
            target_ids = sorted(
                (s for sids in field_screens.values() for s in sids),
                key=_screen_sort_key,
            )
            lit = "_".join(str(s) for s in target_ids) if target_ids else lit
            entry = {
                "kind": "labeled_action",
                "index": len(playlist) + 1,
                "test_num": test_num,
                "action_in_set": action_in_set,
                "actions_in_set": LABEL_ACTIONS_PER_TEST,
                "is_last_in_set": action_in_set == LABEL_ACTIONS_PER_TEST,
                "timing_scale": scale,
                "action_num": action_in_set,
                "action": "PASS",
                "parts": [{
                    "screens": list(field_screens.get(next(iter(field_screens)), [])),
                    "path": next(iter(screen_images.values())),
                    "field": next(iter(field_screens)),
                }],
                "field_screens": field_screens,
                "screen_images": screen_images,
                "gap_path": (
                    gaps.get(action_in_set)
                    if gaps.get(action_in_set) and os.path.isfile(gaps[action_in_set])
                    else None
                ),
                "label": (
                    f"dual({'|'.join(mode_bits)}) T{test_num}/{LABEL_TEST_COUNT} "
                    f"a{action_in_set}/{LABEL_ACTIONS_PER_TEST} "
                    f"pass_{lit} x{scale:.2f}"
                ),
                "path": f"image://dual/test{test_num}/{action_in_set}",
                "foundation_sf": "dual",
            }
            if math_fields or cog_fields:
                entry["no_fillers"] = True
            if math_fields:
                entry["math_op"] = str(
                    (field_modes or {}).get(math_fields[0]) or ""
                ).lower()
            if cog_fields:
                entry["cognitive"] = str(
                    (field_modes or {}).get(cog_fields[0]) or ""
                ).lower()
            if rotation_fields:
                entry["rotation"] = True
                entry["rotation_fields"] = rotation_fields
                entry["spin_arcs"] = _spin_arcs_for_fields(rotation_fields)
            playlist.append(entry)
    return playlist


# Gap images (gap_N) appear on these slices BEFORE action N
# (gap_1 before action 1; gap_2 between action 1 and 2; …).
# Missing gap_/filler_ → black (nothing displayed on those slices).
GAP_SCREENS = ("A4", "A3", "B3", "B4")
PASS_FLASH_STEPS = (
    {"A": "A6", "B": "B6"},
    {"A": "A5", "B": "B5"},
)
_ACTION_FILE_RE = re.compile(
    r"^(\d+)[_-]([A-Za-z]+)[_-](\d+)[_-](\d+)$", re.IGNORECASE
)
_FILLER_FILE_RE = re.compile(r"^filler[_-](\d+)$", re.IGNORECASE)
_GAP_FILE_RE = re.compile(r"^gap[_-](\d+)$", re.IGNORECASE)

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def _snap_ms_to_display_fps(ms):
    """Snap wall-clock ms to whole frames at DISPLAY_FPS (30)."""
    frames = max(1, int(round(float(ms) / 1000.0 * DISPLAY_FPS)))
    return int(round(frames * 1000.0 / DISPLAY_FPS)), frames


def _read_flash_timing_ms():
    """ON / gap ms from frontend, snapped to 30 FPS frame grid."""
    on_ms = FLASH_ON_MS
    gap_ms = FLASH_OFF_MS
    try:
        if os.path.isfile(FLASH_TIMING_FILE):
            with open(FLASH_TIMING_FILE, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            if "on_ms" in data:
                on_ms = int(data["on_ms"])
            elif "on_sec" in data:
                on_ms = int(round(float(data["on_sec"]) * 1000))
            if "gap_ms" in data:
                gap_ms = int(data["gap_ms"])
            elif "gap_sec" in data:
                gap_ms = int(round(float(data["gap_sec"]) * 1000))
    except Exception as exc:
        logger.warning("Could not read teammate flash timing: %s", exc)
    on_ms = max(100, min(9900, int(on_ms)))
    gap_ms = max(100, min(9900, int(gap_ms)))
    on_ms, on_frames = _snap_ms_to_display_fps(on_ms)
    gap_ms, gap_frames = _snap_ms_to_display_fps(gap_ms)
    logger.info(
        "Flash timing @ %.0f FPS: ON %sms (%s frames), Gap %sms (%s frames)",
        DISPLAY_FPS, on_ms, on_frames, gap_ms, gap_frames,
    )
    return on_ms, gap_ms


def _screens_for_active_fields(step, active_fields):
    screens = []
    active = set(active_fields or [])
    for fid in ("A", "B"):
        if fid not in active:
            continue
        name = _sid(step.get(fid))
        if name:
            screens.append(name)
    return screens


def _field_for_screen(screen_id):
    """Field A or B from a screen name. A1 stays a name; it is not cast to int."""
    name = _sid(screen_id)
    if name and name[0] == "B":
        return "B"
    if name and name[0] == "A":
        return "A"
    if simust_fields is not None:
        return simust_fields.field_for_screens([screen_id]) or "A"
    return "A"


def _active_field_screens(active_fields):
    """All coach-band screens for the active fields, named A1–A6 and B1–B6."""
    screens = []
    for fid in ("A", "B"):
        if fid not in set(active_fields or []):
            continue
        screens.extend(_field_all_screens(fid))
    return screens


def _level_display_name(level_id: str, subdirectory: str = "") -> str:
    """Short name shown before the intro video."""
    text = f"{level_id or ''} {subdirectory or ''}"
    series = re.search(r"A[-.]T([1-9]\d*)", text, re.I)

    def with_set(name):
        if series and not str(name).upper().startswith("SF-"):
            return f"{name} A-T{series.group(1)}"
        return name

    if re.search(r"L05-WorldClass|World[-_ ]?Class", text, re.I):
        return with_set("World Class")
    if re.search(r"L04-Elite", text, re.I):
        return with_set("Elite")
    if re.search(r"L03-HighPerformance|High[-_ ]?Performance", text, re.I):
        return with_set("High Performance")
    if re.search(r"L02-Activated", text, re.I):
        return with_set("Activated")
    if re.search(r"L01-Entry", text, re.I):
        return with_set("Entry")
    if re.search(r"SF-30N|SF-60N|SF-110N|SF-180N", text, re.I):
        match = re.search(r"SF-\d+N", text, re.I)
        return match.group(0).upper() if match else "Foundation"
    if re.search(r"Foundation", text, re.I):
        return "Foundation"
    tail = str(level_id or "Test").split("/")[-1] or "Test"
    return with_set(tail)


def _opening_cards_for_fields(active, levels, modes, playlists, fallback_entry, fallback_playlist, test_num):
    """Opening name, clock, and action count for each field on its own screens."""
    cards = {}
    try:
        wanted = int(test_num or 1)
    except (TypeError, ValueError):
        wanted = 1
    for fid in active or []:
        level_id = str((levels or {}).get(fid) or "")
        mode = str((modes or {}).get(fid) or "")
        own = (playlists or {}).get(fid) or []
        playlist = own or list(fallback_playlist or [])
        field_entry = None
        for item in playlist:
            if not isinstance(item, dict):
                continue
            try:
                item_test = int(item.get("test_num") or 0)
            except (TypeError, ValueError):
                item_test = 0
            if item_test == wanted:
                field_entry = item
                break
        if field_entry is None:
            field_entry = own[0] if own else (fallback_entry or {})
        sub = mode
        if not sub and "/" in level_id:
            sub = level_id.split("/", 1)[1]
        text = _level_card_text(level_id, sub, field_entry or {}, playlist)
        background, foreground = _level_card_colors(f"{level_id} {sub}", "", {})
        cards[fid] = {
            "lines": text.split("\n"),
            "bg": background,
            "fg": foreground,
            "text": text,
        }
    return cards


def _level_card_text(level_id: str, subdirectory: str, entry: dict, playlist: list) -> str:
    """Three lines: name, total clock, and how many actions are in the test."""
    name = _level_display_name(level_id, subdirectory)
    on_ms = 0
    actions = 0
    test_num = 1
    if isinstance(entry, dict):
        try:
            on_ms = int(entry.get("on_ms") or 0)
        except (TypeError, ValueError):
            on_ms = 0
        try:
            actions = int(entry.get("actions_in_set") or 0)
        except (TypeError, ValueError):
            actions = 0
        try:
            test_num = int(entry.get("test_num") or 1)
        except (TypeError, ValueError):
            test_num = 1
    if actions <= 0:
        actions = sum(
            1 for item in (playlist or [])
            if isinstance(item, dict) and int(item.get("test_num") or 0) == test_num
        )
    lines = [name]
    total_ms = 0
    if isinstance(entry, dict) and (entry.get("finish_balls") or entry.get("budget_ms")):
        try:
            total_ms = int(entry.get("budget_ms") or 0)
        except (TypeError, ValueError):
            total_ms = 0
        if total_ms <= 0 and on_ms > 0 and actions > 0:
            total_ms = on_ms * actions
    shown_ms = total_ms or on_ms
    if shown_ms > 0:
        lines.append(f"{shown_ms / 1000.0:.2f} S")
    if actions > 0:
        lines.append(f"{actions} Actions")
    return "\n".join(lines)


def _gap_result_mark(result) -> str:
    """Word, ✔, or ✘ shown on the goal screen during the gap."""
    name = str(result or "").strip().lower()
    if name == "correct":
        return "__check__"
    if name == "wrong":
        return "__wrong__"
    if name in ("late", "miss"):
        return name
    return ""


# Same fills as CURRENT DEVELOPMENT LEVEL on the My SIMUST player page.
_LEVEL_PAGE_BG = {
    "foundation": ((125, 255, 168), (12, 28, 18)),
    "entry": ((241, 243, 245), (40, 44, 48)),
    "activated": ((175, 195, 213), (12, 22, 36)),
    "high-performance": ((49, 95, 145), (255, 255, 255)),
    "elite": ((75, 31, 120), (255, 255, 255)),
    "world-class": ((201, 162, 39), (28, 20, 4)),
}


def _level_card_colors(level_id: str, subdirectory: str, entry: dict):
    """Opening card uses that level's My SIMUST color, every test."""
    text = f"{level_id or ''} {subdirectory or ''}"
    if isinstance(entry, dict):
        text = f"{text} {entry.get('label') or ''} {entry.get('path') or ''}"
    if re.search(r"L05-WorldClass|World[-_ ]?Class", text, re.I):
        key = "world-class"
    elif re.search(r"L04-Elite", text, re.I):
        key = "elite"
    elif re.search(r"L03-HighPerformance|High[-_ ]?Performance", text, re.I):
        key = "high-performance"
    elif re.search(r"L02-Activated", text, re.I):
        key = "activated"
    elif re.search(r"L01-Entry", text, re.I):
        key = "entry"
    elif re.search(r"Foundation|SF-\d+N", text, re.I):
        key = "foundation"
    else:
        key = "foundation"
    return _LEVEL_PAGE_BG[key]


def _level_intro_key_from_id(level_id: str) -> Optional[str]:
    """Map L00-Foundation / Foundation / high-performance → intro key."""
    raw = str(level_id or "").strip()
    if not raw:
        return None
    main = raw.split("/")[0].strip()
    low = main.lower().replace("_", "-").replace(" ", "-")
    aliases = {
        "l00-foundation": "foundation",
        "foundation": "foundation",
        "l01-entry": "entry",
        "entry": "entry",
        "l02-activated": "activated",
        "activated": "activated",
        "l03-highperformance": "high-performance",
        "l03-high-performance": "high-performance",
        "high-performance": "high-performance",
        "highperformance": "high-performance",
        "l04-elite": "elite",
        "elite": "elite",
        "eite": "elite",
        "l05-worldclass": "world-class",
        "l05-world-class": "world-class",
        "world-class": "world-class",
        "worldclass": "world-class",
    }
    if low in aliases:
        return aliases[low]
    for pat, key in _LEVEL_INTRO_PATH_RULES:
        if pat.search(main):
            return key
    return None


def _detect_level_intro_key(directory: str = None) -> Optional[str]:
    """Resolve level intro key from current_level.txt or the play directory path."""
    try:
        if os.path.isfile(CURRENT_LEVEL_FILE):
            with open(CURRENT_LEVEL_FILE, "r", encoding="utf-8") as f:
                key = _level_intro_key_from_id(f.read().strip())
                if key:
                    return key
    except Exception:
        pass
    path = str(directory or "")
    for pat, key in _LEVEL_INTRO_PATH_RULES:
        if pat.search(path):
            return key
    return None


def _intro_video_for_key(key: Optional[str]) -> Optional[str]:
    """Return static/<level>.mp4 for an intro key such as entry or foundation."""
    if not key:
        return None
    names = LEVEL_INTRO_FILES.get(key) or ()
    for name in names:
        hit = os.path.join(LEVEL_INTRO_STATIC_DIR, name)
        if os.path.isfile(hit):
            return hit
    hit = os.path.join(LEVEL_INTRO_STATIC_DIR, f"{key}.mp4")
    if os.path.isfile(hit):
        return hit
    return None


def _find_level_intro_video(directory: str = None) -> Optional[str]:
    """Return absolute path to static/<level>.mp4 for the current level."""
    return _intro_video_for_key(_detect_level_intro_key(directory))


def _scan_label_assets(directory):
    """Parse SF-30N-style labeled images from a foundation subdirectory."""
    actions = {}
    fillers = {}
    gaps = {}
    if not directory or not os.path.isdir(directory):
        return actions, fillers, gaps
    image_ext = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    try:
        entries = os.listdir(directory)
    except Exception as exc:
        logger.error("Could not list labeled assets in %s: %s", directory, exc)
        return actions, fillers, gaps

    for name in entries:
        full = os.path.join(directory, name)
        if not os.path.isfile(full):
            continue
        stem, ext = os.path.splitext(name)
        if ext.lower() not in image_ext:
            continue
        m = _ACTION_FILE_RE.match(stem)
        if m:
            num = int(m.group(1))
            action = m.group(2).upper()
            # Filename digits are legacy cabinet numbers (14, 3, …), not A1 names.
            screens = _named_screens((int(m.group(3)), int(m.group(4))))
            if not screens:
                continue
            field = _field_for_screen(screens[0])
            if len(screens) > 1 and _field_for_screen(screens[1]) != field and simust_fields is not None:
                field = simust_fields.field_for_screens(screens) or field
            bucket = actions.setdefault(num, {"action": action, "parts": []})
            if not bucket.get("action"):
                bucket["action"] = action
            bucket["parts"].append({
                "screens": screens,
                "path": full,
                "field": field,
                "stem": stem,
            })
            continue
        m = _FILLER_FILE_RE.match(stem)
        if m:
            fillers[int(m.group(1))] = full
            continue
        m = _GAP_FILE_RE.match(stem)
        if m:
            gaps[int(m.group(1))] = full
            continue
    return actions, fillers, gaps


def _detect_foundation_sf(directory) -> Optional[str]:
    """Return canonical SF-30N / SF-60N / SF-110N / SF-180N for Foundation folders."""
    if not directory:
        return None
    norm = os.path.normpath(str(directory)).replace("\\", "/")
    base = os.path.basename(norm.rstrip("/"))
    m = _FOUNDATION_SF_RE.search(base) or _FOUNDATION_SF_RE.search(norm)
    if not m:
        return None
    found = m.group(1).upper()
    for name in FOUNDATION_SF_GAPS:
        if name.upper() == found:
            return name
    return found


def _detect_foundation_extra_mode(directory) -> Optional[str]:
    """Return 'digit' or 'random' when the Foundation subdirectory is that mode."""
    if not directory:
        return None
    norm = os.path.normpath(str(directory)).replace("\\", "/")
    base = os.path.basename(norm.rstrip("/")).lower()
    if base in FOUNDATION_EXTRA_MODES:
        return base
    m = _FOUNDATION_EXTRA_RE.search(norm)
    return m.group(1).lower() if m else None


def _foundation_sf_id(directory) -> Optional[str]:
    return _detect_foundation_sf(directory)


def _find_foundation_pass_image(directory) -> Optional[str]:
    """One pass image in the SF/digit/random folder (any *pass* image, else first image)."""
    if not directory or not os.path.isdir(directory):
        return None
    image_ext = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    try:
        names = sorted(os.listdir(directory))
    except Exception:
        return None
    images = []
    for name in names:
        full = os.path.join(directory, name)
        if not os.path.isfile(full):
            continue
        stem, ext = os.path.splitext(name)
        if ext.lower() not in image_ext:
            continue
        if _GAP_FILE_RE.match(stem) or _FILLER_FILE_RE.match(stem):
            continue
        images.append(full)
    if not images:
        return None
    for path in images:
        if "pass" in os.path.basename(path).lower():
            return path
    for path in images:
        if _ACTION_FILE_RE.match(os.path.splitext(os.path.basename(path))[0]):
            return path
    return images[0]


def _find_pass_video(directory) -> Optional[str]:
    """Prefer pass.mp4 in this folder, then sibling Foundation folders / files/."""
    if not directory:
        return None
    cand = os.path.join(directory, "pass.mp4")
    if os.path.isfile(cand):
        return cand
    root = _foundation_challenge_root(directory)
    for name in ("pass.mp4",):
        for folder in (
            os.path.join(root, "files"),
            os.path.join(root, "SF-110N"),
            root,
        ):
            hit = os.path.join(folder, name)
            if os.path.isfile(hit):
                return hit
    # Walk siblings once
    if root and os.path.isdir(root):
        try:
            for sub in sorted(os.listdir(root)):
                hit = os.path.join(root, sub, "pass.mp4")
                if os.path.isfile(hit):
                    return hit
        except Exception:
            pass
    return None


def _build_scripted_sf_playlist(
    sf_id: str,
    script: dict,
    active_fields,
    directory,
    gaps: dict = None,
) -> List[dict]:
    """Fixed screen order + fixed On/Gap; show pass image on lit screens (no video)."""
    active = set(active_fields or [])
    if not active or not script:
        return []
    gaps = gaps or {}
    # Prefer the pass image inside this SF folder (png/jpg/jpeg), then siblings.
    pass_image = _find_foundation_pass_image(directory) or _find_any_foundation_pass_image(
        directory
    )
    if not pass_image and str(sf_id) == "A.T1.C1":
        pass_image = _render_math_equation_image("1")
    if not pass_image:
        return []
    n_tests = len(script)
    playlist = []
    for test_num in sorted(script.keys()):
        spec = script[test_num]
        on_ms = int(spec.get("on_ms") or SF_SCRIPTED_ON_MS)
        gap_ms = int(spec.get("gap_ms") or SF_SCRIPTED_GAP_MS)
        pairs = list(spec.get("pairs") or [])
        for action_in_set, pair in enumerate(pairs, start=1):
            # Scripts use arena indices 1–6, which are the screen names on each field.
            a_arena, b_arena = int(pair[0]), int(pair[1])
            a_sid = _screen_name("A", a_arena)
            b_sid = _screen_name("B", b_arena)
            field_screens = {}
            lit = []
            if "A" in active and a_sid not in DISABLED_DISPLAY_SCREENS:
                field_screens["A"] = [a_sid]
                lit.append(a_sid)
            if "B" in active and b_sid not in DISABLED_DISPLAY_SCREENS:
                field_screens["B"] = [b_sid]
                lit.append(b_sid)
            if not lit:
                continue
            screen_images = {sid: pass_image for sid in lit}
            playlist.append({
                "kind": "labeled_action",
                "index": len(playlist) + 1,
                "test_num": test_num,
                "action_in_set": action_in_set,
                "actions_in_set": len(pairs),
                "is_last_in_set": action_in_set == len(pairs),
                "timing_scale": 1.0,
                "fixed_timing": True,
                "on_ms": on_ms,
                "gap_ms": gap_ms,
                "action_num": action_in_set,
                "action": "PASS",
                "no_fillers": True,
                "screen_video": None,
                "arena_pair": (a_arena, b_arena),
                "parts": [{
                    "screens": list(lit),
                    "path": pass_image,
                    "field": next(iter(field_screens)),
                }],
                "field_screens": field_screens,
                "screen_images": screen_images,
                "gap_path": (
                    gaps.get(action_in_set)
                    if gaps.get(action_in_set) and os.path.isfile(gaps[action_in_set])
                    else None
                ),
                "label": (
                    f"{sf_id} T{test_num}/{n_tests} a{action_in_set}/{len(pairs)} "
                    f"arena_{a_arena}_{b_arena} hw_{'_'.join(str(s) for s in lit)} "
                    f"on={on_ms}ms gap={gap_ms}ms"
                ),
                "path": f"image://{sf_id}/test{test_num}/{action_in_set}",
                "foundation_sf": sf_id,
            })
    return _stamp_finish_balls(playlist)


def _build_sf110n_playlist(active_fields, directory, gaps: dict = None) -> List[dict]:
    return _build_scripted_sf_playlist(
        "SF-110N", SF110N_SCRIPT, active_fields, directory, gaps=gaps
    )


def _build_sf180n_playlist(active_fields, directory, gaps: dict = None) -> List[dict]:
    return _build_scripted_sf_playlist(
        "SF-180N", SF180N_SCRIPT, active_fields, directory, gaps=gaps
    )


def _find_any_foundation_pass_image(directory) -> Optional[str]:
    """Pass image from this folder, then sibling Foundation folders, then teamate.png."""
    direct = _find_foundation_pass_image(directory)
    if direct:
        return direct
    root = _foundation_challenge_root(directory) if directory else None
    if root and os.path.isdir(root):
        try:
            names = sorted(os.listdir(root))
        except Exception:
            names = []
        for name in names:
            sibling = os.path.join(root, name)
            if not os.path.isdir(sibling) or sibling == directory:
                continue
            hit = _find_foundation_pass_image(sibling)
            if hit:
                return hit
    if TEAMATE_IMAGE and os.path.isfile(TEAMATE_IMAGE):
        return TEAMATE_IMAGE
    return None


def _find_digit_images(directory) -> List[str]:
    """Digit assets: 0.png…9.png, digit_N.*, or any image in digit/ (fallback)."""
    if not directory or not os.path.isdir(directory):
        return []
    image_ext = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    digit_named = []
    other = []
    try:
        names = sorted(os.listdir(directory))
    except Exception:
        return []
    for name in names:
        full = os.path.join(directory, name)
        if not os.path.isfile(full):
            continue
        stem, ext = os.path.splitext(name)
        if ext.lower() not in image_ext:
            continue
        if _GAP_FILE_RE.match(stem) or _FILLER_FILE_RE.match(stem):
            continue
        low = stem.lower()
        if re.fullmatch(r"\d", stem) or re.fullmatch(r"digit[_-]?\d+", low):
            digit_named.append(full)
        else:
            other.append(full)
    return digit_named or other


def _pairs_for_degree_gap(arc, gap: int):
    """Pairs on arc with exactly `gap` screens between (includes wrap-around)."""
    n = len(arc or [])
    if n < 2:
        return []
    pairs = []
    seen = set()
    span = int(gap) + 1
    for i in range(n):
        j = (i + span) % n
        if i == j:
            continue
        a, b = arc[i], arc[j]
        key = tuple(sorted((str(a), str(b))))
        if key in seen:
            continue
        seen.add(key)
        pairs.append((a, b))
    return pairs


def _foundation_action_slots(sf_id: str, active_fields, count: int = LABEL_ACTIONS_PER_TEST):
    """Build `count` screen assignments for this SF degree and active fields.

    Single field: both lit screens are a degree-correct pair on that field's arc.
    Dual A+B: one screen on A and the mirrored screen on B (same pass image).
    """
    gap = int(FOUNDATION_SF_GAPS.get(sf_id, 0))
    active = set(active_fields or [])
    pairs_a = _pairs_for_degree_gap(FOUNDATION_ARC_A, gap)
    pairs_b = _pairs_for_degree_gap(FOUNDATION_ARC_B, gap)
    slots = []
    if "A" in active and "B" in active:
        for i in range(count):
            if pairs_a:
                sa = pairs_a[i % len(pairs_a)][0]
                try:
                    idx = FOUNDATION_ARC_A.index(sa)
                except ValueError:
                    idx = i % len(FOUNDATION_ARC_A)
                sb = FOUNDATION_ARC_B[idx % len(FOUNDATION_ARC_B)]
            else:
                idx = i % len(FOUNDATION_ARC_A)
                sa = FOUNDATION_ARC_A[idx]
                sb = FOUNDATION_ARC_B[idx % len(FOUNDATION_ARC_B)]
            slots.append({"A": [sa], "B": [sb]})
    elif "A" in active:
        src = pairs_a or [
            (FOUNDATION_ARC_A[i], FOUNDATION_ARC_A[(i + gap + 1) % len(FOUNDATION_ARC_A)])
            for i in range(len(FOUNDATION_ARC_A))
        ]
        for i in range(count):
            a, b = src[i % len(src)]
            slots.append({"A": [a, b]})
    elif "B" in active:
        src = pairs_b or [
            (FOUNDATION_ARC_B[i], FOUNDATION_ARC_B[(i + gap + 1) % len(FOUNDATION_ARC_B)])
            for i in range(len(FOUNDATION_ARC_B))
        ]
        for i in range(count):
            a, b = src[i % len(src)]
            slots.append({"B": [a, b]})
    return slots


def _random_field_slot(active_fields) -> dict:
    """Fully random lit screens on the working arc — never SF degree pairs.

    Always one random screen per active field (single or dual).
    """
    active = set(active_fields or [])
    slot = {}
    if "A" in active:
        slot["A"] = [random.choice(FOUNDATION_ARC_A)]
    if "B" in active:
        slot["B"] = [random.choice(FOUNDATION_ARC_B)]
    return slot


def _rotation_arc_for_field(fid: str) -> List[int]:
    return list(ROTATION_ARC_A if str(fid).upper() == "A" else ROTATION_ARC_B)


def _rotation_field_slot(active_fields) -> dict:
    """One random stop screen per active field on that field's rotation circle."""
    active = set(active_fields or [])
    slot = {}
    if "A" in active:
        slot["A"] = [random.choice(ROTATION_ARC_A)]
    if "B" in active:
        slot["B"] = [random.choice(ROTATION_ARC_B)]
    return slot


def _field_all_screens(fid: str) -> List[str]:
    """Every coach-band screen on Field A or Field B, named A1–A6 or B1–B6."""
    fid = str(fid).upper()[:1]
    names = []
    if simust_fields is not None:
        names = _named_screens(simust_fields.screens_for_field(fid))
    if not names:
        names = [f"{fid}{n}" for n in range(1, 7)]
    return sorted(names, key=_screen_sort_key)


def _math_correct_slot(active_fields, count: int = None) -> dict:
    """Pick MATH_CORRECT_PER_FIELD distinct target screens per active field."""
    n = int(count or MATH_CORRECT_PER_FIELD)
    active = set(active_fields or [])
    slot = {}
    for fid in ("A", "B"):
        if fid not in active:
            continue
        pool = list(_field_all_screens(fid))
        if not pool:
            continue
        k = min(n, len(pool))
        picked = random.sample(pool, k)
        random.shuffle(picked)
        slot[fid] = _named_screens(picked)
    return slot


def _math_correct_equation(op: str) -> Tuple[str, int, int, int]:
    """Return (display_text, a, b, result) for a true equation."""
    op = str(op or "sum").lower()
    sym = MATH_OP_SYMBOL.get(op, "+")
    if op == "sub":
        a = random.randint(0, 9)
        b = random.randint(0, a)
        result = a - b
        return f"{a}{sym}{b}={result}", a, b, result
    if op == "multiply":
        a = random.randint(1, 9)
        b = random.randint(1, 9)
        result = a * b
        return f"{a}{sym}{b}={result}", a, b, result
    if op == "divide":
        b = random.randint(1, 9)
        result = random.randint(1, 9)
        a = b * result
        return f"{a}{sym}{b}={result}", a, b, result
    # sum (default)
    a = random.randint(0, 9)
    b = random.randint(0, 9)
    result = a + b
    return f"{a}{sym}{b}={result}", a, b, result


def _math_wrong_equation(op: str) -> str:
    """Same operands style as correct, but an incorrect result."""
    text, a, b, right = _math_correct_equation(op)
    sym = MATH_OP_SYMBOL.get(str(op or "sum").lower(), "+")
    wrong = right
    attempts = 0
    while wrong == right and attempts < 20:
        attempts += 1
        lo = 0
        hi = max(18, right + 9)
        wrong = random.randint(lo, hi)
    return f"{a}{sym}{b}={wrong}"


def _render_math_equation_image(eq_text: str) -> Optional[str]:
    """Render equation text to a cached PNG (coach-band tile)."""
    text = str(eq_text or "").strip()
    if not text:
        return None
    try:
        os.makedirs(MATH_EQ_CACHE_DIR, exist_ok=True)
    except Exception:
        return None
    safe = re.sub(r"[^\w=+×÷−\-]+", "_", text, flags=re.UNICODE)
    path = os.path.join(MATH_EQ_CACHE_DIR, f"eq_{safe}.png")
    if os.path.isfile(path):
        return path
    try:
        from PyQt5.QtGui import QImage, QPainter, QColor, QFont, QPen
        from PyQt5.QtCore import Qt as _Qt
    except Exception:
        try:
            from PyQt5.QtGui import QImage, QPainter, QColor, QFont, QPen
            from PyQt5.QtCore import Qt as _Qt
        except Exception as exc:
            logger.warning("Cannot render math equation (no Qt): %s", exc)
            return None
    w, h = 512, 512
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor(10, 12, 18))
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    # Subtle tile frame
    painter.setPen(QPen(QColor(60, 70, 90), 4))
    painter.drawRoundedRect(12, 12, w - 24, h - 24, 24, 24)
    font = QFont("Segoe UI", 72, QFont.Bold)
    painter.setFont(font)
    painter.setPen(QColor(255, 220, 80))
    metrics = painter.fontMetrics()
    # Shrink font if equation is wide (e.g. 8×9=72)
    while metrics.width(text) > w - 40 and font.pointSize() > 28:
        font.setPointSize(font.pointSize() - 4)
        painter.setFont(font)
        metrics = painter.fontMetrics()
    tw = metrics.width(text)
    th = metrics.height()
    painter.drawText((w - tw) // 2, (h + th) // 2 - metrics.descent(), text)
    painter.end()
    if not img.save(path, "PNG"):
        return None
    return path


def _ring_value_center_y(height: int) -> int:
    """Vertical center of the number drawn inside a results ring."""
    return (
        int(CHART_CENTER_Y)
        + int(round(int(height) * float(RESULTS_BAND_DROP)))
        - 10
    )


def _draw_text_at_ring_value(painter, text, width, height):
    """Put one number on the same line as the values inside the results rings."""
    cy = _ring_value_center_y(height)
    painter.drawText(
        QtCore.QRect(0, cy - int(height), int(width), int(height) * 2),
        Qt.AlignCenter,
        str(text),
    )


def _render_band_digit_image(digit: str, bg, fg) -> Optional[str]:
    """Digit on a colored screen. fg and bg are (r, g, b) and must stay readable."""
    text = str(digit or "").strip()
    if not text or not bg or not fg:
        return None
    try:
        os.makedirs(MATH_EQ_CACHE_DIR, exist_ok=True)
    except Exception:
        return None
    br, bgc, bb = (int(bg[0]), int(bg[1]), int(bg[2]))
    fr, fg_c, fb = (int(fg[0]), int(fg[1]), int(fg[2]))
    path = os.path.join(
        MATH_EQ_CACHE_DIR,
        f"digitring_fg_{fr}_{fg_c}_{fb}_bg_{br}_{bgc}_{bb}_{text}.png",
    )
    if os.path.isfile(path):
        return path
    try:
        from PyQt5.QtGui import QImage
    except Exception as exc:
        logger.warning("Cannot render colored digit (no Qt): %s", exc)
        return None
    w, h = 512, 512
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor(br, bgc, bb, 255))
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    font = QFont("Segoe UI", 50, QFont.Bold)
    painter.setFont(font)
    painter.setPen(QColor(fr, fg_c, fb))
    _draw_text_at_ring_value(painter, text, w, h)
    painter.end()
    if not img.save(path, "PNG"):
        return None
    return path


def _render_entry_digit_image(digit: str, bg=None) -> Optional[str]:
    """Digit centered on the screen, 30% smaller than the previous 72pt size.

    bg is an (r, g, b) fill shared by every screen of a High Performance test.
    The digit is white on that fill so it stays readable. Entry and Activated
    use the same red digit.
    """
    text = str(digit or "").strip()
    if not text:
        return None
    try:
        os.makedirs(MATH_EQ_CACHE_DIR, exist_ok=True)
    except Exception:
        return None
    if bg:
        r, g, b = (int(bg[0]), int(bg[1]), int(bg[2]))
        path = os.path.join(MATH_EQ_CACHE_DIR, f"digitring_bg_{r}_{g}_{b}_{text}.png")
    else:
        r = g = b = None
        path = os.path.join(MATH_EQ_CACHE_DIR, f"digitring_red_{text}.png")
    if os.path.isfile(path):
        return path
    try:
        from PyQt5.QtGui import QImage, QPainter, QColor, QFont
    except Exception as exc:
        logger.warning("Cannot render entry digit (no Qt): %s", exc)
        return None
    w, h = 512, 512
    img = QImage(w, h, QImage.Format_ARGB32)
    if bg:
        img.fill(QColor(r, g, b, 255))
        pen = QColor(255, 255, 255)
    else:
        img.fill(QColor(0, 0, 0, 0))
        pen = QColor(255, 0, 0)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    font = QFont("Segoe UI", 50, QFont.Bold)
    painter.setFont(font)
    painter.setPen(pen)
    _draw_text_at_ring_value(painter, text, w, h)
    painter.end()
    if not img.save(path, "PNG"):
        return None
    return path


def _math_screen_layout(op: str, fid: str) -> Tuple[List[int], dict]:
    """All field screens show equations; return (correct_screens, screen_images)."""
    op = str(op or "sum").lower()
    screens = list(_field_all_screens(fid))
    if not screens:
        return [], {}
    k = min(MATH_CORRECT_PER_FIELD, len(screens))
    correct = random.sample(screens, k)
    correct_set = set(_named_screens(correct))
    screen_images = {}
    used_texts = set()
    for sid in screens:
        if sid in correct_set:
            text, _, _, _ = _math_correct_equation(op)
            # Avoid duplicate identical correct texts when possible
            tries = 0
            while text in used_texts and tries < 8:
                text, _, _, _ = _math_correct_equation(op)
                tries += 1
        else:
            text = _math_wrong_equation(op)
            tries = 0
            while text in used_texts and tries < 8:
                text = _math_wrong_equation(op)
                tries += 1
        used_texts.add(text)
        path = _render_math_equation_image(text)
        if path:
            screen_images[sid] = path
    if len(screen_images) < k:
        return [], {}
    # Only keep correct targets that actually have images
    correct_out = [s for s in correct if s in screen_images]
    if len(correct_out) < k:
        return [], {}
    return correct_out, screen_images


def _build_math_playlist(
    op: str,
    active_fields,
    gaps: dict = None,
) -> List[dict]:
    """5×10 math challenge: equations on all screens, 2 correct targets per field."""
    op = str(op or "sum").lower()
    if op not in FOUNDATION_MATH_MODES:
        return []
    active = [f for f in ("A", "B") if f in set(active_fields or [])]
    if not active:
        return []
    gaps = gaps or {}
    playlist = []
    for test_num in range(1, LABEL_TEST_COUNT + 1):
        scale = LABEL_TIMING_DECAY ** (test_num - 1)
        for action_in_set in range(1, LABEL_ACTIONS_PER_TEST + 1):
            field_screens = {}
            screen_images = {}
            for fid in active:
                correct, imgs = _math_screen_layout(op, fid)
                if not correct or not imgs:
                    continue
                field_screens[fid] = correct
                screen_images.update(imgs)
            if not field_screens or not screen_images:
                continue
            lit = "_".join(str(s) for s in sorted(
                (sid for sids in field_screens.values() for sid in sids),
                key=_screen_sort_key,
            ))
            playlist.append({
                "kind": "labeled_action",
                "index": len(playlist) + 1,
                "test_num": test_num,
                "action_in_set": action_in_set,
                "actions_in_set": LABEL_ACTIONS_PER_TEST,
                "is_last_in_set": action_in_set == LABEL_ACTIONS_PER_TEST,
                "timing_scale": scale,
                "action_num": action_in_set,
                "action": "PASS",
                "math_op": op,
                "no_fillers": True,
                "parts": [{
                    "screens": list(field_screens.get(next(iter(field_screens)), [])),
                    "path": next(iter(screen_images.values())),
                    "field": next(iter(field_screens)),
                }],
                "field_screens": field_screens,
                "screen_images": screen_images,
                "gap_path": (
                    gaps.get(action_in_set)
                    if gaps.get(action_in_set) and os.path.isfile(gaps[action_in_set])
                    else None
                ),
                "label": (
                    f"{op} T{test_num}/{LABEL_TEST_COUNT} "
                    f"a{action_in_set}/{LABEL_ACTIONS_PER_TEST} "
                    f"ok_{lit} x{scale:.2f}"
                ),
                "path": f"image://{op}/test{test_num}/{action_in_set}",
                "foundation_sf": op,
            })
    return playlist


def _spin_arcs_for_fields(field_ids) -> dict:
    return {
        str(fid).upper(): _rotation_arc_for_field(fid)
        for fid in (field_ids or [])
        if str(fid).upper() in ("A", "B")
    }


def _build_rotation_playlist(
    active_fields,
    pass_image: str,
    gaps: dict = None,
) -> List[dict]:
    """5×10: spin pass image around the field circle, stop on one screen for On time."""
    active = [f for f in ("A", "B") if f in set(active_fields or [])]
    if not active or not pass_image:
        return []
    gaps = gaps or {}
    spin_arcs = _spin_arcs_for_fields(active)
    playlist = []
    for test_num in range(1, LABEL_TEST_COUNT + 1):
        scale = LABEL_TIMING_DECAY ** (test_num - 1)
        for action_in_set in range(1, LABEL_ACTIONS_PER_TEST + 1):
            slot = _rotation_field_slot(active) or {}
            field_screens = {}
            screen_images = {}
            for fid in active:
                sids = _named_screens(slot.get(fid) or [])
                if not sids:
                    continue
                field_screens[fid] = sids
                for s in sids:
                    screen_images[s] = pass_image
            if not screen_images:
                continue
            lit = "_".join(str(s) for s in sorted(screen_images.keys(), key=_screen_sort_key))
            playlist.append({
                "kind": "labeled_action",
                "index": len(playlist) + 1,
                "test_num": test_num,
                "action_in_set": action_in_set,
                "actions_in_set": LABEL_ACTIONS_PER_TEST,
                "is_last_in_set": action_in_set == LABEL_ACTIONS_PER_TEST,
                "timing_scale": scale,
                "action_num": action_in_set,
                "action": "PASS",
                "rotation": True,
                "rotation_fields": list(active),
                "spin_arcs": spin_arcs,
                "parts": [{
                    "screens": list(screen_images.keys()),
                    "path": pass_image,
                    "field": next(iter(field_screens)),
                }],
                "field_screens": field_screens,
                "screen_images": screen_images,
                "gap_path": (
                    gaps.get(action_in_set)
                    if gaps.get(action_in_set) and os.path.isfile(gaps[action_in_set])
                    else None
                ),
                "label": (
                    f"rotation T{test_num}/{LABEL_TEST_COUNT} "
                    f"a{action_in_set}/{LABEL_ACTIONS_PER_TEST} "
                    f"stop_{lit} x{scale:.2f}"
                ),
                "path": f"image://rotation/test{test_num}/{action_in_set}",
                "foundation_sf": "rotation",
            })
    return playlist


def _build_foundation_timed_playlist(
    mode_id: str,
    active_fields,
    image_for_action,
    gaps: dict,
    make_slot,
    label_prefix: str,
) -> List[dict]:
    """5 tests × 10 actions, frontend On/Gap then −10% each test."""
    playlist = []
    for test_num in range(1, LABEL_TEST_COUNT + 1):
        scale = LABEL_TIMING_DECAY ** (test_num - 1)
        for action_in_set in range(1, LABEL_ACTIONS_PER_TEST + 1):
            slot = make_slot(action_in_set, test_num)
            if not slot:
                continue
            image_path = image_for_action(action_in_set, test_num)
            if not image_path:
                continue
            field_screens = {}
            screen_images = {}
            for fid, sids in slot.items():
                if fid not in set(active_fields or []):
                    continue
                field_screens[fid] = _named_screens(sids)
                for s in field_screens[fid]:
                    screen_images[s] = image_path
            if not screen_images:
                continue
            lit = "_".join(str(s) for s in sorted(screen_images.keys(), key=_screen_sort_key))
            playlist.append({
                "kind": "labeled_action",
                "index": len(playlist) + 1,
                "test_num": test_num,
                "action_in_set": action_in_set,
                "actions_in_set": LABEL_ACTIONS_PER_TEST,
                "is_last_in_set": action_in_set == LABEL_ACTIONS_PER_TEST,
                "timing_scale": scale,
                "action_num": action_in_set,
                "action": "PASS",
                "parts": [{
                    "screens": list(screen_images.keys()),
                    "path": image_path,
                    "field": next(iter(field_screens)),
                }],
                "field_screens": field_screens,
                "screen_images": screen_images,
                "gap_path": (
                    gaps.get(action_in_set)
                    if gaps.get(action_in_set) and os.path.isfile(gaps[action_in_set])
                    else None
                ),
                "label": (
                    f"{label_prefix} T{test_num}/{LABEL_TEST_COUNT} "
                    f"a{action_in_set}/{LABEL_ACTIONS_PER_TEST} "
                    f"pass_{lit} x{scale:.2f}"
                ),
                "path": f"image://{mode_id}/test{test_num}/{action_in_set}",
                "foundation_sf": mode_id,
            })
    return playlist


def _pick_filler_placements(action_num, action_screens, active_fields, fillers):
    """Place fillers on non-action screens; never reuse filler_N when action is N.

    Dual field: distribute fillers evenly across A and B free screens.
    Single field: only place on that field's free screens.
    Positions reshuffled each call.
    """
    banned = {int(action_num)}
    pool_ids = [fid for fid in fillers.keys() if int(fid) not in banned and int(fid) >= 1]
    if not pool_ids:
        pool_ids = [fid for fid in fillers.keys() if int(fid) not in banned]
    if not pool_ids:
        return {}

    free_by_field = {"A": [], "B": []}
    action_set = set(_named_screens(action_screens))
    for sid in _active_field_screens(active_fields):
        if sid in action_set:
            continue
        free_by_field[_field_for_screen(sid)].append(sid)

    active = [f for f in ("A", "B") if f in set(active_fields or []) and free_by_field[f]]
    if not active:
        return {}

    random.shuffle(pool_ids)
    field_pools = {f: [] for f in active}
    for i, fid in enumerate(pool_ids):
        field_pools[active[i % len(active)]].append(fid)

    placements = {}
    for fid in active:
        screens = list(free_by_field[fid])
        random.shuffle(screens)
        fpool = field_pools[fid] or list(pool_ids)
        if not fpool:
            continue
        random.shuffle(fpool)
        for i, sid in enumerate(screens):
            placements[sid] = fillers[fpool[i % len(fpool)]]
    return placements


def _write_image_action_cue(active, field_screens, seq=0, force_end=False, action="PASS", on_sec=None, efficiency_max_sec=None, finish_balls=False, budget_elapsed_sec=None, budget_total_sec=None, action_in_set=None, actions_in_set=None, test_num=None):
    """Tell simust_realtime which screens are lit (no QR on canvas).

    force_end=True: sequence finished — realtime must clear keypoints now.
    on_sec: effective teammate On duration for this action (session length).
    """
    payload = {
        "active": bool(active) and not force_end,
        "force_end": bool(force_end),
        "seq": int(seq),
        "fields": {},
        "timestamp": time.time(),
    }
    if on_sec is not None:
        try:
            # Shared clocks reach 4.5s × 12 actions (54s). The first screen
            # has to stay up for whatever is left of that clock.
            payload["on_sec"] = max(0.1, min(60.0, float(on_sec)))
        except (TypeError, ValueError):
            pass
    if efficiency_max_sec is not None:
        try:
            payload["efficiency_max_sec"] = max(0.1, float(efficiency_max_sec))
        except (TypeError, ValueError):
            pass
    if finish_balls:
        payload["finish_balls"] = True
    if budget_elapsed_sec is not None:
        try:
            payload["budget_elapsed_sec"] = max(0.0, float(budget_elapsed_sec))
        except (TypeError, ValueError):
            pass
    if budget_total_sec is not None:
        try:
            payload["budget_total_sec"] = max(0.0, float(budget_total_sec))
        except (TypeError, ValueError):
            pass
    if action_in_set is not None:
        try:
            payload["action_in_set"] = int(action_in_set)
        except (TypeError, ValueError):
            pass
    if actions_in_set is not None:
        try:
            payload["actions_in_set"] = int(actions_in_set)
        except (TypeError, ValueError):
            pass
    if test_num is not None:
        try:
            payload["test_num"] = int(test_num)
        except (TypeError, ValueError):
            pass
    action_name = str(action or "PASS").strip().upper() or "PASS"
    if active and not force_end and field_screens:
        for fid, screens in field_screens.items():
            if not screens:
                continue
            payload["fields"][str(fid).upper()] = {
                "action": action_name,
                "screens": [str(s) for s in screens],
            }
    try:
        os.makedirs(os.path.dirname(IMAGE_ACTION_CUE_FILE), exist_ok=True)
        with open(IMAGE_ACTION_CUE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception as exc:
        logger.warning("Could not write image action cue: %s", exc)


def _clear_image_action_cue(force_end=False):
    try:
        _write_image_action_cue(False, {}, seq=0, force_end=force_end)
    except Exception:
        pass


class ImageActionCanvas(QtWidgets.QWidget):
    """3840×512 coach band on screen 2. Fourteen frames, Field A left, Field B right."""

    # Pass pictures are 10% smaller than the previous size (81% of the calibrator rectangle).
    # Digits and equations stay full size.
    PASS_IMAGE_SCALE = 0.81

    def __init__(self, parent=None, image_path=TEAMATE_IMAGE):
        super().__init__(parent)
        self.setStyleSheet("background-color: black;")
        self.setFixedSize(COACH_BAND_WIDTH, COACH_BAND_HEIGHT)
        self.active_screens = set()
        self._screen_pixmaps = {}  # screen_id -> QPixmap
        self._pixmap_cache = {}  # path -> QPixmap
        self._fallback = QtGui.QPixmap(image_path) if os.path.isfile(image_path) else QtGui.QPixmap()
        self._video_cap = None
        self._video_timer = None
        self._video_frame = None  # latest QPixmap from pass.mp4
        self._video_screens = set()
        self._video_groups = []  # [{cap, screens, path}]
        self._video_fill = False
        self._content_scale = 1.0
        self._summary_lines = []
        self._summary_screens = None
        self._summary_by_screen = {}
        self._summary_bg = (0, 0, 0)
        self._summary_fg = (255, 255, 255)
        self._result_badges = {}
        self._badge_anchor = "center"

    def clear(self):
        self._stop_screen_video()
        self.active_screens = set()
        self._screen_pixmaps = {}
        self._content_scale = 1.0
        self._summary_lines = []
        self._summary_screens = None
        self._summary_by_screen = {}
        self._summary_bg = (0, 0, 0)
        self._summary_fg = (255, 255, 255)
        self.update()

    def set_result_badges(self, screen_to_label, anchor=None):
        """Finish marks. '__check__' draws ✔. '__wrong__' draws ✘. 'under' sits below a 00."""
        badges = {}
        for sid, label in (screen_to_label or {}).items():
            name = _sid(sid)
            text = str(label or "").strip()
            if name and text:
                badges[name] = text
        place = anchor if anchor in ("center", "under") else getattr(self, "_badge_anchor", "center")
        if badges == getattr(self, "_result_badges", {}) and place == getattr(self, "_badge_anchor", "center"):
            return
        self._badge_anchor = place
        self._result_badges = badges
        self.update()

    def set_level_summary(self, lines, screen_ids=None, background=None, foreground=None):
        """Show the test name, time, and action count on each listed screen."""
        self._stop_screen_video()
        self.active_screens = set()
        self._screen_pixmaps = {}
        self._summary_by_screen = {}
        self._summary_lines = [str(line) for line in (lines or []) if str(line).strip()]
        chosen = {_sid(sid) for sid in (screen_ids or []) if _sid(sid)}
        self._summary_screens = chosen or None
        self._summary_bg = tuple(int(v) for v in (background or (0, 0, 0))[:3])
        self._summary_fg = tuple(int(v) for v in (foreground or (255, 255, 255))[:3])
        self._result_badges = {}
        self.update()

    def set_level_summaries(self, by_screen):
        """Different opening text and colors on each field's screens."""
        self._stop_screen_video()
        self.active_screens = set()
        self._screen_pixmaps = {}
        specs = {}
        for sid, spec in (by_screen or {}).items():
            name = _sid(sid)
            if not name or not isinstance(spec, dict):
                continue
            lines = [str(line) for line in (spec.get("lines") or []) if str(line).strip()]
            if not lines:
                continue
            specs[name] = {
                "lines": lines,
                "bg": tuple(int(v) for v in (spec.get("bg") or (0, 0, 0))[:3]),
                "fg": tuple(int(v) for v in (spec.get("fg") or (255, 255, 255))[:3]),
            }
        self._summary_by_screen = specs
        self._summary_lines = [" "] if specs else []
        self._summary_screens = set(specs) or None
        self._result_badges = {}
        self.update()

    def set_pass_screens(self, screen_ids):
        """Legacy: same fallback image on each lit screen."""
        self._stop_screen_video()
        self._summary_lines = []
        self._summary_screens = None
        self._summary_by_screen = {}
        self._result_badges = {}
        self._content_scale = self.PASS_IMAGE_SCALE
        self.active_screens = {_sid(sid) for sid in screen_ids if _sid(sid)}
        self._screen_pixmaps = {}
        for sid in self.active_screens:
            if not self._fallback.isNull():
                self._screen_pixmaps[sid] = self._fallback
        self.update()

    def set_screen_images(self, screen_to_path, scale=1.0):
        """Map screen id → image path (action, filler, or gap)."""
        self._stop_screen_video()
        self._summary_lines = []
        self._summary_screens = None
        self._summary_by_screen = {}
        self._content_scale = float(scale or 1.0)
        self._screen_pixmaps = {}
        self.active_screens = set()
        for sid, path in (screen_to_path or {}).items():
            pix = self._load_pixmap(path)
            if pix is None or pix.isNull():
                continue
            key = _sid(sid)
            if not key:
                continue
            self._screen_pixmaps[key] = pix
            self.active_screens.add(key)
        self.update()

    def set_screen_video(self, screen_ids, video_path, scale=None):
        """Play the same pass.mp4 (looping) on each listed screen tile."""
        self.set_screen_videos(
            {_sid(s): video_path for s in (screen_ids or []) if _sid(s)},
            scale=self.PASS_IMAGE_SCALE if scale is None else scale,
        )

    def set_screen_videos(self, screen_to_path, fill=False, scale=None):
        """Play a full video on each screen. Screens that share a path share one decoder."""
        self._stop_screen_video()
        self._summary_lines = []
        self._summary_screens = None
        self._summary_by_screen = {}
        self._video_fill = bool(fill)
        if scale is None:
            scale = 1.0 if fill else self.PASS_IMAGE_SCALE
        self._content_scale = float(scale)
        groups = {}
        for sid, path in (screen_to_path or {}).items():
            key = _sid(sid)
            if not key or key not in SLICE_ORDER:
                continue
            path = str(path or "")
            if not path or not os.path.isfile(path):
                continue
            groups.setdefault(os.path.abspath(path), set()).add(key)
        self._screen_pixmaps = {}
        self.active_screens = set()
        if not groups:
            self.update()
            return
        try:
            import cv2
        except Exception as exc:
            logger.warning("OpenCV unavailable for screen video: %s — falling back to still", exc)
            stills = {}
            for path, screens in groups.items():
                still = os.path.splitext(path)[0] + ".png"
                if os.path.isfile(still):
                    for sid in screens:
                        stills[sid] = still
            if stills:
                self.set_screen_images(stills, scale=self._content_scale)
            return
        fps = 25.0
        opened = []
        stills = {}
        for path, screens in groups.items():
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                logger.warning("Could not open screen video: %s", path)
                still = os.path.splitext(path)[0] + ".png"
                if os.path.isfile(still):
                    for sid in screens:
                        stills[sid] = still
                continue
            rate = float(cap.get(cv2.CAP_PROP_FPS) or 0) or 25.0
            fps = max(fps, rate)
            opened.append({"cap": cap, "screens": set(screens), "path": path})
        if not opened:
            if stills:
                self.set_screen_images(stills, scale=self._content_scale)
            else:
                self.update()
            return
        self._video_groups = opened
        self._video_screens = {sid for group in opened for sid in group["screens"]}
        self._tick_screen_video()
        interval = max(20, int(round(1000.0 / fps)))
        self._video_timer = QtCore.QTimer(self)
        self._video_timer.timeout.connect(self._tick_screen_video)
        self._video_timer.start(interval)

    def _stop_screen_video(self):
        if self._video_timer is not None:
            try:
                self._video_timer.stop()
                self._video_timer.deleteLater()
            except Exception:
                pass
            self._video_timer = None
        if self._video_cap is not None:
            try:
                self._video_cap.release()
            except Exception:
                pass
            self._video_cap = None
        for group in list(getattr(self, "_video_groups", None) or []):
            try:
                group["cap"].release()
            except Exception:
                pass
        self._video_groups = []
        self._video_fill = False
        self._video_frame = None
        self._video_screens = set()

    def _tick_screen_video(self):
        groups = list(getattr(self, "_video_groups", None) or [])
        if not groups:
            return
        try:
            import cv2
            pixmaps = {}
            screens = set()
            for group in groups:
                cap = group["cap"]
                ok, frame = cap.read()
                if not ok or frame is None:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w = rgb.shape[:2]
                qimg = QtGui.QImage(
                    rgb.data, w, h, rgb.strides[0], QtGui.QImage.Format_RGB888
                ).copy()
                pix = QtGui.QPixmap.fromImage(qimg)
                for sid in group["screens"]:
                    name = _sid(sid)
                    if not name:
                        continue
                    pixmaps[name] = pix
                    screens.add(name)
            if not pixmaps:
                return
            self._video_frame = next(iter(pixmaps.values()))
            self._screen_pixmaps = pixmaps
            self._video_screens = set(screens)
            self.active_screens = set(screens)
            self.update()
        except Exception as exc:
            logger.warning("screen video frame tick failed: %s", exc)

    def _load_pixmap(self, path):
        if not path:
            return None
        key = os.path.abspath(path)
        if key in self._pixmap_cache:
            return self._pixmap_cache[key]
        if not os.path.isfile(key):
            return None
        pix = QtGui.QPixmap(key)
        if pix.isNull():
            return None
        self._pixmap_cache[key] = pix
        return pix

    def _tile_rect(self, screen_id) -> QtCore.QRect:
        name = _sid(screen_id)
        i = SLICE_ORDER.index(name)
        x0, x1 = slice_x_span(i, COACH_BAND_WIDTH, len(SLICE_ORDER))
        return QtCore.QRect(x0, 0, x1 - x0, COACH_BAND_HEIGHT)

    def _paint_level_summary(self, painter):
        """Name, time, and action count, centered on every screen."""
        by_screen = getattr(self, "_summary_by_screen", None) or {}
        lines = list(self._summary_lines or [])
        if by_screen:
            lines = [" "]
        if not lines:
            return
        chosen = getattr(self, "_summary_screens", None)
        if chosen:
            matched = [name for name in SLICE_ORDER if name and name in chosen]
            if not matched:
                chosen = None
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
        bg = getattr(self, "_summary_bg", (0, 0, 0)) or (0, 0, 0)
        fg = getattr(self, "_summary_fg", (255, 255, 255)) or (255, 255, 255)
        for name in SLICE_ORDER:
            if not name:
                continue
            if chosen is not None and name not in chosen:
                continue
            screen_lines = lines
            screen_bg = bg
            screen_fg = fg
            if by_screen:
                spec = by_screen.get(name) or {}
                screen_lines = list(spec.get("lines") or [])
                if not screen_lines:
                    continue
                screen_bg = spec.get("bg") or bg
                screen_fg = spec.get("fg") or fg
            painter.setPen(QtGui.QColor(int(screen_fg[0]), int(screen_fg[1]), int(screen_fg[2])))
            fill = QtGui.QColor(int(screen_bg[0]), int(screen_bg[1]), int(screen_bg[2]))
            index = SLICE_ORDER.index(name)
            left, _right, rect_w = content_x_box(index, name, self.width(), len(SLICE_ORDER))
            if rect_w < 8:
                continue
            rect = QtCore.QRect(left, 0, rect_w, self.height())
            painter.fillRect(rect, fill)
            lines = screen_lines
            font = QtGui.QFont("Segoe UI", 20, QtGui.QFont.Bold)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            longest = max(lines, key=len)
            while metrics.width(longest) > rect_w - 12 and font.pointSize() > 8:
                font.setPointSize(font.pointSize() - 2)
                painter.setFont(font)
                metrics = painter.fontMetrics()
            painter.setClipRect(rect)
            spacing = max(1, metrics.lineSpacing())
            mid = len(lines) // 2
            target = _ring_value_center_y(self.height()) + int(screen_content_offset_y(name) or 0)
            first_top = target - metrics.height() // 2 - mid * spacing
            for i, line in enumerate(lines):
                line_rect = QtCore.QRect(rect.left(), first_top + i * spacing, rect.width(), metrics.height())
                painter.drawText(line_rect, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter, line)
            painter.setClipping(False)

    def _mark_font(self, point):
        return QtGui.QFont("Segoe UI", max(18, int(point)), QtGui.QFont.Bold)

    def _paint_mark_glyph(self, painter, rect, glyph, color, match=None):
        side = min(rect.width(), rect.height())
        point = max(36, int(side * 0.42))
        font = self._mark_font(point)
        if match:
            probe = QtGui.QFontMetrics(font)
            tick_box = probe.tightBoundingRect(match)
            mark_box = probe.tightBoundingRect(glyph)
            tick_size = max(tick_box.width(), tick_box.height())
            mark_size = max(mark_box.width(), mark_box.height())
            if tick_size > 0 and mark_size > 0:
                font = self._mark_font(point * float(tick_size) / float(mark_size))
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(rect, QtCore.Qt.AlignCenter, glyph)

    def _paint_check_mark(self, painter, rect):
        """Green ✔ for a correct finish."""
        self._paint_mark_glyph(painter, rect, "✔", QtGui.QColor(0, 200, 80))

    def _paint_wrong_mark(self, painter, rect):
        """Red ✘, the same size as the tick."""
        self._paint_mark_glyph(painter, rect, "✘", QtGui.QColor(255, 48, 48), match="✔")

    def _paint_result_badges(self, painter):
        """Finish marks are no longer drawn on the action screens."""
        return
        badges = getattr(self, "_result_badges", None) or {}
        if not badges:
            return
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
        for name, label in badges.items():
            if not name or name not in SLICE_ORDER:
                continue
            index = SLICE_ORDER.index(name)
            left, _right, rect_w = content_x_box(index, name, self.width(), len(SLICE_ORDER))
            if rect_w < 8:
                continue
            rect = QtCore.QRect(left, 0, rect_w, self.height())
            if getattr(self, "_badge_anchor", "center") == "under":
                # 00 is centered. Keep late / miss / the OK mark beneath it.
                top = rect.top() + int(rect.height() * 0.62)
                rect = QtCore.QRect(rect.left(), top, rect.width(), max(8, rect.bottom() - top))
            painter.setClipRect(rect)
            if label == "__check__":
                self._paint_check_mark(painter, rect)
            elif label == "__wrong__":
                self._paint_wrong_mark(painter, rect)
            else:
                color = {
                    "late": QtGui.QColor(255, 152, 0),
                    "miss": QtGui.QColor(255, 82, 82),
                    "wrong": QtGui.QColor(255, 82, 82),
                }.get(label, QtGui.QColor(255, 255, 255))
                font = QtGui.QFont("Segoe UI", 54, QtGui.QFont.Bold)
                painter.setFont(font)
                metrics = painter.fontMetrics()
                while metrics.width(label) > rect_w - 16 and font.pointSize() > 18:
                    font.setPointSize(font.pointSize() - 2)
                    painter.setFont(font)
                    metrics = painter.fontMetrics()
                plate_h = metrics.height() + 28
                plate = QtCore.QRect(
                    rect.left() + 8,
                    rect.center().y() - plate_h // 2,
                    rect.width() - 16,
                    plate_h,
                )
                painter.setPen(QtCore.Qt.NoPen)
                painter.setBrush(QtGui.QColor(0, 0, 0, 170))
                painter.drawRoundedRect(plate, 10, 10)
                painter.setPen(color)
                painter.drawText(rect, QtCore.Qt.AlignCenter, label)
            painter.setClipping(False)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0))
        if self._summary_lines:
            self._paint_level_summary(painter)
            painter.end()
            return
        if not self._screen_pixmaps and not getattr(self, "_result_badges", None):
            painter.end()
            return
        for sid, pix in self._screen_pixmaps.items():
            name = _sid(sid)
            if not name or name not in SLICE_ORDER:
                continue
            index = SLICE_ORDER.index(name)
            left, _right, rect_w = content_x_box(index, name, self.width(), len(SLICE_ORDER))
            dy = screen_content_offset_y(name)
            placed = QtCore.QRect(left, 0, rect_w, self.height())
            painter.setClipRect(placed)
            if not pix.isNull():
                scale = 1.0 if self._video_fill else float(self._content_scale or 1.0)
                draw_w = max(1, int(round(rect_w * scale)))
                draw_h = max(1, int(round(self.height() * scale)))
                scaled = pix.scaled(
                    draw_w,
                    draw_h,
                    QtCore.Qt.KeepAspectRatioByExpanding,
                    QtCore.Qt.SmoothTransformation,
                )
                px = left + (rect_w - scaled.width()) // 2
                py = (self.height() - scaled.height()) // 2 + dy
                painter.drawPixmap(px, py, scaled)
            painter.setClipping(False)
        self._paint_result_badges(painter)
        painter.end()


# ============================================================
# BOUNCING BALL CLASS (for the waiting overlay)
# ============================================================
class Ball:
    """A bouncing ball with position, velocity, radius, and color."""
    def __init__(self, x, y, vx, vy, radius, color):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.radius = radius
        self.color = color

    def update(self, bounds_x, bounds_y, width, height):
        """Move ball and bounce off walls."""
        self.x += self.vx
        self.y += self.vy

        if self.x - self.radius < bounds_x:
            self.x = bounds_x + self.radius
            self.vx = -self.vx
        elif self.x + self.radius > bounds_x + width:
            self.x = bounds_x + width - self.radius
            self.vx = -self.vx

        if self.y - self.radius < bounds_y:
            self.y = bounds_y + self.radius
            self.vy = -self.vy
        elif self.y + self.radius > bounds_y + height:
            self.y = bounds_y + height - self.radius
            self.vy = -self.vy


# ============================================================
# WAITING OVERLAY – Professional with bouncing balls & text backgrounds
# ============================================================
class WaitingOverlay(QtWidgets.QWidget):
    """
    Enhanced waiting overlay with:
    - Spinning gold rings on active-field slices only (inactive half stays dark)
    - "Processing" / "Results" text on rounded, semi‑transparent backgrounds
    - 2–3 colourful bouncing balls per active tile
    - Optional status text override (for "Generating final summary…")
    """
    def __init__(self, parent=None, active_fields=None):
        super().__init__(parent)
        self.setAutoFillBackground(True)
        self.setMouseTracking(False)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.angle = 0
        self.status_text = ""          # can be set via set_status_text()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_animation)
        self.timer.start(30)

        # Slice order must match the results video
        self.slice_order = list(DISPLAY_SLICE_ORDER)
        self.num_slices = len(self.slice_order)
        self.ring_radius = RING_RADIUS
        self.active_fields = {"A", "B"}
        self.active_slice_nums = set(self.slice_order)
        self.set_active_fields(active_fields)

        # Balls per slice (will be created on first paint)
        self.balls_by_slice = None
        self.level_colors = {}

        # Audio player (optional)
        self.audio_player = QMediaPlayer()
        self.sound_file = "C:/Users/siama/Documents/simust_player/processing_answers.wav"
        if os.path.exists(self.sound_file):
            self.audio_player.setMedia(QMediaContent(QUrl.fromLocalFile(self.sound_file)))
        else:
            self.audio_player = None

    def set_active_fields(self, active_fields):
        """Limit rings/balls to the selected field(s); other half stays black."""
        active = {
            str(f).upper()
            for f in (active_fields or [])
            if str(f).strip().upper() in ("A", "B")
        }
        if not active:
            active = {"A", "B"}
        self.active_fields = active
        # Only physically existing displays (excludes screens 1 and 8)
        self.active_slice_nums = set(_active_field_screens(active))
        # Rebuild balls next paint so they stay inside the live half
        self.balls_by_slice = None
        self.update()

    def set_level_colors(self, colors):
        """Background and text colors, one pair per field, matching the opening card."""
        cleaned = {}
        for fid, pair in (colors or {}).items():
            key = str(fid or "").upper()[:1]
            if key not in ("A", "B") or not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            cleaned[key] = (
                tuple(int(v) for v in pair[0][:3]),
                tuple(int(v) for v in pair[1][:3]),
            )
        self.level_colors = cleaned
        self.update()

    def _level_qcolor(self, fid, which):
        pair = (self.level_colors or {}).get(fid)
        if not pair:
            return QColor(10, 12, 18) if which == "bg" else QColor(255, 255, 255)
        rgb = pair[0] if which == "bg" else pair[1]
        return QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]))

    def set_status_text(self, text):
        """Update the status text (shown inside the rings instead of 'Processing Results')."""
        self.status_text = text
        self.update()

    def _update_animation(self):
        self.angle = (self.angle + 5) % 360

        # Update ball positions if they exist
        if self.balls_by_slice is not None:
            w = self.width()
            h = self.height()
            if w <= 0 or h <= 0:
                return
            padding = 8
            for i, slice_num in enumerate(self.slice_order):
                if slice_num is None or slice_num not in self.active_slice_nums:
                    continue
                rect = self._opening_rect(i, slice_num)
                for ball in self.balls_by_slice[i]:
                    ball.update(
                        rect.left() + padding,
                        rect.top() + padding,
                        max(1, rect.width() - 2 * padding),
                        max(1, rect.height() - 2 * padding),
                    )

        self.update()

    def _opening_rect(self, index, slice_num):
        """Same rectangle as the opening card on this screen."""
        left, _right, rect_w = content_x_box(index, slice_num, self.width(), self.num_slices)
        return QtCore.QRect(int(left), 0, int(rect_w), max(1, self.height()))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return
        painter.fillRect(self.rect(), QColor(10, 12, 18))
        for i, slice_num in enumerate(self.slice_order):
            if slice_num is None or slice_num not in self.active_slice_nums:
                continue
            fid = "B" if str(slice_num).startswith("B") else "A"
            painter.fillRect(self._opening_rect(i, slice_num), self._level_qcolor(fid, "bg"))

        # Create balls on first paint (active slices only)
        if self.balls_by_slice is None:
            self.balls_by_slice = []
            colors = [
                QColor(255, 50, 50), QColor(50, 255, 50), QColor(50, 150, 255),
                QColor(255, 200, 50), QColor(255, 50, 200), QColor(50, 255, 200),
                QColor(255, 150, 50), QColor(200, 50, 255), QColor(100, 255, 100),
                QColor(255, 100, 100)
            ]
            for i, slice_num in enumerate(self.slice_order):
                if slice_num is None or slice_num not in self.active_slice_nums:
                    self.balls_by_slice.append([])
                    continue
                num_balls = random.randint(2, 3)
                slice_balls = []
                padding = 8
                box = self._opening_rect(i, slice_num)
                x0 = box.left() + padding
                y0 = box.top() + padding
                width = max(1, box.width() - 2 * padding)
                height = max(1, box.height() - 2 * padding)
                for _ in range(num_balls):
                    radius_ball = random.randint(6, 14)
                    vx = random.uniform(1.0, 3.0) * random.choice([-1, 1])
                    vy = random.uniform(1.0, 3.0) * random.choice([-1, 1])
                    color = random.choice(colors)
                    x = random.randint(x0 + radius_ball, x0 + width - radius_ball)
                    y = random.randint(y0 + radius_ball, y0 + height - radius_ball)
                    ball = Ball(x, y, vx, vy, radius_ball, color)
                    slice_balls.append(ball)
                self.balls_by_slice.append(slice_balls)

        # Draw each active slice only
        for i, slice_num in enumerate(self.slice_order):
            if slice_num is None or slice_num not in self.active_slice_nums:
                continue
            rect = self._opening_rect(i, slice_num)
            painter.setClipRect(rect)
            cx = rect.center().x()
            cy = CHART_CENTER_Y + screen_content_offset_y(slice_num) + int(round(h * RESULTS_BAND_DROP))

            # Ring
            radius = min(self.ring_radius, max(5, rect.width() // 2 - 4))
            if radius < 5:
                radius = 5

            # Background ring — same size and thickness as results rings
            painter.setPen(QPen(QColor(60, 60, 80), RING_THICKNESS))
            painter.drawEllipse(cx - radius, cy - radius, 2*radius, 2*radius)

            # Spinning arc
            painter.setPen(QPen(QColor(255, 193, 7), RING_THICKNESS + 2))
            painter.drawArc(
                cx - radius, cy - radius,
                2*radius, 2*radius,
                self.angle * 16, 270 * 16
            )

            # Text inside the ring
            if self.status_text:
                lines = self.status_text.split('\n')
                text1 = lines[0] if len(lines) > 0 else "Processing"
                text2 = lines[1] if len(lines) > 1 else ""
            else:
                text1 = "Processing"
                text2 = "Results"

            fid = "B" if str(slice_num).startswith("B") else "A"
            painter.setPen(self._level_qcolor(fid, "fg"))
            font = QFont("Segoe UI", 12 if text2 else 14, QFont.Bold)
            painter.setFont(font)

            metrics = painter.fontMetrics()
            tw1 = metrics.width(text1)
            th1 = metrics.height()
            if text2:
                tw2 = metrics.width(text2)
                th2 = metrics.height()
                total_text_height = th1 + th2 + 12
                y_text = cy - total_text_height // 2
                painter.drawText(cx - tw1//2, y_text + th1 + 4, text1)
                painter.drawText(cx - tw2//2, y_text + th1 + 8 + th2, text2)
            else:
                tw = metrics.width(text1)
                th = metrics.height()
                total_text_height = th + 12
                y_text = cy - total_text_height // 2
                painter.drawText(cx - tw//2, y_text + th + 6, text1)

            # Bouncing balls
            for ball in self.balls_by_slice[i]:
                painter.setBrush(QBrush(ball.color))
                painter.setPen(QPen(ball.color.darker(150), 1))
                painter.drawEllipse(int(ball.x - ball.radius),
                                    int(ball.y - ball.radius),
                                    int(2 * ball.radius),
                                    int(2 * ball.radius))

                highlight_radius = int(ball.radius * 0.3)
                if highlight_radius > 1:
                    painter.setBrush(QBrush(QColor(255, 255, 255, 180)))
                    painter.setPen(Qt.NoPen)
                    painter.drawEllipse(int(ball.x - highlight_radius * 0.5),
                                        int(ball.y - highlight_radius * 0.5),
                                        int(highlight_radius),
                                        int(highlight_radius))
            painter.setClipping(False)

    def showEvent(self, event):
        self.timer.start()
        if self.audio_player and self.audio_player.state() != QMediaPlayer.PlayingState:
            self.audio_player.play()
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        if self.audio_player:
            self.audio_player.stop()
        super().hideEvent(event)


# ============================================================
# SMART PLAYER MAIN WINDOW
# ============================================================
class SmartPlayerWindow(QtWidgets.QMainWindow):
    # Signals emit the video path (or empty string on failure)
    final_summary_done = pyqtSignal(str)
    per_video_results_ready = pyqtSignal(str)

    def __init__(self, video_directory, player_speed=1.0, screen_index=1, status_file=None):
        super().__init__()
        self.video_directory = video_directory
        self.player_speed = player_speed
        self.screen_index = screen_index
        self.video_width = COACH_BAND_WIDTH
        self.video_height = COACH_BAND_HEIGHT
        self.playlist_finished = False
        self.status_file = status_file or "C:/Users/siama/Documents/simust_player/playback_status.json"
        self.auto_close_delay = 3000
        self.close_timer = None
        self._is_closing = False
        self.video_count = 0
        self.video_start_time = 0
        self.current_video_index = 0
        self.current_video_path = None
        self.waiting_for_results = False
        self.results_timer = None
        self.video_end_called = False
        self.play_delay_timer = None
        self.is_first_video = True
        self.total_videos = 0
        self._realtime_stopped = False
        self._status_completed = False
        self._final_play_started_at = 0
        self.operator_paused = False
        self._paused_media_time = None
        self._pause_started_at = 0
        self._pending_start_after_pause = False
        self._force_close_timer = None
        self._frozen_qt_timers = []
        self.display_phase = "action"
        self._wait_started = 0.0
        self.image_based = IMAGE_BASED_ACTIONS
        self.action_timer = None
        self._action_phase = "idle"  # idle | label | flash
        self._label_phase = "action"  # gap (before action) | action
        self._flash_cycle = 0
        self._flash_phase = 0  # legacy teammate flash
        self._flash_seq = 0
        self._label_mode = False
        self._asset_fillers = {}
        self._asset_gaps = {}
        self._prestart_done = False  # "starting" wait only once per session
        self._post_results_index = None
        self._set_start_time = None
        self._phase_active = None
        self._run_phases = []
        self._phase_index = 0
        self._level_root = video_directory

        # Waiting overlay (initially None)
        self.waiting_overlay = None

        self.final_summary_done.connect(self._on_final_summary_done)
        self.per_video_results_ready.connect(self._on_per_video_results_ready)

        # Speed / control files (needed before building image playlist)
        self.speed_file_dir = "C:/Users/siama/Documents/simust_player"
        self.speed_file_path = os.path.join(self.speed_file_dir, "simust_speed.txt")
        self.pause_file_path = os.path.join(self.speed_file_dir, "pause.txt")
        self.video_index_file = os.path.join(self.speed_file_dir, "current_video_index.txt")
        try:
            os.makedirs(self.speed_file_dir, exist_ok=True)
            with open(self.speed_file_path, 'w') as f:
                f.write(str(self.player_speed))
        except:
            pass

        # Field A and Field B run as separate phases (own playlist, tests, conclusion)
        self._run_phases = _build_separate_field_phases(self._level_root)
        self._phase_index = 0
        if not self._apply_run_phase(0, fatal=True):
            return

        logger.info(
            "Separate field run: %s phase(s): %s",
            len(self._run_phases),
            " → ".join(p.get("label") or "?" for p in self._run_phases),
        )

        # VLC used for per-video / final results (action phase is teammate flash when image_based)
        vlc_args = [
            '--quiet', '--no-video-title-show', '--intf', 'dummy',
            '--aspect-ratio', f'{COACH_BAND_WIDTH}:{COACH_BAND_HEIGHT}',
            '--network-caching=300', '--file-caching=300', '--no-xlib',
            '--no-video-on-top', '--no-video-deco',
            '--scale=1', '--zoom=1', f'--crop=0:0:{COACH_BAND_WIDTH}:{COACH_BAND_HEIGHT}'
        ]
        self.instance = vlc.Instance(vlc_args)
        self.player = self.instance.media_player_new()
        self.player.audio_set_volume(100)
        if self.image_based:
            logger.info("Image-based mode: labeled/teammate images for actions; VLC for results")


        # Window
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setStyleSheet("background-color: transparent;")

        self.videoframe = QtWidgets.QFrame(self)
        self.videoframe.setStyleSheet("background-color: black; border: none;")
        self.videoframe.setFixedSize(self.video_width, self.video_height)
        self.videoframe.installEventFilter(self)

        self.image_canvas = None
        if self.image_based:
            self.image_canvas = ImageActionCanvas(self, TEAMATE_IMAGE)
            self.image_canvas.setGeometry(0, 0, self.video_width, self.video_height)
            self.image_canvas.show()
            self.image_canvas.raise_()

        # Overlays
        self.status = QtWidgets.QLabel("", self)
        self.status.setAlignment(QtCore.Qt.AlignCenter)
        self.status.setStyleSheet("background-color: rgba(10,12,18,200); color: #ffc107; font-size: 14px; padding: 8px; border-radius: 4px; font-weight: bold;")
        self.status.hide()
        self.status_timer = QtCore.QTimer(singleShot=True)
        self.status_timer.timeout.connect(self.status.hide)

        self.progress_label = QtWidgets.QLabel("", self)
        self.progress_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignBottom)
        self.progress_label.setStyleSheet("background-color: rgba(10,12,18,180); color: #ffd700; font-size: 12px; padding: 5px 10px; border-radius: 4px; font-family: monospace;")
        self.progress_label.hide()

        self.completion_label = QtWidgets.QLabel("", self)
        self.completion_label.setAlignment(QtCore.Qt.AlignCenter)
        self.completion_label.setStyleSheet("background-color: rgba(10,12,18,220); color: #ffd700; font-size: 24px; padding: 20px; border-radius: 10px; font-weight: bold;")
        self.completion_label.hide()

        self.level_card_label = QtWidgets.QLabel("", self)
        self.level_card_label.setAlignment(QtCore.Qt.AlignCenter)
        self.level_card_label.setStyleSheet(
            "background-color: rgb(21,101,192); color: white; font-size: 34px; "
            "padding: 28px 48px; border-radius: 12px; font-weight: bold; "
            "font-family: 'Segoe UI';"
        )
        self.level_card_label.hide()

        # Timers
        self.check_timer = QtCore.QTimer()
        self.check_timer.setInterval(500)
        self.check_timer.timeout.connect(self._check_video_position)

        self.speed_monitor_timer = QtCore.QTimer()
        self.speed_monitor_timer.setInterval(300)
        self.speed_monitor_timer.timeout.connect(self._check_speed_changes)
        self.speed_monitor_timer.timeout.connect(self._check_operator_pause)
        self.last_speed = player_speed
        self.last_check_time = time.time()

        self.setFocusPolicy(QtCore.Qt.StrongFocus)

        # Position on screen
        app = QtWidgets.QApplication.instance()
        screens = app.screens()
        if screens:
            if self.screen_index >= len(screens):
                self.screen_index = 0
            screen = screens[self.screen_index]
            geometry = screen.geometry()
            self.setGeometry(geometry)
            self.move(geometry.topLeft())

        self.showFullScreen()

        # Force video to top 512px
        for delay in [20, 60, 120, 250, 400, 600, 800, 1000]:
            QtCore.QTimer.singleShot(delay, self._force_top_512)

        # Embed VLC into videoframe (results playback; action may use image_canvas on top)
        if sys.platform.startswith('linux'):
            self.player.set_xwindow(self.videoframe.winId())
        elif sys.platform == "win32":
            self.player.set_hwnd(int(self.videoframe.winId()))
        elif sys.platform == "darwin":
            self.player.set_nsobject(int(self.videoframe.winId()))

        # Level intro clip before each test (replaces "starting" ring animation)
        self._begin_level_intro(0)

        self.speed_monitor_timer.start()
        self._show_playlist_status()

        atexit.register(self._force_cleanup)
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum, frame):
        logger.info("Received termination signal")
        self._force_cleanup()
        sys.exit(0)

    def _force_cleanup(self):
        if self._is_closing:
            return
        self._is_closing = True
        logger.info("Cleaning up resources...")
        try:
            if self._status_completed or self.playlist_finished:
                self._update_status_file("completed", self.total_videos, self.total_videos, "Playback completed")
            else:
                self._update_status_file("closed", self.current_video_index + 1, len(self.video_files), "Player closed")
        except:
            pass
        if not self._realtime_stopped and not self._status_completed:
            self._stop_realtime()
        try:
            self.check_timer.stop()
            self.speed_monitor_timer.stop()
            if self.close_timer:
                self.close_timer.stop()
            if self.results_timer:
                self.results_timer.stop()
            if self.play_delay_timer:
                self.play_delay_timer.stop()
            self._stop_action_timer()
            _clear_image_action_cue(force_end=True)
        except:
            pass
        try:
            self.player.stop()
            time.sleep(0.1)
            self.player.release()
        except:
            pass
        try:
            self.instance.release()
        except:
            pass
        try:
            if self.videoframe:
                self.videoframe.deleteLater()
                self.videoframe = None
        except:
            pass
        try:
            if os.path.exists(self.video_index_file):
                os.remove(self.video_index_file)
        except:
            pass
        gc.collect()

    def _auto_close(self, delay_ms=2000):
        if self.close_timer:
            self.close_timer.stop()
        self.close_timer = QtCore.QTimer(singleShot=True)
        self.close_timer.timeout.connect(self.close)
        self.close_timer.start(delay_ms)

    def _update_status_file(self, state, current_video, total_videos, message):
        try:
            status_data = {
                "state": state,
                "current_video": current_video,
                "total_videos": total_videos,
                "progress": (current_video / total_videos * 100) if total_videos > 0 else 0,
                "message": message,
                "timestamp": time.time()
            }
            with open(self.status_file, 'w') as f:
                json.dump(status_data, f)
        except Exception:
            pass

    # ====== MODIFIED: only list videos directly in the given directory (NO recursion) ======
    def _field_levels_differ(self):
        levels = getattr(self, "_phase_field_levels", None) or {}
        active = list(self._active_fields())
        chosen = [str(levels.get(fid) or "").strip() for fid in active]
        chosen = [level for level in chosen if level]
        return len(active) >= 2 and len(set(chosen)) > 1

    def _field_modes_differ(self):
        modes = getattr(self, "_phase_field_modes", None) or {}
        active = list(self._active_fields())
        chosen = [str(modes.get(fid) or "").strip().lower() for fid in active]
        chosen = [mode for mode in chosen if mode]
        return len(active) >= 2 and len(set(chosen)) > 1

    def _build_one_field_playlist(self, fid):
        """Playlist for one half, using that field's own level folder."""
        if getattr(self, "_one_field_build", False):
            return []
        saved = (
            list(self._phase_active or []),
            bool(getattr(self, "_phase_dual_independent", False)),
            self.video_directory,
            self._level_root,
            getattr(self, "_phase_mode_id", ""),
            getattr(self, "_phase_subdirectory", ""),
        )
        dirs = getattr(self, "_phase_field_directories", {}) or {}
        modes = getattr(self, "_phase_field_modes", {}) or {}
        self._one_field_build = True
        try:
            self._phase_active = [fid]
            self._phase_dual_independent = False
            directory = dirs.get(fid) or self.video_directory
            self.video_directory = directory
            self._level_root = directory
            mode = str(modes.get(fid) or "")
            self._phase_mode_id = mode
            self._phase_subdirectory = mode
            return list(self._build_image_action_playlist() or [])
        finally:
            self._one_field_build = False
            (
                self._phase_active,
                self._phase_dual_independent,
                self.video_directory,
                self._level_root,
                self._phase_mode_id,
                self._phase_subdirectory,
            ) = saved

    def _build_image_action_playlist(self):
        """Build 5 timed tests from Foundation SF degree rules or labeled assets.

        Foundation SF-30/60/110/180N: one pass image, 10 actions/test with
        degree-correct screens; digit/random: fully random screens (never SF gaps).
        Test 1 = frontend On/Gap; each later test ×0.9. Missing gap/filler → black.
        """
        active = set(self._active_fields())
        if not active:
            return []
        if not getattr(self, "_one_field_build", False):
            self._field_opening_playlists = {}

        self._playlist_block_reason = ""
        decision = _combined_play_decision(
            active,
            getattr(self, "_phase_field_levels", None),
            getattr(self, "_phase_field_directories", None),
            getattr(self, "_level_root", ""),
            self.video_directory,
            getattr(self, "_phase_mode_id", ""),
            getattr(self, "_phase_subdirectory", ""),
        )
        if decision:
            kind = decision[0]
            if kind != "play":
                self._playlist_block_reason = decision[1]
                logger.error(self._playlist_block_reason)
                self._label_mode = False
                return []
            _band, series_num = decision[1], decision[2]
            playlist = _build_elite_playlist(series_num, _band)
            if playlist:
                self._label_mode = True
                logger.info(
                    "%s A-T%s playlist: %s tests x %s actions, on=%sms gap=%sms",
                    "World Class" if _band == "world-class" else "Elite",
                    series_num,
                    ENTRY_TEST_COUNT,
                    ELITE_ACTIONS_PER_TEST,
                    playlist[0].get("on_ms"),
                    playlist[0].get("gap_ms"),
                )
                return playlist
            logger.error("%s A-T%s playlist empty", _band, series_num)
            self._label_mode = False
            return []

        if not getattr(self, "_one_field_build", False) and (
            self._field_levels_differ() or self._field_modes_differ()
        ):
            parts = {}
            for fid in ("A", "B"):
                if fid not in active:
                    continue
                parts[fid] = self._build_one_field_playlist(fid)
            self._field_opening_playlists = parts
            playlist = _zip_field_action_playlists(parts)
            if playlist:
                self._label_mode = True
                logger.info(
                    "Independent field levels: %s steps (%s)",
                    len(playlist),
                    getattr(self, "_phase_field_levels", {}),
                )
                return playlist
            logger.error(
                "Independent field playlist empty for %s",
                getattr(self, "_phase_field_levels", {}),
            )
            self._label_mode = False
            return []

        level_bits = _level_context_bits(
            getattr(self, "_level_root", ""),
            self.video_directory,
            getattr(self, "_phase_field_levels", None),
            active,
        )
        hp_num = _high_performance_series_num(*level_bits)
        if hp_num:
            playlist = _build_high_performance_playlist(hp_num, active)
            if playlist:
                self._label_mode = True
                logger.info(
                    "High Performance A-T%s playlist: %s tests x %s actions, on=%sms gap=%sms",
                    hp_num,
                    ENTRY_TEST_COUNT,
                    ENTRY_ACTIONS_PER_TEST,
                    playlist[0].get("on_ms"),
                    playlist[0].get("gap_ms"),
                )
                return playlist
            logger.error("High Performance A-T%s playlist empty", hp_num)
            self._label_mode = False
            return []

        activated_num = _activated_series_num(*level_bits)
        if activated_num:
            playlist = _build_activated_playlist(activated_num, active)
            if playlist:
                self._label_mode = True
                logger.info(
                    "Activated A-T%s playlist: %s tests x %s actions, on=%sms gap=%sms",
                    activated_num,
                    ENTRY_TEST_COUNT,
                    ENTRY_ACTIONS_PER_TEST,
                    playlist[0].get("on_ms"),
                    playlist[0].get("gap_ms"),
                )
                return playlist
            logger.error("Activated A-T%s playlist empty", activated_num)
            self._label_mode = False
            return []

        series_num = _entry_series_num(*level_bits)
        if series_num:
            playlist = _build_entry_playlist(series_num, active)
            if playlist:
                self._label_mode = True
                logger.info(
                    "A-T%s playlist: %s tests x %s actions, on=%sms gap=%sms",
                    series_num,
                    ENTRY_TEST_COUNT,
                    ENTRY_ACTIONS_PER_TEST,
                    playlist[0].get("on_ms"),
                    playlist[0].get("gap_ms"),
                )
                return playlist
            logger.error("A-T%s playlist empty", series_num)
            self._label_mode = False
            return []

        actions, fillers, gaps = _scan_label_assets(self.video_directory)
        self._asset_fillers = fillers
        self._asset_gaps = gaps

        # Dual A+B with different challenges: one timeline, independent screens per half
        if (
            getattr(self, "_phase_dual_independent", False)
            and len(active) >= 2
            and getattr(self, "_phase_field_modes", None)
        ):
            playlist = _build_dual_field_playlist(
                self._phase_field_modes,
                getattr(self, "_phase_field_directories", {}) or {},
                active,
                gaps=gaps,
            )
            if playlist:
                self._label_mode = True
                logger.info(
                    "Dual independent playlist: %s steps for modes %s",
                    len(playlist),
                    self._phase_field_modes,
                )
                return playlist
            logger.error(
                "Dual independent playlist empty for modes %s — refusing SF-only fallback",
                self._phase_field_modes,
            )
            self._label_mode = False
            return []

        # Phase subdirectory / mode_id wins over folder basename (avoids falling
        # back to SF-30N when random/ is empty or launch path was an SF folder).
        mode_hint = str(
            getattr(self, "_phase_mode_id", None)
            or getattr(self, "_phase_subdirectory", None)
            or ""
        ).strip()
        mode_low = mode_hint.lower()
        extra_mode = None
        if mode_low in FOUNDATION_EXTRA_MODES:
            extra_mode = mode_low
        else:
            extra_mode = _detect_foundation_extra_mode(self.video_directory)

        if extra_mode == "omid":
            self._label_mode = True
            playlist = _build_omid_playlist(active)
            if playlist:
                logger.info(
                    "Foundation omid playlist: %s tests x %s actions, "
                    "advance when the ball reaches the goal, max=%sms",
                    ENTRY_TEST_COUNT,
                    ENTRY_ACTIONS_PER_TEST,
                    OMID_ON_MS,
                )
                return playlist
            logger.error("Omid playlist empty")
            self._label_mode = False
            return []

        if extra_mode == "omid_2":
            self._label_mode = True
            playlist = _build_omid_playlist(active, name="omid_2", budget_ms=OMID2_BUDGET_MS)
            if playlist:
                logger.info(
                    "Foundation omid_2 playlist: %s tests x %s actions, "
                    "%sms shared for each set of 6",
                    ENTRY_TEST_COUNT,
                    ENTRY_ACTIONS_PER_TEST,
                    OMID2_BUDGET_MS,
                )
                return playlist
            logger.error("Omid_2 playlist empty")
            self._label_mode = False
            return []

        # ---- Foundation random / digit / rotation ----
        if extra_mode == "random":
            pass_image = _find_any_foundation_pass_image(self.video_directory)
            if pass_image:
                self._label_mode = True
                playlist = _build_foundation_timed_playlist(
                    "random",
                    active,
                    image_for_action=lambda *_: pass_image,
                    gaps=gaps,
                    make_slot=lambda *_: _random_field_slot(active),
                    label_prefix="random",
                )
                if playlist:
                    logger.info(
                        "Foundation random playlist: %s tests x %s actions (image=%s) from %s",
                        LABEL_TEST_COUNT,
                        LABEL_ACTIONS_PER_TEST,
                        os.path.basename(pass_image),
                        self.video_directory,
                    )
                    return playlist
            logger.error(
                "Random mode selected but no pass image found under %s "
                "(will NOT fall back to SF-30N degree pairs)",
                self.video_directory,
            )
            self._label_mode = False
            return []
        if extra_mode == "rotation":
            pass_image = _find_any_foundation_pass_image(self.video_directory)
            if pass_image:
                self._label_mode = True
                playlist = _build_rotation_playlist(active, pass_image, gaps=gaps)
                if playlist:
                    logger.info(
                        "Foundation rotation playlist: %s tests x %s actions "
                        "(spin→stop, image=%s) from %s",
                        LABEL_TEST_COUNT,
                        LABEL_ACTIONS_PER_TEST,
                        os.path.basename(pass_image),
                        self.video_directory,
                    )
                    return playlist
            logger.error(
                "Rotation mode selected but no pass image found under %s "
                "(will NOT fall back to SF-30N degree pairs)",
                self.video_directory,
            )
            self._label_mode = False
            return []
        if extra_mode in FOUNDATION_MATH_MODES:
            self._label_mode = True
            playlist = _build_math_playlist(extra_mode, active, gaps=gaps)
            if playlist:
                logger.info(
                    "Foundation %s playlist: %s tests x %s actions "
                    "(2 correct equations/field) from %s",
                    extra_mode,
                    LABEL_TEST_COUNT,
                    LABEL_ACTIONS_PER_TEST,
                    self.video_directory,
                )
                return playlist
            logger.error(
                "Math mode %s playlist empty (equation render failed?) under %s",
                extra_mode,
                self.video_directory,
            )
            self._label_mode = False
            return []
        if extra_mode in FOUNDATION_COGNITIVE_MODES:
            self._label_mode = True
            playlist = build_cognitive_playlist(
                extra_mode,
                active,
                gaps=gaps,
                test_count=LABEL_TEST_COUNT,
                actions_per_test=LABEL_ACTIONS_PER_TEST,
                timing_decay=LABEL_TIMING_DECAY,
            )
            if playlist:
                logger.info(
                    "Foundation cognitive %s playlist: %s steps from %s",
                    extra_mode,
                    len(playlist),
                    self.video_directory,
                )
                return playlist
            logger.error(
                "Cognitive mode %s playlist empty under %s",
                extra_mode,
                self.video_directory,
            )
            self._label_mode = False
            return []
        if extra_mode == "digit":
            digit_images = _find_digit_images(self.video_directory)
            pass_image = _find_any_foundation_pass_image(self.video_directory)
            pool = digit_images or ([pass_image] if pass_image else [])
            if pool:
                self._label_mode = True

                def _digit_image(action_in_set, test_num):
                    return random.choice(pool)

                playlist = _build_foundation_timed_playlist(
                    "digit",
                    active,
                    image_for_action=_digit_image,
                    gaps=gaps,
                    make_slot=lambda *_: _random_field_slot(active),
                    label_prefix="digit",
                )
                if playlist:
                    logger.info(
                        "Foundation digit playlist: %s tests x %s actions (%s images) from %s",
                        LABEL_TEST_COUNT,
                        LABEL_ACTIONS_PER_TEST,
                        len(pool),
                        self.video_directory,
                    )
                    return playlist
            logger.error(
                "Digit mode selected but no images found under %s "
                "(will NOT fall back to SF-30N degree pairs)",
                self.video_directory,
            )
            self._label_mode = False
            return []

        # ---- Foundation SF-*N: degree spacing + single pass image ----
        sf_id = None
        if mode_hint and mode_hint.upper() in FOUNDATION_SF_GAPS:
            sf_id = mode_hint.upper()
            for name in FOUNDATION_SF_GAPS:
                if name.upper() == mode_hint.upper():
                    sf_id = name
                    break
        if not sf_id:
            sf_id = _foundation_sf_id(self.video_directory)

        # SF-110N / SF-180N: fixed screen script + pass.mp4 + fixed On/Gap
        scripted_id = None
        hint_u = str(mode_hint or "").upper()
        if sf_id in SF_SCRIPTED_PLAYLISTS:
            scripted_id = sf_id
        elif hint_u in SF_SCRIPTED_PLAYLISTS:
            scripted_id = hint_u
        if scripted_id:
            script = SF_SCRIPTED_PLAYLISTS[scripted_id]
            playlist = _build_scripted_sf_playlist(
                scripted_id, script, active, self.video_directory, gaps=gaps
            )
            if playlist:
                self._label_mode = True
                on_list = [
                    f"{int(script[t]['on_ms']) / 1000:g}"
                    for t in sorted(script.keys())
                ]
                logger.info(
                    "Foundation %s scripted playlist: %s steps "
                    "(tests=%s on=%ss gap=0.5s image=%s) from %s",
                    scripted_id,
                    len(playlist),
                    len(script),
                    "/".join(on_list),
                    os.path.basename(
                        (playlist[0].get("screen_images") or {}).get(
                            next(iter(playlist[0].get("screen_images") or {}), None)
                        )
                        or playlist[0].get("parts", [{}])[0].get("path")
                        or "?"
                    ),
                    self.video_directory,
                )
                return playlist
            logger.error(
                "%s scripted playlist empty under %s (need pass image in folder)",
                scripted_id,
                self.video_directory,
            )
            self._label_mode = False
            return []

        pass_image = _find_any_foundation_pass_image(self.video_directory) if sf_id else None
        if sf_id and pass_image:
            self._label_mode = True
            slots = _foundation_action_slots(sf_id, active, LABEL_ACTIONS_PER_TEST)
            if not slots:
                self._label_mode = False
            else:
                deg = {0: 30, 1: 60, 2: 110, 3: 180}.get(FOUNDATION_SF_GAPS.get(sf_id, 0), 30)

                def _sf_image(*_):
                    return pass_image

                def _sf_slot(action_in_set, _test_num):
                    return slots[(action_in_set - 1) % len(slots)]

                playlist = _build_foundation_timed_playlist(
                    sf_id,
                    active,
                    image_for_action=_sf_image,
                    gaps=gaps,
                    make_slot=_sf_slot,
                    label_prefix=f"{sf_id} ~{deg}deg",
                )
                if playlist:
                    logger.info(
                        "Foundation %s playlist: %s tests x %s actions (gap=%s ~%sdeg, image=%s) from %s",
                        sf_id,
                        LABEL_TEST_COUNT,
                        LABEL_ACTIONS_PER_TEST,
                        FOUNDATION_SF_GAPS.get(sf_id, 0),
                        deg,
                        os.path.basename(pass_image),
                        self.video_directory,
                    )
                    return playlist
                self._label_mode = False

        if actions:
            self._label_mode = True
            # Action templates from first digit of filenames (may be < 10)
            templates = []
            for num in sorted(actions.keys()):
                info = actions[num]
                parts = []
                field_screens = {}
                screen_images = {}
                for part in info.get("parts") or []:
                    field = part.get("field") or _field_for_screen(part["screens"][0])
                    if field not in active:
                        keep = [s for s in part["screens"] if _field_for_screen(s) in active]
                        if not keep:
                            continue
                        part = dict(part)
                        part["screens"] = keep
                        part["field"] = _field_for_screen(keep[0])
                        field = part["field"]
                    parts.append(part)
                    field_screens.setdefault(field, [])
                    for s in part["screens"]:
                        name = _sid(s)
                        if not name or name in DISABLED_DISPLAY_SCREENS:
                            continue
                        if name not in field_screens[field]:
                            field_screens[field].append(name)
                        screen_images[name] = part["path"]
                if not parts:
                    continue
                action_name = str(info.get("action") or "PASS").upper()
                templates.append({
                    "action_num": num,
                    "action": action_name,
                    "parts": parts,
                    "field_screens": field_screens,
                    "screen_images": screen_images,
                    "gap_path": gaps.get(num) if gaps.get(num) and os.path.isfile(gaps[num]) else None,
                    "base_label": f"{num}_{action_name.lower()}_" + "_".join(
                        str(s) for p in parts for s in p["screens"]
                    ),
                })

            if not templates:
                self._label_mode = False
            else:
                playlist = []
                n_actions = len(templates)
                for test_num in range(1, LABEL_TEST_COUNT + 1):
                    scale = LABEL_TIMING_DECAY ** (test_num - 1)
                    for i, tmpl in enumerate(templates):
                        action_in_set = i + 1
                        playlist.append({
                            "kind": "labeled_action",
                            "index": len(playlist) + 1,
                            "test_num": test_num,
                            "action_in_set": action_in_set,
                            "actions_in_set": n_actions,
                            "is_last_in_set": action_in_set == n_actions,
                            "timing_scale": scale,
                            "action_num": tmpl["action_num"],
                            "action": tmpl["action"],
                            "parts": tmpl["parts"],
                            "field_screens": tmpl["field_screens"],
                            "screen_images": tmpl["screen_images"],
                            "gap_path": tmpl["gap_path"],
                            "label": (
                                f"T{test_num}/{LABEL_TEST_COUNT} "
                                f"a{action_in_set}/{n_actions} "
                                f"{tmpl['base_label']} "
                                f"x{scale:.2f}"
                            ),
                            "path": f"image://test{test_num}/{tmpl['action_num']}/{tmpl['action']}",
                        })
                logger.info(
                    "Labeled playlist: %s tests x %s action(s) = %s steps "
                    "(fillers=%s gaps=%s; missing=black) from %s",
                    LABEL_TEST_COUNT,
                    n_actions,
                    len(playlist),
                    len(fillers),
                    len(gaps),
                    self.video_directory,
                )
                return playlist

        # Fallback: legacy teammate flash (4+11 ↔ 3+10 ×5)
        self._label_mode = False
        far = _screens_for_active_fields(PASS_FLASH_STEPS[0], active)
        near = _screens_for_active_fields(PASS_FLASH_STEPS[1], active)
        if not far and not near:
            return []
        return [{
            "kind": "image_pass_flash",
            "index": 1,
            "screens_far": far,
            "screens_near": near,
            "label": f"PASS flash 4/11↔3/10 ×{FLASH_REPEAT}",
            "path": "image://PASS/flash",
        }]

    def _intro_video_for_field(self, fid: str) -> Optional[str]:
        """Intro clip for one field. Uses that field's level when A and B differ."""
        fid = str(fid or "").upper()
        level = str((getattr(self, "_phase_field_levels", None) or {}).get(fid) or "").strip()
        if level:
            hit = _intro_video_for_key(_level_intro_key_from_id(level))
            if hit:
                return hit
            # This field has its own level. Do not borrow the other field's intro.
            return None
        directory = str((getattr(self, "_phase_field_directories", None) or {}).get(fid) or "").strip()
        if directory:
            for pat, key in _LEVEL_INTRO_PATH_RULES:
                if pat.search(directory):
                    hit = _intro_video_for_key(key)
                    if hit:
                        return hit
        return _find_level_intro_video(directory or self.video_directory or self._level_root)

    def _begin_level_intro(self, next_index=0):
        """Show the test card for 5 seconds, then play the level clip."""
        next_index = int(next_index)
        self._clear_held_results()
        if getattr(self, "_level_card_shown_for", None) != next_index:
            self._show_level_card(next_index)
            return
        self._play_level_intro(next_index)

    def _show_level_card(self, next_index):
        self._level_card_shown_for = int(next_index)
        files = self.video_files or []
        entry = files[next_index] if 0 <= next_index < len(files) and isinstance(files[next_index], dict) else {}
        levels = getattr(self, "_phase_field_levels", None) or {}
        modes = getattr(self, "_phase_field_modes", None) or {}
        level_id = ""
        subdirectory = str(getattr(self, "_phase_subdirectory", "") or "")
        active_fields = list(self._active_fields())
        for fid in active_fields:
            if levels.get(fid):
                level_id = str(levels.get(fid))
                break
        if not level_id:
            level_id = str(getattr(self, "_phase_mode_id", "") or "")
        try:
            card_test = int(entry.get("test_num") or 1) if isinstance(entry, dict) else 1
        except (TypeError, ValueError):
            card_test = 1
        separate_cards = (
            len(active_fields) >= 2
            and (self._field_levels_differ() or self._field_modes_differ())
        )
        field_cards = {}
        if separate_cards:
            field_cards = _opening_cards_for_fields(
                active_fields,
                levels,
                modes,
                getattr(self, "_field_opening_playlists", None) or {},
                entry,
                files,
                card_test,
            )
            text = " | ".join(
                f"{fid} {field_cards[fid]['text'].replace(chr(10), ' ')}"
                for fid in active_fields if fid in field_cards
            )
        else:
            text = _level_card_text(level_id, subdirectory, entry, files)
        color_context = " ".join([
            level_id,
            subdirectory,
            str(getattr(self, "video_directory", "") or ""),
            str(getattr(self, "_level_root", "") or ""),
        ])
        if not separate_cards:
            color_context = " ".join([
                color_context,
                " ".join(str(v) for v in (getattr(self, "_phase_field_directories", None) or {}).values()),
                " ".join(str(v) for v in levels.values()),
            ])
        background, foreground = _level_card_colors(color_context, "", entry if not separate_cards else {})
        if self.image_canvas:
            screens = []
            for fid in self._active_fields():
                screens.extend(_field_all_screens(fid))
            self.image_canvas.setGeometry(0, 0, self.video_width, self.video_height)
            if separate_cards and field_cards:
                by_screen = {}
                for fid in active_fields:
                    card = field_cards.get(fid)
                    if not card:
                        continue
                    for sid in _field_all_screens(fid):
                        by_screen[sid] = card
                self.image_canvas.set_level_summaries(by_screen)
            else:
                self.image_canvas.set_level_summary(
                    text.split("\n"), screens, background, foreground,
                )
            self.image_canvas.show()
            self.image_canvas.raise_()
            self.image_canvas.update()
            if self.level_card_label:
                self.level_card_label.hide()
        else:
            label = self.level_card_label
            br, bgc, bb = background
            fr, fg_c, fb = foreground
            label.setStyleSheet(
                f"background-color: rgb({br},{bgc},{bb}); color: rgb({fr},{fg_c},{fb}); "
                "font-size: 14px; padding: 12px 20px; border-radius: 12px; "
                "font-weight: bold; font-family: 'Segoe UI';"
            )
            label.setText(text)
            label.adjustSize()
            label.move(
                max(0, (self.video_width - label.width()) // 2),
                max(0, (self.video_height - label.height()) // 2),
            )
            label.show()
            label.raise_()
        self.display_phase = "level_card"
        self._update_status_file("starting", 0, self.total_videos or 0, text.replace("\n", " "))
        logger.info("Level card %sms: %s", LEVEL_CARD_MS, text.replace("\n", " | "))
        if self.play_delay_timer:
            self.play_delay_timer.stop()
        self.play_delay_timer = QtCore.QTimer(singleShot=True)
        self.play_delay_timer.timeout.connect(lambda idx=next_index: self._play_level_intro(idx))
        self.play_delay_timer.start(LEVEL_CARD_MS)

    def _play_level_intro(self, next_index=0):
        """Play the level clip on every screen of each active field before a test."""
        if self.level_card_label:
            self.level_card_label.hide()
        self._level_intro_next_index = int(next_index)
        self._hide_waiting_overlay()
        active = self._active_fields()
        screen_to_video = {}
        by_field = {}
        for fid in active:
            intro = self._intro_video_for_field(fid)
            by_field[fid] = intro
            if not intro:
                continue
            for sid in _field_all_screens(fid):
                screen_to_video[sid] = intro
        if not screen_to_video:
            logger.warning(
                "No level intro video found for fields %s — starting test immediately",
                active,
            )
            self._after_level_intro()
            return

        names = {
            fid: (os.path.basename(path) if path else "missing")
            for fid, path in by_field.items()
        }
        self.display_phase = "level_intro"
        self._update_status_file(
            "starting",
            max(0, self._current_test_num() - 1),
            self.total_videos,
            "Level intro: " + ", ".join(f"{fid}={name}" for fid, name in names.items()),
        )
        logger.info(
            "Level intro %sms on fields %s screens %s clips %s (then index %s)",
            LEVEL_INTRO_MS, active, sorted(screen_to_video), names, next_index,
        )

        played = False
        try:
            self.player.stop()
        except Exception:
            pass
        if self.image_canvas:
            self.image_canvas.setGeometry(0, 0, self.video_width, self.video_height)
            self.image_canvas.show()
            self.image_canvas.raise_()
            self.image_canvas.set_screen_videos(screen_to_video, fill=True)
            played = bool(self.image_canvas.active_screens)
            if played and len(set(screen_to_video.values())) == 1:
                self._play_intro_audio(next(iter(screen_to_video.values())))
        if not played:
            intro = next(iter(screen_to_video.values()))
            try:
                self._play_local_clip(intro, rate=1.0)
                played = True
            except Exception as exc:
                logger.error("Level intro playback failed: %s", exc)

        if not played:
            self._after_level_intro()
            return

        if self.play_delay_timer:
            self.play_delay_timer.stop()
        self.play_delay_timer = QtCore.QTimer(singleShot=True)
        self.play_delay_timer.timeout.connect(self._after_level_intro)
        self.play_delay_timer.start(LEVEL_INTRO_MS)

    def _after_level_intro(self):
        if self.operator_paused:
            QTimer.singleShot(200, self._after_level_intro)
            return
        if self.play_delay_timer:
            try:
                self.play_delay_timer.stop()
            except Exception:
                pass
            self.play_delay_timer = None
        try:
            self.player.stop()
        except Exception:
            pass
        if self.image_canvas:
            self.image_canvas.clear()
        self._clear_held_results()
        self._prestart_done = True
        self.is_first_video = False
        self._hide_waiting_overlay()
        idx = int(getattr(self, "_level_intro_next_index", 0) or 0)
        self.display_phase = "action"
        if self.image_canvas:
            self.image_canvas.show()
            self.image_canvas.raise_()
        self._load_video(idx)

    def _begin_prestart_waiting(self):
        """Backward-compatible alias → level intro video."""
        self._begin_level_intro(0)

    def _after_prestart_waiting(self):
        self._after_level_intro()

    def _get_video_files(self, directory):
        """
        List only video files (mp4, avi, mov, mkv, flv, wmv) that are DIRECTLY inside
        the given directory (no subdirectories). Sorts numerically by the first number
        found in the filename.
        """
        video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv'}
        videos = []
        try:
            for entry in os.listdir(directory):
                full_path = os.path.join(directory, entry)
                if os.path.isfile(full_path):
                    if Path(entry).suffix.lower() in video_extensions:
                        videos.append(full_path)
        except Exception as e:
            logger.error(f"Error listing directory {directory}: {e}")
            return []

        # Natural sort: extract the first number in the filename
        def natural_key(path):
            import re
            filename = os.path.basename(path)
            numbers = re.findall(r'\d+', filename)
            if numbers:
                return int(numbers[0])
            return 0

        videos.sort(key=natural_key)
        logger.info(f"Found {len(videos)} video files directly in {directory}.")
        return videos

    def _flash_delay_ms(self, on=True):
        """On/Gap ms from frontend (scaled), or fixed per-entry on_ms/gap_ms (SF scripts)."""
        speed = max(0.25, float(self.player_speed or 1.0))
        try:
            entry = self.video_files[self.current_video_index]
            if isinstance(entry, dict):
                fixed = bool(entry.get("fixed_timing"))
                div = 1.0 if fixed else speed
                if on and entry.get("on_ms") is not None:
                    return max(80, int(float(entry["on_ms"]) / div))
                if (not on) and entry.get("gap_ms") is not None:
                    return max(80, int(float(entry["gap_ms"]) / div))
        except Exception:
            pass
        on_ms, gap_ms = _read_flash_timing_ms()
        base = on_ms if on else gap_ms
        scale = 1.0
        try:
            entry = self.video_files[self.current_video_index]
            if isinstance(entry, dict):
                scale = float(entry.get("timing_scale") or 1.0)
        except Exception:
            scale = 1.0
        scale = max(0.05, min(1.0, scale))
        return max(80, int((base * scale) / speed))

    def _current_test_num(self):
        try:
            entry = self.video_files[self.current_video_index]
            if isinstance(entry, dict) and entry.get("test_num"):
                return int(entry["test_num"])
        except Exception:
            pass
        return max(1, int(self.current_video_index) + 1)

    def _stop_action_timer(self):
        if self.action_timer:
            try:
                self.action_timer.stop()
            except Exception:
                pass
            self.action_timer = None

    def _field_screens_map(self, screen_ids):
        """Map lit screens back to fields for the realtime cue file."""
        active = set(self._active_fields())
        out = {}
        for sid in screen_ids or []:
            fid = _field_for_screen(sid)
            if fid not in active:
                continue
            name = _sid(sid)
            if not name:
                continue
            out.setdefault(fid, []).append(name)
        return out

    def _load_video(self, index):
        self._hide_waiting_overlay()
        self._stop_action_timer()
        if not (0 <= index < len(self.video_files)):
            return
        self.player.stop()
        self.check_timer.stop()
        self.current_video_index = index
        entry = self.video_files[index]
        self.current_video_path = entry.get("path") if isinstance(entry, dict) else entry
        self.video_end_called = False
        self._action_phase = "idle"
        self._label_phase = "action" if isinstance(entry, dict) and entry.get("skip_gap") else "gap"
        self._flash_cycle = 0
        self._flash_phase = 0

        if self.image_based and isinstance(entry, dict):
            label = entry.get("label", f"action {index + 1}")
            test_num = int(entry.get("test_num") or 1)
            action_in_set = int(entry.get("action_in_set") or 1)
            # One wall-clock window per test for per-video results
            if action_in_set <= 1 or self._set_start_time is None:
                self._set_start_time = time.time()
                self.video_start_time = self._set_start_time
            else:
                self.video_start_time = self._set_start_time
            logger.info(
                "Loading %s (%s/%s)",
                label, index + 1, len(self.video_files),
            )
            self._update_status_file(
                "loading", test_num, self.total_videos, f"Loading: {label}"
            )
            try:
                # Realtime scores by test number (1..5), not flat step index
                with open(self.video_index_file, 'w') as f:
                    f.write(str(test_num))
            except Exception as e:
                logger.error(f"Failed to write video index file: {e}")
            if self.image_canvas:
                self.image_canvas.clear()
                self.image_canvas.show()
                self.image_canvas.raise_()
            self.is_first_video = False
            self._start_playback()
            return

        self.current_video_path = entry
        self.video_start_time = time.time()
        self._set_start_time = self.video_start_time
        logger.info(f"Loading video {index+1}/{len(self.video_files)}: {os.path.basename(self.current_video_path)}")
        self._update_status_file("loading", index+1, len(self.video_files), f"Loading: {os.path.basename(self.current_video_path)}")
        try:
            with open(self.video_index_file, 'w') as f:
                f.write(str(index + 1))
        except Exception as e:
            logger.error(f"Failed to write video index file: {e}")
        if self.image_canvas:
            self.image_canvas.hide()
        self.media = self.instance.media_new(os.path.abspath(self.current_video_path))
        self.player.set_media(self.media)
        if self.is_first_video:
            self.is_first_video = False
            delay_ms = 3000
            if self.play_delay_timer:
                self.play_delay_timer.stop()
            self.play_delay_timer = QtCore.QTimer()
            self.play_delay_timer.setSingleShot(True)
            self.play_delay_timer.timeout.connect(self._start_playback)
            self.play_delay_timer.start(delay_ms)
        else:
            self._start_playback()

    def _start_playback(self):
        if self.operator_paused:
            self._pending_start_after_pause = True
            logger.info("Start delayed until operator resumes.")
            return
        if self.play_delay_timer:
            self.play_delay_timer.stop()
            self.play_delay_timer = None
        self.completion_label.hide()
        self.progress_label.hide()
        self.playlist_finished = False
        self.waiting_for_results = False
        self.display_phase = "action"

        if self.image_based:
            entry = self.video_files[self.current_video_index]
            label = entry.get("label", "image action") if isinstance(entry, dict) else "image action"
            logger.info("Starting image action: %s", label)
            if self.image_canvas:
                self.image_canvas.clear()
                self.image_canvas.show()
                self.image_canvas.raise_()
            self.video_start_time = time.time()
            self._update_status_file(
                "playing",
                self.current_video_index + 1,
                self.total_videos,
                f"Playing: {label}",
            )
            self.check_timer.start()
            if (isinstance(entry, dict) and entry.get("kind") == "labeled_action") or self._label_mode:
                self._action_phase = "label"
                # gap_N before action N, unless this test switches as soon as the ball arrives.
                if isinstance(entry, dict) and entry.get("skip_gap"):
                    self._label_phase = "action"
                else:
                    self._label_phase = "gap"
                self._apply_label_phase()
            else:
                self._action_phase = "flash"
                self._flash_cycle = 0
                self._flash_phase = 0
                self._apply_flash_phase()
            return

        logger.info("Starting playback now.")
        self.player.set_time(0)
        self.player.video_set_aspect_ratio(f"{COACH_BAND_WIDTH}:{COACH_BAND_HEIGHT}")
        self.player.video_set_scale(1.0)
        self.player.video_set_crop_geometry(f"0:0:{COACH_BAND_WIDTH}:{COACH_BAND_HEIGHT}")
        self.player.play()
        self._update_progress_display()
        self.check_timer.start()

    def _current_label_entry(self):
        files = self.video_files or []
        index = int(getattr(self, "current_video_index", 0) or 0)
        if 0 <= index < len(files) and isinstance(files[index], dict):
            return files[index]
        return {}

    def _result_hold_mode(self, entry=None) -> str:
        """How long a finish mark stays on its screen.

        Foundation: until a later action uses that same screen.
        Entry through High Performance: until the test ends.
        Elite and World Class: under the 00 until every action in the test is done.
        """
        if not isinstance(entry, dict):
            entry = self._current_label_entry()
        if entry.get("combined_field"):
            return "under"
        text = " ".join(
            str(part or "")
            for part in (
                getattr(self, "_phase_mode_id", ""),
                getattr(self, "_phase_subdirectory", ""),
                getattr(self, "video_directory", ""),
                entry.get("label"),
                entry.get("path"),
            )
        )
        if re.search(r"L04-Elite|L05-WorldClass|World[-_ ]?Class", text, re.I):
            return "under"
        if re.search(
            r"L01-Entry|L02-Activated|L03-HighPerformance|High[-_ ]?Performance",
            text,
            re.I,
        ):
            return "test"
        if entry.get("entry_digits"):
            return "test"
        return "screen"

    def _apply_held_results(self):
        if not self.image_canvas:
            return
        anchor = "under" if self._result_hold_mode() == "under" else "center"
        self.image_canvas.set_result_badges(getattr(self, "_held_result_badges", {}), anchor)

    def _release_results_on(self, screens):
        """Foundation: the mark leaves when this screen starts another action."""
        held = getattr(self, "_held_result_badges", None)
        if not isinstance(held, dict):
            self._held_result_badges = {}
            return
        released = getattr(self, "_result_released_screens", None)
        if not isinstance(released, set):
            released = set()
            self._result_released_screens = released
        for sid in screens or []:
            name = _sid(sid)
            if name:
                held.pop(name, None)
                released.add(name)
        self._apply_held_results()

    def _clear_held_results(self):
        self._stop_gap_result_poll()
        self._held_result_badges = {}
        self._result_released_screens = set()
        if self.image_canvas:
            self.image_canvas.set_result_badges({})

    def _stop_gap_result_poll(self):
        timer = getattr(self, "_gap_result_timer", None)
        if timer is not None:
            try:
                timer.stop()
                timer.deleteLater()
            except Exception:
                pass
            self._gap_result_timer = None

    def _budget_remaining_ms(self, entry) -> int:
        """Milliseconds left in this test's shared clock."""
        budget = int(entry.get("budget_ms") or 0)
        test_num = int(entry.get("test_num") or 0)
        action_in_set = int(entry.get("action_in_set") or 1)
        if action_in_set <= 1 or getattr(self, "_budget_test", None) != test_num:
            self._budget_started_at = time.perf_counter()
            self._budget_test = test_num
            self._budget_closed_test = None
        elapsed = (time.perf_counter() - float(self._budget_started_at)) * 1000.0
        return int(round(budget - elapsed))

    def _abandon_budget_rest(self):
        """The shared clock is finished. Actions not reached are Wrong."""
        files = self.video_files or []
        idx = int(getattr(self, "current_video_index", 0) or 0)
        if not (0 <= idx < len(files)) or not isinstance(files[idx], dict):
            return
        test_num = int(files[idx].get("test_num") or 0)
        if getattr(self, "_budget_closed_test", None) == test_num:
            return
        self._budget_closed_test = test_num
        missed = []
        last = idx
        for i in range(idx, len(files)):
            item = files[i]
            if not isinstance(item, dict) or int(item.get("test_num") or 0) != test_num:
                break
            missed.append(item)
            last = i
        logger.info(
            "Shared clock finished on test %s — %s actions scored Wrong",
            test_num, len(missed),
        )
        self._store_budget_wrongs(missed)
        self._stop_goal_advance_poll()
        self._stop_action_timer()
        self.current_video_index = last
        self._post_results_index = last + 1 if last + 1 < len(files) else None
        self._finished_field_screens = {}
        self._on_video_ended()

    def _store_budget_wrongs(self, missed):
        """Write a Wrong row for each action the player had no time to play."""
        import urllib.request
        root = "C:/Users/siama/Documents/simust_realtime_recordings"
        if not os.path.isdir(root):
            logger.warning("No recording folder for unfinished omid_2 actions")
            return
        folders = [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
        if not folders:
            logger.warning("No recording folder for unfinished omid_2 actions")
            return
        folders.sort(key=lambda d: os.path.getctime(os.path.join(root, d)), reverse=True)
        newest = os.path.join(root, folders[0])
        for item in missed:
            test_num = int(item.get("test_num") or 1)
            action_in_set = int(item.get("action_in_set") or 1)
            if item.get("budget_ms"):
                window = float(item.get("budget_ms") or 0) / 1000.0
            else:
                window = float(item.get("efficiency_max_sec") or 12.0)
            ae = max(0.0, min(100.0, (0.40 * 70.0) - 25.0))
            for fid, screens in (item.get("field_screens") or {}).items():
                fid_u = str(fid).upper()[:1]
                folder = os.path.join(newest, f"field_{fid_u}")
                if not os.path.isdir(folder):
                    continue
                payload = {
                    "session_folder": folder,
                    "action_result": {
                        "id": f"T{test_num}a{action_in_set}",
                        "action": "PASS",
                        "screens": list(screens or []),
                        "field": fid_u,
                        "result": "Wrong",
                        "winning_screen": "N/A",
                        "min_dist": None,
                        "movement": 0,
                        "direction": "NONE",
                        "aep": "N/A",
                        "session_duration": f"{window:.3f}",
                        "video_index": test_num,
                        "finishing_time": f"{window:.3f}",
                        "total_distance": 0.0,
                        "ae": ae,
                    },
                }
                if item.get("finish_balls"):
                    payload["action_result"]["finish_balls"] = True
                    payload["action_result"]["balls_budget_sec"] = window
                    payload["action_result"]["balls_clock_sec"] = window
                try:
                    req = urllib.request.Request(
                        "http://127.0.0.1:8000/save-results-to-json",
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    urllib.request.urlopen(req, timeout=3).read()
                except Exception as exc:
                    logger.warning("Could not store Wrong for unfinished action: %s", exc)

    def _stop_goal_advance_poll(self):
        timer = getattr(self, "_goal_advance_timer", None)
        if timer is not None:
            try:
                timer.stop()
                timer.deleteLater()
            except Exception:
                pass
            self._goal_advance_timer = None

    def _start_goal_advance_poll(self):
        """Omid: leave this screen as soon as the ball reaches its goal."""
        self._stop_goal_advance_poll()
        self._goal_advance_timer = QtCore.QTimer(self)
        self._goal_advance_timer.timeout.connect(self._poll_goal_advance)
        self._goal_advance_timer.start(40)

    def _poll_goal_advance(self):
        if self.display_phase != "action" or getattr(self, "_label_phase", "") != "action":
            return
        if getattr(self, "_goal_arrived", False):
            return
        files = self.video_files or []
        idx = int(getattr(self, "current_video_index", 0) or 0)
        entry = files[idx] if 0 <= idx < len(files) and isinstance(files[idx], dict) else {}
        if not entry.get("advance_on_goal"):
            self._stop_goal_advance_poll()
            return
        try:
            want_seq = int(getattr(self, "_flash_seq", 0) or 0)
        except (TypeError, ValueError):
            want_seq = 0
        cue_wall = float(getattr(self, "_action_cue_wall", 0) or 0)
        try:
            with open(LIVE_ACTION_RESULT_FILE, "r", encoding="utf-8") as handle:
                payload = json.load(handle) or {}
        except Exception:
            return
        fields = payload.get("fields") if isinstance(payload, dict) else {}
        if not isinstance(fields, dict):
            return
        for fid in self._active_fields():
            item = fields.get(fid) or {}
            if not isinstance(item, dict):
                continue
            by_seq = item.get("by_seq") if isinstance(item.get("by_seq"), dict) else {}
            chosen = by_seq.get(str(want_seq)) if want_seq else None
            if not isinstance(chosen, dict):
                chosen = item
            try:
                item_seq = int(chosen.get("seq") or 0)
            except (TypeError, ValueError):
                item_seq = 0
            try:
                stamped = float(chosen.get("ts") or 0)
            except (TypeError, ValueError):
                stamped = 0
            if want_seq and item_seq and item_seq != want_seq:
                continue
            if cue_wall and stamped + 0.05 < cue_wall:
                continue
            name = str(chosen.get("result") or "").strip().lower()
            if name not in ("correct", "miss", "late"):
                continue
            self._goal_arrived = True
            self._stop_goal_advance_poll()
            logger.info("Ball reached the goal on %s (%s) — next screen", fid, name)
            self._finish_label_action()
            return

    def _start_gap_result_poll(self):
        """Finish marks stay off the action screens."""
        self._stop_gap_result_poll()

    def _finished_marks_pending(self) -> bool:
        """True while a finished screen still has no mark and is not in a new action."""
        released = getattr(self, "_result_released_screens", None) or set()
        held = getattr(self, "_held_result_badges", None) or {}
        for screens in (getattr(self, "_finished_field_screens", None) or {}).values():
            for sid in screens or []:
                name = _sid(sid)
                if name and name not in held and name not in released:
                    return True
        return False

    def _finished_screens_open(self) -> bool:
        """True while a finished screen is still showing its own result."""
        released = getattr(self, "_result_released_screens", None) or set()
        for screens in (getattr(self, "_finished_field_screens", None) or {}).values():
            for sid in screens or []:
                name = _sid(sid)
                if name and name not in released:
                    return True
        return False

    def _poll_gap_result(self):
        phase = getattr(self, "_label_phase", "")
        if self.display_phase != "action" or phase not in ("gap", "action", "encode", "spin"):
            self._stop_gap_result_poll()
            return
        if not self._finished_screens_open():
            self._stop_gap_result_poll()
            return
        payload = {}
        try:
            with open(LIVE_ACTION_RESULT_FILE, "r", encoding="utf-8") as handle:
                payload = json.load(handle) or {}
        except Exception:
            payload = {}
        fields = payload.get("fields") if isinstance(payload, dict) else {}
        if not isinstance(fields, dict):
            fields = {}
        started = float(getattr(self, "_finished_action_at", 0) or 0)
        cue_wall = float(getattr(self, "_finished_cue_wall", 0) or 0)
        try:
            want_seq = int(getattr(self, "_finished_cue_seq", 0) or 0)
        except (TypeError, ValueError):
            want_seq = 0
        released = getattr(self, "_result_released_screens", None) or set()
        badges = {}
        for fid, screens in (getattr(self, "_finished_field_screens", None) or {}).items():
            item = fields.get(fid) or {}
            if not isinstance(item, dict):
                continue
            by_seq = item.get("by_seq") if isinstance(item.get("by_seq"), dict) else {}
            chosen = by_seq.get(str(want_seq)) if want_seq else None
            if not isinstance(chosen, dict):
                chosen = item
            try:
                stamped = float(chosen.get("ts") or 0)
            except (TypeError, ValueError):
                stamped = 0
            try:
                item_seq = int(chosen.get("seq") or 0)
            except (TypeError, ValueError):
                item_seq = 0
            # Show this action's score. A result from the previous cue stays hidden.
            if cue_wall and stamped + 0.05 < cue_wall:
                continue
            if want_seq and item_seq and item_seq != want_seq:
                continue
            if not cue_wall and stamped + 1.5 < started:
                continue
            mark = _gap_result_mark(chosen.get("result"))
            if not mark:
                continue
            for sid in screens:
                name = _sid(sid)
                if name and name in released:
                    continue
                badges[sid] = mark
        if not hasattr(self, "_held_result_badges") or not isinstance(self._held_result_badges, dict):
            self._held_result_badges = {}
        before = dict(getattr(self, "_held_result_badges", {}) or {})
        self._held_result_badges.update(badges)
        if self._held_result_badges != before:
            logger.info("Finish marks on screen: %s", self._held_result_badges)
        self._apply_held_results()

    def _apply_label_phase(self):
        """gap_N (before action) → labeled action (+ fillers). Cue only during action."""
        if self.display_phase != "action" or self._action_phase != "label":
            return
        if self.operator_paused:
            QTimer.singleShot(200, self._apply_label_phase)
            return

        entry = self.video_files[self.current_video_index]
        if not isinstance(entry, dict):
            self._on_video_ended()
            return

        action_num = int(entry.get("action_num") or entry.get("index") or 1)
        action_name = str(entry.get("action") or "PASS").upper()
        active = set(self._active_fields())

        # ---- Gap BEFORE this action: gap_N on slices 2/14/7/9 ----
        if self._label_phase == "gap":
            # Never let waiting rings cover gap images
            self._hide_waiting_overlay()
            if self.image_canvas:
                self.image_canvas.show()
                self.image_canvas.raise_()

            gap_path = entry.get("gap_path") or (self._asset_gaps or {}).get(action_num)
            if gap_path and not os.path.isfile(gap_path):
                gap_path = None
            gap_images = {}
            held = entry.get("gap_screen_images") if entry.get("entry_digits") else None
            if held:
                gap_images = _named_image_map(held, active)
            elif gap_path:
                for sid in GAP_SCREENS:
                    if _field_for_screen(sid) in active:
                        gap_images[sid] = gap_path
            if self.image_canvas:
                if gap_images:
                    self.image_canvas.set_screen_images(gap_images)
                else:
                    # No gap image → black (nothing displayed)
                    self.image_canvas.clear()
            self._apply_held_results()
            self._start_gap_result_poll()

            # Gap does not send cue false. Keypoints clear from the cue-ON countdown.
            delay = self._flash_delay_ms(on=False)
            logger.info(
                "Gap BEFORE action %s (%s) screens %s for %sms [scale=%.2f]",
                action_num,
                os.path.basename(gap_path) if gap_path else "black",
                list(gap_images.keys()) if gap_images else "black",
                delay,
                float(entry.get("timing_scale") or 1.0),
            )
            self._stop_action_timer()
            self.action_timer = QtCore.QTimer(singleShot=True)
            self.action_timer.timeout.connect(self._advance_label_phase)
            self.action_timer.start(delay)
            return

        # ---- Action ON: labeled images + fillers ----
        self._hide_waiting_overlay()
        if self.image_canvas:
            self.image_canvas.show()
            self.image_canvas.raise_()

        screen_images = _named_image_map(entry.get("screen_images") or {}, active)
        action_screens = list(screen_images.keys())
        # Math modes already fill every field screen with equations — never overlay fillers.
        fillers = {}
        if self._asset_fillers and not entry.get("no_fillers") and not entry.get("math_op"):
            fillers = _pick_filler_placements(
                action_num, action_screens, active, self._asset_fillers or {}
            )
        for sid, path in fillers.items():
            name = _sid(sid)
            if name and name not in screen_images:
                screen_images[name] = path

        # Cue only correct/target screens (math: 2 true equations per field).
        # Display may show equations on every screen via screen_images.
        raw_fs = entry.get("field_screens") or {}
        field_screens = {}
        if isinstance(raw_fs, dict) and raw_fs:
            for fid, sids in raw_fs.items():
                fid_u = str(fid).upper()
                if fid_u not in active:
                    continue
                field_screens[fid_u] = _named_screens(sids or [])
        if not field_screens:
            for sid in action_screens:
                fid = _field_for_screen(sid)
                if fid in active:
                    field_screens.setdefault(fid, []).append(sid)

        # Lit screens for display + cue (prefer explicit field_screens)
        lit_screens = []
        for sids in field_screens.values():
            lit_screens.extend(sids)
        if not lit_screens:
            lit_screens = list(action_screens)

        video_path = entry.get("screen_video")
        pass_scale = 1.0
        if not (entry.get("entry_digits") or entry.get("math_op")):
            pass_scale = (
                self.image_canvas.PASS_IMAGE_SCALE if self.image_canvas else 0.81
            )
        if self._result_hold_mode(entry) == "screen":
            self._release_results_on(lit_screens)
        if self.image_canvas:
            if video_path and os.path.isfile(str(video_path)):
                self.image_canvas.set_screen_video(lit_screens, str(video_path), scale=pass_scale)
            else:
                self.image_canvas.set_screen_images(screen_images, scale=pass_scale)
            self._apply_held_results()
            # Paint now. The old timer started before the second monitor showed
            # the image, so Kinovea measured ~2.6s of a 3.0s hold.
            self.image_canvas.repaint()
            QtWidgets.QApplication.processEvents()

        delay = self._flash_delay_ms(on=True)
        if entry.get("budget_ms"):
            delay = self._budget_remaining_ms(entry)
            if delay <= 40:
                self._abandon_budget_rest()
                return
        self._flash_seq += 1
        on_sec = max(0.1, float(delay) / 1000.0)
        self._pass_shown_at = time.perf_counter()
        self._pass_on_ms = int(delay)
        self._action_cue_wall = time.time()
        self._goal_arrived = False
        budget_elapsed = None
        budget_total = None
        if entry.get("finish_balls") and entry.get("budget_ms"):
            started = getattr(self, "_budget_started_at", None)
            budget_elapsed = 0.0 if not started else max(0.0, time.perf_counter() - started)
            budget_total = float(entry.get("budget_ms") or 0) / 1000.0
        _write_image_action_cue(
            True,
            field_screens,
            seq=self._flash_seq,
            action=action_name,
            on_sec=on_sec,
            efficiency_max_sec=entry.get("efficiency_max_sec"),
            finish_balls=bool(entry.get("finish_balls")),
            budget_elapsed_sec=budget_elapsed,
            budget_total_sec=budget_total,
            action_in_set=entry.get("action_in_set"),
            actions_in_set=entry.get("actions_in_set"),
            test_num=entry.get("test_num"),
        )
        logger.info(
            "Labeled action %s %s ON screens %s (+%s fillers) for %sms [test %s scale=%.2f on=%.3fs]",
            action_num,
            action_name,
            action_screens,
            len(fillers),
            delay,
            entry.get("test_num"),
            float(entry.get("timing_scale") or 1.0),
            on_sec,
        )
        self._stop_action_timer()
        self.action_timer = QtCore.QTimer(singleShot=True)
        self.action_timer.setTimerType(QtCore.Qt.PreciseTimer)
        self.action_timer.timeout.connect(self._finish_label_action)
        self.action_timer.start(delay)
        if entry.get("advance_on_goal"):
            self._start_goal_advance_poll()
        if getattr(self, "_finished_field_screens", None):
            self._start_gap_result_poll()

    def _advance_label_phase(self):
        """After pre-action gap → encode (cognitive) / rotation spin → action hold."""
        if self.display_phase != "action" or self._action_phase != "label":
            return
        if self.operator_paused:
            QTimer.singleShot(200, self._advance_label_phase)
            return
        entry = self.video_files[self.current_video_index] if self.video_files else {}
        if isinstance(entry, dict) and entry.get("cognitive_encode") and entry.get("encode_images"):
            self._label_phase = "encode"
            self._begin_cognitive_encode(entry)
            return
        if isinstance(entry, dict) and entry.get("rotation") and entry.get("rotation_fields"):
            self._label_phase = "spin"
            self._begin_rotation_spin(entry)
            return
        self._label_phase = "action"
        self._apply_label_phase()

    def _begin_cognitive_encode(self, entry):
        """Brief preview of stimuli (memory/tracking), then blank, then probe+session."""
        self._hide_waiting_overlay()
        if self.image_canvas:
            self.image_canvas.show()
            self.image_canvas.raise_()
        encode = _named_image_map(
            entry.get("encode_images") or {},
            set(self._active_fields()),
        )
        if self.image_canvas:
            if encode:
                self.image_canvas.set_screen_images(encode)
            else:
                self.image_canvas.clear()
        scale = max(0.05, float(entry.get("timing_scale") or 1.0))
        delay = max(200, int(COG_ENCODE_MS * scale))
        logger.info(
            "Cognitive encode %s for %sms (%s tiles)",
            entry.get("cognitive"), delay, len(encode),
        )
        self._stop_action_timer()
        self.action_timer = QtCore.QTimer(singleShot=True)
        self.action_timer.timeout.connect(self._cognitive_encode_blank)
        self.action_timer.start(delay)

    def _cognitive_encode_blank(self):
        if self.display_phase != "action" or self._action_phase != "label":
            return
        if self.operator_paused:
            QTimer.singleShot(200, self._cognitive_encode_blank)
            return
        if self.image_canvas:
            self.image_canvas.clear()
        entry = self.video_files[self.current_video_index] if self.video_files else {}
        scale = max(0.05, float((entry or {}).get("timing_scale") or 1.0))
        delay = max(100, int(COG_BLANK_MS * scale))
        self._stop_action_timer()
        self.action_timer = QtCore.QTimer(singleShot=True)
        self.action_timer.timeout.connect(self._cognitive_after_blank)
        self.action_timer.start(delay)

    def _cognitive_after_blank(self):
        if self.display_phase != "action" or self._action_phase != "label":
            return
        if self.operator_paused:
            QTimer.singleShot(200, self._cognitive_after_blank)
            return
        self._label_phase = "action"
        self._apply_label_phase()

    def _begin_rotation_spin(self, entry):
        """Fast pass-image rotation around each field's circle, then stop on target."""
        self._hide_waiting_overlay()
        if self.image_canvas:
            self.image_canvas.show()
            self.image_canvas.raise_()

        rotation_fields = [
            f for f in (entry.get("rotation_fields") or [])
            if f in set(self._active_fields())
        ]
        spin_arcs = dict(entry.get("spin_arcs") or {})
        stop = dict(entry.get("field_screens") or {})
        self._spin_fields = []
        self._spin_arcs = {}
        self._spin_index = {}
        self._spin_steps_left = {}
        self._spin_stop = {}
        self._spin_images = dict(entry.get("screen_images") or {})
        # Fallback image for spin frames
        self._spin_pass_image = None
        if self._spin_images:
            self._spin_pass_image = next(iter(self._spin_images.values()))
        for fid in rotation_fields:
            arc = _named_screens(spin_arcs.get(fid) or _rotation_arc_for_field(fid))
            if not arc:
                continue
            targets = _named_screens(stop.get(fid) or [])
            target = targets[0] if targets else arc[0]
            if target not in arc:
                arc = list(arc) + [target]
            start_i = random.randrange(len(arc))
            # Land on target after ≥ ROTATION_MIN_LAPS full circles
            try:
                target_i = arc.index(target)
            except ValueError:
                target_i = 0
            steps = ROTATION_MIN_LAPS * len(arc) + ((target_i - start_i) % len(arc))
            if steps < len(arc):
                steps += len(arc)
            self._spin_fields.append(fid)
            self._spin_arcs[fid] = arc
            self._spin_index[fid] = start_i
            self._spin_steps_left[fid] = int(steps)
            self._spin_stop[fid] = target
        if not self._spin_fields:
            self._label_phase = "action"
            self._apply_label_phase()
            return
        logger.info(
            "Rotation spin start fields=%s stops=%s step=%sms",
            self._spin_fields,
            self._spin_stop,
            ROTATION_STEP_MS,
        )
        self._tick_rotation_spin()

    def _tick_rotation_spin(self):
        if self.display_phase != "action" or self._action_phase != "label":
            return
        if self._label_phase != "spin":
            return
        if self.operator_paused:
            QTimer.singleShot(200, self._tick_rotation_spin)
            return

        # Show current spin frame (one screen per rotating field); no cue yet
        frame_images = {}
        for fid in self._spin_fields:
            arc = self._spin_arcs.get(fid) or []
            if not arc:
                continue
            idx = int(self._spin_index.get(fid, 0)) % len(arc)
            # Prefer exact stop screen once steps are exhausted
            if int(self._spin_steps_left.get(fid, 0)) <= 0:
                sid = int(self._spin_stop.get(fid, arc[idx]))
            else:
                sid = int(arc[idx])
            img = self._spin_images.get(sid) or self._spin_pass_image
            if img:
                frame_images[sid] = img

        if self.image_canvas:
            if frame_images:
                self.image_canvas.set_screen_images(
                    frame_images, scale=self.image_canvas.PASS_IMAGE_SCALE
                )
            else:
                self.image_canvas.clear()

        if all(int(self._spin_steps_left.get(f, 0)) <= 0 for f in self._spin_fields):
            # Sudden stop on this frame → session hold (cue + On time)
            logger.info("Rotation stop → hold on %s", self._spin_stop)
            self._label_phase = "action"
            self._apply_label_phase()
            return

        for fid in self._spin_fields:
            arc = self._spin_arcs.get(fid) or []
            if not arc:
                continue
            idx = int(self._spin_index.get(fid, 0)) % len(arc)
            left = int(self._spin_steps_left.get(fid, 0))
            self._spin_index[fid] = (idx + 1) % len(arc)
            self._spin_steps_left[fid] = max(0, left - 1)

        self._stop_action_timer()
        self.action_timer = QtCore.QTimer(singleShot=True)
        self.action_timer.timeout.connect(self._tick_rotation_spin)
        self.action_timer.start(max(20, int(ROTATION_STEP_MS)))

    def _finish_label_action(self):
        if self.display_phase != "action" or self._action_phase != "label":
            return
        if self.operator_paused:
            QTimer.singleShot(200, self._finish_label_action)
            return
        # Keep the pass image up until a full 3s after it was painted.
        shown = getattr(self, "_pass_shown_at", None)
        need_ms = int(getattr(self, "_pass_on_ms", 0) or 0)
        goal_hit = bool(getattr(self, "_goal_arrived", False))
        if not goal_hit and shown is not None and need_ms > 0:
            remain = int(need_ms - (time.perf_counter() - shown) * 1000.0)
            if remain > 40:
                self._stop_action_timer()
                self.action_timer = QtCore.QTimer(singleShot=True)
                self.action_timer.setTimerType(QtCore.Qt.PreciseTimer)
                self.action_timer.timeout.connect(self._finish_label_action)
                self.action_timer.start(remain)
                return
            self._pass_shown_at = None
            logger.info(
                "Pass image held %.3fs (target %.3fs)",
                (time.perf_counter() - shown),
                need_ms / 1000.0,
            )
        self._goal_arrived = False
        self._stop_goal_advance_poll()
        self._stop_action_timer()
        if self.image_canvas:
            self.image_canvas.clear()
        # Pass image goes off here. Keypoints clear themselves after the cue-ON
        # countdown (3s / 90 frames). Do not send cue false.
        next_idx = self.current_video_index + 1
        cur = self.video_files[self.current_video_index] if self.video_files else {}
        cur_test = int(cur.get("test_num") or 0) if isinstance(cur, dict) else 0
        next_entry = (
            self.video_files[next_idx]
            if next_idx < len(self.video_files) and isinstance(self.video_files[next_idx], dict)
            else None
        )
        same_test = (
            self._label_mode
            and next_entry is not None
            and next_entry.get("kind") == "labeled_action"
            and int(next_entry.get("test_num") or -1) == cur_test
        )
        if isinstance(cur, dict) and (same_test or self._label_mode):
            finished = {}
            for fid, sids in (cur.get("field_screens") or {}).items():
                names = _named_screens(sids or [])
                if names:
                    finished[str(fid).upper()[:1]] = names
            self._finished_field_screens = finished
            self._finished_action_at = time.time()
            self._finished_cue_seq = int(getattr(self, "_flash_seq", 0) or 0)
            self._finished_cue_wall = float(getattr(self, "_action_cue_wall", 0) or 0)
            self._result_released_screens = set()
        else:
            self._finished_field_screens = {}
            self._finished_action_at = 0
            self._finished_cue_seq = 0
            self._clear_held_results()
        self._action_phase = "idle"

        # Within a test: next action. End of test: per-video results.
        if same_test:
            logger.info(
                "Labeled action done — next in test %s (skip waiting overlay)",
                cur_test,
            )
            self.video_end_called = False
            self.waiting_for_results = False
            self.check_timer.stop()
            self._stop_action_timer()
            self._hide_waiting_overlay()
            self.current_video_index = next_idx
            self.display_phase = "action"
            self._load_video(self.current_video_index)
            return

        # End of test: go to the per-video results. Finish marks are not shown.
        self._post_results_index = next_idx if next_idx < len(self.video_files) else None
        self._finished_field_screens = {}
        self._clear_held_results()
        self._on_video_ended()

    def _hold_for_last_result(self, entry):
        """Stay on the last action until its mark is on screen, then open results."""
        gap_ms = 1000
        if isinstance(entry, dict):
            try:
                gap_ms = int(entry.get("gap_ms") or 1000)
            except (TypeError, ValueError):
                gap_ms = 1000
        self._waiting_last_result = True
        self._last_result_seen_at = None
        self._last_result_read_ms = max(800, min(2000, int(gap_ms)))
        self._last_result_deadline = time.time() + 5.0
        self.display_phase = "action"
        self._action_phase = "label"
        self._label_phase = "gap"
        self.video_end_called = False
        self.waiting_for_results = False
        self.check_timer.stop()
        self._stop_action_timer()
        self._hide_waiting_overlay()
        if self.image_canvas:
            self.image_canvas.show()
            self.image_canvas.raise_()
            self._apply_held_results()
        self._start_gap_result_poll()
        logger.info("Holding the last action until its result is on screen")
        self._check_last_result_hold()

    def _check_last_result_hold(self):
        if not getattr(self, "_waiting_last_result", False):
            return
        if self.operator_paused:
            QTimer.singleShot(200, self._check_last_result_hold)
            return
        now = time.time()
        if not self._finished_marks_pending():
            if not getattr(self, "_last_result_seen_at", None):
                self._last_result_seen_at = now
                logger.info("Last action result is on screen")
            seen_ms = (now - float(self._last_result_seen_at)) * 1000.0
            if seen_ms >= float(getattr(self, "_last_result_read_ms", 1000) or 1000):
                self._waiting_last_result = False
                self._stop_gap_result_poll()
                self._on_video_ended()
                return
        elif now >= float(getattr(self, "_last_result_deadline", now) or now):
            logger.info("Last action result did not arrive — opening per-video results")
            self._waiting_last_result = False
            self._stop_gap_result_poll()
            self._on_video_ended()
            return
        QTimer.singleShot(40, self._check_last_result_hold)

    def _apply_flash_phase(self):
        """Legacy teammate flash: 4+11 / off / 3+10 / off, × FLASH_REPEAT."""
        if self.display_phase != "action" or self._action_phase != "flash":
            return
        if self.operator_paused:
            QTimer.singleShot(200, self._apply_flash_phase)
            return

        if self._flash_cycle >= FLASH_REPEAT and self._flash_phase == 0:
            logger.info("PASS flash done — %s cycles complete.", FLASH_REPEAT)
            if self.image_canvas:
                self.image_canvas.clear()
            self._action_phase = "idle"
            self._post_results_index = self.current_video_index + 1
            if self._post_results_index >= len(self.video_files):
                self._post_results_index = None
            self._on_video_ended()
            return

        entry = self.video_files[self.current_video_index]
        far = entry.get("screens_far", []) if isinstance(entry, dict) else []
        near = entry.get("screens_near", []) if isinstance(entry, dict) else []

        if self._flash_phase == 0:
            screens = far
            delay = self._flash_delay_ms(on=True)
            self._flash_seq += 1
            logger.info(
                "Flash cycle %s/%s: ON screens %s (%s ms)",
                self._flash_cycle + 1, FLASH_REPEAT, screens, delay,
            )
        elif self._flash_phase == 1:
            screens = []
            delay = self._flash_delay_ms(on=False)
            logger.info(
                "Flash cycle %s/%s: OFF (%s ms)",
                self._flash_cycle + 1, FLASH_REPEAT, delay,
            )
        elif self._flash_phase == 2:
            screens = near
            delay = self._flash_delay_ms(on=True)
            self._flash_seq += 1
            logger.info(
                "Flash cycle %s/%s: ON screens %s (%s ms)",
                self._flash_cycle + 1, FLASH_REPEAT, screens, delay,
            )
        else:
            screens = []
            delay = self._flash_delay_ms(on=False)
            logger.info(
                "Flash cycle %s/%s: OFF (%s ms)",
                self._flash_cycle + 1, FLASH_REPEAT, delay,
            )

        if self.image_canvas:
            if screens:
                self.image_canvas.set_pass_screens(screens)
            else:
                self.image_canvas.clear()

        if screens:
            _write_image_action_cue(
                True,
                self._field_screens_map(screens),
                seq=self._flash_seq,
                on_sec=max(0.1, float(delay) / 1000.0),
            )

        self._stop_action_timer()
        self.action_timer = QtCore.QTimer(singleShot=True)
        self.action_timer.timeout.connect(self._advance_flash_phase)
        self.action_timer.start(delay)

    def _advance_flash_phase(self):
        if self.display_phase != "action" or self._action_phase != "flash":
            return
        if self.operator_paused:
            QTimer.singleShot(200, self._advance_flash_phase)
            return
        self._flash_phase += 1
        if self._flash_phase > 3:
            self._flash_phase = 0
            self._flash_cycle += 1
        self._apply_flash_phase()

    def _update_progress_display(self):
        if self.image_based and self.display_phase == "action":
            self.progress_label.hide()
            return
        current = self.current_video_index + 1
        total = len(self.video_files)
        entry = self.video_files[self.current_video_index] if self.video_files else None
        if isinstance(entry, dict):
            name = entry.get("label") or entry.get("path") or "PASS"
        else:
            name = os.path.basename(self.current_video_path or "")
        if len(name) > 40:
            name = name[:37] + "..."
        self.progress_label.setText(f"Action {current}/{total} | {name}")
        self.progress_label.adjustSize()
        self.progress_label.move(self.video_width - self.progress_label.width() - 10,
                                 self.video_height - self.progress_label.height() - 5)
        self.progress_label.show()
        if hasattr(self, '_progress_hide_timer'):
            self._progress_hide_timer.stop()
        self._progress_hide_timer = QtCore.QTimer(singleShot=True)
        self._progress_hide_timer.timeout.connect(lambda: self.progress_label.hide() if not self.underMouse() else None)
        self._progress_hide_timer.start(5000)

    def _show_playlist_status(self):
        total = len(self.video_files)
        kind = "labeled image actions" if (self.image_based and self._label_mode) else (
            "image PASS actions" if self.image_based else "videos"
        )
        self._update_status_file("playing", 0, total, f"Playlist loaded: {total} {kind}")
        logger.info("Playlist loaded: %s %s", total, kind)

    def _opening_card_colors(self):
        """Same background and text colors as the opening card, per field."""
        levels = getattr(self, "_phase_field_levels", None) or {}
        directories = getattr(self, "_phase_field_directories", None) or {}
        subdirectory = str(getattr(self, "_phase_subdirectory", "") or "")
        colors = {}
        for fid in ("A", "B"):
            level_id = str(levels.get(fid) or getattr(self, "_phase_mode_id", "") or "")
            context = " ".join([
                level_id,
                subdirectory,
                str(getattr(self, "video_directory", "") or ""),
                str(getattr(self, "_level_root", "") or ""),
                str(directories.get(fid) or ""),
            ])
            colors[fid] = _level_card_colors(context, "", {})
        return colors

    def _show_waiting_overlay(self, status_text=""):
        if self.image_canvas:
            self.image_canvas.clear()
            self.image_canvas.hide()
        active = self._active_fields()
        if self.waiting_overlay is None:
            self.waiting_overlay = WaitingOverlay(self.videoframe, active_fields=active)
            self.videoframe.installEventFilter(self)
        else:
            self.waiting_overlay.set_active_fields(active)
        # Empty status keeps the same "Processing" / "Results" rings as per-video wait.
        self.waiting_overlay.set_level_colors(self._opening_card_colors())
        self.waiting_overlay.set_status_text(status_text or "")
        self.waiting_overlay.setGeometry(0, 0, self.videoframe.width(), self.videoframe.height())
        self.waiting_overlay.show()
        self.waiting_overlay.raise_()
        self.waiting_overlay.update()

    def _hide_waiting_overlay(self):
        if self.waiting_overlay:
            self.waiting_overlay.hide()
            self.waiting_overlay.deleteLater()
            self.waiting_overlay = None

    def eventFilter(self, obj, event):
        if obj == self.videoframe and event.type() == QtCore.QEvent.Resize:
            if self.waiting_overlay:
                self.waiting_overlay.setGeometry(0, 0, self.videoframe.width(), self.videoframe.height())
        return super().eventFilter(obj, event)

    def _apply_run_phase(self, phase_index, fatal=False):
        """Load playlist for the current phase (single field or dual A+B)."""
        if phase_index < 0 or phase_index >= len(self._run_phases):
            return False
        phase = self._run_phases[phase_index]
        self._phase_index = int(phase_index)
        self._phase_active = list(phase.get("active") or [])
        self._phase_subdirectory = str(phase.get("subdirectory") or "").strip()
        self._phase_mode_id = str(phase.get("mode_id") or self._phase_subdirectory or "").strip()
        self._phase_field_modes = dict(phase.get("field_modes") or {})
        self._phase_field_directories = dict(phase.get("field_directories") or {})
        self._phase_field_levels = dict(phase.get("field_levels") or {})
        self._phase_dual_independent = bool(phase.get("dual_independent"))
        self.video_directory = phase.get("directory") or self._level_root
        _reset_live_action_results()
        self._held_result_badges = {}
        self._result_released_screens = set()
        self._finished_field_screens = {}
        _write_players_fields_active(self._phase_active)
        logger.info(
            "Starting phase %s/%s: %s → %s (active=%s mode=%s dual=%s)",
            phase_index + 1,
            len(self._run_phases),
            phase.get("label"),
            self.video_directory,
            self._phase_active,
            self._phase_mode_id,
            self._phase_dual_independent,
        )

        if self.image_based:
            self.video_files = self._build_image_action_playlist()
            if not self.video_files:
                msg = getattr(self, "_playlist_block_reason", "") or (
                    f"No labeled actions for {phase.get('label')} in:\n{self.video_directory}"
                )
                self._update_status_file("error", 0, 0, msg)
                if fatal:
                    QtWidgets.QMessageBox.critical(None, "Error", msg)
                    self._auto_close(1000)
                    sys.exit(1)
                logger.error(msg)
                return False
            logger.info(
                "Phase playlist: %s step(s) / %s test(s) for %s (label_mode=%s)",
                len(self.video_files),
                LABEL_TEST_COUNT if self._label_mode else 1,
                self._phase_active,
                self._label_mode,
            )
        else:
            self.video_files = self._get_video_files(self.video_directory)
            if not self.video_files:
                msg = f"No video files in:\n{self.video_directory}"
                self._update_status_file("error", 0, 0, msg)
                if fatal:
                    QtWidgets.QMessageBox.critical(None, "Error", msg)
                    self._auto_close(1000)
                    sys.exit(1)
                return False

        self._update_status_file(
            "playing", 0, len(self.video_files),
            f"Starting {phase.get('label') or 'phase'}",
        )
        self.video_count = len(self.video_files)
        if self.image_based and self._label_mode:
            # Prefer highest test_num in playlist (SF-110N = 4; others = 5)
            max_test = 0
            for e in (self.video_files or []):
                if isinstance(e, dict) and e.get("test_num"):
                    try:
                        max_test = max(max_test, int(e["test_num"]))
                    except (TypeError, ValueError):
                        pass
            self.total_videos = max_test or LABEL_TEST_COUNT
        else:
            self.total_videos = self.video_count
        self._post_results_index = None
        self._set_start_time = None
        self.current_video_index = 0
        self.video_end_called = False
        self.waiting_for_results = False
        self.playlist_finished = False
        return True

    def _restart_highest_level(self, info):
        """Play the highest open set again while the reservation still has time."""
        if not self._run_phases:
            return False
        phase = self._run_phases[self._phase_index]
        level = str((info or {}).get("level") or "").strip()
        subdirectory = str((info or {}).get("subdirectory") or "").strip()
        directory = str((info or {}).get("directory") or phase.get("directory") or "").strip()
        if level:
            levels = dict(phase.get("field_levels") or {})
            for fid in phase.get("active") or []:
                levels[fid] = level
            phase["field_levels"] = levels
            phase["subdirectory"] = subdirectory
            phase["mode_id"] = level
        if directory:
            phase["directory"] = directory
            phase["field_directories"] = {
                fid: directory for fid in (phase.get("active") or [])
            }
        self._level_card_shown_for = None
        self._after_final = {}
        logger.info(
            "Reservation time left — repeating %s %s",
            level or phase.get("label"),
            subdirectory,
        )
        if not self._apply_run_phase(self._phase_index, fatal=False):
            return False
        self._prestart_done = False
        self.is_first_video = True
        self.playlist_finished = False
        self._begin_level_intro(0)
        return True

    def _advance_to_next_field_phase(self):
        """After one field's final conclusion → next field, or close."""
        next_idx = self._phase_index + 1
        if next_idx >= len(self._run_phases):
            logger.info("All field phases complete.")
            if not self._is_closing:
                self._status_completed = True
                self._update_status_file(
                    "completed", self.total_videos, self.total_videos,
                    "All fields completed",
                )
                self._auto_close(self.auto_close_delay)
            return
        if not self._apply_run_phase(next_idx, fatal=False):
            # Skip broken phase
            self._phase_index = next_idx
            self._advance_to_next_field_phase()
            return
        self._prestart_done = False
        self.is_first_video = True
        self._begin_level_intro(0)

    def _active_fields(self):
        if getattr(self, "_phase_active", None):
            return list(self._phase_active)
        path = PLAYERS_FIELDS_FILE
        try:
            import simust_fields
            return sorted(simust_fields.load_active_fields(path))
        except Exception:
            return ["A", "B"]

    def _find_latest_report(self):
        realtime_dir = "C:/Users/siama/Documents/simust_realtime_recordings"
        if os.path.exists(realtime_dir):
            subdirs = [d for d in os.listdir(realtime_dir) if os.path.isdir(os.path.join(realtime_dir, d))]
            if subdirs:
                subdirs.sort(key=lambda d: os.path.getctime(os.path.join(realtime_dir, d)), reverse=True)
                newest = os.path.join(realtime_dir, subdirs[0])
                active = self._active_fields()
                # Prefer active field folders only
                search_bases = []
                for fid in active:
                    search_bases.append(os.path.join(newest, f"field_{fid}"))
                search_bases.append(newest)
                for base in search_bases:
                    for fname in ("recognition.json", "results.json"):
                        path = os.path.join(base, fname)
                        if os.path.exists(path):
                            return path
                return newest
        return None

    def _arm_timer(self, ms, callback):
        if self.results_timer:
            self.results_timer.stop()
        self.results_timer = QtCore.QTimer(singleShot=True)
        self.results_timer.timeout.connect(callback)
        self.results_timer.start(max(0, int(ms)))

    def _remaining_wait_ms(self):
        elapsed_ms = int((time.time() - getattr(self, "_wait_started", time.time())) * 1000)
        return max(0, WAIT_ANIMATION_MS - elapsed_ms)

    def _play_intro_audio(self, video_path):
        """Play the intro soundtrack while each screen shows its own picture."""
        try:
            self.player.stop()
            media = self.instance.media_new(os.path.abspath(video_path))
            media.add_option(":no-video")
            self.player.set_media(media)
            self.player.audio_set_volume(100)
            self.player.play()
        except Exception as exc:
            logger.warning("Level intro audio failed: %s", exc)

    def _play_local_clip(self, video_path, rate=1.0):
        if self.image_canvas:
            self.image_canvas.hide()
        self.videoframe.show()
        self.videoframe.raise_()
        self.player.stop()
        self.media = self.instance.media_new(os.path.abspath(video_path))
        self.player.set_media(self.media)
        self.player.video_set_aspect_ratio(f"{COACH_BAND_WIDTH}:{COACH_BAND_HEIGHT}")
        self.player.video_set_scale(1.0)
        self.player.video_set_crop_geometry(f"0:0:{COACH_BAND_WIDTH}:{COACH_BAND_HEIGHT}")
        try:
            self.player.set_rate(rate)
        except Exception:
            pass
        self.player.play()
        self.check_timer.start()

    def _do_per_video_request(self, video_num, start_time, end_time):
        report_path = self._find_latest_report()
        video_path = ""
        if not report_path:
            logger.warning("No report found – skipping per-video results.")
            self.per_video_results_ready.emit("")
            return
        backend_url = "http://127.0.0.1:8000/create-video-results"
        session_dir = os.path.dirname(report_path) if report_path else ""
        # Normalize to session root when pointed at field_A / field_B
        base = os.path.basename(session_dir.rstrip("\\/"))
        if base in ("field_A", "field_B"):
            session_dir = os.path.dirname(session_dir)
        payload = {
            "report_path": report_path,
            "directory": session_dir,
            "start_time": start_time,
            "end_time": end_time,
            "video_index": video_num,
            "total_videos": self.total_videos,
            "display": False,
            "fields": self._active_fields(),
        }
        try:
            if HAS_REQUESTS:
                response = requests.post(backend_url, json=payload, timeout=90)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "error":
                        logger.error(
                            "Per-video results error for test %s: %s",
                            video_num, data.get("message") or data,
                        )
                    candidate = data.get("video_path") or ""
                    if candidate and os.path.exists(candidate):
                        video_path = candidate
                        logger.info("Results video for test %s generated.", video_num)
                    else:
                        logger.error("Per-video results missing file: %s", data)
                else:
                    logger.error("Backend error: %s", response.text)
            else:
                import urllib.request
                req = urllib.request.Request(
                    backend_url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=90) as resp:
                    data = json.loads(resp.read().decode("utf-8") or "{}")
                    candidate = data.get("video_path") or ""
                    if candidate and os.path.exists(candidate):
                        video_path = candidate
        except Exception as e:
            logger.error("Per-video results request failed: %s", e)
        self.per_video_results_ready.emit(video_path)

    def _on_per_video_results_ready(self, video_path):
        if self.operator_paused:
            QTimer.singleShot(200, lambda: self._on_per_video_results_ready(video_path))
            return
        self._arm_timer(self._remaining_wait_ms(), lambda: self._play_per_video_results(video_path))

    def _play_per_video_results(self, video_path):
        if self.operator_paused:
            QTimer.singleShot(200, lambda: self._play_per_video_results(video_path))
            return
        self._hide_waiting_overlay()
        if not video_path or not os.path.exists(video_path):
            logger.warning("Per-video results missing; continuing sequence")
            self._finish_per_video_results()
            return
        self.display_phase = "per_video_results"
        self.waiting_for_results = True
        self.completion_label.hide()
        if self.image_canvas:
            self.image_canvas.hide()
        self._update_status_file(
            "playing_results",
            self._current_test_num(),
            self.total_videos,
            "Playing per-video results...",
        )
        logger.info(
            "Playing per-video results for test %s/%s: %s",
            self._current_test_num(), self.total_videos, video_path,
        )
        self._play_local_clip(video_path, rate=1.0)
        self._arm_timer(PER_VIDEO_RESULTS_MS, self._finish_per_video_results)

    def _finish_per_video_results(self):
        if self.results_timer:
            self.results_timer.stop()
            self.results_timer = None
        try:
            self.player.stop()
        except Exception:
            pass
        self.waiting_for_results = False
        self.display_phase = "action"
        self._do_continue()

    def _continue_to_next_video(self):
        self.waiting_for_results = False
        if self.results_timer:
            self.results_timer.stop()
            self.results_timer = None
        self._hide_waiting_overlay()
        self._do_continue()

    def _do_continue(self):
        """After per-video results: level intro, then next test's first action (or final)."""
        if getattr(self, "_post_results_index", None) is not None:
            next_idx = int(self._post_results_index)
            self._post_results_index = None
        else:
            next_idx = self.current_video_index + 1
        self._set_start_time = None
        if next_idx < len(self.video_files):
            self.current_video_index = next_idx
            self._begin_level_intro(next_idx)
        else:
            self._show_final_summary()

    def _show_final_summary(self):
        logger.info("All action sets done; showing the same wait animation then final results")
        self.display_phase = "wait_final"
        self.waiting_for_results = True
        self._wait_started = time.time()
        self._show_waiting_overlay()
        QTimer.singleShot(100, self._call_final_summary_backend)

    def _call_final_summary_backend(self):
        thread = threading.Thread(target=self._do_final_summary_request, daemon=True)
        thread.start()

    def _do_final_summary_request(self):
        report_path = self._find_latest_report()
        if not report_path:
            self.final_summary_done.emit("")
            return
        backend_url = "http://127.0.0.1:8000/create-results-video"
        session_dir = os.path.dirname(report_path) if report_path else ""
        base = os.path.basename(session_dir.rstrip("\\/"))
        if base in ("field_A", "field_B"):
            session_dir = os.path.dirname(session_dir)
        try:
            response = requests.post(
                backend_url,
                json={
                    "report_path": report_path,
                    "directory": session_dir,
                    "display": False,
                    "fields": self._active_fields(),
                },
                timeout=120,
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    self._after_final = data.get("progress") or {}
                    video_path = data.get("video_path")
                    if video_path and os.path.exists(video_path):
                        self.final_summary_done.emit(video_path)
                        return
            self.final_summary_done.emit("")
        except Exception as e:
            logger.error("Final summary request failed: %s", e)
            self.final_summary_done.emit("")

    def _on_final_summary_done(self, video_path):
        if self.operator_paused:
            QTimer.singleShot(200, lambda: self._on_final_summary_done(video_path))
            return
        self._arm_timer(self._remaining_wait_ms(), lambda: self._play_final_after_wait(video_path))

    def _play_final_after_wait(self, video_path):
        if self.operator_paused:
            QTimer.singleShot(200, lambda: self._play_final_after_wait(video_path))
            return
        self._hide_waiting_overlay()
        if video_path and os.path.exists(video_path):
            self.display_phase = "final"
            phase = (
                self._run_phases[self._phase_index]
                if 0 <= self._phase_index < len(self._run_phases)
                else {}
            )
            self._update_status_file(
                "playing_final", self.total_videos, self.total_videos,
                f"Playing final — {phase.get('label') or 'field'}...",
            )
            logger.info(
                "Playing final summary for %s: %s",
                phase.get("label"), video_path,
            )
            if self.image_canvas:
                self.image_canvas.hide()
            self._play_local_clip(video_path, rate=1.0)

            self.completion_label.setText(
                f"Final — {phase.get('label') or 'field'}..."
            )
            self.completion_label.adjustSize()
            self.completion_label.move((self.video_width - self.completion_label.width()) // 2,
                                       (self.video_height - self.completion_label.height()) // 2)
            self.completion_label.show()

            self.playlist_finished = True
            self._final_play_started_at = time.time()
            self.check_timer.start()

            if self._force_close_timer:
                self._force_close_timer.stop()
            self._force_close_timer = QtCore.QTimer(singleShot=True)
            self._force_close_timer.timeout.connect(self._on_field_final_finished)
            self._force_close_timer.start(60000)
        else:
            logger.warning("Final summary missing for phase — advancing")
            self._on_field_final_finished()

    def _on_field_final_finished(self):
        """One field's conclusion done → next field phase, or stop camera + close."""
        if self._force_close_timer:
            try:
                self._force_close_timer.stop()
            except Exception:
                pass
            self._force_close_timer = None
        try:
            self.player.stop()
        except Exception:
            pass
        self.playlist_finished = False
        self.display_phase = "action"
        self.completion_label.hide()
        self.waiting_for_results = False
        more = self._phase_index + 1 < len(self._run_phases)
        info = getattr(self, "_after_final", None) or {}
        try:
            seconds_left = float(info.get("seconds_left") or 0)
        except (TypeError, ValueError):
            seconds_left = 0
        if info.get("continue_play") and seconds_left > 30 and self._restart_highest_level(info):
            return
        if more:
            logger.info("Field phase done — starting next field")
            self._advance_to_next_field_phase()
            return
        # All fields finished
        if not self._realtime_stopped:
            self._stop_camera_only()
        if not self._is_closing:
            self._status_completed = True
            self._update_status_file(
                "completed", self.total_videos, self.total_videos,
                "All fields completed",
            )
            self._auto_close(self.auto_close_delay)

    def _force_close_with_completion(self):
        """Fallback when final clip never ends."""
        self._on_field_final_finished()

    def _stop_camera_only(self):
        if self._realtime_stopped:
            return
        self._realtime_stopped = True
        try:
            logger.info("Stopping camera process only...")
            if HAS_REQUESTS:
                response = requests.post("http://127.0.0.1:8000/stop-realtime-camera", timeout=10)
                if response.status_code == 200:
                    logger.info("Camera process stopped automatically.")
                else:
                    logger.error(f"Failed to stop camera: {response.text}")
            else:
                import urllib.request
                req = urllib.request.Request("http://127.0.0.1:8000/stop-realtime-camera", method='POST')
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.getcode() == 200:
                        logger.info("Camera process stopped automatically.")
        except Exception as e:
            logger.error(f"Error stopping camera: {e}")

    def _stop_realtime(self):
        if self._realtime_stopped:
            return
        self._realtime_stopped = True
        try:
            logger.info("Stopping realtime process (camera + player) via backend...")
            if HAS_REQUESTS:
                response = requests.post("http://127.0.0.1:8000/stop-realtime", timeout=10)
                if response.status_code == 200:
                    logger.info("Realtime process stopped (both camera and player).")
                else:
                    logger.error(f"Failed to stop realtime: {response.text}")
            else:
                import urllib.request
                req = urllib.request.Request("http://127.0.0.1:8000/stop-realtime", method='POST')
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.getcode() == 200:
                        logger.info("Realtime process stopped (both camera and player).")
        except Exception as e:
            logger.error(f"Error stopping realtime: {e}")

    def _on_video_ended(self):
        if self.display_phase != "action":
            return
        if self.operator_paused or self.video_end_called or self.waiting_for_results:
            return
        self.video_end_called = True
        self.waiting_for_results = True
        self.display_phase = "wait_per_video"
        more_tests = getattr(self, "_post_results_index", None) is not None
        if more_tests:
            logger.info("Test finished — saved video stays open for the next test")
        else:
            try:
                with open(STOP_SAVE_FILE, "w", encoding="utf-8") as f:
                    f.write("1")
                logger.info("Last test finished — asked realtime to stop video save")
            except Exception as exc:
                logger.warning("Could not signal video stop: %s", exc)
        self.check_timer.stop()
        self._stop_action_timer()
        self._wait_started = time.time()
        if self.image_canvas:
            self.image_canvas.clear()
            self.image_canvas.hide()
        self._show_waiting_overlay()
        video_num = self._current_test_num()
        logger.info(
            "Test %s/%s finished; 5s wait then 20s per-video results",
            video_num, self.total_videos,
        )
        try:
            self.player.stop()
        except Exception:
            pass
        start_time = self._set_start_time or self.video_start_time
        end_time = time.time()
        thread = threading.Thread(
            target=self._do_per_video_request,
            args=(video_num, start_time, end_time),
            daemon=True,
        )
        thread.start()

    def _set_speed_with_retry(self, speed, retry_count=0):
        try:
            speed = max(0.25, min(4.0, speed))
            self.player.set_rate(speed)
            QtCore.QThread.msleep(50)
            actual_speed = self.player.get_rate()
            if abs(actual_speed - speed) > 0.05 and retry_count < 3:
                QTimer.singleShot(100, lambda: self._set_speed_with_retry(speed, retry_count + 1))
        except Exception:
            if retry_count < 3:
                QTimer.singleShot(100, lambda: self._set_speed_with_retry(speed, retry_count + 1))

    def _check_speed_changes(self):
        try:
            if getattr(self, "display_phase", "action") != "action":
                return
            current_time = time.time()
            if current_time - self.last_check_time < 0.1:
                return
            if os.path.exists(self.speed_file_path):
                with open(self.speed_file_path, 'r') as f:
                    content = f.read().strip()
                    if content:
                        new_speed = float(content)
                        new_speed = max(0.25, min(4.0, new_speed))
                        if abs(new_speed - self.last_speed) > 0.01:
                            self.last_speed = new_speed
                            self.player_speed = new_speed
                            self._set_speed_with_retry(self.player_speed)
                self.last_check_time = current_time
        except Exception:
            pass

    def _force_top_512(self):
        if not self.videoframe:
            return
        self.videoframe.setGeometry(0, 0, self.video_width, self.video_height)
        self.setFixedSize(self.video_width, self.video_height)
        self.videoframe.raise_()
        if self.image_canvas and self.image_based and self.display_phase in ("action", "level_intro", "level_card"):
            self.image_canvas.setGeometry(0, 0, self.video_width, self.video_height)
            self.image_canvas.show()
            self.image_canvas.raise_()
            if self.display_phase == "level_card":
                self.image_canvas.update()
        elif self.display_phase == "level_card" and self.level_card_label and self.level_card_label.isVisible():
            self.level_card_label.raise_()
        self.videoframe.repaint()
        self.repaint()
        try:
            self.player.video_set_aspect_ratio(f"{COACH_BAND_WIDTH}:{COACH_BAND_HEIGHT}")
            self.player.video_set_scale(1.0)
            self.player.video_set_crop_geometry(f"0:0:{COACH_BAND_WIDTH}:{COACH_BAND_HEIGHT}")
        except:
            pass

    def show_status(self, message, timeout=2000):
        self.status.setText(message)
        self.status.adjustSize()
        self.status.move((self.video_width - self.status.width()) // 2, 20)
        self.status.show()
        self.status_timer.start(timeout)

    def _read_pause_file(self):
        try:
            if not os.path.exists(self.pause_file_path):
                return False
            with open(self.pause_file_path, "r", encoding="utf-8") as f:
                return f.read().strip().lower() in ("1", "true", "yes", "on", "paused")
        except Exception:
            return False

    def _set_vlc_paused(self, paused):
        try:
            if hasattr(self.player, "set_pause"):
                self.player.set_pause(1 if paused else 0)
            elif paused:
                if self.player.is_playing():
                    self.player.pause()
            else:
                self.player.play()
        except Exception as exc:
            logger.warning("VLC pause/resume failed: %s", exc)

    def _apply_operator_pause(self, paused):
        if paused == self.operator_paused:
            return
        self.operator_paused = paused
        if paused:
            self._pause_started_at = time.time()
            try:
                t = self.player.get_time()
                self._paused_media_time = t if t is not None and t >= 0 else None
            except Exception:
                self._paused_media_time = None
            self._freeze_qt_timers()
            self._set_vlc_paused(True)
            self._update_status_file("paused", self.current_video_index + 1, len(self.video_files), "Paused")
            logger.info("Operator pause: video and timers frozen at %s ms", self._paused_media_time)
            return
        dt = time.time() - self._pause_started_at if self._pause_started_at else 0
        if self._pause_started_at and self.video_start_time:
            self.video_start_time += dt
        if self._final_play_started_at:
            self._final_play_started_at += dt
        self._pause_started_at = 0
        self._thaw_qt_timers()
        self._set_vlc_paused(False)
        if self._paused_media_time is not None:
            try:
                self.player.set_time(self._paused_media_time)
            except Exception:
                pass
        self._paused_media_time = None
        if self._pending_start_after_pause:
            self._pending_start_after_pause = False
            self._start_playback()
        self._update_status_file("playing", self.current_video_index + 1, len(self.video_files), "Resumed")
        logger.info("Operator resume: continuing from pause point")

    def _freeze_qt_timers(self):
        frozen = []
        for name in ("results_timer", "close_timer", "play_delay_timer", "_force_close_timer", "action_timer"):
            timer = getattr(self, name, None)
            if timer is None:
                continue
            try:
                if not timer.isActive():
                    continue
                remaining = timer.remainingTime()
                timer.stop()
                frozen.append((name, max(50, remaining if remaining >= 0 else 0)))
            except Exception:
                continue
        self._frozen_qt_timers = frozen

    def _thaw_qt_timers(self):
        for name, remaining in self._frozen_qt_timers:
            timer = getattr(self, name, None)
            if timer is None:
                continue
            try:
                timer.start(remaining)
            except Exception:
                continue
        self._frozen_qt_timers = []

    def _check_operator_pause(self):
        if self._is_closing or self.playlist_finished:
            return
        try:
            self._apply_operator_pause(self._read_pause_file())
        except Exception as exc:
            logger.warning("Pause control check failed: %s", exc)

    def _check_video_position(self):
        if self._is_closing:
            return
        if self.operator_paused:
            return
        if not self.player:
            return

        try:
            if getattr(self, "display_phase", "action") in (
                "wait_per_video", "wait_final", "per_video_results", "level_intro", "prestart"
            ):
                return
            state = self.player.get_state()

            # If we're playing the final video (playlist_finished is True)
            if self.playlist_finished or getattr(self, "display_phase", "") == "final":
                if self._final_play_started_at and (time.time() - self._final_play_started_at) < 2.0:
                    return
                length = 0
                play_time = 0
                try:
                    length = self.player.get_length() or 0
                    play_time = self.player.get_time() or 0
                except Exception:
                    pass
                ended = state in (vlc.State.Ended, vlc.State.Error)
                stopped_after_play = state == vlc.State.Stopped and play_time > 800
                near_end = length > 1000 and play_time >= max(0, length - 400)
                if ended or stopped_after_play or near_end:
                    logger.info("Final video finished for this field phase.")
                    self._on_field_final_finished()
                return

            # Image-based actions end via action_timer, not VLC state
            if self.image_based and self.display_phase == "action":
                return

            # Normal playlist video playback
            if state == vlc.State.Ended:
                logger.info(f"Video ended: {self.current_video_path}")
                self._on_video_ended()
        except Exception as e:
            logger.error(f"Error in _check_video_position: {e}")

    def _next_video(self):
        if self.waiting_for_results:
            return
        if self.playlist_finished:
            self.current_video_index = 0
            self.playlist_finished = False
            self._load_video(0)
        elif self.current_video_index + 1 < len(self.video_files):
            self.current_video_index += 1
            self._load_video(self.current_video_index)

    def _prev_video(self):
        if self.waiting_for_results:
            return
        if self.playlist_finished:
            self.current_video_index = len(self.video_files) - 1
            self.playlist_finished = False
            self._load_video(self.current_video_index)
        elif self.current_video_index - 1 >= 0:
            self.current_video_index -= 1
            self._load_video(self.current_video_index)

    def restart_playlist(self):
        if self.waiting_for_results:
            return
        self.current_video_index = 0
        self.playlist_finished = False
        self.completion_label.hide()
        self._load_video(0)

    def toggle_play(self):
        if self.waiting_for_results:
            return
        if self.playlist_finished:
            self.restart_playlist()
        elif self.player.is_playing():
            self.player.pause()
        else:
            self.player.play()

    def increase_speed(self):
        new_speed = min(4.0, self.player_speed + 0.25)
        self.player_speed = new_speed
        self.last_speed = new_speed
        self._set_speed_with_retry(self.player_speed)
        try:
            with open(self.speed_file_path, 'w') as f:
                f.write(str(self.player_speed))
        except:
            pass

    def decrease_speed(self):
        new_speed = max(0.25, self.player_speed - 0.25)
        self.player_speed = new_speed
        self.last_speed = new_speed
        self._set_speed_with_retry(self.player_speed)
        try:
            with open(self.speed_file_path, 'w') as f:
                f.write(str(self.player_speed))
        except:
            pass

    def reset_speed(self):
        self.player_speed = 1.0
        self.last_speed = 1.0
        self._set_speed_with_retry(1.0)
        try:
            with open(self.speed_file_path, 'w') as f:
                f.write(str(self.player_speed))
        except:
            pass

    def keyPressEvent(self, event):
        key = event.key()
        if key == QtCore.Qt.Key_Space:
            self.toggle_play()
        elif key == QtCore.Qt.Key_N:
            self._next_video()
        elif key == QtCore.Qt.Key_P:
            self._prev_video()
        elif key == QtCore.Qt.Key_R:
            self.restart_playlist()
        elif key == QtCore.Qt.Key_Up:
            self.increase_speed()
        elif key == QtCore.Qt.Key_Down:
            self.decrease_speed()
        elif key == QtCore.Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def mouseMoveEvent(self, event):
        if not self.playlist_finished and not self.waiting_for_results:
            self._update_progress_display()
        super().mouseMoveEvent(event)

    def closeEvent(self, event):
        self._force_cleanup()
        QtWidgets.QApplication.quit()
        event.accept()


# ============================================================
# main()
# ============================================================
def main():
    logger.info("Starting main()")
    # Image-based mode only needs a directory arg for API compatibility with app.py
    if len(sys.argv) < 2:
        app = QtWidgets.QApplication(sys.argv)
        QtWidgets.QMessageBox.critical(None, "Error",
            "Usage: smart_simust_player.py <level-directory> [player_speed] [screen_index]")
        sys.exit(1)

    video_dir = sys.argv[1]
    if not IMAGE_BASED_ACTIONS and not os.path.isdir(video_dir):
        app = QtWidgets.QApplication(sys.argv)
        QtWidgets.QMessageBox.critical(None, "Error", f"Directory not found:\n{video_dir}")
        sys.exit(1)

    player_speed = 1.0
    screen_index = 1
    if len(sys.argv) >= 3:
        try:
            player_speed = float(sys.argv[2])
            player_speed = max(0.25, min(4.0, player_speed))
        except:
            pass
    if len(sys.argv) >= 4:
        try:
            screen_index = int(sys.argv[3])
        except:
            pass

    app = QtWidgets.QApplication(sys.argv)
    screens = app.screens()
    if screen_index >= len(screens):
        screen_index = 0

    player = SmartPlayerWindow(video_dir, player_speed=player_speed, screen_index=screen_index)
    exit_code = app.exec_()

    try:
        player._force_cleanup()
    except:
        pass
    gc.collect()
    logger.info("Player exited with code %d", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()