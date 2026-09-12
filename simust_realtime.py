"""
SIMUST REALTIME PLAYER - with YOLOv8‑pose for stable player tracking
- Ball detection: BOTH halves (existing YOLO detection)
- Player detection: LEFT half (existing YOLO detection)  +  POLYGON ROI FILTER
- Pose estimation: lightweight YOLOv8‑pose on the player crop
- Tracking point: average of left/right hip keypoints (stable vs. posture changes)
- NO fallback to bounding-box if pose fails
- 1‑Euro filter for smooth, cm‑accurate displacement
- EOP computed using every 8th frame (sampling)
- All existing features: QR-based actions, real-time results, video saving, etc.
- **UPDATED ANALYSIS LOGIC** – simplified return detection, larger thresholds, FINISH_DIST
- **FIXED:** Repeated identical QR codes now trigger new sessions after disappearance
- **NEW:** Player detection restricted to a polygon ROI; polygon drawn in saved video
- **FIX (2026-08-04):** Between‑session data is now included in the analysis to capture late completions.
- **FIX (2026-08-07):** GOAL detection uses dedicated late search (no time limit, no movement filter)
- **NEW (2026-08-07):** Action Efficiency (AE) score computed per action.
- **FIX (2026-08-07):** Late detection for PASS/TARGET/PRESS now uses fallback action_end_time
- **FIX (2026-08-30):** QR block is saved to recognition.json immediately; delayed analysis only sends results.
"""

import cv2
import numpy as np
import threading
import queue
import time
import json
import os
import sys
import re
import math
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from typing import Optional, Tuple, List, Dict
import mss
from ultralytics import YOLO
import torch
import warnings
import signal
import atexit
import gc
import random
import requests

warnings.filterwarnings('ignore', category=FutureWarning)

# ============================================================================
# CONSTANTS - OPTIMIZED
# ============================================================================

QR_OFFSET_FRAMES = 21
TARGET_FPS = 25.0
QR_OFFSET_SECONDS = QR_OFFSET_FRAMES / TARGET_FPS
MAX_SESSION_DURATION = 5.0
QR_COOLDOWN = 0.5
# Require continuous QR absence before ending a session / clearing last_raw_data.
# Brief decoder flicker otherwise splits one action into a ghost Wrong + a real one
# (e.g. SF-60N 40 → 41 with duplicate consecutive screens).
QR_DISAPPEAR_DEBOUNCE = 0.35
# Dual-field: video QRs for A/B appear together but decoder can lag one ROI by ~1–2s.
# Pair within this window so both fields share the same action id and session clock.
QR_PAIR_WINDOW_SEC = 2.5
SAVE_EVERY_N_ACTIONS = 1

DEFAULT_RECORDINGS_DIR = "C:/Users/siama/Documents/simust_realtime_recordings"
SIMUST_PLAYER_DIRECTORY = "C:/Users/siama/Documents/simust_player"

DETECTION_CONF = 0.12  # lower to keep blurred / distant balls (GOAL motion blur)
MAX_PLAYERS = 2

COLOR_BALL = (255, 0, 0)
COLOR_PLAYER = (0, 255, 0)
COLOR_GOAL_LINE = (0, 255, 255)
COLOR_QR = (0, 255, 0)
COLOR_CORRECT = (0, 255, 0)
COLOR_LATE = (0, 255, 255)
COLOR_WRONG = (0, 0, 255)
COLOR_HIP = (0, 255, 255)  # cyan for hip point
COLOR_POLYGON = (0, 255, 0)  # green for polygon outline

STITCHED_WIDTH = 3840
STITCHED_HEIGHT = 1080
HALF_WIDTH = STITCHED_WIDTH // 2

VIZ_FILE = os.path.join(SIMUST_PLAYER_DIRECTORY, "visualization.txt")
SIM_FILE = os.path.join(SIMUST_PLAYER_DIRECTORY, "arena_simulation.txt")
PAUSE_FILE = os.path.join(SIMUST_PLAYER_DIRECTORY, "pause.txt")
DISPLAY_WIDTH = 1280
DISPLAY_HEIGHT = 720
SIM_FRAME_WIDTH = 1280
SIM_FRAME_HEIGHT = 360

try:
    import simust_fields
    from simust_fields import (
        POLYGON_POINTS,
        POLYGON_POINTS_A,
        POLYGON_POINTS_B,
        FIELD_A_SCREENS,
        FIELD_B_SCREENS,
        QR_ROI_A,
        QR_ROI_B,
        field_config,
        field_for_screens,
        normalize_field,
        polygon_for_field,
        qr_roi_for_field,
        screens_for_field,
        ALL_FIELDS,
    )
except Exception:
    simust_fields = None
    POLYGON_POINTS_A = [
        (12, 297), (10, 254), (37, 192), (58, 171), (109, 142), (139, 132),
        (204, 103), (444, 105), (503, 133), (532, 147), (582, 180), (609, 202),
        (634, 261), (623, 303), (469, 342), (79, 321), (12, 297),
    ]
    POLYGON_POINTS_B = [
        (654, 285), (652, 242), (675, 179), (695, 159), (748, 124), (776, 112),
        (833, 87), (1090, 87), (1144, 113), (1172, 125), (1225, 159), (1246, 181),
        (1269, 245), (1266, 286), (1105, 323), (717, 302), (654, 285),
    ]
    POLYGON_POINTS = POLYGON_POINTS_A
    FIELD_A_SCREENS = {"1", "2", "3", "4", "12", "13", "14"}
    FIELD_B_SCREENS = {"8", "9", "10", "11", "5", "6", "7"}
    QR_ROI_A = (0, 0, 1920, 540)
    QR_ROI_B = (1920, 0, 3840, 540)

    def field_config(field_id):
        return {"id": str(field_id or "A").upper()}

    def field_for_screens(screens):
        return "A"

    def normalize_field(value):
        return "A" if str(value or "A").upper().startswith("A") else "B"

    def polygon_for_field(field_id):
        return list(POLYGON_POINTS_A if normalize_field(field_id) != "B" else POLYGON_POINTS_B)

    def qr_roi_for_field(field_id):
        return QR_ROI_A if normalize_field(field_id) != "B" else QR_ROI_B

    def screens_for_field(field_id):
        return set(FIELD_A_SCREENS if normalize_field(field_id) != "B" else FIELD_B_SCREENS)

    ALL_FIELDS = {"A": field_config("A"), "B": field_config("B")}

# ============================================================================
# POLYGON ROI – Field A (left) and Field B (right)
# ============================================================================
# POLYGON_POINTS kept as Field A alias for older call sites.

# ============================================================================
# UPDATED ANALYSIS CONSTANTS (from Code A)
# ============================================================================
SCALE = 1.0
CORRECT_THRESHOLD = 40
LATE_SEARCH_DURATION = 2.5          # max late window (slow / long-gap videos)
LATE_SEARCH_MIN = 0.30              # never search less than this after a QR
LATE_SEARCH_GAP_MARGIN = 0.05       # leave a slice before the next action starts
SHORT_SESSION_SEC = 1.8             # T1.2-style QR windows
SHORT_FINISH_DIST = 35.0            # tighter mouth band on short tempo (in-session)
LATE_NEXT_PEEK = 0.22               # short tempo: early frames of next shot may finish previous
PEEK_BETWEEN_MAX_DIST = 140.0       # only peek if BETWEEN already closed toward the target
LATE_OVER_CORRECT_MARGIN = 8.0      # prefer clear Late over a weak in-session Correct
MIN_MOVEMENT_THRESHOLD = 33
MOVEMENT_RADIUS = 120
LEAVE_THRESHOLD = 200          # kept but not used in simplified check
SEARCH_FRAMES = 15
MIN_NEAR_FRAMES = 3            # kept but not used in simplified check
PRE_FRAMES = 6                 # kept but not used in simplified check
ENTRY_MARGIN = 1.0             # not used in simplified check

# Maximum distance to consider a PASS as a valid finish attempt
FINISH_DIST = 100   # px – increased from 100 to capture all correct actions
GOAL_POST_SLACK = 0.10  # posts of screens 1 / 7 / 8 count as the goal mouth
GOAL_POST_RADIUS = 30.0  # GOAL mouth endpoints
PASS_POST_RADIUS = 45.0  # PASS/TARGET graze near left/right keypoints
PRESS_POST_RADIUS = 70.0  # PRESS player can finish slightly past the short screen segment
BALL_TRACK_MAX_STEP_PX = 280  # ignore distant junk blobs as the same ball
BALL_RETURN_MAX_GAP_SEC = 0.75  # long dropout + far reappear = not a bounce (last-of-video Miss)
BALL_RETURN_GAP_NEAR_PX = 100  # after a long dropout, only keep the ball if it reappears nearby
BALL_RETURN_MAX_AFTER_ARRIVE = 1.25  # unused legacy; gap rule handles false returns
LATE_ANALYSIS_DELAY = LATE_SEARCH_DURATION  # default; live path uses dynamic_late_window when known

PIXEL_TO_METER_SCALE = 0.0259

try:
    import simust_homography
except Exception:
    simust_homography = None

# Screen-specific thresholds (PASS, TARGET, GOAL)
SCREEN_CORRECT_THRESHOLDS = {
    '2': 22,  '3': 30,  '4': 10,   '5': 10,   '6': 13,  '7': 22,
    '9': 22,  '10': 13, '11': 10,  '12': 10,  '13': 30, '14': 30,
    '1': 13,  '8': 13,
    '9L': 40,   '6L': 40,
}

# Screen-specific thresholds for PRESS
PRESS_SCREEN_THRESHOLDS = {
    '2': 120,   '3': 120,   '7': 120,   '9': 120,   '13': 120,   '14': 120,
}

# GOAL-specific thresholds (overrides)
GOAL_SCREEN_THRESHOLDS = {
    '8': 73,
    '1': 73,
    '7': 73,  # Field B right-edge goal / keypoint area
}

# Goal lines for 1280x360
GOAL_LINES = {
    "1": {"p0": (629, 293), "p1":  (12, 285)},
    "2": {"p0": (2, 298), "p1": (3, 253)},
    "3": {"p0": (22, 194), "p1": (44, 174)},
    "4": {"p0": (101, 140), "p1": (128, 129)},
    "5": {"p0": (1154, 112), "p1": (1180, 122)},
    "6": {"p0": (1239, 161), "p1": (1260, 180)},
    "7": {"p0":  (1275, 243), "p1": (1272, 287)},
    "8": {"p0": (1269, 276), "p1":  (652, 274)},
    "9": {"p0": (642, 286), "p1": (642, 242)},
    "10": {"p0":  (662, 178), "p1": (682, 158)},
    "11": {"p0":  (741, 121), "p1": (767, 111)},
    "12": {"p0": (513, 133), "p1": (541, 142)},
    "13": {"p0":  (599, 180), "p1":  (620, 198)},
    "14": {"p0": (637, 262), "p1": (636, 303)},
    "9L": {"p0": (642, 241), "p1": (647, 191)},
    "6L": {"p0": (1262, 181), "p1": (1273, 222)},
}

# Probe markers only. Scoring uses GOAL_LINES + proj_t + GOAL_SCREEN_THRESHOLDS.
SUGGESTED_GOAL_HEIGHT_PX = 90
GOAL_PROBE_TRAVEL_S = 1.9
GOAL_SHOT_TRAVEL_S = 0.85
# Real send origin (far pitch, top of the camera). Screen 8 is the live pack.
GOAL_SEND_ORIGIN = {
    "8": (961.0, 82.0),
    "1": (311.0, 103.0),
    "7": (1105.0, 200.0),  # approach Field B screen 7 (right vertical)
}
# Screens that count as full goal mouths (line + send origin + GOAL threshold band)
GOAL_MOUTH_SCREENS = frozenset({"1", "7", "8"})
# TARGET 6L/6R/9L/9R start from the same far-pitch point as GOAL screen 8.
TARGET_FROM_SCREEN8_ORIGIN = frozenset({"6L", "6R", "9L", "9R"})
GOAL_PROBE_ZONES = (
    "line_center",
    "post_a",
    "post_b",
    "upper_center_40",
    "upper_center_90",
    "upper_corner_a",
    "upper_corner_b",
    "outside_20",
    "outside_40",
    "outside_73",
    "outside_100",
    "outside_140",
    "wide_a",
    "wide_b",
)
# Live GOAL aims: in-band finishes vs out-of-band misses. Never only the midpoint.
GOAL_AIM_IN = (
    "line_center",
    "post_a",
    "post_b",
    "upper_center_40",
    "outside_20",
    "outside_40",
    "wide_a",
    "wide_b",
)
GOAL_AIM_OUT = (
    "upper_center_90",
    "upper_corner_a",
    "upper_corner_b",
    "sidestep",
)


def normalize_screen_id(screen):
    """Canonical screen id: '07'/'7' → '7', '9L' stays '9L'."""
    raw = str(screen or "").strip().upper()
    if not raw:
        return ""
    suffix = ""
    if raw.endswith("L") or raw.endswith("R"):
        suffix = raw[-1]
        raw = raw[:-1]
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return str(screen).strip()
    try:
        digits = str(int(digits))
    except ValueError:
        pass
    return digits + suffix


def screen_base_id(screen):
    return normalize_screen_id(screen).rstrip("LR")


def goal_send_origin(screens):
    """Where GOAL shots start. Prefer explicit goal-mouth screens 1 / 7 / 8."""
    ids = [screen_base_id(s) for s in (screens or [])]
    if "7" in ids:
        return GOAL_SEND_ORIGIN["7"]
    if "8" in ids:
        return GOAL_SEND_ORIGIN["8"]
    if "1" in ids:
        return GOAL_SEND_ORIGIN["1"]
    return GOAL_SEND_ORIGIN["8"]


def target_uses_screen8_origin(screens):
    for screen in screens or []:
        if str(screen).strip().upper() in TARGET_FROM_SCREEN8_ORIGIN:
            return True
    return False


def target_send_origin(screens):
    """TARGET 6L/6R/9L/9R launch from the GOAL screen-8 origin (961, 82)."""
    if target_uses_screen8_origin(screens):
        return GOAL_SEND_ORIGIN["8"]
    return None


def goal_up_axis(p0, p1):
    """Unit perpendicular toward image-up (into the net if the camera faces the goal)."""
    tx, ty = float(p1[0]) - float(p0[0]), float(p1[1]) - float(p0[1])
    nlen = math.hypot(tx, ty) or 1.0
    n1 = (-ty / nlen, tx / nlen)
    n2 = (ty / nlen, -tx / nlen)
    return n1 if n1[1] <= n2[1] else n2


def goal_along_axis(p0, p1):
    tx, ty = float(p1[0]) - float(p0[0]), float(p1[1]) - float(p0[1])
    nlen = math.hypot(tx, ty) or 1.0
    return (tx / nlen, ty / nlen), nlen


def goal_probe_xy(p0, p1, name, height=SUGGESTED_GOAL_HEIGHT_PX):
    along, width = goal_along_axis(p0, p1)
    up = goal_up_axis(p0, p1)
    mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
    pitch = (-up[0], -up[1])

    def add(origin, ax, ay, dist):
        return (origin[0] + ax * dist, origin[1] + ay * dist)

    table = {
        "line_center": mid,
        "post_a": (float(p0[0]), float(p0[1])),
        "post_b": (float(p1[0]), float(p1[1])),
        "upper_center_40": add(mid, up[0], up[1], 40.0),
        "upper_center_90": add(mid, up[0], up[1], height),
        "upper_corner_a": add(p0, up[0], up[1], height),
        "upper_corner_b": add(p1, up[0], up[1], height),
        "outside_20": add(mid, pitch[0], pitch[1], 20.0),
        "outside_40": add(mid, pitch[0], pitch[1], 40.0),
        "outside_73": add(mid, pitch[0], pitch[1], 73.0),
        "outside_100": add(mid, pitch[0], pitch[1], 100.0),
        "outside_140": add(mid, pitch[0], pitch[1], 140.0),
        "wide_a": add(p0, -along[0], -along[1], 28.0),
        "wide_b": add(p1, along[0], along[1], 28.0),
    }
    return table.get(name, mid)


def analyze_goal_with_context(action_id, screens, track, full_track, session_duration,
                              movement, direction, goal_lines):
    """GOAL only: software goal line + proj_t (posts included). No Miss.

    Arrival is in_goal_area: perpendicular distance <= screen threshold and a
    valid projection (proj_t in [-slack, 1+slack], posts count). Come-back is
    only a return toward the far-pitch send origin. Passing the line toward
    the camera is a finish, not a return.
    """
    arrival, depth = best_arrival_in_positions(track, screens, goal_lines, "GOAL")
    extra = [p for p in (full_track or []) if p[0] > session_duration + 1e-6]
    late_arrival, late_depth = (
        best_arrival_in_positions(extra, screens, goal_lines, "GOAL") if extra else (None, None)
    )

    result = "Wrong"
    winning_screen = "N/A"
    display_time = "-"
    display_duration = "-"
    min_dist_display = None
    best_proj_t = None
    evidence = None

    if arrival is not None:
        eff, t_hit, screen, proj = arrival
        if not returned_toward_origin(full_track, screen, screens, goal_lines, t_hit, depth):
            result = "Correct"
            evidence = (eff, t_hit, screen, proj)
    elif late_arrival is not None:
        eff, t_hit, screen, proj = late_arrival
        if not returned_toward_origin(full_track, screen, screens, goal_lines, t_hit, late_depth):
            result = "Late"
            evidence = (eff, t_hit, screen, proj)

    if evidence is not None:
        min_dist_display, t_hit, winning_screen, best_proj_t = evidence
        display_time = f"{t_hit:.3f}"
        display_duration = f"{session_duration:.3f}"

    aep = get_aep_orientation(screens, winning_screen)
    finishing_time_val = float(display_time) if display_time != "-" else 0.0
    ae = compute_action_efficiency("GOAL", result, finishing_time_val, movement)
    return {
        "Action ID": action_id,
        "Action": "GOAL",
        "Screens": ", ".join(screens),
        "Result": result,
        "Winning Screen": winning_screen,
        "Min Distance (px)": round(min_dist_display, 1) if min_dist_display is not None and min_dist_display != float("inf") else None,
        "Time of Min (s)": display_time,
        "Session Duration (s)": display_duration,
        "Movement (px)": movement,
        "Direction": direction,
        "AEP": aep,
        "proj_t": round(best_proj_t, 3) if best_proj_t is not None else None,
        "AE": ae,
    }

CAPTURE_TRIGGER_FILE = os.path.join(SIMUST_PLAYER_DIRECTORY, "capture_trigger.txt")
CAPTURE_OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================================
# MODEL PATHS
# ============================================================================
DETECTION_ENGINE_PATH = "best_b_p.engine"
POSE_ENGINE_PATH = "yolov8n-pose.engine"

# ============================================================================
# HELPER: Point-in-polygon test
# ============================================================================
def is_inside_polygon(pt, polygon):
    """Return True if point (x,y) is inside the polygon."""
    if not polygon:
        return True
    return cv2.pointPolygonTest(np.array(polygon, dtype=np.int32), (float(pt[0]), float(pt[1])), False) >= 0

# ============================================================================
# POSE DETECTOR CLASS (unchanged)
# ============================================================================

class PoseDetector:
    def __init__(self, engine_path: str):
        self.model = None
        if os.path.exists(engine_path):
            try:
                self.model = YOLO(engine_path)
                print(f"Pose model loaded: {engine_path}")
            except Exception as e:
                print(f"Failed to load pose engine: {e}")
        else:
            print(f"Pose engine not found at {engine_path} – pose will not be used.")

    def get_hip_point(self, cropped_img: np.ndarray) -> Optional[Tuple[float, float]]:
        """
        Run pose inference on a cropped image (player region) and return the
        average of left/right hip keypoints (indices 11 and 12).
        Returns (x, y) in the crop's local coordinates, or None if not found.
        """
        if self.model is None or cropped_img is None or cropped_img.size == 0:
            return None
        try:
            results = self.model(cropped_img, verbose=False, conf=0.3)
            if not results or len(results) == 0:
                return None
            result = results[0]
            if result.keypoints is None or len(result.keypoints) == 0:
                return None
            # Get keypoints for the first person
            kpts = result.keypoints.xy[0].cpu().numpy()  # (17, 2)
            # Keypoint indices: 11 = left hip, 12 = right hip
            left_hip = kpts[11]
            right_hip = kpts[12]
            # Check if either is (0,0) – invalid
            if (left_hip[0] == 0 and left_hip[1] == 0) or (right_hip[0] == 0 and right_hip[1] == 0):
                return None
            # Average
            hip_x = (left_hip[0] + right_hip[0]) / 2.0
            hip_y = (left_hip[1] + right_hip[1]) / 2.0
            return (hip_x, hip_y)
        except Exception as e:
            return None

# ============================================================================
# 1-EURO FILTER (unchanged)
# ============================================================================

class OneEuroFilter:
    """Simple 1-Euro filter for real-time smoothing."""
    def __init__(self, min_cutoff=1.0, beta=0.0, d_cutoff=1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.x_prev = None
        self.dx_prev = None
        self.t_prev = None

    def filter(self, x, t=None):
        if t is None:
            t = time.time()
        if self.x_prev is None:
            self.x_prev = x
            self.dx_prev = 0.0
            self.t_prev = t
            return x
        dt = max(0.001, t - self.t_prev)
        dx = (x - self.x_prev) / dt
        d_cutoff = self.d_cutoff + self.beta * abs(dx)
        tau = 1.0 / (2.0 * 3.14159 * (self.min_cutoff + d_cutoff))
        alpha = 1.0 / (1.0 + tau / dt)
        x_filt = alpha * x + (1 - alpha) * self.x_prev
        self.x_prev = x_filt
        self.dx_prev = dx
        self.t_prev = t
        return x_filt

# ============================================================================
# DETECTION TRACKER (modified to filter players by polygon)
# ============================================================================

class DetectionTracker:
    def __init__(self, require_models=True):
        self.detection_model = None
        self.pose_detector = PoseDetector("")
        self.detection_conf = DETECTION_CONF
        self.max_players = MAX_PLAYERS
        self.half_width = HALF_WIDTH
        self.filter_x = OneEuroFilter(min_cutoff=1.0, beta=0.5)
        self.filter_y = OneEuroFilter(min_cutoff=1.0, beta=0.5)
        self.filters_by_field = {
            "A": (OneEuroFilter(min_cutoff=1.0, beta=0.5), OneEuroFilter(min_cutoff=1.0, beta=0.5)),
            "B": (OneEuroFilter(min_cutoff=1.0, beta=0.5), OneEuroFilter(min_cutoff=1.0, beta=0.5)),
        }
        self.total_balls_detected = 0
        self.total_players_detected = 0
        self.frame_process_count = 0
        self.last_fps_time = time.time()
        self.current_fps = 0
        self.polygon = POLYGON_POINTS_A
        self.polygons = {"A": POLYGON_POINTS_A, "B": POLYGON_POINTS_B}

        cuda_ok = torch.cuda.is_available()
        engine_ok = os.path.exists(DETECTION_ENGINE_PATH)
        if not cuda_ok or not engine_ok:
            msg = "CUDA not available." if not cuda_ok else f"{DETECTION_ENGINE_PATH} not found."
            if require_models:
                print(f"ERROR: {msg} .engine files require GPU.")
                sys.exit(1)
            print(f"Arena simulation: skipping detection models ({msg})")
            self.pose_detector = PoseDetector("")
            return
        try:
            self.detection_model = YOLO(DETECTION_ENGINE_PATH)
            print(f"Detection model loaded: {DETECTION_ENGINE_PATH}")
        except Exception as e:
            print(f"Failed to load detection engine: {e}")
            if require_models:
                sys.exit(1)
            print("Arena simulation: continuing without detection model.")
            return
        if os.path.exists(POSE_ENGINE_PATH):
            self.pose_detector = PoseDetector(POSE_ENGINE_PATH)

    def detect_objects(self, frame):
        """Balls on both halves; players on left (Field A) and right (Field B) polygons."""
        if self.detection_model is None:
            return [], []

        orig_h, orig_w = frame.shape[:2]
        mid_x = orig_w // 2

        left_half = frame[:, :mid_x]
        right_half = frame[:, mid_x:]

        balls = []
        players = []

        try:
            results_left = self.detection_model(left_half, verbose=False, conf=self.detection_conf, iou=0.45)
            for result in results_left:
                if result.boxes is None:
                    continue
                for box in result.boxes:
                    class_id = int(box.cls)
                    confidence = float(box.conf)
                    xyxy = box.xyxy[0].cpu().numpy()
                    x1 = int(xyxy[0]); y1 = int(xyxy[1]); x2 = int(xyxy[2]); y2 = int(xyxy[3])
                    x1 = max(0, min(x1, mid_x-1)); y1 = max(0, min(y1, orig_h-1))
                    x2 = max(x1+1, min(x2, mid_x)); y2 = max(y1+1, min(y2, orig_h))
                    center = [(x1+x2)//2, (y1+y2)//2]
                    det = {
                        'center': center, 'bbox': [x1, y1, x2, y2],
                        'confidence': round(confidence, 3), 'field': 'A',
                    }
                    if class_id == 0:
                        balls.append(det)
                    elif class_id == 1:
                        players.append(det)

            results_right = self.detection_model(right_half, verbose=False, conf=self.detection_conf, iou=0.45)
            for result in results_right:
                if result.boxes is None:
                    continue
                for box in result.boxes:
                    class_id = int(box.cls)
                    confidence = float(box.conf)
                    xyxy = box.xyxy[0].cpu().numpy()
                    x1 = int(xyxy[0]) + mid_x
                    y1 = int(xyxy[1])
                    x2 = int(xyxy[2]) + mid_x
                    y2 = int(xyxy[3])
                    x1 = max(mid_x, min(x1, orig_w-1)); y1 = max(0, min(y1, orig_h-1))
                    x2 = max(x1+1, min(x2, orig_w)); y2 = max(y1+1, min(y2, orig_h))
                    center = [(x1+x2)//2, (y1+y2)//2]
                    det = {
                        'center': center, 'bbox': [x1, y1, x2, y2],
                        'confidence': round(confidence, 3),
                        'field': 'B',
                    }
                    if class_id == 0:
                        balls.append(det)
                    elif class_id == 1:
                        players.append(det)
        except Exception:
            pass

        # Filter players into Field A / Field B play zones
        poly_a = (self.polygons or {}).get("A") or self.polygon
        poly_b = (self.polygons or {}).get("B")
        filtered = []
        for p in players:
            feet = ((p['bbox'][0] + p['bbox'][2]) // 2, p['bbox'][3])
            in_a = bool(poly_a) and is_inside_polygon(feet, poly_a)
            in_b = bool(poly_b) and is_inside_polygon(feet, poly_b)
            if in_a and not in_b:
                p['field'] = 'A'
                filtered.append(p)
            elif in_b and not in_a:
                p['field'] = 'B'
                filtered.append(p)
            elif in_a and in_b:
                # Prefer the half the bbox center sits in
                p['field'] = 'A' if p['center'][0] < mid_x else 'B'
                filtered.append(p)
            elif not poly_a and not poly_b:
                filtered.append(p)
        players = filtered

        players.sort(key=lambda p: (p['bbox'][2]-p['bbox'][0]) * (p['bbox'][3]-p['bbox'][1]), reverse=True)
        # Keep up to 2 players total (one per field preferred)
        by_field = {"A": [], "B": []}
        other = []
        for p in players:
            fid = p.get("field")
            if fid in by_field and len(by_field[fid]) < 1:
                by_field[fid].append(p)
            else:
                other.append(p)
        players = by_field["A"] + by_field["B"]
        for p in other:
            if len(players) >= max(2, self.max_players):
                break
            players.append(p)

        self.total_balls_detected += len(balls)
        self.total_players_detected += len(players)

        return balls, players

    def get_player_tracking_point_for_field(self, frame, players, field_id, current_timestamp, session_start_timestamp):
        field_players = [p for p in (players or []) if p.get("field") == field_id] or [
            p for p in (players or [])
            if (field_id == "A" and p["center"][0] < frame.shape[1] // 2)
            or (field_id == "B" and p["center"][0] >= frame.shape[1] // 2)
        ]
        fx, fy = self.filters_by_field.get(field_id, (self.filter_x, self.filter_y))
        return self.get_player_tracking_point(
            frame, field_players, current_timestamp, session_start_timestamp,
            filter_x=fx, filter_y=fy,
        )

    def get_player_tracking_point(self, frame, players, current_timestamp, session_start_timestamp,
                                  filter_x=None, filter_y=None):
        """
        Returns a stable tracking point (x, y) for the main player.
        Uses pose hip keypoints if available, else returns (None, None).
        NO FALLBACK to bounding-box bottom-centre.
        """
        if not players:
            return None, None

        # Choose the largest player (closest to camera)
        main_player = max(players, key=lambda p: (p['bbox'][2]-p['bbox'][0]) * (p['bbox'][3]-p['bbox'][1]))
        x1, y1, x2, y2 = main_player['bbox']
        crop = frame[y1:y2, x1:x2]

        hip_point = None
        if crop.size > 0 and self.pose_detector.model is not None:
            hip = self.pose_detector.get_hip_point(crop)
            if hip is not None:
                # Convert local crop coords back to full frame coords
                hip_x = x1 + hip[0]
                hip_y = y1 + hip[1]
                hip_point = (hip_x, hip_y)

        if hip_point is None:
            # No valid pose – return None (skip this frame for EOP)
            return None, None

        # Apply 1‑Euro smoothing (per-field filters when dual-field tracking)
        fx = filter_x if filter_x is not None else self.filter_x
        fy = filter_y if filter_y is not None else self.filter_y
        rel_time = current_timestamp - session_start_timestamp
        smooth_x = fx.filter(hip_point[0], rel_time)
        smooth_y = fy.filter(hip_point[1], rel_time)

        return smooth_x, smooth_y

    def update_fps(self):
        current_time = time.time()
        elapsed = current_time - self.last_fps_time
        if elapsed >= 1.0:
            self.current_fps = self.frame_process_count / elapsed
            self.frame_process_count = 0
            self.last_fps_time = current_time
        self.frame_process_count += 1
        return self.current_fps

    def increment_frame_count(self):
        self.frame_process_count += 1

    def flush_resources(self):
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

# ============================================================================
# UPDATED ANALYSIS FUNCTIONS (from code A – simplified logic)
# ============================================================================

def post_radius_for(action_type):
    if action_type == "GOAL":
        return GOAL_POST_RADIUS
    if action_type == "PRESS":
        return PRESS_POST_RADIUS
    return PASS_POST_RADIUS


def finishing_return_origin(action_type, screens, track):
    """Player/send side of a come-back. Junk lights on the far camera are not a return."""
    if action_type == "GOAL":
        return goal_send_origin(screens)
    if action_type == "TARGET":
        origin = target_send_origin(screens)
        if origin is not None:
            return origin
    if track:
        return (float(track[0][1]), float(track[0][2]))
    return ArenaSimulator.BALL_HOME


def append_continuing_ball(
    track,
    extra,
    max_step_px=BALL_TRACK_MAX_STEP_PX,
    max_gap_sec=BALL_RETURN_MAX_GAP_SEC,
    gap_near_px=BALL_RETURN_GAP_NEAR_PX,
):
    """Keep one ball identity.

    Far jumps are ignored. A long dropout that reappears far away (typical
    last-of-video BETWEEN motion) ends the track. A brief dropout near the
    screen can still continue into a real bounce.
    """
    merged = list(track or [])
    extra_f = extra or []
    if extra_f and len(extra_f) >= 3:
        extra_f = filter_static_ball_positions(extra_f) or []
    prev = (merged[-1][0], merged[-1][1], merged[-1][2]) if merged else None
    for t, x, y in extra_f:
        if prev is not None:
            dt = float(t) - float(prev[0])
            dist = math.hypot(float(x) - prev[1], float(y) - prev[2])
            if dist > max_step_px:
                continue
            if dt > max_gap_sec and dist > gap_near_px:
                break
        merged.append((t, x, y))
        prev = (float(t), float(x), float(y))
    return merged


def get_positions_from_data(data, key, scale=SCALE):
    positions = []
    for entry in data:
        t = entry.get('t', 0.0)
        if key in entry and entry[key]:
            for pos in entry[key]:
                if isinstance(pos, list) and len(pos) >= 2:
                    try:
                        x = int(float(pos[0]) * scale)
                        y = int(float(pos[1]) * scale)
                        positions.append((t, x, y))
                    except (ValueError, TypeError):
                        continue
    return positions

def get_unique_trajectory(positions):
    seen = set()
    unique = []
    for t, x, y in positions:
        key = (x, y)
        if key not in seen:
            seen.add(key)
            unique.append((t, x, y))
    return unique

def compute_projection(point, p0, p1):
    x0, y0 = point
    x1, y1 = p0
    x2, y2 = p1
    vx, vy = x2 - x1, y2 - y1
    len2 = vx*vx + vy*vy
    if len2 < 1e-6:
        return float('inf'), 0.0, float('inf'), float('inf')
    proj_t = ((x0 - x1)*vx + (y0 - y1)*vy) / len2
    px = x1 + proj_t * vx
    py = y1 + proj_t * vy
    dist = math.hypot(x0 - px, y0 - py)
    dist_left = math.hypot(x0 - x1, y0 - y1)
    dist_right = math.hypot(x0 - x2, y0 - y2)
    return dist, proj_t, dist_left, dist_right

def get_effective_distance(point, p0, p1):
    dist_seg, proj_t, d_left, d_right = compute_projection(point, p0, p1)
    if proj_t < 0:
        eff_dist = d_left
    elif proj_t > 1:
        eff_dist = d_right
    else:
        eff_dist = dist_seg
    return eff_dist, proj_t

def get_screen_info(screen, goal_lines):
    screen_str = normalize_screen_id(screen)
    base_screen = screen_base_id(screen)
    if screen_str in goal_lines:
        line = goal_lines[screen_str]
    elif base_screen in goal_lines:
        line = goal_lines[base_screen]
    elif str(screen) in goal_lines:
        line = goal_lines[str(screen)]
    else:
        return None, None
    return line['p0'], line['p1']

def remove_static_positions(positions):
    if not positions or len(positions) < 5:
        return positions
    rounded = [(round(x/5)*5, round(y/5)*5) for _, x, y in positions]
    counter = Counter(rounded)
    total_frames = len(positions)
    static_threshold = 0.10 * total_frames
    static_cells = {cell for cell, count in counter.items() if count > static_threshold}
    if not static_cells:
        return positions
    filtered = []
    for t, x, y in positions:
        cell = (round(x/5)*5, round(y/5)*5)
        if cell not in static_cells:
            filtered.append((t, x, y))
    return filtered

def is_ball_moving(positions, min_movement=MIN_MOVEMENT_THRESHOLD):
    if not positions or len(positions) < 2:
        return False
    unique_positions = get_unique_trajectory(positions)
    if len(unique_positions) < 2:
        return False
    max_x = max(p[1] for p in unique_positions)
    min_x = min(p[1] for p in unique_positions)
    max_y = max(p[2] for p in unique_positions)
    min_y = min(p[2] for p in unique_positions)
    total_movement = math.hypot(max_x - min_x, max_y - min_y)
    return total_movement > min_movement

def filter_static_ball_positions(positions):
    if not positions or len(positions) < 3:
        return positions
    filtered = remove_static_positions(positions)
    if not filtered or len(filtered) < 3:
        if is_ball_moving(positions):
            return positions
        else:
            return []
    if not is_ball_moving(filtered):
        if is_ball_moving(positions):
            return positions
        else:
            return []
    return filtered

def filter_positions_near_goal_lines(positions, screens, goal_lines, radius=MOVEMENT_RADIUS):
    if not positions:
        return []
    near_positions = []
    for screen in screens:
        p0, p1 = get_screen_info(screen, goal_lines)
        if p0 is None:
            continue
        for t, x, y in positions:
            dist, _, _, _ = compute_projection((x, y), p0, p1)
            if dist <= radius:
                near_positions.append((t, x, y))
    if not near_positions:
        return []
    seen = set()
    unique_near = []
    for t, x, y in near_positions:
        key = (x, y)
        if key not in seen:
            seen.add(key)
            unique_near.append((t, x, y))
    return unique_near

def find_min_distance_to_screens(positions, screens, goal_lines, require_movement=True, use_near_filter=False):
    if not positions:
        return None, float('inf'), None, None
    filtered = filter_static_ball_positions(positions)
    if not filtered:
        return None, float('inf'), None, None

    if require_movement:
        if use_near_filter:
            near_positions = filter_positions_near_goal_lines(filtered, screens, goal_lines)
        else:
            near_positions = filtered
        if not is_ball_moving(near_positions):
            return None, float('inf'), None, None

    unique_positions = get_unique_trajectory(filtered)

    best_screen = None
    best_dist = float('inf')
    best_time = None
    best_proj_t = None

    for screen in screens:
        p0, p1 = get_screen_info(screen, goal_lines)
        if p0 is None:
            continue
        min_dist = float('inf')
        min_time = None
        min_proj = None
        for t, x, y in unique_positions:
            eff_dist, proj_t = get_effective_distance((x, y), p0, p1)
            if eff_dist < min_dist:
                min_dist = eff_dist
                min_time = t
                min_proj = proj_t
        if min_dist < best_dist:
            best_dist = min_dist
            best_screen = screen
            best_time = min_time
            best_proj_t = min_proj

    return best_screen, best_dist, best_time, best_proj_t

def get_threshold_for_screen(screen: str, action_type: str) -> float:
    if action_type == 'PRESS':
        if screen in PRESS_SCREEN_THRESHOLDS:
            return PRESS_SCREEN_THRESHOLDS[screen]
        base = screen.rstrip('LR')
        return PRESS_SCREEN_THRESHOLDS.get(base, 100)

    if action_type == 'GOAL':
        if screen in GOAL_SCREEN_THRESHOLDS:
            return GOAL_SCREEN_THRESHOLDS[screen]
        if screen in SCREEN_CORRECT_THRESHOLDS:
            return SCREEN_CORRECT_THRESHOLDS[screen]
        base = screen.rstrip('LR')
        return SCREEN_CORRECT_THRESHOLDS.get(base, CORRECT_THRESHOLD)

    # PASS, TARGET
    if screen in SCREEN_CORRECT_THRESHOLDS:
        return SCREEN_CORRECT_THRESHOLDS[screen]
    base = screen.rstrip('LR')
    return SCREEN_CORRECT_THRESHOLDS.get(base, CORRECT_THRESHOLD)

# ============================================================================
# GOAL-specific late search – no time limit, no filtering, no movement check
# ============================================================================
def search_goal_late(current_index: int, all_data: List[dict],
                     screens: List[str], goal_lines: Dict,
                     key: str, action_end_time: datetime) -> Tuple[bool, Optional[str], Optional[float], float, Optional[float]]:
    """
    Searches all blocks after current_index for any ball position that:
    - Has valid projection (0 <= proj_t <= 1)
    - Distance to goal line <= threshold for that screen
    Returns (found, screen, time_offset_from_action_end, distance, proj_t)
    """
    if current_index + 1 >= len(all_data):
        return False, None, None, float('inf'), None

    best_screen = None
    best_dist = float('inf')
    best_time_offset = None
    best_proj_t = None

    def get_goal_threshold(screen: str) -> float:
        return get_threshold_for_screen(screen, 'GOAL')

    for idx in range(current_index + 1, len(all_data)):
        block = all_data[idx]
        block_start_str = block.get('start_time')
        if not block_start_str:
            continue
        try:
            block_start = datetime.strptime(block_start_str, "%H:%M:%S.%f")
        except:
            continue

        block_data = block.get('data', [])
        if not block_data:
            continue

        # Raw ball positions – no static filter, no movement check
        positions = get_positions_from_data(block_data, key, SCALE)
        if not positions:
            continue

        for t, x, y in positions:
            for screen in screens:
                p0, p1 = get_screen_info(screen, goal_lines)
                if p0 is None:
                    continue
                eff_dist, proj_t = get_effective_distance((x, y), p0, p1)
                threshold = get_goal_threshold(screen)
                if not in_goal_area((x, y), p0, p1, threshold):
                    continue
                if eff_dist <= threshold:
                    pos_abs_time = block_start + timedelta(seconds=t)
                    offset = (pos_abs_time - action_end_time).total_seconds()
                    if eff_dist < best_dist:
                        best_dist = eff_dist
                        best_screen = screen
                        best_time_offset = offset
                        best_proj_t = proj_t

    if best_screen is not None:
        return True, best_screen, best_time_offset, best_dist, best_proj_t
    else:
        return False, None, None, float('inf'), None

# ============================================================================
# Late search for PASS / TARGET / PRESS – respects time limit and movement
# ============================================================================
def _parse_block_start(block) -> Optional[datetime]:
    start_str = (block or {}).get("start_time")
    if not start_str:
        return None
    try:
        return datetime.strptime(str(start_str), "%H:%M:%S.%f")
    except Exception:
        try:
            return datetime.strptime(str(start_str)[:15], "%H:%M:%S.%f")
        except Exception:
            return None


def is_scored_action_block(block) -> bool:
    action = str((block or {}).get("action") or "").upper()
    ident = str((block or {}).get("id") or "")
    return action in ("PASS", "TARGET", "PRESS", "GOAL") and ident.startswith("S")


def wall_gap_until_next_action(action_index: int, all_data: List[dict], action_end_time: Optional[datetime]) -> Optional[float]:
    """Wall-clock seconds until the next scored action starts (ignores BETWEEN length)."""
    if action_end_time is None or not all_data:
        return None
    for idx in range(int(action_index) + 1, len(all_data)):
        block = all_data[idx]
        if not is_scored_action_block(block):
            continue
        nxt = _parse_block_start(block)
        if nxt is None:
            continue
        return max(0.0, (nxt - action_end_time).total_seconds())
    return None


def between_duration_until_next(action_index: int, all_data: List[dict]) -> Optional[float]:
    """Max relative t in BETWEEN_SESSIONS blocks before the next scored action."""
    if not all_data:
        return None
    best = None
    for idx in range(int(action_index) + 1, len(all_data)):
        block = all_data[idx]
        if is_scored_action_block(block):
            break
        action = str((block or {}).get("action") or "").upper()
        if action != "BETWEEN_SESSIONS":
            continue
        data = block.get("data") or []
        if not data:
            continue
        tmax = max(float(e.get("t") or 0.0) for e in data)
        best = tmax if best is None else max(best, tmax)
    return best


def gap_until_next_action(action_index: int, all_data: List[dict], action_end_time: Optional[datetime]) -> Optional[float]:
    """Seconds available for late search until the next scored action.

    Fast SF-30N often stamps action end_time equal to the next QR start (wall gap 0).
    In that case use the BETWEEN block duration (real inter-shot frames).
    """
    if not all_data:
        return None
    wall_gap = wall_gap_until_next_action(action_index, all_data, action_end_time)
    between_gap = between_duration_until_next(action_index, all_data)
    if between_gap is not None and (wall_gap is None or wall_gap < float(LATE_SEARCH_MIN)):
        return float(between_gap)
    if wall_gap is not None:
        return float(wall_gap)
    return float(between_gap) if between_gap is not None else None


def is_short_tempo_action(
    action_index: int,
    all_data: List[dict],
    action_end_time: Optional[datetime],
    wall_session: Optional[float] = None,
) -> bool:
    """True for T1.2-style spacing (short BETWEEN / zero wall gap to next QR)."""
    wall_gap = wall_gap_until_next_action(action_index, all_data, action_end_time)
    between_gap = between_duration_until_next(action_index, all_data)
    if wall_gap is not None:
        if wall_gap < float(LATE_SEARCH_MIN):
            return bool(between_gap is not None and 0 < float(between_gap) < 1.25)
        return bool(0 < float(wall_gap) < 1.25)
    if wall_session is not None:
        return bool(0 < float(wall_session) < float(SHORT_SESSION_SEC))
    return False


def dynamic_late_window(
    action_index: int,
    all_data: List[dict],
    action_end_time: Optional[datetime],
    session_duration: Optional[float] = None,
) -> float:
    """Late/return search window scaled to the real BETWEEN gap.

    Slow/long-gap videos keep up to 2.5s. Fast T1.2 (~0.5–0.9s gap) shrinks so
    the next shot's ball is not counted as this shot's Late/Correct return.
    """
    gap = gap_until_next_action(action_index, all_data, action_end_time)
    if gap is None:
        return float(LATE_SEARCH_DURATION)
    return float(
        min(
            float(LATE_SEARCH_DURATION),
            max(float(LATE_SEARCH_MIN), float(gap) - float(LATE_SEARCH_GAP_MARGIN)),
        )
    )


def dynamic_analysis_delay(recent_gap_sec: Optional[float] = None, session_duration: Optional[float] = None) -> float:
    """Live label delay: wait for BETWEEN frames, but not longer than the tempo allows."""
    if recent_gap_sec is None and session_duration is None:
        return float(LATE_ANALYSIS_DELAY)
    gap = float(recent_gap_sec) if recent_gap_sec is not None else float(LATE_SEARCH_DURATION)
    return float(
        min(
            float(LATE_SEARCH_DURATION),
            max(float(LATE_SEARCH_MIN), gap - float(LATE_SEARCH_GAP_MARGIN)),
        )
    )


def _between_approach_stats(block, screens) -> Tuple[bool, float]:
    """Whether BETWEEN ball closes on a target, and how close it got."""
    positions = get_positions_from_data((block or {}).get("data") or [], "b", SCALE)
    filtered = filter_static_ball_positions(positions) or positions
    if len(filtered) < 2:
        return False, float("inf")
    best_improve = -1e9
    best_min = float("inf")
    for screen in screens or []:
        p0, p1 = get_screen_info(screen, GOAL_LINES)
        if p0 is None:
            continue
        dists = [compute_projection((x, y), p0, p1)[0] for _, x, y in filtered]
        best_improve = max(best_improve, float(dists[0]) - float(dists[-1]))
        best_min = min(best_min, min(dists))
    return best_improve > 15.0, float(best_min)


def _late_hit_on_send_side(filtered, screen, screens, action_type, thresh):
    """Late contact must still be on the send/player side (or bounce back)."""
    p0, p1 = get_screen_info(screen, GOAL_LINES)
    if p0 is None:
        return False, None, None, None
    origin = finishing_return_origin(action_type, screens, filtered)
    post_r = post_radius_for(action_type)
    first_side = None
    best_return = None
    for t, x, y in filtered:
        if not in_goal_area((x, y), p0, p1, thresh, post_radius=post_r):
            continue
        eff, proj = get_effective_distance((x, y), p0, p1)
        if on_origin_side((x, y), p0, p1, origin):
            if first_side is None or eff < first_side[0]:
                first_side = (eff, t, proj)
        else:
            came = returned_toward_origin(
                filtered, screen, screens, GOAL_LINES, t, thresh,
                origin=origin, post_radius=post_r,
            )
            if came and (best_return is None or eff < best_return[0]):
                best_return = (eff, t, proj)
    pick = first_side or best_return
    if pick is None:
        return False, None, None, None
    return True, pick[1], pick[0], pick[2]


def search_late_across_blocks(current_index: int, all_data: List[dict],
                               screens: List[str], goal_lines: Dict,
                               key: str, action_end_time: datetime,
                               action_type: str,
                               late_window: Optional[float] = None,
                               session_duration: Optional[float] = None) -> Tuple[bool, Optional[str], Optional[float], float, Optional[float]]:
    """
    Returns: (found, screen, time_offset, distance, proj_t)
    Used for non-GOAL actions.

    Never steals a deep finish from the next scored action. On short tempo, a
    gated peek into the first LATE_NEXT_PEEK seconds of the next shot covers
    finishes that land as the next QR appears (common on T1.2).
    """
    if current_index + 1 >= len(all_data):
        return False, None, None, float('inf'), None

    window = float(LATE_SEARCH_DURATION if late_window is None else late_window)
    short = session_duration is not None and 0 < float(session_duration) < float(SHORT_SESSION_SEC)
    thresh = float(FINISH_DIST)
    best_screen = None
    best_dist = float('inf')
    best_time = None
    best_proj_t = None
    between_block = None
    bet_approach = False
    bet_min = float('inf')

    for idx in range(current_index + 1, len(all_data)):
        block = all_data[idx]
        scored = is_scored_action_block(block)
        action = str((block or {}).get("action") or "").upper()
        block_start = _parse_block_start(block)
        if block_start is None:
            continue
        offset = (block_start - action_end_time).total_seconds()

        if action == "BETWEEN_SESSIONS":
            between_block = block
            bet_approach, bet_min = _between_approach_stats(block, screens)

        if scored:
            allow_peek = short and (
                between_block is None
                or (bet_approach and bet_min <= float(PEEK_BETWEEN_MAX_DIST))
            )
            if not allow_peek:
                break
            block_data = [
                e for e in (block.get("data") or [])
                if float(e.get("t") or 0.0) <= float(LATE_NEXT_PEEK)
            ]
            if not block_data:
                break
        else:
            if offset > window:
                break
            block_data = block.get("data") or []

        if not block_data:
            if scored:
                break
            continue

        positions = get_positions_from_data(block_data, key, SCALE)
        if not positions:
            if scored:
                break
            continue

        filtered = filter_static_ball_positions(positions)
        if not filtered:
            if scored:
                break
            continue
        if not is_ball_moving(filtered):
            if scored:
                break
            continue

        for screen in screens:
            if short:
                ok, arrive_t, eff, proj = _late_hit_on_send_side(
                    filtered, screen, screens, action_type, thresh
                )
                if not ok:
                    continue
            else:
                best_screen_block, best_dist_block, best_time_block, best_proj_block = find_min_distance_to_screens(
                    filtered, [screen], goal_lines, require_movement=False
                )
                if best_screen_block is None:
                    continue
                p0, p1 = get_screen_info(screen, goal_lines)
                hit = False
                if p0 is not None:
                    for t, x, y in filtered:
                        if in_goal_area(
                            (x, y), p0, p1, thresh, post_radius=post_radius_for(action_type)
                        ):
                            hit = True
                            break
                if not hit or best_dist_block > thresh:
                    continue
                arrive_t = best_time_block
                eff = best_dist_block
                proj = best_proj_block

            if scored or offset < float(LATE_SEARCH_MIN):
                absolute_time = float(arrive_t or 0.0)
            else:
                absolute_time = float(offset) + float(arrive_t or 0.0)

            if absolute_time <= window and eff < best_dist:
                best_dist = float(eff)
                best_screen = screen
                best_time = absolute_time
                best_proj_t = proj

        if scored:
            break

    if best_screen is not None:
        return True, best_screen, best_time, best_dist, best_proj_t
    return False, None, None, float('inf'), None


def analyze_movement(unique_positions):
    if len(unique_positions) < 2:
        return 0, 'NONE'
    start_x = unique_positions[0][1]
    max_x = max(p[1] for p in unique_positions)
    min_x = min(p[1] for p in unique_positions)
    if max_x - start_x > 100:
        return max_x - start_x, 'RIGHT'
    elif start_x - min_x > 100:
        return start_x - min_x, 'LEFT'
    else:
        return 0, 'NONE'

def get_positions_from_blocks_after(current_index, all_data, key, action_end_time, session_start_time, time_window=1.0):
    extra_positions = []
    for idx in range(current_index + 1, len(all_data)):
        block = all_data[idx]
        if is_scored_action_block(block):
            break
        block_start_str = block.get('start_time')
        if not block_start_str:
            continue
        try:
            block_start = datetime.strptime(block_start_str, "%H:%M:%S.%f")
        except:
            continue

        offset = (block_start - action_end_time).total_seconds()
        if offset > time_window:
            break

        block_data = block.get('data', [])
        if not block_data:
            continue

        positions = get_positions_from_data(block_data, key, SCALE)
        if not positions:
            continue

        time_offset = (block_start - session_start_time).total_seconds()
        for t, x, y in positions:
            if offset + t > time_window:
                continue
            extra_positions.append((t + time_offset, x, y))

    return extra_positions

# ================================================================
# SIMPLIFIED check_ball_return – only presence check (from code A)
# ================================================================
def check_ball_return(positions, screen, goal_lines, min_time, threshold, session_duration,
                      search_frames=SEARCH_FRAMES, entry_threshold=None):
    """True if the tracked point leaves the goal area after arriving (come-back)."""
    depth = entry_threshold if entry_threshold is not None else threshold
    return departed_goal_area(positions, screen, goal_lines, min_time, depth)


def arrival_depth_for(screen, action_type, session_duration=None):
    threshold = get_threshold_for_screen(screen, action_type)
    if action_type == "GOAL":
        return float(threshold)
    finish = float(FINISH_DIST)
    if session_duration is not None and session_duration > 0 and session_duration < SHORT_SESSION_SEC:
        # T1.2: the wide 100px band creates false Correct from near-screen noise.
        finish = float(SHORT_FINISH_DIST)
    return float(max(finish, threshold))


def in_goal_area(point, p0, p1, depth, post_radius=GOAL_POST_RADIUS):
    """Goal mouth including posts. Cameras face screens 1 / 7 / 8."""
    dist, proj_t, d_left, d_right = compute_projection(point, p0, p1)
    if dist <= depth and (-GOAL_POST_SLACK) <= proj_t <= (1.0 + GOAL_POST_SLACK):
        return True
    post_r = min(float(depth), float(post_radius))
    return d_left <= post_r or d_right <= post_r


def first_arrival_time(positions, screen, goal_lines, depth, post_radius=GOAL_POST_RADIUS):
    p0, p1 = get_screen_info(screen, goal_lines)
    if p0 is None:
        return None
    for t, x, y in positions:
        if in_goal_area((x, y), p0, p1, depth, post_radius=post_radius):
            return t
    return None


def best_arrival_in_positions(positions, screens, goal_lines, action_type, session_duration=None):
    best = None
    depth_used = None
    post_r = post_radius_for(action_type)
    for screen in screens:
        p0, p1 = get_screen_info(screen, goal_lines)
        if p0 is None:
            continue
        depth = arrival_depth_for(screen, action_type, session_duration=session_duration)
        for t, x, y in positions:
            if not in_goal_area((x, y), p0, p1, depth, post_radius=post_r):
                continue
            eff, proj = get_effective_distance((x, y), p0, p1)
            if best is None or eff < best[0]:
                best = (eff, t, screen, proj)
                depth_used = depth
    return best, depth_used


def departed_goal_area(positions, screen, goal_lines, arrive_time, depth, post_radius=GOAL_POST_RADIUS):
    """True if the object leaves the goal area after the arrival time."""
    p0, p1 = get_screen_info(screen, goal_lines)
    if p0 is None or arrive_time is None:
        return False
    leave_depth = float(depth) * 1.15
    seen_in = False
    for t, x, y in positions:
        if t + 1e-6 < arrive_time:
            continue
        if in_goal_area((x, y), p0, p1, depth, post_radius=post_radius):
            seen_in = True
            continue
        if seen_in and t > arrive_time + 0.08 and not in_goal_area((x, y), p0, p1, leave_depth, post_radius=post_radius):
            return True
    return False


def line_side_sign(point, p0, p1):
    """Signed cross product: which side of directed line p0→p1 the point is on."""
    return (float(p1[0]) - float(p0[0])) * (float(point[1]) - float(p0[1])) - (
        (float(p1[1]) - float(p0[1])) * (float(point[0]) - float(p0[0]))
    )


def on_origin_side(point, p0, p1, origin):
    """True when point is on the same side of the goal line as the send origin."""
    return line_side_sign(point, p0, p1) * line_side_sign(origin, p0, p1) > 1e-6


def returned_toward_origin(positions, screen, screens, goal_lines, arrive_time, depth, origin=None, post_radius=GOAL_POST_RADIUS, max_after_arrive=None):
    """Come-back: leave the line band back toward the send/player origin.

    Continuing past the line toward the camera is a finish, not a return.
    Long dropouts are already removed by append_continuing_ball for PASS/TARGET.
    """
    p0, p1 = get_screen_info(screen, goal_lines)
    if p0 is None or arrive_time is None:
        return False
    if origin is None:
        origin = goal_send_origin(screens)
    leave_depth = float(depth) * 1.15
    seen_in = False
    away = 0
    for t, x, y in positions:
        if t + 1e-6 < arrive_time:
            continue
        pt = (x, y)
        if in_goal_area(pt, p0, p1, depth, post_radius=post_radius):
            seen_in = True
            away = 0
            continue
        if not seen_in or t <= arrive_time + 0.08:
            continue
        if in_goal_area(pt, p0, p1, leave_depth, post_radius=post_radius):
            continue
        if on_origin_side(pt, p0, p1, origin):
            away += 1
            if away >= 2:
                return True
        else:
            away = 0
    return False


def extended_track(positions, action_index, all_data, key, action_end_time, session_start_time, window=2.5, continue_ball=False):
    extra = []
    if action_end_time is not None and session_start_time is not None:
        extra = get_positions_from_blocks_after(
            action_index, all_data, key, action_end_time, session_start_time, time_window=window
        )
    if continue_ball:
        return append_continuing_ball(positions, extra)
    if not extra:
        return list(positions or [])
    merged = list(positions or []) + list(extra)
    merged.sort(key=lambda p: p[0])
    return merged

# ================================================================
# Helper to compute AEP orientation for a single action (from code A)
# ================================================================

def compute_distances_by_video(blocks, results, fallback_m_per_px=PIXEL_TO_METER_SCALE):
    """Hip path length (metres) for each video_index from recognition + results.

    Counts hip samples on action blocks only (PASS/GOAL/…). BETWEEN standing /
    rest frames are excluded — noisy hips while waiting for the next QR were
    inflating each video (e.g. ~5 m of play → ~19 m) and breaking final sums.
    """
    action_vid = {}
    for row in results or []:
        sid = row.get("id")
        if not sid:
            continue
        try:
            action_vid[sid] = int(row.get("video_index") or 1)
        except (TypeError, ValueError):
            action_vid[sid] = 1

    by_v = defaultdict(list)
    for block in blocks or []:
        sid = block.get("id")
        if not sid or sid not in action_vid:
            continue
        if str(block.get("action") or "").upper() in ("BETWEEN_SESSIONS", "BETWEEN", ""):
            continue
        cur_v = action_vid[sid]
        st = block.get("start_time")
        if not st:
            continue
        try:
            block_start = datetime.strptime(st, "%H:%M:%S.%f")
        except Exception:
            continue
        for entry in block.get("data") or []:
            hp = entry.get("hp")
            if hp is None or not isinstance(hp, list) or len(hp) != 2:
                continue
            by_v[cur_v].append(
                (block_start + timedelta(seconds=float(entry.get("t", 0.0) or 0.0)), hp[0], hp[1])
            )
    out = {}
    for vid, pts in by_v.items():
        pts = sorted(pts, key=lambda p: p[0])
        step = 4 if len(pts) >= 8 else 1
        sampled = pts[::step]
        if len(sampled) < 2:
            out[vid] = 0.0
            continue
        if simust_homography is not None:
            out[vid] = float(
                simust_homography.path_distance_meters(sampled, fallback_m_per_px=fallback_m_per_px)
            )
        else:
            total = 0.0
            for i in range(1, len(sampled)):
                _, x1, y1 = sampled[i - 1]
                _, x2, y2 = sampled[i]
                total += math.hypot(float(x2) - float(x1), float(y2) - float(y1))
            out[vid] = total * float(fallback_m_per_px)
    return out


def get_aep_orientation(screens: List[str], winning_screen: Optional[str]) -> str:
    """
    Returns 'Right' or 'Left' based on the AEP rules (Code A).
    Strips non-numeric characters from screen IDs (e.g., '9L' -> '9').
    """
    if not screens or len(screens) != 2:
        return 'N/A'
    if winning_screen is None or winning_screen == 'N/A':
        return 'N/A'
    try:
        # Remove any non-digit characters (e.g., 'L' suffix)
        s1 = int(re.sub(r'[^0-9]', '', screens[0]))
        s2 = int(re.sub(r'[^0-9]', '', screens[1]))
        win = int(re.sub(r'[^0-9]', '', winning_screen))
    except (ValueError, TypeError):
        return 'N/A'

    right_screens = {2, 3, 4, 9, 10, 11}
    left_screens  = {5, 6, 7, 12, 13, 14}
    special_pairs = [{2, 4}, {12, 14}, {9, 11}, {5, 7}]
    pair_set = {s1, s2}

    if pair_set in special_pairs:
        if win == min(s1, s2):
            return 'Left'
        elif win == max(s1, s2):
            return 'Right'
        else:
            return 'N/A'
    else:
        if win in right_screens:
            return 'Right'
        elif win in left_screens:
            return 'Left'
        else:
            return 'N/A'

# ================================================================
# Compute Action Efficiency (AE)
# ================================================================
def compute_action_efficiency(action_type: str, result: str, finishing_time: float,
                              movement_px: int, max_movement_px: int = 100) -> float:
    """
    Compute Action Efficiency (AE) score for a single action.
    Returns a value between 0 and 100.
    """
    priority_map = {
        'GOAL': 90,
        'PASS': 70,
        'TARGET': 50,
        'PRESS': 30
    }
    P = priority_map.get(action_type, 50)

    if result == 'Correct':
        A = 100
    elif result == 'Late':
        A = 80
    else:  # Wrong or Miss
        A = 0

    # ---- Finishing time (T) – now 3 seconds = optimal ----
    max_time = 3.0
    if finishing_time and finishing_time > 0:
        T = min(finishing_time / max_time, 1.0) * 100
    else:
        T = 0

    # ---- Body Displacement (D) – now 100 px = optimal ----
    if movement_px > 0:
        D = max(0, min(100, 100 - (movement_px / max_movement_px) * 100))
    else:
        D = 100

    # Penalties (binary)
    W = 1 if result == 'Wrong' else 0
    M = 1 if result == 'Miss' else 0
    L = 1 if result == 'Late' else 0

    ae_raw = (0.40 * P) + (0.30 * A) + (0.20 * (100 - T)) + (0.10 * (100 - D)) - (25 * W) - (35 * M) - (15 * L)
    ae = max(0, min(100, ae_raw))
    return ae

# ------------------------------------------------------------------
# Updated analyze_action_with_context (GOAL uses dedicated late search)
# Includes AE computation and fallback action_end_time
# ------------------------------------------------------------------
def analyze_action_with_context(action_data, goal_lines, action_type, all_data, action_index):
    action_id = action_data.get('id', '')
    screens = action_data['screens']
    data = action_data.get('data', [])
    key = 'p' if action_type == 'PRESS' else 'b'

    end_time_str = action_data.get('end_time')
    if end_time_str:
        try:
            action_end_time = datetime.strptime(end_time_str, "%H:%M:%S.%f")
        except:
            action_end_time = None
    else:
        action_end_time = None

    start_time_str = action_data.get('start_time')
    if start_time_str:
        try:
            session_start_time = datetime.strptime(start_time_str, "%H:%M:%S.%f")
        except:
            session_start_time = None
    else:
        session_start_time = None

    # ----- Fallback for action_end_time if it's None -----
    # Use start_time + last frame t as the action end time
    if action_end_time is None and start_time_str and data:
        try:
            last_t = data[-1].get('t', 0.0)
            start_time = datetime.strptime(start_time_str, "%H:%M:%S.%f")
            action_end_time = start_time + timedelta(seconds=last_t)
        except:
            action_end_time = None

    positions = get_positions_from_data(data, key, SCALE)
    if not positions:
        return {
            'Action ID': action_id,
            'Action': action_type,
            'Screens': ', '.join(screens),
            'Result': 'Wrong',
            'Winning Screen': 'N/A',
            'Min Distance (px)': None,
            'Time of Min (s)': '-',
            'Session Duration (s)': '-',
            'Movement (px)': 0,
            'Direction': 'NONE',
            'AEP': 'N/A',
            'proj_t': None,
            'AE': 0.0
        }

    # GOAL uses raw points so nearby screens 1/8 (cameras in front) are not dropped
    # as "static". PASS/TARGET still drop static noise; PRESS uses the player track.
    if action_type == 'GOAL':
        track = positions
    elif action_type == 'PRESS':
        track = positions
    else:
        track = filter_static_ball_positions(positions) or positions

    session_duration = track[-1][0] if track else 0
    wall_session = None
    if action_end_time is not None and session_start_time is not None:
        wall_session = (action_end_time - session_start_time).total_seconds()
    short_tempo = is_short_tempo_action(
        action_index, all_data, action_end_time, wall_session=wall_session
    )
    tempo_duration = float(session_duration) if session_duration else float(wall_session or 0)
    movement, direction = analyze_movement(track)
    late_window = dynamic_late_window(
        action_index, all_data, action_end_time, session_duration=tempo_duration
    )
    full_track = extended_track(
        track, action_index, all_data, key, action_end_time, session_start_time,
        window=late_window,
        continue_ball=(action_type in ("PASS", "TARGET")),
    )

    result = 'Wrong'
    winning_screen = 'N/A'
    display_time = '-'
    display_duration = '-'
    min_dist_display = None
    best_proj_t = None

    if action_type == 'GOAL':
        return analyze_goal_with_context(
            action_id, screens, track, full_track, session_duration,
            movement, direction, goal_lines
        )

    if action_type in ('PASS', 'TARGET', 'PRESS'):
        arrival, depth = best_arrival_in_positions(
            track, screens, goal_lines, action_type,
            session_duration=tempo_duration if short_tempo else None,
        )
        if arrival is not None:
            best_eff_dist, best_min_time, best_screen, best_proj_t = arrival
            arrive_t = first_arrival_time(
                track, best_screen, goal_lines, depth, post_radius=post_radius_for(action_type)
            )
            if arrive_t is None:
                arrive_t = best_min_time
            origin = finishing_return_origin(action_type, screens, track)
            came_back = returned_toward_origin(
                full_track, best_screen, screens, goal_lines, arrive_t, depth,
                origin=origin, post_radius=post_radius_for(action_type),
            )
            came_back_in_session = returned_toward_origin(
                track, best_screen, screens, goal_lines, arrive_t, depth,
                origin=origin, post_radius=post_radius_for(action_type),
            )
            # Finish that only completes at the last in-session frame (return after
            # the QR) is Late — covers T1.2 boundary finishes and end-of-video S10.
            near_session_end = (
                session_duration > 0
                and arrive_t is not None
                and arrive_t >= max(0.0, session_duration - 0.12)
            )
            if action_type == 'PRESS':
                result = 'Correct'
                winning_screen = best_screen
                display_time = f"{best_min_time:.3f}"
                display_duration = f"{session_duration:.3f}"
                min_dist_display = best_eff_dist
            elif came_back and came_back_in_session:
                result = 'Correct'
                winning_screen = best_screen
                display_time = f"{best_min_time:.3f}"
                display_duration = f"{session_duration:.3f}"
                min_dist_display = best_eff_dist
            elif came_back and near_session_end and not came_back_in_session:
                result = 'Late'
                winning_screen = best_screen
                display_time = f"{best_min_time:.3f}"
                display_duration = f"{session_duration:.3f}"
                min_dist_display = best_eff_dist
            elif came_back:
                result = 'Correct'
                winning_screen = best_screen
                display_time = f"{best_min_time:.3f}"
                display_duration = f"{session_duration:.3f}"
                min_dist_display = best_eff_dist
            else:
                result = 'Miss'
                winning_screen = best_screen
                min_dist_display = best_eff_dist

            # Short tempo: a weak in-session graze should lose to a clear BETWEEN/peek Late.
            if (
                result in ('Correct', 'Miss')
                and short_tempo
                and action_end_time is not None
                and action_type in ('PASS', 'TARGET')
            ):
                found_late, late_screen, late_time, late_dist, late_proj = search_late_across_blocks(
                    action_index, all_data, screens, goal_lines, key, action_end_time, action_type,
                    late_window=late_window,
                    session_duration=tempo_duration if short_tempo else max(float(tempo_duration), float(SHORT_SESSION_SEC)),
                )
                if found_late and (
                    min_dist_display is None
                    or float(late_dist) + float(LATE_OVER_CORRECT_MARGIN) < float(min_dist_display)
                ):
                    result = 'Late'
                    winning_screen = late_screen
                    display_time = f"{late_time:.3f}"
                    display_duration = f"{session_duration:.3f}"
                    min_dist_display = late_dist
                    best_proj_t = late_proj
        else:
            if action_end_time is not None:
                found_late, late_screen, late_time, late_dist, late_proj = search_late_across_blocks(
                    action_index, all_data, screens, goal_lines, key, action_end_time, action_type,
                    late_window=late_window,
                    session_duration=tempo_duration if short_tempo else max(float(tempo_duration), float(SHORT_SESSION_SEC)),
                )
                if found_late:
                    result = 'Late'
                    winning_screen = late_screen
                    display_time = f"{late_time:.3f}"
                    display_duration = f"{session_duration:.3f}"
                    min_dist_display = late_dist
                    best_proj_t = late_proj

        if result == 'Wrong':
            display_time = '-'
            display_duration = '-'
            winning_screen = 'N/A'
            min_dist_display = None

        aep = get_aep_orientation(screens, winning_screen)
        finishing_time_val = float(display_time) if display_time != '-' else 0.0
        ae = compute_action_efficiency(action_type, result, finishing_time_val, movement)
        return {
            'Action ID': action_id,
            'Action': action_type,
            'Screens': ', '.join(screens),
            'Result': result,
            'Winning Screen': winning_screen,
            'Min Distance (px)': round(min_dist_display, 1) if min_dist_display is not None and min_dist_display != float('inf') else None,
            'Time of Min (s)': display_time,
            'Session Duration (s)': display_duration,
            'Movement (px)': movement,
            'Direction': direction,
            'AEP': aep,
            'proj_t': round(best_proj_t, 3) if best_proj_t is not None else None,
            'AE': ae
        }

    return {
        'Action ID': action_id,
        'Action': action_type,
        'Screens': ', '.join(screens),
        'Result': 'Wrong',
        'Winning Screen': 'N/A',
        'Min Distance (px)': None,
        'Time of Min (s)': '-',
        'Session Duration (s)': '-',
        'Movement (px)': 0,
        'Direction': 'NONE',
        'AEP': 'N/A',
        'proj_t': None,
        'AE': 0.0
    }

# ============================================================================
# HELPERS AND VIDEO WRITER (unchanged)
# ============================================================================

def get_timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]

def ensure_directory(path):
    if not os.path.exists(path):
        os.makedirs(path)
    return path

def _read_flag_file(path):
    """Return True/False from a flag file, or None if missing/partial."""
    try:
        if not os.path.exists(path):
            return False
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read().strip().lower()
        if not content:
            return None
        if content in ('true', '1', 'yes', 'on', 'paused'):
            return True
        if content in ('false', '0', 'no', 'off'):
            return False
        return None
    except Exception:
        return None


def read_visualization_setting():
    return _read_flag_file(VIZ_FILE)


def read_simulation_setting():
    return _read_flag_file(SIM_FILE)


def read_pause_setting():
    flag = _read_flag_file(PAUSE_FILE)
    return bool(flag)


class ArenaSimulator:
    """Synthetic ball + player for empty-arena testing of the realtime pipeline.

    PASS / TARGET / PRESS:
      Correct — arrive in the goal area during the session and come back.
      Miss    — arrive in the goal area and do not come back, even after the session.
      Late    — first arrival is after the session.
      Wrong   — never arrive.
    GOAL (cameras face screens 1 and 8; posts count):
      Correct — reach the goal line / proj_t band during the session and do not
                come back toward the send origin.
      Late    — first reach the line after the session and do not come back.
      Wrong   — any other case (including a return toward the origin).
    GOAL shots start at the real send origin and aim at rotating spots
    (corners, up-center, up-corners, through the line) — not only the midpoint.
    GOAL and TARGET include physical camera facts: the ball smears along its
    velocity and YOLO drops some fast/blurred frames. GOAL also grows as it
    nears the camera. PASS / PRESS stay crisp.
    """

    PLAYER_HOME = (280.0, 268.0)
    BALL_HOME = (302.0, 282.0)
    PASS_CYCLE = ("correct", "miss", "late", "wrong")
    OTHER_CYCLE = ("correct", "miss", "late", "wrong")
    GOAL_CYCLE = ("correct", "late", "wrong")
    GOAL_PROBE = False

    def __init__(self, field_id="A"):
        fid = normalize_field(field_id) or "A"
        self.field_id = fid
        if fid == "B":
            self.PLAYER_HOME = (280.0 + 640.0, 268.0)
            self.BALL_HOME = (302.0 + 640.0, 282.0)
            self.wrong_xy_default = (420.0 + 640.0, 200.0)
        else:
            self.PLAYER_HOME = (280.0, 268.0)
            self.BALL_HOME = (302.0, 282.0)
            self.wrong_xy_default = (420.0, 200.0)
        self.action = None
        self.screens = []
        self.start_ts = 0.0
        self.active = False
        self.late_phase = False
        self.late_start_ts = 0.0
        self.intended = "correct"
        self.outcome_index = 0
        self.target_xy = self.BALL_HOME
        self.miss_xy = self.BALL_HOME
        self.late_hold_xy = self.BALL_HOME
        self.late_start_xy = self.BALL_HOME
        self.late_from_xy = self.BALL_HOME
        self.late_finish_xy = self.BALL_HOME
        self.late_finish_roll_xy = self.BALL_HOME
        self.wrong_xy = self.wrong_xy_default
        self.goal_late_start_xy = self.BALL_HOME
        self.line_p0 = None
        self.line_p1 = None
        self.last_ball = self.BALL_HOME
        self.last_player = self.PLAYER_HOME
        self.start_xy = self.BALL_HOME
        self.hold_finish = False
        self.hold_xy = self.BALL_HOME
        self.hold_player = self.PLAYER_HOME
        self.probe_name = ""
        self.travel_s = 0.70
        self.last_ball_vel = (0.0, 0.0)
        self.last_ball_radius = 6.0
        self.last_blur = 0.0
        self.last_detected = True
        self.last_step_ts = 0.0
        self._prev_ball = None
        self._miss_streak = 0
        self._goal_rng = random.Random(1808)
        self.goal_closeness = 0.0
        self.aim_in_index = 0
        self.aim_out_index = 0
        self.aim_name = ""

    def start_action(self, action, screens):
        self.action = (action or "").upper()
        self.screens = [str(s) for s in (screens or [])]
        self.start_ts = time.time()
        self.active = True
        self.late_phase = False
        self.hold_finish = False
        self.target_xy, self.line_p0, self.line_p1 = self._line_target(self.screens)
        # Stay off the line during the QR. GOAL needs a valid projection (0..1)
        # so late search can run; PASS/TARGET/PRESS stay on the home side so the
        # path never enters FINISH_DIST.
        if self.action == "GOAL":
            origin = goal_send_origin(self.screens)
            self.miss_xy = self._perp_from_mid(78)
            # Late: stay near the send origin so the session never enters the mouth.
            self.late_hold_xy = (origin[0] + 40.0, origin[1])
            self.late_start_xy = origin
            self.goal_late_start_xy = self.late_start_xy
            self.wrong_xy = (origin[0] - 80.0, origin[1] + 10.0)
        else:
            self.miss_xy = self._offset_from_line(78)
            self.late_start_xy, self.late_hold_xy = self._late_local_pair(118.0, 44.0, goal=False)
            self.goal_late_start_xy = self.late_start_xy
            self.wrong_xy = self._far_from_all_screens(240, min_from_home=50)
        self.late_finish_xy = self._closest_screen_mid(self.late_hold_xy)
        self.late_finish_roll_xy = self._along_line_from(self.late_finish_xy, 28.0)
        self.start_xy = self.BALL_HOME
        if self.action == "TARGET" and target_uses_screen8_origin(self.screens):
            origin = target_send_origin(self.screens)
            self.start_xy = origin
            self.late_start_xy = origin
            self.late_hold_xy = (origin[0] + 40.0, origin[1])
            self.wrong_xy = (origin[0] - 80.0, origin[1] + 10.0)
            self.late_finish_xy = self._closest_screen_mid(origin)
            self.late_finish_roll_xy = self._along_line_from(self.late_finish_xy, 28.0)
        self.probe_name = ""
        self.aim_name = ""
        self.travel_s = 0.70
        self.last_step_ts = 0.0
        self._prev_ball = None
        self._miss_streak = 0
        self.last_ball_vel = (0.0, 0.0)
        self.last_blur = 0.0
        self.last_detected = True
        seed = 1800 + (80 if any(screen_base_id(s) in GOAL_MOUTH_SCREENS for s in self.screens) else 10) + int(self.outcome_index)
        self._goal_rng = random.Random(seed)
        # Screen 1's mouth covers the left-camera baseline; home sits inside it.
        # Start from the pitch side so in-session "late" / "wrong" are not already arrivals.
        if self.action == "GOAL" and self.line_p0 and self.line_p1:
            goal_screen = self.screens[0] if self.screens else "8"
            depth = arrival_depth_for(goal_screen, "GOAL")
            self.start_xy = goal_send_origin(self.screens)
            self.travel_s = GOAL_SHOT_TRAVEL_S
            if self.GOAL_PROBE:
                name = GOAL_PROBE_ZONES[self.outcome_index % len(GOAL_PROBE_ZONES)]
                self.outcome_index += 1
                self.probe_name = name
                self.aim_name = name
                self.target_xy = goal_probe_xy(self.line_p0, self.line_p1, name)
                self.start_xy = goal_send_origin(self.screens)
                self.travel_s = GOAL_PROBE_TRAVEL_S
                self.intended = "correct"
                dist, proj_t, _, _ = compute_projection(self.target_xy, self.line_p0, self.line_p1)
                now_in = in_goal_area(self.target_xy, self.line_p0, self.line_p1, depth)
                print(
                    f"  [SIM] GOAL probe={name} screen={self.screens} target={self.target_xy} "
                    f"dist={dist:.1f} proj_t={proj_t:.3f} band={'IN' if now_in else 'OUT'}"
                )
                return
            self.intended = self._next_outcome(self.action)
            name, xy = self._next_goal_aim(self.intended)
            self.aim_name = name
            self.probe_name = name
            self.target_xy = xy
            if self.intended == "late":
                self.late_finish_xy = xy
            elif self.intended == "wrong":
                self.wrong_xy = xy
            dist, proj_t, _, _ = compute_projection(xy, self.line_p0, self.line_p1)
            now_in = in_goal_area(xy, self.line_p0, self.line_p1, depth)
            print(
                f"  [SIM] GOAL -> {self.screens} intended={self.intended.upper()} aim={name} "
                f"target={xy} dist={dist:.1f} proj_t={proj_t:.3f} band={'IN' if now_in else 'OUT'}"
            )
            return
        self.intended = self._next_outcome(self.action)
        print(
            f"  [SIM] {self.action} -> {self.screens} intended={self.intended.upper()} "
            f"start={self.start_xy} target={self.target_xy} "
            f"late_hold={self.late_hold_xy} wrong={self.wrong_xy}"
        )

    def end_action(self):
        self.active = False
        if self.intended == "late":
            self.late_phase = True
            self.hold_finish = False
            self.late_start_ts = time.time()
            self.late_from_xy = self.last_ball
        elif self.intended == "miss" or (self.intended == "correct" and self.action == "GOAL"):
            # Stay in the goal after the QR so after-session frames do not look like a return.
            self.late_phase = False
            self.hold_finish = True
            self.hold_xy = self.last_ball
            self.hold_player = self.last_player
        else:
            self.late_phase = False
            self.hold_finish = False
            self.action = None

    def _next_outcome(self, action):
        if action == "GOAL":
            cycle = self.GOAL_CYCLE
        elif action == "PASS":
            cycle = self.PASS_CYCLE
        else:
            cycle = self.OTHER_CYCLE
        result = cycle[self.outcome_index % len(cycle)]
        self.outcome_index += 1
        return result

    def _next_goal_aim(self, intended):
        """Rotate GOAL destinations: corners / up-center / through, not only mid."""
        if intended in ("correct", "late"):
            name = GOAL_AIM_IN[self.aim_in_index % len(GOAL_AIM_IN)]
            self.aim_in_index += 1
        else:
            name = GOAL_AIM_OUT[self.aim_out_index % len(GOAL_AIM_OUT)]
            self.aim_out_index += 1
        if name == "sidestep":
            origin = goal_send_origin(self.screens)
            return name, (origin[0] - 80.0, origin[1] + 10.0)
        return name, goal_probe_xy(self.line_p0, self.line_p1, name)

    def _uses_physical_ball(self):
        return self.action in ("GOAL", "TARGET")

    def _line_target(self, screens):
        # Prefer goal-mouth screens (1/7/8) so area 7 is not skipped for a side keypoint.
        ordered = list(screens or [])
        mouths = [s for s in ordered if screen_base_id(s) in GOAL_MOUTH_SCREENS]
        for screen in mouths + [s for s in ordered if s not in mouths]:
            p0, p1 = get_screen_info(screen, GOAL_LINES)
            if p0 is None:
                continue
            mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
            return mid, p0, p1
        return (640.0, 280.0), (600.0, 280.0), (680.0, 280.0)

    def _min_dist_to_screens(self, pt):
        best = float("inf")
        for screen in self.screens:
            p0, p1 = get_screen_info(screen, GOAL_LINES)
            if p0 is None:
                continue
            d, _ = get_effective_distance(pt, p0, p1)
            if d < best:
                best = d
        return best

    def _point_line_dist(self, pt):
        if not self.line_p0 or not self.line_p1:
            return float("inf")
        return get_effective_distance(pt, self.line_p0, self.line_p1)[0]

    def _far_from_all_screens(self, min_clearance, min_from_home=50.0):
        """In-frame point at least min_clearance from every listed screen, and not on home."""
        hx, hy = self.BALL_HOME
        saved = (self.line_p0, self.line_p1, self.target_xy)
        samples = [(220.0, 200.0), (400.0, 140.0), (180.0, 310.0), (450.0, 250.0),
                   (350.0, 180.0), (250.0, 120.0), (500.0, 300.0), (320.0, 220.0)]
        for screen in self.screens:
            p0, p1 = get_screen_info(screen, GOAL_LINES)
            if p0 is None:
                continue
            self.line_p0, self.line_p1 = p0, p1
            self.target_xy = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
            samples.append(self._offset_from_line(min_clearance))
            samples.append(self._offset_from_line(min_clearance + 70))
        self.line_p0, self.line_p1, self.target_xy = saved
        best = None
        best_score = -1.0
        for raw in samples:
            pt = self._clip(raw[0], raw[1])
            d_screens = self._min_dist_to_screens(pt)
            d_home = math.hypot(pt[0] - hx, pt[1] - hy)
            if d_screens >= min_clearance and d_home >= min_from_home:
                return pt
            score = d_screens + 0.15 * d_home
            if score > best_score:
                best_score = score
                best = pt
        return best if best is not None else self.BALL_HOME

    def _closest_screen_mid(self, pt):
        """Midpoint of the listed screen nearest this point (short late finish)."""
        best_mid = self.target_xy
        best_d = float("inf")
        for screen in self.screens:
            p0, p1 = get_screen_info(screen, GOAL_LINES)
            if p0 is None:
                continue
            d, _ = get_effective_distance(pt, p0, p1)
            if d < best_d:
                best_d = d
                best_mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
        return best_mid

    def _along_line_from(self, pt, span):
        p0, p1 = self.line_p0, self.line_p1
        nearest = None
        nearest_d = float("inf")
        for screen in self.screens:
            cand0, cand1 = get_screen_info(screen, GOAL_LINES)
            if cand0 is None:
                continue
            d, _ = get_effective_distance(pt, cand0, cand1)
            if d < nearest_d:
                nearest_d = d
                nearest = (cand0, cand1)
        if nearest:
            p0, p1 = nearest
        if not p0 or not p1:
            return self._clip(pt[0] + span, pt[1])
        tx, ty = p1[0] - p0[0], p1[1] - p0[1]
        nlen = math.hypot(tx, ty) or 1.0
        return self._clip(pt[0] + (tx / nlen) * span, pt[1] + (ty / nlen) * span)

    def _late_hold_near_home(self, clearance, goal=False):
        """Closest practical point to home that stays outside FINISH_DIST of every listed screen."""
        if goal:
            return self._perp_from_mid(clearance)
        hx, hy = self.BALL_HOME
        home = (hx, hy)
        if self._min_dist_to_screens(home) >= clearance:
            return home
        nearest = None
        nearest_d = float("inf")
        for screen in self.screens:
            p0, p1 = get_screen_info(screen, GOAL_LINES)
            if p0 is None:
                continue
            d, _ = get_effective_distance(home, p0, p1)
            if d < nearest_d:
                nearest_d = d
                nearest = (p0, p1)
        if not nearest:
            return home
        saved = (self.line_p0, self.line_p1, self.target_xy)
        self.line_p0, self.line_p1 = nearest
        p0, p1 = nearest
        self.target_xy = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
        chosen = home
        for dist in range(int(clearance), 280, 6):
            pt = self._offset_from_line(float(dist))
            if self._min_dist_to_screens(pt) >= clearance:
                chosen = pt
                break
            chosen = pt
        self.line_p0, self.line_p1, self.target_xy = saved
        return chosen

    def _late_local_pair(self, clearance, span, goal=False):
        """Two nearby safe points: one short control step, then freeze (no pitch-wide run)."""
        a = self._late_hold_near_home(clearance, goal=goal)
        ax, ay = a
        dirs = []
        if self.line_p0 and self.line_p1:
            tx = self.line_p1[0] - self.line_p0[0]
            ty = self.line_p1[1] - self.line_p0[1]
            nlen = math.hypot(tx, ty) or 1.0
            dirs.append((tx / nlen, ty / nlen))
            dirs.append((-tx / nlen, -ty / nlen))
        dirs.extend([(1.0, 0.0), (0.0, 1.0), (-0.8, 0.6), (0.6, -0.8), (-1.0, 0.0), (0.0, -1.0)])
        min_ok = 108.0
        for ux, uy in dirs:
            b = self._clip(ax + ux * span, ay + uy * span)
            if math.hypot(b[0] - ax, b[1] - ay) < 36:
                continue
            if self._min_dist_to_screens(a) >= min_ok and self._min_dist_to_screens(b) >= min_ok:
                if goal:
                    _d0, t0 = get_effective_distance(a, self.line_p0, self.line_p1)
                    _d1, t1 = get_effective_distance(b, self.line_p0, self.line_p1)
                    if not (0.0 <= t0 <= 1.0 and 0.0 <= t1 <= 1.0):
                        continue
                return a, b
        b = self._clip(ax + span, ay)
        return a, b

    def _offset_from_line(self, dist):
        """Point on the home side of the goal line, still in-frame, ~dist px away."""
        if not self.line_p0 or not self.line_p1:
            return self._lerp(self.target_xy, self.BALL_HOME, 0.45)
        x0, y0 = self.line_p0
        x1, y1 = self.line_p1
        hx, hy = self.BALL_HOME
        _d, proj_t, _, _ = compute_projection((hx, hy), self.line_p0, self.line_p1)
        t_seg = max(0.0, min(1.0, proj_t))
        cx = x0 + t_seg * (x1 - x0)
        cy = y0 + t_seg * (y1 - y0)
        vx, vy = hx - cx, hy - cy
        nlen = math.hypot(vx, vy)
        if nlen < 1e-3:
            vx, vy = -(y1 - y0), (x1 - x0)
            nlen = math.hypot(vx, vy) or 1.0
        vx, vy = vx / nlen, vy / nlen
        min_ok = dist * 0.85
        candidates = []
        for scale in (dist, dist + 40, dist + 80, dist + 120):
            candidates.append((cx + vx * scale, cy + vy * scale))
        candidates.extend([self.BALL_HOME, (220.0, 200.0), (400.0, 140.0), (180.0, 310.0)])
        best = None
        best_d = -1.0
        for raw in candidates:
            clipped = self._clip(raw[0], raw[1])
            d = self._point_line_dist(clipped)
            if d >= min_ok:
                return clipped
            if d > best_d:
                best_d = d
                best = clipped
        return best if best is not None else self.BALL_HOME

    def _perp_from_mid(self, dist):
        """Offset from segment midpoint along the perpendicular that stays in-frame.

        Keeps 0<=proj_t<=1 so GOAL late search is allowed.
        """
        if not self.line_p0 or not self.line_p1:
            return self._offset_from_line(dist)
        x0, y0 = self.line_p0
        x1, y1 = self.line_p1
        mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        nx, ny = -(y1 - y0), (x1 - x0)
        nlen = math.hypot(nx, ny) or 1.0
        nx, ny = nx / nlen, ny / nlen
        min_ok = dist * 0.85
        best = None
        best_d = -1.0
        for sign in (1.0, -1.0):
            for scale in (dist, dist + 40, dist + 80):
                clipped = self._clip(mx + sign * nx * scale, my + sign * ny * scale)
                d = self._point_line_dist(clipped)
                _eff, proj_t = get_effective_distance(clipped, self.line_p0, self.line_p1)
                if d >= min_ok and 0.0 <= proj_t <= 1.0:
                    return clipped
                if d > best_d and 0.0 <= proj_t <= 1.0:
                    best_d = d
                    best = clipped
        return best if best is not None else self._offset_from_line(dist)

    def blank_half(self):
        frame = np.zeros((SIM_FRAME_HEIGHT, SIM_FRAME_WIDTH // 2, 3), dtype=np.uint8)
        frame[:] = (28, 72, 32)
        cv2.rectangle(frame, (8, 8), (SIM_FRAME_WIDTH // 2 - 8, SIM_FRAME_HEIGHT - 8), (40, 110, 50), 1)
        return frame

    def _lerp(self, a, b, u):
        u = max(0.0, min(1.0, u))
        return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)

    def _clip(self, x, y):
        return (
            max(8.0, min(float(SIM_FRAME_WIDTH - 8), x)),
            max(8.0, min(float(SIM_FRAME_HEIGHT - 8), y)),
        )

    def _ball_player_for_outcome(self, t, now):
        target = self.target_xy
        is_press = self.action == "PRESS"
        intended = self.intended

        if self.hold_finish:
            bx, by = self.hold_xy
            px, py = self.hold_player
            return bx, by, px, py

        if self.late_phase:
            elapsed = now - self.late_start_ts
            dest = self.late_finish_xy
            start = self.late_from_xy
            if elapsed <= 0.40:
                pos = self._lerp(start, dest, elapsed / 0.40)
            elif self.action == "GOAL":
                pos = dest
            else:
                pos = self._lerp(dest, self.late_finish_roll_xy, min(1.0, (elapsed - 0.40) / 0.30))
            bx, by = pos
            if is_press:
                px, py = bx - 16, by - 10
            else:
                px, py = self._lerp(self.PLAYER_HOME, dest, 0.10)
            if elapsed > 2.2 and self.action != "GOAL":
                self.late_phase = False
            return bx, by, px, py

        if not self.active:
            wobble = math.sin(now * 1.15)
            rest = self.start_xy or self.BALL_HOME
            px = self.PLAYER_HOME[0] + wobble * 7
            py = self.PLAYER_HOME[1]
            bx = rest[0] + wobble * 5
            by = rest[1]
            return bx, by, px, py

        if intended == "correct":
            if self.action == "GOAL":
                u = min(1.0, t / max(0.20, self.travel_s))
                # Constant world speed looks faster in pixels as the ball nears
                # the camera (bottom of the image). Ease-in matches that.
                u_pix = u ** 1.35
                bx, by = self._lerp(self.start_xy, target, u_pix)
                px, py = self._lerp(self.PLAYER_HOME, target, u * 0.22)
                return bx, by, px, py
            if is_press:
                if t <= 0.70:
                    px, py = self._lerp(self.PLAYER_HOME, target, t / 0.70)
                else:
                    px, py = self._lerp(target, self.PLAYER_HOME, min(1.0, (t - 0.70) / 0.65))
                bx, by = px + 16, py + 10
                return bx, by, px, py
            origin = self.start_xy or self.BALL_HOME
            if t <= 0.70:
                bx, by = self._lerp(origin, target, t / 0.70)
            else:
                bx, by = self._lerp(target, origin, min(1.0, (t - 0.70) / 0.65))
            px, py = self._lerp(self.PLAYER_HOME, target, min(1.0, t / 1.1) * 0.22)
            return bx, by, px, py

        if intended == "miss":
            # Arrive in the goal area and stay — no come-back.
            u = min(1.0, t / 0.70)
            if is_press:
                px, py = self._lerp(self.PLAYER_HOME, target, u)
                bx, by = px + 16, py + 10
            else:
                bx, by = self._lerp(self.start_xy, target, u)
                px, py = self._lerp(self.PLAYER_HOME, target, u * 0.22)
            return bx, by, px, py

        if intended == "late":
            # One short control step (~44px), then freeze. Enough for the static
            # filter (>33px), without running across the pitch the way a late
            # player would not.
            u = min(1.0, t / 0.40)
            origin = self.late_start_xy
            hold = self.late_hold_xy
            if is_press:
                px, py = self._lerp(origin, hold, u)
                bx, by = px + 16, py + 10
            else:
                bx, by = self._lerp(origin, hold, u)
                px, py = self._lerp(self.PLAYER_HOME, hold, u * 0.08)
            return bx, by, px, py

        # wrong: move on the home side only — never cross the goal line
        u = min(1.0, t / 0.60)
        origin = self.start_xy
        if is_press:
            px, py = self._lerp(self.PLAYER_HOME, self.wrong_xy, u)
            bx, by = px + 16, py + 10
        else:
            bx, by = self._lerp(origin, self.wrong_xy, u)
            px, py = self._lerp(self.PLAYER_HOME, self.wrong_xy, u * 0.18)
        return bx, by, px, py

    def _goal_closeness(self, x, y):
        """0 at the send origin, 1 at the goal line, >1 past the line toward the camera."""
        origin = self.start_xy or goal_send_origin(self.screens)
        if self.line_p0 and self.line_p1:
            mx = (self.line_p0[0] + self.line_p1[0]) / 2.0
            my = (self.line_p0[1] + self.line_p1[1]) / 2.0
        else:
            mx, my = self.target_xy
        ox, oy = origin
        span = math.hypot(mx - ox, my - oy) or 1.0
        along = ((x - ox) * (mx - ox) + (y - oy) * (my - oy)) / (span * span)
        return max(0.0, min(1.45, along))

    def _shot_closeness(self, x, y):
        """0 at the shot origin, 1 at this action's target."""
        if self.action == "GOAL":
            return self._goal_closeness(x, y)
        origin = self.start_xy or self.BALL_HOME
        dest = self.target_xy or origin
        ox, oy = origin
        span = math.hypot(dest[0] - ox, dest[1] - oy) or 1.0
        along = ((x - ox) * (dest[0] - ox) + (y - oy) * (dest[1] - oy)) / (span * span)
        return max(0.0, min(1.15, along))

    def _physical_should_detect(self, closeness, speed, blur, x, y):
        """YOLO-style dropouts: fast + smeared balls are often missed."""
        if self.action == "TARGET" and (closeness >= 0.86 or closeness <= 0.12):
            return True
        if closeness < 0.14 or speed < 48.0:
            return True
        if x < 18 or y < 18 or x > SIM_FRAME_WIDTH - 18 or y > SIM_FRAME_HEIGHT - 18:
            return self._goal_rng.random() > 0.55
        p_miss = (
            0.08
            + 0.50 * min(1.0, blur / 22.0)
            + 0.22 * min(1.0, closeness) * min(1.0, speed / 380.0)
        )
        if self._miss_streak:
            p_miss = min(0.82, p_miss + 0.22)
        return self._goal_rng.random() > p_miss

    def step(self, frame_w, frame_h):
        sx = frame_w / float(SIM_FRAME_WIDTH)
        sy = frame_h / float(SIM_FRAME_HEIGHT)
        now = time.time()
        t = now - self.start_ts if self.active else (now - self.late_start_ts if self.late_phase else 0.0)
        bx, by, px, py = self._ball_player_for_outcome(t, now)
        bx, by = self._clip(bx, by)
        px, py = self._clip(px, py)
        if self.last_step_ts <= 0:
            dt = 1.0 / TARGET_FPS
        else:
            dt = max(1e-3, min(0.20, now - self.last_step_ts))
        self.last_step_ts = now
        if self._prev_ball is not None:
            vx = (bx - self._prev_ball[0]) / dt
            vy = (by - self._prev_ball[1]) / dt
        else:
            vx, vy = 0.0, 0.0
        self._prev_ball = (bx, by)
        self.last_ball = (bx, by)
        self.last_player = (px, py)
        self.last_ball_vel = (vx, vy)

        closeness = 0.0
        radius = 9.0
        blur = 0.0
        detected = True
        if self._uses_physical_ball():
            closeness = self._shot_closeness(bx, by)
            if self.action == "GOAL":
                radius = 5.0 + 11.0 * min(1.0, closeness) + 3.0 * max(0.0, closeness - 1.0)
            else:
                radius = 6.0 + 6.0 * min(1.0, closeness)
            speed = math.hypot(vx, vy)
            blur = min(
                42.0,
                speed * (1.0 / 80.0) * (0.75 + 1.55 * min(1.0, closeness))
                + radius * 0.35 * min(1.0, speed / 220.0),
            )
            detected = self._physical_should_detect(closeness, speed, blur, bx, by)
            self._miss_streak = 0 if detected else (self._miss_streak + 1)
        self.last_ball_radius = radius
        self.last_blur = blur
        self.last_detected = detected
        self.goal_closeness = closeness

        bx_s = int(bx * sx)
        by_s = int(by * sy)
        px_s = int(px * sx)
        py_s = int(py * sy)
        bw, bh = max(18, int(36 * sx)), max(50, int(88 * sy))
        x1 = max(0, px_s - bw // 2)
        y1 = max(0, py_s - bh)
        x2 = min(frame_w - 1, px_s + bw // 2)
        y2 = min(frame_h - 1, py_s + 6)
        hip = (float(px_s), float(max(0, py_s - int(28 * sy))))
        r_box = max(6, int(radius * min(sx, sy)))
        stretch = max(0, int(blur * 0.45 * min(sx, sy)))
        balls = []
        if detected:
            conf = 0.96 if not self._uses_physical_ball() else max(0.28, 0.94 - 0.035 * blur)
            balls.append({
                "center": [bx_s, by_s],
                "bbox": [bx_s - r_box - stretch, by_s - r_box, bx_s + r_box + stretch, by_s + r_box],
                "confidence": conf,
                "simulated": True,
            })
        players = [{
            "center": [px_s, py_s - bh // 3],
            "bbox": [x1, y1, x2, y2],
            "confidence": 1.0,
            "simulated": True,
        }]
        return balls, players, hip

    def draw_on_frame(self, frame, balls, players):
        for player in players:
            x1, y1, x2, y2 = player["bbox"]
            overlay = frame.copy()
            cv2.rectangle(overlay, (x1, y1), (x2, y2), (40, 180, 80), -1)
            frame = cv2.addWeighted(overlay, 0.35, frame, 0.65, 0)
            cv2.ellipse(frame, ((x1 + x2) // 2, y1 + 16), (12, 14), 0, 0, 360, (20, 220, 90), -1)
        if self._uses_physical_ball():
            frame = self._draw_physical_ball(frame)
        else:
            for ball in balls:
                cx, cy = ball["center"]
                cv2.circle(frame, (cx, cy), 11, (0, 0, 0), -1)
                cv2.circle(frame, (cx, cy), 9, (255, 255, 255), -1)
                cv2.circle(frame, (cx, cy), 9, (0, 140, 255), 2)
        if self.action == "GOAL" and self.aim_name and (self.active or self.late_phase or self.hold_finish) and self.line_p0 and self.line_p1:
            dist, proj_t, _, _ = compute_projection(self.last_ball, self.line_p0, self.line_p1)
            screen = self.screens[0] if self.screens else "8"
            depth = arrival_depth_for(screen, "GOAL")
            now_in = in_goal_area(self.last_ball, self.line_p0, self.line_p1, depth)
            det = "DET" if self.last_detected else "MISS"
            label = (
                f"GOAL AIM {self.aim_name}  {self.intended.upper()}  dist={dist:.1f} "
                f"proj_t={proj_t:.2f} band={'IN' if now_in else 'OUT'} {det}"
            )
        elif self._uses_physical_ball() and (self.active or self.late_phase or self.hold_finish):
            det = "DET" if self.last_detected else "MISS"
            label = (
                f"ARENA SIM  {self.action} {self.intended.upper()}  r={self.last_ball_radius:.0f} "
                f"blur={self.last_blur:.0f} {det}"
            )
        elif self.active or self.late_phase:
            label = f"ARENA SIM  {self.intended.upper()}"
        else:
            label = "ARENA SIMULATION"
        cv2.putText(frame, label, (12, frame.shape[0] - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 220, 255), 2)
        return frame

    def _draw_physical_ball(self, frame):
        """True ball with perspective size and a velocity smear, even on miss frames."""
        h, w = frame.shape[:2]
        sx = w / float(SIM_FRAME_WIDTH)
        sy = h / float(SIM_FRAME_HEIGHT)
        cx = int(self.last_ball[0] * sx)
        cy = int(self.last_ball[1] * sy)
        r = max(3, int(round(self.last_ball_radius * min(sx, sy))))
        vx, vy = self.last_ball_vel
        speed = math.hypot(vx, vy)
        blur = self.last_blur * min(sx, sy)
        overlay = frame.copy()
        if blur > 2.5 and speed > 8.0:
            ux, uy = vx / speed, vy / speed
            n = max(4, min(12, int(blur / 2.5)))
            for i in range(n, 0, -1):
                k = i / float(n)
                px = int(cx - ux * blur * k)
                py = int(cy - uy * blur * k)
                rr = max(2, int(r * (0.55 + 0.45 * (1.0 - k))))
                shade = int(40 + 90 * (1.0 - k))
                cv2.circle(overlay, (px, py), rr + 1, (0, 0, 0), -1)
                cv2.circle(overlay, (px, py), rr, (shade, shade, 255), -1)
            frame = cv2.addWeighted(overlay, 0.55, frame, 0.45, 0)
        alpha = 0.38 if not self.last_detected else 0.85
        core = frame.copy()
        cv2.circle(core, (cx, cy), r + 1, (0, 0, 0), -1)
        cv2.circle(core, (cx, cy), r, (255, 255, 255), -1)
        cv2.circle(core, (cx, cy), max(2, r - 2), (0, 140, 255), 2)
        frame = cv2.addWeighted(core, alpha, frame, 1.0 - alpha, 0)
        if not self.last_detected:
            cv2.putText(frame, "MISS", (cx + r + 6, cy - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 180, 255), 1)
        if self.line_p0 and self.line_p1:
            tx, ty = self.target_xy
            cv2.drawMarker(frame, (int(tx * sx), int(ty * sy)), (0, 140, 255), cv2.MARKER_CROSS, 16, 2)
        return frame

class VideoSaver:
    def __init__(self):
        self.writer = None
        self.frame_count = 0
        self.is_recording = False
        self.output_path = None

    def start(self, output_path, width, height, fps=25):
        self.output_path = output_path
        ensure_directory(os.path.dirname(output_path))
        fourcc = cv2.VideoWriter_fourcc(*'MJPG')
        self.writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        if self.writer.isOpened():
            self.is_recording = True
            self.frame_count = 0
            return True
        return False

    def write_frame(self, frame):
        if self.writer and self.writer.isOpened() and frame is not None:
            self.writer.write(frame)
            self.frame_count += 1

    def stop(self):
        if self.writer and self.writer.isOpened():
            self.writer.release()
            self.is_recording = False
            return True
        return False

def get_current_time_ms():
    now = datetime.now()
    return now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"

def add_offset_to_time(time_str, offset_seconds):
    try:
        parts = time_str.split(':')
        hours = int(parts[0])
        minutes = int(parts[1])
        secs_parts = parts[2].split('.')
        seconds = int(secs_parts[0])
        milliseconds = int(secs_parts[1]) if len(secs_parts) > 1 else 0
        total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
        total_seconds += offset_seconds
        if total_seconds >= 86400:
            total_seconds -= 86400
        new_hours = int(total_seconds // 3600)
        new_minutes = int((total_seconds % 3600) // 60)
        new_seconds = total_seconds % 60
        new_ms = int((new_seconds - int(new_seconds)) * 1000)
        new_seconds_int = int(new_seconds)
        return f"{new_hours:02d}:{new_minutes:02d}:{new_seconds_int:02d}.{new_ms:03d}"
    except:
        return time_str

def detect_qr_in_roi(frame, roi):
    """Decode QR inside ROI.

    OpenCV often fails on tall Field-B crops (screen-7 QRs) while a shorter top
    band or a mild upscale succeeds — try several crops before giving up.
    """
    x1, y1, x2, y2 = roi
    h, w = frame.shape[:2]
    x1 = max(0, min(x1, w - 1))
    y1 = max(0, min(y1, h - 1))
    x2 = max(x1 + 1, min(x2, w))
    y2 = max(y1 + 1, min(y2, h))
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return "", None

    ch, cw = crop.shape[:2]
    candidates = [crop]
    # Top band: screen QRs sit in the upper player chrome (fixes PASS/7 miss).
    for top_h in (300, 256, max(160, ch // 2)):
        if 40 < top_h < ch:
            candidates.append(crop[0:top_h, :])
    # Mild upscales help small / soft QRs on the right half.
    for scale in (1.5, 2.0):
        try:
            candidates.append(cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR))
            top = min(300, ch)
            if top < ch:
                candidates.append(
                    cv2.resize(crop[0:top, :], None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
                )
        except Exception:
            pass

    detector = cv2.QRCodeDetector()
    for img in candidates:
        try:
            data, bbox, _ = detector.detectAndDecode(img)
            if data and str(data).strip():
                if bbox is not None and len(bbox) > 0:
                    # Bbox is in candidate coords; only remap when 1:1 with crop
                    if img.shape[0] == ch and img.shape[1] == cw:
                        bbox = bbox.astype(int)
                        bbox[:, :, 0] += x1
                        bbox[:, :, 1] += y1
                    else:
                        bbox = None
                return str(data).strip(), bbox
            ok, datas, points, _ = detector.detectAndDecodeMulti(img)
            if ok and datas:
                for i, raw in enumerate(datas):
                    if raw and str(raw).strip():
                        bbox = None
                        if points is not None and i < len(points):
                            if img.shape[0] == ch and img.shape[1] == cw:
                                bbox = np.array([points[i]], dtype=int)
                                bbox[:, :, 0] += x1
                                bbox[:, :, 1] += y1
                        return str(raw).strip(), bbox
        except Exception:
            continue
    return "", None

def parse_qr_data(raw_data):
    action = ""
    screens = []
    keypoints = []

    if not raw_data:
        return action, screens, keypoints

    try:
        qr = json.loads(raw_data)
        action = str(qr.get("action", "")).strip()
        val = qr.get("screens_index", [])
        if isinstance(val, str):
            screens = [s.strip() for s in val.split(',') if s.strip()]
        elif isinstance(val, (list, tuple)):
            screens = [str(s).strip() for s in val if s is not None]

        kp_val = qr.get("keypoints", [])
        if isinstance(kp_val, list):
            keypoints = [str(k).strip() for k in kp_val if k]
        elif isinstance(kp_val, str):
            keypoints = [kp.strip() for kp in kp_val.split(',') if kp.strip()]

        if action:
            return action.upper(), screens, keypoints
    except Exception:
        pass

    patterns = [
        (r'"action"\s*:\s*"([^"]*)"', r'"screens_index"\s*:\s*\[([^\]]*)\]'),
        (r'action\s*[:=]\s*["\']?([^,"\'}\s]+)', r'screens_index\s*[:=]\s*["\']?([^,"\'}\s]+)'),
    ]

    for action_pattern, screens_pattern in patterns:
        if not action:
            m = re.search(action_pattern, raw_data, re.IGNORECASE)
            if m:
                action = m.group(1).strip().upper()
        if not screens:
            m = re.search(screens_pattern, raw_data, re.IGNORECASE)
            if m:
                content = m.group(1).strip('[]').strip('"\'')
                items = [item.strip().strip('"\'').strip() for item in content.split(',') if item.strip()]
                screens = [s for s in items if s]
        if action and screens:
            break

    if action and not screens:
        numbers = re.findall(r'\b([0-9]+)\b', raw_data)
        if numbers:
            screens = numbers

    return action.upper(), screens, keypoints

# ============================================================================
# PER-FIELD RUNTIME (Field A left / Field B right)
# ============================================================================

class FieldRuntime:
    """Independent QR session + recognition/results for one arena half."""

    def __init__(self, field_id):
        self.field_id = normalize_field(field_id) or "A"
        cfg = field_config(self.field_id)
        self.label = cfg.get("label", f"Field {self.field_id}")
        self.qr_roi = tuple(cfg.get("qr_roi") or qr_roi_for_field(self.field_id))
        self.polygon = list(cfg.get("polygon") or polygon_for_field(self.field_id))
        self.allowed_screens = set(cfg.get("screens") or screens_for_field(self.field_id))
        self.subdir_name = f"field_{self.field_id}"
        self.recording_subdir = None

        self.pending_start = None
        self.pending_start_time = 0
        self.pending_end = False
        self.pending_end_time = 0
        self.pending_end_time_str = ""

        self.session_active = False
        self.between_sessions_active = False
        self.current_action = None
        self.current_screens = []
        self.current_keypoints = []
        self.current_block_id = None
        self.active_goal_lines = {}
        self.session_start_timestamp = 0
        self.session_frame_count = 0
        self.session_fps_sum = 0
        self.between_session_start_time = 0
        self.between_session_start_ts = 0.0
        self.between_session_end_time = ""

        self.session_data = []
        self.between_session_data = []
        self.qr_blocks = []
        self.current_qr_block = None
        self.block_counter = 0

        self.qr_state = {
            "last_raw_data": None,
            "last_detection_time": 0,
            "cooldown": QR_COOLDOWN,
            "detection_count": 0,
            "missing_since": None,
        }
        self.stats = {"sessions_completed": 0, "action_counts": {}, "results": []}
        self.all_player_positions = []
        self.pending_analysis = None
        self.analysis_timer = None
        self._recent_between_gap = None
        self._last_session_duration = None
        self.analysis_started_at = 0
        self._paused_analysis_remaining = None

    def reset_for_recording(self, parent_dir):
        self.recording_subdir = os.path.join(parent_dir, self.subdir_name)
        ensure_directory(self.recording_subdir)
        self.session_data = []
        self.between_session_data = []
        self.qr_blocks = []
        self.block_counter = 0
        self.session_active = False
        self.between_sessions_active = False
        self.pending_start = None
        self.pending_end = False
        self.current_qr_block = None
        self.all_player_positions = []
        self.pending_analysis = None
        self.analysis_timer = None
        self._recent_between_gap = None
        self._last_session_duration = None
        self.stats = {"sessions_completed": 0, "action_counts": {}, "results": []}
        self.qr_state = {
            "last_raw_data": None,
            "last_detection_time": 0,
            "cooldown": QR_COOLDOWN,
            "detection_count": 0,
            "missing_since": None,
        }
        self.start_between_sessions()

    def start_between_sessions(self):
        current_time = get_current_time_ms()
        self.between_sessions_active = True
        self.between_session_data = []
        self.between_session_start_time = current_time
        self.between_session_start_ts = time.time()
        self.between_session_end_time = ""

    def screens_belong(self, screens):
        cleaned = []
        for s in screens or []:
            digits = "".join(ch for ch in str(s) if ch.isdigit())
            if digits:
                cleaned.append(digits)
        if not cleaned:
            return True
        return any(s in self.allowed_screens for s in cleaned)


# ============================================================================
# SIMUST REALTIME CAMERA (with pose-based tracking + polygon drawing)
# ============================================================================

class SimustRealtimeCamera:
    def __init__(self):
        print("=" * 60)
        print("SIMUST REALTIME PLAYER - Dual Field A / Field B")
        print("=" * 60)
        print("Ball detection: BOTH halves (Camera 1 + Camera 8)")
        print("Player tracking: Pose-based hip point (Field A + Field B)")
        print("QR: Field A ROI left | Field B ROI right (3840x1080 grab)")
        print("REAL-TIME RESULTS ANALYSIS DISPLAYED (A left / B right)")
        print("=" * 60)

        sim = read_simulation_setting()
        self.simulation_enabled = bool(sim)
        self.simulator_a = ArenaSimulator(field_id="A")
        self.simulator_b = ArenaSimulator(field_id="B")
        self.simulator = self.simulator_a  # back-compat alias
        self.simulators = {"A": self.simulator_a, "B": self.simulator_b}
        self.tracker = DetectionTracker(require_models=not self.simulation_enabled)
        viz = read_visualization_setting()
        self.visualization_enabled = bool(viz)

        self.session_lock = threading.Lock()
        self.channels = {"A": FieldRuntime("A"), "B": FieldRuntime("B")}

        # Back-compat aliases → Field A (legacy single-field call sites)
        ch_a = self.channels["A"]
        self.pending_start = None
        self.pending_start_time = 0
        self.pending_end = False
        self.pending_end_time = 0
        self.session_active = False
        self.between_sessions_active = False
        self.current_action = None
        self.current_screens = []
        self.current_keypoints = []
        self.current_block_id = None
        self.active_goal_lines = {}
        self.session_start_timestamp = 0
        self.session_frame_count = 0
        self.session_fps_sum = 0
        self.between_session_start_time = 0
        self.between_session_start_ts = 0.0
        self.between_session_end_time = ""
        self.session_data = []
        self.between_session_data = []
        self.qr_blocks = []
        self.current_qr_block = None
        self.qr_state = ch_a.qr_state
        self.stats = ch_a.stats
        self.block_counter = 0
        self.frame_counter = 0
        self.shared_action_index = 0  # keeps Field A / Field B action numbers aligned

        self.video_index = 1
        self.last_video_index = 1

        self.recording_dir = None
        self.video_saver = VideoSaver()
        self.video_started = False
        self.recording_active = False

        self.window_name = "SIMUST REALTIME - Camera Feed"
        self.window_created = False

        self.cameras = {
            "camera-1": {"address": "rtsp://admin:majidAram2@192.168.2.1:554/Streaming/Channels/101/"},
            "camera-8": {"address": "rtsp://admin:majidAram2@192.168.2.8:554/Streaming/Channels/101/"}
        }

        self.frame_buffers = {}
        self.frame_locks = {}
        self.frame_queues = {}
        self.camera_running = True

        for cam in self.cameras:
            self.frame_buffers[cam] = None
            self.frame_locks[cam] = threading.Lock()
            self.frame_queues[cam] = queue.Queue(maxsize=2)

        # Dual-monitor player surface: Field A then Field B (lab desktop often starts at x=1920)
        self.screen_monitor = {"left": 1920, "top": 0, "width": 3840, "height": 1080}
        self.qr_roi = QR_ROI_A
        self.qr_rois = {"A": QR_ROI_A, "B": QR_ROI_B}
        self.screen_capture_running = True

        self.all_player_positions = []

        self.pending_analysis = None
        self.analysis_timer = None
        self._recent_between_gap = None
        self._last_session_duration = None
        self.analysis_started_at = 0
        self.operator_paused = False
        self._pause_lock = threading.Lock()
        self._pause_started_at = 0
        self._paused_analysis_remaining = None

        ensure_directory(DEFAULT_RECORDINGS_DIR)

        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        atexit.register(self.cleanup)

        print(f"Detection: {DETECTION_ENGINE_PATH} (TensorRT)")
        print(f"Pose model: {POSE_ENGINE_PATH if os.path.exists(POSE_ENGINE_PATH) else 'Not found – pose will be skipped'}")
        print(f"Detection Confidence: {DETECTION_CONF}")
        print(f"Recordings: {DEFAULT_RECORDINGS_DIR}")
        print(f"Visualization: {'ON' if self.visualization_enabled else 'OFF'}")
        print(f"Arena simulation: {'ON' if self.simulation_enabled else 'OFF'} (Field A + Field B)")
        print("-" * 60)

    def signal_handler(self, signum, frame):
        print()
        self.camera_running = False
        self.screen_capture_running = False
        self.cleanup()
        sys.exit(0)

    def start_new_recording(self):
        timestamp = get_timestamp()
        self.recording_dir = os.path.join(DEFAULT_RECORDINGS_DIR, f"realtime_{timestamp}")
        ensure_directory(self.recording_dir)

        self.frame_counter = 0
        self.video_index = 1
        self.last_video_index = 1
        self.recording_active = True
        self.video_started = False
        self.tracker.total_balls_detected = 0
        self.tracker.total_players_detected = 0

        for ch in self.channels.values():
            ch.reset_for_recording(self.recording_dir)

        self.shared_action_index = 0
        # Keep top-level aliases pointing at Field A for legacy helpers
        self._sync_aliases_from_channel(self.channels["A"])

        if simust_homography is not None:
            store = simust_homography.load_store()
            for cam in (simust_homography.LEFT_CAMERA, simust_homography.RIGHT_CAMERA):
                rec = simust_homography.public_camera_status(
                    cam, simust_homography.camera_record(store, cam)
                )
                print(f"Homography {cam}: {rec['status']}")

        print(f"Recording: {self.recording_dir}")
        print(f"  Field A → {self.channels['A'].recording_subdir}")
        print(f"  Field B → {self.channels['B'].recording_subdir}")

    def _sync_aliases_from_channel(self, ch):
        self.session_active = ch.session_active
        self.between_sessions_active = ch.between_sessions_active
        self.current_action = ch.current_action
        self.current_screens = ch.current_screens
        self.current_keypoints = ch.current_keypoints
        self.current_block_id = ch.current_block_id
        self.active_goal_lines = ch.active_goal_lines
        self.session_start_timestamp = ch.session_start_timestamp
        self.session_data = ch.session_data
        self.between_session_data = ch.between_session_data
        self.qr_blocks = ch.qr_blocks
        self.current_qr_block = ch.current_qr_block
        self.qr_state = ch.qr_state
        self.stats = ch.stats
        self.all_player_positions = ch.all_player_positions
        self.pending_analysis = ch.pending_analysis
        self.analysis_timer = ch.analysis_timer

    def start_between_sessions(self):
        for ch in self.channels.values():
            ch.start_between_sessions()
        self._sync_aliases_from_channel(self.channels["A"])

    def save_between_sessions_block(self, ch=None):
        if ch is None:
            ch = self.channels["A"]
        if not ch.between_session_data:
            return

        end_time = ch.between_session_end_time if ch.between_session_end_time else get_current_time_ms()

        block = {
            "action": "BETWEEN_SESSIONS",
            "screens": [],
            "field": ch.field_id,
            "start_time": ch.between_session_start_time,
            "end_time": end_time,
            "data": ch.between_session_data
        }
        ch.qr_blocks.append(block)
        try:
            start = datetime.strptime(block["start_time"], "%H:%M:%S.%f")
            end = datetime.strptime(end_time, "%H:%M:%S.%f")
            ch._recent_between_gap = max(0.0, (end - start).total_seconds())
        except Exception:
            n = len(block.get("data") or [])
            if n:
                ch._recent_between_gap = n / 30.0
        ch.between_session_data = []
        self.save_recognition_json(ch)
        print(f"  [{ch.label}] Between sessions: {len(block['data'])} frames ({block['start_time']} -> {block['end_time']})")

    def stop_recording(self):
        if not self.recording_active:
            return

        with self.session_lock:
            for ch in self.channels.values():
                self._flush_pending_analysis_locked(ch)

        now_str = get_current_time_ms()
        now_ts = time.time()
        for ch in self.channels.values():
            if ch.session_active:
                self._execute_end(now_str, now_ts, ch)

        for ch in self.channels.values():
            if ch.between_sessions_active and ch.between_session_data:
                self.save_between_sessions_block(ch)
                ch.between_sessions_active = False

        print("\n[DEBUG] Computing per-video hip distance per field...")
        for ch in self.channels.values():
            try:
                self._write_per_video_distances(ch)
            except Exception as e:
                print(f"[DEBUG] Error writing distances for {ch.label}: {e}")

        self.video_saver.stop()
        for ch in self.channels.values():
            self.save_recognition_json(ch)
        self._write_combined_results_index()
        self.recording_active = False
        self.video_started = False
        self.video_saver = VideoSaver()

    def _write_per_video_distances(self, ch=None):
        """Stamp total_distance on each result from hips of that video only."""
        if ch is None:
            ch = self.channels["A"]
        if simust_homography is None:
            return
        base = ch.recording_subdir or self.recording_dir
        results_json_path = os.path.join(base, "results.json")
        recognition_path = os.path.join(base, "recognition.json")
        if not os.path.exists(results_json_path) or not os.path.exists(recognition_path):
            return
        with open(results_json_path, "r", encoding="utf-8") as f:
            all_results = json.load(f)
        with open(recognition_path, "r", encoding="utf-8") as f:
            blocks = json.load(f)
        if not all_results:
            return
        by_video = compute_distances_by_video(blocks, all_results)
        for row in all_results:
            vid = int(row.get("video_index") or 1)
            row["total_distance"] = float(by_video.get(vid, 0.0))
            row["field"] = ch.field_id
        with open(results_json_path, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2, ensure_ascii=False)
        ch.stats["results"] = all_results
        for vid, metres in sorted(by_video.items()):
            print(f"[DEBUG] [{ch.label}] Video {vid} hip distance: {metres:.2f} m")

    def save_recognition_json(self, ch=None):
        if ch is None:
            # Save both fields
            ok = True
            for channel in self.channels.values():
                if not self.save_recognition_json(channel):
                    ok = False
            return ok

        base = ch.recording_subdir or self.recording_dir
        if not base:
            return False

        json_path = os.path.join(base, "recognition.json")
        sorted_blocks = sorted(ch.qr_blocks, key=lambda x: x.get("start_time", ""))
        output_data = []
        for block in sorted_blocks:
            block_data = {
                "id": block.get("id", ""),
                "action": block.get("action", ""),
                "screens": block.get("screens", []),
                "field": block.get("field", ch.field_id),
                "start_time": block.get("start_time", ""),
                "end_time": block.get("end_time", ""),
                "data": block.get("data", [])
            }
            output_data.append(block_data)

        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            # Keep root recognition.json current so smart player can find a report mid-session
            if self.recording_dir and ch.recording_subdir:
                try:
                    self._write_combined_results_index()
                except Exception:
                    pass
            return True
        except Exception as e:
            print(f"Error saving JSON ({ch.label}): {e}")
            return False

    def _write_combined_results_index(self):
        """Root-level index + merged recognition/results for legacy player/report paths."""
        if not self.recording_dir:
            return
        index = {
            "fields": {
                fid: {
                    "subdir": ch.subdir_name,
                    "results": list(ch.stats.get("results") or []),
                    "sessions_completed": ch.stats.get("sessions_completed", 0),
                }
                for fid, ch in self.channels.items()
            }
        }
        path = os.path.join(self.recording_dir, "fields_index.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(index, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error writing fields_index.json: {e}")
        # recognition.json / results.json stay only under field_A and field_B

    def cleanup(self):
        if self.recording_active:
            self.stop_recording()
        self.destroy_window()

    def get_goal_lines(self, screens, action, keypoints):
        lines = {}
        action_u = (action or "").upper()
        # Union screens + keypoints so area 7 still gets a mouth line when the
        # QR lists it only under keypoints (common for PRESS / goal markers).
        candidates = []
        for src in (screens or [], keypoints or []):
            for screen in src:
                nid = normalize_screen_id(screen)
                if nid and nid not in candidates:
                    candidates.append(nid)
        # PRESS may use QR keypoints instead of the software line — but still
        # draw software lines for goal-mouth screens (1/7/8) so area 7 is visible.
        use_keypoints_only = action_u == "PRESS" and keypoints
        for screen_str in candidates:
            base = screen_base_id(screen_str)
            if use_keypoints_only and base not in GOAL_MOUTH_SCREENS and screen_str not in GOAL_MOUTH_SCREENS:
                continue
            if screen_str in GOAL_LINES:
                lines[screen_str] = GOAL_LINES[screen_str]
            elif base in GOAL_LINES:
                lines[base] = GOAL_LINES[base]
        # GOAL / TARGET / PASS always need software lines for listed screens
        if action_u in ("GOAL", "TARGET", "PASS"):
            for screen_str in candidates:
                base = screen_base_id(screen_str)
                if base in GOAL_LINES and base not in lines and screen_str not in lines:
                    lines[base] = GOAL_LINES[base]
        # Always expose mouth geometry when any mouth id is present
        for screen_str in candidates:
            base = screen_base_id(screen_str)
            if base in GOAL_MOUTH_SCREENS and base in GOAL_LINES:
                lines[base] = GOAL_LINES[base]
        return lines

    def _peer_channel(self, ch):
        other = "B" if ch.field_id == "A" else "A"
        return self.channels.get(other)

    def _parse_block_num(self, block_id):
        try:
            return int(str(block_id or "").lstrip("Ss") or 0)
        except (TypeError, ValueError):
            return 0

    def _field_completed_block(self, ch, block_id):
        """True if this field already finished (or is playing) this action id."""
        if not block_id:
            return False
        if ch.current_block_id == block_id and (ch.session_active or ch.pending_start):
            return True
        for block in ch.qr_blocks or []:
            if block.get("id") == block_id:
                return True
        return False

    def _sessions_paired(self, ch, peer):
        """True when A/B are the same physical action (same id or started together)."""
        if not ch or not peer:
            return False
        if not (ch.session_active and peer.session_active):
            # Pending end / active peer still counts while ending
            if not (ch.session_active or peer.session_active):
                return False
        if (
            ch.current_block_id
            and peer.current_block_id
            and ch.current_block_id == peer.current_block_id
        ):
            return True
        a_ts = getattr(ch, "session_start_timestamp", None)
        b_ts = getattr(peer, "session_start_timestamp", None)
        if a_ts and b_ts and abs(float(a_ts) - float(b_ts)) <= (QR_PAIR_WINDOW_SEC + 1.0):
            return True
        return False

    def _peer_join_info(self, ch, current_timestamp):
        """If peer already owns this action, return join clocks so we do not bump S{n}.

        Join is only for a late ROI decode of the *same* action — never to re-enter a
        block this field already finished (that caused Field A duplicate S1/S3/S5 and
        Field B missing even sessions on SF-60N).
        """
        peer = self._peer_channel(ch)
        if not peer:
            return None
        # New QR while we are still in a session means "next action", not join.
        if ch.session_active or ch.pending_start:
            return None
        if peer.pending_end:
            return None
        window = QR_PAIR_WINDOW_SEC + QR_OFFSET_SECONDS + 0.5
        if peer.pending_start:
            block_id = peer.pending_start.get("block_id")
            if self._field_completed_block(ch, block_id):
                return None
            det = float(peer.pending_start.get("detected_timestamp") or peer.pending_start_time or 0)
            if current_timestamp - det <= window:
                return {
                    "block_id": block_id,
                    "pending_start_time": float(peer.pending_start_time),
                    "offset_start_time_str": peer.pending_start.get("offset_start_time_str"),
                    "paired_session_start": float(peer.pending_start_time),
                    "detected_timestamp": det,
                }
        if peer.session_active and peer.session_start_timestamp:
            block_id = peer.current_block_id
            if self._field_completed_block(ch, block_id):
                return None
            age = current_timestamp - float(peer.session_start_timestamp)
            if age <= window:
                return {
                    "block_id": block_id,
                    "pending_start_time": float(peer.session_start_timestamp),
                    "offset_start_time_str": (peer.current_qr_block or {}).get("start_time"),
                    "paired_session_start": float(peer.session_start_timestamp),
                    "detected_timestamp": float(peer.session_start_timestamp) - QR_OFFSET_SECONDS,
                }
        return None

    def _end_paired_sessions_now(self, current_time_str, current_timestamp, ch):
        """End this field and the peer if they share the same action id."""
        if not ch or not ch.session_active:
            return
        block_id = ch.current_block_id
        peer = self._peer_channel(ch)
        self._end_session_locked(current_time_str, current_timestamp, ch)
        if (
            peer
            and peer.session_active
            and block_id
            and peer.current_block_id == block_id
        ):
            peer.pending_end = False
            self._end_session_locked(current_time_str, current_timestamp, peer)

    def _align_pending_start_to_peer(self, ch, peer):
        """Make late Field share the earlier peer's start clock / block id."""
        if not ch.pending_start or not peer:
            return
        peer_pending = peer.pending_start
        if peer_pending:
            t = min(float(ch.pending_start_time), float(peer.pending_start_time))
            ch.pending_start_time = t
            peer.pending_start_time = t
            # Prefer the earlier detection's offset string
            if float(peer_pending.get("detected_timestamp") or 0) <= float(
                ch.pending_start.get("detected_timestamp") or 0
            ):
                ch.pending_start["offset_start_time_str"] = peer_pending.get(
                    "offset_start_time_str", ch.pending_start.get("offset_start_time_str")
                )
                ch.pending_start["block_id"] = peer_pending.get("block_id", ch.pending_start.get("block_id"))
                ch.current_block_id = ch.pending_start["block_id"]
                ch.block_counter = self._parse_block_num(ch.pending_start["block_id"])
            else:
                peer_pending["offset_start_time_str"] = ch.pending_start.get(
                    "offset_start_time_str", peer_pending.get("offset_start_time_str")
                )
                peer_pending["block_id"] = ch.pending_start.get("block_id", peer_pending.get("block_id"))
                peer.block_counter = self._parse_block_num(peer_pending["block_id"])
            return
        if peer.session_active and peer.session_start_timestamp:
            # Peer already running — join immediately on peer's clock
            ch.pending_start_time = float(peer.session_start_timestamp)
            ch.pending_start["paired_session_start"] = float(peer.session_start_timestamp)
            ch.pending_start["offset_start_time_str"] = (
                (peer.current_qr_block or {}).get("start_time")
                or ch.pending_start.get("offset_start_time_str")
            )
            if peer.current_block_id:
                ch.pending_start["block_id"] = peer.current_block_id
                ch.block_counter = self._parse_block_num(peer.current_block_id)

    def schedule_session_start(self, action, screens, keypoints, block_id, detected_time_str, detected_timestamp, ch,
                               paired_session_start=None, paired_offset_str=None):
        offset_start_time_str = paired_offset_str or add_offset_to_time(detected_time_str, QR_OFFSET_SECONDS)
        with self.session_lock:
            ch.pending_start = {
                "action": action.upper(),
                "screens": screens,
                "keypoints": keypoints,
                "block_id": block_id,
                "goal_lines": self.get_goal_lines(screens, action, keypoints),
                "offset_start_time_str": offset_start_time_str,
                "detected_timestamp": detected_timestamp,
                "field": ch.field_id,
            }
            if paired_session_start is not None:
                ch.pending_start["paired_session_start"] = float(paired_session_start)
                # Start as soon as check_pending runs (catch-up)
                ch.pending_start_time = float(paired_session_start)
            else:
                ch.pending_start_time = detected_timestamp + QR_OFFSET_SECONDS
            peer = self._peer_channel(ch)
            if peer is not None:
                self._align_pending_start_to_peer(ch, peer)

    def schedule_session_end(self, current_time_str, current_timestamp, ch):
        if ch.session_active:
            offset_end_time_str = add_offset_to_time(current_time_str, QR_OFFSET_SECONDS)
            with self.session_lock:
                ch.pending_end = True
                ch.pending_end_time = current_timestamp + QR_OFFSET_SECONDS
                ch.pending_end_time_str = offset_end_time_str
                peer = self._peer_channel(ch)
                if peer is None or not peer.session_active:
                    return
                # Keep A/B endings locked for the same physical action
                paired = self._sessions_paired(ch, peer)
                peer_qr_gone = peer.qr_state.get("missing_since") is not None
                if paired or peer_qr_gone or peer.pending_end:
                    if peer.pending_end:
                        t = min(float(ch.pending_end_time), float(peer.pending_end_time))
                        ch.pending_end_time = t
                        peer.pending_end_time = t
                    else:
                        peer.pending_end = True
                        peer.pending_end_time = ch.pending_end_time
                        peer.pending_end_time_str = offset_end_time_str

    def _sync_peer_pending_clocks_locked(self):
        """Caller holds session_lock. Align pending start/end times across A/B."""
        a, b = self.channels.get("A"), self.channels.get("B")
        if not a or not b:
            return
        if a.pending_start and b.pending_start:
            t = min(float(a.pending_start_time), float(b.pending_start_time))
            a.pending_start_time = t
            b.pending_start_time = t
            # Same block id / start string from earlier detection
            a_det = float(a.pending_start.get("detected_timestamp") or 0)
            b_det = float(b.pending_start.get("detected_timestamp") or 0)
            early, late = (a, b) if a_det <= b_det else (b, a)
            late.pending_start["offset_start_time_str"] = early.pending_start.get(
                "offset_start_time_str", late.pending_start.get("offset_start_time_str")
            )
            late.pending_start["block_id"] = early.pending_start.get(
                "block_id", late.pending_start.get("block_id")
            )
            late.block_counter = self._parse_block_num(late.pending_start["block_id"])
        if a.pending_end and b.pending_end:
            t = min(float(a.pending_end_time), float(b.pending_end_time))
            a.pending_end_time = t
            b.pending_end_time = t

    def check_pending(self, current_timestamp, current_time_str):
        with self.session_lock:
            self._sync_peer_pending_clocks_locked()
            # End paired fields in one pass so A does not finish a beat before B
            ending = []
            for ch in self.channels.values():
                if ch.pending_end and current_timestamp >= ch.pending_end_time:
                    ending.append(ch)
            if ending:
                end_ids = {ch.field_id for ch in ending}
                for ch in list(ending):
                    peer = self._peer_channel(ch)
                    if (
                        peer
                        and peer.session_active
                        and peer.field_id not in end_ids
                        and (peer.pending_end or self._sessions_paired(ch, peer))
                    ):
                        peer.pending_end = True
                        peer.pending_end_time = min(
                            float(getattr(peer, "pending_end_time", current_timestamp) or current_timestamp),
                            float(ch.pending_end_time),
                        )
                        ending.append(peer)
                        end_ids.add(peer.field_id)
                for ch in ending:
                    if ch.session_active:
                        self._end_session_locked(current_time_str, current_timestamp, ch)
                    ch.pending_end = False
            for ch in self.channels.values():
                if ch.pending_start and current_timestamp >= ch.pending_start_time:
                    self._execute_start(current_timestamp, ch)
                    ch.pending_start = None

    def _blocks_for_late_analysis(self, ch):
        """Rebuild block list at analysis time so post-QR (late) frames are included."""
        combined = list(ch.qr_blocks)
        if ch.between_session_data:
            combined.append({
                "id": "BETWEEN",
                "action": "BETWEEN_SESSIONS",
                "screens": [],
                "field": ch.field_id,
                "start_time": ch.between_session_start_time,
                "end_time": get_current_time_ms(),
                "data": list(ch.between_session_data),
            })
        return combined

    def _perform_late_analysis(self, field_id="A"):
        """Delayed analysis (timer thread). Acquires session_lock."""
        with self.session_lock:
            ch = self.channels.get(field_id) or self.channels["A"]
            self._perform_late_analysis_locked(ch)

    def _perform_late_analysis_locked(self, ch=None):
        """Compute one pending result. Caller must hold session_lock."""
        if ch is None:
            ch = self.channels["A"]
        if ch.pending_analysis is None:
            return

        action_data = ch.pending_analysis['action_data']
        action_type = ch.pending_analysis['action_type']
        video_index = ch.pending_analysis['video_index']
        block_id = ch.pending_analysis['block_id']
        screens = ch.pending_analysis['screens']

        combined_blocks = self._blocks_for_late_analysis(ch)
        action_index = 0
        for i, block in enumerate(combined_blocks):
            if block.get("id") == block_id:
                action_index = i
                break

        analysis_result = analyze_action_with_context(
            action_data,
            GOAL_LINES,
            action_type,
            combined_blocks,
            action_index
        )

        result_entry = {
            'id': block_id,
            'action': action_type,
            'screens': screens,
            'field': ch.field_id,
            'result': analysis_result['Result'],
            'winning_screen': analysis_result['Winning Screen'],
            'min_dist': analysis_result['Min Distance (px)'],
            'movement': analysis_result['Movement (px)'],
            'direction': analysis_result['Direction'],
            'aep': analysis_result.get('AEP', 'N/A'),
            'session_duration': analysis_result['Session Duration (s)'],
            'video_index': video_index,
            'finishing_time': analysis_result.get('Time of Min (s)', 0.0),
            'total_distance': 0.0,
            'ae': analysis_result.get('AE', 0.0)
        }

        ch.stats['results'].append(result_entry)
        session_folder = ch.recording_subdir or self.recording_dir
        try:
            payload = {
                'session_folder': session_folder,
                'action_result': result_entry
            }
            requests.post('http://127.0.0.1:8000/save-results-to-json', json=payload, timeout=1)
        except Exception as e:
            print(f"Failed to save result to results.json: {e}")

        print(
            f"  [{ch.label}] RESULT {block_id} {action_type}: {result_entry['result']} "
            f"(video {video_index}, dur={result_entry['session_duration']})"
        )
        ch.pending_analysis = None
        ch.analysis_timer = None
        ch._recent_between_gap = None
        ch._last_session_duration = None

    def _flush_pending_analysis_locked(self, ch=None):
        """Finish the previous shot before scheduling the next (required for T1.2)."""
        if ch is None:
            for channel in self.channels.values():
                self._flush_pending_analysis_locked(channel)
            return
        if ch.analysis_timer:
            try:
                ch.analysis_timer.cancel()
            except Exception:
                pass
            ch.analysis_timer = None
        if ch.pending_analysis is not None:
            self._perform_late_analysis_locked(ch)

    def _schedule_late_analysis_locked(self, ch, delay=None):
        if delay is None:
            delay = dynamic_analysis_delay(
                recent_gap_sec=getattr(ch, "_recent_between_gap", None),
                session_duration=getattr(ch, "_last_session_duration", None),
            )
        delay = float(delay)
        ch.analysis_started_at = time.time()
        field_id = ch.field_id
        ch.analysis_timer = threading.Timer(delay, lambda: self._perform_late_analysis(field_id))
        ch.analysis_timer.daemon = True
        ch.analysis_timer.start()

    def _end_session_locked(self, current_time_str, current_timestamp, ch=None):
        """End the active session. Must be called with self.session_lock held."""
        if ch is None:
            ch = self.channels["A"]
        if not ch.session_active:
            return
        ch.stats["sessions_completed"] += 1
        action_key = ch.current_action
        ch.stats["action_counts"][action_key] = ch.stats["action_counts"].get(action_key, 0) + 1
        ch.session_active = False
        if self.simulation_enabled:
            sim = self.simulators.get(ch.field_id)
            if sim is not None:
                sim.end_action()

        if getattr(ch, "qr_state", None) is not None:
            ch.qr_state["last_raw_data"] = None
            ch.qr_state["missing_since"] = None

        offset_end_time_str = add_offset_to_time(current_time_str, QR_OFFSET_SECONDS)

        if ch.current_qr_block:
            if ch.session_data:
                ch.current_qr_block["data"] = ch.session_data

            ch.current_qr_block["end_time"] = offset_end_time_str
            ch.current_qr_block["field"] = ch.field_id

            block_copy = ch.current_qr_block.copy()
            ch.qr_blocks.append(block_copy)

            video_index_file = os.path.join(SIMUST_PLAYER_DIRECTORY, "current_video_index.txt")
            video_index = 1
            if os.path.exists(video_index_file):
                try:
                    with open(video_index_file, 'r') as f:
                        video_index = int(f.read().strip())
                except Exception:
                    video_index = 1
            if video_index < 1:
                video_index = 1

            self._flush_pending_analysis_locked(ch)

            duration = current_timestamp - ch.session_start_timestamp
            ch._last_session_duration = float(duration)
            ch.pending_analysis = {
                'action_data': ch.current_qr_block,
                'screens': ch.current_screens,
                'action_type': ch.current_action,
                'block_id': ch.current_block_id,
                'video_index': video_index,
            }
            self._schedule_late_analysis_locked(ch)

            ch.current_qr_block = None

            session_fps_avg = ch.session_fps_sum / ch.session_frame_count if ch.session_frame_count > 0 else 0

            print(f"{'-'*50}")
            print(f"[{ch.label}] SESSION END - Frames: {ch.session_frame_count} | Duration: {duration:.2f}s | Avg FPS: {session_fps_avg:.1f}")
            print(f"End: {offset_end_time_str}")
            print(
                f"Analysis scheduled "
                f"(delay={dynamic_analysis_delay(ch._recent_between_gap, ch._last_session_duration):.2f}s, "
                f"gap_hint={ch._recent_between_gap})."
            )
            print(f"{'='*50}\n")

            self.save_recognition_json(ch)

        ch.active_goal_lines = {}
        ch.current_action = None
        ch.current_screens = []
        ch.current_keypoints = []
        ch.current_block_id = None
        ch.session_data = []
        ch.session_fps_sum = 0
        ch.session_frame_count = 0

        ch.between_sessions_active = True
        ch.between_session_data = []
        ch.between_session_start_time = offset_end_time_str
        ch.between_session_start_ts = current_timestamp
        ch.between_session_end_time = ""

    def _execute_end(self, current_time_str, current_timestamp, ch=None):
        """Public method: acquires lock and calls _end_session_locked."""
        with self.session_lock:
            if ch is None:
                for channel in self.channels.values():
                    if channel.session_active:
                        self._end_session_locked(current_time_str, current_timestamp, channel)
            else:
                self._end_session_locked(current_time_str, current_timestamp, ch)

    def _execute_start(self, current_timestamp, ch):
        p = ch.pending_start
        if not p:
            return

        if ch.between_sessions_active:
            ch.between_session_end_time = p["offset_start_time_str"]
            self.save_between_sessions_block(ch)
            ch.between_sessions_active = False

        ch.current_action = p["action"]
        ch.current_screens = p["screens"]
        ch.current_keypoints = p["keypoints"]
        ch.current_block_id = p["block_id"]
        ch.active_goal_lines = p["goal_lines"]
        ch.session_active = True
        ch.session_start_timestamp = current_timestamp
        ch.session_frame_count = 0
        ch.session_fps_sum = 0
        ch.session_data = []

        ch.current_qr_block = {
            "id": ch.current_block_id,
            "action": ch.current_action,
            "screens": ch.current_screens,
            "keypoints": ch.current_keypoints,
            "field": ch.field_id,
            "start_time": p["offset_start_time_str"],
            "end_time": "",
            "data": []
        }

        if self.simulation_enabled:
            sim = self.simulators.get(ch.field_id)
            if sim is not None:
                sim.start_action(ch.current_action, ch.current_screens)

        print(f"\n{'='*50}")
        print(f"[{ch.label}] SESSION {ch.current_block_id} - {ch.current_action}")
        print(f"Screens: {ch.current_screens}")
        print(f"Start: {p['offset_start_time_str']}")
        print(f"{'-'*50}")

    # ---- Drawing and UI methods ----
    def draw_goal_lines(self, frame, ch=None):
        channels = [ch] if ch is not None else list(self.channels.values())
        h, w = frame.shape[:2]
        sx = w / float(SIM_FRAME_WIDTH)
        sy = h / float(SIM_FRAME_HEIGHT)
        for channel in channels:
            if not channel.session_active or not channel.active_goal_lines:
                continue
            for screen_name, line_data in channel.active_goal_lines.items():
                x1, y1 = line_data['p0']
                x2, y2 = line_data['p1']
                p0 = (int(x1 * sx), int(y1 * sy))
                p1 = (int(x2 * sx), int(y2 * sy))
                cv2.line(frame, p0, p1, COLOR_GOAL_LINE, 3)
                cv2.circle(frame, p0, 5, (0, 0, 255), -1)
                cv2.circle(frame, p1, 5, (0, 0, 255), -1)
                cv2.putText(frame, f"GOAL {screen_name}", ((p0[0] + p1[0]) // 2 - 40, p0[1] - 10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
        return frame

    def draw_results_overlay(self, frame):
        """Team A labels on left slice; Team B on right slice — orange bold."""
        h, w = frame.shape[:2]
        mid = w // 2
        # BGR orange, bold
        label_color = (0, 165, 255)
        thickness = 2
        panels = [
            ("A", 10),
            ("B", mid + 10),
        ]
        for fid, left_x in panels:
            ch = self.channels.get(fid)
            if ch is None:
                continue
            results = ch.stats['results'][-8:] if ch.stats['results'] else []
            cv2.putText(frame, f"RESULTS {ch.label}", (left_x + 10, 25),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.55, label_color, thickness)
            cv2.line(frame, (left_x + 10, 30), (left_x + 330, 30), label_color, 2)
            for i, result in enumerate(results):
                action_id = result.get('id', '')
                action_type = result.get('action', '')
                action_result = result.get('result', '')
                winning = result.get('winning_screen', '')
                text = f"{action_id} {action_type}: {action_result}"
                if winning and winning != 'N/A':
                    text += f" -> {winning}"
                cv2.putText(frame, text, (left_x + 10, 50 + i * 28),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.48, label_color, thickness)
        return frame

    def draw_all_annotations(self, frame, balls, players):
        h, w = frame.shape[:2]
        mid_x = w // 2

        frame = self.draw_goal_lines(frame)

        for fid, poly in (("A", POLYGON_POINTS_A), ("B", POLYGON_POINTS_B)):
            if poly:
                pts = np.array(poly, dtype=np.int32)
                color = COLOR_POLYGON if fid == "A" else (0, 200, 255)
                cv2.polylines(frame, [pts], True, color, 2)

        any_active = any(ch.session_active for ch in self.channels.values())
        if any_active:
            cv2.putText(frame, "SESSION ACTIVE", (w // 2 - 80, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        else:
            cv2.putText(frame, "BETWEEN SESSIONS", (w // 2 - 90, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 255, 100), 1)

        for i, ball in enumerate(balls):
            cx, cy = ball['center']
            cv2.circle(frame, (cx, cy), 8, COLOR_BALL, -1)
            cv2.putText(frame, f"B{i+1}", (cx-15, cy-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_BALL, 2)

        for player_idx, player in enumerate(players):
            cv2.rectangle(frame, (player['bbox'][0], player['bbox'][1]),
                         (player['bbox'][2], player['bbox'][3]), COLOR_PLAYER, 2)
            tag = player.get("field") or ""
            cv2.putText(frame, f"P{player_idx+1}{tag}", (player['bbox'][0], player['bbox'][1] - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_PLAYER, 1)

        fps = self.tracker.current_fps
        fps_color = (0, 255, 0) if fps >= 20 else ((0, 255, 255) if fps >= 12 else (0, 0, 255))
        cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, fps_color, 2)

        for ch in self.channels.values():
            if not ch.session_active:
                continue
            x0 = 15 if ch.field_id == "A" else mid_x + 15
            overlay = frame.copy()
            cv2.rectangle(overlay, (x0 - 5, 50), (x0 + 340, 80), (0, 0, 0), -1)
            frame = cv2.addWeighted(overlay, 0.7, frame, 0.3, 0)
            cv2.putText(frame, f"{ch.label} {ch.current_block_id} - {ch.current_action}", (x0, 68),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        cv2.putText(frame, "FIELD A", (w // 4 - 50, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(frame, "FIELD B", (w // 4 * 3 - 50, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)
        cv2.line(frame, (mid_x, 0), (mid_x, h), (255, 255, 255), 2)
        frame = self.draw_results_overlay(frame)
        return frame

    # ---- Frame processing (with hip-point tracking) ----
    def _detections_for_frame(self, frame, current_timestamp):
        if self.simulation_enabled:
            h, w = frame.shape[:2]
            balls, players = [], []
            hips = {}
            for fid, sim in self.simulators.items():
                b, p, hip = sim.step(w, h)
                for item in b:
                    item = dict(item)
                    item["field"] = fid
                    balls.append(item)
                for item in p:
                    item = dict(item)
                    item["field"] = fid
                    players.append(item)
                hips[fid] = hip
                frame = sim.draw_on_frame(frame, b, p)
            return frame, balls, players, hips
        balls, players = self.tracker.detect_objects(frame)
        hips = {}
        for fid in ("A", "B"):
            ch = self.channels[fid]
            sx, sy = self.tracker.get_player_tracking_point_for_field(
                frame, players, fid, current_timestamp, ch.session_start_timestamp or current_timestamp
            )
            hips[fid] = (sx, sy)
        return frame, balls, players, hips

    def _append_frame_data(self, ch, balls, players, hip, current_timestamp, into_session):
        sx, sy = hip if hip else (None, None)
        if sx is not None and sy is not None:
            origin = ch.session_start_timestamp if into_session else (ch.between_session_start_ts or 0.0)
            rel_time = current_timestamp - origin if origin else 0.0
            ch.all_player_positions.append((rel_time, sx, sy))

        if into_session:
            origin = ch.session_start_timestamp
        else:
            origin = getattr(ch, "between_session_start_ts", 0.0) or 0.0
        rel_time = current_timestamp - origin if origin else 0.0
        mid_x = 640
        field_players = [p for p in players if p.get("field") == ch.field_id]
        tagged = [b for b in balls if b.get("field")]
        if tagged:
            field_balls = [b for b in balls if b.get("field") == ch.field_id]
        else:
            field_balls = [
                b for b in balls
                if (ch.field_id == "A" and b["center"][0] < mid_x)
                or (ch.field_id == "B" and b["center"][0] >= mid_x)
            ]

        frame_data = {
            't': round(rel_time, 3),
            'b': [[c[0], c[1]] for c in [ball['center'] for ball in field_balls]],
            'p': [[c[0], c[1]] for c in [player['center'] for player in field_players]],
            'hp': [sx, sy] if (sx is not None and sy is not None) else None,
            'field': ch.field_id,
        }
        if into_session:
            ch.session_data.append(frame_data)
            ch.session_frame_count += 1
            if ch.current_qr_block is not None:
                ch.current_qr_block["data"].append(frame_data)
        else:
            ch.between_session_data.append(frame_data)
        return sx, sy

    def process_dual_fields_frame(self, frame, current_timestamp):
        self.tracker.increment_frame_count()
        frame, balls, players, hips = self._detections_for_frame(frame, current_timestamp)

        for fid, ch in self.channels.items():
            hip = hips.get(fid, (None, None))
            into_session = bool(ch.session_active)
            sx, sy = self._append_frame_data(ch, balls, players, hip, current_timestamp, into_session)
            if sx is not None and sy is not None:
                cv2.circle(frame, (int(sx), int(sy)), 6, COLOR_HIP, -1)
                cv2.putText(frame, f"HIP {fid}", (int(sx) - 20, int(sy) - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_HIP, 1)
            if into_session:
                ch.session_fps_sum += self.tracker.current_fps

        self.frame_counter += 1
        self.tracker.update_fps()
        frame = self.draw_all_annotations(frame, balls, players)
        return frame

    def process_qr_detection(self, frame, current_time_str, current_timestamp):
        """Detect QR in Field A and Field B ROIs. ROI defines the field (keep A/B in sync)."""
        # Pass 1: detect both ROIs on this frame
        detected = {}
        for fid, ch in self.channels.items():
            roi = self.qr_rois.get(fid) or ch.qr_roi
            raw_data, bbox = detect_qr_in_roi(frame, roi)
            action, screens, keypoints = parse_qr_data(raw_data) if raw_data else ("", [], [])
            # Trust the ROI: do not drop QR based on screen→field mapping (that lagged B behind A).
            detected[fid] = {
                "raw": raw_data,
                "action": action,
                "screens": screens,
                "keypoints": keypoints,
                "bbox": bbox,
            }

        # Pass 2: flicker / missing handling
        new_qr_fields = []
        for fid, ch in self.channels.items():
            raw_data = detected[fid]["raw"]
            action = detected[fid]["action"]
            screens = detected[fid]["screens"]

            if raw_data:
                ch.qr_state["missing_since"] = None
                if (
                    ch.pending_end
                    and ch.qr_state["last_raw_data"] is not None
                    and raw_data == ch.qr_state["last_raw_data"]
                ):
                    ch.pending_end = False
            elif ch.current_qr_block or ch.session_active or ch.pending_start:
                if ch.qr_state["missing_since"] is None:
                    ch.qr_state["missing_since"] = current_timestamp
            else:
                ch.qr_state["missing_since"] = None

            is_new_qr = (
                raw_data and raw_data != ch.qr_state["last_raw_data"] and action and screens and
                (current_timestamp - ch.qr_state["last_detection_time"] >= ch.qr_state["cooldown"])
            )
            if is_new_qr:
                new_qr_fields.append(fid)

        # Shared action index: late Field B must JOIN peer's S{n}, not bump to S{n+1}
        # But never re-join a block this field already finished (SF-60N A duplicate / B skip).
        join_by_field = {}
        for fid in new_qr_fields:
            ch = self.channels[fid]
            peer = self._peer_channel(ch)
            if peer is None:
                continue
            if peer.field_id in new_qr_fields and not peer.session_active and not peer.pending_start:
                continue
            info = self._peer_join_info(ch, current_timestamp)
            if info and info.get("block_id"):
                join_by_field[fid] = info

        starters = [fid for fid in new_qr_fields if fid not in join_by_field]
        shared_num = None
        if starters:
            self.shared_action_index = max(
                int(getattr(self, "shared_action_index", 0) or 0) + 1,
                max(ch.block_counter for ch in self.channels.values()) + 1,
            )
            shared_num = self.shared_action_index
            for sim in self.simulators.values():
                sim.outcome_index = max(int(getattr(sim, "outcome_index", 0) or 0), shared_num - 1)

        for fid in new_qr_fields:
            ch = self.channels[fid]
            info = detected[fid]
            with self.session_lock:
                # New QR while active: end this field AND peer on the same action so
                # the peer cannot invite a re-join of the just-finished block.
                if ch.session_active:
                    self._end_paired_sessions_now(current_time_str, current_timestamp, ch)
                ch.pending_start = None
                ch.pending_end = False

            if ch.current_qr_block:
                ch.qr_blocks.append(ch.current_qr_block.copy())
                ch.current_qr_block = None

            join = join_by_field.get(fid)
            if join and self._field_completed_block(ch, join.get("block_id")):
                join = None

            if join:
                block_id = join["block_id"]
                ch.block_counter = self._parse_block_num(block_id)
                paired_start = join.get("paired_session_start")
                paired_offset = join.get("offset_start_time_str")
            else:
                if shared_num is None:
                    self.shared_action_index = max(
                        int(getattr(self, "shared_action_index", 0) or 0) + 1,
                        max(c.block_counter for c in self.channels.values()) + 1,
                    )
                    shared_num = self.shared_action_index
                    for sim in self.simulators.values():
                        sim.outcome_index = max(
                            int(getattr(sim, "outcome_index", 0) or 0), shared_num - 1
                        )
                ch.block_counter = int(shared_num)
                block_id = f"S{shared_num}"
                paired_start = None
                paired_offset = None
                peer = self._peer_channel(ch)
                # Peer still stuck on a previous action → end it so both can align
                if peer and peer.session_active and peer.current_block_id != block_id:
                    with self.session_lock:
                        if peer.session_active:
                            self._end_session_locked(current_time_str, current_timestamp, peer)
                if peer and peer.pending_start and peer.pending_start.get("block_id") == block_id:
                    paired_start = float(peer.pending_start_time)
                    paired_offset = peer.pending_start.get("offset_start_time_str")

            ch.qr_state["last_raw_data"] = info["raw"]
            ch.qr_state["last_detection_time"] = current_timestamp
            ch.qr_state["detection_count"] += 1
            ch.qr_state["missing_since"] = None
            self.schedule_session_start(
                info["action"], info["screens"], info["keypoints"],
                block_id, current_time_str, current_timestamp, ch,
                paired_session_start=paired_start,
                paired_offset_str=paired_offset,
            )

            bbox = info["bbox"]
            if bbox is not None and len(bbox) > 0 and self.visualization_enabled:
                pts = bbox[0].astype(int)
                cv2.polylines(frame, [pts], True, COLOR_QR, 2)
                cv2.putText(frame, f"QR {fid} {block_id}", (pts[0][0], max(20, pts[0][1] - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_QR, 1)

        # Pass 3: end sessions / max duration (fields that did not just start)
        for fid, ch in self.channels.items():
            if fid in new_qr_fields:
                continue
            raw_data = detected[fid]["raw"]
            if (
                not raw_data
                and ch.current_qr_block
                and not ch.pending_end
                and ch.qr_state["missing_since"] is not None
                and (current_timestamp - ch.qr_state["missing_since"]) >= QR_DISAPPEAR_DEBOUNCE
            ):
                self.schedule_session_end(current_time_str, current_timestamp, ch)
            elif ch.session_active and (current_timestamp - ch.session_start_timestamp) > MAX_SESSION_DURATION:
                self._execute_end(current_time_str, current_timestamp, ch)
                ch.pending_end = False

        return frame

    # ---- Camera capture threads ----
    def capture_screen(self):
        with mss.mss() as sct:
            while self.screen_capture_running:
                try:
                    img = sct.grab(self.screen_monitor)
                    frame = np.array(img)
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                    current_time_str = get_current_time_ms()
                    current_timestamp = time.time()
                    paused = read_pause_setting()
                    if paused:
                        if not self.operator_paused:
                            self._freeze_for_pause()
                        time.sleep(1.0 / 30.0)
                        continue
                    if self.operator_paused:
                        self._unfreeze_after_pause()
                    self.check_pending(current_timestamp, current_time_str)
                    frame = self.process_qr_detection(frame, current_time_str, current_timestamp)
                    time.sleep(1.0 / 30.0)
                except Exception as e:
                    time.sleep(0.1)

    def capture_stream(self, cam_name, url):
        while self.camera_running:
            try:
                cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                if not cap.isOpened():
                    time.sleep(2)
                    continue
                while self.camera_running:
                    ret, frame = cap.read()
                    if not ret:
                        break

                    h, w = frame.shape[:2]
                    target_h = 360
                    target_w = int(w * target_h / h)
                    frame = cv2.resize(frame, (target_w, target_h))

                    with self.frame_locks[cam_name]:
                        self.frame_buffers[cam_name] = frame.copy()
                    try:
                        while self.frame_queues[cam_name].qsize() >= 2:
                            self.frame_queues[cam_name].get_nowait()
                        self.frame_queues[cam_name].put_nowait(frame.copy())
                    except:
                        pass
                cap.release()
                time.sleep(2)
            except:
                time.sleep(2)

    def get_frames(self):
        frames = {}
        for cam in self.cameras:
            try:
                frames[cam] = self.frame_queues[cam].get_nowait()
            except queue.Empty:
                with self.frame_locks[cam]:
                    if self.frame_buffers[cam] is not None:
                        frames[cam] = self.frame_buffers[cam].copy()
                    else:
                        return None, None
        return frames.get("camera-1"), frames.get("camera-8")

    def stitch_frames(self, left, right):
        if left is None or right is None:
            return None
        h_l, w_l = left.shape[:2]
        h_r, w_r = right.shape[:2]
        if h_l != h_r:
            target_h = min(h_l, h_r)
            if h_l != target_h:
                scale = target_h / h_l
                left = cv2.resize(left, (int(w_l * scale), target_h))
            if h_r != target_h:
                scale = target_h / h_r
                right = cv2.resize(right, (int(w_r * scale), target_h))
        return np.hstack([left, right])

    def show_frame(self, frame):
        if not self.visualization_enabled:
            return

        if not self.window_created:
            cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(self.window_name, DISPLAY_WIDTH, DISPLAY_HEIGHT)
            cv2.moveWindow(self.window_name, 100, 100)
            self.window_created = True

        h, w = frame.shape[:2]
        scale = min(DISPLAY_WIDTH / w, DISPLAY_HEIGHT / h)
        new_w, new_h = int(w * scale), int(h * scale)
        display_frame = cv2.resize(frame, (new_w, new_h))

        canvas = np.zeros((DISPLAY_HEIGHT, DISPLAY_WIDTH, 3), dtype=np.uint8)
        x_offset = (DISPLAY_WIDTH - new_w) // 2
        y_offset = (DISPLAY_HEIGHT - new_h) // 2
        canvas[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = display_frame

        cv2.imshow(self.window_name, canvas)
        cv2.waitKey(1)

    def _close_viz_window(self):
        if not self.window_created:
            return
        try:
            cv2.destroyWindow(self.window_name)
            cv2.waitKey(1)
        except Exception:
            pass
        self.window_created = False

    def destroy_window(self):
        self._close_viz_window()

    def _apply_visualization_setting(self):
        new_viz = read_visualization_setting()
        if new_viz is None or new_viz == self.visualization_enabled:
            return
        self.visualization_enabled = new_viz
        print(f"Visualization: {'ON' if self.visualization_enabled else 'OFF'}")
        if not self.visualization_enabled:
            self._close_viz_window()

    def _freeze_for_pause(self):
        with self._pause_lock:
            if self.operator_paused:
                return
            self.operator_paused = True
            self._pause_started_at = time.time()
            for ch in self.channels.values():
                if ch.analysis_timer:
                    ch.analysis_timer.cancel()
                    started = ch.analysis_started_at or self._pause_started_at
                    ch._paused_analysis_remaining = max(
                        0.05, LATE_ANALYSIS_DELAY - (self._pause_started_at - started)
                    )
                    ch.analysis_timer = None
            print("PAUSED — detection, analysis, and saving frozen")

    def _unfreeze_after_pause(self):
        with self._pause_lock:
            if not self.operator_paused:
                return
            dt = time.time() - (self._pause_started_at or time.time())
            for ch in self.channels.values():
                if ch.pending_start:
                    ch.pending_start_time += dt
                    offset = ch.pending_start.get("offset_start_time_str")
                    if offset:
                        ch.pending_start["offset_start_time_str"] = add_offset_to_time(offset, dt)
                if ch.pending_end:
                    ch.pending_end_time += dt
                    end_str = getattr(ch, "pending_end_time_str", "")
                    if end_str:
                        ch.pending_end_time_str = add_offset_to_time(end_str, dt)
                if ch.session_active:
                    ch.session_start_timestamp += dt
                current_block = getattr(ch, "current_qr_block", None)
                if current_block and current_block.get("start_time"):
                    current_block["start_time"] = add_offset_to_time(current_block["start_time"], dt)
                if ch.between_sessions_active and ch.between_session_start_ts:
                    ch.between_session_start_ts += dt
                between_start = getattr(ch, "between_session_start_time", None)
                if between_start:
                    ch.between_session_start_time = add_offset_to_time(between_start, dt)
                last_det = (getattr(ch, "qr_state", None) or {}).get("last_detection_time")
                if last_det:
                    ch.qr_state["last_detection_time"] = last_det + dt
                if ch._paused_analysis_remaining is not None:
                    field_id = ch.field_id
                    remaining = ch._paused_analysis_remaining
                    ch.analysis_started_at = time.time()
                    ch.analysis_timer = threading.Timer(
                        remaining, lambda fid=field_id: self._perform_late_analysis(fid)
                    )
                    ch.analysis_timer.daemon = True
                    ch.analysis_timer.start()
                    ch._paused_analysis_remaining = None
            for simulator in self.simulators.values():
                if getattr(simulator, "start_ts", 0):
                    simulator.start_ts += dt
                if getattr(simulator, "late_start_ts", 0):
                    simulator.late_start_ts += dt
            self.operator_paused = False
            self._pause_started_at = 0
            print("RESUMED — continuing from the pause point")

    def _apply_simulation_setting(self):
        new_sim = read_simulation_setting()
        if new_sim is None or new_sim == self.simulation_enabled:
            return
        self.simulation_enabled = new_sim
        print(f"Arena simulation: {'ON' if self.simulation_enabled else 'OFF'} (Field A + Field B)")
        if self.simulation_enabled:
            for fid, ch in self.channels.items():
                if ch.session_active:
                    self.simulators[fid].start_action(ch.current_action, ch.current_screens)
        else:
            for sim in self.simulators.values():
                sim.end_action()

    # ---- Main loop ----
    def run(self):
        screen_thread = threading.Thread(target=self.capture_screen, daemon=True)
        screen_thread.start()

        for name, config in self.cameras.items():
            t = threading.Thread(target=self.capture_stream, args=(name, config["address"]), daemon=True)
            t.start()

        time.sleep(3)

        self.start_new_recording()
        viz = read_visualization_setting()
        self.visualization_enabled = bool(viz)

        last_viz_check = 0
        recording_started_for_video = False
        last_stitched = None

        print("\n" + "=" * 60)
        print("READY - Press Ctrl+C to stop")
        print("=" * 60)
        print("Detection ALWAYS active (Balls both cameras, Players Field A + Field B)")
        print("QR: dual ROI on 3840x1080 (Field A left / Field B right)")
        print("Arena simulation: artificial ball/player injected on both fields when enabled")
        print("Results overlay: Team A left panel / Team B right panel")
        print("Saving field_A/ and field_B/ recognition + results separately")
        print("=" * 60 + "\n")

        try:
            while self.camera_running:
                current_timestamp = time.time()
                current_time_str = get_current_time_ms()

                paused = read_pause_setting()
                if paused:
                    if not self.operator_paused:
                        self._freeze_for_pause()
                    if self.visualization_enabled and last_stitched is not None:
                        self.show_frame(last_stitched)
                    time.sleep(0.05)
                    continue
                if self.operator_paused:
                    self._unfreeze_after_pause()

                self.check_pending(current_timestamp, current_time_str)

                if current_timestamp - last_viz_check >= 0.5:
                    self._apply_visualization_setting()
                    self._apply_simulation_setting()
                    last_viz_check = current_timestamp

                left, right = self.get_frames()

                if left is None or right is None:
                    if self.simulation_enabled:
                        left = self.simulator_a.blank_half()
                        right = self.simulator_b.blank_half()
                    else:
                        time.sleep(0.01)
                        continue

                stitched = self.stitch_frames(left, right)
                if stitched is None:
                    continue

                if stitched is not None and os.path.exists(CAPTURE_TRIGGER_FILE):
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    capture_path = os.path.join(CAPTURE_OUTPUT_DIR, f"calibration_capture_{timestamp}.jpg")
                    cv2.imwrite(capture_path, stitched)
                    print(f"Captured frame saved to {capture_path}")
                    os.remove(CAPTURE_TRIGGER_FILE)
                    with open(os.path.join(CAPTURE_OUTPUT_DIR, "last_capture.txt"), 'w') as f:
                        f.write(capture_path)

                if not recording_started_for_video and stitched is not None:
                    h, w = stitched.shape[:2]
                    video_path = os.path.join(self.recording_dir, "realtime_recording.avi")
                    self.video_saver.start(video_path, w, h, TARGET_FPS)
                    recording_started_for_video = True

                stitched = self.process_dual_fields_frame(stitched, current_timestamp)

                if self.recording_active and self.video_saver.is_recording:
                    self.video_saver.write_frame(stitched)

                last_stitched = stitched

                if self.visualization_enabled:
                    self.show_frame(stitched)

                time.sleep(0.005)

        except KeyboardInterrupt:
            pass
        finally:
            if self.recording_active:
                self.stop_recording()
            self.destroy_window()
            print(f"\nSaved: {self.recording_dir}")

def main():
    camera = SimustRealtimeCamera()
    try:
        camera.run()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("Done.")

if __name__ == "__main__":
    main()