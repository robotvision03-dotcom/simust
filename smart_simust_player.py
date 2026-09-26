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
    from simust_display_layout import CHART_CENTER_Y, RING_RADIUS, RING_THICKNESS
except ImportError:
    CHART_CENTER_Y = 140
    RING_RADIUS = 63
    RING_THICKNESS = 15
try:
    import simust_fields
except ImportError:
    simust_fields = None


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

WAIT_ANIMATION_MS = 5000
PER_VIDEO_RESULTS_MS = 20000
# Level intro clip played before every test (replaces "starting" ring animation).
LEVEL_INTRO_MS = 4000
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
# Working arcs (adjacent = ~30°). Screens 1 and 8 do not exist.
FOUNDATION_ARC_A = [2, 3, 4, 12, 13, 14]
FOUNDATION_ARC_B = [11, 10, 9, 7, 6, 5]
DISABLED_DISPLAY_SCREENS = {1, 8}
# New arena indices (1–7 per field) → hardware screen ids used by the display.
# Field A: 12→1, 13→2, 14→3, 2→4, 3→5, 4→6, 1→7
# Field B: 5→1, 6→2, 7→3, 9→4, 10→5, 11→6, 8→7
ARENA_A_TO_HW = {1: 12, 2: 13, 3: 14, 4: 2, 5: 3, 6: 4, 7: 1}
ARENA_B_TO_HW = {1: 5, 2: 6, 3: 7, 4: 9, 5: 10, 6: 11, 7: 8}
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
    ("digit", "random", "rotation")
    + FOUNDATION_MATH_MODES
    + tuple(FOUNDATION_COGNITIVE_MODES)
)
_FOUNDATION_SF_RE = re.compile(r"(SF-30N|SF-60N|SF-110N|SF-180N)", re.IGNORECASE)
_cog_alt = "|".join(
    re.escape(m) for m in (
        ("digit", "random", "rotation")
        + FOUNDATION_MATH_MODES
        + tuple(FOUNDATION_COGNITIVE_MODES)
    )
)
_FOUNDATION_EXTRA_RE = re.compile(
    rf"(?:^|[/\\])({_cog_alt})(?:[/\\]?)$",
    re.IGNORECASE,
)
TEAMATE_IMAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "teamate.png")
SLICE_ORDER = [12, 13, 14, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
IMAGE_ACTION_CUE_FILE = "C:/Users/siama/Documents/simust_player/image_action_cue.json"
STOP_SAVE_FILE = "C:/Users/siama/Documents/simust_player/stop_save.txt"
FLASH_TIMING_FILE = "C:/Users/siama/Documents/simust_player/teammate_flash_timing.json"
PLAYERS_FIELDS_FILE = "C:/Users/siama/Documents/simust_player/players_fields.json"
# Rotation mode: fast pass-image spin around the field arc, then hold on one screen.
ROTATION_ARC_A = list(FOUNDATION_ARC_A)  # 2→3→4→12→13→14→…
ROTATION_ARC_B = list(FOUNDATION_ARC_B)  # 11→10→9→7→6→5→…
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


def _entry_series_num(*paths) -> Optional[int]:
    """A-T1..A-T5 (also A.T1.C1) → series 1..5. Time reduction uses this index."""
    blob = " ".join(str(p or "") for p in paths)
    if not re.search(r"L01-Entry", blob, re.I):
        return None
    match = re.search(r"A[-.]T([1-5])", blob, re.I)
    if not match:
        return None
    return int(match.group(1))


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


def _script_for_mode(mode_id: str):
    key = str(mode_id or "").strip().upper()
    for name, script in SF_SCRIPTED_PLAYLISTS.items():
        if name.upper() == key:
            return script
    return None


def _hw_screen_for_field(fid: str, pair) -> Optional[int]:
    """Arena pair (A index, B index) → this field's hardware screen."""
    a_arena, b_arena = int(pair[0]), int(pair[1])
    if str(fid).upper() == "A":
        sid = int(ARENA_A_TO_HW.get(a_arena, a_arena))
    else:
        sid = int(ARENA_B_TO_HW.get(b_arena, b_arena))
    if sid in DISABLED_DISPLAY_SCREENS:
        return None
    return sid


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
                        images[int(sid)] = png
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
    return playlist


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
                    screen_images[int(sid)] = img
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
        return playlist

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
                    field_screens[fid] = list(correct or [])
                    screen_images.update({int(k): v for k, v in probe.items() if v})
                    mode_bits.append(f"{fid}:{mode_low}")
                    continue
                slot = factories[fid](action_in_set, test_num) or {}
                sids = [int(s) for s in (slot.get(fid) or [])]
                if not sids:
                    continue
                img = images.get(fid)
                if not img:
                    continue
                field_screens[fid] = sids
                for s in sids:
                    screen_images[int(s)] = img
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
            lit = "_".join(str(s) for s in sorted(screen_images.keys())
                           if any(int(s) in (field_screens.get(f) or []) for f in field_screens))
            # Prefer listing only correct/target screens in label
            target_ids = sorted(
                int(s) for sids in field_screens.values() for s in sids
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
GAP_SCREENS = (2, 14, 7, 9)
PASS_FLASH_STEPS = (
    {"A": 4, "B": 11},
    {"A": 3, "B": 10},
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
        sid = step.get(fid)
        if sid is not None:
            screens.append(int(sid))
    return screens


def _field_for_screen(screen_id):
    sid = str(int(screen_id))
    if simust_fields is not None:
        return simust_fields.field_for_screens([sid]) or "A"
    if sid in {"2", "3", "4", "12", "13", "14"}:
        return "A"
    return "B"


def _active_field_screens(active_fields):
    """All existing coach-band screens for currently active fields (never 1 or 8)."""
    screens = []
    for fid in sorted(active_fields or []):
        if simust_fields is not None:
            for s in sorted(simust_fields.screens_for_field(fid), key=lambda x: int(x)):
                if int(s) in DISABLED_DISPLAY_SCREENS:
                    continue
                screens.append(int(s))
        elif fid == "A":
            screens.extend([2, 3, 4, 12, 13, 14])
        elif fid == "B":
            screens.extend([5, 6, 7, 9, 10, 11])
    return screens


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
            s1, s2 = int(m.group(3)), int(m.group(4))
            screens = [s1, s2]
            field = _field_for_screen(s1)
            f2 = _field_for_screen(s2)
            if f2 != field and simust_fields is not None:
                field = simust_fields.field_for_screens([str(s1), str(s2)]) or field
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
            # Scripts use new arena indices; convert to hardware screen ids.
            a_arena, b_arena = int(pair[0]), int(pair[1])
            a_sid = int(ARENA_A_TO_HW.get(a_arena, a_arena))
            b_sid = int(ARENA_B_TO_HW.get(b_arena, b_arena))
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
            screen_images = {int(sid): pass_image for sid in lit}
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
    return playlist


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


def _pairs_for_degree_gap(arc: List[int], gap: int) -> List[Tuple[int, int]]:
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
        a, b = int(arc[i]), int(arc[j])
        key = (min(a, b), max(a, b))
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
        slot["A"] = [int(random.choice(FOUNDATION_ARC_A))]
    if "B" in active:
        slot["B"] = [int(random.choice(FOUNDATION_ARC_B))]
    return slot


def _rotation_arc_for_field(fid: str) -> List[int]:
    return list(ROTATION_ARC_A if str(fid).upper() == "A" else ROTATION_ARC_B)


def _rotation_field_slot(active_fields) -> dict:
    """One random stop screen per active field on that field's rotation circle."""
    active = set(active_fields or [])
    slot = {}
    if "A" in active:
        slot["A"] = [int(random.choice(ROTATION_ARC_A))]
    if "B" in active:
        slot["B"] = [int(random.choice(ROTATION_ARC_B))]
    return slot


def _field_all_screens(fid: str) -> List[int]:
    """Every existing coach-band screen belonging to Field A or B (never 1 or 8)."""
    fid = str(fid).upper()
    if simust_fields is not None:
        try:
            return sorted(
                (
                    int(s) for s in simust_fields.screens_for_field(fid)
                    if int(s) not in DISABLED_DISPLAY_SCREENS
                ),
                key=lambda x: int(x),
            )
        except Exception:
            pass
    if fid == "A":
        return [2, 3, 4, 12, 13, 14]
    return [5, 6, 7, 9, 10, 11]


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
        slot[fid] = [int(s) for s in picked]
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


def _render_entry_digit_image(digit: str) -> Optional[str]:
    """Red digit, 3× the equation size, centered like a results ring label."""
    text = str(digit or "").strip()
    if not text:
        return None
    try:
        os.makedirs(MATH_EQ_CACHE_DIR, exist_ok=True)
    except Exception:
        return None
    path = os.path.join(MATH_EQ_CACHE_DIR, f"digit_red3_{text}.png")
    if os.path.isfile(path):
        return path
    try:
        from PyQt5.QtGui import QImage, QPainter, QColor, QFont
        from PyQt5.QtCore import Qt as _Qt
    except Exception as exc:
        logger.warning("Cannot render entry digit (no Qt): %s", exc)
        return None
    w, h = 512, 512
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    font = QFont("Segoe UI", 216, QFont.Bold)
    painter.setFont(font)
    painter.setPen(QColor(255, 0, 0))
    painter.drawText(
        QtCore.QRect(0, 0, w, h),
        _Qt.AlignCenter,
        text,
    )
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
    correct_set = set(int(s) for s in correct)
    screen_images = {}
    used_texts = set()
    for sid in screens:
        if int(sid) in correct_set:
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
            screen_images[int(sid)] = path
    if len(screen_images) < k:
        return [], {}
    # Only keep correct targets that actually have images
    correct_out = [int(s) for s in correct if int(s) in screen_images]
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
                sid for sids in field_screens.values() for sid in sids
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
                sids = [int(s) for s in (slot.get(fid) or [])]
                if not sids:
                    continue
                field_screens[fid] = sids
                for s in sids:
                    screen_images[int(s)] = pass_image
            if not screen_images:
                continue
            lit = "_".join(str(s) for s in sorted(screen_images.keys()))
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
                field_screens[fid] = [int(s) for s in sids]
                for s in sids:
                    screen_images[int(s)] = image_path
            if not screen_images:
                continue
            lit = "_".join(str(s) for s in sorted(screen_images.keys()))
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
    action_set = {int(s) for s in action_screens}
    for sid in _active_field_screens(active_fields):
        if int(sid) in action_set:
            continue
        free_by_field[_field_for_screen(sid)].append(int(sid))

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


def _write_image_action_cue(active, field_screens, seq=0, force_end=False, action="PASS", on_sec=None):
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
            payload["on_sec"] = max(0.1, min(9.9, float(on_sec)))
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
    """3712×512 coach band: per-slice labeled action / filler / gap images or pass.mp4."""

    # Drawn at 85% of the slice (15% smaller than full-tile cover)
    IMAGE_SCALE = 0.85

    def __init__(self, parent=None, image_path=TEAMATE_IMAGE):
        super().__init__(parent)
        self.setStyleSheet("background-color: black;")
        self.setFixedSize(3712, 512)
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

    def clear(self):
        self._stop_screen_video()
        self.active_screens = set()
        self._screen_pixmaps = {}
        self.update()

    def set_pass_screens(self, screen_ids):
        """Legacy: same fallback image on each lit screen."""
        self._stop_screen_video()
        self.active_screens = {int(sid) for sid in screen_ids}
        self._screen_pixmaps = {}
        for sid in self.active_screens:
            if not self._fallback.isNull():
                self._screen_pixmaps[int(sid)] = self._fallback
        self.update()

    def set_screen_images(self, screen_to_path):
        """Map screen id → image path (action, filler, or gap)."""
        self._stop_screen_video()
        self._screen_pixmaps = {}
        self.active_screens = set()
        for sid, path in (screen_to_path or {}).items():
            pix = self._load_pixmap(path)
            if pix is None or pix.isNull():
                continue
            self._screen_pixmaps[int(sid)] = pix
            self.active_screens.add(int(sid))
        self.update()

    def set_screen_video(self, screen_ids, video_path):
        """Play the same pass.mp4 (looping) on each listed screen tile."""
        self.set_screen_videos({int(s): video_path for s in (screen_ids or [])})

    def set_screen_videos(self, screen_to_path, fill=False):
        """Play a full video on each screen. Screens that share a path share one decoder."""
        self._stop_screen_video()
        self._video_fill = bool(fill)
        groups = {}
        for sid, path in (screen_to_path or {}).items():
            try:
                sid = int(sid)
            except (TypeError, ValueError):
                continue
            if sid in DISABLED_DISPLAY_SCREENS:
                continue
            path = str(path or "")
            if not path or not os.path.isfile(path):
                continue
            groups.setdefault(os.path.abspath(path), set()).add(sid)
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
                self.set_screen_images(stills)
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
                self.set_screen_images(stills)
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
                    pixmaps[int(sid)] = pix
                    screens.add(int(sid))
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

    def _tile_rect(self, screen_id: int) -> QtCore.QRect:
        i = SLICE_ORDER.index(int(screen_id))
        n = len(SLICE_ORDER)
        tile_w = 3712 / float(n)
        x0 = int(round(i * tile_w))
        x1 = int(round((i + 1) * tile_w))
        return QtCore.QRect(x0, 0, max(1, x1 - x0), 512)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0))
        if not self._screen_pixmaps:
            painter.end()
            return
        for sid, pix in self._screen_pixmaps.items():
            try:
                tile = self._tile_rect(sid)
            except ValueError:
                continue
            painter.setClipRect(tile)
            if not pix.isNull():
                if getattr(self, "_video_fill", False):
                    scaled = pix.scaled(
                        tile.width(),
                        tile.height(),
                        QtCore.Qt.KeepAspectRatioByExpanding,
                        QtCore.Qt.SmoothTransformation,
                    )
                else:
                    target_w = max(1, int(round(tile.width() * self.IMAGE_SCALE)))
                    target_h = max(1, int(round(tile.height() * self.IMAGE_SCALE)))
                    scaled = pix.scaled(
                        target_w,
                        target_h,
                        QtCore.Qt.KeepAspectRatio,
                        QtCore.Qt.SmoothTransformation,
                    )
                px = tile.x() + (tile.width() - scaled.width()) // 2
                py = tile.y() + (tile.height() - scaled.height()) // 2
                painter.drawPixmap(px, py, scaled)
            painter.setClipping(False)
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
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setMouseTracking(False)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.angle = 0
        self.status_text = ""          # can be set via set_status_text()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_animation)
        self.timer.start(30)

        # Slice order must match the results video
        self.slice_order = [12, 13, 14, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
        self.num_slices = len(self.slice_order)
        self.ring_radius = RING_RADIUS
        self.active_fields = {"A", "B"}
        self.active_slice_nums = set(self.slice_order)
        self.set_active_fields(active_fields)

        # Balls per slice (will be created on first paint)
        self.balls_by_slice = None

        # --- CONTENT OFFSETS PER TILE INDEX ---
        self.content_offset = {
            0: -5,   # tile 0 (slice 12) – shift left
            1: -15,  # tile 1 (slice 13) – shift left
            2: -20,  # tile 2 (slice 14) – shift left
            4: 20,   # tile 4 (slice 2)  – shift right
            5: 15,   # tile 5 (slice 3)  – shift right
            6: 5,    # tile 6 (slice 4)  – shift right
            7: -5,   # tile 7 (slice 5)  – shift left
            8: -15,  # tile 8 (slice 6)  – shift left
            9: -20,  # tile 9 (slice 7)  – shift left
            11: 20,  # tile 11 (slice 9) – shift right
            12: 15,  # tile 12 (slice 10) – shift right
            13: 5    # tile 13 (slice 11) – shift right
        }

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
            tile_width = w / self.num_slices
            padding = 12
            for i, slice_num in enumerate(self.slice_order):
                if int(slice_num) not in self.active_slice_nums:
                    continue
                offset_x = self.content_offset.get(i, 0)
                x0 = int(i * tile_width) + padding + offset_x
                y0 = padding
                width = int(tile_width) - 2 * padding
                height = h - 2 * padding
                for ball in self.balls_by_slice[i]:
                    ball.update(x0, y0, width, height)

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(10, 12, 18))

        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return

        tile_width = w / self.num_slices

        # Draw tile boundaries only across the active half
        painter.setPen(QPen(QColor(80, 80, 100, 80), 1))
        for i in range(1, self.num_slices):
            left_num = int(self.slice_order[i - 1])
            right_num = int(self.slice_order[i])
            if left_num not in self.active_slice_nums and right_num not in self.active_slice_nums:
                continue
            x_line = int(i * tile_width)
            painter.drawLine(x_line, 0, x_line, h)

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
                if int(slice_num) not in self.active_slice_nums:
                    self.balls_by_slice.append([])
                    continue
                num_balls = random.randint(2, 3)
                slice_balls = []
                padding = 12
                offset_x = self.content_offset.get(i, 0)
                x0 = int(i * tile_width) + padding + offset_x
                y0 = padding
                width = int(tile_width) - 2 * padding
                height = h - 2 * padding
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
            if int(slice_num) not in self.active_slice_nums:
                continue
            offset_x = self.content_offset.get(i, 0)
            cx = int((i + 0.5) * tile_width) + offset_x
            cy = CHART_CENTER_Y

            # Ring
            radius = min(self.ring_radius, int(tile_width // 2))
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

            painter.setPen(QColor(255, 255, 255))
            font = QFont("Segoe UI", 12 if text2 else 14, QFont.Bold)
            painter.setFont(font)

            metrics = painter.fontMetrics()
            tw1 = metrics.width(text1)
            th1 = metrics.height()
            if text2:
                tw2 = metrics.width(text2)
                th2 = metrics.height()
                total_text_width = max(tw1, tw2) + 20
                total_text_height = th1 + th2 + 12
                x_text = cx - total_text_width // 2
                y_text = cy - total_text_height // 2
                painter.setBrush(QBrush(QColor(0, 0, 0, 200)))
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(x_text, y_text, total_text_width, total_text_height, 8, 8)
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(cx - tw1//2, y_text + th1 + 4, text1)
                painter.drawText(cx - tw2//2, y_text + th1 + 8 + th2, text2)
            else:
                tw = metrics.width(text1)
                th = metrics.height()
                total_text_width = tw + 20
                total_text_height = th + 12
                x_text = cx - total_text_width // 2
                y_text = cy - total_text_height // 2
                painter.setBrush(QBrush(QColor(0, 0, 0, 200)))
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(x_text, y_text, total_text_width, total_text_height, 8, 8)
                painter.setPen(QColor(255, 255, 255))
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
        self.video_width = 3712
        self.video_height = 512
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
            '--aspect-ratio', '3712:512',
            '--network-caching=300', '--file-caching=300', '--no-xlib',
            '--no-video-on-top', '--no-video-deco',
            '--scale=1', '--zoom=1', '--crop=0:0:3712:512'
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

        if not getattr(self, "_one_field_build", False) and (
            self._field_levels_differ() or self._field_modes_differ()
        ):
            parts = {}
            for fid in ("A", "B"):
                if fid not in active:
                    continue
                parts[fid] = self._build_one_field_playlist(fid)
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

        series_num = _entry_series_num(getattr(self, "_level_root", ""), self.video_directory)
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
                        if int(s) not in field_screens[field]:
                            field_screens[field].append(int(s))
                        screen_images[int(s)] = part["path"]
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
        directory = str((getattr(self, "_phase_field_directories", None) or {}).get(fid) or "").strip()
        if directory:
            for pat, key in _LEVEL_INTRO_PATH_RULES:
                if pat.search(directory):
                    hit = _intro_video_for_key(key)
                    if hit:
                        return hit
        return _find_level_intro_video(directory or self.video_directory or self._level_root)

    def _begin_level_intro(self, next_index=0):
        """Play the level clip on every screen of each active field before a test."""
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
                screen_to_video[int(sid)] = intro
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
            out.setdefault(fid, []).append(int(sid))
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
        self._label_phase = "gap"  # gap_N before action N
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
                # gap_N before action N (gap_1 before first action; gap_2 between 1→2)
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
        self.player.video_set_aspect_ratio("3712:512")
        self.player.video_set_scale(1.0)
        self.player.video_set_crop_geometry("0:0:3712:512")
        self.player.play()
        self._update_progress_display()
        self.check_timer.start()

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
                gap_images = {
                    int(s): p for s, p in dict(held).items()
                    if _field_for_screen(s) in active and int(s) not in DISABLED_DISPLAY_SCREENS
                }
            elif gap_path:
                for sid in GAP_SCREENS:
                    if _field_for_screen(sid) in active:
                        gap_images[int(sid)] = gap_path
            if self.image_canvas:
                if gap_images:
                    self.image_canvas.set_screen_images(gap_images)
                else:
                    # No gap image → black (nothing displayed)
                    self.image_canvas.clear()

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

        screen_images = dict(entry.get("screen_images") or {})
        screen_images = {
            int(s): p for s, p in screen_images.items()
            if _field_for_screen(s) in active and int(s) not in DISABLED_DISPLAY_SCREENS
        }
        action_screens = list(screen_images.keys())
        # Math modes already fill every field screen with equations — never overlay fillers.
        fillers = {}
        if self._asset_fillers and not entry.get("no_fillers") and not entry.get("math_op"):
            fillers = _pick_filler_placements(
                action_num, action_screens, active, self._asset_fillers or {}
            )
        for sid, path in fillers.items():
            if int(sid) not in screen_images:
                screen_images[int(sid)] = path

        # Cue only correct/target screens (math: 2 true equations per field).
        # Display may show equations on every screen via screen_images.
        raw_fs = entry.get("field_screens") or {}
        field_screens = {}
        if isinstance(raw_fs, dict) and raw_fs:
            for fid, sids in raw_fs.items():
                fid_u = str(fid).upper()
                if fid_u not in active:
                    continue
                field_screens[fid_u] = [
                    int(s) for s in (sids or [])
                    if int(s) not in DISABLED_DISPLAY_SCREENS
                ]
        if not field_screens:
            for sid in action_screens:
                fid = _field_for_screen(sid)
                if fid in active:
                    field_screens.setdefault(fid, []).append(int(sid))

        # Lit screens for display + cue (prefer explicit field_screens)
        lit_screens = []
        for sids in field_screens.values():
            lit_screens.extend(int(s) for s in sids)
        if not lit_screens:
            lit_screens = list(action_screens)

        video_path = entry.get("screen_video")
        if self.image_canvas:
            if video_path and os.path.isfile(str(video_path)):
                self.image_canvas.set_screen_video(lit_screens, str(video_path))
            else:
                self.image_canvas.set_screen_images(screen_images)
            # Paint now. The old timer started before the second monitor showed
            # the image, so Kinovea measured ~2.6s of a 3.0s hold.
            self.image_canvas.repaint()
            QtWidgets.QApplication.processEvents()

        self._flash_seq += 1
        delay = self._flash_delay_ms(on=True)
        on_sec = max(0.1, float(delay) / 1000.0)
        self._pass_shown_at = time.perf_counter()
        self._pass_on_ms = int(delay)
        _write_image_action_cue(
            True,
            field_screens,
            seq=self._flash_seq,
            action=action_name,
            on_sec=on_sec,
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
        encode = {
            int(s): p for s, p in (entry.get("encode_images") or {}).items()
            if _field_for_screen(s) in set(self._active_fields())
        }
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
            arc = [int(s) for s in (spin_arcs.get(fid) or _rotation_arc_for_field(fid))]
            if not arc:
                continue
            targets = [int(s) for s in (stop.get(fid) or [])]
            target = targets[0] if targets else int(arc[0])
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
                self.image_canvas.set_screen_images(frame_images)
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
        if shown is not None and need_ms > 0:
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

        # End of test set → per-video results, then resume at next_idx (or final)
        self._post_results_index = next_idx if next_idx < len(self.video_files) else None
        self._on_video_ended()

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
                msg = (
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
        self.player.video_set_aspect_ratio("3712:512")
        self.player.video_set_scale(1.0)
        self.player.video_set_crop_geometry("0:0:3712:512")
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
        if self.image_canvas and self.image_based and self.display_phase in ("action", "level_intro"):
            self.image_canvas.setGeometry(0, 0, self.video_width, self.video_height)
            self.image_canvas.show()
            self.image_canvas.raise_()
        self.videoframe.repaint()
        self.repaint()
        try:
            self.player.video_set_aspect_ratio("3712:512")
            self.player.video_set_scale(1.0)
            self.player.video_set_crop_geometry("0:0:3712:512")
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