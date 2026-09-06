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
SAVE_EVERY_N_ACTIONS = 1

DEFAULT_RECORDINGS_DIR = "C:/Users/siama/Documents/simust_realtime_recordings"
SIMUST_PLAYER_DIRECTORY = "C:/Users/siama/Documents/simust_player"

DETECTION_CONF = 0.2
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
COLOR_GOAL_RECT = (0, 200, 255)  # suggested GOAL rectangle (visual only)

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

# ============================================================================
# POLYGON ROI – DEFINE YOUR 17 POINTS HERE (stitched frame coordinates)
# ============================================================================
POLYGON_POINTS = [
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
    (12, 297)
]

# ============================================================================
# UPDATED ANALYSIS CONSTANTS (from Code A)
# ============================================================================
SCALE = 1.0
CORRECT_THRESHOLD = 40
LATE_SEARCH_DURATION = 2.5
MIN_MOVEMENT_THRESHOLD = 33
MOVEMENT_RADIUS = 120
LEAVE_THRESHOLD = 200          # kept but not used in simplified check
SEARCH_FRAMES = 15
MIN_NEAR_FRAMES = 3            # kept but not used in simplified check
PRE_FRAMES = 6                 # kept but not used in simplified check
ENTRY_MARGIN = 1.0             # not used in simplified check

# Maximum distance to consider a PASS as a valid finish attempt
FINISH_DIST = 100   # px – increased from 100 to capture all correct actions
GOAL_POST_SLACK = 0.10  # posts of screens 1 and 8 count as the goal mouth

PIXEL_TO_METER_SCALE = 0.0259

# Screen-specific thresholds (PASS, TARGET, GOAL)
SCREEN_CORRECT_THRESHOLDS = {
    '2': 22,  '3': 30,  '4': 10,   '5': 10,   '6': 13,  '7': 22,
    '9': 22,  '10': 13, '11': 10,  '12': 10,  '13': 30, '14': 30,
    '1': 13,  '8': 13,
    '9L': 40,   '6L': 40,
}

# Screen-specific thresholds for PRESS
PRESS_SCREEN_THRESHOLDS = {
    '2': 120,   '7': 120,   '9': 120,   '14': 120,
}

# GOAL-specific thresholds (overrides)
GOAL_SCREEN_THRESHOLDS = {
    '8': 73,
    '1': 73,
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

# GOAL mouth: software GOAL_LINES is the BOTTOM. Posts go image-up; height is
# one quarter of the bottom-line length. Used only for GOAL scoring.
GOAL_RECT_HEIGHT_RATIO = 0.25
GOAL_LINE_SLACK_PX = 12
GOAL_SIDE_SLACK_PX = 12
GOAL_CROSS_SPEED_PX_S = 18.0
GOAL_CROSS_HORIZON_S = 1.4
SUGGESTED_GOAL_HEIGHT_PX = 90  # probe marker only
SUGGESTED_GOAL_LINE_SLACK_PX = 12
GOAL_PROBE_TRAVEL_S = 1.9
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


def goal_mouth_height(p0, p1):
    _along, width = goal_along_axis(p0, p1)
    return max(40.0, width * GOAL_RECT_HEIGHT_RATIO)


def goal_line_coords(point, p0, p1):
    along, width = goal_along_axis(p0, p1)
    up = goal_up_axis(p0, p1)
    vx = float(point[0]) - float(p0[0])
    vy = float(point[1]) - float(p0[1])
    t = vx * along[0] + vy * along[1]
    h = vx * up[0] + vy * up[1]
    return t, h, width, along, up


def suggested_goal_corners(p0, p1, height=None):
    if height is None:
        height = goal_mouth_height(p0, p1)
    up = goal_up_axis(p0, p1)
    a = (float(p0[0]), float(p0[1]))
    b = (float(p1[0]), float(p1[1]))
    c = (b[0] + up[0] * height, b[1] + up[1] * height)
    d = (a[0] + up[0] * height, a[1] + up[1] * height)
    return a, b, c, d


def point_in_goal_mouth(point, p0, p1, height=None,
                        line_slack=GOAL_LINE_SLACK_PX, side_slack=GOAL_SIDE_SLACK_PX):
    """True if the point is in the GOAL rectangle (bottom = software line)."""
    if height is None:
        height = goal_mouth_height(p0, p1)
    t, h, width, _along, _up = goal_line_coords(point, p0, p1)
    return (-side_slack) <= t <= (width + side_slack) and (-line_slack) <= h <= (height + 8.0)


def point_in_suggested_goal(point, p0, p1, height=None,
                            line_slack=SUGGESTED_GOAL_LINE_SLACK_PX, side_slack=8.0):
    return point_in_goal_mouth(point, p0, p1, height=height, line_slack=line_slack, side_slack=side_slack)


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


def recent_ball_velocity(positions, window_s=0.35):
    """px/s from the last moving window. A held ball returns ~zero."""
    if not positions or len(positions) < 2:
        return (0.0, 0.0)
    t1, x1, y1 = positions[-1]
    chosen = None
    for row in reversed(positions[:-1]):
        if t1 - row[0] >= window_s:
            chosen = row
            break
    if chosen is None:
        chosen = positions[0]
    dt = t1 - chosen[0]
    if dt < 0.08:
        return (0.0, 0.0)
    return ((x1 - chosen[1]) / dt, (y1 - chosen[2]) / dt)


def predict_goal_crossing(positions, p0, p1, horizon=GOAL_CROSS_HORIZON_S):
    """If recent velocity aims through the mouth, return (t_cross, proj_t, dist)."""
    if not positions or len(positions) < 2:
        return None
    vx, vy = recent_ball_velocity(positions)
    up = goal_up_axis(p0, p1)
    vh = vx * up[0] + vy * up[1]
    if vh < GOAL_CROSS_SPEED_PX_S:
        return None
    t_last, x, y = positions[-1]
    along_t, h, width, along, _up = goal_line_coords((x, y), p0, p1)
    if h > goal_mouth_height(p0, p1) + 8.0:
        return None
    if h >= -GOAL_LINE_SLACK_PX:
        if (-GOAL_SIDE_SLACK_PX) <= along_t <= (width + GOAL_SIDE_SLACK_PX):
            proj = 0.0 if width <= 1e-6 else max(0.0, min(1.0, along_t / width))
            return (t_last, proj, max(0.0, -h))
        return None
    t_cross = -h / vh
    if t_cross < 0.0 or t_cross > horizon:
        return None
    cx = x + vx * t_cross
    cy = y + vy * t_cross
    along_c, _hc, width_c, _a, _u = goal_line_coords((cx, cy), p0, p1)
    if (-GOAL_SIDE_SLACK_PX) <= along_c <= (width_c + GOAL_SIDE_SLACK_PX):
        proj = 0.0 if width_c <= 1e-6 else max(0.0, min(1.0, along_c / width_c))
        return (t_last + t_cross, proj, 0.0)
    return None


def first_goal_mouth_hit(positions, p0, p1):
    height = goal_mouth_height(p0, p1)
    best = None
    first_t = None
    for t, x, y in positions:
        if not point_in_goal_mouth((x, y), p0, p1, height):
            continue
        if first_t is None:
            first_t = t
        eff, proj = get_effective_distance((x, y), p0, p1)
        if best is None or eff < best[0]:
            best = (eff, t, proj)
    return first_t, best


def left_goal_mouth(positions, p0, p1, after_t):
    """True if the ball enters the mouth then goes back onto the pitch."""
    if after_t is None or not positions:
        return False
    height = goal_mouth_height(p0, p1)
    seen = False
    away = 0
    for t, x, y in positions:
        if t + 1e-6 < after_t:
            continue
        if point_in_goal_mouth((x, y), p0, p1, height):
            seen = True
            away = 0
            continue
        _along_t, h, _w, _a, _u = goal_line_coords((x, y), p0, p1)
        if seen and h < -20.0:
            away += 1
            if away >= 3:
                return True
    return False


def goal_finish_evidence(positions, screens, goal_lines):
    """Best in-mouth or predicted-crossing evidence on this track."""
    best = None
    for screen in screens:
        p0, p1 = get_screen_info(screen, goal_lines)
        if p0 is None:
            continue
        first_t, hit = first_goal_mouth_hit(positions, p0, p1)
        if hit is not None:
            eff, t_hit, proj = hit
            cand = {
                "screen": screen,
                "t": first_t if first_t is not None else t_hit,
                "dist": eff,
                "proj": proj,
                "kind": "mouth",
            }
            if best is None or cand["dist"] < best["dist"]:
                best = cand
            continue
        cross = predict_goal_crossing(positions, p0, p1)
        if cross is None:
            continue
        t_cross, proj, dist = cross
        cand = {
            "screen": screen,
            "t": t_cross,
            "dist": dist,
            "proj": proj,
            "kind": "predict",
        }
        if best is None or cand["dist"] < best["dist"]:
            best = cand
    return best


def analyze_goal_with_context(action_id, screens, track, full_track, session_duration,
                              movement, direction, goal_lines):
    """GOAL only: rectangle mouth + heading through dropouts. No Miss."""
    session_ev = goal_finish_evidence(track, screens, goal_lines)
    extra = [p for p in (full_track or []) if p[0] > session_duration + 1e-6]
    late_ev = goal_finish_evidence(extra, screens, goal_lines) if extra else None

    result = "Wrong"
    winning_screen = "N/A"
    display_time = "-"
    display_duration = "-"
    min_dist_display = None
    best_proj_t = None
    evidence = None

    if session_ev is not None:
        p0, p1 = get_screen_info(session_ev["screen"], goal_lines)
        if not left_goal_mouth(full_track, p0, p1, session_ev["t"]):
            result = "Correct"
            evidence = session_ev
    elif late_ev is not None:
        p0, p1 = get_screen_info(late_ev["screen"], goal_lines)
        if not left_goal_mouth(full_track, p0, p1, late_ev["t"]):
            result = "Late"
            evidence = late_ev

    if evidence is not None:
        winning_screen = evidence["screen"]
        display_time = f"{evidence['t']:.3f}"
        display_duration = f"{session_duration:.3f}"
        min_dist_display = evidence["dist"]
        best_proj_t = evidence["proj"]

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
        self.total_balls_detected = 0
        self.total_players_detected = 0
        self.frame_process_count = 0
        self.last_fps_time = time.time()
        self.current_fps = 0
        self.polygon = POLYGON_POINTS

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
        """Fast detection - balls on both halves, players on left half only, filtered by polygon."""
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
                    det = {'center': center, 'bbox': [x1, y1, x2, y2], 'confidence': round(confidence, 3)}
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
                    if class_id == 0:
                        confidence = float(box.conf)
                        xyxy = box.xyxy[0].cpu().numpy()
                        x1 = int(xyxy[0]) + mid_x
                        y1 = int(xyxy[1])
                        x2 = int(xyxy[2]) + mid_x
                        y2 = int(xyxy[3])
                        x1 = max(mid_x, min(x1, orig_w-1)); y1 = max(0, min(y1, orig_h-1))
                        x2 = max(x1+1, min(x2, orig_w)); y2 = max(y1+1, min(y2, orig_h))
                        center = [(x1+x2)//2, (y1+y2)//2]
                        det = {'center': center, 'bbox': [x1, y1, x2, y2], 'confidence': round(confidence, 3)}
                        balls.append(det)
        except Exception as e:
            pass

        # ----- FILTER PLAYERS BY POLYGON -----
        if self.polygon:
            # Use bottom-center of the bounding box (feet) for the polygon check
            players = [p for p in players if is_inside_polygon(((p['bbox'][0] + p['bbox'][2]) // 2, p['bbox'][3]), self.polygon)]

        # Sort by bounding box area (largest = closest to camera)
        players.sort(key=lambda p: (p['bbox'][2]-p['bbox'][0]) * (p['bbox'][3]-p['bbox'][1]), reverse=True)
        players = players[:self.max_players]

        self.total_balls_detected += len(balls)
        self.total_players_detected += len(players)

        return balls, players

    def get_player_tracking_point(self, frame, players, current_timestamp, session_start_timestamp):
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

        # Apply 1‑Euro smoothing
        rel_time = current_timestamp - session_start_timestamp
        smooth_x = self.filter_x.filter(hip_point[0], rel_time)
        smooth_y = self.filter_y.filter(hip_point[1], rel_time)

        return smooth_x, smooth_y

    def update_fps(self):
        current_time = time.time()
        elapsed = current_time - self.last_fps_time
        if elapsed >= 1.0:
            self.current_fps = self.frame_process_count / elapsed
            self.frame_process_count = 0
            self.last_fps_time = current_time
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
    screen_str = str(screen)
    base_screen = screen_str.rstrip('LR')
    if screen_str in goal_lines:
        line = goal_lines[screen_str]
    elif base_screen in goal_lines:
        line = goal_lines[base_screen]
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
def search_late_across_blocks(current_index: int, all_data: List[dict],
                               screens: List[str], goal_lines: Dict,
                               key: str, action_end_time: datetime,
                               action_type: str) -> Tuple[bool, Optional[str], Optional[float], float, Optional[float]]:
    """
    Returns: (found, screen, time_offset, distance, proj_t)
    Used for non-GOAL actions.
    """
    if current_index + 1 >= len(all_data):
        return False, None, None, float('inf'), None

    best_screen = None
    best_dist = float('inf')
    best_time = None
    best_proj_t = None

    def get_threshold(screen: str) -> float:
        return get_threshold_for_screen(screen, action_type)

    for idx in range(current_index + 1, len(all_data)):
        block = all_data[idx]
        block_start_str = block.get('start_time')
        if not block_start_str:
            continue
        try:
            block_start = datetime.strptime(block_start_str, "%H:%M:%S.%f")
        except:
            continue

        offset = (block_start - action_end_time).total_seconds()
        if offset > LATE_SEARCH_DURATION:
            break

        block_data = block.get('data', [])
        if not block_data:
            continue
        positions = get_positions_from_data(block_data, key, SCALE)
        if not positions:
            continue

        filtered = filter_static_ball_positions(positions)
        if not filtered:
            continue

        use_near = action_type in ['PASS']
        if use_near:
            near_positions = filter_positions_near_goal_lines(filtered, screens, goal_lines)
            if not is_ball_moving(near_positions):
                continue
        else:
            if not is_ball_moving(filtered):
                continue

        best_screen_block, best_dist_block, best_time_block, best_proj_block = find_min_distance_to_screens(
            filtered, screens, goal_lines, require_movement=False
        )

        if best_screen_block is not None:
            threshold = get_threshold(best_screen_block)
            if best_dist_block <= threshold:
                absolute_time = offset + (best_time_block if best_time_block is not None else 0)
                if absolute_time <= LATE_SEARCH_DURATION and best_dist_block < best_dist:
                    best_dist = best_dist_block
                    best_screen = best_screen_block
                    best_time = absolute_time
                    best_proj_t = best_proj_block

    if best_screen is not None:
        return True, best_screen, best_time, best_dist, best_proj_t
    else:
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


def arrival_depth_for(screen, action_type):
    threshold = get_threshold_for_screen(screen, action_type)
    if action_type == "GOAL":
        return float(threshold)
    return float(max(FINISH_DIST, threshold))


def in_goal_area(point, p0, p1, depth):
    """Goal mouth including posts. Cameras face screens 1 and 8."""
    dist, proj_t, d_left, d_right = compute_projection(point, p0, p1)
    if dist <= depth and (-GOAL_POST_SLACK) <= proj_t <= (1.0 + GOAL_POST_SLACK):
        return True
    post_r = min(float(depth), 30.0)
    return d_left <= post_r or d_right <= post_r


def first_arrival_time(positions, screen, goal_lines, depth):
    p0, p1 = get_screen_info(screen, goal_lines)
    if p0 is None:
        return None
    for t, x, y in positions:
        if in_goal_area((x, y), p0, p1, depth):
            return t
    return None


def best_arrival_in_positions(positions, screens, goal_lines, action_type):
    best = None
    depth_used = None
    for screen in screens:
        p0, p1 = get_screen_info(screen, goal_lines)
        if p0 is None:
            continue
        depth = arrival_depth_for(screen, action_type)
        for t, x, y in positions:
            if not in_goal_area((x, y), p0, p1, depth):
                continue
            eff, proj = get_effective_distance((x, y), p0, p1)
            if best is None or eff < best[0]:
                best = (eff, t, screen, proj)
                depth_used = depth
    return best, depth_used


def departed_goal_area(positions, screen, goal_lines, arrive_time, depth):
    """True if the object leaves the goal area after the arrival time."""
    p0, p1 = get_screen_info(screen, goal_lines)
    if p0 is None or arrive_time is None:
        return False
    leave_depth = float(depth) * 1.15
    seen_in = False
    for t, x, y in positions:
        if t + 1e-6 < arrive_time:
            continue
        if in_goal_area((x, y), p0, p1, depth):
            seen_in = True
            continue
        if seen_in and t > arrive_time + 0.08 and not in_goal_area((x, y), p0, p1, leave_depth):
            return True
    return False


def extended_track(positions, action_index, all_data, key, action_end_time, session_start_time, window=2.5):
    extra = []
    if action_end_time is not None and session_start_time is not None:
        extra = get_positions_from_blocks_after(
            action_index, all_data, key, action_end_time, session_start_time, time_window=window
        )
    if not extra:
        return list(positions or [])
    merged = list(positions or []) + list(extra)
    merged.sort(key=lambda p: p[0])
    return merged

# ================================================================
# Helper to compute AEP orientation for a single action (from code A)
# ================================================================

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
    movement, direction = analyze_movement(track)
    full_track = extended_track(
        track, action_index, all_data, key, action_end_time, session_start_time
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
        arrival, depth = best_arrival_in_positions(track, screens, goal_lines, action_type)
        if arrival is not None:
            best_eff_dist, best_min_time, best_screen, best_proj_t = arrival
            arrive_t = first_arrival_time(track, best_screen, goal_lines, depth)
            if arrive_t is None:
                arrive_t = best_min_time
            came_back = departed_goal_area(
                full_track, best_screen, goal_lines, arrive_t, depth
            )
            # Arrive and come back = Correct. Arrive and stay = Miss.
            if came_back:
                result = 'Correct'
                winning_screen = best_screen
                display_time = f"{best_min_time:.3f}"
                display_duration = f"{session_duration:.3f}"
                min_dist_display = best_eff_dist
            else:
                result = 'Miss'
                winning_screen = best_screen
                min_dist_display = best_eff_dist
        else:
            if action_end_time is not None:
                found_late, late_screen, late_time, late_dist, late_proj = search_late_across_blocks(
                    action_index, all_data, screens, goal_lines, key, action_end_time, action_type
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
      Correct — arrive in the goal area during the session and do not come back.
      Late    — arrive after the session and do not come back.
      Wrong   — any other case.
    When GOAL_PROBE is True the ball walks slowly through named zones so the
    mouth can be judged by eye. Scoring is unchanged.
    """

    PLAYER_HOME = (280.0, 268.0)
    BALL_HOME = (302.0, 282.0)
    PASS_CYCLE = ("correct", "miss", "late", "wrong")
    OTHER_CYCLE = ("correct", "miss", "late", "wrong")
    GOAL_CYCLE = ("correct", "late", "wrong")
    GOAL_PROBE = True

    def __init__(self):
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
        self.wrong_xy = (420.0, 200.0)
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
            self.miss_xy = self._perp_from_mid(78)
            # Hold on the pitch, outside the mouth, so a late shot is not already in.
            if self.line_p0 and self.line_p1:
                up = goal_up_axis(self.line_p0, self.line_p1)
                along, _w = goal_along_axis(self.line_p0, self.line_p1)
                mid = self.target_xy
                pitch = 160.0
                self.late_hold_xy = self._clip(mid[0] - up[0] * pitch, mid[1] - up[1] * pitch)
                self.late_start_xy = self._clip(
                    self.late_hold_xy[0] + along[0] * 36.0,
                    self.late_hold_xy[1] + along[1] * 36.0,
                )
            else:
                self.late_start_xy, self.late_hold_xy = self._late_local_pair(118.0, 44.0, goal=True)
            self.goal_late_start_xy = self.late_start_xy
            self.wrong_xy = self._offset_from_line(240)
        else:
            self.miss_xy = self._offset_from_line(78)
            self.late_start_xy, self.late_hold_xy = self._late_local_pair(118.0, 44.0, goal=False)
            self.goal_late_start_xy = self.late_start_xy
            self.wrong_xy = self._far_from_all_screens(240, min_from_home=50)
        self.late_finish_xy = self._closest_screen_mid(self.late_hold_xy)
        self.late_finish_roll_xy = self._along_line_from(self.late_finish_xy, 28.0)
        self.start_xy = self.BALL_HOME
        self.probe_name = ""
        self.travel_s = 0.70
        # Screen 1's mouth covers the left-camera baseline; home sits inside it.
        # Start from the pitch side so in-session "late" / "wrong" are not already arrivals.
        if self.action == "GOAL" and self.line_p0 and self.line_p1:
            goal_screen = self.screens[0] if self.screens else "8"
            depth = arrival_depth_for(goal_screen, "GOAL")
            if in_goal_area(self.BALL_HOME, self.line_p0, self.line_p1, depth):
                self.start_xy = self._perp_from_mid(max(depth + 40.0, 110.0))
            up = goal_up_axis(self.line_p0, self.line_p1)
            mid = self.target_xy
            self.start_xy = (mid[0] - up[0] * 150.0, mid[1] - up[1] * 150.0)
            self.travel_s = GOAL_PROBE_TRAVEL_S
            if self.GOAL_PROBE:
                name = GOAL_PROBE_ZONES[self.outcome_index % len(GOAL_PROBE_ZONES)]
                self.outcome_index += 1
                self.probe_name = name
                self.target_xy = goal_probe_xy(self.line_p0, self.line_p1, name)
                along_t, _h, _w, along, up = goal_line_coords(self.target_xy, self.line_p0, self.line_p1)
                self.start_xy = (
                    self.line_p0[0] + along[0] * along_t - up[0] * 150.0,
                    self.line_p0[1] + along[1] * along_t - up[1] * 150.0,
                )
                self.intended = "correct"
                dist, proj_t, _, _ = compute_projection(self.target_xy, self.line_p0, self.line_p1)
                now_in = in_goal_area(self.target_xy, self.line_p0, self.line_p1, depth)
                rect_in = point_in_suggested_goal(self.target_xy, self.line_p0, self.line_p1)
                print(
                    f"  [SIM] GOAL probe={name} screen={self.screens} target={self.target_xy} "
                    f"dist={dist:.1f} proj_t={proj_t:.3f} current_band={now_in} "
                    f"suggested_rect={rect_in}"
                )
                return
        self.intended = self._next_outcome(self.action)
        print(
            f"  [SIM] {self.action} → {self.screens} intended={self.intended.upper()} "
            f"target={self.target_xy} late_hold={self.late_hold_xy} wrong={self.wrong_xy}"
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

    def _line_target(self, screens):
        for screen in screens:
            line = GOAL_LINES.get(str(screen))
            if not line:
                continue
            p0, p1 = line["p0"], line["p1"]
            mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
            return mid, p0, p1
        return (640.0, 280.0), (600.0, 280.0), (680.0, 280.0)

    def _min_dist_to_screens(self, pt):
        best = float("inf")
        for screen in self.screens:
            line = GOAL_LINES.get(str(screen))
            if not line:
                continue
            d, _ = get_effective_distance(pt, line["p0"], line["p1"])
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
            line = GOAL_LINES.get(str(screen))
            if not line:
                continue
            self.line_p0, self.line_p1 = line["p0"], line["p1"]
            p0, p1 = line["p0"], line["p1"]
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
            line = GOAL_LINES.get(str(screen))
            if not line:
                continue
            d, _ = get_effective_distance(pt, line["p0"], line["p1"])
            if d < best_d:
                best_d = d
                p0, p1 = line["p0"], line["p1"]
                best_mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
        return best_mid

    def _along_line_from(self, pt, span):
        p0, p1 = self.line_p0, self.line_p1
        nearest = None
        nearest_d = float("inf")
        for screen in self.screens:
            line = GOAL_LINES.get(str(screen))
            if not line:
                continue
            d, _ = get_effective_distance(pt, line["p0"], line["p1"])
            if d < nearest_d:
                nearest_d = d
                nearest = line
        if nearest:
            p0, p1 = nearest["p0"], nearest["p1"]
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
            line = GOAL_LINES.get(str(screen))
            if not line:
                continue
            d, _ = get_effective_distance(home, line["p0"], line["p1"])
            if d < nearest_d:
                nearest_d = d
                nearest = line
        if not nearest:
            return home
        saved = (self.line_p0, self.line_p1, self.target_xy)
        self.line_p0, self.line_p1 = nearest["p0"], nearest["p1"]
        p0, p1 = nearest["p0"], nearest["p1"]
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
                bx, by = self._lerp(self.start_xy, target, u)
                px, py = self._lerp(self.PLAYER_HOME, target, u * 0.22)
                return bx, by, px, py
            if is_press:
                if t <= 0.70:
                    px, py = self._lerp(self.PLAYER_HOME, target, t / 0.70)
                else:
                    px, py = self._lerp(target, self.PLAYER_HOME, min(1.0, (t - 0.70) / 0.65))
                bx, by = px + 16, py + 10
                return bx, by, px, py
            if t <= 0.70:
                bx, by = self._lerp(self.BALL_HOME, target, t / 0.70)
            else:
                bx, by = self._lerp(target, self.BALL_HOME, min(1.0, (t - 0.70) / 0.65))
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

    def step(self, frame_w, frame_h):
        sx = frame_w / float(SIM_FRAME_WIDTH)
        sy = frame_h / float(SIM_FRAME_HEIGHT)
        now = time.time()
        t = now - self.start_ts if self.active else (now - self.late_start_ts if self.late_phase else 0.0)
        bx, by, px, py = self._ball_player_for_outcome(t, now)
        bx, by = self._clip(bx, by)
        px, py = self._clip(px, py)
        self.last_ball = (bx, by)
        self.last_player = (px, py)

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
        balls = [{
            "center": [bx_s, by_s],
            "bbox": [bx_s - 8, by_s - 8, bx_s + 8, by_s + 8],
            "confidence": 1.0,
            "simulated": True,
        }]
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
        for ball in balls:
            cx, cy = ball["center"]
            cv2.circle(frame, (cx, cy), 11, (0, 0, 0), -1)
            cv2.circle(frame, (cx, cy), 9, (255, 255, 255), -1)
            cv2.circle(frame, (cx, cy), 9, (0, 140, 255), 2)
        if self.action == "GOAL" and self.line_p0 and self.line_p1:
            self._draw_suggested_goal(frame)
        if self.probe_name and (self.active or self.hold_finish):
            dist, proj_t, _, _ = compute_projection(self.last_ball, self.line_p0, self.line_p1)
            screen = self.screens[0] if self.screens else "8"
            depth = arrival_depth_for(screen, "GOAL")
            now_in = in_goal_area(self.last_ball, self.line_p0, self.line_p1, depth)
            rect_in = point_in_suggested_goal(self.last_ball, self.line_p0, self.line_p1)
            label = (
                f"GOAL PROBE {self.probe_name}  dist={dist:.1f} proj={proj_t:.2f} "
                f"band={'IN' if now_in else 'OUT'} rect={'IN' if rect_in else 'OUT'}"
            )
        elif self.active or self.late_phase:
            label = f"ARENA SIM  {self.intended.upper()}"
        else:
            label = "ARENA SIMULATION"
        cv2.putText(frame, label, (12, frame.shape[0] - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 220, 255), 2)
        return frame

    def _draw_suggested_goal(self, frame):
        h, w = frame.shape[:2]
        sx = w / float(SIM_FRAME_WIDTH)
        sy = h / float(SIM_FRAME_HEIGHT)
        corners = suggested_goal_corners(self.line_p0, self.line_p1)
        pts = [(int(x * sx), int(y * sy)) for x, y in corners]
        for i in range(4):
            cv2.line(frame, pts[i], pts[(i + 1) % 4], COLOR_GOAL_RECT, 2)
        tx, ty = self.target_xy
        cv2.drawMarker(frame, (int(tx * sx), int(ty * sy)), (0, 140, 255), cv2.MARKER_CROSS, 18, 2)

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
    x1, y1, x2, y2 = roi
    h, w = frame.shape[:2]
    x1 = max(0, min(x1, w-1))
    y1 = max(0, min(y1, h-1))
    x2 = max(x1+1, min(x2, w))
    y2 = max(y1+1, min(y2, h))
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return "", None
    try:
        detector = cv2.QRCodeDetector()
        data, bbox, _ = detector.detectAndDecode(crop)
        if bbox is not None and len(bbox) > 0:
            bbox = bbox.astype(int)
            bbox[:,:,0] += x1
            bbox[:,:,1] += y1
        return data.strip() if data else "", bbox
    except Exception:
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
# SIMUST REALTIME CAMERA (with pose-based tracking + polygon drawing)
# ============================================================================

class SimustRealtimeCamera:
    def __init__(self):
        print("=" * 60)
        print("SIMUST REALTIME PLAYER - with YOLOv8‑pose stable tracking")
        print("=" * 60)
        print("Ball detection: BOTH halves (Camera 1 + Camera 8)")
        print("Player tracking: Pose-based hip point (cm-accurate)")
        print("Goal lines drawn based on QR action")
        print("REAL-TIME RESULTS ANALYSIS DISPLAYED")
        print("=" * 60)

        sim = read_simulation_setting()
        self.simulation_enabled = bool(sim)
        self.simulator = ArenaSimulator()
        self.tracker = DetectionTracker(require_models=not self.simulation_enabled)
        viz = read_visualization_setting()
        self.visualization_enabled = bool(viz)

        self.session_lock = threading.Lock()
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

        self.qr_state = {
            "last_raw_data": None,
            "last_detection_time": 0,
            "cooldown": QR_COOLDOWN,
            "detection_count": 0
        }

        self.stats = {"sessions_completed": 0, "action_counts": {}, "results": []}
        self.block_counter = 0
        self.frame_counter = 0

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

        self.screen_monitor = {"left": 1920, "top": 0, "width": 1920, "height": 1080}
        self.qr_roi = (0, 0, 1920, 540)
        self.screen_capture_running = True

        # Player position tracking (hip points) – smoothed, no fallback
        self.all_player_positions = []  # (timestamp, x, y)

        # Delayed analysis support
        self.pending_analysis = None
        self.analysis_timer = None
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
        print(f"Arena simulation: {'ON' if self.simulation_enabled else 'OFF'}")
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

        self.session_data = []
        self.between_session_data = []
        self.qr_blocks = []
        self.block_counter = 0
        self.session_active = False
        self.between_sessions_active = False
        self.frame_counter = 0
        self.stats = {"sessions_completed": 0, "action_counts": {}, "results": []}
        self.tracker.total_balls_detected = 0
        self.tracker.total_players_detected = 0
        self.pending_start = None
        self.pending_end = False
        self.current_qr_block = None
        self.all_player_positions = []
        self.video_index = 1
        self.last_video_index = 1
        self.pending_analysis = None
        self.analysis_timer = None

        self.recording_active = True
        self.video_started = False

        self.start_between_sessions()

    def start_between_sessions(self):
        current_time = get_current_time_ms()
        self.between_sessions_active = True
        self.between_session_data = []
        self.between_session_start_time = current_time
        self.between_session_start_ts = time.time()
        self.between_session_end_time = ""

    def save_between_sessions_block(self):
        if not self.between_session_data:
            return

        end_time = self.between_session_end_time if self.between_session_end_time else get_current_time_ms()

        block = {
            "action": "BETWEEN_SESSIONS",
            "screens": [],
            "start_time": self.between_session_start_time,
            "end_time": end_time,
            "data": self.between_session_data
        }
        self.qr_blocks.append(block)
        self.between_session_data = []
        self.save_recognition_json()
        print(f"  Between sessions: {len(block['data'])} frames ({block['start_time']} -> {block['end_time']})")

    def stop_recording(self):
        if not self.recording_active:
            return

        # ---- Ensure any pending analysis is completed before saving ----
        if self.analysis_timer:
            self.analysis_timer.cancel()
            self._perform_late_analysis()
            self.analysis_timer = None

        if self.session_active:
            self._execute_end(get_current_time_ms(), time.time())

        if self.between_sessions_active and self.between_session_data:
            self.save_between_sessions_block()
            self.between_sessions_active = False

        # --- Compute total player distance from in‑memory hip positions (sampled every 4 frames) ---
        print("\n[DEBUG] Computing total distance from in‑memory blocks (sampled every 4 frames)...")
        total_distance_meters = 0.0

        if len(self.all_player_positions) > 1:
            # Sample every 4th frame (step=4)
            sampled = self.all_player_positions[::4]
            if len(sampled) > 1:
                total_dist_px = 0.0
                for i in range(1, len(sampled)):
                    _, x1, y1 = sampled[i-1]
                    _, x2, y2 = sampled[i]
                    total_dist_px += math.hypot(x2 - x1, y2 - y1)
                total_distance_meters = total_dist_px * PIXEL_TO_METER_SCALE
                print(f"[DEBUG] Total pixel distance (hip, sampled): {total_dist_px:.2f} px → {total_distance_meters:.2f} m")
            else:
                print("[DEBUG] Not enough sampled hip positions (need >1).")
        else:
            print("[DEBUG] Not enough hip positions to compute distance (need >1).")

        # Update the first action's total_distance
        if self.stats['results']:
            self.stats['results'][0]['total_distance'] = total_distance_meters
            results_json_path = os.path.join(self.recording_dir, "results.json")
            if os.path.exists(results_json_path):
                try:
                    with open(results_json_path, 'r', encoding='utf-8') as f:
                        all_results = json.load(f)
                    if all_results:
                        all_results[0]['total_distance'] = total_distance_meters
                        with open(results_json_path, 'w', encoding='utf-8') as f:
                            json.dump(all_results, f, indent=2, ensure_ascii=False)
                        print(f"[DEBUG] Updated results.json with distance {total_distance_meters:.2f} m")
                except Exception as e:
                    print(f"[DEBUG] Error updating results.json: {e}")
            else:
                with open(results_json_path, 'w', encoding='utf-8') as f:
                    json.dump(self.stats['results'], f, indent=2, ensure_ascii=False)
                print(f"[DEBUG] Created results.json with distance {total_distance_meters:.2f} m")

        self.video_saver.stop()
        self.save_recognition_json()
        self.recording_active = False
        self.video_started = False
        self.video_saver = VideoSaver()

    def save_recognition_json(self):
        if not self.recording_dir:
            return False

        json_path = os.path.join(self.recording_dir, "recognition.json")
        sorted_blocks = sorted(self.qr_blocks, key=lambda x: x.get("start_time", ""))
        output_data = []
        for block in sorted_blocks:
            block_data = {
                "id": block.get("id", ""),
                "action": block.get("action", ""),
                "screens": block.get("screens", []),
                "start_time": block.get("start_time", ""),
                "end_time": block.get("end_time", ""),
                "data": block.get("data", [])
            }
            output_data.append(block_data)

        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving JSON: {e}")
            return False

    def cleanup(self):
        if self.recording_active:
            self.stop_recording()
        self.destroy_window()

    def get_goal_lines(self, screens, action, keypoints):
        lines = {}
        # PRESS may use QR keypoints instead of the software line.
        # GOAL always uses the software bottom line so the mouth can be seen.
        if action == "PRESS" and keypoints:
            return lines
        for screen in screens:
            screen_str = str(screen)
            if screen_str in GOAL_LINES:
                lines[screen_str] = GOAL_LINES[screen_str]
        return lines

    def schedule_session_start(self, action, screens, keypoints, block_id, detected_time_str, detected_timestamp):
        offset_start_time_str = add_offset_to_time(detected_time_str, QR_OFFSET_SECONDS)
        with self.session_lock:
            self.pending_start = {
                "action": action.upper(),
                "screens": screens,
                "keypoints": keypoints,
                "block_id": block_id,
                "goal_lines": self.get_goal_lines(screens, action, keypoints),
                "offset_start_time_str": offset_start_time_str,
                "detected_timestamp": detected_timestamp
            }
            self.pending_start_time = detected_timestamp + QR_OFFSET_SECONDS

    def schedule_session_end(self, current_time_str, current_timestamp):
        if self.session_active:
            offset_end_time_str = add_offset_to_time(current_time_str, QR_OFFSET_SECONDS)
            with self.session_lock:
                self.pending_end = True
                self.pending_end_time = current_timestamp + QR_OFFSET_SECONDS
                self.pending_end_time_str = offset_end_time_str

    def check_pending(self, current_timestamp, current_time_str):
        with self.session_lock:
            if self.pending_end and current_timestamp >= self.pending_end_time:
                self._end_session_locked(current_time_str, current_timestamp)
                self.pending_end = False
            if self.pending_start and current_timestamp >= self.pending_start_time:
                self._execute_start(current_timestamp)
                self.pending_start = None

    def _blocks_for_late_analysis(self):
        """Rebuild block list at analysis time so post-QR (late) frames are included."""
        combined = list(self.qr_blocks)
        if self.between_session_data:
            combined.append({
                "id": "BETWEEN",
                "action": "BETWEEN_SESSIONS",
                "screens": [],
                "start_time": self.between_session_start_time,
                "end_time": get_current_time_ms(),
                "data": list(self.between_session_data),
            })
        return combined

    def _perform_late_analysis(self):
        """Delayed analysis: computes result and sends to backend, but does NOT append the block (it's already in qr_blocks)."""
        with self.session_lock:
            if self.pending_analysis is None:
                return

            action_data = self.pending_analysis['action_data']
            action_type = self.pending_analysis['action_type']
            video_index = self.pending_analysis['video_index']
            block_id = self.pending_analysis['block_id']
            screens = self.pending_analysis['screens']

            combined_blocks = self._blocks_for_late_analysis()
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

            # Build result entry
            result_entry = {
                'id': block_id,
                'action': action_type,
                'screens': screens,
                'result': analysis_result['Result'],
                'winning_screen': analysis_result['Winning Screen'],
                'min_dist': analysis_result['Min Distance (px)'],
                'movement': analysis_result['Movement (px)'],
                'direction': analysis_result['Direction'],
                'aep': analysis_result.get('AEP', 'N/A'),
                'session_duration': analysis_result['Session Duration (s)'],
                'video_index': video_index,
                'finishing_time': analysis_result.get('Time of Min (s)', 0.0),
                'total_distance': 0.0,   # will be set in stop_recording
                'ae': analysis_result.get('AE', 0.0)
            }

            # Store in stats and send to backend
            self.stats['results'].append(result_entry)
            try:
                payload = {
                    'session_folder': self.recording_dir,
                    'action_result': result_entry
                }
                requests.post('http://127.0.0.1:8000/save-results-to-json', json=payload, timeout=1)
            except Exception as e:
                print(f"Failed to save result to results.json: {e}")

            # Clear pending
            self.pending_analysis = None
            self.analysis_timer = None

    def _end_session_locked(self, current_time_str, current_timestamp):
        """End the active session. Must be called with self.session_lock held."""
        if not self.session_active:
            return
        self.stats["sessions_completed"] += 1
        action_key = self.current_action
        self.stats["action_counts"][action_key] = self.stats["action_counts"].get(action_key, 0) + 1
        self.session_active = False
        if self.simulation_enabled:
            self.simulator.end_action()

        if self.current_qr_block:
            if self.session_data:
                self.current_qr_block["data"] = self.session_data

            offset_end_time_str = add_offset_to_time(current_time_str, QR_OFFSET_SECONDS)
            self.current_qr_block["end_time"] = offset_end_time_str

            # ---- Append block immediately to qr_blocks ----
            block_copy = self.current_qr_block.copy()
            self.qr_blocks.append(block_copy)

            # Store pending analysis data (using the block copy, but we'll keep the original for analysis)
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

            # Build combined_blocks for analysis (including the new block and between-session data)
            combined_blocks = self.qr_blocks.copy()   # includes the new block
            if self.between_session_data:
                between_block = {
                    "id": "BETWEEN",
                    "action": "BETWEEN_SESSIONS",
                    "screens": [],
                    "start_time": self.between_session_start_time,
                    "end_time": current_time_str,
                    "data": self.between_session_data
                }
                combined_blocks.append(between_block)
                print(f"  Including between‑session data ({len(self.between_session_data)} frames) for analysis.")

            self.pending_analysis = {
                'action_data': self.current_qr_block,    # original block (same data)
                'screens': self.current_screens,
                'action_type': self.current_action,
                'block_id': self.current_block_id,
                'video_index': video_index,
                'combined_blocks': combined_blocks,
            }

            # Schedule delayed analysis (timer) – this will compute result and send to backend
            if self.analysis_timer:
                self.analysis_timer.cancel()
            self.analysis_started_at = time.time()
            self.analysis_timer = threading.Timer(1.5, self._perform_late_analysis)
            self.analysis_timer.daemon = True
            self.analysis_timer.start()

            # ---- Clear current_qr_block ----
            self.current_qr_block = None

            # We no longer print result here because it will be computed later.
            # However, we keep the end print to show the session has ended.
            duration = current_timestamp - self.session_start_timestamp
            session_fps_avg = self.session_fps_sum / self.session_frame_count if self.session_frame_count > 0 else 0

            print(f"{'-'*50}")
            print(f"SESSION END - Frames: {self.session_frame_count} | Duration: {duration:.2f}s | Avg FPS: {session_fps_avg:.1f}")
            print(f"End: {offset_end_time_str}")
            print(f"Analysis scheduled (will include between‑session frames).")
            print(f"{'='*50}\n")

            self.save_recognition_json()   # saves immediately, includes the new block

        self.active_goal_lines = {}
        self.current_action = None
        self.current_screens = []
        self.current_keypoints = []
        self.current_block_id = None
        self.session_data = []
        self.session_fps_sum = 0
        self.session_frame_count = 0

        self.between_sessions_active = True
        self.between_session_data = []
        self.between_session_start_time = offset_end_time_str
        self.between_session_start_ts = current_timestamp
        self.between_session_end_time = ""

    def _execute_end(self, current_time_str, current_timestamp):
        """Public method: acquires lock and calls _end_session_locked."""
        with self.session_lock:
            self._end_session_locked(current_time_str, current_timestamp)

    def _execute_start(self, current_timestamp):
        p = self.pending_start

        if self.between_sessions_active:
            self.between_session_end_time = p["offset_start_time_str"]
            self.save_between_sessions_block()
            self.between_sessions_active = False

        self.current_action = p["action"]
        self.current_screens = p["screens"]
        self.current_keypoints = p["keypoints"]
        self.current_block_id = p["block_id"]
        self.active_goal_lines = p["goal_lines"]
        self.session_active = True
        self.session_start_timestamp = current_timestamp
        self.session_frame_count = 0
        self.session_fps_sum = 0
        self.session_data = []

        self.current_qr_block = {
            "id": self.current_block_id,
            "action": self.current_action,
            "screens": self.current_screens,
            "keypoints": self.current_keypoints,
            "start_time": p["offset_start_time_str"],
            "end_time": "",
            "data": []
        }

        if self.simulation_enabled:
            self.simulator.start_action(self.current_action, self.current_screens)

        print(f"\n{'='*50}")
        print(f"SESSION {self.current_block_id} - {self.current_action}")
        print(f"Screens: {self.current_screens}")
        print(f"Start: {p['offset_start_time_str']}")
        print(f"{'-'*50}")

    # ---- Drawing and UI methods ----
    def draw_goal_lines(self, frame):
        if not self.session_active or not self.active_goal_lines:
            return frame

        h, w = frame.shape[:2]
        sx = w / float(SIM_FRAME_WIDTH)
        sy = h / float(SIM_FRAME_HEIGHT)
        for screen_name, line_data in self.active_goal_lines.items():
            x1, y1 = line_data['p0']
            x2, y2 = line_data['p1']
            p0 = (int(x1 * sx), int(y1 * sy))
            p1 = (int(x2 * sx), int(y2 * sy))
            cv2.line(frame, p0, p1, COLOR_GOAL_LINE, 3)
            cv2.circle(frame, p0, 5, (0, 0, 255), -1)
            cv2.circle(frame, p1, 5, (0, 0, 255), -1)
            cv2.putText(frame, f"GOAL {screen_name}", ((p0[0] + p1[0]) // 2 - 40, p0[1] - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
            if str(screen_name) in ("1", "8"):
                corners = suggested_goal_corners(line_data["p0"], line_data["p1"])
                pts = [(int(x * sx), int(y * sy)) for x, y in corners]
                for i in range(4):
                    cv2.line(frame, pts[i], pts[(i + 1) % 4], COLOR_GOAL_RECT, 2)
        return frame

    def draw_results_overlay(self, frame):
        h, w = frame.shape[:2]
        panel_x = w - 350
        panel_y = 10
        panel_w = 340
        panel_h = 230

        overlay = frame.copy()
        cv2.rectangle(overlay, (panel_x, panel_y), (panel_x + panel_w, panel_y + panel_h), (0, 0, 0), -1)
        frame = cv2.addWeighted(overlay, 0.7, frame, 0.3, 0)

        cv2.putText(frame, "RESULTS", (panel_x + 10, panel_y + 25),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.line(frame, (panel_x + 10, panel_y + 30), (panel_x + panel_w - 10, panel_y + 30), (255, 255, 255), 1)

        y_offset = 50
        results = self.stats['results'][-5:] if self.stats['results'] else []

        for i, result in enumerate(results):
            action_id = result.get('id', '')
            action_type = result.get('action', '')
            action_result = result.get('result', '')
            winning = result.get('winning_screen', '')
            movement = result.get('movement', 0)
            direction = result.get('direction', '')
            aep = result.get('aep', 'N/A')
            ae = result.get('ae', 0.0)

            if action_result == 'Correct':
                color = COLOR_CORRECT
            elif action_result == 'Late':
                color = COLOR_LATE
            else:
                color = COLOR_WRONG

            text = f"{action_id} {action_type}: {action_result}"
            if winning and winning != 'N/A':
                text += f" → {winning}"
            if movement > 0:
                text += f" [{movement}px {direction}]"
            text += f" AEP:{aep} AE:{ae:.1f}"

            cv2.putText(frame, text, (panel_x + 10, panel_y + y_offset + i * 25),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

        return frame

    def draw_all_annotations(self, frame, balls, players, session_active):
        h, w = frame.shape[:2]
        mid_x = w // 2

        frame = self.draw_goal_lines(frame)

        if session_active:
            cv2.putText(frame, "SESSION ACTIVE", (w//2 - 80, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        else:
            cv2.putText(frame, "BETWEEN SESSIONS", (w//2 - 90, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 255, 100), 1)

        for i, ball in enumerate(balls):
            cx, cy = ball['center']
            cv2.circle(frame, (cx, cy), 8, COLOR_BALL, -1)
            cv2.putText(frame, f"B{i+1}", (cx-15, cy-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_BALL, 2)

        for player_idx, player in enumerate(players):
            cv2.rectangle(frame, (player['bbox'][0], player['bbox'][1]),
                         (player['bbox'][2], player['bbox'][3]), COLOR_PLAYER, 2)
            cv2.putText(frame, f"P{player_idx+1}", (player['bbox'][0], player['bbox'][1] - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_PLAYER, 1)

        fps = self.tracker.current_fps
        fps_color = (0, 255, 0) if fps >= 20 else ((0, 255, 255) if fps >= 12 else (0, 0, 255))
        cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, fps_color, 2)

        if session_active:
            overlay = frame.copy()
            cv2.rectangle(overlay, (10, 50), (350, 80), (0, 0, 0), -1)
            frame = cv2.addWeighted(overlay, 0.7, frame, 0.3, 0)
            cv2.putText(frame, f"{self.current_block_id} - {self.current_action}", (15, 68),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        cv2.putText(frame, "CAM1", (w//4 - 50, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(frame, "CAM8", (w//4*3 - 50, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        cv2.line(frame, (mid_x, 0), (mid_x, h), (255, 255, 255), 2)

        frame = self.draw_results_overlay(frame)

        return frame

    # ---- Frame processing (with hip-point tracking) ----
    def _detections_for_frame(self, frame, current_timestamp):
        if self.simulation_enabled:
            h, w = frame.shape[:2]
            balls, players, hip = self.simulator.step(w, h)
            frame = self.simulator.draw_on_frame(frame, balls, players)
            return frame, balls, players, hip[0], hip[1]
        balls, players = self.tracker.detect_objects(frame)
        sx, sy = self.tracker.get_player_tracking_point(
            frame, players, current_timestamp, self.session_start_timestamp
        )
        return frame, balls, players, sx, sy

    def process_frame_for_session(self, frame, current_timestamp):
        self.tracker.increment_frame_count()

        frame, balls, players, sx, sy = self._detections_for_frame(frame, current_timestamp)

        # Store in all_player_positions ONLY if hip is valid (used for EOP)
        if sx is not None and sy is not None:
            rel_time = current_timestamp - self.session_start_timestamp
            self.all_player_positions.append((rel_time, sx, sy))

        # Build frame_data – 'hp' is None if pose fails
        frame_data = {
            't': round(current_timestamp - self.session_start_timestamp, 3),
            'b': [[c[0], c[1]] for c in [ball['center'] for ball in balls]],
            'p': [[c[0], c[1]] for c in [player['center'] for player in players]],
            'hp': [sx, sy] if (sx is not None and sy is not None) else None
        }
        self.session_data.append(frame_data)
        self.session_frame_count += 1
        self.frame_counter += 1

        if self.current_qr_block is not None:
            self.current_qr_block["data"].append(frame_data)

        fps = self.tracker.update_fps()
        self.session_fps_sum += fps

        if self.session_frame_count % 10 == 0:
            print(f"  Frame {self.session_frame_count:3d} | B:{len(balls)} P:{len(players)} | FPS: {fps:.1f}")

        # ========= OVERLAY – ALWAYS DRAWN (regardless of visualization_enabled) =========
        if sx is not None and sy is not None:
            # Valid hip – cyan
            cv2.circle(frame, (int(sx), int(sy)), 6, COLOR_HIP, -1)
            cv2.putText(frame, "HIP", (int(sx)-15, int(sy)-10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_HIP, 1)
        elif players:
            # Fallback overlay – red at bottom‑centre of largest player
            main_player = max(players, key=lambda p: (p['bbox'][2]-p['bbox'][0]) * (p['bbox'][3]-p['bbox'][1]))
            x1, y1, x2, y2 = main_player['bbox']
            fallback_x = (x1 + x2) // 2
            fallback_y = y2  # bottom edge
            cv2.circle(frame, (fallback_x, fallback_y), 6, (0, 0, 255), -1)
            cv2.putText(frame, "FALLBACK", (fallback_x-30, fallback_y-10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
        # (no player at all – nothing to draw)

        frame = self.draw_all_annotations(frame, balls, players, True)
        return frame

    def process_frame_between_sessions(self, frame, current_timestamp):
        self.tracker.increment_frame_count()

        frame, balls, players, sx, sy = self._detections_for_frame(frame, current_timestamp)

        # Store in all_player_positions ONLY if hip is valid (used for EOP)
        if sx is not None and sy is not None:
            # Use the last known session start as reference for timestamps
            rel_time = current_timestamp - self.session_start_timestamp if self.session_start_timestamp != 0 else 0.0
            self.all_player_positions.append((rel_time, sx, sy))

        # ===== FIX: assign a real time offset for between‑session frames =====
        # Time is relative to the between-session block start so late search
        # (LATE_SEARCH_DURATION) can still accept finishes after the QR ends.
        between_origin = getattr(self, "between_session_start_ts", 0.0) or 0.0
        rel_time = current_timestamp - between_origin if between_origin else 0.0
        frame_data = {
            't': round(rel_time, 3),
            'b': [[c[0], c[1]] for c in [ball['center'] for ball in balls]],
            'p': [[c[0], c[1]] for c in [player['center'] for player in players]],
            'hp': [sx, sy] if (sx is not None and sy is not None) else None
        }
        self.between_session_data.append(frame_data)
        self.frame_counter += 1

        self.tracker.update_fps()

        # ========= OVERLAY – ALWAYS DRAWN (regardless of visualization_enabled) =========
        if sx is not None and sy is not None:
            # Valid hip – cyan
            cv2.circle(frame, (int(sx), int(sy)), 6, COLOR_HIP, -1)
            cv2.putText(frame, "HIP", (int(sx)-15, int(sy)-10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_HIP, 1)
        elif players:
            # Fallback overlay – red at bottom‑centre of largest player
            main_player = max(players, key=lambda p: (p['bbox'][2]-p['bbox'][0]) * (p['bbox'][3]-p['bbox'][1]))
            x1, y1, x2, y2 = main_player['bbox']
            fallback_x = (x1 + x2) // 2
            fallback_y = y2  # bottom edge
            cv2.circle(frame, (fallback_x, fallback_y), 6, (0, 0, 255), -1)
            cv2.putText(frame, "FALLBACK", (fallback_x-30, fallback_y-10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)

        frame = self.draw_all_annotations(frame, balls, players, False)
        return frame

    def process_qr_detection(self, frame, current_time_str, current_timestamp):
        raw_data, bbox = detect_qr_in_roi(frame, self.qr_roi)
        action, screens, keypoints = parse_qr_data(raw_data) if raw_data else ("", [], [])

        is_new_qr = (raw_data and raw_data != self.qr_state["last_raw_data"] and action and screens and
                    (current_timestamp - self.qr_state["last_detection_time"] >= self.qr_state["cooldown"]))

        if is_new_qr:
            # --- FIX: force end of any active session or cancel pending starts ---
            with self.session_lock:
                # If there is an active session, end it now
                if self.session_active:
                    self._end_session_locked(current_time_str, current_timestamp)
                # Cancel any pending start (overwrite)
                self.pending_start = None
                # Cancel any pending end (since we are starting a new session)
                self.pending_end = False
            # --- END FIX ---

            # Now schedule the new session
            if self.current_qr_block:
                self.qr_blocks.append(self.current_qr_block.copy())
                self.current_qr_block = None
            self.block_counter += 1
            block_id = f"S{self.block_counter}"

            self.qr_state["last_raw_data"] = raw_data
            self.qr_state["last_detection_time"] = current_timestamp
            self.qr_state["detection_count"] += 1
            self.schedule_session_start(action, screens, keypoints, block_id, current_time_str, current_timestamp)

            if bbox is not None and len(bbox) > 0 and self.visualization_enabled:
                pts = bbox[0].astype(int)
                cv2.polylines(frame, [pts], True, COLOR_QR, 2)

        elif not raw_data and self.current_qr_block and not self.pending_end:
            # QR disappeared – schedule session end AND reset last_raw_data so that
            # a reappearance with identical content will be detected as new.
            self.qr_state["last_raw_data"] = None  # <-- FIX: allow identical QR to be detected again
            self.schedule_session_end(current_time_str, current_timestamp)
        elif self.session_active and (current_timestamp - self.session_start_timestamp) > MAX_SESSION_DURATION:
            self._execute_end(current_time_str, current_timestamp)
            self.pending_end = False

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
            if self.analysis_timer:
                self.analysis_timer.cancel()
                started = self.analysis_started_at or self._pause_started_at
                self._paused_analysis_remaining = max(0.05, 1.5 - (self._pause_started_at - started))
                self.analysis_timer = None
            print("PAUSED — detection, analysis, and saving frozen")

    def _unfreeze_after_pause(self):
        with self._pause_lock:
            if not self.operator_paused:
                return
            dt = time.time() - (self._pause_started_at or time.time())
            if self.pending_start:
                self.pending_start_time += dt
                offset = self.pending_start.get("offset_start_time_str")
                if offset:
                    self.pending_start["offset_start_time_str"] = add_offset_to_time(offset, dt)
            if self.pending_end:
                self.pending_end_time += dt
                end_str = getattr(self, "pending_end_time_str", "")
                if end_str:
                    self.pending_end_time_str = add_offset_to_time(end_str, dt)
            if self.session_active:
                self.session_start_timestamp += dt
            current_block = getattr(self, "current_qr_block", None)
            if current_block and current_block.get("start_time"):
                current_block["start_time"] = add_offset_to_time(current_block["start_time"], dt)
            if self.between_sessions_active and self.between_session_start_ts:
                self.between_session_start_ts += dt
            between_start = getattr(self, "between_session_start_time", None)
            if between_start:
                self.between_session_start_time = add_offset_to_time(between_start, dt)
            last_det = (getattr(self, "qr_state", None) or {}).get("last_detection_time")
            if last_det:
                self.qr_state["last_detection_time"] = last_det + dt
            simulator = getattr(self, "simulator", None)
            if simulator is not None:
                if getattr(simulator, "start_ts", 0):
                    simulator.start_ts += dt
                if getattr(simulator, "late_start_ts", 0):
                    simulator.late_start_ts += dt
            if self._paused_analysis_remaining is not None:
                self.analysis_started_at = time.time()
                self.analysis_timer = threading.Timer(self._paused_analysis_remaining, self._perform_late_analysis)
                self.analysis_timer.daemon = True
                self.analysis_timer.start()
                self._paused_analysis_remaining = None
            self.operator_paused = False
            self._pause_started_at = 0
            print("RESUMED — continuing from the pause point")

    def _apply_simulation_setting(self):
        new_sim = read_simulation_setting()
        if new_sim is None or new_sim == self.simulation_enabled:
            return
        self.simulation_enabled = new_sim
        print(f"Arena simulation: {'ON' if self.simulation_enabled else 'OFF'}")
        if self.simulation_enabled and self.session_active:
            self.simulator.start_action(self.current_action, self.current_screens)
        if not self.simulation_enabled:
            self.simulator.end_action()

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
        print("Detection ALWAYS active (Balls on both cameras, Players on Camera 1)")
        print("Arena simulation: artificial ball/player injected when enabled")
        print("Player tracking: Pose-based hip point (cm-accurate) – NO fallback")
        print("Video ALWAYS recording at 25 FPS")
        print("Real-time results displayed on screen and saved to file")
        print("Saving each result with video_index for per‑video results")
        print("Economy of Play: total video distance computed using every 8th frame")
        print("Distance converted to meters using calibration: 0.01492 m/pixel")
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
                        left = self.simulator.blank_half()
                        right = self.simulator.blank_half()
                    else:
                        time.sleep(0.01)
                        continue

                stitched = self.stitch_frames(left, right)
                if stitched is None:
                    continue

                # ----- DRAW POLYGON ON THE STITCHED FRAME (for saved video) -----
                if POLYGON_POINTS:
                    pts = np.array(POLYGON_POINTS, dtype=np.int32)
                    cv2.polylines(stitched, [pts], True, COLOR_POLYGON, 2)

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

                if self.session_active:
                    stitched = self.process_frame_for_session(stitched, current_timestamp)
                else:
                    stitched = self.process_frame_between_sessions(stitched, current_timestamp)

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