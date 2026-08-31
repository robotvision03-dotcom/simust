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

STITCHED_WIDTH = 3840
STITCHED_HEIGHT = 1080
HALF_WIDTH = STITCHED_WIDTH // 2

VIZ_FILE = os.path.join(SIMUST_PLAYER_DIRECTORY, "visualization.txt")
DISPLAY_WIDTH = 1280
DISPLAY_HEIGHT = 720

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
    def __init__(self):
        # Existing detection engine
        if not torch.cuda.is_available():
            print("ERROR: CUDA not available. .engine files require GPU.")
            sys.exit(1)
        if not os.path.exists(DETECTION_ENGINE_PATH):
            print(f"ERROR: {DETECTION_ENGINE_PATH} not found.")
            sys.exit(1)
        try:
            self.detection_model = YOLO(DETECTION_ENGINE_PATH)
            print(f"Detection model loaded: {DETECTION_ENGINE_PATH}")
        except Exception as e:
            print(f"Failed to load detection engine: {e}")
            sys.exit(1)

        self.detection_conf = DETECTION_CONF
        self.max_players = MAX_PLAYERS
        self.half_width = HALF_WIDTH

        # Pose detector
        self.pose_detector = PoseDetector(POSE_ENGINE_PATH)

        # 1‑Euro filters for hip point
        self.filter_x = OneEuroFilter(min_cutoff=1.0, beta=0.5)
        self.filter_y = OneEuroFilter(min_cutoff=1.0, beta=0.5)

        self.total_balls_detected = 0
        self.total_players_detected = 0
        self.frame_process_count = 0
        self.last_fps_time = time.time()
        self.current_fps = 0

        # Polygon for player ROI
        self.polygon = POLYGON_POINTS

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
                if not (0 <= proj_t <= 1):
                    continue
                threshold = get_goal_threshold(screen)
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
    """
    Returns True if the ball ever comes within 2*threshold of the goal line
    after the minimum distance time (min_time).
    """
    p0, p1 = get_screen_info(screen, goal_lines)
    if p0 is None:
        return True

    check_dist = entry_threshold if entry_threshold is not None else threshold * 2

    count = 0
    for t, x, y in positions:
        if t > min_time and t <= session_duration:
            d, _, _, _ = compute_projection((x, y), p0, p1)
            if d <= check_dist:
                return True
            count += 1
            if count >= search_frames:
                break
    return False

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

    # ---- GOAL actions ----
    if action_type == 'GOAL':
        # Use filtered positions to remove static noise, but don't require movement
        filtered_positions = filter_static_ball_positions(positions)
        if not filtered_positions:
            filtered_positions = positions

        # Compute best distance and projection from this action's data
        best_screen, best_eff_dist, best_min_time, best_proj_t = find_min_distance_to_screens(
            filtered_positions, screens, goal_lines, require_movement=False
        )

        result = 'Wrong'
        winning_screen = 'N/A'
        display_time = '-'
        display_duration = '-'
        min_dist_display = best_eff_dist if best_eff_dist != float('inf') else None

        valid_projection = False
        if best_proj_t is not None and 0 <= best_proj_t <= 1:
            valid_projection = True

        if best_screen is not None and valid_projection:
            threshold = get_threshold_for_screen(best_screen, 'GOAL')
            if best_eff_dist <= threshold:
                result = 'Correct'
                winning_screen = best_screen
                display_time = f"{best_min_time:.3f}"
                display_duration = f"{filtered_positions[-1][0]:.3f}"
            else:
                if action_end_time is not None:
                    found_late, late_screen, late_time, late_dist, late_proj = search_goal_late(
                        action_index, all_data, screens, goal_lines, key, action_end_time
                    )
                    if found_late:
                        result = 'Late'
                        winning_screen = late_screen
                        display_time = f"{late_time:.3f}"
                        display_duration = f"{filtered_positions[-1][0]:.3f}"
                        min_dist_display = late_dist
        else:
            # Projection invalid -> Wrong, no late search
            result = 'Wrong'
            winning_screen = 'N/A'
            display_time = '-'
            display_duration = '-'
            min_dist_display = None

        if result == 'Wrong':
            display_time = '-'
            display_duration = '-'
            winning_screen = 'N/A'

        movement, direction = analyze_movement(filtered_positions)
        aep = get_aep_orientation(screens, winning_screen)

        # --- Compute AE ---
        finishing_time_val = float(display_time) if display_time != '-' else 0.0
        ae = compute_action_efficiency('GOAL', result, finishing_time_val, movement)

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

    # ---- PRESS and TARGET actions ----
    if action_type in ['PRESS', 'TARGET']:
        filtered_positions = positions if action_type == 'PRESS' else filter_static_ball_positions(positions)
        if not filtered_positions:
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
        if not is_ball_moving(filtered_positions):
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
        unique_positions = get_unique_trajectory(filtered_positions)
        session_duration = unique_positions[-1][0] if unique_positions else 0
        movement, direction = analyze_movement(filtered_positions)

        best_screen, best_eff_dist, best_min_time, best_proj_t = find_min_distance_to_screens(
            filtered_positions, screens, goal_lines, require_movement=False
        )

        if best_screen is not None:
            action_threshold = get_threshold_for_screen(best_screen, action_type)
        else:
            action_threshold = 50 if action_type == 'PRESS' else CORRECT_THRESHOLD

        result = 'Wrong'
        winning_screen = 'N/A'
        display_time = '-'
        display_duration = '-'
        min_dist_display = best_eff_dist if best_eff_dist != float('inf') else None

        if best_screen is not None:
            if best_eff_dist <= action_threshold:
                result = 'Correct'
                winning_screen = best_screen
                display_time = f"{best_min_time:.3f}"
                display_duration = f"{session_duration:.3f}"
            else:
                # --- Use fallback action_end_time if needed ---
                if action_end_time is not None:
                    found_late, late_screen, late_time, late_dist, _ = search_late_across_blocks(
                        action_index, all_data, screens, goal_lines, key, action_end_time, action_type
                    )
                    if found_late:
                        result = 'Late'
                        winning_screen = late_screen
                        display_time = f"{late_time:.3f}"
                        display_duration = f"{session_duration:.3f}"
                        min_dist_display = late_dist

        if result == 'Wrong':
            display_time = '-'
            display_duration = '-'
            winning_screen = 'N/A'

        aep = get_aep_orientation(screens, winning_screen)

        # --- Compute AE ---
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

    # ---- PASS actions (UPDATED: uses FINISH_DIST and simplified check_ball_return) ----
    if action_type == 'PASS':
        filtered_positions = filter_static_ball_positions(positions)
        if not filtered_positions:
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

        session_duration = filtered_positions[-1][0] if filtered_positions else 0

        best_screen, best_eff_dist, best_min_time, best_proj_t = find_min_distance_to_screens(
            filtered_positions, screens, goal_lines, require_movement=False
        )

        result = 'Wrong'
        winning_screen = 'N/A'
        display_time = '-'
        display_duration = '-'
        min_dist_display = best_eff_dist if best_eff_dist != float('inf') else None

        def get_threshold(screen: str) -> float:
            return get_threshold_for_screen(screen, 'PASS')

        if best_screen is not None:
            threshold = get_threshold(best_screen)
            # Use FINISH_DIST as the outer acceptance radius
            if best_eff_dist <= FINISH_DIST:
                # Check if the ball ever gets within threshold*2 after min_time
                is_returned = check_ball_return(
                    positions, best_screen, goal_lines,
                    best_min_time, threshold, session_duration,
                    entry_threshold=threshold * 3.4  # use 2x threshold for presence
                )
                if not is_returned and action_end_time is not None and session_start_time is not None:
                    extra_positions = get_positions_from_blocks_after(
                        action_index, all_data, key, action_end_time, session_start_time, time_window=1.0
                    )
                    if extra_positions:
                        all_positions = positions + extra_positions
                        all_positions.sort(key=lambda p: p[0])
                        extended_duration = all_positions[-1][0] if all_positions else session_duration
                        is_returned = check_ball_return(
                            all_positions, best_screen, goal_lines,
                            best_min_time, threshold, extended_duration,
                            entry_threshold=threshold * 2
                        )
                if is_returned:
                    result = 'Correct'
                    winning_screen = best_screen
                    display_time = f"{best_min_time:.3f}"
                    display_duration = f"{session_duration:.3f}"
                else:
                    # Within FINISH_DIST but not within threshold*2 → Miss (almost)
                    result = 'Miss'
                    winning_screen = best_screen  # Keep screen for AEP
                    display_time = '-'
                    display_duration = '-'
                    min_dist_display = None
            else:
                # Too far → Wrong (or try late)
                result = 'Wrong'
                winning_screen = 'N/A'
                display_time = '-'
                display_duration = '-'
                min_dist_display = None
                # --- Use fallback action_end_time if needed ---
                if action_end_time is not None:
                    found_late, late_screen, late_time, late_dist, _ = search_late_across_blocks(
                        action_index, all_data, screens, goal_lines, key, action_end_time, action_type
                    )
                    if found_late:
                        result = 'Late'
                        winning_screen = late_screen
                        display_time = f"{late_time:.3f}"
                        display_duration = f"{session_duration:.3f}"
                        min_dist_display = late_dist
        else:
            # No best screen – try late
            if action_end_time is not None:
                found_late, late_screen, late_time, late_dist, _ = search_late_across_blocks(
                    action_index, all_data, screens, goal_lines, key, action_end_time, action_type
                )
                if found_late:
                    result = 'Late'
                    winning_screen = late_screen
                    display_time = f"{late_time:.3f}"
                    display_duration = f"{session_duration:.3f}"
                    min_dist_display = late_dist

        if result == 'Wrong':
            display_time = '-'
            display_duration = '-'
            winning_screen = 'N/A'

        movement, direction = analyze_movement(filtered_positions)
        aep = get_aep_orientation(screens, winning_screen)

        # --- Compute AE ---
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

def read_visualization_setting():
    try:
        if os.path.exists(VIZ_FILE):
            with open(VIZ_FILE, 'r') as f:
                content = f.read().strip().lower()
                return content == 'true' or content == '1' or content == 'yes'
    except:
        pass
    return False

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

        self.tracker = DetectionTracker()
        self.visualization_enabled = read_visualization_setting()

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

        ensure_directory(DEFAULT_RECORDINGS_DIR)

        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        atexit.register(self.cleanup)

        print(f"Detection: {DETECTION_ENGINE_PATH} (TensorRT)")
        print(f"Pose model: {POSE_ENGINE_PATH if os.path.exists(POSE_ENGINE_PATH) else 'Not found – pose will be skipped'}")
        print(f"Detection Confidence: {DETECTION_CONF}")
        print(f"Recordings: {DEFAULT_RECORDINGS_DIR}")
        print(f"Visualization: {'ON' if self.visualization_enabled else 'OFF'}")
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
        if action in ["PRESS", "GOAL"] and keypoints:
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

    def _perform_late_analysis(self):
        """Delayed analysis: computes result and sends to backend, but does NOT append the block (it's already in qr_blocks)."""
        with self.session_lock:
            if self.pending_analysis is None:
                return

            action_data = self.pending_analysis['action_data']
            combined_blocks = self.pending_analysis['combined_blocks']
            action_type = self.pending_analysis['action_type']
            video_index = self.pending_analysis['video_index']
            block_id = self.pending_analysis['block_id']
            screens = self.pending_analysis['screens']

            # The block is already in qr_blocks, we do NOT append it again.

            # Perform analysis
            analysis_result = analyze_action_with_context(
                action_data,
                GOAL_LINES,
                action_type,
                combined_blocks,
                len(self.qr_blocks) - 1   # index of the block in qr_blocks (it's the last one)
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

        print(f"\n{'='*50}")
        print(f"SESSION {self.current_block_id} - {self.current_action}")
        print(f"Screens: {self.current_screens}")
        print(f"Start: {p['offset_start_time_str']}")
        print(f"{'-'*50}")

    # ---- Drawing and UI methods ----
    def draw_goal_lines(self, frame):
        if not self.session_active or not self.active_goal_lines:
            return frame

        for screen_name, line_data in self.active_goal_lines.items():
            x1, y1 = line_data['p0']
            x2, y2 = line_data['p1']
            cv2.line(frame, (x1, y1), (x2, y2), COLOR_GOAL_LINE, 3)
            cv2.circle(frame, (x1, y1), 5, (0, 0, 255), -1)
            cv2.circle(frame, (x2, y2), 5, (0, 0, 255), -1)
            cv2.putText(frame, f"GOAL {screen_name}", ((x1 + x2)//2 - 40, y1 - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
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
    def process_frame_for_session(self, frame, current_timestamp):
        self.tracker.increment_frame_count()

        balls, players = self.tracker.detect_objects(frame)

        # Get hip point (no fallback – may be None)
        sx, sy = self.tracker.get_player_tracking_point(
            frame, players, current_timestamp, self.session_start_timestamp
        )

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

        balls, players = self.tracker.detect_objects(frame)

        # Get hip point (no fallback – may be None)
        sx, sy = self.tracker.get_player_tracking_point(
            frame, players, current_timestamp,
            self.session_start_timestamp if self.session_active else 0.0
        )

        # Store in all_player_positions ONLY if hip is valid (used for EOP)
        if sx is not None and sy is not None:
            # Use the last known session start as reference for timestamps
            rel_time = current_timestamp - self.session_start_timestamp if self.session_start_timestamp != 0 else 0.0
            self.all_player_positions.append((rel_time, sx, sy))

        # ===== FIX: assign a real time offset for between‑session frames =====
        # Use the session start timestamp as reference; if no session, use 0.
        rel_time = current_timestamp - self.session_start_timestamp if self.session_start_timestamp != 0 else 0.0
        frame_data = {
            't': round(rel_time, 3),  # now correct relative time
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
            if self.window_created:
                cv2.destroyWindow(self.window_name)
                self.window_created = False
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

    def destroy_window(self):
        if self.window_created:
            cv2.destroyWindow(self.window_name)
            self.window_created = False

    # ---- Main loop ----
    def run(self):
        screen_thread = threading.Thread(target=self.capture_screen, daemon=True)
        screen_thread.start()

        for name, config in self.cameras.items():
            t = threading.Thread(target=self.capture_stream, args=(name, config["address"]), daemon=True)
            t.start()

        time.sleep(3)

        self.start_new_recording()
        self.visualization_enabled = read_visualization_setting()

        last_viz_check = time.time()
        recording_started_for_video = False

        print("\n" + "=" * 60)
        print("READY - Press Ctrl+C to stop")
        print("=" * 60)
        print("Detection ALWAYS active (Balls on both cameras, Players on Camera 1)")
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
                self.check_pending(current_timestamp, current_time_str)

                if current_timestamp - last_viz_check >= 0.5:
                    new_viz = read_visualization_setting()
                    if new_viz != self.visualization_enabled:
                        self.visualization_enabled = new_viz
                        if not self.visualization_enabled and self.window_created:
                            cv2.destroyWindow(self.window_name)
                            self.window_created = False
                    last_viz_check = current_timestamp

                left, right = self.get_frames()

                if left is None or right is None:
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

                if self.visualization_enabled:
                    self.show_frame(stitched)
                elif self.window_created:
                    cv2.destroyWindow(self.window_name)
                    self.window_created = False

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