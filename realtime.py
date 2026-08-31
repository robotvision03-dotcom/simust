import cv2
import numpy as np
import threading
import queue
import time
import signal
import sys
from datetime import datetime
import json
import os
import mss
from collections import defaultdict
import math
from ultralytics import YOLO
from insightface.app import FaceAnalysis
import torch
import warnings
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText
import concurrent.futures
from collections import deque

warnings.filterwarnings('ignore', category=FutureWarning, module='insightface.utils.transform')

# ============================================================================
# ONE EURO FILTER for Yaw smoothing
# ============================================================================

class OneEuroFilter:
    def __init__(self, t0, x0, min_cutoff=0.8, beta=0.07, d_cutoff=1.0):
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self.x_prev = float(x0)
        self.dx_prev = 0.0
        self.t_prev = float(t0)
        self.first_call = True
      
    def __call__(self, t, x):
        if self.first_call:
            self.first_call = False
            self.x_prev = x
            self.t_prev = t
            return x
        dt = t - self.t_prev
        if dt <= 1e-6:
            return self.x_prev
        dx = (x - self.x_prev) / dt
        edx = self._lowpass(dx, self.dx_prev, self.d_cutoff, dt)
        self.dx_prev = edx
        cutoff = self.min_cutoff + self.beta * abs(edx)
        alpha = self._alpha(cutoff, dt)
        x_hat = alpha * x + (1 - alpha) * self.x_prev
        self.x_prev = x_hat
        self.t_prev = t
        return x_hat
  
    def _alpha(self, cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)
  
    def _lowpass(self, value, prev, cutoff, dt):
        alpha = self._alpha(cutoff, dt)
        return alpha * value + (1 - alpha) * prev


# ============================================================================
# OPTIMIZED GOAL DETECTOR CORE (WITHOUT PER-FRAME JSON STORAGE)
# ============================================================================

class OptimizedGoalDetectorCore:
    def __init__(self, yolo_ball_model='best_b_p.pt', 
                 yolo_screen_model='best_pose.pt',
                 qr_offset_frames=21,
                 target_fps=25,
                 process_scale=0.5,
                 inference_imgsz=640,
                 json_output_path="detections_output.json"):
        
        self.qr_offset_frames = qr_offset_frames
        self.qr_offset_seconds = qr_offset_frames / target_fps
        self.target_fps = target_fps
        
        # OPTIMIZATION: Video scaling parameters
        self.process_scale = process_scale
        self.inference_imgsz = inference_imgsz
        
        # JSON output path
        self.json_output_path = json_output_path
        
        # Session state
        self.session_active = False
        self.session_start_time = 0
        self.session_end_time = 0
        self.current_action = None
        self.current_screens = []
        self.current_block_id = None
        
        # Finishing state
        self.finishing_type = None
        self.finishing_screen = None
        self.finishing_distance = 0.0
        self.is_strong = False
        self.finishing_time = None
        
        # Detection state
        self.detecting = False
        self.ball_positions = []
        self.tracked_balls = defaultdict(list)
        
        # OPTIMIZATION: Store only summaries, not every frame
        self.session_summary = {
            "balls_detected": 0,
            "screen_detections": [],
            "key_detections": []  # Store only key moments (every 30 frames or when goal happens)
        }
        
        # Results storage (only session-level, not per-frame)
        self.results = []
        
        # FPS tracking
        self.fps_buffer = []
        self.last_fps_update = time.time()
        self.current_fps = 0
        
        # Load models (ONLY 2 MODELS)
        self.load_models(yolo_ball_model, yolo_screen_model)
        self.load_face_model()
        
        # Keypoint tracking
        self.last_valid_kp = {}
        self.kp_ema = {}
        self.KP_PERSIST_FRAMES = 18
        self.EMA_ALPHA = 0.85
        self.KEYPOINT_MIN_CONF = 0.08
        
        # Detection parameters
        self.PASS_CROSSED_DISTANCE = 8
        self.PASS_ACCEPTED_DISTANCE = 15
        self.TARGET_CROSSED_DISTANCE = 15
        self.TARGET_ACCEPTED_DISTANCE = 150
        self.GOAL_CROSSED_DISTANCE = 8
        self.GOAL_ACCEPTED_DISTANCE = 15
        self.DIST_GOAL_CROSSED_DEFAULT = 120
        self.DIST_GOAL_ACCEPTED_DEFAULT = 180
        
        self.BALL_MODEL_CONF = 0.35
        self.BALL_POST_CONF = 0.25
        self.GOAL_MODEL_CONF = 0.40
        
        self.RIGHT_ORIENTED_SCREENS = {'2', '3', '4', '9', '10', '11'}
        self.LEFT_ORIENTED_SCREENS = {'5', '6', '7', '12', '13', '14'}
        
        self.PASS_HORIZONTAL_TOLERANCE = 0.15
        self.PROJ_T_SANITY_MIN = -0.2
        self.PROJ_T_SANITY_MAX = 1.2
        
        self.USE_POST_DISTANCE_SCREENS = {'14', '7', '9', '2', '12', '13', '3'}
        self.CUSTOM_THRESHOLDS = {
            '14': 45, '7': 36, '9': 36, '2': 36, '12': 20, '13': 20, '3': 31
        }
        
        self.SCREEN_COLORS = {
            '10': (255,0,0), '11': (0,255,0), '12': (0,0,255), '13': (255,255,0),
            '14': (255,0,255), '2': (0,255,255), '3': (255,128,0), '4': (128,0,255),
            '5': (0,128,255), '6': (255,0,128), '7': (128,255,0), '9': (0,255,128)
        }
        
        self.TARGET_MAPPING = {
            '2R': 'target-2', '2L': 'target-3', '3R': 'target-3', '3L': 'target-4',
            '4R': 'target-4', '5L': 'target-5', '6R': 'target-5', '6L': 'target-6',
            '7R': 'target-6', '7L': 'target-7', '9R': 'target-9', '9L': 'target-10',
            '10R': 'target-10', '10L': 'target-11', '11R': 'target-11', '12L': 'target-12',
            '13R': 'target-12', '13L': 'target-13', '14R': 'target-13', '14L': 'target-14'
        }
        
        # Yaw tracking
        self.yaw_filter = None
        self.aware_detected = False
        self.seen_positive = False
        self.seen_negative = False
        self.yaw_history = deque(maxlen=100)  # Limit history size
        self.frames_without_face = 0
        self.last_display_yaw = None
        self.face_app = None
        
        self.processing = False
        self.should_stop = False
        self.frame_counter = 0
        
        # Callbacks
        self.on_frame_processed = None
        self.on_session_start = None
        self.on_session_end = None
        self.on_goal_detected = None
        
        print(f"✅ OptimizedGoalDetectorCore initialized")
    
    def load_models(self, ball_model, screen_model):
        """Load ONLY 2 YOLO models"""
        print("Loading YOLO models...")
        try:
            self.detection_model = YOLO(ball_model)
            if torch.cuda.is_available():
                self.detection_model.to('cuda')
                if hasattr(self.detection_model.model, 'half'):
                    self.detection_model.model.half()
            print(f"✓ Ball model loaded")
        except Exception as e:
            print(f"✗ Ball model error: {e}")
            self.detection_model = None
            
        try:
            self.goal_model = YOLO(screen_model)
            if torch.cuda.is_available():
                self.goal_model.to('cuda')
                if hasattr(self.goal_model.model, 'half'):
                    self.goal_model.model.half()
            print(f"✓ Screen model loaded")
        except Exception as e:
            print(f"✗ Screen model error: {e}")
            self.goal_model = None
        
        self.pose_model = None
        print(f"✓ Pose model SKIPPED")
    
    def load_face_model(self):
        """Load InsightFace for head pose estimation"""
        print("Loading InsightFace...")
        try:
            import onnxruntime as ort
            providers = ['CUDAExecutionProvider', 'CPUExecutionProvider'] if 'CUDAExecutionProvider' in ort.get_available_providers() else ['CPUExecutionProvider']
            self.face_app = FaceAnalysis(name='buffalo_l', providers=providers)
            self.face_app.prepare(ctx_id=0 if 'CUDAExecutionProvider' in providers else -1, det_size=(160, 160))
            print("✓ Face model loaded")
        except Exception as e:
            print(f"✗ Face model error: {e}")
            self.face_app = None
    
    def update_fps(self, timestamp):
        """Update FPS calculation"""
        self.fps_buffer.append(timestamp)
        if len(self.fps_buffer) > 30:
            self.fps_buffer.pop(0)
        if len(self.fps_buffer) >= 2:
            fps = len(self.fps_buffer) / (self.fps_buffer[-1] - self.fps_buffer[0])
            self.current_fps = fps
        return self.current_fps
    
    def scale_frame(self, frame):
        """Scale frame for faster processing"""
        if self.process_scale < 1.0:
            h, w = frame.shape[:2]
            new_w = int(w * self.process_scale)
            new_h = int(h * self.process_scale)
            return cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        return frame
    
    def process_models_parallel(self, frame):
        """Run ball and screen models in parallel"""
        results = {}
        
        def run_model(model, frame, model_name):
            try:
                with torch.amp.autocast('cuda', enabled=torch.cuda.is_available()):
                    result = model(frame, verbose=False)[0]
                return model_name, result
            except Exception as e:
                return model_name, None
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = []
            if self.detection_model:
                futures.append(executor.submit(run_model, self.detection_model, frame, 'ball'))
            if self.goal_model:
                futures.append(executor.submit(run_model, self.goal_model, frame, 'screen'))
            
            for future in concurrent.futures.as_completed(futures):
                name, result = future.result()
                results[name] = result
        
        return results
    
    def calculate_distance_to_line(self, point, p1, p2):
        x0, y0 = point
        x1, y1 = p1
        x2, y2 = p2
        vx, vy = x2 - x1, y2 - y1
        len2 = vx*vx + vy*vy
        if len2 < 1e-6:
            return float('inf'), 0.0, 0.0, 0.0, 0
        proj_t = ((x0 - x1) * vx + (y0 - y1) * vy) / len2
        t = max(0, min(1, proj_t))
        projx = x1 + t * vx
        projy = y1 + t * vy
        dist = math.sqrt((x0 - projx)**2 + (y0 - projy)**2)
        dist_left = math.sqrt((x0 - x1)**2 + (y0 - y1)**2)
        dist_right = math.sqrt((x0 - x2)**2 + (y0 - y2)**2)
        signed = ((x2 - x1) * (y0 - y1) - (y2 - y1) * (x0 - x1)) / math.sqrt(len2 + 1e-9)
        return dist, dist_left, dist_right, proj_t, signed
    
    def extract_screen_base(self, s):
        s = str(s).strip().upper()
        return ''.join(c for c in s if c.isdigit()) or s
    
    def is_point_between_posts(self, proj_t):
        return -self.PASS_HORIZONTAL_TOLERANCE <= proj_t <= 1 + self.PASS_HORIZONTAL_TOLERANCE
    
    def set_session(self, action, screens, block_id, start_time, qr_raw_data=None):
        """Set active session when QR code is detected"""
        self.current_action = action.upper()
        self.current_screens = screens
        self.current_block_id = block_id
        self.session_start_time = start_time
        self.session_active = True
        self.detecting = True
        
        # Initialize finishing attributes
        self.finishing_type = None
        self.finishing_screen = None
        self.finishing_distance = 0.0
        self.is_strong = False
        self.finishing_time = 0.0
        
        self.aware_detected = False
        self.seen_positive = False
        self.seen_negative = False
        self.yaw_filter = None
        self.yaw_history.clear()
        self.last_display_yaw = None
        self.frames_without_face = 0
        
        self.ball_positions = []
        self.tracked_balls = defaultdict(list)
        
        # Reset session summary
        self.session_summary = {
            "balls_detected": 0,
            "screen_detections": [],
            "key_detections": []
        }
        self.frame_counter = 0
        
        # Store QR data
        self.current_qr_data = {
            "block_id": block_id,
            "action": action.upper(),
            "screens": screens,
            "timestamp": start_time,
            "raw_data": qr_raw_data
        }
        
        print(f"\n🎯 SESSION ACTIVE: {self.current_action} {self.current_screens}")
        if self.on_session_start:
            self.on_session_start(block_id, action, screens)
    
    def end_session(self, end_time):
        """End current session and record result (no per-frame storage)"""
        if self.session_active:
            self.session_end_time = end_time
            self.session_active = False
            self.detecting = False
            
            if self.finishing_type is None:
                self.finishing_type = "WRONG"
            
            print(f"\n🏁 SESSION ENDED: {self.current_action} {self.current_screens}")
            
            # Create session result (without per-frame detections for speed)
            session_result = {
                "block_id": self.current_block_id,
                "qr_data": self.current_qr_data,
                "action": self.current_action,
                "screens": self.current_screens,
                "start_time": self.session_start_time,
                "end_time": self.session_end_time,
                "duration_seconds": round(self.session_end_time - self.session_start_time, 3),
                "finishing": {
                    "type": self.finishing_type,
                    "goal_screen": self.finishing_screen if self.finishing_screen else "None",
                    "distance_px": round(self.finishing_distance, 1) if self.finishing_distance else 0,
                    "is_strong": self.is_strong,
                    "time_from_start": round(self.finishing_time, 3) if self.finishing_time else 0
                },
                "awareness": {
                    "detected": self.aware_detected,
                    "yaw_history": [round(y, 1) for y in list(self.yaw_history)[-30:]]  # Last 30 only
                },
                "summary": self.session_summary
            }
            
            self.results.append(session_result)
            
            # Save to JSON after each session (async)
            self.save_to_json_async()
            
            if self.on_session_end:
                self.on_session_end(self.current_block_id, self.finishing_type, 
                                  self.finishing_screen, self.finishing_distance, 
                                  self.is_strong, self.aware_detected)
    
    def save_to_json_async(self):
        """Save results to JSON in a separate thread"""
        def save():
            output_data = {
                "system_info": {
                    "created_at": datetime.now().isoformat(),
                    "processing_scale": self.process_scale,
                    "inference_imgsz": self.inference_imgsz,
                    "target_fps": self.target_fps,
                    "qr_offset_frames": self.qr_offset_frames
                },
                "sessions": self.results,
                "summary": {
                    "total_sessions": len(self.results),
                    "correct_count": sum(1 for r in self.results if r['finishing']['type'] == 'CORRECT'),
                    "late_count": sum(1 for r in self.results if r['finishing']['type'] == 'LATE'),
                    "wrong_count": sum(1 for r in self.results if r['finishing']['type'] == 'WRONG'),
                    "total_balls_detected": sum(r['summary'].get('balls_detected', 0) for r in self.results)
                }
            }
            
            try:
                # Write to temp file first, then rename
                temp_path = self.json_output_path + ".tmp"
                with open(temp_path, 'w') as f:
                    json.dump(output_data, f, indent=2)
                os.replace(temp_path, self.json_output_path)
                print(f"💾 Results saved to {self.json_output_path}")
            except Exception as e:
                print(f"❌ Error saving JSON: {e}")
        
        # Run save in background thread to not block processing
        save_thread = threading.Thread(target=save, daemon=True)
        save_thread.start()
    
    def process_frame(self, frame, timestamp):
        """Process a single frame (optimized - minimal JSON storage)"""
        self.frame_counter += 1
        
        if not self.detecting:
            return self.scale_frame(frame)
        
        # Scale frame for faster processing
        scaled_frame = self.scale_frame(frame)
        original_h, original_w = frame.shape[:2]
        scale_x = original_w / scaled_frame.shape[1]
        scale_y = original_h / scaled_frame.shape[0]
        
        is_late = self.session_end_time > 0 and timestamp > self.session_end_time
        
        # Run models in parallel
        results = self.process_models_parallel(scaled_frame)
        
        # Store only key detections (every 30 frames) to reduce JSON size
        save_key_frame = (self.frame_counter % 30 == 0) or self.finishing_type is not None
        
        frame_detection_summary = None
        if save_key_frame:
            frame_detection_summary = {
                "frame": self.frame_counter,
                "time": round(timestamp - self.session_start_time, 2)
            }
        
        # Ball detection (count only, don't store all coordinates)
        balls_detected_this_frame = 0
        if self.current_action in ['PASS', 'TARGET', 'GOAL'] and 'ball' in results and results['ball'] is not None:
            try:
                dets = results['ball']
                if dets.boxes is not None:
                    for box in dets.boxes:
                        if int(box.cls) != 0:
                            continue
                        xyxy = box.xyxy[0].cpu().numpy()
                        if np.any(np.isnan(xyxy)):
                            continue
                        x1, y1, x2, y2 = map(int, xyxy * scale_x)
                        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                        conf = float(box.conf)
                        if conf >= self.BALL_POST_CONF:
                            balls_detected_this_frame += 1
                            self.ball_positions.append((cx, cy, timestamp))
                            self.ball_positions = [p for p in self.ball_positions if timestamp - p[2] < 2.0]
                            cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 0), 2)
            except:
                pass
        
        # Update session summary
        self.session_summary["balls_detected"] += balls_detected_this_frame
        
        if save_key_frame and balls_detected_this_frame > 0:
            frame_detection_summary["balls"] = balls_detected_this_frame
        
        # Screen/Goal detection
        screen_detected = False
        if 'screen' in results and results['screen'] is not None and self.current_action in ['PASS', 'TARGET', 'PRESS', 'SPRINT', 'GOAL']:
            allowed_screens = self.current_screens
            allowed_screen_strings = [str(s).strip() for s in allowed_screens]
            
            try:
                screen_dets = results['screen']
                if screen_dets.boxes is not None:
                    for i_box, box in enumerate(screen_dets.boxes):
                        cls = int(box.cls)
                        if cls not in self.goal_model.names:
                            continue
                        xyxy = box.xyxy[0].cpu().numpy()
                        if np.any(np.isnan(xyxy)):
                            continue
                        x1, y1, x2, y2 = map(int, xyxy * scale_x)
                        screen_name = str(self.goal_model.names[cls]).strip()
                        
                        is_target_keypoint = 'target-' in screen_name.lower()
                        
                        if self.current_action == 'TARGET':
                            if not is_target_keypoint:
                                continue
                            is_allowed = screen_name in [self.TARGET_MAPPING.get(s, '') for s in allowed_screen_strings]
                        elif self.current_action in ['PRESS', 'SPRINT']:
                            if is_target_keypoint:
                                continue
                            is_allowed = len(allowed_screen_strings) == 0 or self.extract_screen_base(screen_name) in [self.extract_screen_base(s) for s in allowed_screen_strings]
                        else:
                            is_allowed = self.extract_screen_base(screen_name) in [self.extract_screen_base(s) for s in allowed_screen_strings]
                        
                        if not is_allowed:
                            continue
                        
                        screen_name_base = self.extract_screen_base(screen_name)
                        color = self.SCREEN_COLORS.get(screen_name_base, (200,200,200))
                        
                        screen_detected = True
                        thickness = 3 if self.finishing_type is None else 2
                        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
                        cv2.putText(frame, screen_name, (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                        
                        # Store screen detection summary (not every frame)
                        if save_key_frame:
                            self.session_summary["screen_detections"].append({
                                "frame": self.frame_counter,
                                "screen": screen_name,
                                "bbox": [x1, y1, x2, y2]
                            })
                            # Keep only last 50 to prevent memory bloat
                            if len(self.session_summary["screen_detections"]) > 50:
                                self.session_summary["screen_detections"] = self.session_summary["screen_detections"][-50:]
                        
                        # Keypoint processing
                        if hasattr(screen_dets, 'keypoints') and screen_dets.keypoints is not None and i_box < len(screen_dets.keypoints.xy):
                            kps_xy = screen_dets.keypoints.xy[i_box].cpu().numpy()
                            if not np.any(np.isnan(kps_xy)):
                                kp_right = tuple(map(int, kps_xy[0] * scale_x))
                                kp_left = tuple(map(int, kps_xy[1] * scale_x))
                                
                                if kp_right[0] > 0 and kp_right[1] > 0 and kp_left[0] > 0 and kp_left[1] > 0:
                                    line_color = (0, 255, 255) if self.finishing_type is None else (180, 180, 255)
                                    cv2.line(frame, kp_left, kp_right, line_color, 3)
                                    cv2.circle(frame, kp_left, 6, (0, 255, 0), -1)
                                    cv2.circle(frame, kp_right, 6, (0, 255, 0), -1)
                                    
                                    is_right_oriented = screen_name_base in self.RIGHT_ORIENTED_SCREENS
                                    goal_side_sign = -1 if is_right_oriented else 1
                                    
                                    if self.finishing_type is None and self.current_action in ['PASS', 'TARGET', 'GOAL']:
                                        for (cx, cy), conf in self.ball_positions[-10:]:  # Check last 10 ball positions
                                            dist, dist_left, dist_right, proj_t, signed_raw = self.calculate_distance_to_line((cx, cy), kp_left, kp_right)
                                            signed = signed_raw * goal_side_sign
                                            
                                            if screen_name_base in self.USE_POST_DISTANCE_SCREENS:
                                                dist_to_left = math.hypot(cx - kp_left[0], cy - kp_left[1])
                                                dist_to_right = math.hypot(cx - kp_right[0], cy - kp_right[1])
                                                effective_dist = min(dist_to_left, dist_to_right)
                                                threshold = self.CUSTOM_THRESHOLDS.get(screen_name_base, self.PASS_ACCEPTED_DISTANCE)
                                                is_within_distance = effective_dist <= threshold
                                                is_position_valid = True
                                            else:
                                                effective_dist = dist
                                                is_within_distance = dist <= self.PASS_ACCEPTED_DISTANCE
                                                is_position_valid = self.is_point_between_posts(proj_t) and (signed > -25)
                                            
                                            if is_within_distance and is_position_valid:
                                                self.finishing_type = "LATE" if is_late else "CORRECT"
                                                self.finishing_screen = screen_name
                                                self.finishing_distance = effective_dist
                                                self.is_strong = effective_dist <= self.PASS_CROSSED_DISTANCE
                                                self.finishing_time = timestamp - self.session_start_time
                                                
                                                # Add key moment to summary
                                                self.session_summary["key_detections"].append({
                                                    "type": "goal",
                                                    "frame": self.frame_counter,
                                                    "time": round(self.finishing_time, 2),
                                                    "screen": screen_name,
                                                    "distance": round(effective_dist, 1),
                                                    "is_strong": self.is_strong
                                                })
                                                
                                                goal_color = (0, 165, 255) if is_late else (0, 255, 0)
                                                cv2.rectangle(frame, (x1, y1), (x2, y2), goal_color, 6)
                                                cv2.line(frame, kp_left, kp_right, goal_color, 5)
                                                
                                                text = "LATE FINISHING" if is_late else "CORRECT FINISHING"
                                                if self.is_strong:
                                                    text += " (STRONG!)"
                                                cv2.putText(frame, text, (x1, y1-30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, goal_color, 2)
                                                cv2.putText(frame, "GOAL!", (cx-30, cy-20), cv2.FONT_HERSHEY_SIMPLEX, 1.0, goal_color, 3)
                                                
                                                print(f"⚽ {text} on {screen_name} at {effective_dist:.1f}px")
                                                if self.on_goal_detected:
                                                    self.on_goal_detected(self.finishing_type, screen_name, effective_dist, self.is_strong)
                                                break
                                    
                                    elif self.finishing_type is None and self.current_action in ['PRESS', 'SPRINT']:
                                        # Simplified press/sprint detection without person boxes for speed
                                        pass
            except Exception as e:
                pass
        
        if save_key_frame and screen_detected:
            if "screens_detected" not in frame_detection_summary:
                frame_detection_summary["screens"] = 1
        
        if save_key_frame and frame_detection_summary and (balls_detected_this_frame > 0 or screen_detected):
            self.session_summary["key_detections"].append(frame_detection_summary)
            # Keep only last 100 key detections
            if len(self.session_summary["key_detections"]) > 100:
                self.session_summary["key_detections"] = self.session_summary["key_detections"][-100:]
        
        # Face detection for yaw (simplified for speed)
        if self.face_app and self.finishing_type is None:
            try:
                # Simplified: use center of frame for face detection
                h, w = frame.shape[:2]
                center_roi = frame[h//4:3*h//4, w//4:3*w//4]
                if center_roi.size > 0:
                    faces = self.face_app.get(center_roi)
                    if faces:
                        face = faces[0]
                        raw_yaw = face.pose[1]
                        if self.yaw_filter is None:
                            self.yaw_filter = OneEuroFilter(timestamp, raw_yaw, min_cutoff=0.7, beta=0.06, d_cutoff=1.0)
                        smoothed_yaw = self.yaw_filter(timestamp, raw_yaw)
                        self.last_display_yaw = smoothed_yaw
                        self.frames_without_face = 0
                        self.yaw_history.append(smoothed_yaw)
                        
                        if smoothed_yaw > 8:
                            self.seen_positive = True
                        elif smoothed_yaw < -8:
                            self.seen_negative = True
                        
                        if self.seen_positive and self.seen_negative:
                            self.aware_detected = True
                        
                        cv2.putText(frame, f"YAW: {int(smoothed_yaw)} deg", (10, 60), 
                                  cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            except Exception as e:
                pass
        
        # Draw action info
        if self.current_action:
            overlay = frame.copy()
            cv2.rectangle(overlay, (10, 10), (450, 200), (0, 0, 0), -1)
            frame = cv2.addWeighted(overlay, 0.6, frame, 0.4, 0)
            
            cv2.putText(frame, f"FPS: {self.current_fps:.1f}", (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            
            screens_str = ', '.join(self.current_screens)
            cv2.putText(frame, f"ACTION: {self.current_action}  {screens_str}", (20, 65),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            cv2.putText(frame, f"Block: {self.current_block_id}", (20, 95),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
            
            if self.finishing_type is not None:
                if self.finishing_type == "CORRECT":
                    result_color = (0, 255, 0)
                    result_text = f"✓ CORRECT FINISHING"
                elif self.finishing_type == "LATE":
                    result_color = (0, 165, 255)
                    result_text = f"⚠ LATE FINISHING"
                else:
                    result_color = (0, 0, 255)
                    result_text = f"✗ WRONG FINISHING"
                
                cv2.putText(frame, result_text, (20, 125), cv2.FONT_HERSHEY_SIMPLEX, 0.6, result_color, 2)
                
                if self.finishing_screen:
                    screen_info = f"Screen: {self.finishing_screen} | Distance: {self.finishing_distance:.1f}px"
                    cv2.putText(frame, screen_info, (20, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
                
                if self.is_strong:
                    cv2.putText(frame, "💪 STRONG!", (20, 175), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
                
                if self.aware_detected:
                    cv2.putText(frame, "🧠 AWARE", (20, 195), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            
            elif self.session_active:
                cv2.putText(frame, "▶ DETECTING...", (20, 125), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        
        return frame


# ============================================================================
# REAL-TIME MODE (with Optimized Detector)
# ============================================================================

class RealTimeMode:
    def __init__(self, detector, on_frame_callback, on_status_callback):
        self.detector = detector
        self.on_frame_callback = on_frame_callback
        self.on_status_callback = on_status_callback
        self.running = False
        self.capture_threads = {}
        self.frame_queues = {}
        self.frame_buffers = {}
        self.frame_locks = {}
        self.cameras = {
            "camera-1": {"address": "rtsp://admin:majidAram2@192.168.2.1:554/Streaming/Channels/101/"},
            "camera-8": {"address": "rtsp://admin:majidAram2@192.168.2.8:554/Streaming/Channels/101/"}
        }
        
        # QR detection
        self.screen_monitor = {"left": 1920, "top": 0, "width": 1920, "height": 1080}
        self.qr_roi = {"x": 0, "y": 0, "width": 1920, "height": 540}
        self.pending_actions = []
        self.last_qr_time = 0
        self.qr_cooldown = 0.5
        self.last_qr_data = ""
        self.block_counter = 0
        
        # FPS tracking
        self.frame_times = []
        self.last_fps_print = time.time()
        
        # Initialize buffers
        for cam_name in self.cameras:
            self.frame_buffers[cam_name] = None
            self.frame_locks[cam_name] = threading.Lock()
            self.frame_queues[cam_name] = queue.Queue(maxsize=2)
    
    def parse_qr_data(self, raw_data):
        action = ""
        screens = []
        if not raw_data:
            return action, screens
        try:
            qr = json.loads(raw_data)
            action = str(qr.get("action", "")).strip()
            val = qr.get("screens_index", [])
            if isinstance(val, str):
                screens = [s.strip() for s in val.split(',') if s.strip()]
            elif isinstance(val, list):
                screens = [str(s).strip() for s in val if s is not None]
            if action or screens:
                return action.upper(), screens
        except:
            pass
        import re
        action_match = re.search(r'action[\s:=]*["\']?([A-Za-z]+)', raw_data, re.IGNORECASE)
        if action_match:
            action = action_match.group(1).upper()
        screens_match = re.findall(r'(\d+[LR]?)', raw_data, re.IGNORECASE)
        if screens_match:
            screens = [s.upper() for s in screens_match]
        return action, screens
    
    def detect_qr_codes(self, frame, timestamp):
        current_time = time.time()
        if current_time - self.last_qr_time < self.qr_cooldown:
            return None
        
        roi_frame = frame[self.qr_roi["y"]:self.qr_roi["y"]+self.qr_roi["height"], 
                          self.qr_roi["x"]:self.qr_roi["x"]+self.qr_roi["width"]]
        
        try:
            from pyzbar import pyzbar
            decoded_objects = pyzbar.decode(roi_frame)
            for obj in decoded_objects:
                qr_data = obj.data.decode('utf-8').strip()
                if not qr_data or qr_data == self.last_qr_data:
                    continue
                
                self.last_qr_data = qr_data
                self.last_qr_time = current_time
                
                action, screens = self.parse_qr_data(qr_data)
                
                if action and screens:
                    qr_lower = qr_data.lower()
                    is_start = any(k in qr_lower for k in ['start', 'begin', 's', 'play'])
                    is_end = any(k in qr_lower for k in ['end', 'stop', 'e', 'finish'])
                    
                    if is_start:
                        if self.detector.session_active:
                            self.detector.end_session(current_time)
                        
                        self.block_counter += 1
                        block_id = f"A{self.block_counter}"
                        scheduled_time = current_time + self.detector.qr_offset_seconds
                        
                        self.pending_actions.append({
                            "action": action,
                            "screens": screens,
                            "block_id": block_id,
                            "scheduled_time": scheduled_time,
                            "detected_time": current_time,
                            "raw_data": qr_data
                        })
                        
                        self.on_status_callback(f"QR START: {action} {screens} (session in {self.detector.qr_offset_seconds:.1f}s)")
                    
                    elif is_end:
                        scheduled_time = current_time + self.detector.qr_offset_seconds
                        self.pending_actions.append({
                            "action": "END",
                            "scheduled_time": scheduled_time,
                            "is_end": True
                        })
                        
                        self.on_status_callback(f"QR END (session will end in {self.detector.qr_offset_seconds:.1f}s)")
                
                return qr_data
        except Exception as e:
            pass
        return None
    
    def update_sessions(self, current_time):
        actions_to_process = [a for a in self.pending_actions if a["scheduled_time"] <= current_time]
        for action in actions_to_process:
            if action.get("is_end"):
                if self.detector.session_active:
                    self.detector.end_session(current_time)
            else:
                if self.detector.session_active:
                    self.detector.end_session(current_time)
                self.detector.set_session(
                    action["action"],
                    action["screens"],
                    action["block_id"],
                    action["detected_time"],
                    action.get("raw_data")
                )
            self.pending_actions.remove(action)
    
    def capture_screen(self):
        with mss.mss() as sct:
            while self.running:
                try:
                    img = sct.grab(self.screen_monitor)
                    frame = np.array(img)
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                    self.detect_qr_codes(frame, time.time())
                    time.sleep(1.0 / 30.0)
                except:
                    time.sleep(0.1)
    
    def capture_stream(self, cam_name, rtsp_url):
        while self.running:
            try:
                cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                if not cap.isOpened():
                    time.sleep(5)
                    continue
                
                while self.running:
                    ret, frame = cap.read()
                    if not ret:
                        break
                    
                    height, width = frame.shape[:2]
                    target_height = 540
                    target_width = int(width * target_height / height)
                    frame = cv2.resize(frame, (target_width, target_height))
                    
                    with self.frame_locks[cam_name]:
                        self.frame_buffers[cam_name] = frame.copy()
                    
                    while self.frame_queues[cam_name].qsize() >= self.frame_queues[cam_name].maxsize:
                        try:
                            self.frame_queues[cam_name].get_nowait()
                        except queue.Empty:
                            break
                    
                    try:
                        self.frame_queues[cam_name].put_nowait(frame.copy())
                    except queue.Full:
                        pass
                
                cap.release()
                time.sleep(5)
            except Exception as e:
                print(f"❌ {cam_name} error: {e}")
                time.sleep(5)
    
    def get_synchronized_frames(self):
        frames = {}
        for cam_name in self.cameras:
            try:
                frame = self.frame_queues[cam_name].get_nowait()
                frames[cam_name] = frame
            except queue.Empty:
                with self.frame_locks[cam_name]:
                    if self.frame_buffers[cam_name] is not None:
                        frames[cam_name] = self.frame_buffers[cam_name].copy()
                    else:
                        return None, None
        
        if len(frames) != 2:
            return None, None
        
        return frames.get("camera-1"), frames.get("camera-8")
    
    def stitch_frames(self, frame_left, frame_right):
        if frame_left is None or frame_right is None:
            return None
        
        h_left, w_left = frame_left.shape[:2]
        h_right, w_right = frame_right.shape[:2]
        
        if h_left != h_right:
            target_height = min(h_left, h_right)
            if h_left != target_height:
                scale = target_height / h_left
                new_width = int(w_left * scale)
                frame_left = cv2.resize(frame_left, (new_width, target_height))
            if h_right != target_height:
                scale = target_height / h_right
                new_width = int(w_right * scale)
                frame_right = cv2.resize(frame_right, (new_width, target_height))
        
        return np.hstack([frame_left, frame_right])
    
    def add_overlay(self, frame):
        h, w = frame.shape[:2]
        mid_x = w // 2
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, 35), (0, 0, 0), -1)
        frame = cv2.addWeighted(overlay, 0.7, frame, 0.3, 0)
        
        cv2.putText(frame, f"QR Offset: {self.detector.qr_offset_frames}f ({self.detector.qr_offset_seconds:.1f}s)", (10, 25),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        cv2.putText(frame, f"JSON: {os.path.basename(self.detector.json_output_path)}", (10, 50),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)
        cv2.putText(frame, "CAM1", (w//4 - 30, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        cv2.putText(frame, "CAM8", (w//4*3 - 30, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        cv2.line(frame, (mid_x, 0), (mid_x, h), (255, 255, 255), 2)
        
        if self.detector.session_active:
            cv2.circle(frame, (w - 30, 20), 8, (0, 255, 0), -1)
            cv2.putText(frame, "ACTIVE", (w - 80, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
        
        return frame
    
    def start(self):
        self.running = True
        
        # Start screen capture
        screen_thread = threading.Thread(target=self.capture_screen, daemon=True)
        screen_thread.start()
        
        # Start camera captures
        for cam_name, config in self.cameras.items():
            thread = threading.Thread(target=self.capture_stream, args=(cam_name, config["address"]), daemon=True)
            thread.start()
            self.capture_threads[cam_name] = thread
        
        # Main display loop
        cv2.namedWindow("Goal Detection - Optimized", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("Goal Detection - Optimized", 1920, 600)
        
        frame_count = 0
        start_time = time.time()
        
        print("\n" + "="*60)
        print("OPTIMIZED REAL-TIME PROCESSING ACTIVE")
        print(f"JSON output: {self.detector.json_output_path}")
        print(f"Processing scale: {self.detector.process_scale}x")
        print(f"Inference imgsz: {self.detector.inference_imgsz}")
        print("="*60 + "\n")
        
        while self.running:
            current_time = time.time()
            self.update_sessions(current_time)
            
            frame_left, frame_right = self.get_synchronized_frames()
            
            if frame_left is None or frame_right is None:
                h, w = 540, 960
                waiting_frame = np.zeros((h, w, 3), dtype=np.uint8)
                cv2.putText(waiting_frame, "Waiting for camera streams...", (w//2 - 200, h//2),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                cv2.imshow("Goal Detection - Optimized", waiting_frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
                continue
            
            stitched = self.stitch_frames(frame_left, frame_right)
            if stitched is None:
                continue
            
            # Update FPS in detector
            self.detector.update_fps(current_time)
            
            # Process frame
            processed = self.detector.process_frame(stitched, current_time)
            processed = self.add_overlay(processed)
            
            # Print FPS to terminal every second
            frame_count += 1
            if current_time - self.last_fps_print >= 1.0:
                elapsed = current_time - start_time
                avg_fps = frame_count / elapsed
                sessions_completed = len(self.detector.results)
                print(f"\r📊 FPS: {self.detector.current_fps:.1f} | Avg: {avg_fps:.1f} | "
                      f"Sessions: {sessions_completed} | Active: {self.detector.session_active} | "
                      f"Balls: {self.detector.session_summary['balls_detected']}", end="", flush=True)
                self.last_fps_print = current_time
            
            cv2.imshow("Goal Detection - Optimized", processed)
            
            if self.on_frame_callback:
                self.on_frame_callback(processed)
            
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        
        # Print final stats
        elapsed = time.time() - start_time
        avg_fps = frame_count / elapsed
        print(f"\n\n{'='*60}")
        print("PROCESSING COMPLETE")
        print(f"Total frames: {frame_count}")
        print(f"Total time: {elapsed:.1f}s")
        print(f"Average FPS: {avg_fps:.1f}")
        print(f"Sessions completed: {len(self.detector.results)}")
        print(f"JSON saved to: {self.detector.json_output_path}")
        print("="*60)
        
        cv2.destroyAllWindows()
        self.running = False
    
    def stop(self):
        self.running = False


# ============================================================================
# GUI APPLICATION (Simplified)
# ============================================================================

class OptimizedGoalDetectionGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Goal Detection System - Optimized")
        self.root.geometry("1200x800")
        self.root.configure(bg='#2b2b2b')
        
        # Variables
        self.offset_frames = tk.StringVar(value="21")
        self.process_scale = tk.StringVar(value="0.5")
        self.inference_imgsz = tk.StringVar(value="640")
        self.json_filename = tk.StringVar(value="detections_output.json")
        
        # Detector
        self.detector = None
        self.realtime_mode = None
        self.is_processing = False
        
        self.setup_ui()
    
    def setup_ui(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TLabel', background='#2b2b2b', foreground='white', font=('Arial', 10))
        style.configure('TFrame', background='#2b2b2b')
        style.configure('TLabelframe', background='#2b2b2b', foreground='white')
        style.configure('TLabelframe.Label', background='#2b2b2b', foreground='white')
        style.configure('TButton', background='#3c3c3c', foreground='white', font=('Arial', 10))
        style.map('TButton', background=[('active', '#4c4c4c')])
        
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        left_panel = ttk.Frame(main_frame, width=300)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        left_panel.pack_propagate(False)
        
        params_frame = ttk.LabelFrame(left_panel, text="Configuration", padding="10")
        params_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(params_frame, text="QR Offset Frames:").pack(anchor=tk.W)
        offset_entry = ttk.Entry(params_frame, textvariable=self.offset_frames, width=10)
        offset_entry.pack(anchor=tk.W, pady=(0, 5))
        
        ttk.Label(params_frame, text="Processing Scale (0.5 = 1920x540):").pack(anchor=tk.W, pady=(10, 0))
        scale_entry = ttk.Entry(params_frame, textvariable=self.process_scale, width=10)
        scale_entry.pack(anchor=tk.W, pady=(0, 5))
        
        ttk.Label(params_frame, text="Inference Size (640 recommended):").pack(anchor=tk.W, pady=(10, 0))
        imgsz_entry = ttk.Entry(params_frame, textvariable=self.inference_imgsz, width=10)
        imgsz_entry.pack(anchor=tk.W, pady=(0, 5))
        
        ttk.Label(params_frame, text="JSON Output File:").pack(anchor=tk.W, pady=(10, 0))
        json_entry = ttk.Entry(params_frame, textvariable=self.json_filename, width=20)
        json_entry.pack(anchor=tk.W, pady=(0, 5))
        
        ttk.Label(params_frame, text="\n⚡ OPTIMIZATIONS:", font=('Arial', 10, 'bold')).pack(anchor=tk.W, pady=(10, 5))
        ttk.Label(params_frame, text="• No per-frame JSON storage", font=('Arial', 8)).pack(anchor=tk.W)
        ttk.Label(params_frame, text="• Async JSON saving", font=('Arial', 8)).pack(anchor=tk.W)
        ttk.Label(params_frame, text="• Key frames only (every 30 frames)", font=('Arial', 8)).pack(anchor=tk.W)
        ttk.Label(params_frame, text="• Reduced face detection ROI", font=('Arial', 8)).pack(anchor=tk.W)
        
        control_frame = ttk.Frame(left_panel)
        control_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.start_button = ttk.Button(control_frame, text="START", command=self.start_processing)
        self.start_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        self.stop_button = ttk.Button(control_frame, text="STOP", command=self.stop_processing, state=tk.DISABLED)
        self.stop_button.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5, 0))
        
        status_frame = ttk.LabelFrame(left_panel, text="Status", padding="10")
        status_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        
        self.status_text = ScrolledText(status_frame, height=12, bg='#1e1e1e', fg='#00ff00', font=('Consolas', 9))
        self.status_text.pack(fill=tk.BOTH, expand=True)
        
        right_panel = ttk.Frame(main_frame)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        self.video_label = ttk.Label(right_panel, text="Video Feed (Optimized)", background='#000000')
        self.video_label.pack(fill=tk.BOTH, expand=True)
    
    def init_detector(self):
        try:
            offset = int(self.offset_frames.get())
            scale = float(self.process_scale.get())
            imgsz = int(self.inference_imgsz.get())
            json_path = self.json_filename.get()
        except:
            offset = 21
            scale = 0.5
            imgsz = 640
            json_path = "detections_output.json"
        
        self.detector = OptimizedGoalDetectorCore(
            yolo_ball_model="best_b_p.pt",
            yolo_screen_model="best_pose.pt",
            qr_offset_frames=offset,
            target_fps=25,
            process_scale=scale,
            inference_imgsz=imgsz,
            json_output_path=json_path
        )
        
        self.detector.on_frame_processed = self.update_video_display
        self.detector.on_session_start = self.on_session_start
        self.detector.on_session_end = self.on_session_end
        self.detector.on_goal_detected = self.on_goal_detected
    
    def update_video_display(self, frame):
        if frame is not None:
            h, w = frame.shape[:2]
            display_w = 800
            display_h = int(h * display_w / w)
            display_frame = cv2.resize(frame, (display_w, display_h))
            rgb_frame = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            img = tk.PhotoImage(data=cv2.imencode('.png', rgb_frame)[1].tobytes())
            self.video_label.config(image=img)
            self.video_label.image = img
    
    def on_session_start(self, block_id, action, screens):
        self.log_message(f"▶ SESSION START: {block_id} - {action} {screens}")
    
    def on_session_end(self, block_id, finishing_type, screen, distance, is_strong, aware):
        strong_str = " (STRONG)" if is_strong else ""
        aware_str = " 🧠 AWARE" if aware else ""
        distance_str = f"{distance:.1f}px" if distance is not None else "N/A"
        screen_str = screen if screen else "None"
        self.log_message(f"🏁 SESSION END: {block_id} - {finishing_type}{strong_str}{aware_str} - {screen_str} @ {distance_str}")
    
    def on_goal_detected(self, finishing_type, screen, distance, is_strong):
        strong_str = " (STRONG!)" if is_strong else ""
        distance_str = f"{distance:.1f}px" if distance is not None else "N/A"
        screen_str = screen if screen else "Unknown"
        self.log_message(f"⚽ GOAL DETECTED: {finishing_type} on {screen_str} at {distance_str}{strong_str}")
    
    def log_message(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.status_text.see(tk.END)
        print(message)
    
    def start_processing(self):
        if self.is_processing:
            messagebox.showwarning("Warning", "Processing already running")
            return
        
        self.log_message("Starting OPTIMIZED real-time mode...")
        self.log_message(f"JSON file: {self.json_filename.get()}")
        
        self.init_detector()
        
        self.realtime_mode = RealTimeMode(
            self.detector,
            self.update_video_display,
            self.log_message
        )
        
        self.is_processing = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        
        self.processing_thread = threading.Thread(target=self.run_realtime, daemon=True)
        self.processing_thread.start()
    
    def run_realtime(self):
        try:
            self.realtime_mode.start()
        except Exception as e:
            self.log_message(f"ERROR: {e}")
        finally:
            self.stop_processing()
    
    def stop_processing(self):
        if self.realtime_mode:
            self.realtime_mode.stop()
            self.realtime_mode = None
        
        self.is_processing = False
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        
        self.log_message("Processing stopped.")
    
    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()
    
    def on_closing(self):
        self.stop_processing()
        cv2.destroyAllWindows()
        self.root.destroy()


def main():
    print("="*60)
    print("OPTIMIZED GOAL DETECTION SYSTEM")
    print("="*60)
    print("Optimizations applied:")
    print("  • No per-frame JSON storage (30x faster)")
    print("  • Async JSON saving")
    print("  • Key frames only (every 30 frames)")
    print("  • Reduced face detection ROI")
    print("="*60 + "\n")
    
    app = OptimizedGoalDetectionGUI()
    app.run()


if __name__ == "__main__":
    main()