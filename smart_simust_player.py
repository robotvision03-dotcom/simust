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
        content_band_layout,
        content_band_center_y,
        content_band_mask_span,
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

    def content_band_center_y(screen_id, height=None):
        height = COACH_BAND_HEIGHT if height is None else int(height)
        return int(CHART_CENTER_Y) + int(round(height * float(RESULTS_BAND_DROP)))

    def content_band_layout(index, screen_id, width=None, height=None, count=None):
        left, _right, rect_w = content_x_box(index, screen_id, width, count)
        cx = int(left) + int(rect_w) // 2
        cy = content_band_center_y(screen_id, height)
        return int(left), int(rect_w), cx, cy

    def content_band_mask_span(index, screen_id, width=None, height=None, count=None):
        width = COACH_BAND_WIDTH if width is None else int(width)
        count = len(DISPLAY_SLICE_ORDER) if count is None else max(1, int(count))
        x0, x1 = slice_x_span(index, width, count)
        left, rect_w, _cx, _cy = content_band_layout(index, screen_id, width, height, count)
        return min(int(x0), int(left)), max(int(x1), int(left) + int(rect_w))

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
# Fallback if the starting video length cannot be read.
LEVEL_INTRO_MS = 4000
# Keep the last frame of the starting video on screen this long after it ends.
LEVEL_INTRO_HOLD_MS = 1000
LEVEL_CARD_MS = 5000
LEVEL_INTRO_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
SCREEN_SAVER_VIDEO = "screen_saver.mp4"
CABINET_CONTROLS_FILE = "cabinet_controls.json"
# Launch token from app.py when System + Screen saver are on and no realtime is running.
IDLE_SCREENSAVER_ARG = "__screensaver__"
# Idle saver box: 40% smaller than full-cabinet (0.60 of width/height).
SCREEN_SAVER_SCALE = 0.60
# Key → candidate filenames (elite file is currently misspelled "eite.mp4").
LEVEL_INTRO_FILES = {
    "foundation": ("foundation.mp4",),
    "entry": ("entry.mp4",),
    "activated": ("activated.mp4",),
    "high-performance": ("high-performance.mp4",),
    "elite": ("eite.mp4", "elite.mp4"),
    "world-class": ("world-class.mp4",),
}
# Opening card: logo above the beginning information (all bands).
# +30% vs prior 0.728 / 0.42 box (was already +40% over the original 0.52 / 0.30).
OPENING_LOGO_MAX_WIDTH = 0.946
OPENING_LOGO_MAX_HEIGHT = 0.546
# Text under the opening logo.
OPENING_LOGO_TEXT_GAP_LINES = 0
# Extra downward shift of opening-card text (fraction of screen height).
OPENING_LOGO_TEXT_DOWN_FRAC = 0.20
# Pull that text back up by this many lines (was 1; +2 more for visibility under logo).
OPENING_LOGO_TEXT_LIFT_LINES = 3
# World Class digits: keep clear of the top/bottom screen edges.
WC_TEXT_EDGE_MARGIN = 0.10
LEVEL_OPENING_LOGO_FILES = {
    "foundation": ("logo_video_foundation.mp4",),
    "entry": ("logo_video_Entry.mp4",),
    "activated": ("logo_video_activated.mp4",),
    "high-performance": ("logo_video_high_performance.mp4",),
    "elite": ("logo_video_Elite.mp4",),
    # Current static name is logo_image_world_class.mp4 (kept legacy aliases too).
    "world-class": ("logo_image_world_class.mp4", "logo_video_world_class.mp4"),
}
# Keep old name for any callers that still reference it.
ACTIVATED_LOGO_VIDEO = "logo_video_activated.mp4"
ACTIVATED_LOGO_MAX_WIDTH = OPENING_LOGO_MAX_WIDTH
ACTIVATED_LOGO_MAX_HEIGHT = OPENING_LOGO_MAX_HEIGHT
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
# Scripted SF: 5 tests × 10 actions. On=3.0s, Gap=0.5s, fixed (no speed scale).
SF_TEST_COUNT = 5
SF_SCRIPTED_ON_MS = 3000
SF_SCRIPTED_GAP_MS = 500
SF110N_GAP_MS = SF_SCRIPTED_GAP_MS  # alias
# After pass image is on, briefly flash a digit/letter on the *next* screen
# so the player knows where the following pass will land. Advance itself still
# waits for the ball in the goal (finish-balls / advance_on_goal).
SF_NEXT_HINT_DELAY_MS = 1000
SF_NEXT_HINT_HOLD_MS = 1000
SF_NEXT_HINT_LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"

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


def _sf_series(*pair_lists, tests=SF_TEST_COUNT):
    """5 tests, 10 actions each. Later tests repeat the stored screen order."""
    source = [list(p)[:10] for p in pair_lists if p]
    if not source:
        return {}
    count = max(1, int(tests or SF_TEST_COUNT))
    return {
        i: {"on_ms": SF_SCRIPTED_ON_MS, "pairs": list(source[(i - 1) % len(source)])}
        for i in range(1, count + 1)
    }


SF30N_SCRIPT = _sf_series(_SF30_T1, _SF30_T2)
SF60N_SCRIPT = _sf_series(_SF60_T1, _SF60_T2)
SF110N_SCRIPT = _sf_series(_SF110_T1)
SF180N_SCRIPT = _sf_series(_SF180_T1)
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
# Activated A1.T1..A1.T5: odd-one-out on each field (5 same / 1 different).
# T1/T2=1-digit, T3=2-digit, T4=3-digit, T5=similar 3-letter triples (e.g. LOL vs TOL).
# Timing matches Entry/Activated: set 1 is 3.0s; each later set is 10% faster.
# Background is the Activated level color on every screen.
ACTIVATED_A1_BG = (175, 195, 213)
ACTIVATED_A1_LETTER_GROUPS = (
    ("L", "T", "I", "J"),
    ("O", "Q", "D", "C", "G"),
    ("E", "F", "B", "P", "R"),
    ("U", "V", "W"),
    ("M", "N", "H"),
    ("S", "Z"),
    ("X", "Y", "K"),
)
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
ELITE_S2_ON_MIN_MS = 2600
ELITE_GAP_MS = 500
ELITE_ZERO_COLOR = (255, 152, 0)
ELITE_S2_SYMBOLS = (
    "$", "%", "#", "@", "&", "*", "!", "?", "+", "=", "~", "€", "£", "¥", "§",
)
# Elite S2 tests 3–5: similar geometric marks instead of punctuation characters.
ELITE_S2_SHAPES = (
    "●", "○", "◆", "◇", "■", "□", "▲", "△", "◎", "◉", "◈", "✦", "★", "☆",
)
# High Performance S2 uses the band page color (same as opening card).
HP_S2_BG = (49, 95, 145)
# One shared patch color behind every middle letter (KOK / KUK, etc.).
HP_S2_MID_BG = (255, 196, 64)
ELITE_S2_BG = (75, 31, 120)
# World Class S2 motion themes: T1 flowers, then fruits / animals / space / orbs.
WORLD_S2_FLOWER_SEEDS = (11, 29, 47, 63, 81)
WORLD_S2_THEMES = ("flowers", "fruits", "animals", "space", "orbs")
# Mild v2 baseline × 1.4 → denser / harder camouflage.
WORLD_S2_CAMO_SEVERITY = 1.4
WORLD_S2_MOTION_FRAMES = 24
WORLD_S2_MOTION_FPS = 20
HP_S2_FLOWER_SEED = 71
# Realistic bouncing sprites (Pillow + NumPy).
FLOWER_BOUNCE_COUNT = 8
# One looping clip per theme — never block Realtime Play on encode.
_MOTION_BG_LOCK = threading.Lock()
_MOTION_BG_BUSY = set()
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
# World Class rotates these backgrounds every action (not once per test).
WORLD_ACTION_BG = (
    (8, 24, 90),
    (0, 55, 28),
    (48, 8, 72),
    (90, 8, 12),
    (0, 48, 52),
    (24, 12, 64),
    (64, 28, 0),
    (0, 36, 64),
    (72, 0, 40),
    (16, 48, 16),
    (40, 8, 8),
    (8, 40, 48),
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
    ("digit", "rotation", "omid_2", "omid")
    + FOUNDATION_MATH_MODES
    + tuple(FOUNDATION_COGNITIVE_MODES)
)
_FOUNDATION_SF_RE = re.compile(r"(SF-30N|SF-60N|SF-110N|SF-180N)", re.IGNORECASE)
# omid_2 before omid so folder names do not match the shorter token first.
_cog_alt = "|".join(
    re.escape(m) for m in (
        ("digit", "rotation", "omid_2", "omid")
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
        level_id = s.get("level") or ""
        # Elite / World Class: one chosen field still lights all 12 screens.
        if _combined_level_band(level_id):
            other = "B" if s["field"] == "A" else "A"
            modes = {s["field"]: s["mode_id"], other: s["mode_id"]}
            dirs = {s["field"]: s["directory"], other: s["directory"]}
            levels = {s["field"]: level_id, other: level_id}
            return [{
                "active": ["A", "B"],
                "directory": s["directory"] or root,
                "subdirectory": s["subdirectory"],
                "mode_id": s["mode_id"],
                "field_modes": modes,
                "field_directories": dirs,
                "field_levels": levels,
                "dual_independent": False,
                "label": (
                    f"{s['field']}+{other}[{level_id or s['subdirectory'] or s['mode_id'] or '?'}]"
                ),
                "player_id": s["player_id"],
            }]
        return [{
            "active": [s["field"]],
            "directory": s["directory"],
            "subdirectory": s["subdirectory"],
            "mode_id": s["mode_id"],
            "field_modes": {s["field"]: s["mode_id"]},
            "field_levels": {s["field"]: level_id},
            "label": f"Field {s['field']}" + (f" [{s['subdirectory']}]" if s["subdirectory"] else ""),
            "player_id": s["player_id"],
        }]

    # Both A and B — always together so neither half stays dark.
    modes = {s["field"]: s["mode_id"] for s in slots}
    dirs = {s["field"]: s["directory"] for s in slots}
    levels = {s["field"]: s.get("level") or "" for s in slots}
    same_mode = len(set(m for m in modes.values() if m)) == 1 and all(modes.values())
    same_level = len(set(lv for lv in levels.values() if lv)) <= 1
    combined = any(_combined_level_band(lv) for lv in levels.values())
    if combined:
        # Keep both halves on the shared Elite / World Class set.
        lead = next(
            (s for s in slots if _combined_level_band(s.get("level") or "")),
            slots[0],
        )
        lead_level = lead.get("level") or ""
        lead_mode = lead.get("mode_id") or ""
        lead_dir = lead.get("directory") or root
        modes = {"A": lead_mode, "B": lead_mode}
        dirs = {"A": lead_dir, "B": lead_dir}
        levels = {"A": lead_level, "B": lead_level}
        same_mode = True
        same_level = True
    label_parts = [
        f"{s['field']}[{s.get('level') or s['subdirectory'] or s['mode_id'] or '?'}]"
        for s in slots
    ]
    return [{
        "active": ["A", "B"] if combined else [s["field"] for s in slots],
        "directory": dirs.get("A") or dirs.get("B") or root,
        "subdirectory": (modes.get("A") if same_mode and same_level else ""),
        "mode_id": (modes.get("A") if same_mode and same_level else "dual"),
        "field_modes": modes,
        "field_directories": dirs,
        "field_levels": levels,
        "dual_independent": (not combined) and ((not same_mode) or (not same_level)),
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
    """S1.T1..S1.T5 (legacy A-T1) inside a level band → series 1..5."""
    blob = " ".join(str(p or "") for p in paths)
    if not re.search(band, blob, re.I):
        return None
    if re.search(r"S2[.-]T[1-5]|A1[-.]T[1-5]", blob, re.I):
        return None
    match = re.search(r"S1[.-]T([1-5])", blob, re.I)
    if match:
        return int(match.group(1))
    match = re.search(r"(?<!\d)A[-.]T([1-5])", blob, re.I)
    if not match:
        return None
    return int(match.group(1))


def _entry_series_num(*paths) -> Optional[int]:
    """S1.T1..S1.T5 (legacy A-T) → series 1..5. Time reduction uses this index."""
    return _band_series_num(*paths, band=r"L01-Entry")


def _activated_series_num(*paths) -> Optional[int]:
    """Activated S1.T1..S1.T5 only (not S2.T*)."""
    blob = " ".join(str(p or "") for p in paths)
    if not re.search(r"L02-Activated", blob, re.I):
        return None
    if re.search(r"S2[.-]T[1-5]|A1[-.]T[1-5]", blob, re.I):
        return None
    match = re.search(r"S1[.-]T([1-5])", blob, re.I)
    if match:
        return int(match.group(1))
    match = re.search(r"(?<!\d)A[-.]T([1-5])", blob, re.I)
    if not match:
        return None
    return int(match.group(1))


def _activated_a1_series_num(*paths) -> Optional[int]:
    """Activated S2.T1..S2.T5 (legacy A1.T) → series 1..5."""
    blob = " ".join(str(p or "") for p in paths)
    if not re.search(r"L02-Activated", blob, re.I):
        return None
    match = re.search(r"S2[.-]T([1-5])", blob, re.I)
    if match:
        return int(match.group(1))
    match = re.search(r"A1[-.]T([1-5])", blob, re.I)
    if not match:
        return None
    return int(match.group(1))


def _high_performance_series_num(*paths) -> Optional[int]:
    return _band_series_num(*paths, band=r"L03-HighPerformance|High[-_ ]?Performance")


def _band_s2_series_num(*paths, band: str) -> Optional[int]:
    """S2.T1..S2.T5 inside a level band → series 1..5."""
    blob = " ".join(str(p or "") for p in paths)
    if not re.search(band, blob, re.I):
        return None
    match = re.search(r"S2[.-]T([1-5])", blob, re.I)
    if not match:
        return None
    return int(match.group(1))


def _high_performance_s2_series_num(*paths) -> Optional[int]:
    return _band_s2_series_num(
        *paths, band=r"L03-HighPerformance|High[-_ ]?Performance"
    )


def _elite_series_num(*paths) -> Optional[int]:
    return _band_series_num(*paths, band=r"L04-Elite")


def _elite_s2_series_num(*paths) -> Optional[int]:
    return _band_s2_series_num(*paths, band=r"L04-Elite")


def _world_class_series_num(*paths) -> Optional[int]:
    return _band_series_num(*paths, band=r"L05-WorldClass|World[-_ ]?Class")


def _world_class_s2_series_num(*paths) -> Optional[int]:
    return _band_s2_series_num(*paths, band=r"L05-WorldClass|World[-_ ]?Class")


def _combined_level_band(text) -> Optional[str]:
    """Elite and World Class use both fields as one. World Class is checked first."""
    blob = str(text or "")
    if re.search(r"L05-WorldClass|World[-_ ]?Class", blob, re.I):
        return "world-class"
    if re.search(r"L04-Elite", blob, re.I):
        return "elite"
    return None


COMBINED_PLAY_MESSAGE = (
    "Elite and World Class use all 12 screens. Pick Field A or Field B (or both) "
    "on the same Elite set or the same World Class set."
)


def _combined_series_group_and_num(text, band: str) -> Tuple[Optional[int], Optional[int]]:
    """Return (series_group, set_num). Group 2 is S2.T*; group 1 is S1.T*."""
    if band == "world-class":
        s2 = _world_class_s2_series_num(text)
        if s2:
            return 2, s2
        s1 = _world_class_series_num(text)
        return (1, s1) if s1 else (None, None)
    s2 = _elite_s2_series_num(text)
    if s2:
        return 2, s2
    s1 = _elite_series_num(text)
    return (1, s1) if s1 else (None, None)


def _safe_cache_token(text) -> str:
    """Filename-safe token so symbols like * ? $ work on Windows cache paths."""
    out = []
    for ch in str(text or ""):
        if ch.isalnum() or ch in "-_.":
            out.append(ch)
        else:
            out.append("u%04x" % ord(ch))
    return "".join(out) or "x"


def _combined_play_decision(active, field_levels=None, field_directories=None, *extra):
    """None when this play is not Elite or World Class.

    Otherwise ("play", band, series, group) or ("block", message).
    Group is 1 for S1.T* and 2 for S2.T*.
    One field is enough: the other half lights automatically for all 12 screens.
    If both fields are set, they must share the same band and set.
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
        group, series = _combined_series_group_and_num(text, band)
        found.append((band, series, group))
    if not found:
        blob = " ".join(str(part or "") for part in extra)
        band = _combined_level_band(blob)
        if not band:
            return None
        group, series = _combined_series_group_and_num(blob, band)
        found = [(band, series, group)]
    bands = {band for band, _series, _group in found}
    series_nums = {series for _band, series, _group in found}
    groups = {group for _band, _series, group in found}
    ready = (
        len(found) >= 1
        and len(bands) == 1
        and len(series_nums) == 1
        and len(groups) == 1
        and None not in series_nums
        and None not in groups
    )
    if not ready:
        return ("block", COMBINED_PLAY_MESSAGE)
    return (
        "play",
        next(iter(bands)),
        next(iter(series_nums)),
        next(iter(groups)),
    )


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


def _a1_random_digit(width: int) -> str:
    width = max(1, min(3, int(width)))
    if width == 1:
        return str(random.randint(0, 9))
    low = 10 ** (width - 1)
    high = (10 ** width) - 1
    return str(random.randint(low, high))


def _a1_digit_pair(width: int) -> Tuple[str, str]:
    """Same value on five screens; one different value of the same digit width."""
    same = _a1_random_digit(width)
    odd = _a1_random_digit(width)
    tries = 0
    while odd == same and tries < 24:
        odd = _a1_random_digit(width)
        tries += 1
    if odd == same:
        if width == 1:
            odd = str((int(same) + 1) % 10)
        else:
            odd = str(int(same) + 1) if int(same) < (10 ** width) - 1 else str(int(same) - 1)
    return same, odd


def _a1_similar_letter_pair() -> Tuple[str, str]:
    """ABA triple like KOK; the odd screen only changes the middle letter (KUK)."""
    groups = [g for g in ACTIVATED_A1_LETTER_GROUPS if len(g) >= 2]
    outer_group = random.choice(groups)
    outer = random.choice(outer_group)
    mid_choices = [g for g in ACTIVATED_A1_LETTER_GROUPS if g is not outer_group and len(g) >= 2]
    mid_group = random.choice(mid_choices or groups)
    mid_same, mid_odd = random.sample(list(mid_group), 2)
    same = f"{outer}{mid_same}{outer}"
    odd = f"{outer}{mid_odd}{outer}"
    return same, odd


def _a1_value_pair(series_num: int) -> Tuple[str, str]:
    series = max(1, min(5, int(series_num)))
    widths = {1: 1, 2: 1, 3: 2, 4: 3}
    if series in widths:
        return _a1_digit_pair(widths[series])
    return _a1_similar_letter_pair()


def _build_activated_a1_playlist(series_num: int, active_fields) -> List[dict]:
    """5 tests × 6 actions. Each action is odd-one-out on Field A and Field B.

    Every screen uses the Activated level background color. The different value
    on each field is the pass target for that action.
    """
    active = [f for f in ("A", "B") if f in set(active_fields or [])]
    if not active:
        return []
    on_ms, gap_ms = _entry_series_timing_ms(series_num)
    bg = ACTIVATED_A1_BG
    playlist = []
    for test_num in range(1, ENTRY_TEST_COUNT + 1):
        for action_in_set in range(1, ENTRY_ACTIONS_PER_TEST + 1):
            images = {}
            field_screens = {}
            labels = []
            for fid in active:
                same, odd = _a1_value_pair(series_num)
                odd_screen = random.randint(1, ENTRY_ACTIONS_PER_TEST)
                for screen in range(1, ENTRY_ACTIONS_PER_TEST + 1):
                    text = odd if screen == odd_screen else same
                    if len(str(text)) == 3 and str(text).isalpha():
                        # Middle letter only gets a distinct background patch.
                        png = _render_middle_colored_text_image(
                            str(text),
                            bg,
                            (255, 255, 255),
                            (20, 24, 32),
                            mid_bg=(255, 196, 64),
                        )
                    else:
                        png = _render_entry_digit_image(str(text), bg=bg)
                    if not png:
                        continue
                    sid = _hw_screen_for_field(fid, (screen, screen))
                    if sid is not None:
                        images[sid] = png
                goal_sid = _hw_screen_for_field(fid, (odd_screen, odd_screen))
                if goal_sid is not None:
                    field_screens[fid] = [goal_sid]
                labels.append(f"{fid}:{same}/{odd}@{odd_screen}")
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
                "arena_pair": (1, 1),
                "field_screens": field_screens,
                "screen_images": dict(images),
                "gap_screen_images": dict(images),
                "label": (
                    f"Activated A1.T{series_num} T{test_num}/{ENTRY_TEST_COUNT} "
                    f"a{action_in_set}/{ENTRY_ACTIONS_PER_TEST} "
                    f"{' '.join(labels)} on={on_ms}ms gap={gap_ms}ms"
                ),
                "path": f"image://Activated/A1.T{series_num}/test{test_num}/{action_in_set}",
            })
    return _stamp_finish_balls(playlist)


def _hp_s2_confusable_middle_pair() -> Tuple[str, str, Tuple[int, int, int]]:
    """ABA triple; odd changes the middle letter only. Patch color is shared."""
    groups = [g for g in ACTIVATED_A1_LETTER_GROUPS if len(g) >= 2]
    outer_group = random.choice(groups)
    outer = random.choice(outer_group)
    mid_group = random.choice([g for g in groups if g is not outer_group] or groups)
    mid_same, mid_odd = random.sample(list(mid_group), 2)
    same = f"{outer}{mid_same}{outer}"
    odd = f"{outer}{mid_odd}{outer}"
    return same, odd, (255, 255, 255)


def _build_high_performance_s2_playlist(series_num: int, active_fields) -> List[dict]:
    """HP S2: 3-letter odd-one-out on bouncing realistic flower backgrounds."""
    active = [f for f in ("A", "B") if f in set(active_fields or [])]
    if not active:
        return []
    on_ms, gap_ms = _entry_series_timing_ms(series_num)
    seed = int(HP_S2_FLOWER_SEED) + int(series_num) * 17
    # Never block Realtime Play — warm shared flower clip in the background.
    motion_bg = _ensure_wc_motion_bg_video("flowers", seed, base_rgb=HP_S2_BG)
    playlist = []
    for test_num in range(1, ENTRY_TEST_COUNT + 1):
        for action_in_set in range(1, ENTRY_ACTIONS_PER_TEST + 1):
            images = {}
            overlay_images = {}
            field_screens = {}
            labels = []
            for fid in active:
                same, odd, outer_fg = _hp_s2_confusable_middle_pair()
                odd_screen = random.randint(1, ENTRY_ACTIONS_PER_TEST)
                for screen in range(1, ENTRY_ACTIONS_PER_TEST + 1):
                    text = odd if screen == odd_screen else same
                    # Same amber patch behind every middle letter on every screen.
                    overlay = _render_middle_colored_text_image(
                        text, None, outer_fg, (20, 24, 32), mid_bg=HP_S2_MID_BG,
                    )
                    # Instant solid-bg stills; motion video attaches when ready.
                    png = _render_middle_colored_text_image(
                        text, HP_S2_BG, outer_fg, (20, 24, 32), mid_bg=HP_S2_MID_BG,
                    )
                    if not png:
                        continue
                    sid = _hw_screen_for_field(fid, (screen, screen))
                    if sid is not None:
                        images[sid] = png
                        if overlay:
                            overlay_images[sid] = overlay
                goal_sid = _hw_screen_for_field(fid, (odd_screen, odd_screen))
                if goal_sid is not None:
                    field_screens[fid] = [goal_sid]
                labels.append(f"{fid}:{same}/{odd}@{odd_screen}")
            if not field_screens or not images:
                continue
            # Unique seed every action → new flower spawn edges/locations.
            action_seed = (
                int(seed) * 1009
                + int(test_num) * 131
                + int(action_in_set) * 41
                + random.randint(1, 997)
            )
            start_frame = int(action_seed) % 180
            entry = {
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
                "arena_pair": (1, 1),
                "field_screens": field_screens,
                "screen_images": dict(images),
                "gap_screen_images": dict(images),
                "motion_theme": "flowers",
                "motion_seed": action_seed,
                "motion_base_rgb": tuple(HP_S2_BG),
                "motion_start_frame": start_frame,
                "overlay_images": dict(overlay_images),
                "motion_fill": True,
                "label": (
                    f"HighPerformance S2.T{series_num} T{test_num}/{ENTRY_TEST_COUNT} "
                    f"a{action_in_set}/{ENTRY_ACTIONS_PER_TEST} "
                    f"{' '.join(labels)} flowers on={on_ms}ms gap={gap_ms}ms"
                ),
                "path": (
                    f"image://HighPerformance/S2.T{series_num}/"
                    f"test{test_num}/{action_in_set}"
                ),
            }
            if motion_bg:
                entry["screen_video"] = motion_bg
                entry["motion_bg"] = motion_bg
            playlist.append(entry)
    return _stamp_finish_balls(playlist)


def _composite_overlay_on_bg(overlay_path: str, bg_path: str, text: str, seed: int) -> Optional[str]:
    """Paste transparent letter art onto a flower still (Pillow)."""
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        os.makedirs(MATH_EQ_CACHE_DIR, exist_ok=True)
        out = os.path.join(
            MATH_EQ_CACHE_DIR,
            f"hp_s2_comp_{seed}_{_safe_cache_token(text)}.png",
        )
        if os.path.isfile(out):
            return out
        base = Image.open(bg_path).convert("RGBA")
        over = Image.open(overlay_path).convert("RGBA")
        if over.size != base.size:
            over = over.resize(base.size, Image.BICUBIC)
        Image.alpha_composite(base, over).convert("RGB").save(out)
        return out
    except Exception:
        return None


def _build_high_performance_playlist(series_num: int, active_fields) -> List[dict]:
    return _stamp_finish_balls(_build_number_band_playlist(
        series_num,
        active_fields,
        _high_performance_test_layout,
        "HighPerformance",
    ))


def _build_omid_playlist(active_fields, directory=None) -> List[dict]:
    """Same scenario as SF-30N (pairs + On/Gap); pass is coded .ssav, not the mp4."""
    active = set(active_fields or [])
    if not active:
        return []
    pass_ssav = _find_pass_ssav(directory)
    if not pass_ssav:
        return []
    script = SF30N_SCRIPT
    n_tests = len(script)
    playlist = []
    for test_num in sorted(script.keys()):
        spec = script[test_num]
        on_ms = int(spec.get("on_ms") or SF_SCRIPTED_ON_MS)
        gap_ms = int(spec.get("gap_ms") or SF_SCRIPTED_GAP_MS)
        pairs = list(spec.get("pairs") or [])
        for action_in_set, pair in enumerate(pairs, start=1):
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
            screen_images = {sid: pass_ssav for sid in lit}
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
                "screen_ssav": pass_ssav,
                "arena_pair": (a_arena, b_arena),
                "parts": [{
                    "screens": list(lit),
                    "path": pass_ssav,
                    "field": next(iter(field_screens)),
                }],
                "field_screens": field_screens,
                "screen_images": screen_images,
                "label": (
                    f"omid T{test_num}/{n_tests} a{action_in_set}/{len(pairs)} "
                    f"arena_{a_arena}_{b_arena} hw_{'_'.join(str(s) for s in lit)} "
                    f"on={on_ms}ms gap={gap_ms}ms ssav"
                ),
                "path": f"image://omid/test{test_num}/{action_in_set}",
                "foundation_sf": "omid",
            })
    return _stamp_finish_balls(playlist)


def _build_omid_2_playlist(active_fields, directory=None) -> List[dict]:
    """Same scenario as omid/SF-30N; pass is coded .player (siamak_files), not .ssav."""
    active = set(active_fields or [])
    if not active:
        return []
    pass_player = _find_pass_player(directory)
    if not pass_player:
        return []
    script = SF30N_SCRIPT
    n_tests = len(script)
    playlist = []
    for test_num in sorted(script.keys()):
        spec = script[test_num]
        on_ms = int(spec.get("on_ms") or SF_SCRIPTED_ON_MS)
        gap_ms = int(spec.get("gap_ms") or SF_SCRIPTED_GAP_MS)
        pairs = list(spec.get("pairs") or [])
        for action_in_set, pair in enumerate(pairs, start=1):
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
            screen_images = {sid: pass_player for sid in lit}
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
                "screen_ssav": None,
                "screen_player": pass_player,
                "player_loop": True,
                "arena_pair": (a_arena, b_arena),
                "parts": [{
                    "screens": list(lit),
                    "path": pass_player,
                    "field": next(iter(field_screens)),
                }],
                "field_screens": field_screens,
                "screen_images": screen_images,
                "label": (
                    f"omid_2 T{test_num}/{n_tests} a{action_in_set}/{len(pairs)} "
                    f"arena_{a_arena}_{b_arena} hw_{'_'.join(str(s) for s in lit)} "
                    f"on={on_ms}ms gap={gap_ms}ms player"
                ),
                "path": f"image://omid_2/test{test_num}/{action_in_set}",
                "foundation_sf": "omid_2",
            })
    return _stamp_finish_balls(playlist)


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


def _elite_series_timing_ms(series_num: int, min_ms: Optional[int] = None) -> Tuple[int, int]:
    """S1.T1 is 4.5s. Each later set is 10% shorter. Gap stays 0.5s.

    Series 1 floors at 2.5s. Series 2 floors at 2.6s (pass ELITE_S2_ON_MIN_MS).
    """
    floor = float(ELITE_ON_MIN_MS if min_ms is None else min_ms)
    decay = ENTRY_TIMING_DECAY ** (max(1, int(series_num)) - 1)
    on = max(floor, float(ELITE_ON_START_MS) * decay)
    on_ms, _ = _snap_ms_to_display_fps(on)
    if on_ms < floor:
        on_ms, _ = _snap_ms_to_display_fps(floor)
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


def _world_action_bg(action_in_set: int) -> Tuple[int, int, int]:
    """Background for this World Class action (changes every action)."""
    palette = WORLD_ACTION_BG or tuple(ELITE_TEST_BG.values())
    return palette[(max(1, int(action_in_set)) - 1) % len(palette)]


def _world_digit_colors_for_action(
    bg, action_in_set: int, screen_ids: List[str]
) -> List[Tuple[int, int, int]]:
    """Fresh readable colors each action (rotated by screen index), not one fixed test set."""
    base = _world_digit_colors(bg)
    if not base or not screen_ids:
        return []
    all_ids = _elite_screen_ids()
    shift = (max(1, int(action_in_set)) - 1) % len(base)
    out = []
    for sid in screen_ids:
        try:
            index = all_ids.index(sid)
        except ValueError:
            index = 0
        out.append(base[(index + shift) % len(base)])
    return out


def _world_fg_on_bg(fg, bg, fallback) -> Tuple[int, int, int]:
    """Keep a finished digit color when it stays readable; otherwise use a fallback."""
    if fg and _colors_are_visible(fg, bg):
        return tuple(int(v) for v in fg[:3])
    for color in fallback or ():
        if _colors_are_visible(color, bg):
            return tuple(int(v) for v in color[:3])
    return (255, 255, 255)


def _build_elite_playlist(series_num: int, mode: str = "elite") -> List[dict]:
    """12 screens, one field. Lowest number is the pass, then that screen becomes 00.

    Elite: every number on a test shares one color, and 00 is always orange.
    World Class: background and remaining digit colors change every action; 00
    keeps its digit color when still readable on the new background.
    """
    world = str(mode) == "world-class"
    label_prefix = "WorldClass" if world else "Elite"
    on_ms, gap_ms = _elite_series_timing_ms(series_num)
    screens = _elite_screen_ids()
    playlist = []
    for test_num in range(1, ENTRY_TEST_COUNT + 1):
        placement, bg = _elite_test_layout(test_num, "world-class" if world else "elite")
        shared = ELITE_DIGIT_ON_BG[int(test_num)]
        if not world:
            if not _colors_are_visible(shared, bg) or not _colors_are_visible(ELITE_ZERO_COLOR, bg):
                logger.error("Elite colors are not readable on test %s", test_num)
                return []
        else:
            probe_bg = _world_action_bg(1)
            probe = _world_digit_colors(probe_bg)
            if len(probe) < len(screens):
                logger.error("World Class could not color every screen on test %s", test_num)
                return []
        order = _ordered_combined_goals(test_num, "world-class" if world else "elite")
        number_png = {}
        zero_png = {}
        if not world:
            for sid in screens:
                number_png[sid] = _render_band_digit_image(placement[sid], bg, shared)
                zero_png[sid] = _render_band_digit_image("00", bg, ELITE_ZERO_COLOR)
            if any(not number_png[sid] or not zero_png[sid] for sid in screens):
                return []
        last_fg = {}
        for action_in_set, goal_sid in enumerate(order, start=1):
            finished = set(order[:action_in_set - 1])
            remaining = [sid for sid in screens if sid not in finished]
            images = {}
            if world:
                action_bg = _world_action_bg(action_in_set)
                palette = _world_digit_colors(action_bg)
                if len(palette) < 1:
                    logger.error("World Class action bg unreadable on test %s a%s", test_num, action_in_set)
                    return []
                for sid in finished:
                    fg = _world_fg_on_bg(last_fg.get(sid), action_bg, palette)
                    pix = _render_band_digit_image("00", action_bg, fg)
                    if not pix:
                        return []
                    images[sid] = pix
                colors = _world_digit_colors_for_action(action_bg, action_in_set, remaining)
                if len(colors) < len(remaining):
                    logger.error("World Class action colors short on test %s a%s", test_num, action_in_set)
                    return []
                for index, sid in enumerate(remaining):
                    fg = colors[index]
                    last_fg[sid] = fg
                    pix = _render_band_digit_image(placement[sid], action_bg, fg)
                    if not pix:
                        return []
                    images[sid] = pix
            else:
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


def _combined_s2_goal_order(test_num: int) -> List[str]:
    """Tests 1–3 alternate A/B; tests 4–5 shuffle that alternating line."""
    base = _elite_alternating_screens()
    if int(test_num) >= 4:
        order = list(base)
        random.shuffle(order)
        return order
    return base


def _elite_s2_distractors_for_series(series_num: int) -> Tuple[str, ...]:
    """S2.T1–T2 levels: character symbols. S2.T3–T5 levels: similar geometric marks."""
    if int(series_num or 1) <= 2:
        return ELITE_S2_SYMBOLS
    return ELITE_S2_SHAPES


def _build_elite_s2_playlist(series_num: int) -> List[dict]:
    """Elite S2: 11 similar distractors + one number on 12 screens. Goal is the number.

    Level S2.T1–T2 use characters ($ % …). Level S2.T3–T5 use shapes (● ○ ◆ …)
    for every timed test in that set. Timed tests 4–5 randomize goal order.
    """
    on_ms, gap_ms = _elite_series_timing_ms(series_num, min_ms=ELITE_S2_ON_MIN_MS)
    bg = ELITE_S2_BG
    screens = _elite_screen_ids()
    distractors = _elite_s2_distractors_for_series(series_num)
    distractor_kind = "characters" if int(series_num or 1) <= 2 else "shapes"
    playlist = []
    for test_num in range(1, ENTRY_TEST_COUNT + 1):
        order = _combined_s2_goal_order(test_num)
        for action_in_set, goal_sid in enumerate(order, start=1):
            symbol = random.choice(distractors)
            number = str(random.randint(0, 9))
            images = {}
            for sid in screens:
                text = number if sid == goal_sid else symbol
                # Mix a second similar distractor so neighbors stay confusing.
                if sid != goal_sid and random.random() < 0.35:
                    text = random.choice(distractors)
                png = _render_band_digit_image(text, bg, (255, 255, 255))
                if not png:
                    # Unicode shapes can fail on some fonts — draw a fallback mark.
                    png = _render_elite_s2_shape_fallback(text, bg)
                if not png:
                    return []
                images[sid] = png
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
                "distractor_kind": distractor_kind,
                "label": (
                    f"Elite S2.T{series_num} T{test_num}/{ENTRY_TEST_COUNT} "
                    f"a{action_in_set}/{ELITE_ACTIONS_PER_TEST} "
                    f"goal {goal_sid} number {number} "
                    f"distractors={distractor_kind} on={on_ms}ms"
                ),
                "path": f"image://Elite/S2.T{series_num}/test{test_num}/{action_in_set}",
            })
    return _stamp_finish_balls(playlist)


def _render_elite_s2_shape_fallback(text: str, bg) -> Optional[str]:
    """Draw a simple geometric mark when Unicode shape glyphs cannot be painted."""
    raw = str(text or "").strip()
    if not raw or not bg:
        return None
    try:
        os.makedirs(MATH_EQ_CACHE_DIR, exist_ok=True)
    except Exception:
        return None
    path = os.path.join(
        MATH_EQ_CACHE_DIR,
        f"elite_s2_shape_{_safe_cache_token(raw)}_{int(bg[0])}_{int(bg[1])}_{int(bg[2])}.png",
    )
    if os.path.isfile(path):
        return path
    try:
        from PyQt5.QtGui import QImage, QPainter, QColor, QPen, QBrush, QPolygon
        from PyQt5.QtCore import Qt as QtCoreQt
    except Exception:
        return None
    w = h = 512
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor(int(bg[0]), int(bg[1]), int(bg[2]), 255))
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor(255, 255, 255), 8))
    painter.setBrush(QBrush(QColor(255, 255, 255)))
    cx, cy = w // 2, _ring_value_center_y(h)
    r = 70
    # Pick a drawn shape from the glyph family so missing fonts still look distinct.
    code = sum(ord(ch) for ch in raw) % 4
    if code == 0:
        painter.drawEllipse(cx - r, cy - r, 2 * r, 2 * r)
    elif code == 1:
        painter.setBrush(QtCoreQt.NoBrush)
        painter.drawEllipse(cx - r, cy - r, 2 * r, 2 * r)
    elif code == 2:
        painter.drawRect(cx - r, cy - r, 2 * r, 2 * r)
    else:
        pts = [
            QtCore.QPoint(cx, cy - r),
            QtCore.QPoint(cx + r, cy),
            QtCore.QPoint(cx, cy + r),
            QtCore.QPoint(cx - r, cy),
        ]
        painter.drawPolygon(QPolygon(pts))
    painter.end()
    if not img.save(path, "PNG"):
        return None
    return path


def _build_world_class_s2_playlist(series_num: int) -> List[dict]:
    """World Class S2: motion-camouflaged 2-digit numbers; one screen shows K2.

    Theme follows the level set (S2.T#), not the timed test inside the set:
    S2.T1 flowers, S2.T2 fruits, S2.T3 animals, S2.T4 space, S2.T5 orbs.
    Each action uses a different bounce start seed so sprites do not always
    begin from the same edge/location. Timing matches Elite S2.
    """
    on_ms, gap_ms = _elite_series_timing_ms(series_num, min_ms=ELITE_S2_ON_MIN_MS)
    screens = _elite_screen_ids()
    # Level S2.T# → one motion theme for the whole playlist.
    theme = _wc_s2_theme_for_series(series_num)
    base_seed = WORLD_S2_FLOWER_SEEDS[(int(series_num) - 1) % len(WORLD_S2_FLOWER_SEEDS)]
    # One shared clip per theme — schedule once; never encode per action.
    motion_bg = _ensure_wc_motion_bg_video(theme, int(base_seed))
    playlist = []
    for test_num in range(1, ENTRY_TEST_COUNT + 1):
        order = _combined_s2_goal_order(test_num)
        for action_in_set, goal_sid in enumerate(order, start=1):
            # Per-action seed → text color + video seek offset (not a new encode).
            action_seed = (
                int(base_seed) * 1009
                + int(series_num) * 131
                + int(test_num) * 57
                + int(action_in_set) * 41
                + random.randint(1, 997)
            )
            # Large step offset so sprites are mid-flight, not stuck on one edge.
            start_frame = int(action_seed) % 180
            images = {}
            motion_texts = {}
            motion_positions = {}
            for sid in screens:
                text = "K2" if sid == goal_sid else f"{random.randint(10, 99)}"
                motion_texts[sid] = text
                # Each number/K2 gets its own random place (not top/bottom 10%).
                motion_positions[sid] = _wc_text_anchor_frac(action_seed, f"{sid}:{text}")
                # Fast solid-theme stills so playlist build stays instant.
                png = _render_camouflage_text_image(
                    text,
                    seed=action_seed,
                    camouflage=True,
                    theme=theme,
                    phase=0.0,
                    fast=True,
                )
                if not png:
                    return []
                images[sid] = png
            fid = "B" if str(goal_sid).startswith("B") else "A"
            entry = {
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
                "motion_theme": theme,
                "motion_seed": action_seed,
                "motion_start_frame": start_frame,
                "motion_texts": dict(motion_texts),
                "motion_text_positions": dict(motion_positions),
                "motion_fill": True,
                "label": (
                    f"WorldClass S2.T{series_num} T{test_num}/{ENTRY_TEST_COUNT} "
                    f"a{action_in_set}/{ELITE_ACTIONS_PER_TEST} "
                    f"goal {goal_sid} K2 theme={theme} on={on_ms}ms"
                ),
                "path": (
                    f"image://WorldClass/S2.T{series_num}/"
                    f"test{test_num}/{action_in_set}"
                ),
            }
            if motion_bg:
                entry["screen_video"] = motion_bg
                entry["motion_bg"] = motion_bg
            playlist.append(entry)
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


def _compose_independent_entry(parts: dict, indices: dict, skip=None) -> Optional[dict]:
    """One live step. Each field keeps its own action; a finished field is left out."""
    skip = {str(fid).upper()[:1] for fid in (skip or set())}
    field_screens = {}
    screen_images = {}
    gap_screen_images = {}
    field_meta = {}
    on_ms = None
    gap_ms = None
    labels = []
    entry_digits = False
    budgets = []
    efficiencies = []
    for fid in ("A", "B"):
        if fid in skip:
            continue
        playlist = (parts or {}).get(fid) or []
        try:
            index = int((indices or {}).get(fid, 0))
        except (TypeError, ValueError):
            index = 0
        if index < 0 or index >= len(playlist) or not isinstance(playlist[index], dict):
            continue
        step = playlist[index]
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
        try:
            budget = int(step.get("budget_ms") or 0)
        except (TypeError, ValueError):
            budget = 0
        if budget > 0:
            budgets.append(budget)
        try:
            eff = float(step.get("efficiency_max_sec") or 0)
        except (TypeError, ValueError):
            eff = 0.0
        if eff > 0:
            efficiencies.append(eff)
        field_meta[fid] = {
            "test_num": int(step.get("test_num") or 1),
            "action_in_set": int(step.get("action_in_set") or (index + 1)),
            "actions_in_set": int(step.get("actions_in_set") or 1),
            "on_ms": step.get("on_ms"),
            "budget_ms": step.get("budget_ms"),
            "finish_balls": bool(step.get("finish_balls")),
            "index": index,
        }
    if not field_screens or not screen_images:
        return None
    primary = field_meta.get("A") or next(iter(field_meta.values()))
    return {
        "kind": "labeled_action",
        "index": 1,
        "test_num": primary.get("test_num") or 1,
        "action_in_set": primary.get("action_in_set") or 1,
        "actions_in_set": max(int(meta.get("actions_in_set") or 1) for meta in field_meta.values()),
        "is_last_in_set": False,
        "timing_scale": 1.0,
        "fixed_timing": on_ms is not None,
        "on_ms": on_ms,
        "gap_ms": gap_ms,
        "action_num": primary.get("action_in_set") or 1,
        "action": "PASS",
        "no_fillers": True,
        "entry_digits": entry_digits,
        "independent_fields": True,
        "field_meta": field_meta,
        "field_screens": field_screens,
        "screen_images": screen_images,
        "gap_screen_images": gap_screen_images or None,
        "advance_on_goal": True,
        "skip_gap": True,
        "finish_balls": any(bool(meta.get("finish_balls")) for meta in field_meta.values()),
        "budget_ms": max(budgets) if budgets else None,
        "efficiency_max_sec": max(efficiencies) if efficiencies else None,
        "label": " | ".join(labels) if labels else "independent fields",
        "path": "image://independent/live",
    }


def _result_video_index(test_num, file_index=1) -> int:
    """Each field's own test number. A shared file cannot name two tests at once."""
    try:
        number = int(test_num)
    except (TypeError, ValueError):
        number = 0
    if number >= 1:
        return number
    try:
        fallback = int(file_index)
    except (TypeError, ValueError):
        fallback = 1
    return fallback if fallback >= 1 else 1


def _zip_field_action_playlists(parts: dict) -> List[dict]:
    """One live step. Each field advances on its own action count."""
    indices = {fid: 0 for fid in ("A", "B") if (parts or {}).get(fid)}
    entry = _compose_independent_entry(parts, indices)
    return [entry] if entry else []


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


def _images_for_fields(entry, field_ids) -> dict:
    """Pictures for these fields only, from the live step."""
    wanted = {str(fid).upper()[:1] for fid in (field_ids or set())}
    images = {}
    for sid, path in ((entry or {}).get("screen_images") or {}).items():
        name = _sid(sid) or str(sid)
        if path and _field_for_screen(name) in wanted:
            images[name] = path
    return images


def _without_field_screens(existing, replace_fields) -> dict:
    """Drop one field's old pictures. The other field's screens stay."""
    replace = {str(fid).upper()[:1] for fid in (replace_fields or set())}
    kept = {}
    for name, pix in (existing or {}).items():
        if _field_for_screen(name) in replace:
            continue
        kept[name] = pix
    return kept


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


def _series_set_label(level_id: str, subdirectory: str = "") -> Optional[str]:
    """S1.T# = series group 1 set #; S2.T# = series group 2 (Activated second block)."""
    text = f"{level_id or ''} {subdirectory or ''}"
    s2 = re.search(r"S2[.-]T([1-5])|A1[-.]T([1-5])", text, re.I)
    if s2:
        return f"S2.T{s2.group(1) or s2.group(2)}"
    s1 = re.search(r"S1[.-]T([1-5])|(?<!\d)A[-.]T([1-5])", text, re.I)
    if s1:
        return f"S1.T{s1.group(1) or s1.group(2)}"
    return None


def _level_display_parts(level_id: str, subdirectory: str = "") -> Tuple[str, Optional[str]]:
    """Band name and optional S1.T / SF line for the opening card."""
    text = f"{level_id or ''} {subdirectory or ''}"
    series_label = _series_set_label(level_id, subdirectory)
    sf = re.search(r"SF-\d+N", text, re.I)

    if re.search(r"L05-WorldClass|World[-_ ]?Class", text, re.I):
        return "World Class", series_label
    if re.search(r"L04-Elite", text, re.I):
        return "Elite", series_label
    if re.search(r"L03-HighPerformance|High[-_ ]?Performance", text, re.I):
        return "High Performance", series_label
    if re.search(r"L02-Activated", text, re.I):
        return "Activated", series_label
    if re.search(r"L01-Entry", text, re.I):
        return "Entry", series_label
    if sf:
        return sf.group(0).upper(), None
    if re.search(r"Foundation", text, re.I):
        return "Foundation", None
    tail = str(level_id or "Test").split("/")[-1] or "Test"
    if series_label and re.match(r"^S[12]\.T[1-5]$", tail, re.I):
        return "Test", series_label
    return tail, series_label


def _level_display_name(level_id: str, subdirectory: str = "") -> str:
    """Short name shown before the intro video."""
    name, series = _level_display_parts(level_id, subdirectory)
    if series:
        return f"{name} {series}"
    return name


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
            "logo": _opening_logo_video_for_level(level_id, sub),
        }
    return cards


def _level_card_text(level_id: str, subdirectory: str, entry: dict, playlist: list) -> str:
    """One fact per line for the opening card.

    Series levels (Entry → World Class) match Activated: S1.T# / S2.T# and
    the action count only. Foundation keeps playlist name, clock, and actions.
    """
    name, series = _level_display_parts(level_id, subdirectory)
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
    set_label = series or _series_set_label(level_id, subdirectory)
    if set_label:
        lines = [set_label]
        if actions > 0:
            lines.append(f"{actions} Actions")
        return "\n".join(lines)
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


# Brand fills as CURRENT DEVELOPMENT LEVEL on the My SIMUST player page.
_LEVEL_BRAND_RGB = {
    "foundation": (125, 255, 168),
    "entry": (241, 243, 245),
    "activated": (175, 195, 213),
    "high-performance": (49, 95, 145),
    "elite": (75, 31, 120),
    "world-class": (201, 162, 39),
}
# Legacy pair kept for any caller that still expects (bg, fg) page fills.
_LEVEL_PAGE_BG = {
    "foundation": ((125, 255, 168), (12, 28, 18)),
    "entry": ((241, 243, 245), (40, 44, 48)),
    "activated": ((175, 195, 213), (12, 22, 36)),
    "high-performance": ((49, 95, 145), (255, 255, 255)),
    "elite": ((75, 31, 120), (255, 255, 255)),
    "world-class": ((201, 162, 39), (28, 20, 4)),
}


def _level_brand_key(level_id: str, subdirectory: str = "", entry: dict = None) -> str:
    text = f"{level_id or ''} {subdirectory or ''}"
    if isinstance(entry, dict):
        text = f"{text} {entry.get('label') or ''} {entry.get('path') or ''}"
    if re.search(r"L05-WorldClass|World[-_ ]?Class", text, re.I):
        return "world-class"
    if re.search(r"L04-Elite", text, re.I):
        return "elite"
    if re.search(r"L03-HighPerformance|High[-_ ]?Performance", text, re.I):
        return "high-performance"
    if re.search(r"L02-Activated", text, re.I):
        return "activated"
    if re.search(r"L01-Entry", text, re.I):
        return "entry"
    if re.search(r"Foundation|SF-\d+N", text, re.I):
        return "foundation"
    return "foundation"


def _level_card_colors(level_id: str, subdirectory: str, entry: dict):
    """Opening information card: level color, with text dark or light enough to read."""
    key = _level_brand_key(level_id, subdirectory, entry)
    pair = _LEVEL_PAGE_BG.get(key) or _LEVEL_PAGE_BG["foundation"]
    return tuple(pair[0]), tuple(pair[1])


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


def _screen_saver_video_path() -> Optional[str]:
    """Muted looping idle clip — same folder as beginning logo videos."""
    path = os.path.join(LEVEL_INTRO_STATIC_DIR, SCREEN_SAVER_VIDEO)
    return path if os.path.isfile(path) else None


def _cabinet_controls_path(directory: str = None) -> str:
    root = directory or "C:/Users/siama/Documents/simust_player"
    return os.path.join(root, CABINET_CONTROLS_FILE)


def _read_cabinet_controls(directory: str = None) -> dict:
    """Operator System / Screensaver switches written by the frontend."""
    path = _cabinet_controls_path(directory)
    defaults = {"system_on": True, "screensaver_on": False}
    if not os.path.isfile(path):
        return dict(defaults)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return dict(defaults)
        return {
            "system_on": bool(data.get("system_on", True)),
            "screensaver_on": bool(data.get("screensaver_on", False)),
        }
    except Exception:
        return dict(defaults)


def _opening_logo_video_for_level(level_id: str = "", subdirectory: str = "") -> Optional[str]:
    """Small logo clip shown above beginning information for that band."""
    text = f"{level_id or ''} {subdirectory or ''}".strip()
    key = _level_intro_key_from_id(text) if text else None
    if not key:
        for pat, mapped in _LEVEL_INTRO_PATH_RULES:
            if pat.search(text):
                key = mapped
                break
    if not key:
        return None
    for name in LEVEL_OPENING_LOGO_FILES.get(key) or ():
        hit = os.path.join(LEVEL_INTRO_STATIC_DIR, name)
        if os.path.isfile(hit):
            return hit
    return None


def _activated_logo_video() -> Optional[str]:
    """Backward-compatible alias for the Activated opening logo."""
    return _opening_logo_video_for_level("L02-Activated")


def _find_level_intro_video(directory: str = None) -> Optional[str]:
    """Return absolute path to static/<level>.mp4 for the current level."""
    return _intro_video_for_key(_detect_level_intro_key(directory))


def _video_duration_ms(path: str, fallback_ms: int = LEVEL_INTRO_MS) -> int:
    """Length of an mp4 in milliseconds. Falls back when OpenCV cannot probe it."""
    path = str(path or "")
    try:
        fallback = max(500, int(fallback_ms or LEVEL_INTRO_MS))
    except (TypeError, ValueError):
        fallback = LEVEL_INTRO_MS
    if not path or not os.path.isfile(path):
        return fallback
    try:
        import cv2
    except Exception:
        return fallback
    cap = None
    try:
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            return fallback
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0) or 25.0
        frames = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if frames > 0 and fps > 0:
            return max(500, int(round(1000.0 * frames / fps)))
        msec = float(cap.get(cv2.CAP_PROP_POS_MSEC) or 0)
        if msec > 0:
            return max(500, int(round(msec)))
    except Exception:
        return fallback
    finally:
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
    return fallback


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
            os.path.join(root, "omid"),
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


def _find_pass_ssav(directory) -> Optional[str]:
    """Coded pass clip (.ssav). Prefer local pack; convert pass.mp4 once if needed."""
    if not directory:
        return None
    direct = os.path.join(directory, "pass_pixels.ssav")
    if os.path.isfile(direct):
        return direct
    try:
        from screen_saver_anim import ensure_pass_ssav
    except ImportError:
        ensure_pass_ssav = None
    if ensure_pass_ssav:
        hit = ensure_pass_ssav(directory)
        if hit and os.path.isfile(hit):
            return hit
    video = _find_pass_video(directory)
    if video and ensure_pass_ssav:
        hit = ensure_pass_ssav(video)
        if hit and os.path.isfile(hit):
            return hit
    if video:
        sibling = os.path.join(os.path.dirname(video), "pass_pixels.ssav")
        if os.path.isfile(sibling):
            return sibling
    return None


def _find_pass_player(directory) -> Optional[str]:
    """Coded pass animation (.player from siamak_files). Prefer local omid_2 pack."""
    names = (
        "teammate_asking.player",
        "pass_pixels.player",
        "pass.player",
    )
    candidates = []
    if directory:
        for name in names:
            candidates.append(os.path.join(directory, name))
        root = _foundation_challenge_root(directory)
        if root:
            for name in names:
                candidates.append(os.path.join(root, "omid_2", name))
                candidates.append(os.path.join(root, "files", name))
    here = os.path.dirname(os.path.abspath(__file__))
    for name in names:
        candidates.append(os.path.join(here, "static", "players", name))
        candidates.append(os.path.join(here, "static", "siamak_files", name))
    seen = set()
    for path in candidates:
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        if os.path.isfile(path):
            return path
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
    # SF-30N…180N keep the previous still-image pass (png/jpg/jpeg).
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
                # Mid-action awareness flash on the upcoming screen (display only).
                "next_screen_hint": True,
            })
    return _stamp_finish_balls(playlist)


def _next_sf_hint_targets(playlist, index, active_fields=None):
    """Next same-test SF action's lit screens (and arena digit), or empty.

    Used for the 1s awareness flash on the upcoming pass destination. Does not
    change when the pass image itself moves.
    """
    if not playlist or index is None:
        return {}, None
    try:
        cur_i = int(index)
    except (TypeError, ValueError):
        return {}, None
    if cur_i < 0 or cur_i >= len(playlist):
        return {}, None
    cur = playlist[cur_i]
    if not isinstance(cur, dict) or not cur.get("next_screen_hint"):
        return {}, None
    nxt_i = cur_i + 1
    if nxt_i >= len(playlist):
        return {}, None
    nxt = playlist[nxt_i]
    if not isinstance(nxt, dict) or nxt.get("kind") != "labeled_action":
        return {}, None
    try:
        if int(nxt.get("test_num") or -1) != int(cur.get("test_num") or -2):
            return {}, None
    except (TypeError, ValueError):
        return {}, None
    active = {
        str(f).upper()[:1]
        for f in (active_fields if active_fields is not None else ("A", "B"))
        if str(f).upper()[:1] in ("A", "B")
    }
    cur_lit = set()
    for sids in (cur.get("field_screens") or {}).values():
        cur_lit.update(_named_screens(sids or []))
    field_screens = {}
    for fid, sids in (nxt.get("field_screens") or {}).items():
        key = str(fid).upper()[:1]
        if key not in active:
            continue
        names = [s for s in _named_screens(sids or []) if s not in cur_lit]
        if names:
            field_screens[key] = names
    if not field_screens:
        return {}, None
    arena = None
    pair = nxt.get("arena_pair")
    if isinstance(pair, (list, tuple)) and pair:
        try:
            arena = int(pair[0])
        except (TypeError, ValueError):
            arena = None
    if arena is None:
        for sids in field_screens.values():
            for sid in sids:
                digits = "".join(ch for ch in str(sid) if ch.isdigit())
                if digits:
                    try:
                        arena = int(digits)
                    except ValueError:
                        arena = None
                    break
            if arena is not None:
                break
    return field_screens, arena


def _sf_next_hint_glyph(arena) -> str:
    """Random digit or letter for the next-screen awareness flash."""
    if random.random() < 0.5:
        try:
            number = int(arena)
            if 1 <= number <= 6:
                return str(number)
        except (TypeError, ValueError):
            pass
        return str(random.randint(1, 9))
    return random.choice(SF_NEXT_HINT_LETTERS)


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


def _result_ring_specs(panel) -> dict:
    """Screen name → ring label, center lines, and fill percent. No video."""
    if not isinstance(panel, dict):
        return {}
    specs = {}

    def add(screen, label, lines, percent):
        name = str(screen or "").strip()
        if not name:
            return
        shown = []
        for line in lines:
            text = str(line or "").strip()
            if not text or text == "-":
                continue
            shown.append(text)
        if not shown:
            shown = ["-"]
        try:
            value = float(percent or 0)
        except (TypeError, ValueError):
            value = 0.0
        specs[name] = {
            "label": label,
            "lines": shown[:2],
            "percent": max(0.0, min(100.0, value)),
        }

    add(
        panel.get("slice_aet"),
        "Execution Time",
        [panel.get("aet_display") or "-", panel.get("aet_session_display") or ""],
        panel.get("aet_percent"),
    )
    raw_aac = panel.get("aac")
    accuracy = None
    if raw_aac is not None:
        try:
            accuracy = float(raw_aac)
        except (TypeError, ValueError):
            accuracy = None
    if accuracy is None or accuracy <= 0:
        try:
            total_n = int(panel.get("total_actions") or 0)
            hit_n = int(panel.get("correct") or 0) + int(panel.get("late") or 0)
        except (TypeError, ValueError):
            total_n = hit_n = 0
        if total_n > 0 and hit_n > 0:
            accuracy = (hit_n / total_n) * 100.0
    if accuracy is None:
        add(panel.get("slice_acc"), "Accuracy", ["-"], 0.0)
    else:
        add(
            panel.get("slice_acc"),
            "Accuracy",
            [f"{accuracy:.0f}%"],
            accuracy,
        )
    add(
        panel.get("slice_ae"),
        "Efficiency",
        [panel.get("ae_display") or "-"],
        panel.get("avg_ae"),
    )
    try:
        metres = int(panel.get("distance_shown") or 0)
    except (TypeError, ValueError):
        metres = 0
    add(
        panel.get("slice_disp"),
        "Displacement",
        [f"{metres}m" if metres > 0 else "-"],
        panel.get("economy_percent"),
    )
    return specs


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


def _wc_text_anchor_frac(seed: int, key: str = "") -> Tuple[float, float]:
    """Random normalized (x, y) text center; y stays out of the top/bottom 10%."""
    token = str(key or "")
    rng = random.Random(int(seed) * 10007 + sum((i + 1) * ord(c) for i, c in enumerate(token)))
    margin = float(WC_TEXT_EDGE_MARGIN)
    # Slight side inset so wide glyphs (K2 / 2-digit) stay inside the tile.
    fx = rng.uniform(0.14, 0.86)
    fy = rng.uniform(margin, 1.0 - margin)
    return float(fx), float(fy)


def _draw_text_at_frac(painter, text, width, height, fx: float, fy: float):
    """Draw text centered on a normalized point inside the image."""
    cx = int(round(float(fx) * float(width)))
    cy = int(round(float(fy) * float(height)))
    painter.drawText(
        QtCore.QRect(cx - int(width), cy - int(height), int(width) * 2, int(height) * 2),
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
        f"digitring_fg_{fr}_{fg_c}_{fb}_bg_{br}_{bgc}_{bb}_{_safe_cache_token(text)}.png",
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


def _render_middle_colored_text_image(
    text: str, bg, outer_fg, mid_fg, mid_bg=None,
) -> Optional[str]:
    """Three-character text with a distinct fill behind the middle glyph only."""
    raw = str(text or "").strip()
    if len(raw) != 3 or not outer_fg:
        return None
    try:
        os.makedirs(MATH_EQ_CACHE_DIR, exist_ok=True)
    except Exception:
        return None
    transparent = bg is None
    if transparent:
        br = bgc = bb = -1
    else:
        br, bgc, bb = (int(bg[0]), int(bg[1]), int(bg[2]))
    or_, og, ob = (int(outer_fg[0]), int(outer_fg[1]), int(outer_fg[2]))
    if mid_bg is None and mid_fg:
        # Older callers passed a mid text color; treat it as the mid patch color.
        mid_bg = mid_fg
        mid_fg = (20, 24, 32)
    if mid_bg is None:
        mid_bg = (255, 196, 64)
    if not mid_fg:
        mid_fg = (20, 24, 32)
    mr, mg, mb = (int(mid_fg[0]), int(mid_fg[1]), int(mid_fg[2]))
    bgr, bgg, bgb = (int(mid_bg[0]), int(mid_bg[1]), int(mid_bg[2]))
    path = os.path.join(
        MATH_EQ_CACHE_DIR,
        f"midbg_{br}_{bgc}_{bb}_{or_}_{og}_{ob}_{mr}_{mg}_{mb}_{bgr}_{bgg}_{bgb}_{raw}.png",
    )
    if os.path.isfile(path):
        return path
    try:
        from PyQt5.QtGui import QImage, QPainter, QColor, QFont, QBrush
        from PyQt5.QtCore import Qt as QtCoreQt
    except Exception as exc:
        logger.warning("Cannot render middle-colored text (no Qt): %s", exc)
        return None
    w, h = 512, 512
    img = QImage(w, h, QImage.Format_ARGB32)
    if transparent:
        img.fill(QColor(0, 0, 0, 0))
    else:
        img.fill(QColor(br, bgc, bb, 255))
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    # Same point size as entry digits so letter triples match digit screens.
    font = QFont("Segoe UI", 50, QFont.Bold)
    painter.setFont(font)
    metrics = painter.fontMetrics()
    widths = [metrics.width(ch) for ch in raw]
    total_w = sum(widths)
    x = (w - total_w) // 2
    cy = _ring_value_center_y(h)
    # Patch behind the middle letter only.
    mid_x = x + widths[0]
    mid_w = max(1, widths[1])
    pad_x = max(8, mid_w // 5)
    pad_y = max(10, metrics.height() // 5)
    patch = QtCore.QRect(
        mid_x - pad_x,
        cy - metrics.ascent() // 2 - pad_y,
        mid_w + 2 * pad_x,
        metrics.height() + 2 * pad_y,
    )
    painter.setPen(QtCoreQt.NoPen)
    painter.setBrush(QBrush(QColor(bgr, bgg, bgb, 255)))
    painter.drawRoundedRect(patch, 12, 12)
    for index, ch in enumerate(raw):
        color = (mr, mg, mb) if index == 1 else (or_, og, ob)
        painter.setPen(QColor(color[0], color[1], color[2]))
        ch_w = widths[index]
        painter.drawText(
            QtCore.QRect(x, cy - h, ch_w, h * 2),
            QtCoreQt.AlignCenter,
            ch,
        )
        x += ch_w
    painter.end()
    if not img.save(path, "PNG"):
        return None
    return path


def _wc_s2_theme_for_series(series_num: int) -> str:
    """Level S2.T1 flowers; S2.T2 fruits; S2.T3 animals; S2.T4 space; S2.T5 orbs."""
    index = max(1, int(series_num or 1)) - 1
    return WORLD_S2_THEMES[index % len(WORLD_S2_THEMES)]


def _wc_s2_theme_for_test(test_num: int) -> str:
    """Backward-compatible alias — prefer _wc_s2_theme_for_series(series_num)."""
    return _wc_s2_theme_for_series(test_num)


def _wc_s2_base_rgb(theme: str, seed: int) -> Tuple[int, int, int]:
    theme = str(theme or "flowers").lower()
    if theme == "fruits":
        return (
            90 + (seed * 13) % 50,
            55 + (seed * 7) % 40,
            40 + (seed * 5) % 30,
        )
    if theme == "animals":
        return (
            70 + (seed * 9) % 40,
            95 + (seed * 13) % 45,
            55 + (seed * 7) % 35,
        )
    if theme == "space":
        return (
            8 + (seed * 5) % 20,
            10 + (seed * 7) % 25,
            40 + (seed * 11) % 50,
        )
    if theme in ("shapes", "leaves"):
        return (
            45 + (seed * 11) % 40,
            55 + (seed * 9) % 45,
            95 + (seed * 17) % 55,
        )
    if theme == "orbs":
        return (
            55 + (seed * 15) % 45,
            40 + (seed * 11) % 40,
            85 + (seed * 19) % 50,
        )
    return (
        55 + (seed * 17) % 45,
        95 + (seed * 11) % 50,
        60 + (seed * 7) % 40,
    )


def _wc_s2_text_rgb(theme: str, seed: int) -> Tuple[int, int, int]:
    """Cream blended toward the theme base — severity 1.4 over the mild v2 look."""
    cream = (245, 240, 220)
    base = _wc_s2_base_rgb(theme, seed)
    # Mild was ~0.0 blend; +40% camouflage → pull 40% toward the background.
    blend = max(0.0, min(0.85, 0.40 * float(WORLD_S2_CAMO_SEVERITY) / 1.4))
    return tuple(
        int(round(cream[i] * (1.0 - blend) + base[i] * blend))
        for i in range(3)
    )


def _pil_realistic_flower_rgba(size: int, petal_rgb, seed: int = 1):
    """Paint a soft photographic flower with Pillow (gradient petals + glowing center)."""
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except Exception:
        return None
    size = max(24, int(size))
    rng = random.Random(int(seed) * 13 + size)
    side = size * 2
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    cx = cy = size
    petals = 5 + (int(seed) % 3)
    pr, pg, pb = [max(0, min(255, int(v))) for v in petal_rgb[:3]]
    petal_w = int(size * rng.uniform(0.55, 0.7))
    petal_h = int(size * rng.uniform(0.95, 1.15))
    for p in range(petals):
        ang = (360.0 / petals) * p + rng.uniform(-6, 6)
        petal = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        draw = ImageDraw.Draw(petal, "RGBA")
        for layer, fade in ((0, 70), (1, 130), (2, 200)):
            shrink = 1.0 - layer * 0.14
            pw = petal_w * shrink
            ph = petal_h * shrink
            box = [cx - pw / 2, cy - ph, cx + pw / 2, cy - size * 0.05]
            shade = (
                max(0, min(255, pr - 16 * layer + rng.randint(-10, 10))),
                max(0, min(255, pg - 12 * layer + rng.randint(-10, 10))),
                max(0, min(255, pb - 10 * layer + rng.randint(-10, 10))),
                fade,
            )
            draw.ellipse(box, fill=shade)
        petal = petal.rotate(ang, resample=Image.BICUBIC, center=(cx, cy))
        canvas = Image.alpha_composite(canvas, petal)
    draw = ImageDraw.Draw(canvas, "RGBA")
    core = max(4, int(size * 0.24))
    draw.ellipse([cx - core, cy - core, cx + core, cy + core], fill=(255, 215, 60, 240))
    draw.ellipse(
        [cx - core * 0.5, cy - core * 0.5, cx + core * 0.35, cy + core * 0.35],
        fill=(255, 255, 220, 210),
    )
    # Tiny stigma dots.
    for _ in range(6):
        dx = rng.randint(-core // 2, core // 2)
        dy = rng.randint(-core // 2, core // 2)
        draw.ellipse(
            [cx + dx - 1, cy + dy - 1, cx + dx + 1, cy + dy + 1],
            fill=(160, 90, 20, 220),
        )
    return canvas.filter(ImageFilter.GaussianBlur(radius=max(0.6, size * 0.025)))


def _pil_theme_sprite_rgba(kind: str, size: int, rgb, seed: int = 1):
    """Pillow sprite for flowers / fruits / animals / space / orbs."""
    kind = str(kind or "flowers").lower()
    if kind == "flowers":
        return _pil_realistic_flower_rgba(size, rgb, seed)
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except Exception:
        return None
    size = max(22, int(size))
    rng = random.Random(int(seed) * 19 + size)
    side = size * 2
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas, "RGBA")
    cx = cy = size
    r, g, b = [max(0, min(255, int(v))) for v in (rgb or (200, 100, 100))[:3]]
    if kind == "fruits":
        body = max(10, int(size * 0.85))
        draw.ellipse([cx - body, cy - body, cx + body, cy + body], fill=(r, g, b, 230))
        draw.ellipse(
            [cx - body * 0.45, cy - body * 0.55, cx - body * 0.05, cy - body * 0.15],
            fill=(255, 255, 255, 110),
        )
        draw.ellipse(
            [cx - 3, cy - body - 8, cx + 5, cy - body + 4],
            fill=(50, 140, 60, 230),
        )
        draw.polygon(
            [(cx + 2, cy - body - 2), (cx + 18, cy - body - 10), (cx + 10, cy - body + 8)],
            fill=(40, 130, 55, 220),
        )
    elif kind == "animals":
        body = max(12, int(size * 0.7))
        draw.ellipse([cx - body, cy - body * 0.7, cx + body, cy + body], fill=(r, g, b, 230))
        ear = max(6, body // 3)
        draw.ellipse([cx - body, cy - body - ear // 2, cx - body + ear * 2, cy - body + ear], fill=(r, g, b, 230))
        draw.ellipse([cx + body - ear * 2, cy - body - ear // 2, cx + body, cy - body + ear], fill=(r, g, b, 230))
        eye = max(2, body // 6)
        draw.ellipse([cx - body // 3 - eye, cy - eye, cx - body // 3 + eye, cy + eye], fill=(20, 20, 20, 240))
        draw.ellipse([cx + body // 3 - eye, cy - eye, cx + body // 3 + eye, cy + eye], fill=(20, 20, 20, 240))
        draw.ellipse([cx - 4, cy + body // 4, cx + 4, cy + body // 4 + 6], fill=(40, 30, 30, 220))
    elif kind == "space":
        # Planet + ring + stars.
        body = max(10, int(size * 0.55))
        draw.ellipse([cx - body, cy - body, cx + body, cy + body], fill=(r, g, b, 230))
        draw.ellipse(
            [cx - body * 1.4, cy - 4, cx + body * 1.4, cy + 4],
            outline=(220, 220, 255, 200),
            width=max(2, body // 8),
        )
        for _ in range(8):
            sx = rng.randint(4, side - 4)
            sy = rng.randint(4, side - 4)
            if abs(sx - cx) < body and abs(sy - cy) < body:
                continue
            s = rng.randint(1, 3)
            draw.ellipse([sx - s, sy - s, sx + s, sy + s], fill=(255, 255, 240, 220))
    else:
        # Soft glowing orb.
        body = max(10, int(size * 0.8))
        draw.ellipse([cx - body, cy - body, cx + body, cy + body], fill=(r, g, b, 160))
        draw.ellipse(
            [cx - body // 2, cy - body // 2, cx + body // 3, cy + body // 3],
            fill=(255, 255, 255, 90),
        )
    return canvas.filter(ImageFilter.GaussianBlur(radius=max(0.5, size * 0.02)))


def _theme_bounce_palettes(kind: str):
    kind = str(kind or "flowers").lower()
    if kind == "fruits":
        return [
            (220, 50, 50), (255, 140, 40), (255, 210, 60),
            (180, 40, 160), (255, 90, 90), (120, 200, 70),
        ]
    if kind == "animals":
        return [
            (210, 160, 110), (120, 90, 70), (240, 200, 160),
            (90, 90, 95), (200, 120, 80), (160, 130, 100),
        ]
    if kind == "space":
        return [
            (120, 160, 255), (255, 180, 90), (180, 120, 255),
            (100, 220, 200), (255, 120, 160), (200, 200, 255),
        ]
    if kind == "orbs":
        return [
            (120, 180, 255), (200, 120, 255), (100, 220, 200),
            (255, 140, 180), (160, 200, 255), (220, 180, 255),
        ]
    return [
        (220, 70, 110), (255, 140, 60), (255, 90, 160),
        (180, 80, 220), (255, 200, 70), (120, 180, 255), (255, 110, 90),
    ]


def _flower_bounce_fleet(seed: int, width: int, height: int, count: int = None, kind: str = "flowers"):
    """Initial bouncing particles; seed changes start locations every action."""
    rng = random.Random(int(seed) * 91 + 7)
    n = int(count or FLOWER_BOUNCE_COUNT)
    fleet = []
    palettes = _theme_bounce_palettes(kind)
    # Prefer starts near different edges so motion does not always begin center-left.
    edges = ("left", "right", "top", "bottom")
    for i in range(n):
        radius = rng.randint(26, 50)
        speed = rng.uniform(2.4, 5.2)
        edge = edges[(i + int(seed)) % 4]
        if edge == "left":
            x = float(radius + rng.randint(0, 8))
            y = float(rng.randint(radius, max(radius + 1, height - radius)))
            angle = rng.uniform(-0.6, 0.6)
        elif edge == "right":
            x = float(width - radius - rng.randint(0, 8))
            y = float(rng.randint(radius, max(radius + 1, height - radius)))
            angle = math.pi + rng.uniform(-0.6, 0.6)
        elif edge == "top":
            x = float(rng.randint(radius, max(radius + 1, width - radius)))
            y = float(radius + rng.randint(0, 8))
            angle = math.pi / 2 + rng.uniform(-0.6, 0.6)
        else:
            x = float(rng.randint(radius, max(radius + 1, width - radius)))
            y = float(height - radius - rng.randint(0, 8))
            angle = -math.pi / 2 + rng.uniform(-0.6, 0.6)
        fleet.append({
            "x": x,
            "y": y,
            "vx": math.cos(angle) * speed,
            "vy": math.sin(angle) * speed,
            "r": radius,
            "rgb": palettes[i % len(palettes)],
            "spin": rng.uniform(0, 360),
            "spin_v": rng.uniform(-3.5, 3.5),
            "seed": int(seed) * 17 + i * 31,
            "kind": str(kind or "flowers"),
        })
    return fleet


def _advance_flower_bounce(fleet, width: int, height: int):
    """Move sprites and bounce (debounce) when they hit a screen edge."""
    for flower in fleet or []:
        r = float(flower["r"])
        flower["x"] += float(flower["vx"])
        flower["y"] += float(flower["vy"])
        flower["spin"] = (float(flower["spin"]) + float(flower["spin_v"])) % 360.0
        if flower["x"] <= r:
            flower["x"] = r
            flower["vx"] = abs(float(flower["vx"]))
            flower["spin_v"] = -float(flower["spin_v"])
        elif flower["x"] >= width - r:
            flower["x"] = width - r
            flower["vx"] = -abs(float(flower["vx"]))
            flower["spin_v"] = -float(flower["spin_v"])
        if flower["y"] <= r:
            flower["y"] = r
            flower["vy"] = abs(float(flower["vy"]))
            flower["spin_v"] = -float(flower["spin_v"])
        elif flower["y"] >= height - r:
            flower["y"] = height - r
            flower["vy"] = -abs(float(flower["vy"]))
            flower["spin_v"] = -float(flower["spin_v"])


def _compose_bouncing_flowers_rgb(
    width: int,
    height: int,
    seed: int,
    frame_i: int = 0,
    base_rgb=None,
    fleet=None,
    kind: str = "flowers",
):
    """NumPy/Pillow frame: theme sprites bouncing edge-to-edge.

    Pass an existing fleet to advance one step without replaying from frame 0.
    Different seeds place sprites at different starting edges/locations.
    """
    try:
        from PIL import Image
        import numpy as np
    except Exception:
        return None, fleet
    theme = str(kind or "flowers").lower()
    base = tuple(base_rgb or _wc_s2_base_rgb(theme, seed))
    canvas = Image.new("RGB", (width, height), base)
    if fleet is None:
        fleet = _flower_bounce_fleet(seed, width, height, kind=theme)
        for _ in range(max(0, int(frame_i))):
            _advance_flower_bounce(fleet, width, height)
    else:
        _advance_flower_bounce(fleet, width, height)
    for flower in fleet:
        sprite = _pil_theme_sprite_rgba(
            flower.get("kind") or theme,
            int(flower["r"]),
            flower["rgb"],
            flower["seed"],
        )
        if sprite is None:
            continue
        rotated = sprite.rotate(float(flower["spin"]), resample=Image.BICUBIC, expand=True)
        px = int(flower["x"] - rotated.size[0] / 2)
        py = int(flower["y"] - rotated.size[1] / 2)
        canvas.paste(rotated, (px, py), rotated)
    return np.asarray(canvas.convert("RGB"), dtype=np.uint8), fleet


def _paint_flower_camouflage(painter, width: int, height: int, seed: int, phase: float = 0.0):
    """Animated flower field (legacy name kept for callers)."""
    _paint_wc_motion_theme(painter, width, height, "flowers", seed, phase)


def _qimage_from_rgb_array(arr):
    """Wrap an HxWx3 uint8 RGB array as a QImage (copied)."""
    try:
        import numpy as np
        from PyQt5.QtGui import QImage
    except Exception:
        return None
    if arr is None:
        return None
    rgb = np.ascontiguousarray(arr, dtype=np.uint8)
    h, w, _ = rgb.shape
    image = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
    return image


def _paint_wc_motion_theme(
    painter, width: int, height: int, theme: str, seed: int, phase: float = 0.0
):
    """Motion graphics: bouncing Pillow sprites (flowers / fruits / animals / space / orbs)."""
    theme = str(theme or "flowers").lower()
    if theme in ("flowers", "fruits", "animals", "space", "orbs"):
        frame_i = int(round((float(phase or 0.0) / (2.0 * math.pi)) * WORLD_S2_MOTION_FRAMES)) % max(
            1, int(WORLD_S2_MOTION_FRAMES)
        )
        arr, _fleet = _compose_bouncing_flowers_rgb(
            width, height, seed, frame_i, kind=theme
        )
        image = _qimage_from_rgb_array(arr)
        if image is not None and not image.isNull():
            painter.drawImage(0, 0, image)
            return
    rng = random.Random(int(seed) * 97 + 17)
    base = _wc_s2_base_rgb(theme, seed)
    painter.fillRect(0, 0, width, height, QColor(base[0], base[1], base[2], 255))
    count = int(round(22 * WORLD_S2_CAMO_SEVERITY))
    alpha = int(min(230, round(120 * WORLD_S2_CAMO_SEVERITY)))
    t = float(phase or 0.0)
    painter.setPen(Qt.NoPen)
    for i in range(count):
        ox = rng.randint(0, width)
        oy = rng.randint(0, height)
        radius = rng.randint(10, 26)
        drift_x = int(math.sin(t * 2.1 + i * 0.7) * (10 + radius * 0.25))
        drift_y = int(math.cos(t * 1.7 + i * 0.5) * (8 + radius * 0.2))
        cx = (ox + drift_x) % max(1, width)
        cy = (oy + drift_y) % max(1, height)
        spin = t * 40.0 + i * 17.0
        if theme == "fruits":
            fruit = QColor(
                rng.randint(170, 255),
                rng.randint(40, 160),
                rng.randint(30, 120),
                alpha,
            )
            painter.setBrush(fruit)
            painter.drawEllipse(cx - radius, cy - radius, radius * 2, radius * 2)
            painter.setBrush(QColor(40, 120, 50, min(255, alpha + 20)))
            painter.drawEllipse(cx - radius // 5, cy - radius - 4, max(4, radius // 3), max(6, radius // 2))
            highlight = QColor(255, 255, 255, max(40, alpha // 3))
            painter.setBrush(highlight)
            painter.drawEllipse(cx - radius // 2, cy - radius // 2, max(4, radius // 3), max(4, radius // 3))
        elif theme == "shapes":
            color = QColor(
                rng.randint(120, 230),
                rng.randint(140, 240),
                rng.randint(180, 255),
                alpha,
            )
            painter.setBrush(color)
            sides = 3 + (i % 4)
            pts = []
            for s in range(sides):
                ang = math.radians(spin + s * (360.0 / sides))
                pts.append(QtCore.QPoint(
                    int(cx + math.cos(ang) * radius),
                    int(cy + math.sin(ang) * radius),
                ))
            painter.drawPolygon(QtGui.QPolygon(pts))
        elif theme == "leaves":
            leaf = QColor(
                rng.randint(40, 120),
                rng.randint(130, 220),
                rng.randint(40, 110),
                alpha,
            )
            painter.setBrush(leaf)
            painter.save()
            painter.translate(cx, cy)
            painter.rotate(spin * 0.4 + i * 12)
            painter.drawEllipse(-radius // 3, -radius, max(6, radius // 2), radius * 2)
            painter.restore()
        elif theme == "orbs":
            orb = QColor(
                rng.randint(100, 220),
                rng.randint(80, 200),
                rng.randint(160, 255),
                max(60, alpha - 30),
            )
            painter.setBrush(orb)
            pulse = int(radius * (1.0 + 0.15 * math.sin(t * 3 + i)))
            painter.drawEllipse(cx - pulse, cy - pulse, pulse * 2, pulse * 2)
            painter.setBrush(QColor(255, 255, 255, max(30, alpha // 4)))
            painter.drawEllipse(cx - pulse // 3, cy - pulse // 3, max(4, pulse // 2), max(4, pulse // 2))
        else:
            # Fallback flowers if Pillow path failed.
            petal = QColor(
                rng.randint(140, 235),
                rng.randint(60, 180),
                rng.randint(90, 210),
                alpha,
            )
            painter.setBrush(petal)
            for angle in range(0, 360, 60):
                ang = math.radians(angle + spin)
                px = int(cx + math.cos(ang) * radius * 0.55)
                py = int(cy + math.sin(ang) * radius * 0.55)
                painter.drawEllipse(px - radius // 2, py - radius // 2, radius, radius)
            painter.setBrush(QColor(255, 230, 100, min(255, alpha + 20)))
            center = max(6, int(radius // 1.5))
            painter.drawEllipse(cx - radius // 3, cy - radius // 3, center, center)


def _render_camouflage_text_image(
    text: str,
    seed: int = 1,
    camouflage: bool = True,
    theme: str = "flowers",
    phase: float = 0.0,
    fast: bool = True,
) -> Optional[str]:
    """Still frame with overlaid text (digits and K2 same color).

    fast=True (default): solid theme fill only — keeps Realtime Play start instant.
    Motion graphics play from the shared looping video when it is ready.
    """
    raw = str(text or "").strip()
    if not raw:
        return None
    theme = str(theme or "flowers").lower()
    try:
        os.makedirs(MATH_EQ_CACHE_DIR, exist_ok=True)
    except Exception:
        return None
    phase_key = int(round(float(phase or 0.0) * 1000.0)) % 100000
    tag = "fast" if fast else "full"
    path = os.path.join(
        MATH_EQ_CACHE_DIR,
        f"wc_cam_v4_{tag}_{theme}_{seed}_{phase_key}_{_safe_cache_token(raw)}.png",
    )
    if os.path.isfile(path):
        return path
    try:
        from PyQt5.QtGui import QImage, QPainter, QColor, QFont
    except Exception as exc:
        logger.warning("Cannot render camouflage text (no Qt): %s", exc)
        return None
    w, h = 512, 512
    img = QImage(w, h, QImage.Format_ARGB32)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    if fast:
        base = _wc_s2_base_rgb(theme, seed)
        painter.fillRect(0, 0, w, h, QColor(base[0], base[1], base[2], 255))
    else:
        _paint_wc_motion_theme(painter, w, h, theme, seed, phase)
    font = QFont("Segoe UI", 50, QFont.Bold)
    painter.setFont(font)
    _ = camouflage
    tr, tg, tb = _wc_s2_text_rgb(theme, seed)
    painter.setPen(QColor(tr, tg, tb, 220))
    fx, fy = _wc_text_anchor_frac(seed, raw)
    _draw_text_at_frac(painter, raw, w, h, fx, fy)
    painter.end()
    if not img.save(path, "PNG"):
        return None
    return path


def _motion_bg_video_path(theme: str, base_rgb=None) -> str:
    """Stable cache path — one looping clip per theme (not per action)."""
    theme = str(theme or "flowers").lower()
    base = tuple(base_rgb) if base_rgb else _wc_s2_base_rgb(theme, 1)
    return os.path.join(
        MATH_EQ_CACHE_DIR,
        f"wc_motion_shared_{theme}_{int(base[0])}_{int(base[1])}_{int(base[2])}.mp4",
    )


def _peek_wc_motion_bg_video(theme: str, base_rgb=None) -> Optional[str]:
    """Return cached motion clip if already encoded; never blocks."""
    path = _motion_bg_video_path(theme, base_rgb)
    if os.path.isfile(path) and os.path.getsize(path) > 1000:
        return path
    alt = path.replace(".mp4", ".mjpg.avi")
    if os.path.isfile(alt) and os.path.getsize(alt) > 1000:
        return alt
    return None


def _encode_wc_motion_bg_video(theme: str, seed: int = 1, base_rgb=None) -> Optional[str]:
    """Encode one shared looping motion background (may take a few seconds)."""
    theme = str(theme or "flowers").lower()
    try:
        os.makedirs(MATH_EQ_CACHE_DIR, exist_ok=True)
    except Exception:
        return None
    path = _motion_bg_video_path(theme, base_rgb)
    existing = _peek_wc_motion_bg_video(theme, base_rgb)
    if existing:
        return existing
    try:
        import cv2
        import numpy as np
    except Exception as exc:
        logger.warning("OpenCV/numpy unavailable for WC motion bg: %s", exc)
        return None
    w = h = 512
    frames = int(WORLD_S2_MOTION_FRAMES)
    fps = int(WORLD_S2_MOTION_FPS)
    writer = None
    out_path = path
    for fourcc_name in ("mp4v", "MJPG", "XVID"):
        fourcc = cv2.VideoWriter_fourcc(*fourcc_name)
        candidate = path if fourcc_name == "mp4v" else path.replace(".mp4", f".{fourcc_name.lower()}.avi")
        writer = cv2.VideoWriter(candidate, fourcc, float(fps), (w, h))
        if writer.isOpened():
            out_path = candidate
            break
        writer.release()
        writer = None
    if writer is None:
        logger.warning("Could not open VideoWriter for WC motion bg")
        return None
    fleet = None
    bounce_themes = ("flowers", "fruits", "animals", "space", "orbs")
    for _frame_i in range(frames):
        if theme in bounce_themes:
            if fleet is None:
                arr, fleet = _compose_bouncing_flowers_rgb(
                    w, h, int(seed), frame_i=0, base_rgb=base_rgb, fleet=None, kind=theme
                )
            else:
                arr, fleet = _compose_bouncing_flowers_rgb(
                    w, h, int(seed), base_rgb=base_rgb, fleet=fleet, kind=theme
                )
            if arr is None:
                writer.release()
                return None
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        else:
            try:
                from PyQt5.QtGui import QImage, QPainter
            except Exception:
                writer.release()
                return None
            phase = (2.0 * math.pi * _frame_i) / max(1, frames)
            img = QImage(w, h, QImage.Format_RGB888)
            painter = QPainter(img)
            painter.setRenderHint(QPainter.Antialiasing)
            _paint_wc_motion_theme(painter, w, h, theme, int(seed), phase)
            painter.end()
            ptr = img.bits()
            ptr.setsize(img.byteCount())
            arr = np.frombuffer(ptr, np.uint8).reshape((h, w, 3)).copy()
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        writer.write(bgr)
    writer.release()
    if not os.path.isfile(out_path) or os.path.getsize(out_path) < 500:
        return None
    logger.info("Motion background ready: %s", os.path.basename(out_path))
    return out_path


def _schedule_wc_motion_bg_video(theme: str, seed: int = 1, base_rgb=None) -> Optional[str]:
    """Return clip if cached; otherwise encode in a background thread (non-blocking)."""
    ready = _peek_wc_motion_bg_video(theme, base_rgb)
    if ready:
        return ready
    key = _motion_bg_video_path(theme, base_rgb)
    with _MOTION_BG_LOCK:
        if key in _MOTION_BG_BUSY:
            return None
        _MOTION_BG_BUSY.add(key)

    def _worker():
        try:
            _encode_wc_motion_bg_video(theme, seed=seed, base_rgb=base_rgb)
        except Exception:
            logger.exception("Background motion encode failed for %s", theme)
        finally:
            with _MOTION_BG_LOCK:
                _MOTION_BG_BUSY.discard(key)

    threading.Thread(target=_worker, name="wc-motion-bg", daemon=True).start()
    return None


def _ensure_wc_motion_bg_video(theme: str, seed: int = 1, base_rgb=None, blocking: bool = False) -> Optional[str]:
    """Compatibility wrapper. Default is non-blocking so play starts immediately."""
    if blocking:
        return _encode_wc_motion_bg_video(theme, seed=seed, base_rgb=base_rgb)
    return _schedule_wc_motion_bg_video(theme, seed=seed, base_rgb=base_rgb)


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


def _read_image_action_cue_fields():
    """Live cue fields already on disk (so one field's update does not drop the other)."""
    try:
        if not os.path.isfile(IMAGE_ACTION_CUE_FILE):
            return {}
        with open(IMAGE_ACTION_CUE_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle) or {}
        fields = data.get("fields") if isinstance(data, dict) else {}
        return dict(fields) if isinstance(fields, dict) else {}
    except Exception:
        return {}


def _write_image_action_cue(active, field_screens, seq=0, force_end=False, action="PASS", on_sec=None, efficiency_max_sec=None, finish_balls=False, budget_elapsed_sec=None, budget_total_sec=None, action_in_set=None, actions_in_set=None, test_num=None, field_meta=None, field_seqs=None, keep_other_fields=True):
    """Tell simust_realtime which screens are lit (no QR on canvas).

    force_end=True: sequence finished — realtime must clear keypoints now.
    on_sec: effective teammate On duration for this action (session length).
    keep_other_fields: when updating one half, preserve the other half's cue so a
    mid-session join / goal does not blank the live field for 5s+ of opening.
    """
    payload = {
        "active": bool(active) and not force_end,
        "force_end": bool(force_end),
        "seq": int(seq),
        "fields": {},
        "timestamp": time.time(),
    }
    if keep_other_fields and active and not force_end:
        # Start from the other field's live cue, then overwrite fields we touch.
        payload["fields"] = {
            str(key).upper()[:1]: value
            for key, value in _read_image_action_cue_fields().items()
            if str(key).upper()[:1] in ("A", "B") and isinstance(value, dict)
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
            fid_key = str(fid).upper()
            meta = {}
            if isinstance(field_meta, dict):
                meta = field_meta.get(fid_key) or field_meta.get(fid) or {}
            field_payload = {
                "action": action_name,
                "screens": [str(s) for s in screens],
            }
            for key, fallback in (
                ("action_in_set", action_in_set),
                ("actions_in_set", actions_in_set),
                ("test_num", test_num),
            ):
                value = meta.get(key, fallback) if isinstance(meta, dict) else fallback
                if value is None:
                    continue
                try:
                    field_payload[key] = int(value)
                except (TypeError, ValueError):
                    pass
            if isinstance(meta, dict):
                for key in (
                    "on_sec",
                    "budget_elapsed_sec",
                    "budget_total_sec",
                    "efficiency_max_sec",
                ):
                    if meta.get(key) is None:
                        continue
                    try:
                        field_payload[key] = float(meta.get(key))
                    except (TypeError, ValueError):
                        pass
            own_seq = None
            if isinstance(field_seqs, dict):
                own_seq = field_seqs.get(fid_key, field_seqs.get(fid))
            if own_seq is None and isinstance(meta, dict):
                own_seq = meta.get("seq")
            if own_seq is not None:
                try:
                    field_payload["seq"] = int(own_seq)
                except (TypeError, ValueError):
                    pass
            payload["fields"][fid_key] = field_payload
    if active and not force_end and field_screens:
        # Drop halves that are no longer in this write and were not preserved.
        wanted = {str(fid).upper()[:1] for fid in field_screens if field_screens.get(fid)}
        if not keep_other_fields:
            payload["fields"] = {
                key: value for key, value in payload["fields"].items() if key in wanted
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

    saver_pixels_ready = pyqtSignal(object, int)

    # Pass pictures are 30% smaller than the previous 0.81 scale (~57% of the content box).
    # Digits and equations stay full size.
    PASS_IMAGE_SCALE = 0.57

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
        self._summary_logo = False
        self._result_badges = {}
        self._badge_anchor = "center"
        self._text_overlays = {}
        self._text_overlay_positions = {}
        self._text_overlay_color = (245, 240, 220)
        self._image_overlays = {}
        # Live bouncing sprites (flowers / fruits / …) — reseeded every action.
        self._bounce_timer = None
        self._bounce_fleet = None
        self._bounce_theme = None
        self._bounce_seed = None
        self._bounce_base_rgb = None
        self._bounce_screens = set()
        self._bounce_size = 512
        self._field_level_colors = {}
        self._saver_jpegs = None
        self._saver_index = 0
        self._saver_pix = None
        self._saver_timer = None
        self._saver_loading = False
        self.saver_pixels_ready.connect(self._on_saver_pixels_ready)
        # Coded pass .ssav (Foundation / Omid) — separate from cabinet screensaver.
        self._pass_ssav_jpegs = None
        self._pass_ssav_index = 0
        self._pass_ssav_screens = set()
        self._pass_ssav_timer = None
        self._pass_ssav_path = ""

    def set_field_level_colors(self, colors):
        """Per-field brand fills behind scaled logo / coach / screensaver clips."""
        cleaned = {}
        for fid, pair in (colors or {}).items():
            key = str(fid or "").upper()[:1]
            if key not in ("A", "B") or not isinstance(pair, (list, tuple)) or len(pair) < 1:
                continue
            bg = pair[0] if isinstance(pair[0], (list, tuple)) else pair
            cleaned[key] = tuple(int(v) for v in bg[:3])
        self._field_level_colors = cleaned
        self.update()

    def _field_level_qcolor(self, fid):
        rgb = (self._field_level_colors or {}).get(str(fid or "").upper()[:1])
        if not rgb:
            return QtGui.QColor(0, 0, 0)
        return QtGui.QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]))

    def clear(self):
        self._stop_screen_video(clear_screensaver=True)
        self._stop_pass_ssav()
        self.stop_screen_players()
        self._stop_bounce_motion()
        self.active_screens = set()
        self._screen_pixmaps = {}
        self._content_scale = 1.0
        self._summary_lines = []
        self._summary_screens = None
        self._summary_by_screen = {}
        self._summary_bg = (0, 0, 0)
        self._summary_fg = (255, 255, 255)
        self._summary_logo = False
        self._text_overlays = {}
        self._text_overlay_positions = {}
        self._image_overlays = {}
        self.update()

    def _player_controller(self):
        """Lazy .player (PLYR1) animation controller from static/siamak_files."""
        controller = getattr(self, "_coded_players", None)
        if controller is None:
            from player_qt import PlayerController
            controller = PlayerController(
                self, QtCore, QtGui, _sid, _field_for_screen, SLICE_ORDER,
            )
            self._coded_players = controller
        return controller

    def set_screen_players(self, screen_to_path, scale=None, loop=False,
                           replace_fields=None):
        """Play coded .player assets on these screens (omid_2). No mp4 / .ssav."""
        controller = self._player_controller()
        mapping = {
            _sid(sid): path
            for sid, path in (screen_to_path or {}).items()
            if _sid(sid) and path
        }
        fields = None if replace_fields is None else {
            str(fid).upper()[:1] for fid in replace_fields
            if str(fid).upper()[:1] in ("A", "B")
        }
        names = set(mapping)
        if fields and any(_field_for_screen(s) not in fields for s in names):
            raise ValueError("Player screens must belong to replace_fields")
        scale = self.PASS_IMAGE_SCALE if scale is None else float(scale)
        if not 0 < scale <= 1:
            raise ValueError("Player scale must be greater than zero and at most one")
        groups = controller.prepare(mapping)
        try:
            self._stop_pass_ssav()
            if fields is None:
                self._stop_bounce_motion()
                self._stop_screen_video()
                self._summary_lines = []
                self._summary_screens = None
                self._summary_by_screen = {}
                self._screen_pixmaps = {}
                self._still_pixmaps = {}
                self._text_overlays = {}
                self._text_overlay_positions = {}
                self._image_overlays = {}
            elif fields:
                self._release_field_videos(fields)
                self._clear_field_summary(fields)
                bounce = set(getattr(self, "_bounce_screens", None) or set())
                self._bounce_screens = {
                    s for s in bounce if _field_for_screen(s) not in fields
                }
                if not self._bounce_screens:
                    self._stop_bounce_motion()
                for attr in (
                    "_screen_pixmaps", "_still_pixmaps", "_text_overlays",
                    "_text_overlay_positions", "_image_overlays", "_result_badges",
                ):
                    setattr(self, attr, {
                        s: v for s, v in (getattr(self, attr, None) or {}).items()
                        if _field_for_screen(s) not in fields
                    })
            else:
                controller.stop(screens=names)
            affected = set(names)
            if fields is None:
                affected |= set(SLICE_ORDER)
            elif fields:
                affected |= {
                    s for s in SLICE_ORDER if _field_for_screen(s) in fields
                }
            for attr in (
                "_screensaver_scale_screens", "_logo_scale_screens",
                "_video_fill_screens", "_band_screens", "_pass_ssav_screens",
            ):
                current = set(getattr(self, attr, None) or set())
                setattr(self, attr, current - affected)
            self._result_badges = {
                s: v for s, v in (getattr(self, "_result_badges", None) or {}).items()
                if s not in affected
            }
            self._content_scale = float(scale)
            controller.start(groups, bool(loop), scale)
        except Exception:
            if not any(g in controller.groups for g in groups):
                controller.discard(groups)
            raise
        self.active_screens = set(getattr(self, "_screen_pixmaps", {}) or {})
        self.update()
        return True

    def _stop_players_on_screens(self, screens):
        controller = getattr(self, "_coded_players", None)
        if controller is not None:
            controller.stop(screens={_sid(s) for s in (screens or []) if _sid(s)})

    def stop_screen_players(self, field_ids=None):
        controller = getattr(self, "_coded_players", None)
        if controller is not None:
            controller.stop(fields=field_ids)
            self.update()

    def set_text_overlays(self, screen_to_text, color=None, positions=None):
        """Draw camouflage digits / K2 on top of motion backgrounds."""
        overlays = {}
        for sid, text in (screen_to_text or {}).items():
            name = _sid(sid)
            raw = str(text or "").strip()
            if name and raw:
                overlays[name] = raw
        self._text_overlays = overlays
        pos_map = {}
        for sid, pos in (positions or {}).items():
            name = _sid(sid)
            if not name or not pos or len(pos) < 2:
                continue
            try:
                pos_map[name] = (float(pos[0]), float(pos[1]))
            except (TypeError, ValueError):
                continue
        self._text_overlay_positions = pos_map
        if color is not None:
            self._text_overlay_color = tuple(int(v) for v in color[:3])
        self.update()

    def set_image_overlays(self, screen_to_path):
        """Draw transparent letter/shape PNGs on top of motion backgrounds."""
        overlays = {}
        for sid, path in (screen_to_path or {}).items():
            name = _sid(sid)
            pix = self._load_pixmap(path) if path else None
            if name and pix is not None and not pix.isNull():
                overlays[name] = pix
        self._image_overlays = overlays
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

    def set_level_summary(self, lines, screen_ids=None, background=None, foreground=None, logo_video=None):
        """Show the test name, time, and action count on each listed screen.

        logo_video draws a small looping clip above the text.
        """
        self._stop_bounce_motion()
        self._stop_screen_video()
        self.active_screens = set()
        self._screen_pixmaps = {}
        self._summary_by_screen = {}
        self._summary_logo = False
        self._summary_lines = [str(line) for line in (lines or []) if str(line).strip()]
        chosen = {_sid(sid) for sid in (screen_ids or []) if _sid(sid)}
        self._summary_screens = chosen or None
        self._summary_bg = tuple(int(v) for v in (background or (0, 0, 0))[:3])
        self._summary_fg = tuple(int(v) for v in (foreground or (255, 255, 255))[:3])
        self._result_badges = {}
        if logo_video and chosen:
            self._start_summary_logos({sid: logo_video for sid in chosen})
        else:
            self.update()

    def set_level_summaries(self, by_screen, logo_video=None):
        """Different opening text and colors on each field's screens."""
        self._stop_bounce_motion()
        self._stop_screen_video()
        self.active_screens = set()
        self._screen_pixmaps = {}
        self._summary_logo = False
        specs = {}
        logos = {}
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
            logo = spec.get("logo") or logo_video
            if logo:
                logos[name] = logo
        self._summary_by_screen = specs
        self._summary_lines = [" "] if specs else []
        self._summary_screens = set(specs) or None
        self._result_badges = {}
        if logos:
            self._start_summary_logos(logos)
        else:
            self.update()

    def _start_summary_logos(self, screen_to_path):
        """Loop small logo clip(s) while the opening information stays visible."""
        groups = {}
        for sid, video_path in (screen_to_path or {}).items():
            name = _sid(sid)
            path = str(video_path or "")
            if not name or not path or not os.path.isfile(path):
                continue
            groups.setdefault(os.path.abspath(path), set()).add(name)
        if not groups:
            self.update()
            return
        self._summary_logo = True
        self._video_fill = False
        self._content_scale = float(OPENING_LOGO_MAX_WIDTH)
        # Opening logos paint via the summary path only — drop leftover results
        # logo-scale and saver stamps so a second darker clip cannot overlap.
        logo_names = {sid for screens in groups.values() for sid in screens}
        logo_scale = set(getattr(self, "_logo_scale_screens", None) or set())
        saver = set(getattr(self, "_screensaver_scale_screens", None) or set())
        for name in logo_names:
            logo_scale.discard(name)
            saver.discard(name)
        self._logo_scale_screens = logo_scale
        self._screensaver_scale_screens = saver
        try:
            import cv2
        except Exception as exc:
            logger.warning("OpenCV unavailable for opening logo: %s", exc)
            self.update()
            return
        fps = 25.0
        opened = []
        for path, screens in groups.items():
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                logger.warning("Could not open opening logo video: %s", path)
                continue
            rate = float(cap.get(cv2.CAP_PROP_FPS) or 0) or 25.0
            fps = max(fps, rate)
            opened.append({"cap": cap, "screens": set(screens), "path": path})
        if not opened:
            self.update()
            return
        logo_names = {sid for group in opened for sid in group["screens"]}
        kept = []
        for group in list(getattr(self, "_video_groups", None) or []):
            screens = {_sid(sid) for sid in (group.get("screens") or set()) if _sid(sid)}
            if screens & logo_names:
                cap = group.get("cap")
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass
                continue
            kept.append(group)
        old_timer = getattr(self, "_video_timer", None)
        if old_timer is not None:
            try:
                old_timer.stop()
            except Exception:
                pass
        self._video_groups = kept + opened
        self._tick_screen_video()
        interval = max(20, int(round(1000.0 / fps)))
        self._video_timer = QtCore.QTimer(self)
        self._video_timer.timeout.connect(self._tick_screen_video)
        self._video_timer.start(interval)

    def set_pass_screens(self, screen_ids):
        """Legacy: same fallback image on each lit screen."""
        self._stop_bounce_motion()
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

    def set_screen_images(self, screen_to_path, scale=1.0, keep_videos=False, replace_fields=None):
        """Map screen id → image path (action, filler, or gap)."""
        replace = {str(fid).upper()[:1] for fid in (replace_fields or set()) if str(fid).upper()[:1] in ("A", "B")}
        if replace:
            bounce = {
                name for name in (getattr(self, "_bounce_screens", None) or set())
                if _field_for_screen(name) not in replace
            }
            self._bounce_screens = bounce
            if not bounce:
                self._stop_bounce_motion()
            overlays = getattr(self, "_image_overlays", None) or {}
            self._image_overlays = {
                name: pix for name, pix in overlays.items()
                if _field_for_screen(name) not in replace
            }
            texts = getattr(self, "_text_overlays", None) or {}
            self._text_overlays = {
                name: text for name, text in texts.items()
                if _field_for_screen(name) not in replace
            }
        else:
            self._stop_bounce_motion()
        if replace:
            self._release_field_videos(replace)
            self._clear_field_summary(replace)
            self.stop_screen_players(replace)
            fill = set(getattr(self, "_video_fill_screens", None) or set())
            for name in list(fill):
                if _field_for_screen(name) in replace:
                    fill.discard(name)
            self._video_fill_screens = fill
            # Joining / restarting a field must drop its .ssav ownership or the
            # coded saver keeps painting over realtime actions on that half.
            saver_scale = set(getattr(self, "_screensaver_scale_screens", None) or set())
            for name in list(saver_scale):
                if _field_for_screen(name) in replace:
                    saver_scale.discard(name)
            self._screensaver_scale_screens = saver_scale
            # Drop coded pass tiles for the replaced field (stills take over).
            pass_screens = set(getattr(self, "_pass_ssav_screens", None) or set())
            for name in list(pass_screens):
                if _field_for_screen(name) in replace:
                    pass_screens.discard(name)
            self._pass_ssav_screens = pass_screens
            if not pass_screens:
                self._stop_pass_ssav()
        elif not keep_videos:
            self._stop_screen_video()
            self._summary_lines = []
            self._summary_screens = None
            self._summary_by_screen = {}
            self._video_fill_screens = set()
        if not replace and not getattr(self, "_keep_text_overlays", False):
            self._text_overlays = {}
            self._text_overlay_positions = {}
            self._image_overlays = {}
        self._keep_text_overlays = False
        self._content_scale = float(scale or 1.0)
        stills = {}
        for sid, path in (screen_to_path or {}).items():
            pix = self._load_pixmap(path)
            if pix is None or pix.isNull():
                continue
            key = _sid(sid)
            if not key:
                continue
            stills[key] = pix
        # Action stills must never keep the opening/results logo box size.
        logo_scale = set(getattr(self, "_logo_scale_screens", None) or set())
        for key in stills:
            logo_scale.discard(key)
        if replace:
            for name in list(logo_scale):
                if _field_for_screen(name) in replace:
                    logo_scale.discard(name)
        elif not keep_videos:
            logo_scale = set()
        self._logo_scale_screens = logo_scale
        band = set(getattr(self, "_band_screens", None) or set())
        if keep_videos or replace:
            for key in stills:
                band.discard(key)
            if replace:
                for name in list(band):
                    if _field_for_screen(name) in replace:
                        band.discard(name)
        else:
            band = set()
        self._band_screens = band
        if replace or keep_videos:
            merged = _without_field_screens(getattr(self, "_screen_pixmaps", None) or {}, replace)
            kept_stills = _without_field_screens(getattr(self, "_still_pixmaps", None) or {}, replace)
            if not replace:
                merged = dict(getattr(self, "_screen_pixmaps", None) or {})
                kept_stills = dict(getattr(self, "_still_pixmaps", None) or {})
            merged.update(stills)
            kept_stills.update(stills)
            # Keep free-field coded .ssav tiles when only the busy field is replaced.
            named = set(merged)
            self._stamp_screensaver_pixels(merged, named)
            self._screen_pixmaps = merged
            self._still_pixmaps = kept_stills
        else:
            self._screen_pixmaps = dict(stills)
            self._still_pixmaps = dict(stills)
        self.active_screens = set(self._screen_pixmaps)
        self.update()

    def play_band_on_screens(self, video_path, screen_ids):
        """Play one full-band results clip, cropped onto this field's screens."""
        screens = {_sid(sid) for sid in (screen_ids or []) if _sid(sid) and _sid(sid) in SLICE_ORDER}
        path = str(video_path or "")
        if not screens or not path or not os.path.isfile(path):
            return False
        try:
            import cv2
        except Exception as exc:
            logger.warning("OpenCV unavailable for field results: %s", exc)
            return False
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            logger.warning("Could not open field results: %s", path)
            return False
        kept = []
        for group in list(getattr(self, "_video_groups", None) or []):
            if screens.intersection(group.get("screens") or set()):
                try:
                    group["cap"].release()
                except Exception:
                    pass
                continue
            kept.append(group)
        kept.append({
            "cap": cap,
            "screens": set(screens),
            "path": path,
            "full_band": True,
        })
        self._video_groups = kept
        self._video_screens = {sid for group in kept for sid in group["screens"]}
        self._tick_screen_video()
        if self._video_timer is None:
            rate = float(cap.get(cv2.CAP_PROP_FPS) or 0) or 25.0
            interval = max(20, int(round(1000.0 / rate)))
            self._video_timer = QtCore.QTimer(self)
            self._video_timer.timeout.connect(self._tick_screen_video)
            self._video_timer.start(interval)
        return True

    def set_screen_video(self, screen_ids, video_path, scale=None):
        """Play the same pass.mp4 (looping) on each listed screen tile."""
        # Prefer coded .ssav beside the clip so play never opens the video.
        path = str(video_path or "")
        if path.lower().endswith(".mp4"):
            ssav = os.path.splitext(path)[0].replace("pass", "pass_pixels")
            sibling = os.path.join(os.path.dirname(path), "pass_pixels.ssav")
            for cand in (sibling, ssav if ssav.endswith(".ssav") else ""):
                if cand and os.path.isfile(cand):
                    return self.set_screen_ssav(
                        {_sid(s): cand for s in (screen_ids or []) if _sid(s)},
                        scale=self.PASS_IMAGE_SCALE if scale is None else scale,
                    )
        self.set_screen_videos(
            {_sid(s): video_path for s in (screen_ids or []) if _sid(s)},
            scale=self.PASS_IMAGE_SCALE if scale is None else scale,
        )

    def set_screen_ssav(self, screen_to_ssav, scale=None, replace_fields=None):
        """Loop coded .ssav pass pixels on these screens. Never opens the mp4."""
        self._stop_bounce_motion()
        # Stop OpenCV clips only — do not clear an in-flight coded pass yet.
        try:
            if self._video_timer is not None:
                self._video_timer.stop()
                self._video_timer.deleteLater()
        except Exception:
            pass
        self._video_timer = None
        for group in list(getattr(self, "_video_groups", None) or []):
            try:
                (group.get("cap") or None) and group["cap"].release()
            except Exception:
                pass
        self._video_groups = []
        self._video_screens = set()
        self._video_cap = None
        self._summary_lines = []
        self._summary_screens = None
        self._summary_by_screen = {}
        if not getattr(self, "_keep_text_overlays", False):
            self._text_overlays = {}
            self._text_overlay_positions = {}
            self._image_overlays = {}
        self._keep_text_overlays = False
        self._video_fill = False
        self._content_scale = float(
            self.PASS_IMAGE_SCALE if scale is None else scale
        )
        screens = set()
        ssav_path = ""
        for sid, path in (screen_to_ssav or {}).items():
            key = _sid(sid)
            path = str(path or "")
            if not key or key not in SLICE_ORDER or not path:
                continue
            if not path.lower().endswith(".ssav"):
                continue
            if not os.path.isfile(path):
                continue
            screens.add(key)
            ssav_path = os.path.abspath(path)
        if not screens or not ssav_path:
            self.update()
            return False
        try:
            from screen_saver_anim import load_ssav_pixels_file
            frames, interval_ms = load_ssav_pixels_file(ssav_path)
        except Exception:
            logger.exception("Could not load pass .ssav %s", ssav_path)
            frames, interval_ms = [], 33
        if not frames:
            logger.warning("Empty pass .ssav: %s", ssav_path)
            self.update()
            return False
        replace = {str(fid).upper()[:1] for fid in (replace_fields or set())}
        # Action owns these tiles — coded cabinet saver must not cover them.
        saver_scale = set(getattr(self, "_screensaver_scale_screens", None) or set())
        fill = set(getattr(self, "_video_fill_screens", None) or set())
        for name in screens:
            saver_scale.discard(name)
            fill.discard(name)
        self._screensaver_scale_screens = saver_scale
        self._video_fill_screens = fill
        same_clip = (
            os.path.abspath(str(getattr(self, "_pass_ssav_path", "") or "")) == ssav_path
            and list(getattr(self, "_pass_ssav_jpegs", None) or [])
        )
        if replace:
            kept = {
                name: pix
                for name, pix in (getattr(self, "_screen_pixmaps", None) or {}).items()
                if _field_for_screen(name) not in replace
            }
            old_pass = {
                name
                for name in (getattr(self, "_pass_ssav_screens", None) or set())
                if _field_for_screen(name) not in replace
            }
            self._screen_pixmaps = kept
            self._pass_ssav_screens = old_pass | screens
        else:
            self._stop_pass_ssav()
            self._screen_pixmaps = {}
            self._pass_ssav_screens = set(screens)
        self._pass_ssav_jpegs = list(frames)
        self._pass_ssav_path = ssav_path
        if not same_clip:
            self._pass_ssav_index = 0
        self.active_screens = set(self._screen_pixmaps) | set(self._pass_ssav_screens)
        interval = max(16, int(interval_ms or 33))
        if getattr(self, "_pass_ssav_timer", None) is None:
            timer = QtCore.QTimer(self)
            timer.timeout.connect(self._tick_pass_ssav)
            timer.start(interval)
            self._pass_ssav_timer = timer
        self._tick_pass_ssav()
        logger.info(
            "Coded pass .ssav on %s (%s frames, %sms) — video not opened",
            sorted(screens),
            len(frames),
            interval,
        )
        return True

    def _tick_pass_ssav(self):
        screens = set(getattr(self, "_pass_ssav_screens", None) or set())
        frames = list(getattr(self, "_pass_ssav_jpegs", None) or [])
        if not screens or not frames:
            self._stop_pass_ssav()
            return
        index = int(getattr(self, "_pass_ssav_index", 0) or 0) % len(frames)
        self._pass_ssav_index = index + 1
        image = QtGui.QImage.fromData(frames[index])
        if image.isNull():
            return
        pix = QtGui.QPixmap.fromImage(image)
        pixmaps = dict(getattr(self, "_screen_pixmaps", None) or {})
        for name in screens:
            pixmaps[name] = pix
        self._stamp_screensaver_pixels(pixmaps, set())
        self._screen_pixmaps = pixmaps
        self.active_screens = set(pixmaps) | set(getattr(self, "active_screens", None) or set())
        self.update()

    def _stop_pass_ssav(self):
        timer = getattr(self, "_pass_ssav_timer", None)
        if timer is not None:
            try:
                timer.stop()
                timer.deleteLater()
            except Exception:
                pass
        self._pass_ssav_timer = None
        self._pass_ssav_jpegs = None
        self._pass_ssav_index = 0
        self._pass_ssav_screens = set()
        self._pass_ssav_path = ""

    def set_screen_videos(self, screen_to_path, fill=False, scale=None, start_frame=0, loop=True):
        """Play a full video on each screen. Screens that share a path share one decoder."""
        # Coded .ssav paths must never open as OpenCV video.
        ssav_only = {}
        rest = {}
        for sid, path in (screen_to_path or {}).items():
            path = str(path or "")
            if path.lower().endswith(".ssav"):
                ssav_only[sid] = path
            else:
                rest[sid] = path
        if ssav_only and not rest:
            return self.set_screen_ssav(
                ssav_only,
                scale=self.PASS_IMAGE_SCALE if scale is None else scale,
            )
        self._stop_bounce_motion()
        self._stop_screen_video()
        self._summary_lines = []
        self._summary_screens = None
        self._summary_by_screen = {}
        if not getattr(self, "_keep_text_overlays", False):
            self._text_overlays = {}
            self._text_overlay_positions = {}
            self._image_overlays = {}
        self._keep_text_overlays = False
        self._video_fill = bool(fill)
        if scale is None:
            scale = 1.0 if fill else self.PASS_IMAGE_SCALE
        self._content_scale = float(scale)
        start_frame = max(0, int(start_frame or 0))
        loop = bool(loop)
        groups = {}
        for sid, path in rest.items():
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
            if start_frame:
                total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                if total > 0:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame % total)
                else:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            opened.append({
                "cap": cap,
                "screens": set(screens),
                "path": path,
                "loop": loop,
            })
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

    def _clear_field_summary(self, field_ids):
        """Remove the opening card from these fields. The other field's card stays."""
        replace = {str(fid).upper()[:1] for fid in (field_ids or set())}
        by_screen = dict(getattr(self, "_summary_by_screen", None) or {})
        for name in list(by_screen):
            if _field_for_screen(name) in replace:
                by_screen.pop(name, None)
        screens = {
            name for name in (getattr(self, "_summary_screens", None) or set())
            if _field_for_screen(name) not in replace
        }
        self._summary_by_screen = by_screen
        self._summary_screens = screens or None
        self._summary_lines = [" "] if by_screen else []
        if not by_screen:
            self._summary_logo = False

    def show_field_opening(self, fid, card):
        """Opening information on this field only. The other field keeps its test."""
        fid = str(fid or "").upper()[:1]
        screens = [name for name in _field_all_screens(fid) if name]
        if not screens or not isinstance(card, dict):
            return
        # Beginning-info logos are not the screensaver path.
        try:
            player = self.parent()
            if player is not None and hasattr(player, "_stop_field_screensaver"):
                player._stop_field_screensaver(fid)
        except Exception:
            pass
        self._release_field_videos({fid})
        kept = {}
        for source in (
            getattr(self, "_still_pixmaps", None) or {},
            getattr(self, "_screen_pixmaps", None) or {},
        ):
            for sid, pix in source.items():
                name = _sid(sid)
                if name and _field_for_screen(name) != fid and pix is not None:
                    kept[name] = pix
        stills = kept
        self._still_pixmaps = stills
        self._screen_pixmaps = dict(stills)
        by_screen = dict(getattr(self, "_summary_by_screen", None) or {})
        chosen = set(getattr(self, "_summary_screens", None) or set())
        for name in screens:
            by_screen[name] = {
                "lines": [str(line) for line in (card.get("lines") or []) if str(line).strip()],
                "bg": tuple(int(v) for v in (card.get("bg") or (0, 0, 0))[:3]),
                "fg": tuple(int(v) for v in (card.get("fg") or (255, 255, 255))[:3]),
            }
            chosen.add(name)
        self._summary_by_screen = by_screen
        self._summary_screens = chosen
        self._summary_lines = [" "] if by_screen else []
        saved_scale = float(getattr(self, "_content_scale", 1.0) or 1.0)
        saved_fill = bool(getattr(self, "_video_fill", False))
        logo = card.get("logo")
        if logo:
            self._start_summary_logos({name: logo for name in screens})
            self._content_scale = saved_scale
            self._video_fill = saved_fill
        else:
            self._summary_logo = False
            self.update()

    def play_field_intro(self, fid, video_path):
        """Starting video on this field only."""
        fid = str(fid or "").upper()[:1]
        screens = {_sid(name) for name in _field_all_screens(fid) if _sid(name)}
        self._clear_field_summary({fid})
        self._release_field_videos({fid})
        path = str(video_path or "")
        if not screens or not path or not os.path.isfile(path):
            self.update()
            return False
        stills = {}
        for source in (
            getattr(self, "_still_pixmaps", None) or {},
            getattr(self, "_screen_pixmaps", None) or {},
        ):
            for sid, pix in source.items():
                name = _sid(sid)
                if name and name not in screens and pix is not None:
                    stills[name] = pix
        self._still_pixmaps = stills
        try:
            import cv2
        except Exception:
            self.update()
            return False
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            self.update()
            return False
        groups = list(getattr(self, "_video_groups", None) or [])
        groups.append({
            "cap": cap,
            "screens": set(screens),
            "path": path,
            "loop": False,
        })
        self._video_groups = groups
        fill = set(getattr(self, "_video_fill_screens", None) or set())
        fill |= set(screens)
        self._video_fill_screens = fill
        self._video_screens = {sid for group in groups for sid in (group.get("screens") or set())}
        if getattr(self, "_video_timer", None) is None:
            self._tick_screen_video()
            self._video_timer = QtCore.QTimer(self)
            self._video_timer.timeout.connect(self._tick_screen_video)
            rate = float(cap.get(cv2.CAP_PROP_FPS) or 0) or 25.0
            self._video_timer.start(max(20, int(round(1000.0 / rate))))
        else:
            self._tick_screen_video()
        return True

    def play_layered_clips(self, layers):
        """Play clips on named screens without stopping the other field.

        Each layer is (screen → path, loop[, fill]). Earlier layers sit under
        later ones, so a logo can show once a coach clip that does not loop has
        finished. fill=False keeps the opening-logo size (not full-bleed).
        """
        try:
            import cv2
        except Exception:
            return False
        opened = []
        new_screens = set()
        fill_screens = set()
        for item in layers or []:
            mapping = item[0]
            loop = bool(item[1])
            fill = bool(item[2]) if len(item) > 2 else True
            by_path = {}
            for sid, path in (mapping or {}).items():
                name = _sid(sid)
                path = str(path or "")
                if not name or not path or not os.path.isfile(path):
                    continue
                by_path.setdefault(os.path.abspath(path), set()).add(name)
            for path, screens in by_path.items():
                cap = cv2.VideoCapture(path)
                if not cap.isOpened():
                    continue
                opened.append({
                    "cap": cap,
                    "screens": set(screens),
                    "path": path,
                    "loop": loop,
                    "fill": fill,
                })
                new_screens |= set(screens)
                if fill:
                    fill_screens |= set(screens)
        if not opened:
            return False
        kept = []
        for group in list(getattr(self, "_video_groups", None) or []):
            screens = {_sid(sid) for sid in (group.get("screens") or set()) if _sid(sid)}
            if screens & new_screens:
                try:
                    group["cap"].release()
                except Exception:
                    pass
                continue
            kept.append(group)
        stills = {}
        for source in (
            getattr(self, "_still_pixmaps", None) or {},
            getattr(self, "_screen_pixmaps", None) or {},
        ):
            for sid, pix in source.items():
                name = _sid(sid)
                if name and name not in new_screens and pix is not None:
                    stills[name] = pix
        self._still_pixmaps = stills
        self._video_groups = kept + opened
        fill = set(getattr(self, "_video_fill_screens", None) or set())
        logo_scale = set(getattr(self, "_logo_scale_screens", None) or set())
        for name in new_screens:
            fill.discard(name)
            logo_scale.discard(name)
        fill |= fill_screens
        for group in opened:
            if not group.get("fill", True):
                logo_scale |= set(group.get("screens") or set())
        self._video_fill_screens = fill
        self._logo_scale_screens = logo_scale
        if logo_scale:
            self._content_scale = float(OPENING_LOGO_MAX_WIDTH)
        self._video_screens = {sid for group in self._video_groups for sid in (group.get("screens") or set())}
        if getattr(self, "_video_timer", None) is None:
            self._tick_screen_video()
            self._video_timer = QtCore.QTimer(self)
            self._video_timer.timeout.connect(self._tick_screen_video)
            self._video_timer.start(40)
        else:
            self._tick_screen_video()
        return True

    def _release_field_videos(self, field_ids):
        """Stop this field's clips. The other field's clip keeps playing."""
        replace = {str(fid).upper()[:1] for fid in (field_ids or set())}
        groups = []
        for group in list(getattr(self, "_video_groups", None) or []):
            screens = { _sid(sid) for sid in (group.get("screens") or set()) if _sid(sid) }
            if any(_field_for_screen(name) in replace for name in screens):
                try:
                    group["cap"].release()
                except Exception:
                    pass
                continue
            groups.append(group)
        self._video_groups = groups
        self._video_screens = {sid for group in groups for sid in (group.get("screens") or set())}
        logo_scale = set(getattr(self, "_logo_scale_screens", None) or set())
        for name in list(logo_scale):
            if _field_for_screen(name) in replace:
                logo_scale.discard(name)
        self._logo_scale_screens = logo_scale
        # Do not clear coded .ssav saver tiles here — free-field saver is independent
        # of the busy field's OpenCV clips. Bounce/stop_field_screensaver manage it.
        fill = set(getattr(self, "_video_fill_screens", None) or set())
        for name in list(fill):
            if _field_for_screen(name) in replace:
                fill.discard(name)
        self._video_fill_screens = fill
        if groups:
            return
        timer = getattr(self, "_video_timer", None)
        if timer is not None:
            try:
                timer.stop()
                timer.deleteLater()
            except Exception:
                pass
            self._video_timer = None
        self._video_frame = None

    def _stop_screen_video(self, clear_screensaver: bool = False):
        """Stop OpenCV clip groups. Coded .ssav screensaver keeps running unless asked."""
        try:
            self._stop_pass_ssav()
        except Exception:
            pass
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
        self._band_screens = set()
        self._summary_logo = False
        self._logo_scale_screens = set()
        if clear_screensaver:
            self._screensaver_scale_screens = set()
            self._saver_pix = None
            self._stop_coded_screensaver_timer()

    def _stamp_screensaver_pixels(self, pixmaps, screens):
        """Keep coded .ssav / .player frames on free-field tiles when action redraws."""
        controller = getattr(self, "_coded_players", None)
        if controller is not None:
            controller.stamp(pixmaps, screens)
        pix = getattr(self, "_saver_pix", None)
        saver_screens = set(getattr(self, "_screensaver_scale_screens", None) or set())
        if pix is None or not saver_screens:
            return
        bounce = set(getattr(self, "_bounce_screens", None) or set())
        summary = set(getattr(self, "_summary_screens", None) or set())
        logo = set(getattr(self, "_logo_scale_screens", None) or set())
        stills = set(getattr(self, "_still_pixmaps", None) or {})
        fill = set(getattr(self, "_video_fill_screens", None) or set())
        player_screens = set(controller.screens) if controller is not None else set()
        for name in saver_screens:
            # Never paint saver over a live action, opening card, or results logo.
            if (
                name in bounce
                or name in summary
                or name in logo
                or name in stills
                or name in fill
                or name in player_screens
            ):
                continue
            pixmaps[name] = pix
            screens.add(name)

    def _stop_coded_screensaver_timer(self):
        timer = getattr(self, "_saver_timer", None)
        if timer is not None:
            try:
                timer.stop()
                timer.deleteLater()
            except Exception:
                pass
        self._saver_timer = None

    def play_coded_screensaver(self, screen_ids):
        """Loop extracted screensaver pixels on these screens. No video decode at play time.

        Never steals logo / results tiles — those stay on _logo_scale_screens.
        """
        logo_scale = set(getattr(self, "_logo_scale_screens", None) or set())
        controller = getattr(self, "_coded_players", None)
        player_screens = set(controller.screens) if controller is not None else set()
        screens = set()
        for sid in screen_ids or []:
            name = _sid(sid)
            if not name:
                continue
            # Do not replace opening / results logo or live .player tiles.
            if name in logo_scale or name in player_screens:
                continue
            screens.add(name)
        if not screens:
            return False
        saver_scale = set(getattr(self, "_screensaver_scale_screens", None) or set())
        fill = set(getattr(self, "_video_fill_screens", None) or set())
        for name in screens:
            fill.discard(name)
            saver_scale.add(name)
        self._video_fill_screens = fill
        self._screensaver_scale_screens = saver_scale
        frames = getattr(self, "_saver_jpegs", None)
        if frames:
            self._ensure_saver_timer()
            self._tick_coded_screensaver()
            return True
        if not getattr(self, "_saver_loading", False):
            self._saver_loading = True
            threading.Thread(target=self._load_saver_pixels, daemon=True).start()
        return True

    def _load_saver_pixels(self):
        frames, interval_ms = [], 33
        try:
            from screen_saver_anim import load_screensaver_pixels
            path = _screen_saver_video_path()
            if path:
                frames, interval_ms = load_screensaver_pixels(path)
        except Exception:
            logger.exception("Could not extract screensaver pixels")
            frames, interval_ms = [], 33
        try:
            self.saver_pixels_ready.emit(list(frames or []), int(interval_ms or 33))
        except Exception:
            logger.exception("Could not publish screensaver pixels")

    def _on_saver_pixels_ready(self, frames, interval_ms):
        self._saver_loading = False
        frames = list(frames or [])
        if not frames:
            return
        self._saver_jpegs = frames
        self._saver_interval_ms = max(16, int(interval_ms or 33))
        if getattr(self, "_screensaver_scale_screens", None):
            self._ensure_saver_timer()
            self._tick_coded_screensaver()

    def _ensure_saver_timer(self):
        if getattr(self, "_saver_timer", None) is not None:
            return
        interval = max(16, int(getattr(self, "_saver_interval_ms", 33) or 33))
        timer = QtCore.QTimer(self)
        timer.timeout.connect(self._tick_coded_screensaver)
        timer.start(interval)
        self._saver_timer = timer

    def _tick_coded_screensaver(self):
        screens = set(getattr(self, "_screensaver_scale_screens", None) or set())
        frames = list(getattr(self, "_saver_jpegs", None) or [])
        if not screens or not frames:
            if not screens:
                self._stop_coded_screensaver_timer()
            return
        index = int(getattr(self, "_saver_index", 0) or 0) % len(frames)
        self._saver_index = index + 1
        image = QtGui.QImage.fromData(frames[index])
        if image.isNull():
            return
        pix = QtGui.QPixmap.fromImage(image)
        self._saver_pix = pix
        pixmaps = dict(getattr(self, "_screen_pixmaps", None) or {})
        named = set()
        self._stamp_screensaver_pixels(pixmaps, named)
        self._screen_pixmaps = pixmaps
        self.active_screens = set(pixmaps) | set(getattr(self, "active_screens", None) or set())
        self.update()

    def _stop_bounce_motion(self):
        timer = getattr(self, "_bounce_timer", None)
        if timer is not None:
            try:
                timer.stop()
                timer.deleteLater()
            except Exception:
                pass
        self._bounce_timer = None
        self._bounce_fleet = None
        self._bounce_theme = None
        self._bounce_seed = None
        self._bounce_base_rgb = None
        self._bounce_screens = set()

    def start_bounce_motion(
        self,
        screen_ids,
        theme: str = "flowers",
        seed: int = 1,
        base_rgb=None,
        start_frame: int = 0,
        continue_prev: bool = False,
    ):
        """Live bouncing sprites. New seed → new start locations; or continue fleet."""
        theme = str(theme or "flowers").lower()
        seed = int(seed or 1)
        screens = {_sid(s) for s in (screen_ids or []) if _sid(s) and _sid(s) in SLICE_ORDER}
        if not screens:
            return
        # Stop clip decode on these fields only — never kill the other field's .ssav saver.
        replace = {_field_for_screen(name) for name in screens}
        self._release_field_videos(replace)
        logo_scale = set(getattr(self, "_logo_scale_screens", None) or set())
        for name in screens:
            logo_scale.discard(name)
        self._logo_scale_screens = logo_scale
        # Bounce owns these tiles; coded saver must not cover them.
        saver_scale = set(getattr(self, "_screensaver_scale_screens", None) or set())
        for name in screens:
            saver_scale.discard(name)
        self._screensaver_scale_screens = saver_scale
        # Full-bleed only on bounce tiles — never set global _video_fill (that
        # used to enlarge the free field's coded screensaver).
        fill = set(getattr(self, "_video_fill_screens", None) or set())
        fill |= set(screens)
        self._video_fill_screens = fill
        self._video_fill = False
        self._content_scale = 1.0
        self._summary_lines = []
        self._summary_screens = None
        self._summary_by_screen = {}
        self._bounce_screens = set(screens)
        self.active_screens = set(screens) | set(saver_scale)
        size = int(getattr(self, "_bounce_size", 512) or 512)
        keep = (
            continue_prev
            and self._bounce_fleet
            and self._bounce_theme == theme
            and getattr(self, "_bounce_timer", None) is not None
        )
        if keep:
            # Same theme: sprites keep flying from where the last action left them.
            self._bounce_seed = seed
            if base_rgb is not None:
                self._bounce_base_rgb = tuple(base_rgb)
        else:
            # Fresh spawn edges/locations for this action, then advance so they
            # are not always sitting on the same starting edge.
            self._bounce_theme = theme
            self._bounce_seed = seed
            self._bounce_base_rgb = tuple(base_rgb) if base_rgb is not None else None
            fleet = _flower_bounce_fleet(seed, size, size, kind=theme)
            steps = max(0, int(start_frame or 0)) + (abs(int(seed)) % 97)
            for _ in range(steps):
                _advance_flower_bounce(fleet, size, size)
            self._bounce_fleet = fleet
            if self._bounce_timer is not None:
                try:
                    self._bounce_timer.stop()
                    self._bounce_timer.deleteLater()
                except Exception:
                    pass
                self._bounce_timer = None
        self._tick_bounce_motion()
        if self._bounce_timer is None:
            interval = max(20, int(round(1000.0 / max(1, int(WORLD_S2_MOTION_FPS)))))
            self._bounce_timer = QtCore.QTimer(self)
            self._bounce_timer.timeout.connect(self._tick_bounce_motion)
            self._bounce_timer.start(interval)

    def _tick_bounce_motion(self):
        fleet = getattr(self, "_bounce_fleet", None)
        screens = getattr(self, "_bounce_screens", None) or set()
        if not fleet or not screens:
            return
        size = int(getattr(self, "_bounce_size", 512) or 512)
        theme = str(getattr(self, "_bounce_theme", None) or "flowers")
        seed = int(getattr(self, "_bounce_seed", None) or 1)
        base_rgb = getattr(self, "_bounce_base_rgb", None)
        arr, fleet = _compose_bouncing_flowers_rgb(
            size,
            size,
            seed,
            base_rgb=base_rgb,
            fleet=fleet,
            kind=theme,
        )
        self._bounce_fleet = fleet
        if arr is None:
            return
        try:
            import numpy as np
            rgb = np.ascontiguousarray(arr, dtype=np.uint8)
            h, w, _ = rgb.shape
            qimg = QtGui.QImage(rgb.data, w, h, 3 * w, QtGui.QImage.Format_RGB888).copy()
            pix = QtGui.QPixmap.fromImage(qimg)
        except Exception as exc:
            logger.warning("bounce motion frame failed: %s", exc)
            return
        if pix.isNull():
            return
        pixmaps = {name: pix for name in screens}
        self._video_frame = pix
        kept = _without_field_screens(getattr(self, "_screen_pixmaps", None) or {}, [
            _field_for_screen(name) for name in screens
        ])
        kept.update(pixmaps)
        # Re-stamp coded .ssav tiles on any free field after bounce redraw.
        named = set(kept)
        self._stamp_screensaver_pixels(kept, named)
        self._screen_pixmaps = kept
        self._video_screens = set(screens)
        self.active_screens = set(kept)
        self.update()

    def _tick_screen_video(self):
        groups = list(getattr(self, "_video_groups", None) or [])
        if not groups:
            return
        try:
            import cv2
            pixmaps = dict(getattr(self, "_still_pixmaps", None) or {})
            screens = set(pixmaps)
            kept = []
            for group in groups:
                cap = group["cap"]
                ok, frame = cap.read()
                if not ok or frame is None:
                    if group.get("full_band") or group.get("loop") is False:
                        # One-shot coach/clip finished — drop it so the logo
                        # layer underneath keeps painting on screens 3/4.
                        try:
                            cap.release()
                        except Exception:
                            pass
                        continue
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, frame = cap.read()
                if not ok or frame is None:
                    kept.append(group)
                    continue
                kept.append(group)
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
                    tile = pix
                    if group.get("full_band") and name in SLICE_ORDER and w > 0:
                        index = SLICE_ORDER.index(name)
                        x0, x1 = slice_x_span(index, w, len(SLICE_ORDER))
                        tile = pix.copy(int(x0), 0, max(1, int(x1) - int(x0)), h)
                    pixmaps[name] = tile
                    screens.add(name)
                    if group.get("full_band"):
                        band = set(getattr(self, "_band_screens", None) or set())
                        band.add(name)
                        self._band_screens = band
            self._video_groups = kept
            self._video_screens = {
                sid for group in kept for sid in (group.get("screens") or set())
            }
            if not kept:
                timer = getattr(self, "_video_timer", None)
                if timer is not None and not getattr(self, "_screensaver_scale_screens", None):
                    try:
                        timer.stop()
                    except Exception:
                        pass
            if not pixmaps and not getattr(self, "_saver_pix", None):
                return
            self._stamp_screensaver_pixels(pixmaps, screens)
            if not pixmaps:
                return
            self._video_frame = next(iter(pixmaps.values()))
            self._screen_pixmaps = pixmaps
            self._video_screens = set(screens) | set(self._video_screens or set())
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
        """Name, time, and action count, centered on every screen.

        When a summary logo is playing, draw it small above the text block.
        """
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
        logo_mode = bool(getattr(self, "_summary_logo", False))
        pixmaps = getattr(self, "_screen_pixmaps", None) or {}
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
            left, rect_w, _cx, cy = content_band_layout(
                index, name, self.width(), self.height(), len(SLICE_ORDER),
            )
            if rect_w < 8:
                continue
            rect = QtCore.QRect(left, 0, rect_w, self.height())
            painter.fillRect(rect, fill)
            painter.setClipRect(rect)
            lines = screen_lines
            font = QtGui.QFont("Segoe UI", 20, QtGui.QFont.Bold)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            longest = max(lines, key=len) if lines else ""
            while longest and metrics.width(longest) > rect_w - 12 and font.pointSize() > 8:
                font.setPointSize(font.pointSize() - 2)
                painter.setFont(font)
                metrics = painter.fontMetrics()
            spacing = max(1, metrics.lineSpacing())
            logo_pix = pixmaps.get(name) if logo_mode else None
            logo_bottom = cy
            if logo_pix is not None and not logo_pix.isNull():
                max_w = max(24, int(rect_w * OPENING_LOGO_MAX_WIDTH))
                max_h = max(24, int(self.height() * OPENING_LOGO_MAX_HEIGHT))
                scaled = logo_pix.scaled(
                    max_w,
                    max_h,
                    QtCore.Qt.KeepAspectRatio,
                    QtCore.Qt.SmoothTransformation,
                )
                logo_x = left + (rect_w - scaled.width()) // 2
                logo_y = cy - scaled.height() // 2
                painter.drawPixmap(logo_x, logo_y, scaled)
                logo_bottom = logo_y + scaled.height()
            if logo_mode and logo_pix is not None and not logo_pix.isNull():
                # Below the logo, then an extra downward shift, then one line up.
                first_top = (
                    logo_bottom
                    + OPENING_LOGO_TEXT_GAP_LINES * spacing
                    + int(round(self.height() * float(OPENING_LOGO_TEXT_DOWN_FRAC)))
                    - OPENING_LOGO_TEXT_LIFT_LINES * spacing
                )
            else:
                mid = len(lines) // 2
                first_top = cy - metrics.height() // 2 - mid * spacing
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

    def _paint_band_slice(self, painter, pix, name):
        """Put a results frame on the same slice the video was drawn for."""
        index = SLICE_ORDER.index(name)
        x0, x1 = slice_x_span(index, self.width(), len(SLICE_ORDER))
        dest = QtCore.QRect(int(x0), 0, max(1, int(x1) - int(x0)), max(1, self.height()))
        painter.setClipRect(dest)
        if pix is not None and not pix.isNull():
            scaled = pix.scaled(
                dest.width(),
                dest.height(),
                QtCore.Qt.IgnoreAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )
            painter.drawPixmap(dest.topLeft(), scaled)
        painter.setClipping(False)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0))
        summary_screens = set(getattr(self, "_summary_screens", None) or set())
        other_pix = {
            sid: pix
            for sid, pix in (getattr(self, "_screen_pixmaps", None) or {}).items()
            if _sid(sid) not in summary_screens
        }
        overlays = getattr(self, "_text_overlays", None) or {}
        image_overlays = getattr(self, "_image_overlays", None) or {}
        # Opening-card summary on one field must NEVER skip the other field's
        # action tiles (join-during-results used to leave that half black).
        if (
            self._summary_lines
            and not other_pix
            and not overlays
            and not image_overlays
            and not getattr(self, "_result_badges", None)
            and not (getattr(self, "_video_groups", None) or [])
            and not (getattr(self, "_pass_ssav_screens", None) or set())
        ):
            self._paint_level_summary(painter)
            painter.end()
            return
        if (
            not self._screen_pixmaps
            and not getattr(self, "_result_badges", None)
            and not overlays
            and not image_overlays
            and not self._summary_lines
            and not (getattr(self, "_video_groups", None) or [])
            and not (getattr(self, "_pass_ssav_screens", None) or set())
        ):
            painter.end()
            return
        band_screens = set(getattr(self, "_band_screens", None) or set())
        for sid, pix in self._screen_pixmaps.items():
            name = _sid(sid)
            if not name or name not in SLICE_ORDER:
                continue
            if summary_screens and name in summary_screens:
                continue
            if name in band_screens:
                self._paint_band_slice(painter, pix, name)
                continue
            index = SLICE_ORDER.index(name)
            left, _right, rect_w = content_x_box(index, name, self.width(), len(SLICE_ORDER))
            dy = screen_content_offset_y(name)
            placed = QtCore.QRect(left, 0, rect_w, self.height())
            painter.setClipRect(placed)
            if not pix.isNull():
                fill_screens = set(getattr(self, "_video_fill_screens", None) or set())
                logo_screens = set(getattr(self, "_logo_scale_screens", None) or set())
                saver_screens = set(getattr(self, "_screensaver_scale_screens", None) or set())
                controller = getattr(self, "_coded_players", None)
                player_scale = (
                    controller.scale_for(name) if controller is not None else None
                )
                # Coded .player keeps aspect ratio (siamak_files), like pass scale.
                if player_scale is not None:
                    painter.fillRect(placed, QtGui.QColor(0, 0, 0))
                    scaled = pix.scaled(
                        max(1, int(rect_w * float(player_scale))),
                        max(1, int(self.height() * float(player_scale))),
                        QtCore.Qt.KeepAspectRatio,
                        QtCore.Qt.SmoothTransformation,
                    )
                    px = left + (rect_w - scaled.width()) // 2
                    py = (self.height() - scaled.height()) // 2 + int(dy or 0)
                # Coded .ssav saver always keeps its own size — never follow action fill.
                elif name in saver_screens:
                    painter.fillRect(placed, QtGui.QColor(0, 0, 0))
                    draw_w = max(24, int(round(rect_w * float(SCREEN_SAVER_SCALE))))
                    draw_h = max(24, int(round(self.height() * float(SCREEN_SAVER_SCALE))))
                    scaled = pix.scaled(
                        draw_w,
                        draw_h,
                        QtCore.Qt.KeepAspectRatio,
                        QtCore.Qt.SmoothTransformation,
                    )
                    px = left + (rect_w - scaled.width()) // 2
                    py = (self.height() - scaled.height()) // 2 + int(dy or 0)
                elif name in logo_screens and not (name in fill_screens or self._video_fill):
                    # Results / opening logo — level brand fill only (not screensaver).
                    painter.fillRect(placed, self._field_level_qcolor(_field_for_screen(name)))
                    # Same box as the beginning-information logo.
                    draw_w = max(24, int(round(rect_w * float(OPENING_LOGO_MAX_WIDTH))))
                    draw_h = max(24, int(round(self.height() * float(OPENING_LOGO_MAX_HEIGHT))))
                    scaled = pix.scaled(
                        draw_w,
                        draw_h,
                        QtCore.Qt.KeepAspectRatio,
                        QtCore.Qt.SmoothTransformation,
                    )
                    cy = content_band_center_y(name, self.height())
                    px = left + (rect_w - scaled.width()) // 2
                    py = cy - scaled.height() // 2
                else:
                    fill = name in fill_screens or self._video_fill
                    scale = 1.0 if fill else float(self._content_scale or 1.0)
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
        if image_overlays:
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            for name, over in image_overlays.items():
                if not name or name not in SLICE_ORDER or over is None or over.isNull():
                    continue
                index = SLICE_ORDER.index(name)
                left, _right, rect_w = content_x_box(index, name, self.width(), len(SLICE_ORDER))
                placed = QtCore.QRect(left, 0, rect_w, self.height())
                painter.setClipRect(placed)
                scaled = over.scaled(
                    rect_w,
                    self.height(),
                    QtCore.Qt.KeepAspectRatio,
                    QtCore.Qt.SmoothTransformation,
                )
                px = left + (rect_w - scaled.width()) // 2
                py = (self.height() - scaled.height()) // 2 + int(screen_content_offset_y(name) or 0)
                painter.drawPixmap(px, py, scaled)
                painter.setClipping(False)
        if overlays:
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            painter.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
            color = getattr(self, "_text_overlay_color", (245, 240, 220)) or (245, 240, 220)
            painter.setPen(QtGui.QColor(int(color[0]), int(color[1]), int(color[2])))
            font = QtGui.QFont("Segoe UI", 50, QtGui.QFont.Bold)
            painter.setFont(font)
            positions = getattr(self, "_text_overlay_positions", None) or {}
            for name, text in overlays.items():
                if not name or name not in SLICE_ORDER:
                    continue
                index = SLICE_ORDER.index(name)
                left, _right, rect_w = content_x_box(index, name, self.width(), len(SLICE_ORDER))
                placed = QtCore.QRect(left, 0, rect_w, self.height())
                painter.setClipRect(placed)
                metrics = painter.fontMetrics()
                while metrics.width(str(text)) > rect_w - 12 and font.pointSize() > 18:
                    font.setPointSize(font.pointSize() - 2)
                    painter.setFont(font)
                    metrics = painter.fontMetrics()
                pos = positions.get(name)
                if pos and len(pos) >= 2:
                    fx = min(0.92, max(0.08, float(pos[0])))
                    fy = min(1.0 - WC_TEXT_EDGE_MARGIN, max(WC_TEXT_EDGE_MARGIN, float(pos[1])))
                    cx = left + int(round(fx * rect_w))
                    cy = int(round(fy * self.height())) + int(screen_content_offset_y(name) or 0)
                    line = QtCore.QRect(
                        cx - metrics.width(str(text)) // 2,
                        cy - metrics.height() // 2,
                        max(metrics.width(str(text)), 8),
                        metrics.height(),
                    )
                    painter.drawText(line, QtCore.Qt.AlignCenter, str(text))
                else:
                    cy = _ring_value_center_y(self.height()) + int(screen_content_offset_y(name) or 0)
                    line = QtCore.QRect(left, cy - metrics.height() // 2, rect_w, metrics.height())
                    painter.drawText(line, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter, str(text))
                painter.setClipping(False)
        if self._summary_lines:
            self._paint_level_summary(painter)
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
        self.balls_by_slice = None
        self.level_colors = {}
        # Set before set_active_fields. That call reads this flag.
        self.punch_inactive = False
        self.set_active_fields(active_fields)

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
        if getattr(self, "punch_inactive", False):
            self._apply_field_mask()
        self.update()

    def set_punch_inactive(self, enabled):
        """Cover only the finished field so the other field stays visible."""
        self.punch_inactive = bool(enabled)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, bool(enabled))
        self.setAutoFillBackground(not enabled)
        self._apply_field_mask()
        self.update()

    def _apply_field_mask(self):
        if not self.punch_inactive:
            self.clearMask()
            return
        w = max(1, self.width())
        h = max(1, self.height())
        region = QtGui.QRegion()
        count = len(self.slice_order)
        for i, slice_num in enumerate(self.slice_order):
            if slice_num not in self.active_slice_nums:
                continue
            x0, x1 = content_band_mask_span(i, slice_num, w, h, count)
            region = region.united(QtGui.QRegion(int(x0), 0, max(1, int(x1) - int(x0)), h))
        self.setMask(region)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "punch_inactive", False):
            self._apply_field_mask()

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
        """Same calibrated rectangle as beginning information / results."""
        left, rect_w, _cx, _cy = content_band_layout(
            index, slice_num, self.width(), self.height(), self.num_slices,
        )
        return QtCore.QRect(int(left), 0, int(rect_w), max(1, self.height()))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return
        if not self.punch_inactive:
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
            _left, _rw, cx, cy = content_band_layout(
                i, slice_num, self.width(), h, self.num_slices,
            )

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

            # Text inside the ring — one fact per line (Elite / T1 / A-T1 / …)
            if self.status_text:
                lines = [ln for ln in self.status_text.split("\n") if str(ln).strip()]
            else:
                lines = ["Processing", "Results"]
            if not lines:
                lines = ["Processing"]

            fid = "B" if str(slice_num).startswith("B") else "A"
            painter.setPen(self._level_qcolor(fid, "fg"))
            point = 11 if len(lines) >= 4 else (12 if len(lines) > 1 else 14)
            font = QFont("Segoe UI", point, QFont.Bold)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            spacing = max(1, metrics.lineSpacing())
            total_h = spacing * len(lines)
            y0 = cy - total_h // 2 + metrics.ascent()
            for i, line in enumerate(lines):
                tw = metrics.width(line)
                painter.drawText(cx - tw // 2, y0 + i * spacing, line)

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


class ResultsOverlay(QtWidgets.QWidget):
    """Paint result rings and numbers on the field screens. No results video."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.panels = {}
        self.specs = {}
        self.level_colors = {}
        self.slice_order = list(DISPLAY_SLICE_ORDER)
        self.active_slice_nums = set()
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(QtCore.Qt.NoFocus)

    def set_level_colors(self, colors):
        """Background fill per field — same brand color as the opening card."""
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

    def _level_bg(self, fid):
        pair = (self.level_colors or {}).get(fid)
        if not pair:
            return QColor(10, 12, 18)
        rgb = pair[0]
        return QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]))

    def _level_fg(self, fid):
        """Opening-card text color when readable on the brand fill; else black/white."""
        pair = (self.level_colors or {}).get(fid)
        if not pair:
            return QColor(255, 255, 255)
        bg = tuple(int(v) for v in pair[0][:3])
        fg = tuple(int(v) for v in pair[1][:3])
        if _colors_are_visible(fg, bg):
            return QColor(fg[0], fg[1], fg[2])
        # Fallback: pick black or white for contrast on light/dark brand fills.
        try:
            if _contrast_ratio((20, 24, 32), bg) >= _contrast_ratio((255, 255, 255), bg):
                return QColor(20, 24, 32)
        except Exception:
            pass
        return QColor(255, 255, 255)

    def set_panels(self, panels):
        cleaned = {}
        specs = {}
        for fid, panel in (panels or {}).items():
            key = str(fid or "").upper()[:1]
            if key not in ("A", "B") or not isinstance(panel, dict):
                continue
            cleaned[key] = panel
            specs.update(_result_ring_specs(panel))
        self.panels = cleaned
        self.specs = specs
        self.active_slice_nums = set()
        for fid in cleaned:
            for name in _field_all_screens(fid):
                # Screens 3 and 4 play the logo and coach video under this overlay.
                if str(name)[-1:] in ("3", "4"):
                    continue
                self.active_slice_nums.add(name)
        self._apply_field_mask()
        self.update()

    def _apply_field_mask(self):
        """Same mask span as Field B processing — covers offset overflow (A5→A4)."""
        w = max(1, self.width())
        h = max(1, self.height())
        region = QtGui.QRegion()
        count = len(self.slice_order)
        for i, slice_num in enumerate(self.slice_order):
            if slice_num not in self.active_slice_nums:
                continue
            x0, x1 = content_band_mask_span(i, slice_num, w, h, count)
            region = region.united(QtGui.QRegion(int(x0), 0, max(1, int(x1) - int(x0)), h))
        if region.isEmpty():
            self.clearMask()
        else:
            self.setMask(region)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_field_mask()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return
        for i, slice_num in enumerate(self.slice_order):
            if slice_num is None or slice_num not in self.active_slice_nums:
                continue
            # Same content_band_layout + radius rule as WaitingOverlay (Field B).
            left, rect_w, cx, cy = content_band_layout(
                i, slice_num, w, h, len(self.slice_order),
            )
            rect = QtCore.QRect(int(left), 0, int(rect_w), h)
            painter.setClipRect(rect)
            painter.fillRect(rect, self._level_bg(_field_for_screen(slice_num)))
            spec = self.specs.get(slice_num)
            if spec:
                radius = min(RING_RADIUS, max(5, rect.width() // 2 - 4))
                if radius < 5:
                    radius = 5
                painter.setPen(QPen(QColor(60, 60, 80), RING_THICKNESS))
                painter.drawEllipse(cx - radius, cy - radius, 2 * radius, 2 * radius)
                percent = float(spec.get("percent") or 0)
                if percent > 0:
                    painter.setPen(QPen(QColor(255, 193, 7), RING_THICKNESS))
                    painter.drawArc(
                        cx - radius,
                        cy - radius,
                        2 * radius,
                        2 * radius,
                        90 * 16,
                        int(round(-360.0 * (percent / 100.0) * 16)),
                    )
                lines = list(spec.get("lines") or ["-"])
                text_color = self._level_fg(_field_for_screen(slice_num))
                painter.setPen(text_color)
                point = 12 if len(lines) > 1 else 16
                font = QFont("Segoe UI", point, QFont.Bold)
                painter.setFont(font)
                metrics = painter.fontMetrics()
                spacing = max(1, metrics.lineSpacing())
                total_h = spacing * len(lines)
                y0 = cy - total_h // 2 + metrics.ascent()
                for n, line in enumerate(lines):
                    tw = metrics.width(str(line))
                    painter.drawText(cx - tw // 2, y0 + n * spacing, str(line))
                label = str(spec.get("label") or "")
                if label:
                    painter.setPen(text_color)
                    painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
                    label_metrics = painter.fontMetrics()
                    ly = cy + radius + 28
                    painter.drawText(
                        cx - label_metrics.width(label) // 2,
                        ly,
                        label,
                    )
            painter.setClipping(False)


# ============================================================
# SMART PLAYER MAIN WINDOW
# ============================================================
class SmartPlayerWindow(QtWidgets.QMainWindow):
    # Signals emit the video path (or empty string on failure)
    final_summary_done = pyqtSignal(str)
    per_video_results_ready = pyqtSignal(str)
    field_results_ready = pyqtSignal(str, str)
    independent_close_ready = pyqtSignal(str)

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
        self._pause_perf_started_at = 0
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
        self._pass_shown_at = None
        self._pass_on_ms = 0
        self._budget_started_at = None
        self._budget_test = None
        self._gap_result_timer = None
        self._goal_advance_timer = None
        self._next_hint_show_timer = None
        self._next_hint_clear_timer = None
        self._next_hint_screens = set()
        self._next_hint_pending = None
        self._phase_active = None
        self._run_phases = []
        self._phase_index = 0
        self._level_root = video_directory
        self._idle_screensaver_mode = (
            str(video_directory or "").strip().lower() in (
                IDLE_SCREENSAVER_ARG,
                "--screensaver",
                "screensaver",
            )
        )
        self.video_files = []

        # Waiting overlay (initially None)
        self.waiting_overlay = None

        self.final_summary_done.connect(self._on_final_summary_done)
        self.per_video_results_ready.connect(self._on_per_video_results_ready)
        self.field_results_ready.connect(self._on_field_results_ready)
        self.independent_close_ready.connect(self._on_independent_close_ready)

        # Speed / control files (needed before building image playlist)
        self.speed_file_dir = "C:/Users/siama/Documents/simust_player"
        self.speed_file_path = os.path.join(self.speed_file_dir, "simust_speed.txt")
        self.pause_file_path = os.path.join(self.speed_file_dir, "pause.txt")
        self.video_index_file = os.path.join(self.speed_file_dir, "current_video_index.txt")
        self._screensaver_fields = set()
        self._screensaver_hold_until = {}
        self._coach_audio_field = None
        self._cabinet_controls = {"system_on": True, "screensaver_on": False}
        try:
            os.makedirs(self.speed_file_dir, exist_ok=True)
            with open(self.speed_file_path, 'w') as f:
                f.write(str(self.player_speed))
        except:
            pass
        self._screensaver_timer = QtCore.QTimer(self)
        self._screensaver_timer.timeout.connect(self._on_cabinet_idle_tick)
        self._screensaver_timer.start(250)
        self._cue_heartbeat_at = 0.0

        # Field A and Field B run as separate phases (own playlist, tests, conclusion)
        if self._idle_screensaver_mode:
            self._run_phases = []
            self._phase_index = 0
            self._phase_active = []
            self._field_opening_playlists = {}
            self._fields_opening = set()
            self.display_phase = "idle"
            self._realtime_stopped = True  # no camera session behind idle saver
            logger.info("Idle screensaver mode — coded saver on all screens")
        else:
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

        if self._idle_screensaver_mode:
            # No level playlist — show the coded saver immediately if Switch is on.
            self.speed_monitor_timer.start()
            self._update_status_file("idle", 0, 0, "Screensaver idle")
            # Force the same Screen-2 coach-band layout as waiting / actions.
            for delay in (20, 60, 120, 250, 400, 600):
                QtCore.QTimer.singleShot(delay, self._force_top_512)
            QtCore.QTimer.singleShot(300, self._sync_screensaver)
        else:
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
        # Keep the projector window alive for the coded screensaver when Switch is on.
        controls = _read_cabinet_controls(self._player_attr("speed_file_dir"))
        if bool(controls.get("system_on", True)) and bool(controls.get("screensaver_on", False)):
            logger.info("Series done — staying open for coded screensaver")
            self._enter_idle_screensaver()
            return
        if self.close_timer:
            self.close_timer.stop()
        self.close_timer = QtCore.QTimer(singleShot=True)
        self.close_timer.timeout.connect(self.close)
        self.close_timer.start(delay_ms)

    def _enter_idle_screensaver(self):
        """Clear session state and loop the coded saver on every screen."""
        self._idle_screensaver_mode = True
        self.display_phase = "idle"
        self.playlist_finished = False
        self._status_completed = False
        self._screensaver_hold_until = {}
        self._field_opening_playlists = {}
        self._independent_index = {}
        self._independent_done = {}
        self._field_final_queued = {}
        self._field_final_done = {}
        self._field_result_state = {}
        self._phase_active = []
        self._fields_opening = set()
        self.video_files = []
        try:
            self._hide_projected_results()
        except Exception:
            pass
        for fid in ("A", "B"):
            try:
                self._hide_field_result_rings(fid)
            except Exception:
                pass
        if self.close_timer:
            try:
                self.close_timer.stop()
            except Exception:
                pass
            self.close_timer = None
        self._flash_idle_display(then_screensaver=True)

    def _update_status_file(self, state, current_video, total_videos, message):
        try:
            status_data = {}
            if os.path.isfile(self.status_file):
                try:
                    with open(self.status_file, "r", encoding="utf-8") as handle:
                        loaded = json.load(handle)
                    if isinstance(loaded, dict):
                        status_data = loaded
                except Exception:
                    status_data = {}
            status_data.update({
                "state": state,
                "current_video": current_video,
                "total_videos": total_videos,
                "progress": (current_video / total_videos * 100) if total_videos > 0 else 0,
                "message": message,
                "timestamp": time.time(),
            })
            with open(self.status_file, "w", encoding="utf-8") as handle:
                json.dump(status_data, handle)
        except Exception:
            pass

    def _control_fields_playing(self):
        """Fields whose Stop button should stay down. A finished series releases it."""
        if self._player_attr("playlist_finished", False):
            return []
        phase = str(self._player_attr("display_phase") or "")
        # Cabinet final / post-series: Stop must release even if phase_active is stale.
        if phase in ("wait_final", "final", "idle", "ready", "completed", "closed"):
            return []
        parts = getattr(self, "_field_opening_playlists", None) or {}
        if parts:
            playing = []
            for fid, rows in parts.items():
                key = str(fid).upper()[:1]
                if rows and not self._field_series_finished(key):
                    playing.append(key)
            return playing
        return [
            str(fid).upper()[:1]
            for fid in (getattr(self, "_phase_active", None) or [])
            if str(fid).upper()[:1] in ("A", "B")
        ]

    def _publish_field_controls(self):
        """Tell the operator page which fields are still playing."""
        try:
            playing = set(self._control_fields_playing())
            current = {}
            if os.path.isfile(self.status_file):
                try:
                    with open(self.status_file, "r", encoding="utf-8") as handle:
                        loaded = json.load(handle)
                    if isinstance(loaded, dict):
                        current = loaded
                except Exception:
                    current = {}
            current["fields"] = {
                "A": "playing" if "A" in playing else "idle",
                "B": "playing" if "B" in playing else "idle",
            }
            current["timestamp"] = time.time()
            with open(self.status_file, "w", encoding="utf-8") as handle:
                json.dump(current, handle)
        except Exception:
            pass

    def _player_attr(self, name, default=None):
        try:
            return object.__getattribute__(self, name)
        except Exception:
            return default

    def _field_epoch(self, fid):
        fid = str(fid or "").upper()[:1]
        try:
            return int((self._player_attr("_field_epochs") or {}).get(fid) or 0)
        except (TypeError, ValueError):
            return 0

    def _bump_field_epoch(self, fid):
        """Invalidate timers from this field's previous start or stop."""
        fid = str(fid or "").upper()[:1]
        epochs = dict(self._player_attr("_field_epochs") or {})
        epochs[fid] = self._field_epoch(fid) + 1
        self._field_epochs = epochs
        return epochs[fid]

    def _field_epoch_current(self, fid, epoch):
        if epoch is None:
            return True
        try:
            return int(epoch) == self._field_epoch(fid)
        except (TypeError, ValueError):
            return False

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
            # Combined band always drives both halves (all 12 screens).
            self._phase_active = ["A", "B"]
            _band, series_num = decision[1], decision[2]
            series_group = int(decision[3]) if len(decision) > 3 else 1
            if series_group == 2:
                playlist = (
                    _build_world_class_s2_playlist(series_num)
                    if _band == "world-class"
                    else _build_elite_s2_playlist(series_num)
                )
            else:
                playlist = _build_elite_playlist(series_num, _band)
            if playlist:
                self._label_mode = True
                logger.info(
                    "%s S%s.T%s playlist: %s tests x %s actions, on=%sms gap=%sms",
                    "World Class" if _band == "world-class" else "Elite",
                    series_group,
                    series_num,
                    ENTRY_TEST_COUNT,
                    ELITE_ACTIONS_PER_TEST,
                    playlist[0].get("on_ms"),
                    playlist[0].get("gap_ms"),
                )
                return playlist
            logger.error("%s S%s.T%s playlist empty", _band, series_group, series_num)
            self._label_mode = False
            return []

        if not getattr(self, "_one_field_build", False) and len(active) >= 2:
            parts = {}
            for fid in ("A", "B"):
                if fid not in active:
                    continue
                parts[fid] = self._build_one_field_playlist(fid)
            self._field_opening_playlists = parts
            self._independent_index = {fid: 0 for fid in parts}
            self._independent_done = {fid: False for fid in parts}
            self._field_result_state = {}
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
        hp_s2_num = _high_performance_s2_series_num(*level_bits)
        if hp_s2_num:
            playlist = _build_high_performance_s2_playlist(hp_s2_num, active)
            if playlist:
                self._label_mode = True
                logger.info(
                    "High Performance S2.T%s playlist: %s tests x %s actions, on=%sms gap=%sms",
                    hp_s2_num,
                    ENTRY_TEST_COUNT,
                    ENTRY_ACTIONS_PER_TEST,
                    playlist[0].get("on_ms"),
                    playlist[0].get("gap_ms"),
                )
                return playlist
            logger.error("High Performance S2.T%s playlist empty", hp_s2_num)
            self._label_mode = False
            return []

        hp_num = _high_performance_series_num(*level_bits)
        if hp_num:
            playlist = _build_high_performance_playlist(hp_num, active)
            if playlist:
                self._label_mode = True
                logger.info(
                    "High Performance S1.T%s playlist: %s tests x %s actions, on=%sms gap=%sms",
                    hp_num,
                    ENTRY_TEST_COUNT,
                    ENTRY_ACTIONS_PER_TEST,
                    playlist[0].get("on_ms"),
                    playlist[0].get("gap_ms"),
                )
                return playlist
            logger.error("High Performance S1.T%s playlist empty", hp_num)
            self._label_mode = False
            return []

        activated_a1_num = _activated_a1_series_num(*level_bits)
        if activated_a1_num:
            playlist = _build_activated_a1_playlist(activated_a1_num, active)
            if playlist:
                self._label_mode = True
                logger.info(
                    "Activated A1.T%s playlist: %s tests x %s actions, on=%sms gap=%sms",
                    activated_a1_num,
                    ENTRY_TEST_COUNT,
                    ENTRY_ACTIONS_PER_TEST,
                    playlist[0].get("on_ms"),
                    playlist[0].get("gap_ms"),
                )
                return playlist
            logger.error("Activated A1.T%s playlist empty", activated_a1_num)
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
            playlist = _build_omid_playlist(
                active, directory=self.video_directory,
            )
            if playlist:
                logger.info(
                    "Foundation omid playlist (same as SF-30N + coded .ssav): "
                    "%s steps, on=%sms gap=%sms from %s",
                    len(playlist),
                    playlist[0].get("on_ms"),
                    playlist[0].get("gap_ms"),
                    self.video_directory,
                )
                return playlist
            logger.error(
                "Omid playlist empty under %s (need pass_pixels.ssav or pass.mp4)",
                self.video_directory,
            )
            self._label_mode = False
            return []

        if extra_mode == "omid_2":
            self._label_mode = True
            playlist = _build_omid_2_playlist(
                active, directory=self.video_directory,
            )
            if playlist:
                logger.info(
                    "Foundation omid_2 playlist (SF-30N + coded .player): "
                    "%s steps, on=%sms gap=%sms from %s",
                    len(playlist),
                    playlist[0].get("on_ms"),
                    playlist[0].get("gap_ms"),
                    playlist[0].get("screen_player") or self.video_directory,
                )
                return playlist
            logger.error(
                "Omid_2 playlist empty under %s "
                "(need teammate_asking.player in omid_2 or static/players)",
                self.video_directory,
            )
            self._label_mode = False
            return []

        # ---- Foundation digit / rotation ----
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
            key = _level_intro_key_from_id(level)
            # Foundation beginning-info already loops logo_video_foundation.mp4.
            # Playing static/foundation.mp4 next was a second, darker logo on top.
            if key == "foundation":
                return None
            hit = _intro_video_for_key(key)
            if hit:
                return hit
            # This field has its own level. Do not borrow the other field's intro.
            return None
        directory = str((getattr(self, "_phase_field_directories", None) or {}).get(fid) or "").strip()
        if directory:
            for pat, key in _LEVEL_INTRO_PATH_RULES:
                if pat.search(directory):
                    if key == "foundation":
                        return None
                    hit = _intro_video_for_key(key)
                    if hit:
                        return hit
        root = directory or self.video_directory or self._level_root
        if _detect_level_intro_key(root) == "foundation":
            return None
        return _find_level_intro_video(root)

    def _opening_logo_context(self) -> str:
        levels = getattr(self, "_phase_field_levels", None) or {}
        dirs = getattr(self, "_phase_field_directories", None) or {}
        bits = [
            str(getattr(self, "_phase_mode_id", "") or ""),
            str(getattr(self, "_phase_subdirectory", "") or ""),
            str(getattr(self, "video_directory", "") or ""),
            str(getattr(self, "_level_root", "") or ""),
        ]
        bits.extend(str(v or "") for v in levels.values())
        bits.extend(str(v or "") for v in dirs.values())
        return " ".join(bits)

    def _stop_results_playback(self):
        """Drop the previous results clip before the next opening card."""
        if self.results_timer:
            self.results_timer.stop()
            self.results_timer = None
        try:
            self.player.stop()
            empty = self.instance.media_new("")
            self.player.set_media(empty)
        except Exception:
            pass
        if self.videoframe:
            self.videoframe.hide()

    def _begin_level_intro(self, next_index=0):
        """Every test: opening card with logo, then the starting video, then the test."""
        next_index = int(next_index)
        self._results_epoch = int(getattr(self, "_results_epoch", 0) or 0) + 1
        self._stop_results_playback()
        self._clear_held_results()
        self._show_level_card(next_index, after="intro")

    def _show_level_card(self, next_index, after="intro"):
        self._level_card_shown_for = int(next_index)
        files = self.video_files or []
        entry = files[next_index] if 0 <= next_index < len(files) and isinstance(files[next_index], dict) else {}
        levels = getattr(self, "_phase_field_levels", None) or {}
        modes = getattr(self, "_phase_field_modes", None) or {}
        level_id = ""
        subdirectory = str(getattr(self, "_phase_subdirectory", "") or "")
        active_fields = list(self._active_fields())
        # Only clear saver on fields that are opening — free field keeps its saver.
        for fid in active_fields:
            try:
                self._stop_field_screensaver(fid)
            except Exception:
                pass
        try:
            self._sync_screensaver()
        except Exception:
            pass
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
        logo_video = _opening_logo_video_for_level(color_context)
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
                logos = {
                    path for path in (
                        (field_cards.get(fid) or {}).get("logo") for fid in active_fields
                    ) if path
                }
                logo_video = next(iter(logos), logo_video) if logos else logo_video
            else:
                self.image_canvas.set_level_summary(
                    text.split("\n"), screens, background, foreground,
                    logo_video=logo_video,
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
        after = str(after or "intro").lower()
        if after == "start":
            self.play_delay_timer.timeout.connect(self._after_level_intro)
        else:
            self.play_delay_timer.timeout.connect(
                lambda idx=next_index: self._play_level_intro(idx, after="start")
            )
        self.play_delay_timer.start(LEVEL_CARD_MS)

    def _play_level_intro(self, next_index=0, after="start"):
        """Play the level clip on every screen of each active field before a test."""
        if self.level_card_label:
            self.level_card_label.hide()
        self._level_intro_next_index = int(next_index)
        self._level_intro_shown_for = int(next_index)
        self._hide_waiting_overlay()
        active = self._active_fields()
        # Hold/stop saver only on fields that are starting — free field keeps looping.
        hold = dict(getattr(self, "_screensaver_hold_until", None) or {})
        until = time.time() + 30.0
        for fid in active:
            key = str(fid).upper()[:1]
            if key not in ("A", "B"):
                continue
            hold[key] = until
            try:
                self._stop_field_screensaver(key)
            except Exception:
                pass
        # Drop stale holds on fields that are not starting so their saver can continue.
        for key in ("A", "B"):
            if key not in {str(f).upper()[:1] for f in active}:
                hold.pop(key, None)
        self._screensaver_hold_until = hold
        self.display_phase = "level_intro"
        try:
            self._sync_screensaver()
        except Exception:
            pass
        screen_to_video = {}
        by_field = {}
        for fid in active:
            intro = self._intro_video_for_field(fid)
            by_field[fid] = intro
            if not intro:
                continue
            for sid in _field_all_screens(fid):
                screen_to_video[sid] = intro
        after = str(after or "start").lower()
        if not screen_to_video:
            logger.warning(
                "No level intro video found for fields %s — continuing without clip",
                active,
            )
            if after == "card":
                self._show_level_card(next_index, after="start")
            else:
                self._after_level_intro()
            return

        names = {
            fid: (os.path.basename(path) if path else "missing")
            for fid, path in by_field.items()
        }
        intro_ms = max(
            (_video_duration_ms(path) for path in set(screen_to_video.values())),
            default=LEVEL_INTRO_MS,
        ) + int(LEVEL_INTRO_HOLD_MS)
        self._update_status_file(
            "starting",
            max(0, self._current_test_num() - 1),
            self.total_videos,
            "Level intro: " + ", ".join(f"{fid}={name}" for fid, name in names.items()),
        )
        logger.info(
            "Level intro %sms on fields %s screens %s clips %s (then %s, index %s)",
            intro_ms, active, sorted(screen_to_video), names, after, next_index,
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
            self.image_canvas.set_screen_videos(screen_to_video, fill=True, loop=False)
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
            if after == "card":
                self._show_level_card(next_index, after="start")
            else:
                self._after_level_intro()
            return

        if self.play_delay_timer:
            self.play_delay_timer.stop()
        self.play_delay_timer = QtCore.QTimer(singleShot=True)
        if after == "card":
            self.play_delay_timer.timeout.connect(
                lambda idx=next_index: self._show_level_card(idx, after="start")
            )
        else:
            self.play_delay_timer.timeout.connect(self._after_level_intro)
        self.play_delay_timer.start(intro_ms)

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
        # Hold saver only on fields that just finished starting video.
        # Never canvas.clear() — that kills the free field's coded screensaver.
        hold = dict(getattr(self, "_screensaver_hold_until", None) or {})
        until = time.time() + 8.0
        starting = {str(f).upper()[:1] for f in self._active_fields() if str(f).upper()[:1] in ("A", "B")}
        for key in starting:
            try:
                hold[key] = max(float(hold.get(key) or 0), until)
            except (TypeError, ValueError):
                hold[key] = until
            try:
                self._stop_field_screensaver(key)
            except Exception:
                pass
        for key in ("A", "B"):
            if key not in starting:
                hold.pop(key, None)
        self._screensaver_hold_until = hold
        canvas = getattr(self, "image_canvas", None)
        if canvas is not None:
            try:
                # Clear only the starting field(s); keep the free field's saver tiles.
                if hasattr(canvas, "_release_field_videos"):
                    canvas._release_field_videos(starting)
                canvas.set_screen_images({}, keep_videos=True, replace_fields=starting)
            except Exception:
                logger.exception("Could not clear starting field after level intro")
        self._clear_held_results()
        self._prestart_done = True
        self.is_first_video = False
        self._hide_waiting_overlay()
        idx = int(getattr(self, "_level_intro_next_index", 0) or 0)
        self.display_phase = "action"
        if canvas is not None:
            canvas.show()
            canvas.raise_()
        self._load_video(idx)
        try:
            self._sync_screensaver()
        except Exception:
            pass

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

    def _cancel_next_screen_hint(self, clear_paint=True):
        """Stop SF next-screen awareness timers (and optionally remove the glyph)."""
        for attr in ("_next_hint_show_timer", "_next_hint_clear_timer"):
            timer = getattr(self, attr, None)
            if timer is None:
                continue
            try:
                timer.stop()
            except Exception:
                pass
            setattr(self, attr, None)
        self._next_hint_pending = None
        if clear_paint:
            self._clear_next_screen_hint_paint()

    def _clear_next_screen_hint_paint(self):
        """Remove only the awareness overlays; leave the current pass image alone."""
        screens = set(getattr(self, "_next_hint_screens", None) or set())
        self._next_hint_screens = set()
        canvas = getattr(self, "image_canvas", None)
        if not screens or canvas is None:
            return
        overlays = dict(getattr(canvas, "_image_overlays", None) or {})
        changed = False
        for sid in screens:
            name = _sid(sid)
            if name and name in overlays:
                overlays.pop(name, None)
                changed = True
        if changed:
            canvas._image_overlays = overlays
            canvas.update()

    def _schedule_next_screen_hint(self, entry):
        """1s after pass ON → flash number/letter on next screen for 1s (SF-*N only)."""
        self._cancel_next_screen_hint()
        if not isinstance(entry, dict) or not entry.get("next_screen_hint"):
            return
        if not getattr(self, "image_canvas", None):
            return
        field_screens, arena = _next_sf_hint_targets(
            self.video_files,
            self.current_video_index,
            self._active_fields(),
        )
        if not field_screens:
            return
        screens = []
        for sids in field_screens.values():
            screens.extend(sids)
        screens = [s for s in screens if s]
        if not screens:
            return
        self._next_hint_pending = {"screens": screens, "arena": arena}
        show = QtCore.QTimer(singleShot=True)
        show.setTimerType(QtCore.Qt.PreciseTimer)
        show.timeout.connect(self._show_next_screen_hint)
        show.start(SF_NEXT_HINT_DELAY_MS)
        self._next_hint_show_timer = show
        logger.info(
            "Next-screen hint armed for %s in %sms (hold %sms)",
            screens,
            SF_NEXT_HINT_DELAY_MS,
            SF_NEXT_HINT_HOLD_MS,
        )

    def _show_next_screen_hint(self):
        if self.display_phase != "action" or self._action_phase != "label":
            return
        if self.operator_paused:
            QTimer.singleShot(200, self._show_next_screen_hint)
            return
        pending = getattr(self, "_next_hint_pending", None) or {}
        self._next_hint_pending = None
        self._next_hint_show_timer = None
        screens = list(pending.get("screens") or [])
        if not screens or not self.image_canvas:
            return
        glyph = _sf_next_hint_glyph(pending.get("arena"))
        png = _render_entry_digit_image(glyph)
        if not png:
            return
        overlays = dict(getattr(self.image_canvas, "_image_overlays", None) or {})
        shown = []
        for sid in screens:
            name = _sid(sid)
            pix = self.image_canvas._load_pixmap(png) if name else None
            if name and pix is not None and not pix.isNull():
                overlays[name] = pix
                shown.append(name)
        if not shown:
            return
        self._next_hint_screens = set(shown)
        self.image_canvas._image_overlays = overlays
        self.image_canvas.update()
        clear = QtCore.QTimer(singleShot=True)
        clear.setTimerType(QtCore.Qt.PreciseTimer)
        clear.timeout.connect(self._clear_next_screen_hint_paint)
        clear.start(SF_NEXT_HINT_HOLD_MS)
        self._next_hint_clear_timer = clear
        logger.info("Next-screen hint %r on %s for %sms", glyph, shown, SF_NEXT_HINT_HOLD_MS)

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
        self._cancel_next_screen_hint()
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
        if getattr(self, "_budget_test", None) != test_num or not getattr(self, "_budget_started_at", None):
            self._budget_started_at = time.perf_counter()
            self._budget_test = test_num
            self._budget_closed_test = None
        elapsed = (time.perf_counter() - float(self._budget_started_at)) * 1000.0
        return int(round(budget - elapsed))

    def _label_action_delay_ms(self, entry) -> int:
        """How long this action stays up. 0 means a shared clock is already finished.

        Independent fields each keep their own On time. The longer test's clock
        must not be the hold for one shot: that shot would use the whole clock,
        and the next step would end both fields.
        """
        if isinstance(entry, dict) and entry.get("independent_fields"):
            return self._flash_delay_ms(on=True)
        if isinstance(entry, dict) and entry.get("budget_ms"):
            delay = self._budget_remaining_ms(entry)
            if delay <= 40:
                return 0
            return delay
        return self._flash_delay_ms(on=True)

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
        self._goal_advance_timer.setTimerType(QtCore.Qt.PreciseTimer)
        self._goal_advance_timer.timeout.connect(self._poll_goal_advance)
        # Poll as fast as the UI loop allows; camera lag is the remaining delay.
        self._goal_advance_timer.start(8)

    def _poll_goal_advance(self):
        if self.operator_paused:
            return
        if self.display_phase != "action" or self._player_attr("_label_phase", "") != "action":
            return
        if self._player_attr("_goal_arrived", False):
            return
        files = self.video_files or []
        idx = int(self._player_attr("current_video_index", 0) or 0)
        entry = files[idx] if 0 <= idx < len(files) and isinstance(files[idx], dict) else {}
        if not entry.get("advance_on_goal"):
            self._stop_goal_advance_poll()
            return
        try:
            shared_seq = int(self._player_attr("_flash_seq", 0) or 0)
        except (TypeError, ValueError):
            shared_seq = 0
        field_seqs = self._player_attr("_field_cue_seq") or {}
        cue_wall = float(self._player_attr("_action_cue_wall", 0) or 0)
        action_walls = self._player_attr("_field_action_wall") or {}
        try:
            with open(LIVE_ACTION_RESULT_FILE, "r", encoding="utf-8") as handle:
                payload = json.load(handle) or {}
        except Exception:
            return
        fields = payload.get("fields") if isinstance(payload, dict) else {}
        if not isinstance(fields, dict):
            return
        wanted = {
            str(name).upper()[:1]
            for name in (entry.get("field_screens") or {})
        }
        try:
            paused_fields = self._pause_fields()
        except Exception:
            paused_fields = {}
        arrived = set()
        for fid in self._active_fields():
            if wanted and str(fid).upper()[:1] not in wanted:
                continue
            item = fields.get(fid) or {}
            if not isinstance(item, dict):
                continue
            fid_key = str(fid).upper()[:1]
            if paused_fields.get(fid_key):
                continue
            try:
                want_seq = int(field_seqs.get(fid_key) or shared_seq or 0)
            except (TypeError, ValueError):
                want_seq = shared_seq
            by_seq = item.get("by_seq") if isinstance(item.get("by_seq"), dict) else {}
            chosen = by_seq.get(str(want_seq)) if want_seq else None
            if not isinstance(chosen, dict):
                if want_seq:
                    continue
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
            field_wall = float(action_walls.get(fid_key) or 0)
            if field_wall and stamped + 0.05 < field_wall:
                continue
            # A goal on the other field must not throw this field's result away.
            if not entry.get("independent_fields") and cue_wall and stamped + 0.05 < cue_wall:
                continue
            name = str(chosen.get("result") or "").strip().lower()
            if name != "correct":
                continue
            if entry.get("independent_fields"):
                arrived.add(str(fid).upper()[:1])
                continue
            self._goal_arrived = True
            self._stop_goal_advance_poll()
            # Drop the pass image now so the next screen is not blocked by it.
            self._clear_field_action_now(str(fid).upper()[:1])
            logger.info("Ball reached the goal on %s (%s) — next screen", fid, name)
            self._finish_label_action()
            return
        if entry.get("independent_fields") and arrived:
            # Each field moves on its own ball. The other field keeps this action.
            holds = dict(getattr(self, "_field_hold_until", None) or {})
            for fid in arrived:
                holds[fid] = 0.0
                self._clear_field_action_now(fid)
            self._field_hold_until = holds
            self._stop_goal_advance_poll()
            logger.info("Ball reached the goal on %s — that field continues", ", ".join(sorted(arrived)))
            self._finish_label_action()

    def _clear_field_action_now(self, fid):
        """Drop this field's pass/number tiles so the next action can paint cleanly.

        Do not repaint here: an immediate black frame while the other field still
        has an opening-card summary makes paintEvent early-return and leave this
        half black until something else updates.
        """
        fid = str(fid or "").upper()[:1]
        if fid not in ("A", "B"):
            return
        try:
            canvas = object.__getattribute__(self, "image_canvas")
        except Exception:
            canvas = None
        if canvas is None:
            return
        try:
            canvas.set_screen_images({}, keep_videos=True, replace_fields={fid})
        except Exception:
            logger.exception("Could not clear Field %s screens after the goal", fid)

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
        if entry.get("combined_field"):
            active = {"A", "B"}

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
        continuing = set()
        if entry.get("independent_fields"):
            continuing = self._independent_continuing_fields(entry, field_screens)

        video_path = entry.get("motion_bg") or entry.get("screen_video")
        pass_scale = 1.0
        if not (entry.get("entry_digits") or entry.get("math_op") or entry.get("motion_fill")):
            pass_scale = (
                self.image_canvas.PASS_IMAGE_SCALE if self.image_canvas else 0.57
            )
        if self._result_hold_mode(entry) == "screen":
            self._release_results_on(lit_screens)
        if self.image_canvas:
            motion_texts = entry.get("motion_texts") or {}
            theme = str(entry.get("motion_theme") or "")
            seed = int(entry.get("motion_seed") or 1)
            base_rgb = entry.get("motion_base_rgb")
            wants_motion = bool(
                theme
                and (entry.get("motion_fill") or entry.get("motion_bg") or entry.get("motion_texts")
                     or entry.get("overlay_images"))
            )
            if wants_motion and theme:
                # Paint solid stills first so leftover logo-scale / digit tiles
                # on screens 3–4 cannot linger smaller than the other cabinets.
                replace_fields = None
                paint = screen_images
                if entry.get("independent_fields"):
                    replace_fields = {
                        _field_for_screen(sid)
                        for sid in screen_images
                        if _field_for_screen(sid) in ("A", "B")
                        and _field_for_screen(sid) not in continuing
                    }
                    if continuing:
                        paint = _images_for_fields(entry, replace_fields)
                if paint:
                    self.image_canvas.set_screen_images(
                        paint,
                        scale=1.0,
                        keep_videos=True,
                        replace_fields=replace_fields,
                    )
                overlay_images = entry.get("overlay_images") or {}
                if overlay_images:
                    self.image_canvas.set_image_overlays(overlay_images)
                    self.image_canvas._keep_text_overlays = True
                elif motion_texts:
                    self.image_canvas.set_text_overlays(
                        motion_texts,
                        color=_wc_s2_text_rgb(theme or "flowers", seed),
                        positions=entry.get("motion_text_positions") or {},
                    )
                    self.image_canvas._keep_text_overlays = True
                screens_for_motion = list(screen_images.keys()) or lit_screens
                # Live fleet: each action reseeds to new spawn edges/locations
                # (gap stills stop the fleet, so the next action always starts fresh).
                self.image_canvas.start_bounce_motion(
                    screens_for_motion,
                    theme=theme,
                    seed=seed,
                    base_rgb=base_rgb,
                    start_frame=int(entry.get("motion_start_frame") or 0),
                    continue_prev=False,
                )
                # Free field must keep coded .ssav saver during this field's action.
                try:
                    self._sync_screensaver()
                except Exception:
                    pass
            else:
                keep_videos = any(
                    ((getattr(self, "_field_result_state", None) or {}).get(fid) or {}).get("phase") == "playing"
                    for fid in ("A", "B")
                )
                replace_fields = None
                paint = screen_images
                if entry.get("independent_fields"):
                    replace_fields = {
                        _field_for_screen(sid)
                        for sid in screen_images
                        if _field_for_screen(sid) in ("A", "B")
                        and _field_for_screen(sid) not in continuing
                    }
                    if continuing:
                        paint = _images_for_fields(entry, replace_fields)
                # Coded .player (omid_2) preferred over .ssav / stills.
                player_paint = {
                    sid: path
                    for sid, path in (paint or {}).items()
                    if str(path or "").lower().endswith(".player")
                }
                if not player_paint and entry.get("screen_player"):
                    player_path = str(entry.get("screen_player") or "")
                    if player_path.lower().endswith(".player") and os.path.isfile(player_path):
                        player_paint = {
                            sid: player_path for sid in (paint or screen_images or {})
                        }
                # Coded pass .ssav — never open pass.mp4 during the action.
                ssav_paint = {
                    sid: path
                    for sid, path in (paint or {}).items()
                    if str(path or "").lower().endswith(".ssav")
                }
                if not ssav_paint and entry.get("screen_ssav"):
                    ssav_path = str(entry.get("screen_ssav") or "")
                    if ssav_path.lower().endswith(".ssav") and os.path.isfile(ssav_path):
                        ssav_paint = {sid: ssav_path for sid in (paint or screen_images or {})}
                if player_paint:
                    self.image_canvas.set_screen_players(
                        player_paint,
                        scale=pass_scale,
                        loop=bool(entry.get("player_loop", True)),
                        replace_fields=replace_fields,
                    )
                    try:
                        self._sync_screensaver()
                    except Exception:
                        pass
                elif ssav_paint:
                    self.image_canvas.set_screen_ssav(ssav_paint, scale=pass_scale)
                    try:
                        self._sync_screensaver()
                    except Exception:
                        pass
                elif replace_fields:
                    self.image_canvas.set_screen_images(
                        paint,
                        scale=pass_scale,
                        keep_videos=True,
                        replace_fields=replace_fields,
                    )
                elif not entry.get("independent_fields"):
                    self.image_canvas.set_screen_images(
                        paint,
                        scale=pass_scale,
                        keep_videos=keep_videos,
                    )
            self._apply_held_results()
            # Paint now. The old timer started before the second monitor showed
            # the image, so Kinovea measured ~2.6s of a 3.0s hold.
            self.image_canvas.repaint()
            QtWidgets.QApplication.processEvents()

        delay = self._label_action_delay_ms(entry)
        if (
            entry.get("budget_ms")
            and not entry.get("independent_fields")
            and delay <= 40
        ):
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
        if entry.get("independent_fields"):
            self._stamp_field_clocks(entry)
            meta = entry.get("field_meta") or {}
            primary = meta.get("A") or (next(iter(meta.values())) if meta else {})
            if primary.get("budget_total_sec") is not None:
                budget_elapsed = float(primary.get("budget_elapsed_sec") or 0.0)
                budget_total = float(primary.get("budget_total_sec") or 0.0)
        elif entry.get("finish_balls") and entry.get("budget_ms"):
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
            field_meta=entry.get("field_meta"),
            field_seqs=self._bump_field_cue_seqs(
                [fid for fid in field_screens if str(fid).upper()[:1] not in continuing]
            ),
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
        if entry.get("independent_fields"):
            now = time.perf_counter()
            old_holds = dict(getattr(self, "_field_hold_until", None) or {})
            holds = {}
            identities = dict(getattr(self, "_field_cue_identity", None) or {})
            walls = dict(getattr(self, "_field_action_wall", None) or {})
            started = time.time()
            for fid, info in (entry.get("field_meta") or {}).items():
                key = str(fid).upper()[:1]
                if key in continuing and old_holds.get(key) is not None:
                    holds[key] = float(old_holds[key])
                    continue
                try:
                    on_ms = int(info.get("on_ms") or delay)
                except (TypeError, ValueError):
                    on_ms = int(delay)
                holds[key] = now + max(80, on_ms) / 1000.0
                walls[key] = started
                identities[key] = self._field_action_identity(entry, field_screens, key)
            self._field_hold_until = holds
            self._field_cue_identity = identities
            self._field_action_wall = walls
            if holds:
                delay = max(40, int(round((min(holds.values()) - now) * 1000.0)))
        self._stop_action_timer()
        self.action_timer = QtCore.QTimer(singleShot=True)
        self.action_timer.setTimerType(QtCore.Qt.PreciseTimer)
        self.action_timer.timeout.connect(self._finish_label_action)
        self.action_timer.start(delay)
        if entry.get("advance_on_goal"):
            self._start_goal_advance_poll()
        if getattr(self, "_finished_field_screens", None):
            self._start_gap_result_poll()
        # SF-30N…180N: after 1s, flash a digit/letter on the next pass screen
        # for 1s. Does not arm keypoints or move the pass image early.
        self._schedule_next_screen_hint(entry)

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

    def _advance_independent_field(self, fid, reload=True):
        """Move one field to its next action. A finished test does not stop the other field."""
        fid = str(fid or "").upper()[:1]
        parts = getattr(self, "_field_opening_playlists", None) or {}
        playlist = parts.get(fid) or []
        if not isinstance(getattr(self, "_independent_index", None), dict):
            self._independent_index = {name: 0 for name in parts}
        if not isinstance(getattr(self, "_independent_done", None), dict):
            self._independent_done = {}
        cur_i = int(self._independent_index.get(fid, 0))
        step = playlist[cur_i] if 0 <= cur_i < len(playlist) and isinstance(playlist[cur_i], dict) else None
        nxt = cur_i + 1
        same_test = False
        if step and nxt < len(playlist) and isinstance(playlist[nxt], dict):
            same_test = int(playlist[nxt].get("test_num") or 0) == int(step.get("test_num") or 0)
        if same_test:
            self._independent_index[fid] = nxt
            self._independent_done[fid] = False
        else:
            self._independent_done[fid] = True
            try:
                canvas = object.__getattribute__(self, "image_canvas")
            except Exception:
                canvas = None
            if canvas is not None:
                try:
                    canvas.set_screen_images({}, keep_videos=True, replace_fields={fid})
                except Exception:
                    pass
            if step:
                self._queue_field_results(fid, step)
        if reload:
            # Always patch this field so a goal during the sibling's opening
            # repaints tiles and rewrites the cue (not a silent _apply_label_phase).
            self._reload_independent_entry(restart_fields={fid})

    def _stop_independent_field(self, fid):
        """End this field only. The other field keeps its current screen and clock."""
        fid = str(fid or "").upper()[:1]
        parts = getattr(self, "_field_opening_playlists", None) or {}
        playlist = parts.get(fid) or []
        if not playlist:
            return
        if not isinstance(getattr(self, "_independent_done", None), dict):
            self._independent_done = {}
        if not isinstance(getattr(self, "_independent_index", None), dict):
            self._independent_index = {name: 0 for name in parts}
        if self._independent_done.get(fid) and self._field_series_finished(fid):
            self._publish_field_controls()
            return
        self._bump_field_epoch(fid)
        try:
            opening = set(object.__getattribute__(self, "_fields_opening") or set())
        except Exception:
            opening = set()
        opening.discard(fid)
        self._fields_opening = opening
        self._independent_index[fid] = max(0, len(playlist) - 1)
        self._independent_done[fid] = True
        holds = dict(getattr(self, "_field_hold_until", None) or {})
        holds.pop(fid, None)
        self._field_hold_until = holds
        try:
            canvas = object.__getattribute__(self, "image_canvas")
        except Exception:
            canvas = None
        if canvas is not None:
            try:
                canvas.set_screen_images({}, keep_videos=True, replace_fields={fid})
            except Exception:
                pass
        logger.info("Operator stop: field %s only", fid)
        try:
            stopped = dict(object.__getattribute__(self, "_field_operator_stopped") or {})
        except Exception:
            stopped = {}
        stopped[fid] = True
        self._field_operator_stopped = stopped
        for name in ("_field_result_state", "_field_final_queued", "_field_final_done"):
            try:
                bucket = dict(object.__getattribute__(self, name) or {})
            except Exception:
                bucket = {}
            bucket.pop(fid, None)
            setattr(self, name, bucket)
        try:
            self._hide_field_result_rings(fid)
        except Exception:
            pass
        overlay = (getattr(self, "_field_wait_overlays", None) or {}).get(fid)
        if overlay is not None:
            try:
                overlay.hide()
            except Exception:
                pass
        live = []
        for name, rows in parts.items():
            key = str(name).upper()[:1]
            if not rows or key == fid:
                continue
            if self._field_series_finished(key):
                continue
            live.append(key)
        if live:
            self._phase_active = list(live)
            _write_players_fields_active(live)
        logger.info("Field %s stopped and cleared. Ready for the next start.", fid)
        try:
            threading.Thread(
                target=self._request_field_final,
                args=(fid,),
                kwargs={"display": False},
                daemon=True,
            ).start()
        except Exception:
            logger.exception("Field %s progress save after stop failed", fid)
        self._reload_independent_entry(restart_fields=set())
        self._publish_field_controls()
        hold = dict(self._player_attr("_screensaver_hold_until") or {})
        hold.pop(fid, None)
        self._screensaver_hold_until = hold
        # This field is free again — resume saver here; other field unchanged.
        try:
            self._sync_screensaver()
        except Exception:
            pass

    def _remaining_field_steps(self, fid):
        """Actions this field still has, including the one on screen now."""
        fid = str(fid or "").upper()[:1]
        parts = getattr(self, "_field_opening_playlists", None) or {}
        playlist = parts.get(fid) or []
        if playlist:
            # A results pause sets done while later tests are still in the list.
            # Dropping those tests is what blanked the other field.
            if self._field_series_finished(fid):
                return []
            try:
                index = int((getattr(self, "_independent_index", None) or {}).get(fid) or 0)
            except (TypeError, ValueError):
                index = 0
            return [step for step in playlist[index:] if isinstance(step, dict)]
        files = [step for step in (getattr(self, "video_files", None) or []) if isinstance(step, dict)]
        if files and files[0].get("independent_fields"):
            return []
        try:
            start = int(getattr(self, "current_video_index", 0) or 0)
        except (TypeError, ValueError):
            start = 0
        # Single-field per-video wait already finished this action — resume at the
        # next test, not the last action of the completed one.
        post = getattr(self, "_post_results_index", None)
        if post is not None:
            try:
                start = max(start, int(post))
            except (TypeError, ValueError):
                pass
        return files[start:]

    def _abort_single_field_results_pipeline(self):
        """Cancel cabinet-wide wait/final so a mid-session join keeps playing.

        Single-field play uses wait_per_video → _do_continue → _show_final_summary
        on the flat playlist. After a join, video_files is one independent entry,
        so a late continue would open final results after only a few Field B actions.
        """
        self._post_results_index = None
        try:
            epoch = int(object.__getattribute__(self, "_results_epoch") or 0) + 1
        except Exception:
            epoch = 1
        self._results_epoch = epoch
        self._results_finished_epoch = epoch
        self.waiting_for_results = False
        self.video_end_called = False
        self.playlist_finished = False
        self._status_completed = False
        try:
            timer = object.__getattribute__(self, "results_timer")
        except Exception:
            timer = None
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass
            self.results_timer = None
        try:
            self._hide_waiting_overlay()
        except Exception:
            pass
        try:
            self._hide_projected_results()
        except Exception:
            pass
        try:
            phase = str(object.__getattribute__(self, "display_phase") or "")
        except Exception:
            phase = ""
        if phase in (
            "wait_per_video",
            "per_video_results",
            "wait_final",
            "final",
            "idle",
            "ready",
        ):
            self.display_phase = "action"
        # Cabinet wait hid the canvas — bring it back so the live field can paint.
        try:
            canvas = object.__getattribute__(self, "image_canvas")
        except Exception:
            canvas = None
        if canvas is not None:
            try:
                canvas.show()
            except Exception:
                pass

    def _join_independent_field(self, fid, info=None):
        """Start this field beside the one already playing. Do not restart that field."""
        fid = str(fid or "").upper()[:1]
        info = info or {}
        level = str(info.get("level") or "")
        if _combined_level_band(level):
            logger.warning("Field %s is Elite/World Class. Stop the live field before starting it.", fid)
            return False
        active = [str(name).upper()[:1] for name in (getattr(self, "_phase_active", None) or [])]
        done = getattr(self, "_independent_done", None) or {}
        if fid in active and not done.get(fid):
            return False
        levels = dict(getattr(self, "_phase_field_levels", None) or {})
        if any(_combined_level_band(value) for value in levels.values()):
            logger.warning("Elite/World Class is on screen. Stop it before starting another field.")
            return False
        levels[fid] = level
        self._phase_field_levels = levels
        dirs = dict(getattr(self, "_phase_field_directories", None) or {})
        directory = str(info.get("directory") or "")
        if directory:
            dirs[fid] = directory
        self._phase_field_directories = dirs
        modes = dict(getattr(self, "_phase_field_modes", None) or {})
        modes[fid] = str(info.get("subdirectory") or info.get("mode_id") or "")
        self._phase_field_modes = modes
        self._cancel_independent_session_close()
        self._bump_field_epoch(fid)
        # Leaving full-cabinet idle saver — this field is now in realtime play.
        # Keep saver off the whole cabinet until BOTH fields are free again.
        self._idle_screensaver_mode = False
        try:
            self._stop_all_screensaver()
        except Exception:
            pass
        # Capture the live field's remaining steps before clearing single-field
        # wait/final state (that clear drops _post_results_index).
        parts = {}
        for other in ("A", "B"):
            if other == fid:
                continue
            remaining = self._remaining_field_steps(other)
            if remaining:
                parts[other] = remaining
        self._abort_single_field_results_pipeline()
        if str(self._player_attr("display_phase") or "") in ("idle", "ready"):
            self.display_phase = "action"
        # Hold saver off through opening + first action paint.
        hold = dict(self._player_attr("_screensaver_hold_until") or {})
        hold[fid] = time.time() + 45.0
        self._screensaver_hold_until = hold
        fresh = list(self._build_one_field_playlist(fid) or [])
        if not fresh:
            logger.error("No playlist to start Field %s", fid)
            return False
        parts[fid] = fresh
        self._field_opening_playlists = parts
        self._independent_index = {name: 0 for name in parts}
        previous_done = dict(self._player_attr("_independent_done") or {})
        self._independent_done = {
            name: bool(previous_done.get(name)) and name != fid
            for name in parts
        }
        try:
            stopped = dict(object.__getattribute__(self, "_field_operator_stopped") or {})
        except Exception:
            stopped = {}
        stopped.pop(fid, None)
        self._field_operator_stopped = stopped
        for name in ("_field_final_queued", "_field_final_done", "_field_result_state"):
            try:
                bucket = dict(object.__getattribute__(self, name) or {})
            except Exception:
                bucket = {}
            bucket.pop(fid, None)
            setattr(self, name, bucket)
        try:
            self._hide_field_result_rings(fid)
        except Exception:
            pass
        now = time.perf_counter()
        holds = dict(getattr(self, "_field_hold_until", None) or {})
        holds.pop(fid, None)
        for name, steps in parts.items():
            if name == fid or holds.get(name) is not None or not steps:
                continue
            if self._independent_done.get(name):
                continue
            try:
                on_ms = int(steps[0].get("on_ms") or 3000)
            except (TypeError, ValueError):
                on_ms = 3000
            holds[name] = now + max(80, on_ms) / 1000.0
        self._field_hold_until = holds
        self._phase_active = [name for name in ("A", "B") if parts.get(name)]
        _write_players_fields_active(self._phase_active)
        self._label_mode = True
        self.playlist_finished = False
        self._status_completed = False
        # Goal poll / independent timer require label action phase.
        self.display_phase = "action"
        self._action_phase = "label"
        self._label_phase = "action"
        entry = _compose_independent_entry(parts, self._independent_index)
        if not entry:
            return False
        self.video_files = [entry]
        self.current_video_index = 0
        # Operator Stop must light as soon as this field joins (status poll).
        self._publish_field_controls()
        self._update_status_file(
            "playing",
            0,
            0,
            "Field %s joined — playing" % fid,
        )
        logger.info("Field %s opening beside %s", fid, [name for name in parts if name != fid])
        try:
            canvas = object.__getattribute__(self, "image_canvas")
        except Exception:
            canvas = None
        if canvas is None:
            # Still resume the live field's action, then start the joined field.
            live_others = [
                name for name in parts
                if name != fid and parts.get(name) and not self._independent_done.get(name)
            ]
            if live_others:
                self._reload_independent_entry(restart_fields=set(live_others))
            self._reload_independent_entry(restart_fields={fid})
            return True
        try:
            opening = set(object.__getattribute__(self, "_fields_opening") or set())
        except Exception:
            opening = set()
        opening.add(fid)
        self._fields_opening = opening
        # Resume the already-running field NOW (canvas was often cleared/hidden
        # during single-field wait). Without this, A stays blank / shows stale
        # opening text and the sim never gets a fresh action cue.
        live_others = [
            name for name in parts
            if name != fid and parts.get(name) and not self._independent_done.get(name)
        ]
        if live_others:
            try:
                canvas.show()
                canvas.raise_()
            except Exception:
                pass
            for other in live_others:
                try:
                    if hasattr(canvas, "_clear_field_summary"):
                        canvas._clear_field_summary({other})
                except Exception:
                    pass
                try:
                    self._hide_field_result_rings(other)
                except Exception:
                    pass
                wait = (getattr(self, "_field_wait_overlays", None) or {}).get(other)
                if wait is not None:
                    try:
                        wait.hide()
                    except Exception:
                        pass
            # Drop stale cabinet/per-field result state so a late timer cannot
            # blank the live field while the joined field is opening.
            for name in ("_field_result_state", "_field_final_queued", "_field_final_done"):
                try:
                    bucket = dict(object.__getattribute__(self, name) or {})
                except Exception:
                    bucket = {}
                for other in live_others:
                    bucket.pop(other, None)
                setattr(self, name, bucket)
            self._reload_independent_entry(restart_fields=set(live_others))
        held = _compose_independent_entry(parts, self._independent_index, skip=opening)
        if held:
            self.video_files = [held]
            self.current_video_index = 0
        intro = None
        try:
            intro = self._intro_video_for_field(fid)
        except Exception:
            intro = None
        intro_ms = (
            _video_duration_ms(intro) if intro else LEVEL_INTRO_MS
        ) + int(LEVEL_INTRO_HOLD_MS)
        holds[fid] = now + (LEVEL_CARD_MS + intro_ms) / 1000.0 + 2.0
        self._field_hold_until = holds
        self._begin_joined_field_opening(fid)
        return True

    def _begin_joined_field_opening(self, fid):
        """Opening card, then the starting video, then this field's test."""
        fid = str(fid or "").upper()[:1]
        try:
            self._stop_field_screensaver(fid)
        except Exception:
            pass
        # Free field keeps its saver while this field opens.
        try:
            self._sync_screensaver()
        except Exception:
            pass
        parts = getattr(self, "_field_opening_playlists", None) or {}
        cards = _opening_cards_for_fields(
            [fid],
            getattr(self, "_phase_field_levels", None) or {},
            getattr(self, "_phase_field_modes", None) or {},
            parts,
            {},
            parts.get(fid) or [],
            1,
        )
        card = cards.get(fid) or {}
        try:
            canvas = object.__getattribute__(self, "image_canvas")
        except Exception:
            canvas = None
        if canvas is not None and card:
            try:
                canvas.show_field_opening(fid, card)
            except Exception:
                logger.exception("Field %s opening card failed", fid)
        logger.info("Field %s beginning information", fid)
        epoch = self._field_epoch(fid)
        QtCore.QTimer.singleShot(
            LEVEL_CARD_MS,
            lambda field=fid, token=epoch: self._play_joined_field_intro(field, token),
        )

    def _play_joined_field_intro(self, fid, epoch=None):
        fid = str(fid or "").upper()[:1]
        if not self._field_epoch_current(fid, epoch):
            return
        if (self._player_attr("_field_operator_stopped") or {}).get(fid):
            return
        if fid not in (getattr(self, "_field_opening_playlists", None) or {}):
            return
        if (getattr(self, "_independent_done", None) or {}).get(fid):
            return
        intro = None
        try:
            intro = self._intro_video_for_field(fid)
        except Exception:
            intro = None
        played = False
        try:
            canvas = object.__getattribute__(self, "image_canvas")
        except Exception:
            canvas = None
        if canvas is not None and intro:
            try:
                played = bool(canvas.play_field_intro(fid, intro))
            except Exception:
                logger.exception("Field %s starting video failed", fid)
                played = False
        if not played:
            self._start_joined_field_test(fid)
            return
        intro_ms = _video_duration_ms(intro) + int(LEVEL_INTRO_HOLD_MS)
        logger.info("Field %s starting video (%sms)", fid, intro_ms)
        epoch = self._field_epoch(fid)
        QtCore.QTimer.singleShot(
            intro_ms,
            lambda field=fid, token=epoch: self._start_joined_field_test(field, token),
        )

    def _start_joined_field_test(self, fid, epoch=None):
        fid = str(fid or "").upper()[:1]
        if not self._field_epoch_current(fid, epoch):
            return
        if (self._player_attr("_field_operator_stopped") or {}).get(fid):
            return
        if fid not in (getattr(self, "_field_opening_playlists", None) or {}):
            return
        if (getattr(self, "_independent_done", None) or {}).get(fid):
            return
        try:
            opening = set(object.__getattribute__(self, "_fields_opening") or set())
        except Exception:
            opening = set()
        opening.discard(fid)
        self._fields_opening = opening
        logger.info("Field %s test starts after its opening", fid)
        self._reload_independent_entry(restart_fields={fid})
        # Keep coded saver looping on any free field beside this test.
        try:
            self._sync_screensaver()
        except Exception:
            pass

    def _consume_field_joins(self):
        directory = getattr(self, "speed_file_dir", None) or "C:/Users/siama/Documents/simust_player"
        path = os.path.join(directory, "field_join.json")
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle) or {}
        except Exception:
            data = {}
        try:
            os.remove(path)
        except OSError:
            pass
        fid = str((data or {}).get("field") or "").upper()[:1]
        if fid not in ("A", "B"):
            return
        self._join_independent_field(fid, data)

    def _finish_due_independent_fields(self):
        """Advance only the fields whose own action time, or own goal, is done."""
        cur = self.video_files[self.current_video_index] if self.video_files else {}
        if not isinstance(cur, dict):
            return
        screens = [str(fid).upper()[:1] for fid in (cur.get("field_screens") or {})]
        now = time.perf_counter()
        holds = dict(getattr(self, "_field_hold_until", None) or {})
        meta = cur.get("field_meta") or {}
        for fid in screens:
            if holds.get(fid) is not None:
                continue
            info = meta.get(fid) or {}
            try:
                on_ms = int(info.get("on_ms") or cur.get("on_ms") or 3000)
            except (TypeError, ValueError):
                on_ms = 3000
            holds[fid] = now + max(80, on_ms) / 1000.0
        self._field_hold_until = holds
        paused = {}
        try:
            paused = self._pause_fields()
        except Exception:
            paused = {}
        due = []
        for fid in screens:
            if paused.get(fid):
                continue
            deadline = holds.get(fid)
            if deadline is None:
                continue
            deadline_f = float(deadline)
            if now + 0.04 < deadline_f:
                continue
            # A real field stays on this screen. Only a goal (deadline 0) moves it.
            if deadline_f > 1.0 and not self._field_uses_simulator(fid):
                holds[fid] = now + 3600.0
                continue
            due.append(fid)
        self._field_hold_until = holds
        if not due:
            self._arm_independent_timer()
            return
        self._stop_goal_advance_poll()
        self._stop_action_timer()
        for fid in due:
            holds.pop(fid, None)
            self._advance_independent_field(fid, reload=False)
        self._field_hold_until = holds
        self._reload_independent_entry(restart_fields=set(due))

    def _finish_independent_step(self):
        cur = self.video_files[self.current_video_index] if self.video_files else {}
        fids = list((cur.get("field_screens") or {}) if isinstance(cur, dict) else [])
        for fid in fids:
            self._advance_independent_field(fid, reload=False)
        self._reload_independent_entry(restart_fields=set(fids))

    def _reload_independent_entry(self, restart_fields=None):
        parts = getattr(self, "_field_opening_playlists", None) or {}
        indices = getattr(self, "_independent_index", None) or {}
        skip = {
            fid for fid, done in (getattr(self, "_independent_done", None) or {}).items() if done
        }
        try:
            opening = set(object.__getattribute__(self, "_fields_opening") or set())
        except Exception:
            opening = set()
        skip |= {str(name).upper()[:1] for name in opening}
        entry = _compose_independent_entry(parts, indices, skip=skip)
        if not entry:
            return None
        files = list(self.video_files or [])
        if files:
            files[0] = entry
        else:
            files = [entry]
        self.video_files = files
        self.current_video_index = 0
        live = {str(fid).upper()[:1] for fid in (entry.get("field_screens") or {})}
        if restart_fields is not None:
            self._patch_independent_fields(
                entry,
                {str(fid).upper()[:1] for fid in restart_fields} & live,
            )
            return entry
        try:
            phase = object.__getattribute__(self, "display_phase")
        except AttributeError:
            phase = "action"
        if phase == "action":
            try:
                apply = object.__getattribute__(self, "_apply_label_phase")
            except AttributeError:
                apply = None
            if callable(apply):
                apply()
        try:
            overlays = object.__getattribute__(self, "_field_wait_overlays")
        except AttributeError:
            overlays = None
        for overlay in (overlays or {}).values():
            try:
                if overlay.isVisible():
                    overlay.raise_()
            except Exception:
                pass
        return entry

    def _stamp_field_clocks(self, entry):
        """Each field keeps its own test clock. The other field's On time is not this clock."""
        if not isinstance(entry, dict) or not entry.get("independent_fields"):
            return
        meta = entry.get("field_meta") or {}
        try:
            clocks = dict(object.__getattribute__(self, "_field_budget_started") or {})
        except Exception:
            clocks = {}
        now = time.perf_counter()
        for fid, info in meta.items():
            if not isinstance(info, dict):
                continue
            key = str(fid).upper()[:1]
            try:
                test_num = int(info.get("test_num") or 0)
            except (TypeError, ValueError):
                test_num = 0
            try:
                on_ms = int(info.get("on_ms") or 0)
            except (TypeError, ValueError):
                on_ms = 0
            if on_ms > 0:
                info["on_sec"] = max(0.1, on_ms / 1000.0)
            try:
                budget_ms = int(info.get("budget_ms") or 0)
            except (TypeError, ValueError):
                budget_ms = 0
            if budget_ms <= 0 or not info.get("finish_balls"):
                continue
            prev = clocks.get(key)
            if not isinstance(prev, tuple) or int(prev[0]) != test_num:
                clocks[key] = (test_num, now)
                elapsed = 0.0
            else:
                elapsed = max(0.0, now - float(prev[1]))
            info["budget_elapsed_sec"] = elapsed
            info["budget_total_sec"] = budget_ms / 1000.0
            info["efficiency_max_sec"] = budget_ms / 1000.0
        self._field_budget_started = clocks

    def _field_series_finished(self, fid):
        """True only after this field's last action. A results pause still has tests left."""
        fid = str(fid or "").upper()[:1]
        parts = getattr(self, "_field_opening_playlists", None) or {}
        playlist = parts.get(fid) or []
        if not playlist:
            return True
        try:
            idx = int((getattr(self, "_independent_index", None) or {}).get(fid, 0))
        except (TypeError, ValueError):
            idx = 0
        done = bool((getattr(self, "_independent_done", None) or {}).get(fid))
        return done and idx + 1 >= len(playlist)

    def _every_independent_series_finished(self):
        parts = getattr(self, "_field_opening_playlists", None) or {}
        names = [fid for fid, rows in parts.items() if rows]
        return bool(names) and all(self._field_series_finished(fid) for fid in names)

    def _bump_field_cue_seqs(self, field_ids):
        """New result identity for these fields only. The other field keeps its seq."""
        seqs = dict(getattr(self, "_field_cue_seq", None) or {})
        for fid in field_ids or []:
            key = str(fid).upper()[:1]
            if key not in ("A", "B"):
                continue
            seqs[key] = int(seqs.get(key) or 0) + 1
        self._field_cue_seq = seqs
        return seqs

    def _field_action_identity(self, entry, field_screens, fid):
        """Screen + test + action. A cue rewrite with this same identity is not a new pass."""
        key = str(fid or "").upper()[:1]
        info = {}
        if isinstance(entry, dict):
            meta = entry.get("field_meta") or {}
            info = meta.get(key) or meta.get(fid) or {}
        screens = tuple(
            str(s) for s in ((field_screens or {}).get(key) or (field_screens or {}).get(fid) or [])
        )
        try:
            test_num = int(info.get("test_num") or 0)
        except (TypeError, ValueError):
            test_num = 0
        try:
            action_in_set = int(info.get("action_in_set") or 0)
        except (TypeError, ValueError):
            action_in_set = 0
        return (test_num, action_in_set, screens)

    def _independent_continuing_fields(self, entry, field_screens):
        """Fields still inside this On window. The other field's goal must not restart them."""
        if not isinstance(entry, dict) or not entry.get("independent_fields"):
            return set()
        now = time.perf_counter()
        old_holds = getattr(self, "_field_hold_until", None) or {}
        old_ids = getattr(self, "_field_cue_identity", None) or {}
        continuing = set()
        for fid in (entry.get("field_meta") or {}):
            key = str(fid).upper()[:1]
            deadline = old_holds.get(key)
            ident = self._field_action_identity(entry, field_screens, key)
            if (
                old_ids.get(key) == ident
                and deadline is not None
                and float(deadline) > now + 0.05
            ):
                continuing.add(key)
        return continuing

    def _arm_independent_timer(self):
        cur = self.video_files[0] if self.video_files else {}
        live = set((cur.get("field_screens") or {})) if isinstance(cur, dict) else set()
        holds = getattr(self, "_field_hold_until", None) or {}
        now = time.perf_counter()
        soon = None
        for fid in live:
            deadline = holds.get(fid)
            if deadline is None:
                continue
            soon = float(deadline) if soon is None else min(soon, float(deadline))
        if soon is None:
            return
        delay = max(40, int(round((soon - now) * 1000.0)))
        self._stop_action_timer()
        self.action_timer = QtCore.QTimer(singleShot=True)
        self.action_timer.setTimerType(QtCore.Qt.PreciseTimer)
        self.action_timer.timeout.connect(self._finish_label_action)
        self.action_timer.start(delay)

    def _patch_independent_fields(self, entry, restart_fields):
        """Start these fields' next action without restarting the field still playing."""
        restart_fields = {str(fid).upper()[:1] for fid in (restart_fields or set())}
        now = time.perf_counter()
        holds = dict(getattr(self, "_field_hold_until", None) or {})
        meta = entry.get("field_meta") or {}
        for fid in restart_fields:
            info = meta.get(fid) or {}
            try:
                on_ms = int(info.get("on_ms") or entry.get("on_ms") or 3000)
            except (TypeError, ValueError):
                on_ms = 3000
            holds[fid] = now + max(80, on_ms) / 1000.0
        self._field_hold_until = holds
        identities = dict(getattr(self, "_field_cue_identity", None) or {})
        for fid in restart_fields:
            identities[fid] = self._field_action_identity(
                entry, entry.get("field_screens") or {}, fid,
            )
        self._field_cue_identity = identities
        if restart_fields:
            seqs = self._bump_field_cue_seqs(restart_fields)
            walls = dict(getattr(self, "_field_action_wall", None) or {})
            started = time.time()
            for fid in restart_fields:
                walls[fid] = started
            self._field_action_wall = walls
        else:
            seqs = dict(getattr(self, "_field_cue_seq", None) or {})
        images = _images_for_fields(entry, restart_fields)
        try:
            canvas = object.__getattribute__(self, "image_canvas")
        except Exception:
            canvas = None
        if canvas is not None and restart_fields:
            band = set(getattr(canvas, "_band_screens", None) or set())
            for name in list(band):
                if _field_for_screen(name) in restart_fields:
                    band.discard(name)
            for name in images:
                band.discard(name)
            canvas._band_screens = band
            try:
                pass_scale = (
                    canvas.PASS_IMAGE_SCALE
                    if not (entry.get("entry_digits") or entry.get("math_op"))
                    else 1.0
                )
                player_images = {
                    sid: path
                    for sid, path in (images or {}).items()
                    if str(path or "").lower().endswith(".player")
                }
                if not player_images and entry.get("screen_player"):
                    player_path = str(entry.get("screen_player") or "")
                    if player_path.lower().endswith(".player") and os.path.isfile(player_path):
                        player_images = {sid: player_path for sid in (images or {})}
                ssav_images = {
                    sid: path
                    for sid, path in (images or {}).items()
                    if str(path or "").lower().endswith(".ssav")
                }
                if player_images:
                    canvas.set_screen_players(
                        player_images,
                        scale=pass_scale,
                        loop=bool(entry.get("player_loop", True)),
                        replace_fields=restart_fields,
                    )
                elif ssav_images:
                    # Keep the other field's tiles; only refresh restarting screens.
                    canvas.set_screen_ssav(
                        ssav_images,
                        scale=pass_scale,
                        replace_fields=restart_fields,
                    )
                else:
                    canvas.set_screen_images(
                        images, keep_videos=True, replace_fields=restart_fields,
                    )
            except Exception:
                pass
        on_ms = 3000
        if restart_fields:
            info = meta.get(next(iter(restart_fields))) or {}
            try:
                on_ms = int(info.get("on_ms") or entry.get("on_ms") or 3000)
            except (TypeError, ValueError):
                on_ms = 3000
        try:
            seq = int(getattr(self, "_flash_seq", 0) or 0)
        except (TypeError, ValueError):
            seq = 0
        self._stamp_field_clocks(entry)
        # Only rewrite cues for fields that are restarting. keep_other_fields
        # preserves the sibling half so a join/goal cannot blank it for 5s+.
        cue_screens = {
            key: screens
            for key, screens in (entry.get("field_screens") or {}).items()
            if not restart_fields or str(key).upper()[:1] in restart_fields
        } or (entry.get("field_screens") or {})
        _write_image_action_cue(
            True,
            cue_screens,
            seq=seq,
            action=str(entry.get("action") or "PASS"),
            on_sec=max(0.1, on_ms / 1000.0),
            efficiency_max_sec=entry.get("efficiency_max_sec"),
            finish_balls=bool(entry.get("finish_balls")),
            action_in_set=entry.get("action_in_set"),
            actions_in_set=entry.get("actions_in_set"),
            test_num=entry.get("test_num"),
            field_meta=meta,
            field_seqs=seqs,
            keep_other_fields=True,
        )
        if restart_fields:
            self._action_cue_wall = time.time()
            self._cue_heartbeat_at = time.time()
            for fid in sorted(restart_fields):
                info = meta.get(fid) or {}
                lit = (entry.get("field_screens") or {}).get(fid) or []
                logger.info(
                    "Independent Field %s action ON screens %s for %sms [test %s a%s]",
                    fid,
                    lit,
                    on_ms,
                    info.get("test_num"),
                    info.get("action_in_set"),
                )
        self.display_phase = "action"
        self._action_phase = "label"
        self._label_phase = "action"
        self._arm_independent_timer()
        if entry.get("advance_on_goal"):
            self._start_goal_advance_poll()

    def _queue_field_results(self, fid, step):
        """This field's test is over. Show its results without stopping the other field."""
        fid = str(fid or "").upper()[:1]
        try:
            state = object.__getattribute__(self, "_field_result_state")
        except AttributeError:
            state = {}
        if not isinstance(state, dict):
            state = {}
        try:
            test_num = int((step or {}).get("test_num") or 1)
        except (TypeError, ValueError):
            test_num = 1
        state[fid] = {
            "phase": "wait",
            "started": time.time(),
            "path": "",
            "test_num": test_num,
            "epoch": self._field_epoch(fid),
        }
        self._field_result_state = state
        try:
            canvas = object.__getattribute__(self, "image_canvas")
        except AttributeError:
            return
        if canvas is None:
            return
        self._show_field_processing(fid)
        token = self._field_epoch(fid)
        QtCore.QTimer.singleShot(
            WAIT_ANIMATION_MS,
            lambda field=fid, stamp=token: self._reveal_field_results(field, stamp),
        )
        thread = threading.Thread(
            target=self._request_field_results, args=(fid, test_num), daemon=True,
        )
        thread.start()

    def _show_field_processing(self, fid):
        """Processing rings on the finished field only. The other field keeps playing."""
        if self.image_canvas:
            self.image_canvas.show()
            self.image_canvas.raise_()
        if not isinstance(getattr(self, "_field_wait_overlays", None), dict):
            self._field_wait_overlays = {}
        overlay = self._field_wait_overlays.get(fid)
        host = self.image_canvas or self
        if overlay is None:
            overlay = WaitingOverlay(host, active_fields=[fid])
            self._field_wait_overlays[fid] = overlay
        elif overlay.parent() is not host:
            overlay.setParent(host)
        overlay.set_active_fields([fid])
        overlay.set_punch_inactive(True)
        colors = getattr(self, "_opening_card_colors", None)
        if callable(colors):
            overlay.set_level_colors(colors())
        overlay.set_status_text("")
        overlay.setGeometry(0, 0, host.width() or self.video_width, host.height() or self.video_height)
        overlay._apply_field_mask()
        overlay.show()
        overlay.raise_()

    def _request_field_results(self, fid, test_num):
        report_path = self._find_latest_report()
        video_path = ""
        if report_path:
            session_dir = os.path.dirname(report_path)
            base = os.path.basename(session_dir.rstrip("\\/"))
            if base in ("field_A", "field_B"):
                session_dir = os.path.dirname(session_dir)
            payload = {
                "report_path": report_path,
                "directory": session_dir,
                "start_time": self._set_start_time or self.video_start_time,
                "end_time": time.time(),
                "video_index": int(test_num),
                "total_videos": self.total_videos,
                "display": False,
                "make_video": False,
                "fields": [fid],
            }
            try:
                if HAS_REQUESTS:
                    response = requests.post(
                        "http://127.0.0.1:8000/create-video-results", json=payload, timeout=90,
                    )
                    if response.status_code == 200:
                        data = response.json()
                        panel = (data.get("panels") or {}).get(fid) or {}
                        if isinstance(panel, dict) and panel:
                            video_path = json.dumps(panel)
                else:
                    import urllib.request
                    req = urllib.request.Request(
                        "http://127.0.0.1:8000/create-video-results",
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=90) as resp:
                        data = json.loads(resp.read().decode("utf-8") or "{}")
                        panel = (data.get("panels") or {}).get(fid) or {}
                        if isinstance(panel, dict) and panel:
                            video_path = json.dumps(panel)
            except Exception as exc:
                logger.warning("Field %s results request failed: %s", fid, exc)
        self.field_results_ready.emit(fid, video_path)

    def _on_field_results_ready(self, fid, video_path):
        state = (getattr(self, "_field_result_state", None) or {}).get(fid)
        if not isinstance(state, dict):
            return
        panel = None
        raw = str(video_path or "")
        if raw.startswith("{"):
            try:
                panel = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                panel = None
        if isinstance(panel, dict) and panel.get("slice_aet"):
            state["panel"] = panel
        phase = state.get("phase")
        stamp = state.get("epoch")
        if stamp is not None and not self._field_epoch_current(fid, stamp):
            return
        if (self._player_attr("_field_operator_stopped") or {}).get(fid):
            return
        ready = (time.time() - float(state.get("started") or 0)) * 1000.0 >= WAIT_ANIMATION_MS - 40
        if phase == "wait" and ready:
            self._reveal_field_results(fid, stamp)
        elif phase == "final_wait" and ready:
            self._reveal_field_final(fid, stamp)

    def _show_field_result_rings(self, fid, panel):
        """Draw this field's rings on its screens. The other field stays uncovered."""
        try:
            self._stop_field_screensaver(fid)
        except Exception:
            pass
        if self.image_canvas:
            self.image_canvas.show()
            self.image_canvas.raise_()
            try:
                self.image_canvas.set_field_level_colors(self._opening_card_colors())
            except Exception:
                pass
        if not isinstance(getattr(self, "_field_result_overlays", None), dict):
            self._field_result_overlays = {}
        host = self.image_canvas or self
        overlay = self._field_result_overlays.get(fid)
        if overlay is None or overlay.parent() is not host:
            overlay = ResultsOverlay(host)
            self._field_result_overlays[fid] = overlay
        try:
            overlay.set_level_colors(self._opening_card_colors())
        except Exception:
            pass
        overlay.set_panels({fid: panel})
        overlay.setGeometry(0, 0, host.width() or self.video_width, host.height() or self.video_height)
        overlay.show()
        overlay.raise_()
        self._play_result_side_videos(fid, panel)

    def _result_logo_for_field(self, fid):
        levels = self._player_attr("_phase_field_levels") or {}
        modes = self._player_attr("_phase_field_modes") or {}
        dirs = self._player_attr("_phase_field_directories") or {}
        level = str(levels.get(fid) or "")
        mode = str(modes.get(fid) or "")
        directory = str(dirs.get(fid) or getattr(self, "video_directory", "") or "")
        context = " ".join([level, mode, directory])
        # Foundation results: only static/logo_video_foundation.mp4 — never foundation.mp4.
        key = _level_brand_key(context, mode, {})
        if key == "foundation":
            hit = os.path.join(LEVEL_INTRO_STATIC_DIR, "logo_video_foundation.mp4")
            return hit if os.path.isfile(hit) else _opening_logo_video_for_level(level, mode)
        return _opening_logo_video_for_level(level, mode) or _opening_logo_video_for_level(level)

    def _play_result_side_videos(self, fid, panel):
        """Logo on screens 3 and 4. Final may also play the coach clip.

        Foundation: only logo_video_foundation.mp4 (no second logo / no coach overlay).
        Never replaced by the coded screensaver.
        """
        canvas = getattr(self, "image_canvas", None)
        if canvas is None or not hasattr(canvas, "play_layered_clips"):
            return
        fid = str(fid or "").upper()[:1]
        try:
            self._stop_field_screensaver(fid)
        except Exception:
            pass
        try:
            canvas.set_field_level_colors(self._opening_card_colors())
        except Exception:
            pass
        # Opening-card summary on 3/4 would paint over the coach and early-return
        # the canvas paint path so the clip never appears.
        try:
            if hasattr(canvas, "_clear_field_summary"):
                canvas._clear_field_summary({fid})
        except Exception:
            pass
        screens = [f"{fid}3", f"{fid}4"]
        wanted = {_sid(name) for name in screens}
        # Drop any leftover saver scale on these logo tiles.
        saver = set(getattr(canvas, "_screensaver_scale_screens", None) or set())
        for name in wanted:
            saver.discard(name)
        canvas._screensaver_scale_screens = saver
        for attr in ("_screen_pixmaps", "_still_pixmaps"):
            current = dict(getattr(canvas, attr, None) or {})
            for name in list(current):
                if _sid(name) in wanted:
                    current.pop(name, None)
            setattr(canvas, attr, current)
        layers = []
        logo = self._result_logo_for_field(fid)
        if logo:
            # Same size as the beginning-information logo (not full-bleed).
            layers.append(({name: logo for name in screens}, True, False))
        levels = self._player_attr("_phase_field_levels") or {}
        dirs = self._player_attr("_phase_field_directories") or {}
        brand = _level_brand_key(
            " ".join([
                str(levels.get(fid) or ""),
                str(dirs.get(fid) or ""),
                str(getattr(self, "video_directory", "") or ""),
            ]),
            "",
            {},
        )
        # Foundation results: one logo only — no coach / foundation.mp4 overlay.
        allow_coach = brand != "foundation"
        coach = str((panel or {}).get("coach_video") or "")
        coach_base = os.path.basename(coach).lower()
        if coach_base in ("foundation.mp4", "logo_video_foundation.mp4"):
            allow_coach = False
        allow_coach = bool(allow_coach and coach and os.path.isfile(coach))
        if allow_coach:
            other = "B" if fid == "A" else "A"
            owner = str(self._player_attr("_coach_audio_field") or "").upper()[:1]
            other_state = (getattr(self, "_field_result_state", None) or {}).get(other) or {}
            other_phase = str(other_state.get("phase") or "")
            other_wants_coach = bool(
                other_phase in ("final_wait", "final_playing", "playing", "wait")
                and isinstance(other_state.get("panel"), dict)
                and str((other_state.get("panel") or {}).get("coach_video") or "")
            )
            if owner and owner != fid:
                allow_coach = False
            elif fid == "B" and other_wants_coach and owner != "B":
                # Both finals arrived together — Field A keeps the voice.
                allow_coach = False
            else:
                self._coach_audio_field = fid
        if allow_coach:
            layers.append(({name: coach for name in screens}, False, True))
            logger.info("Field %s final coach clip: %s", fid, os.path.basename(coach))
        elif brand != "foundation":
            logger.warning(
                "Field %s final coach skipped (path=%s brand=%s)",
                fid, coach or "(none)", brand,
            )
        if layers:
            # Keep canvas visible under the results overlay. Do not raise above
            # the overlay — rings stay on top; screens 3/4 are mask holes for coach.
            try:
                canvas.show()
            except Exception:
                pass
            canvas.play_layered_clips(layers)
            overlay = (getattr(self, "_field_result_overlays", None) or {}).get(fid)
            if overlay is None:
                overlay = getattr(self, "_projected_results", None)
            if overlay is not None:
                try:
                    overlay.raise_()
                except Exception:
                    pass

    def _hide_field_result_rings(self, fid):
        try:
            overlays = object.__getattribute__(self, "_field_result_overlays")
        except Exception:
            overlays = None
        overlay = (overlays or {}).get(fid) if isinstance(overlays, dict) else None
        if overlay is not None:
            try:
                overlay.hide()
            except Exception:
                pass

    def _show_projected_results(self, panels):
        """Draw every finished field's rings on the canvas. No results video."""
        if self.image_canvas:
            self.image_canvas.show()
            self.image_canvas.raise_()
            try:
                self.image_canvas.set_field_level_colors(self._opening_card_colors())
            except Exception:
                pass
        host = self.image_canvas or self
        overlay = getattr(self, "_projected_results", None)
        if overlay is None or overlay.parent() is not host:
            overlay = ResultsOverlay(host)
            self._projected_results = overlay
        try:
            overlay.set_level_colors(self._opening_card_colors())
        except Exception:
            pass
        overlay.set_panels(panels)
        overlay.setGeometry(0, 0, host.width() or self.video_width, host.height() or self.video_height)
        overlay.show()
        overlay.raise_()
        for fid, panel in (panels or {}).items():
            self._play_result_side_videos(fid, panel)
        return True

    def _hide_projected_results(self):
        try:
            overlay = object.__getattribute__(self, "_projected_results")
        except Exception:
            overlay = None
        if overlay is not None:
            try:
                overlay.hide()
            except Exception:
                pass

    def _reveal_field_results(self, fid, epoch=None):
        fid = str(fid or "").upper()[:1]
        if not self._field_epoch_current(fid, epoch):
            return
        if (self._player_attr("_field_operator_stopped") or {}).get(fid):
            return
        state = (getattr(self, "_field_result_state", None) or {}).get(fid)
        if not isinstance(state, dict) or state.get("phase") != "wait":
            return
        panel = state.get("panel") if isinstance(state.get("panel"), dict) else None
        if not panel or not panel.get("slice_aet"):
            if time.time() - float(state.get("started") or 0) < 30.0:
                token = self._field_epoch(fid)
                QtCore.QTimer.singleShot(
                    200, lambda field=fid, stamp=token: self._reveal_field_results(field, stamp),
                )
                return
            overlay = (getattr(self, "_field_wait_overlays", None) or {}).get(fid)
            if overlay is not None:
                overlay.hide()
            state["phase"] = "done"
            self._continue_field_after_results(fid, epoch)
            return
        overlay = (getattr(self, "_field_wait_overlays", None) or {}).get(fid)
        if overlay is not None:
            overlay.hide()
        state["phase"] = "playing"
        self._show_field_result_rings(fid, panel)
        logger.info("Field %s results drawn on its screens while the other field continues", fid)
        token = self._field_epoch(fid)
        QtCore.QTimer.singleShot(
            PER_VIDEO_RESULTS_MS,
            lambda field=fid, stamp=token: self._finish_field_results(field, stamp),
        )

    def _finish_field_results(self, fid, epoch=None):
        fid = str(fid or "").upper()[:1]
        if not self._field_epoch_current(fid, epoch):
            return
        if (self._player_attr("_field_operator_stopped") or {}).get(fid):
            return
        state = (getattr(self, "_field_result_state", None) or {}).get(fid)
        if not isinstance(state, dict) or state.get("phase") == "done":
            return
        state["phase"] = "done"
        canvas = getattr(self, "image_canvas", None)
        if canvas is not None and hasattr(canvas, "_release_field_videos"):
            canvas._release_field_videos({fid})
        self._continue_field_after_results(fid, epoch)

    def _show_field_final(self, fid):
        """This field's series is over. Draw its final rings while the other field plays."""
        fid = str(fid or "").upper()[:1]
        queued = dict(getattr(self, "_field_final_queued", None) or {})
        if queued.get(fid):
            return
        queued[fid] = True
        self._field_final_queued = queued
        state = dict(getattr(self, "_field_result_state", None) or {})
        state[fid] = {
            "phase": "final_wait",
            "started": time.time(),
            "path": "",
            "test_num": 0,
            "epoch": self._field_epoch(fid),
        }
        self._field_result_state = state
        # Series is done for this field — release its Stop button now, not after
        # the final rings and coach clip finish.
        self._publish_field_controls()
        try:
            canvas = object.__getattribute__(self, "image_canvas")
        except Exception:
            canvas = None
        if canvas is None:
            return
        self._show_field_processing(fid)
        token = self._field_epoch(fid)
        QtCore.QTimer.singleShot(
            WAIT_ANIMATION_MS,
            lambda field=fid, stamp=token: self._reveal_field_final(field, stamp),
        )
        thread = threading.Thread(target=self._request_field_final, args=(fid,), daemon=True)
        thread.start()

    def _request_field_final(self, fid, display=True):
        fid = str(fid or "").upper()[:1]
        if not display:
            stopped = True
        else:
            try:
                stopped = bool((object.__getattribute__(self, "_field_operator_stopped") or {}).get(fid))
            except Exception:
                stopped = False
        if stopped and display:
            # Let the camera close this field's last action before the totals.
            time.sleep(1.2)
        report_path = self._find_latest_report()
        video_path = ""
        if report_path:
            session_dir = os.path.dirname(report_path)
            base = os.path.basename(session_dir.rstrip("\\/"))
            if base in ("field_A", "field_B"):
                session_dir = os.path.dirname(session_dir)
            payload = {
                "report_path": report_path,
                "directory": session_dir,
                "display": False,
                "make_video": False,
                "update_progress": stopped,
                "fields": [fid],
            }
            try:
                if HAS_REQUESTS:
                    response = requests.post(
                        "http://127.0.0.1:8000/create-results-video", json=payload, timeout=90,
                    )
                    if response.status_code == 200:
                        data = response.json()
                        panel = (data.get("panels") or {}).get(fid) or {}
                        if isinstance(panel, dict) and panel:
                            video_path = json.dumps(panel)
                else:
                    import urllib.request
                    req = urllib.request.Request(
                        "http://127.0.0.1:8000/create-results-video",
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=90) as resp:
                        data = json.loads(resp.read().decode("utf-8") or "{}")
                        panel = (data.get("panels") or {}).get(fid) or {}
                        if isinstance(panel, dict) and panel:
                            video_path = json.dumps(panel)
            except Exception as exc:
                logger.warning("Field %s final results request failed: %s", fid, exc)
        if not display:
            return
        self.field_results_ready.emit(fid, video_path)

    def _reveal_field_final(self, fid, epoch=None):
        if not self._field_epoch_current(fid, epoch):
            return
        if (self._player_attr("_field_operator_stopped") or {}).get(fid):
            return
        state = (getattr(self, "_field_result_state", None) or {}).get(fid)
        if not isinstance(state, dict) or state.get("phase") != "final_wait":
            return
        panel = state.get("panel") if isinstance(state.get("panel"), dict) else None
        if not panel or not panel.get("slice_aet"):
            if time.time() - float(state.get("started") or 0) < 30.0:
                token = self._field_epoch(fid)
                QtCore.QTimer.singleShot(
                    200, lambda field=fid, stamp=token: self._reveal_field_final(field, stamp),
                )
                return
            overlay = (getattr(self, "_field_wait_overlays", None) or {}).get(fid)
            if overlay is not None:
                overlay.hide()
            self._finish_field_final(fid)
            return
        overlay = (getattr(self, "_field_wait_overlays", None) or {}).get(fid)
        if overlay is not None:
            overlay.hide()
        state["phase"] = "final_playing"
        self._show_field_result_rings(fid, panel)
        logger.info("Field %s final results drawn while the other field continues", fid)
        token = self._field_epoch(fid)
        QtCore.QTimer.singleShot(
            PER_VIDEO_RESULTS_MS,
            lambda field=fid, stamp=token: self._finish_field_final(field, stamp),
        )

    def _finish_field_final(self, fid, epoch=None):
        fid = str(fid or "").upper()[:1]
        if not self._field_epoch_current(fid, epoch):
            return
        if (self._player_attr("_field_operator_stopped") or {}).get(fid):
            return
        state = (getattr(self, "_field_result_state", None) or {}).get(fid)
        if isinstance(state, dict):
            if state.get("phase") == "final_done":
                return
            state["phase"] = "final_done"
        self._hide_field_result_rings(fid)
        if str(self._player_attr("_coach_audio_field") or "").upper()[:1] == fid:
            self._coach_audio_field = None
        canvas = getattr(self, "image_canvas", None)
        if canvas is not None and hasattr(canvas, "_release_field_videos"):
            canvas._release_field_videos({fid})
        overlay = (getattr(self, "_field_wait_overlays", None) or {}).get(fid)
        if overlay is not None:
            try:
                overlay.hide()
            except Exception:
                pass
        done = dict(getattr(self, "_field_final_done", None) or {})
        done[fid] = True
        self._field_final_done = done
        # Field is free again — drop intro/action holds so saver can return.
        hold = dict(getattr(self, "_screensaver_hold_until", None) or {})
        hold.pop(fid, None)
        self._screensaver_hold_until = hold
        self._blank_retired_field(fid)
        try:
            self._sync_screensaver()
        except Exception:
            pass
        if not self._independent_finals_complete():
            return
        self._start_independent_session_close()

    def _cancel_independent_session_close(self):
        """A new Play must not be killed by a late close from the previous series."""
        try:
            token = int(self._player_attr("_independent_close_token", 0) or 0) + 1
        except (TypeError, ValueError):
            token = 1
        self._independent_close_token = token
        self._independent_close_started = False
        self._status_completed = False
        self.playlist_finished = False
        close_timer = self._player_attr("close_timer")
        if close_timer is not None:
            try:
                close_timer.stop()
            except Exception:
                pass
            self.close_timer = None
        force_timer = self._player_attr("_force_close_timer")
        if force_timer is not None:
            try:
                force_timer.stop()
            except Exception:
                pass
            self._force_close_timer = None

    def _start_independent_session_close(self):
        if self._player_attr("_independent_close_started", False):
            return
        try:
            token = int(self._player_attr("_independent_close_token", 0) or 0) + 1
        except (TypeError, ValueError):
            token = 1
        self._independent_close_token = token
        self._independent_close_started = True
        thread = threading.Thread(
            target=self._request_independent_close,
            args=(token,),
            daemon=True,
        )
        thread.start()

    def _blank_retired_field(self, fid):
        """After this field's own final, black only its screens. The other field stays."""
        fid = str(fid or "").upper()[:1]
        if not self._field_series_finished(fid):
            return
        try:
            canvas = object.__getattribute__(self, "image_canvas")
        except Exception:
            canvas = None
        if canvas is not None:
            try:
                canvas.set_screen_images({}, keep_videos=True, replace_fields={fid})
            except Exception:
                pass
        parts = getattr(self, "_field_opening_playlists", None) or {}
        live = [
            str(name).upper()[:1]
            for name, rows in parts.items()
            if rows and not self._field_series_finished(name)
        ]
        if live:
            self._phase_active = list(live)
            _write_players_fields_active(live)
        self._publish_field_controls()

    def _independent_finals_complete(self):
        parts = getattr(self, "_field_opening_playlists", None) or {}
        names = [str(fid).upper()[:1] for fid, rows in parts.items() if rows]
        done = getattr(self, "_field_final_done", None) or {}
        return bool(names) and all(
            self._field_series_finished(fid) and done.get(fid) for fid in names
        )

    def _request_independent_close(self, token=None):
        """Save level progress once both fields have shown their own final results."""
        report_path = self._find_latest_report()
        progress = {}
        if report_path:
            session_dir = os.path.dirname(report_path)
            base = os.path.basename(session_dir.rstrip("\\/"))
            if base in ("field_A", "field_B"):
                session_dir = os.path.dirname(session_dir)
            parts = getattr(self, "_field_opening_playlists", None) or {}
            fields = [str(fid).upper()[:1] for fid, rows in parts.items() if rows]
            payload = {
                "report_path": report_path,
                "directory": session_dir,
                "display": False,
                "make_video": False,
                "update_progress": True,
                "fields": fields or self._active_fields(),
            }
            try:
                if HAS_REQUESTS:
                    response = requests.post(
                        "http://127.0.0.1:8000/create-results-video", json=payload, timeout=120,
                    )
                    if response.status_code == 200:
                        progress = response.json().get("progress") or {}
            except Exception as exc:
                logger.warning("Independent final progress failed: %s", exc)
        self.independent_close_ready.emit(
            json.dumps({"progress": progress, "token": token})
        )

    def _on_independent_close_ready(self, payload):
        info = {}
        token = None
        if isinstance(payload, str) and payload.startswith("{"):
            try:
                parsed = json.loads(payload) or {}
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = {}
            info = parsed.get("progress") or {}
            token = parsed.get("token")
        try:
            want = int(self._player_attr("_independent_close_token", 0) or 0)
            got = int(token) if token is not None else want
        except (TypeError, ValueError):
            want, got = 0, -1
        if got != want:
            logger.info("Ignoring stale series-close after a new field start")
            return
        if not self._player_attr("_independent_close_started", False):
            return
        self._after_final = info if isinstance(info, dict) else {}
        self._finish_independent_session()

    def _finish_independent_session(self):
        """Both fields finished. Release Stop, flash the cabinet, clear camera.

        Frontend treats status ready as session complete and the next Play does a
        fresh start (camera + visualization + Stop). Keep the player window only
        when the coded screensaver must stay up.
        """
        self._independent_close_started = False
        self.playlist_finished = False
        self._status_completed = False
        self._field_opening_playlists = {}
        self._independent_index = {}
        self._independent_done = {}
        self._field_final_queued = {}
        self._field_final_done = {}
        self._field_result_state = {}
        self._phase_active = []
        self._fields_opening = set()
        controls = _read_cabinet_controls(self._player_attr("speed_file_dir"))
        keep_screensaver = (
            bool(controls.get("system_on", True))
            and bool(controls.get("screensaver_on", False))
        )
        if keep_screensaver:
            self._enter_idle_screensaver()
        else:
            self._flash_idle_display(then_screensaver=False)
        self._publish_field_controls()
        self._update_status_file(
            "ready", 0, 0, "Series complete — ready for the next level",
        )
        logger.info("Independent series complete — Stop released, ready for next Play")
        info = self._player_attr("_after_final") or {}
        if not isinstance(info, dict):
            info = {}
        try:
            seconds_left = float(info.get("seconds_left") or 0)
        except (TypeError, ValueError):
            seconds_left = 0
        if info.get("continue_play") and seconds_left > 30:
            try:
                if self._restart_highest_level(info):
                    return
            except Exception:
                logger.exception("Could not auto-continue the next booked level")
            return
        # No next Play yet — close camera/visualization and drop the leftover
        # player process so nothing keeps running behind the next test.
        self._close_camera_feed_display()
        if not keep_screensaver:
            try:
                QtCore.QTimer.singleShot(1200, self.close)
            except Exception:
                pass

    def _close_camera_feed_display(self):
        """Turn off the realtime camera window when nothing is playing."""
        directory = (
            self._player_attr("speed_file_dir")
            or "C:/Users/siama/Documents/simust_player"
        )
        try:
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, "visualization.txt")
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write("false")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except Exception:
            logger.exception("Could not turn off camera visualization")
        try:
            if HAS_REQUESTS:
                requests.post(
                    "http://127.0.0.1:8000/set-visualization",
                    json={"enabled": False},
                    timeout=3,
                )
        except Exception:
            pass
        self._stop_camera_only()

    def _flash_idle_display(self, then_screensaver=True):
        """Black the cabinet and hide results when both fields are done."""
        self._screensaver_fields = set()
        self._coach_audio_field = None
        for fid in ("A", "B"):
            try:
                self._hide_field_result_rings(fid)
            except Exception:
                pass
            overlay = (self._player_attr("_field_wait_overlays") or {}).get(fid)
            if overlay is not None:
                try:
                    overlay.hide()
                except Exception:
                    pass
        try:
            self._hide_projected_results()
        except Exception:
            pass
        try:
            canvas = object.__getattribute__(self, "image_canvas")
        except Exception:
            canvas = None
        if canvas is None:
            if then_screensaver:
                self._sync_screensaver()
            return
        try:
            if hasattr(canvas, "_release_field_videos"):
                canvas._release_field_videos({"A", "B"})
            if hasattr(canvas, "clear"):
                canvas.clear()
            else:
                canvas.set_screen_images({}, keep_videos=False, replace_fields={"A", "B"})
            canvas.repaint()
            QtWidgets.QApplication.processEvents()
        except Exception:
            logger.exception("Could not flash idle display after the series")
        if then_screensaver:
            self._sync_screensaver()

    def _field_is_live(self, fid) -> bool:
        """True only while THIS field owns realtime / opening / results."""
        fid = str(fid or "").upper()[:1]
        if fid not in ("A", "B"):
            return False
        if self._player_attr("_idle_screensaver_mode", False):
            return False
        phase = str(self._player_attr("display_phase") or "")
        if phase in ("idle", "ready"):
            return False
        # Hold only applies to the field that is starting — never inherited.
        hold = getattr(self, "_screensaver_hold_until", None) or {}
        try:
            if float(hold.get(fid) or 0) > time.time():
                return True
        except (TypeError, ValueError):
            pass
        if fid in (getattr(self, "_fields_opening", None) or set()):
            return True
        parts = getattr(self, "_field_opening_playlists", None) or {}
        if parts.get(fid) and not self._field_series_finished(fid):
            return True
        state = (getattr(self, "_field_result_state", None) or {}).get(fid) or {}
        if str(state.get("phase") or "") in (
            "wait", "playing", "final_wait", "final_playing",
        ):
            return True
        # Series done but this field's final rings have not finished yet.
        if parts.get(fid) and not (getattr(self, "_field_final_done", None) or {}).get(fid):
            if self._field_series_finished(fid):
                return True
        # Legacy single-playlist: field stays live through wait/results/final too.
        if not parts and self.video_files and not self._player_attr("playlist_finished", False):
            active = {str(x).upper()[:1] for x in (self._player_attr("_phase_active") or [])}
            if fid in active and phase in (
                "level_card", "level_intro", "intro", "starting", "opening", "action",
                "wait_per_video", "per_video_results", "wait_final", "final",
            ):
                return True
        return False

    def _realtime_session_active(self) -> bool:
        """True while any field is in realtime play (actions, wait, results, final).

        Screen saver must stay off until BOTH fields are free — never paint saver
        on a free half while the other half is still running.
        """
        if self._player_attr("_idle_screensaver_mode", False):
            return False
        hold = getattr(self, "_screensaver_hold_until", None) or {}
        now = time.time()
        for fid in ("A", "B"):
            try:
                if float(hold.get(fid) or 0) > now:
                    return True
            except (TypeError, ValueError):
                pass
        if getattr(self, "_fields_opening", None):
            return True
        parts = getattr(self, "_field_opening_playlists", None) or {}
        if parts:
            finals_done = getattr(self, "_field_final_done", None) or {}
            for fid, rows in parts.items():
                if not rows:
                    continue
                key = str(fid).upper()[:1]
                if not self._field_series_finished(key):
                    return True
                state = (getattr(self, "_field_result_state", None) or {}).get(key) or {}
                if str(state.get("phase") or "") in (
                    "wait", "playing", "final_wait", "final_playing",
                ):
                    return True
                if not finals_done.get(key):
                    return True
            return False
        phase = str(self._player_attr("display_phase") or "")
        if self.video_files and not self._player_attr("playlist_finished", False):
            if phase not in ("idle", "ready", "completed", "closed", ""):
                return True
        active = self._player_attr("_phase_active") or []
        if active and phase not in ("idle", "ready", "completed", "closed", ""):
            return True
        return False

    def _stop_field_screensaver(self, fid):
        """Clear screensaver tiles on one field without touching the other.

        Always strip this field's .ssav ownership even if `_screensaver_fields`
        is out of sync — otherwise join/realtime stills get stamped over.
        """
        fid = str(fid or "").upper()[:1]
        if fid not in ("A", "B"):
            return
        active = set(self._player_attr("_screensaver_fields") or set())
        had = fid in active
        active.discard(fid)
        self._screensaver_fields = active
        canvas = getattr(self, "image_canvas", None)
        if canvas is None:
            return
        try:
            saver = set(getattr(canvas, "_screensaver_scale_screens", None) or set())
            had_tiles = any(_field_for_screen(name) == fid for name in saver)
            for name in list(saver):
                if _field_for_screen(name) == fid:
                    saver.discard(name)
            canvas._screensaver_scale_screens = saver
            if not had and not had_tiles:
                return
            if hasattr(canvas, "_release_field_videos"):
                canvas._release_field_videos({fid})
            canvas.set_screen_images({}, keep_videos=True, replace_fields={fid})
            if not getattr(canvas, "_screensaver_scale_screens", None):
                canvas._saver_pix = None
                if hasattr(canvas, "_stop_coded_screensaver_timer"):
                    canvas._stop_coded_screensaver_timer()
            canvas.repaint()
            QtWidgets.QApplication.processEvents()
        except Exception:
            logger.exception("Could not clear screensaver on Field %s", fid)

    def _raise_screensaver_surface(self):
        """Project saver/action band on Screen 2 like waiting animation."""
        canvas = getattr(self, "image_canvas", None)
        if canvas is None:
            return
        try:
            self.setFixedSize(self.video_width, self.video_height)
            if self.videoframe:
                self.videoframe.setGeometry(0, 0, self.video_width, self.video_height)
                self.videoframe.show()
            canvas.setGeometry(0, 0, self.video_width, self.video_height)
            canvas.show()
            canvas.raise_()
            self.show()
            self.raise_()
        except Exception:
            logger.exception("Could not raise screensaver canvas on Screen 2")

    def _play_field_screensaver(self, fid):
        """Loop coded .ssav pixels on every screen of one idle field (no video play)."""
        fid = str(fid or "").upper()[:1]
        if fid not in ("A", "B"):
            return False
        path = _screen_saver_video_path()
        ssav = ""
        if path:
            ssav = os.path.join(os.path.dirname(path), "screen_saver_pixels.ssav")
        canvas = getattr(self, "image_canvas", None)
        if canvas is None or not hasattr(canvas, "play_coded_screensaver"):
            return False
        if not ((path and os.path.isfile(path)) or (ssav and os.path.isfile(ssav))):
            return False
        screens = _field_all_screens(fid)
        if not screens:
            return False
        self._raise_screensaver_surface()
        ok = canvas.play_coded_screensaver(screens)
        if ok:
            active = set(self._player_attr("_screensaver_fields") or set())
            active.add(fid)
            self._screensaver_fields = active
            for delay in (50, 150, 400, 800):
                QtCore.QTimer.singleShot(delay, self._raise_screensaver_canvas)
            logger.info(
                "Coded screensaver on Field %s (%s screens, Screen %s coach band)",
                fid,
                len(screens),
                int(self._player_attr("screen_index", 1)) + 1,
            )
        return bool(ok)

    def _all_cabinet_screens(self):
        """Every projector tile on Field A and Field B."""
        screens = []
        for fid in ("A", "B"):
            screens.extend(_field_all_screens(fid))
        # Deduplicate while keeping order.
        seen = set()
        ordered = []
        for name in screens:
            key = _sid(name)
            if not key or key in seen:
                continue
            seen.add(key)
            ordered.append(key)
        return ordered

    def _stop_all_screensaver(self):
        """Clear the coded saver from every cabinet screen."""
        for fid in ("A", "B"):
            self._stop_field_screensaver(fid)
        canvas = getattr(self, "image_canvas", None)
        if canvas is None:
            self._screensaver_fields = set()
            return
        try:
            canvas._screensaver_scale_screens = set()
            canvas._saver_pix = None
            if hasattr(canvas, "_stop_coded_screensaver_timer"):
                canvas._stop_coded_screensaver_timer()
        except Exception:
            logger.exception("Could not clear full-cabinet screensaver")
        self._screensaver_fields = set()

    def _play_all_screensaver(self):
        """Loop coded screensaver on every Field A and Field B screen."""
        ok_a = self._play_field_screensaver("A")
        ok_b = self._play_field_screensaver("B")
        return bool(ok_a or ok_b)

    def _raise_screensaver_canvas(self):
        """Keep the saver visible above the black VLC frame on monitor 2."""
        if not self._player_attr("_screensaver_fields"):
            return
        canvas = getattr(self, "image_canvas", None)
        if canvas is None:
            return
        try:
            canvas.setGeometry(0, 0, self.video_width, self.video_height)
            canvas.show()
            canvas.raise_()
            canvas.update()
        except Exception:
            pass

    def _field_blocks_screensaver(self, fid) -> bool:
        """True only when THIS field is busy — independent of the other field."""
        fid = str(fid or "").upper()[:1]
        if self._field_is_live(fid):
            return True
        overlay = (getattr(self, "_field_result_overlays", None) or {}).get(fid)
        if overlay is not None:
            try:
                if overlay.isVisible():
                    return True
            except Exception:
                pass
        wait = (getattr(self, "_field_wait_overlays", None) or {}).get(fid)
        if wait is not None:
            try:
                if wait.isVisible():
                    return True
            except Exception:
                pass
        canvas = getattr(self, "image_canvas", None)
        if canvas is not None:
            summary = set(getattr(canvas, "_summary_screens", None) or set())
            if any(_field_for_screen(name) == fid for name in summary):
                return True
            # This field's opening/results logo only — not the other field's logo.
            logo = set(getattr(canvas, "_logo_scale_screens", None) or set())
            if any(_field_for_screen(name) == fid for name in logo):
                return True
            bounce = set(getattr(canvas, "_bounce_screens", None) or set())
            if any(_field_for_screen(name) == fid for name in bounce):
                return True
        return False

    def _field_wants_screensaver(self, fid) -> bool:
        """Saver only when the whole cabinet is free (both fields idle)."""
        fid = str(fid or "").upper()[:1]
        if fid not in ("A", "B"):
            return False
        if self._realtime_session_active():
            return False
        return True

    def _on_cabinet_idle_tick(self):
        """Screensaver sync plus cue heartbeat while a field opening stretches past 5s."""
        try:
            self._heartbeat_independent_action_cue()
        except Exception:
            pass
        self._sync_screensaver()

    def _heartbeat_independent_action_cue(self):
        """Refresh cue timestamp so realtime does not drop a live field mid-opening.

        Realtime ignores plain cues older than 5s. Field B's opening card+intro is
        longer, so Field A's cue must be touched or the sim/cylinder freezes.
        """
        if not self._realtime_session_active():
            return
        # Only needed while a sibling is still on its opening card/intro.
        opening = set(self._player_attr("_fields_opening") or set())
        if not opening:
            return
        entry = None
        files = self._player_attr("video_files") or []
        if files and isinstance(files[0], dict) and files[0].get("independent_fields"):
            entry = files[0]
        if not entry:
            return
        now = time.time()
        last = float(self._player_attr("_cue_heartbeat_at", 0) or 0)
        if now - last < 1.5:
            return
        self._cue_heartbeat_at = now
        screens = entry.get("field_screens") or {}
        if not screens:
            return
        meta = entry.get("field_meta") or {}
        seqs = dict(self._player_attr("_field_cue_seq") or {})
        try:
            on_ms = int(entry.get("on_ms") or 3000)
        except (TypeError, ValueError):
            on_ms = 3000
        _write_image_action_cue(
            True,
            screens,
            seq=int(self._player_attr("_flash_seq", 0) or 0),
            action=str(entry.get("action") or "PASS"),
            on_sec=max(0.1, on_ms / 1000.0),
            efficiency_max_sec=entry.get("efficiency_max_sec"),
            finish_balls=bool(entry.get("finish_balls")),
            action_in_set=entry.get("action_in_set"),
            actions_in_set=entry.get("actions_in_set"),
            test_num=entry.get("test_num"),
            field_meta=meta,
            field_seqs=seqs,
            keep_other_fields=True,
        )

    def _sync_screensaver(self):
        """Coded .ssav saver only when BOTH fields are free (no realtime play).

        While any field is in actions / wait / results / final, keep saver off
        the whole cabinet so a mid-series join cannot hang under a half-saver.
        """
        controls = _read_cabinet_controls(self._player_attr("speed_file_dir"))
        prev = dict(self._player_attr("_cabinet_controls") or {})
        self._cabinet_controls = controls
        system_on = bool(controls.get("system_on", True))
        saver_on = bool(controls.get("screensaver_on", False))
        if not system_on:
            if prev.get("system_on", True) or self._player_attr("_screensaver_fields"):
                try:
                    self._flash_idle_display(then_screensaver=False)
                except Exception:
                    self._screensaver_fields = set()
            return
        want = set()
        if saver_on and not self._realtime_session_active():
            want = {"A", "B"}
        active = set(self._player_attr("_screensaver_fields") or set())
        for fid in list(active - want):
            self._stop_field_screensaver(fid)
        if not want:
            return
        canvas = getattr(self, "image_canvas", None)
        saver_tiles = set(getattr(canvas, "_screensaver_scale_screens", None) or set()) if canvas else set()
        for fid in want:
            field_tiles = {_sid(n) for n in _field_all_screens(fid)}
            # Re-attach coded tiles if action/bounce dropped them mid-play.
            if fid not in active or not field_tiles.issubset(saver_tiles):
                self._play_field_screensaver(fid)

    def _continue_field_after_results(self, fid, epoch=None):
        """This field's results are done. Start its next test without waiting."""
        fid = str(fid or "").upper()[:1]
        if not self._field_epoch_current(fid, epoch):
            return
        if (self._player_attr("_field_operator_stopped") or {}).get(fid):
            return
        state = dict(getattr(self, "_field_result_state", None) or {})
        state.pop(fid, None)
        self._field_result_state = state
        overlay = (getattr(self, "_field_wait_overlays", None) or {}).get(fid)
        if overlay is not None:
            try:
                overlay.hide()
            except Exception:
                pass
        self._hide_field_result_rings(fid)
        canvas = getattr(self, "image_canvas", None)
        if canvas is not None:
            band = set(getattr(canvas, "_band_screens", None) or set())
            for name in _field_all_screens(fid):
                band.discard(name)
            canvas._band_screens = band
        parts = getattr(self, "_field_opening_playlists", None) or {}
        playlist = parts.get(fid) or []
        idx = int((getattr(self, "_independent_index", None) or {}).get(fid, 0))
        if idx + 1 >= len(playlist):
            self._independent_done[fid] = True
            entry = self._reload_independent_entry(restart_fields=set())
            if entry is None:
                self._stop_action_timer()
                self._stop_goal_advance_poll()
            self._show_field_final(fid)
            return
        self._independent_index[fid] = idx + 1
        self._independent_done[fid] = False
        self.display_phase = "action"
        if getattr(self, "_action_phase", "") != "label":
            self._action_phase = "label"
        self._reload_independent_entry(restart_fields={fid})

    def _finish_label_action(self):
        if self.display_phase != "action" or self._action_phase != "label":
            return
        if self.operator_paused:
            QTimer.singleShot(200, self._finish_label_action)
            return
        cur = self.video_files[self.current_video_index] if self.video_files else {}
        independent = isinstance(cur, dict) and bool(cur.get("independent_fields"))
        if independent:
            self._finish_due_independent_fields()
            return
        # A received ball ends this screen now. Otherwise hold the pass image
        # until its On time (or the test clock) runs out.
        goal_hit = bool(getattr(self, "_goal_arrived", False))
        shown = getattr(self, "_pass_shown_at", None)
        need_ms = int(getattr(self, "_pass_on_ms", 0) or 0)
        if (not goal_hit) and shown is not None and need_ms > 0:
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
        self._cancel_next_screen_hint()
        if independent:
            self._finish_independent_step()
            return
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
        self._publish_field_controls()
        self._update_status_file("playing", 0, total, f"Playlist loaded: {total} {kind}")
        logger.info("Playlist loaded: %s %s", total, kind)

    def _opening_card_colors(self):
        """Waiting / results band fills: level brand background with readable text."""
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
            key = _level_brand_key(context, "", {})
            colors[fid] = _LEVEL_PAGE_BG.get(key) or _LEVEL_PAGE_BG["foundation"]
        return colors

    def _show_waiting_overlay(self, status_text=""):
        if self.videoframe:
            self.videoframe.show()
            self.videoframe.raise_()
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
            # Prefer the highest test number in this field's playlist. Foundation is 5.
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
        # Realtime play owns the cabinet — no coded saver until both fields free.
        self._idle_screensaver_mode = False
        try:
            self._stop_all_screensaver()
        except Exception:
            pass
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
            if self.videoframe:
                self.videoframe.hide()
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
            "make_video": False,
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
                    panels = data.get("panels") or {}
                    if isinstance(panels, dict) and panels:
                        video_path = json.dumps({"panels": panels})
                        logger.info("Results for test %s ready to project.", video_num)
                    else:
                        logger.error("Per-video results missing rings: %s", data)
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
                    panels = data.get("panels") or {}
                    if isinstance(panels, dict) and panels:
                        video_path = json.dumps({"panels": panels})
        except Exception as e:
            logger.error("Per-video results request failed: %s", e)
        self.per_video_results_ready.emit(video_path)

    def _on_per_video_results_ready(self, video_path):
        if self.operator_paused:
            QTimer.singleShot(200, lambda: self._on_per_video_results_ready(video_path))
            return
        if getattr(self, "display_phase", "") != "wait_per_video":
            logger.info("Ignoring results from an earlier test")
            return
        epoch = int(getattr(self, "_results_epoch", 0) or 0)
        self._arm_timer(
            self._remaining_wait_ms(),
            lambda path=video_path, token=epoch: self._play_per_video_results(path, token),
        )

    def _play_per_video_results(self, video_path, epoch=None):
        if self.operator_paused:
            QTimer.singleShot(200, lambda: self._play_per_video_results(video_path, epoch))
            return
        if getattr(self, "display_phase", "") != "wait_per_video":
            return
        current = int(getattr(self, "_results_epoch", 0) or 0)
        if epoch is not None and int(epoch) != current:
            logger.info("Ignoring results from an earlier test")
            return
        remain = self._remaining_wait_ms()
        if remain > 40:
            token = current if epoch is None else int(epoch)
            self._arm_timer(
                remain,
                lambda path=video_path, token=token: self._play_per_video_results(path, token),
            )
            return
        self._hide_waiting_overlay()
        panels = None
        if isinstance(video_path, str) and video_path.startswith("{"):
            try:
                panels = json.loads(video_path).get("panels")
            except (TypeError, ValueError, json.JSONDecodeError):
                panels = None
        if isinstance(panels, dict) and panels:
            self.display_phase = "per_video_results"
            self.waiting_for_results = True
            self.completion_label.hide()
            self._show_projected_results(panels)
            self._update_status_file(
                "playing_results",
                self._current_test_num(),
                self.total_videos,
                "Showing per-video results...",
            )
            logger.info(
                "Projecting results for test %s/%s",
                self._current_test_num(), self.total_videos,
            )
            self._arm_timer(PER_VIDEO_RESULTS_MS, self._finish_per_video_results)
            return
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
        epoch = int(getattr(self, "_results_epoch", 0) or 0)
        if getattr(self, "_results_finished_epoch", None) == epoch:
            return
        if getattr(self, "display_phase", "") not in ("per_video_results", "wait_per_video"):
            return
        self._results_finished_epoch = epoch
        if self.results_timer:
            self.results_timer.stop()
            self.results_timer = None
        self._hide_projected_results()
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
        parts = getattr(self, "_field_opening_playlists", None) or {}
        if parts:
            # A mid-session join already owns the timeline. A late single-field
            # continue must not treat the 1-entry independent playlist as "done".
            logger.info("Ignoring single-field continue — independent fields are live")
            self._post_results_index = None
            self.waiting_for_results = False
            self.display_phase = "action"
            return
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
        parts = getattr(self, "_field_opening_playlists", None) or {}
        if parts and not self._every_independent_series_finished():
            logger.info("Ignoring cabinet final — independent fields still playing")
            self.waiting_for_results = False
            self.display_phase = "action"
            return
        logger.info("All action sets done; showing the same wait animation then final results")
        self.display_phase = "wait_final"
        self.waiting_for_results = True
        self._wait_started = time.time()
        # Release Stop as soon as finish-process starts (not only after final rings).
        self._publish_field_controls()
        self._update_status_file(
            "wait_final", self.total_videos, self.total_videos,
            "Processing final results",
        )
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
                    "make_video": False,
                    "fields": self._active_fields(),
                },
                timeout=120,
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    self._after_final = data.get("progress") or {}
                    panels = data.get("panels") or {}
                    if isinstance(panels, dict) and panels:
                        self.final_summary_done.emit(json.dumps({"panels": panels}))
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
        panels = None
        if isinstance(video_path, str) and video_path.startswith("{"):
            try:
                panels = json.loads(video_path).get("panels")
            except (TypeError, ValueError, json.JSONDecodeError):
                panels = None
        if isinstance(panels, dict) and panels:
            self.display_phase = "final"
            self._show_projected_results(panels)
            self.completion_label.hide()
            self.playlist_finished = True
            self._publish_field_controls()
            self._update_status_file(
                "playing_final", self.total_videos, self.total_videos,
                "Final results on screen",
            )
            if self._force_close_timer:
                self._force_close_timer.stop()
            self._force_close_timer = QtCore.QTimer(singleShot=True)
            self._force_close_timer.timeout.connect(self._on_field_final_finished)
            self._force_close_timer.start(PER_VIDEO_RESULTS_MS)
            return
        if video_path and os.path.exists(video_path):
            self.display_phase = "final"
            phase = (
                self._run_phases[self._phase_index]
                if 0 <= self._phase_index < len(self._run_phases)
                else {}
            )
            self.playlist_finished = True
            self._publish_field_controls()
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
        self._hide_projected_results()
        try:
            self.player.stop()
        except Exception:
            pass
        self.completion_label.hide()
        self.waiting_for_results = False
        more = self._phase_index + 1 < len(self._run_phases)
        info = getattr(self, "_after_final", None) or {}
        try:
            seconds_left = float(info.get("seconds_left") or 0)
        except (TypeError, ValueError):
            seconds_left = 0
        if info.get("continue_play") and seconds_left > 30 and self._restart_highest_level(info):
            self.playlist_finished = False
            self.display_phase = "action"
            return
        if more:
            logger.info("Field phase done — starting next field")
            self.playlist_finished = False
            self.display_phase = "action"
            self._advance_to_next_field_phase()
            return
        # All fields finished — keep Stop released (do not flip playlist_finished
        # back to False while phase_active still looks live).
        self.playlist_finished = True
        self.display_phase = "completed"
        self._phase_active = []
        self._publish_field_controls()
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

    def _signal_stop_video_save(self, reason=""):
        """Ask realtime to finalize realtime_recording.mp4 (camera may keep running)."""
        try:
            with open(STOP_SAVE_FILE, "w", encoding="utf-8") as handle:
                handle.write("1")
            logger.info(
                "Asked realtime to stop video save%s",
                f" ({reason})" if reason else "",
            )
        except Exception as exc:
            logger.warning("Could not signal video stop: %s", exc)

    def _stop_camera_only(self):
        if self._realtime_stopped:
            return
        self._signal_stop_video_save("camera stop")
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
        # Operator Stop (or forced cleanup) — end the save immediately.
        self._signal_stop_video_save("operator stop")
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
        parts = getattr(self, "_field_opening_playlists", None) or {}
        if parts:
            # Independent A/B play uses per-field results, not the cabinet wait.
            logger.info("Ignoring single-field video-ended — independent fields are live")
            return
        self.video_end_called = True
        self.waiting_for_results = True
        self._results_epoch = int(getattr(self, "_results_epoch", 0) or 0) + 1
        self._results_finished_epoch = None
        self.display_phase = "wait_per_video"
        # Keep realtime_recording.mp4 open through per-video + final results.
        # Only operator Stop (or session close after finals) ends the save.
        more_tests = getattr(self, "_post_results_index", None) is not None
        if more_tests:
            logger.info("Test finished — saved video stays open for the next test")
        else:
            logger.info("Last test finished — saved video stays open until final results end")
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
        saver_on = bool(self._player_attr("_screensaver_fields"))
        show_canvas = (
            self.image_canvas
            and self.image_based
            and (
                self.display_phase in ("action", "level_intro", "level_card", "idle")
                or saver_on
                or self._player_attr("_idle_screensaver_mode", False)
            )
        )
        if show_canvas:
            # Same projector band as waiting / actions — canvas must sit above the black frame.
            self.image_canvas.setGeometry(0, 0, self.video_width, self.video_height)
            self.image_canvas.show()
            self.image_canvas.raise_()
            if self.display_phase in ("level_card", "idle") or saver_on:
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
        fields = self._pause_fields()
        return bool(fields.get("A") and fields.get("B"))

    def _pause_fields(self):
        """Pause for one field, or both when the file is the legacy true/false flag."""
        path = getattr(self, "pause_file_path", None)
        if not path or not os.path.exists(path):
            return {"A": False, "B": False}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw = handle.read().strip()
        except Exception:
            return {"A": False, "B": False}
        lower = raw.lower()
        if lower in ("1", "true", "yes", "on", "paused"):
            return {"A": True, "B": True}
        if lower in ("0", "false", "no", "off", ""):
            return {"A": False, "B": False}
        if raw[:1] == "{":
            try:
                data = json.loads(raw) or {}
            except Exception:
                return {"A": False, "B": False}
            return {"A": bool(data.get("A")), "B": bool(data.get("B"))}
        return {"A": False, "B": False}

    def _field_uses_simulator(self, fid):
        """True only while this field's simulator switch is on."""
        directory = getattr(self, "speed_file_dir", None) or "C:/Users/siama/Documents/simust_player"
        path = os.path.join(directory, "arena_simulation.txt")
        try:
            if not os.path.exists(path):
                return False
            with open(path, "r", encoding="utf-8") as handle:
                raw = handle.read().strip()
        except Exception:
            return False
        lower = raw.lower()
        if lower in ("1", "true", "yes", "on"):
            return True
        if lower in ("0", "false", "no", "off", ""):
            return False
        key = str(fid or "").upper()[:1]
        if raw[:1] == "{":
            try:
                data = json.loads(raw) or {}
            except Exception:
                return False
            return bool(data.get(key))
        tokens = {
            part.strip().upper()[:1]
            for part in raw.replace(";", ",").split(",")
            if part.strip()
        }
        return key in tokens

    def _hold_paused_fields(self, paused):
        """Keep a paused field's On clock from expiring while the other field plays."""
        holds = dict(getattr(self, "_field_hold_until", None) or {})
        now = time.perf_counter()
        prev = dict(getattr(self, "_field_pause_on", None) or {})
        remains = dict(getattr(self, "_field_pause_remain", None) or {})
        changed = False
        for fid in ("A", "B"):
            on = bool((paused or {}).get(fid))
            if on and not prev.get(fid):
                deadline = holds.get(fid)
                remains[fid] = 0.2 if deadline is None else max(0.2, float(deadline) - now)
            if on and fid in holds:
                holds[fid] = now + float(remains.get(fid) or 0.2)
                changed = True
            prev[fid] = on
        self._field_pause_on = prev
        self._field_pause_remain = remains
        if changed:
            self._field_hold_until = holds

    def _consume_field_stops(self):
        directory = getattr(self, "speed_file_dir", None) or "C:/Users/siama/Documents/simust_player"
        path = os.path.join(directory, "field_stop.json")
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle) or {}
        except Exception:
            data = {}
        try:
            os.remove(path)
        except OSError:
            pass
        fid = str((data or {}).get("field") or "").upper()[:1]
        if fid not in ("A", "B"):
            return
        cur = self.video_files[self.current_video_index] if getattr(self, "video_files", None) else {}
        if not isinstance(cur, dict) or not cur.get("independent_fields"):
            return
        self._stop_independent_field(fid)

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
            self._pause_perf_started_at = time.perf_counter()
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
        dt_perf = (
            time.perf_counter() - self._pause_perf_started_at
            if self._pause_perf_started_at
            else dt
        )
        self._shift_clocks_after_pause(dt, dt_perf)
        self._pause_started_at = 0
        self._pause_perf_started_at = 0
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

    def _maybe_attr(self, name, default=None):
        try:
            return object.__getattribute__(self, name)
        except Exception:
            return default

    def _shift_clocks_after_pause(self, dt, dt_perf):
        """Wall-clock pause must not consume On / budget / result windows."""
        if dt <= 0 and dt_perf <= 0:
            return
        for name in (
            "video_start_time",
            "_set_start_time",
            "_final_play_started_at",
            "_wait_started",
            "_action_cue_wall",
            "_finished_action_at",
            "_finished_cue_wall",
            "_last_result_deadline",
            "last_check_time",
        ):
            value = self._maybe_attr(name)
            if value:
                setattr(self, name, float(value) + dt)
        for name in ("_pass_shown_at", "_budget_started_at"):
            value = self._maybe_attr(name)
            if value:
                setattr(self, name, float(value) + dt_perf)

    def _freeze_qt_timers(self):
        frozen = []
        remain_on = self._paused_on_remaining_ms()
        for name in (
            "results_timer",
            "close_timer",
            "play_delay_timer",
            "_force_close_timer",
            "action_timer",
            "_gap_result_timer",
            "_goal_advance_timer",
        ):
            timer = self._maybe_attr(name)
            if timer is None:
                continue
            try:
                if not timer.isActive():
                    continue
                remaining = timer.remainingTime()
                timer.stop()
                if name == "action_timer" and remain_on is not None:
                    remaining = remain_on
                frozen.append((name, max(50, remaining if remaining >= 0 else 0)))
            except Exception:
                continue
        self._frozen_qt_timers = frozen

    def _paused_on_remaining_ms(self):
        shown = self._maybe_attr("_pass_shown_at")
        need_ms = int(self._maybe_attr("_pass_on_ms", 0) or 0)
        if shown is None or need_ms <= 0:
            return None
        remain = int(need_ms - (time.perf_counter() - float(shown)) * 1000.0)
        return max(50, remain)

    def _thaw_qt_timers(self):
        for name, remaining in self._frozen_qt_timers:
            timer = self._maybe_attr(name)
            if timer is None:
                continue
            try:
                timer.start(remaining)
            except Exception:
                continue
        self._frozen_qt_timers = []

    def _live_control_fields(self):
        """Fields that are on screen and can be paused or stopped on their own."""
        live = []
        for fid in (getattr(self, "_phase_active", None) or []):
            key = str(fid).upper()[:1]
            if key in ("A", "B") and key not in live:
                live.append(key)
        return live or ["A", "B"]

    def _all_live_fields_paused(self, paused):
        live = self._live_control_fields()
        return bool(live) and all(bool((paused or {}).get(fid)) for fid in live)

    def _check_operator_pause(self):
        try:
            self._publish_field_controls()
        except Exception:
            pass
        if self._is_closing or self.playlist_finished:
            return
        try:
            fields = self._pause_fields()
            self._hold_paused_fields(fields)
            self._consume_field_stops()
            self._consume_field_joins()
            self._apply_operator_pause(self._all_live_fields_paused(fields))
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
                "wait_per_video", "wait_final", "per_video_results",
                "level_intro", "level_card", "prestart",
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
    idle_saver = str(video_dir or "").strip().lower() in (
        IDLE_SCREENSAVER_ARG,
        "--screensaver",
        "screensaver",
    )
    if not idle_saver and not IMAGE_BASED_ACTIONS and not os.path.isdir(video_dir):
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