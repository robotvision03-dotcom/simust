import json
import os
import numpy as np
from datetime import datetime
from collections import defaultdict
import cv2
import math
from ultralytics import YOLO
from insightface.app import FaceAnalysis
import torch
import warnings

warnings.filterwarnings('ignore', category=FutureWarning, module='insightface.utils.transform')
os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'video_codec;h264_cuvid'


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


class BlockIDVideoProcessor:
    def __init__(self, video_path, timestamps_file, qr_file,
                 yolo_ball_model='best_b_p.pt',
                 yolo_screen_model='best_pose.pt',
                 yolo_pose_model='best_b_p.pt',
                 pass_crossed_distance=10,
                 pass_accepted_distance=20,
                 target_crossed_distance=15,
                 target_accepted_distance=150,
                 goal_crossed_distance=8,
                 goal_accepted_distance=15,
                 target_side_threshold_left=0.3,
                 target_side_threshold_right=0.7,
                 frame_offset=21,
                 min_duration_percentage=85,
                 extra_frames_after_action=15):
       
        self.video_path = video_path
        self.timestamps_file = timestamps_file
        self.qr_file = qr_file
        self.yolo_ball_model_path = yolo_ball_model
        self.yolo_screen_model_path = yolo_screen_model
        self.yolo_pose_model_path = yolo_pose_model
        self.frame_offset = frame_offset
        self.min_duration_percentage = min_duration_percentage
        self.EXTRA_FRAMES_AFTER_ACTION = extra_frames_after_action
        self.grace_seconds = 3.0
        self.PASS_CROSSED_DISTANCE = pass_crossed_distance
        self.PASS_ACCEPTED_DISTANCE = pass_accepted_distance
        self.TARGET_CROSSED_DISTANCE = target_crossed_distance
        self.TARGET_ACCEPTED_DISTANCE = target_accepted_distance
        self.GOAL_CROSSED_DISTANCE = goal_crossed_distance
        self.GOAL_ACCEPTED_DISTANCE = goal_accepted_distance
        self.DIST_GOAL_CROSSED_DEFAULT = 120
        self.DIST_GOAL_ACCEPTED_DEFAULT = 180
        self.TARGET_SIDE_THRESHOLD_LEFT = target_side_threshold_left
        self.TARGET_SIDE_THRESHOLD_RIGHT = target_side_threshold_right
        self.PASS_HORIZONTAL_TOLERANCE = 0.15
        self.PROJ_T_SANITY_MIN = -0.2
        self.PROJ_T_SANITY_MAX = 1.2
        self.GOAL_NEAR_DISTANCE_PX = 110
        self.TARGET_LEFT_OFFSET_THRESHOLD = 110
        self.TARGET_RIGHT_OFFSET_THRESHOLD = 110
        self.BALL_MODEL_CONF = 0.18
        self.BALL_POST_CONF = 0.07
        self.GOAL_MODEL_CONF = 0.15
        self.KEYPOINT_MIN_CONF = 0.08
        self.KP_PERSIST_FRAMES = 18
        self.EMA_ALPHA = 0.85
        self.MIN_FRAMES_TO_CONSIDER = 5
        self.MIN_DISPLACEMENT_PX = 25
        self.MIN_AVG_SPEED_PX_PER_FRAME = 2.0
        self.MAX_STATIC_NEAR_GOAL_RATIO = 0.85
        self.RIGHT_ORIENTED_SCREENS = {'2', '3', '4', '9', '10', '11'}
        self.LEFT_ORIENTED_SCREENS = {'5', '6', '7', '12', '13', '14'}
        self.SCREEN_YAW_RANGES = {
            '12': (79, 999), '13': (68, 71), '14': (38, 41),
            '1': (-3, 3), '8': (-3, 3),
            '2': (-41, -38), '3': (-73, -69), '4': (-82, -77),
            '5': (79, 999), '6': (79, 999), '7': (79, 999),
            '9': (-41, -38), '10': (-73, -69), '11': (-82, -77),
        }
        self.SPECIAL_CAM1_SCREENS = {'6L', '6', '10L', '10'}
        self.SPECIAL_CAM8_SCREENS = {'13L', '13', '3L', '3'}
      
        self.POSE_CONNECTIONS = [
            (5, 6), (5, 7), (6, 8), (7, 9), (8, 10),
            (11, 12), (11, 13), (12, 14), (13, 15), (14, 16),
            (5, 11), (6, 12)
        ]

        self.TARGET_MAPPING = {
            '2R': 'target-2',
            '2L': 'target-3',
            '3R': 'target-3',
            '3L': 'target-4',
            '4R': 'target-4',
            '5L': 'target-5',
            '6R': 'target-5',
            '6L': 'target-6',
            '7R': 'target-6',
            '7L': 'target-7',
            '9R': 'target-9',
            '9L': 'target-10',
            '10R': 'target-10',
            '10L': 'target-11',
            '11R': 'target-11',
            '12L': 'target-12',
            '13R': 'target-12',
            '13L': 'target-13',
            '14R': 'target-13',
            '14L': 'target-14'
        }

        self.load_json_files()
        self.filter_actions_by_duration()
        self.cap = cv2.VideoCapture(video_path)
        if not self.cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.half_width = self.width // 2
        self.load_yolo_models()
        self.load_face_model()
        self.action_validation = {}
        self.goals_scored = defaultdict(int)
        self.last_valid_kp = {}
        self.kp_ema = {}
        self.yaw_filter = None
        self.prev_timestamp = 0.0
        self.last_display_yaw = None
        self.frames_without_face = 0
        self.MAX_HOLD_FRAMES = 15
        self.yaw_direction_votes = []
        self.aware_detected_per_action = [False] * len(self.actions)
        self.seen_positive = [False] * len(self.actions)
        self.seen_negative = [False] * len(self.actions)
        self.ball_tracks_per_action = []
        self.trusted_tracks_per_action = []
        self.fake_tracks_per_action = []
        self.target_ball_distances = [[] for _ in self.actions]
        self.rejected_actions = []
        self.finishing_times = [None] * len(self.actions)
        self.yaw_history_per_action = [[] for _ in self.actions]
        self.prepare_actions()
        print(f"Video: {video_path}")
        print(f"Frames: {self.total_frames:,}")
        print(f"FPS: {self.fps:.2f}")
        print(f"Resolution: {self.width}×{self.height}")
        print(f"Actions loaded: {len(self.actions)}")
        print(f"\nThresholds:")
        print(f" PASS - Crossed: {self.PASS_CROSSED_DISTANCE}px, Accepted: {self.PASS_ACCEPTED_DISTANCE}px")
        print(f" TARGET - Crossed: {self.TARGET_CROSSED_DISTANCE}px, Accepted: {self.TARGET_ACCEPTED_DISTANCE}px")
        print(f" PRESS/SPRINT - Crossed: {self.DIST_GOAL_CROSSED_DEFAULT}px, Accepted: {self.DIST_GOAL_ACCEPTED_DEFAULT}px")

    def draw_player_boxes_and_face_landmarks(self, frame, person_boxes, best_face):
        """Draw player bounding boxes and face landmarks"""
        frame_copy = frame.copy()
        
        # Draw all detected player bounding boxes
        if person_boxes is not None and len(person_boxes) > 0:
            for i, box in enumerate(person_boxes):
                if len(box) >= 4:
                    x1, y1, x2, y2 = map(int, box[:4])
                    # Different color for largest player (assumed main player)
                    if i == 0:
                        color = (0, 255, 0)
                        thickness = 3
                        cv2.putText(frame_copy, "MAIN PLAYER", (x1, y1-10), 
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                    else:
                        color = (0, 255, 255)
                        thickness = 2
                    cv2.rectangle(frame_copy, (x1, y1), (x2, y2), color, thickness)
        
        # Draw face landmarks if face detected
        if best_face is not None:
            # Get face bounding box
            bbox = best_face.bbox
            if bbox is not None:
                x1, y1, x2, y2 = map(int, bbox)
                cv2.rectangle(frame_copy, (x1, y1), (x2, y2), (255, 255, 0), 2)
                cv2.putText(frame_copy, "FACE", (x1, y1-5), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)
            
            # Draw 5-point landmarks
            landmarks = best_face.landmark_2d_106
            if landmarks is not None:
                for i, (x, y) in enumerate(landmarks[:5]):
                    if 0 <= x < frame.shape[1] and 0 <= y < frame.shape[0]:
                        if i == 0:
                            cv2.circle(frame_copy, (int(x), int(y)), 5, (0, 255, 0), -1)
                            cv2.putText(frame_copy, "RE", (int(x)+5, int(y)), 
                                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
                        elif i == 1:
                            cv2.circle(frame_copy, (int(x), int(y)), 5, (0, 255, 0), -1)
                            cv2.putText(frame_copy, "LE", (int(x)+5, int(y)), 
                                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
                        elif i == 2:
                            cv2.circle(frame_copy, (int(x), int(y)), 5, (0, 0, 255), -1)
                            cv2.putText(frame_copy, "N", (int(x)+5, int(y)), 
                                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
                        elif i == 3:
                            cv2.circle(frame_copy, (int(x), int(y)), 5, (255, 0, 0), -1)
                            cv2.putText(frame_copy, "LM", (int(x)+5, int(y)), 
                                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 0), 1)
                        elif i == 4:
                            cv2.circle(frame_copy, (int(x), int(y)), 5, (255, 0, 0), -1)
                            cv2.putText(frame_copy, "RM", (int(x)+5, int(y)), 
                                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 0), 1)
            
            # Draw yaw direction arrow
            if bbox is not None:
                center_x = int((bbox[0] + bbox[2]) / 2)
                center_y = int((bbox[1] + bbox[3]) / 2)
                yaw_rad = math.radians(best_face.pose[1])
                arrow_end_x = int(center_x + 50 * math.cos(yaw_rad))
                arrow_end_y = int(center_y + 50 * math.sin(yaw_rad))
                cv2.arrowedLine(frame_copy, (center_x, center_y), (arrow_end_x, arrow_end_y), 
                               (255, 100, 0), 3, tipLength=0.3)
                cv2.putText(frame_copy, f"YAW: {int(best_face.pose[1])} deg", 
                           (center_x-40, center_y-15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 100, 0), 2)
        
        return frame_copy

    def draw_pose_skeleton(self, frame):
        if self.pose_model is None:
            return frame
        try:
            pose_results = self.pose_model(frame, verbose=False, conf=0.3)
            for result in pose_results:
                if result.keypoints is None: continue
                keypoints = result.keypoints.xy.cpu().numpy()
                confidences = result.keypoints.conf.cpu().numpy() if result.keypoints.conf is not None else np.ones((len(keypoints), 17))
                if len(keypoints) == 0: continue
                for person_idx, kpts in enumerate(keypoints):
                    if len(kpts) < 17: continue
                    for connection in self.POSE_CONNECTIONS:
                        start_idx, end_idx = connection
                        if start_idx < len(kpts) and end_idx < len(kpts):
                            start_point = tuple(map(int, kpts[start_idx][:2]))
                            end_point = tuple(map(int, kpts[end_idx][:2]))
                            start_conf = confidences[person_idx][start_idx] if len(confidences) > person_idx and start_idx < len(confidences[person_idx]) else 0
                            end_conf = confidences[person_idx][end_idx] if len(confidences) > person_idx and end_idx < len(confidences[person_idx]) else 0
                            if start_conf > 0.3 and end_conf > 0.3 and start_point[0] > 0 and start_point[1] > 0 and end_point[0] > 0 and end_point[1] > 0:
                                cv2.line(frame, start_point, end_point, (0, 255, 0), 3, cv2.LINE_AA)
                    for i, kp in enumerate(kpts):
                        x, y = int(kp[0]), int(kp[1])
                        conf = confidences[person_idx][i] if len(confidences) > person_idx and i < len(confidences[person_idx]) else 0
                        if conf > 0.4 and x > 0 and y > 0:
                            if i in [5, 6, 11, 12]:
                                color = (255, 0, 0)
                            elif i in [7, 8, 9, 10]:
                                color = (0, 255, 255)
                            elif i in [13, 14, 15, 16]:
                                color = (255, 255, 0)
                            else:
                                color = (255, 0, 255)
                            cv2.circle(frame, (x, y), 5, color, -1, cv2.LINE_AA)
                            cv2.circle(frame, (x, y), 7, (255, 255, 255), 1, cv2.LINE_AA)
        except Exception:
            pass
        return frame

    def determine_action_orientation_from_results(self, action_idx, action):
        val = self.action_validation[action_idx]
        ft = val.get('finishing_type')
        if ft not in ['CORRECT', 'LATE']:
            val['action_orientation'] = "-"
            return
        screens = self.parse_screens(action)
        if len(screens) != 2:
            val['action_orientation'] = "-"
            return
        finishing_screen = val.get('goal_screen')
        if not finishing_screen:
            val['action_orientation'] = "-"
            return
        finishing_screen = str(finishing_screen).strip().upper()
        base_finish = ''.join(c for c in finishing_screen if c.isdigit())
        yaw_list = self.yaw_history_per_action[action_idx]
        if not yaw_list:
            val['action_orientation'] = "-"
            return
        INITIAL_FRAMES_TO_CHECK = 20
        FACING_THRESHOLD = 0.30
        initial_yaw_list = yaw_list[:INITIAL_FRAMES_TO_CHECK]
        facing_count = sum(1 for yaw in initial_yaw_list if -60 <= yaw <= 60)
        total_initial = len(initial_yaw_list)
        facing_ratio = facing_count / total_initial if total_initial > 0 else 0
        facing_camera = facing_ratio >= FACING_THRESHOLD
        player_in_cam1 = base_finish in ['2', '3', '4', '12', '13', '14']
        if player_in_cam1:
            right_side_screens = {'2', '3', '4'} if facing_camera else {'12', '13', '14'}
            left_side_screens = {'12', '13', '14'} if facing_camera else {'2', '3', '4'}
        else:
            right_side_screens = {'9', '10', '11'} if facing_camera else {'5', '6', '7'}
            left_side_screens = {'5', '6', '7'} if facing_camera else {'9', '10', '11'}
        if base_finish in right_side_screens:
            val['action_orientation'] = "Action Right Oriented"
        elif base_finish in left_side_screens:
            val['action_orientation'] = "Action Left Oriented"
        else:
            val['action_orientation'] = "Action Mixed Orientation"
        print(f"\n{'='*60}")
        print(f"ACTION {action_idx} ORIENTATION ANALYSIS")
        print(f"{'='*60}")
        print(f"Block: {action.get('block_id', '—')}")
        print(f"Finishing Screen: {finishing_screen} (Base: {base_finish})")
        print(f"Facing Camera: {'YES' if facing_camera else 'NO'}")
        print(f"Action Orientation: {val['action_orientation']}")
        print(f"{'='*60}\n")

    def is_goal_action(self, action):
        act_type = action.get('action', '').strip().upper()
        if act_type == 'GOAL':
            return True
        target_screens = self.get_target_screens(action)
        for s in target_screens:
            base = self.extract_screen_base(s)
            if base in {'7', '9'}:
                return True
        return False

    def filter_actions_by_duration(self):
        if not self.actions: return
        durations = []
        for act in self.actions:
            start_time = act.get('start_time', '')
            end_time = act.get('end_time', '')
            if start_time and end_time:
                duration = self.time_to_seconds(end_time) - self.time_to_seconds(start_time)
                durations.append(duration)
                act['duration_seconds'] = duration
            else:
                act['duration_seconds'] = 0
        valid_durations = [d for d in durations if d > 0]
        if not valid_durations: return
        avg_duration = sum(valid_durations) / len(valid_durations)
        min_required_duration = avg_duration * (self.min_duration_percentage / 100.0)
        filtered_actions = []
        rejected_indices = []
        for i, act in enumerate(self.actions):
            duration = act.get('duration_seconds', 0)
            block_id = act.get('block_id', '?')
            is_first_block = (block_id == 'A1' or (i == 0 and 'A1' in block_id))
            is_last_block = (i == len(self.actions) - 1)
            if (is_first_block or is_last_block) and duration < min_required_duration:
                rejected_indices.append(i)
                continue
            filtered_actions.append(act)
        self.rejected_actions = rejected_indices
        self.actions = filtered_actions

    def load_face_model(self):
        print("Loading InsightFace buffalo_l model...")
        try:
            import onnxruntime as ort
            providers = ['CUDAExecutionProvider', 'CPUExecutionProvider'] if 'CUDAExecutionProvider' in ort.get_available_providers() else ['CPUExecutionProvider']
            self.face_app = FaceAnalysis(name='buffalo_l', providers=providers)
            self.face_app.prepare(ctx_id=0 if 'CUDAExecutionProvider' in providers else -1, det_size=(320, 320))
            print("InsightFace loaded.")
        except Exception as e:
            print(f"Face model load error: {e}")
            self.face_app = None

    def load_yolo_models(self):
        print("\n" + "="*50)
        print("LOADING YOLO MODELS")
        print("="*50)
        try:
            self.detection_model = YOLO(self.yolo_ball_model_path)
            if torch.cuda.is_available():
                self.detection_model.to('cuda')
            print(f"Ball model loaded from: {self.yolo_ball_model_path}")
        except Exception as e:
            print(f"Failed to load ball model: {e}")
            self.detection_model = None
        try:
            self.person_model_for_yaw = YOLO(self.yolo_pose_model_path)
            if torch.cuda.is_available():
                self.person_model_for_yaw.to('cuda')
            print(f"Person model for yaw loaded from: {self.yolo_pose_model_path}")
        except:
            self.person_model_for_yaw = self.detection_model
        try:
            self.goal_model = YOLO(self.yolo_screen_model_path)
            if torch.cuda.is_available():
                self.goal_model.to('cuda')
            print(f"Goal model loaded from: {self.yolo_screen_model_path}")
        except Exception as e:
            print(f"Failed to load goal model: {e}")
            self.goal_model = None
        try:
            self.pose_model = YOLO(self.yolo_pose_model_path)
            if torch.cuda.is_available():
                self.pose_model.to('cuda')
            print(f"Pose model loaded from: {self.yolo_pose_model_path}")
        except Exception as e:
            print(f"Failed to load pose model: {e}")
            self.pose_model = None
        self.SCREEN_COLORS = {
            '10': (255,0,0), '11': (0,255,0), '12': (0,0,255), '13': (255,255,0),
            '14': (255,0,255), '2': (0,255,255), '3': (255,128,0), '4': (128,0,255),
            '5': (0,128,255), '6': (255,0,128), '7': (128,255,0), '9': (0,255,128)
        }
        print("="*50)

    def load_json_files(self):
        with open(self.timestamps_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            self.timestamps = data
        else:
            self.timestamps = data.get('timestamps', [])
        with open(self.qr_file, 'r', encoding='utf-8') as f:
            qr_data = json.load(f)
        self.actions = qr_data.get('analysis', [])
        for i, act in enumerate(self.actions):
            if 'block_id' not in act or not act['block_id'] or act['block_id'] == '???':
                self.actions[i]['block_id'] = f"Block_{i+1}"
            if 'action' not in act or not act['action'] or act['action'] == '???':
                self.actions[i]['action'] = 'UNKNOWN'
            if 'screens_index' not in act:
                self.actions[i]['screens_index'] = []
            if 'start_time' not in act or not act['start_time']:
                self.actions[i]['start_time'] = '00:00:00.000'
            if 'end_time' not in act or not act['end_time']:
                self.actions[i]['end_time'] = '00:00:00.000'

    def time_to_seconds(self, tstr):
        if not tstr: return 0.0
        if ' ' in tstr: tstr = tstr.split(' ', 1)[1]
        try:
            h, m, s_ms = tstr.split(':')
            s, ms = (s_ms.split('.') + ['0'])[:2]
            return int(h)*3600 + int(m)*60 + int(s) + int(ms.ljust(3,'0'))/1000.0
        except:
            return 0.0

    def find_frame_for_time(self, timestr, shift=0):
        target = self.time_to_seconds(timestr)
        best_i, best_diff = 0, float('inf')
        for i, ts in enumerate(self.timestamps):
            diff = abs(self.time_to_seconds(ts) - target)
            if diff < best_diff:
                best_diff = diff
                best_i = i
        return max(0, min(best_i + shift, len(self.timestamps)-1))

    def parse_screens(self, action):
        raw = action.get('screens_index', [])
        if not raw: return []
        if isinstance(raw, str):
            items = [s.strip() for s in raw.split(',') if s.strip()]
        elif isinstance(raw, list):
            items = []
            for item in raw:
                if isinstance(item, str):
                    items.extend(s.strip() for s in item.split(',') if s.strip())
                else:
                    items.append(str(item).strip())
        else:
            items = [str(raw).strip()]
        return [s for s in items if s]

    def get_target_screens(self, action):
        return set(self.parse_screens(action))

    def extract_screen_base(self, s: str) -> str:
        s = str(s).strip().upper()
        base = ''.join(c for c in s if c.isdigit())
        return base if base else s

    def is_screen_match(self, detected_screen, allowed_screens, action_type):
        detected_upper = detected_screen.strip().upper()
        for allowed in allowed_screens:
            allowed_upper = str(allowed).strip().upper()
            if action_type == 'PASS':
                if detected_upper == allowed_upper:
                    return True
            elif action_type == 'GOAL':
                if self.extract_screen_base(detected_upper) == self.extract_screen_base(allowed_upper):
                    return True
            else:
                if self.extract_screen_base(detected_upper) == self.extract_screen_base(allowed_upper):
                    return True
        return False

    def calculate_distance_to_line(self, point, p1, p2):
        x0, y0 = point
        x1, y1 = p1
        x2, y2 = p2
        vx, vy = x2 - x1, y2 - y1
        len2 = vx*vx + vy*vy
        if len2 < 1e-6:
            return float('inf'), float('inf'), float('inf'), 0.0, 0.0
        proj_t = ((x0 - x1) * vx + (y0 - y1) * vy) / len2
        t = max(0, min(1, proj_t))
        projx = x1 + t * vx
        projy = y1 + t * vy
        dist = math.sqrt((x0 - projx)**2 + (y0 - projy)**2)
        dist_left = math.sqrt((x0 - x1)**2 + (y0 - y1)**2)
        dist_right = math.sqrt((x0 - x2)**2 + (y0 - y2)**2)
        signed = ((x2 - x1) * (y0 - y1) - (y2 - y1) * (x0 - x1)) / math.sqrt(len2 + 1e-9)
        return dist, dist_left, dist_right, proj_t, signed

    def is_point_between_posts(self, proj_t):
        return -self.PASS_HORIZONTAL_TOLERANCE <= proj_t <= 1 + self.PASS_HORIZONTAL_TOLERANCE

    def is_position_near_goal(self, cx, cy, kp_dict):
        for screen_name, (kp_right, kp_left) in kp_dict.items():
            if kp_left is None or kp_right is None: continue
            dist, _, _, proj_t, _ = self.calculate_distance_to_line((cx, cy), kp_left, kp_right)
            if dist < self.GOAL_NEAR_DISTANCE_PX and -0.2 <= proj_t <= 1.2:
                return True
        return False

    def extract_target_type(self, target_str):
        target_str = str(target_str).strip().upper()
        if not target_str:
            return '', '', ''
        
        if target_str.endswith('L'):
            base = target_str[:-1]
            side = 'L'
            side_name = 'left'
        elif target_str.endswith('R'):
            base = target_str[:-1]
            side = 'R'
            side_name = 'right'
        else:
            base = target_str
            side = ''
            side_name = ''
        
        return base, side, side_name

    def prepare_actions(self):
        print("\nPreparing actions...")
        self.ball_tracks_per_action = [defaultdict(list) for _ in self.actions]
        self.trusted_tracks_per_action = [set() for _ in self.actions]
        self.fake_tracks_per_action = [set() for _ in self.actions]
        self.target_ball_distances = [[] for _ in self.actions]
        self.yaw_history_per_action = [[] for _ in self.actions]
        self.action_times = [None] * len(self.actions)
        FRAME_OFFSET = self.frame_offset
        print(f"Applying frame offset: {FRAME_OFFSET} frames")
      
        for i, act in enumerate(self.actions):
            self.action_validation[i] = {
                'goal_detected': False, 'finishing_type': None, 'goal_screen': None,
                'is_correct_screen': False, 'is_correct_side': True, 'is_late': False,
                'strong_cross': False, 'vision_orientation': "-", 'action_orientation': "-",
                'proj_t': None, 'fake_static_ignored': False, 'target_side': None
            }
            self.yaw_direction_votes.append({'left': 0, 'right': 0})
            self.seen_positive[i] = False
            self.seen_negative[i] = False
          
            original_sf = self.find_frame_for_time(act.get('start_time', ''), shift=1)
            original_ef = self.find_frame_for_time(act.get('end_time', ''), shift=1)
          
            start_seconds = self.time_to_seconds(act.get('start_time', ''))
            end_seconds = self.time_to_seconds(act.get('end_time', ''))
            action_duration = end_seconds - start_seconds
            self.action_times[i] = round(action_duration, 3) if action_duration > 0 else 0.0
            self.action_validation[i]['action_time'] = self.action_times[i]
          
            sf = original_sf + FRAME_OFFSET
            ef = original_ef + FRAME_OFFSET
            if sf >= self.total_frames: sf = self.total_frames - 1
            if ef >= self.total_frames: ef = self.total_frames - 1
            if ef < sf: ef = sf
          
            act['original_start_frame'] = original_sf
            act['original_end_frame'] = original_ef
            act['original_start_time'] = act.get('start_time', '')
            act['original_end_time'] = act.get('end_time', '')
            act['start_frame'] = sf
            act['end_frame'] = ef
            act['total_frames'] = ef - sf + 1
          
            if self.timestamps and sf < len(self.timestamps):
                act['adjusted_start_time'] = self.timestamps[sf]
            if self.timestamps and ef < len(self.timestamps):
                act['adjusted_end_time'] = self.timestamps[ef]

    def classify_ball_tracks(self, action_idx, kp_history):
        action = self.actions[action_idx]
        act_type = action.get('action', '').upper()
        if act_type in ['TARGET', 'GOAL', 'PRESS', 'SPRINT']:
            return set(), set(self.ball_tracks_per_action[action_idx].keys())
        tracks = self.ball_tracks_per_action[action_idx]
        if not tracks:
            return set(), set()
        fakes = set()
        trusted = set()
        has_real_movement = False
        stable_kp = {}
        for screen, entries in kp_history.items():
            if entries:
                stable_kp[screen] = entries[-1][1]
        for track_id, positions in tracks.items():
            if len(positions) < self.MIN_FRAMES_TO_CONSIDER: continue
            xs = [p[1] for p in positions]
            ys = [p[2] for p in positions]
            total_disp = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
            steps = len(positions) - 1
            avg_speed = total_disp / steps if steps > 0 else 0.0
            near_goal_count = sum(1 for _, cx, cy, _ in positions if self.is_position_near_goal(cx, cy, stable_kp))
            ratio_near = near_goal_count / len(positions)
            is_suspicious_static = (total_disp < self.MIN_DISPLACEMENT_PX and
                                    avg_speed < self.MIN_AVG_SPEED_PX_PER_FRAME and
                                    ratio_near > self.MAX_STATIC_NEAR_GOAL_RATIO)
            if is_suspicious_static:
                fakes.add(track_id)
            else:
                trusted.add(track_id)
                if total_disp > 80 or avg_speed > 5.0:
                    has_real_movement = True
        if not has_real_movement and trusted:
            fakes.update(trusted)
            trusted.clear()
        return fakes, trusted

    def print_block_conclusion(self, action_idx, action):
        act_type = action.get('action', '').upper()
        if act_type not in ['PASS', 'TARGET', 'PRESS', 'SPRINT', 'GOAL']:
            return
        v = self.action_validation.get(action_idx, {})
        bid = action.get('block_id', '—')
        finishing_type = v.get('finishing_type', 'NO_GOAL')
        screen = v.get('goal_screen', '—')
        distance = v.get('distance', '—')
        strong = v.get('strong_cross', False)
        is_late = v.get('is_late', False)
        proj_t = v.get('proj_t', '—')
        target_side = v.get('target_side', '—')
        
        if finishing_type == 'NO_GOAL':
            finishing_type = 'WRONG'
            self.action_validation[action_idx]['finishing_type'] = 'WRONG'
        
        status = "YES" if finishing_type in ["CORRECT", "LATE"] else "NO"
        late_str = " (Late)" if is_late and status == "YES" else ""
        strong_str = " STRONG" if strong else ""
        proj_str = f" | proj_t: {proj_t}" if proj_t != '—' else ""
        fake_str = " (fake ignored)" if v.get('fake_static_ignored') else ""
        side_str = f" | Side: {target_side}" if target_side != '—' else ""
        
        if act_type in ['PASS', 'TARGET', 'PRESS', 'SPRINT', 'GOAL'] and finishing_type == 'NO_GOAL':
            finishing_type = 'WRONG'
            self.action_validation[action_idx]['finishing_type'] = 'WRONG'
        
        if act_type == 'TARGET':
            distances = self.target_ball_distances[action_idx]
            if distances:
                best_left = min([d for d in distances if d.get('x_diff_left', 0) < 0], key=lambda d: d['dist_to_left']) if any(d.get('x_diff_left', 0) < 0 for d in distances) else None
                best_right = min([d for d in distances if d.get('x_diff_right', 0) > 0], key=lambda d: d['dist_to_right']) if any(d.get('x_diff_right', 0) > 0 for d in distances) else None
                
                if best_left:
                    print(f"END OF TARGET ACTION {action_idx} | Best LEFT side: dist_to_left={best_left['dist_to_left']:.1f}px | x_diff={best_left['x_diff_left']:.1f} | frame={best_left['frame']}")
                if best_right:
                    print(f"END OF TARGET ACTION {action_idx} | Best RIGHT side: dist_to_right={best_right['dist_to_right']:.1f}px | x_diff={best_right['x_diff_right']:.1f} | frame={best_right['frame']}")
            else:
                print(f"END OF TARGET ACTION {action_idx} | No valid balls collected")
        
        conclusion = f"[Conclusion for {bid} ({act_type})] -> Correct finishing: {status}{late_str} | Screen: {screen} | Distance: {distance}{proj_str}{side_str} |{strong_str}{fake_str}"
        print(conclusion)
    
    def create_intro_frame(self):
        frame = np.zeros((self.height, self.width, 3), np.uint8)
        font = cv2.FONT_HERSHEY_SIMPLEX
        y = self.height // 2 - 140
        pass_val = getattr(self, 'PASS_ACCEPTED_DISTANCE', 15)
        target_val = getattr(self, 'TARGET_ACCEPTED_DISTANCE', 150)
        press_val = getattr(self, 'DIST_GOAL_ACCEPTED_DEFAULT', 180)
        cv2.putText(frame, "BLOCK ID PROCESSOR", (self.width//2 - 400, y), font, 2.5, (0,255,255), 6)
        y += 80
        cv2.putText(frame, "PASS/GOAL: " + str(pass_val) + "px", (self.width//2 - 300, y), font, 1.2, (200,255,200), 2)
        y += 40
        cv2.putText(frame, "TARGET: Side offset " + str(target_val) + "px", (self.width//2 - 400, y), font, 1.2, (200,255,200), 2)
        y += 40
        cv2.putText(frame, "PRESS/SPRINT: Player distance " + str(press_val) + "px", (self.width//2 - 420, y), font, 1.2, (200,255,200), 2)
        return frame

    def create_outro_frame(self):
        frame = np.zeros((self.height, self.width, 3), np.uint8)
        font = cv2.FONT_HERSHEY_SIMPLEX
        y = self.height // 2 - 160
        cv2.putText(frame, "PROCESSING FINISHED", (self.width//2 - 360, y), font, 2.4, (0,255,120), 6)
        y += 120
        total = sum(self.goals_scored.values())
        cv2.putText(frame, "Total strong goals: " + str(total), (self.width//2 - 280, y), font, 1.6, (255,220,100), 4)
        return frame

    def create_transition_frame(self, action, next_action=None):
        frame = np.zeros((self.height, self.width, 3), np.uint8)
        font = cv2.FONT_HERSHEY_SIMPLEX
        y = self.height // 2 - 160
        idx = self.actions.index(action)
        val = self.action_validation.get(idx, {})
        ft = val.get('finishing_type', '-')
        act_type = action.get('action', 'UNKNOWN').upper()
        bid = str(action.get('block_id') or '?')
        if act_type in ['PASS', 'TARGET', 'PRESS', 'SPRINT', 'GOAL']:
            if ft == "CORRECT":
                if act_type == 'GOAL':
                    text, col = "GOAL SCORED", (0,255,0)
                elif act_type in ['PRESS', 'SPRINT']:
                    text, col = act_type + " CORRECT", (0,255,0)
                else:
                    text, col = "CORRECT FINISHING", (0,255,0)
            elif ft == "LATE":
                if act_type == 'GOAL':
                    text, col = "LATE GOAL", (0,165,255)
                elif act_type in ['PRESS', 'SPRINT']:
                    text, col = "LATE " + act_type, (0,165,255)
                else:
                    text, col = "LATE FINISHING", (0,165,255)
            elif ft == "WRONG":
                text, col = "WRONG FINISHING", (0,0,255)
            else:
                text, col = "WRONG FINISHING", (0,0,255)
        else:
            text = act_type + " BLOCK COMPLETE"
            col = (0,255,180)
        w = len(text) * 15
        cv2.putText(frame, text, (self.width//2 - w//2, y), font, 2.2, col, 6)
        y += 100
        screens_raw = action.get('screens_index', [])
        screens_str = ', '.join(str(s) for s in screens_raw) if screens_raw else "-"
        cv2.putText(frame, "Block " + bid + " . " + act_type, (self.width//2 - 280, y), font, 1.4, (255,255,255), 3)
        y += 60
        cv2.putText(frame, "Screens: " + screens_str, (self.width//2 - 300, y), font, 1.2, (220,220,255), 2)
        y += 80
        if idx < len(self.aware_detected_per_action) and self.aware_detected_per_action[idx]:
            cv2.putText(frame, "Aware", (self.width//2 - 100, y), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (0, 220, 0), 5)
        vision = val.get('vision_orientation', '-')
        if vision != '-':
            col = (0, 200, 255) if "Right" in vision else (255, 160, 0)
            cv2.putText(frame, vision, (self.width//2 - 180, y + 60), cv2.FONT_HERSHEY_SIMPLEX, 1.6, col, 4)
        action_ori = val.get('action_orientation', '-')
        if action_ori != '-':
            col = (0, 180, 255) if "Right" in action_ori else (255, 140, 0)
            cv2.putText(frame, action_ori, (self.width//2 - 220, y + 120), cv2.FONT_HERSHEY_SIMPLEX, 1.5, col, 4)
        finish_time = val.get('finishing_time', None)
        if finish_time is not None:
            cv2.putText(frame, "Time: " + format(finish_time, '.3f') + "s", (self.width//2 - 120, y + 180), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255,255,100), 2)
        if next_action:
            y += 100
            nbid = str(next_action.get('block_id', '?'))
            nact = next_action.get('action', 'UNKNOWN')
            text = "NEXT: Block " + nbid + " . " + nact
            w = len(text) * 13
            cv2.putText(frame, text, (self.width//2 - w//2, y), font, 1.3, (255,255,220), 2)
        return frame

    def detect_goals_in_frame(self, frame, action, action_idx, local_frame_idx, kp_history):
        frame_copy = frame.copy()
        correct_this = False
        wrong_this = False
        global_frame = action.get('start_frame', 0) + local_frame_idx - 1
        end_frame = action.get('end_frame', 0)
        is_late = global_frame > end_frame
        act_type = action.get('action', '').strip().upper()
        player_in_cam1 = False

        person_results = None
        person_boxes = np.array([])
        best_face = None
        
        try:
            person_results = self.person_model_for_yaw(frame_copy, conf=0.35, verbose=False)
            if person_results and len(person_results) > 0 and person_results[0].boxes is not None:
                boxes = person_results[0].boxes.xyxy.cpu().numpy()
                if len(boxes) > 0:
                    person_boxes = boxes[~np.any(np.isnan(boxes), axis=1)]
                    if len(person_boxes) > 0:
                        areas = (person_boxes[:,2]-person_boxes[:,0]) * (person_boxes[:,3]-person_boxes[:,1])
                        sorted_indices = np.argsort(areas)[::-1]
                        person_boxes = person_boxes[sorted_indices]
                        
                        best_box = person_boxes[0]
                        px = (best_box[0] + best_box[2]) / 2
                        player_in_cam1 = px < self.half_width
        except Exception as e:
            print(f"Person detection error: {e}")

        balls = []
        if act_type in ['PASS', 'TARGET', 'GOAL'] and self.detection_model:
            try:
                with torch.amp.autocast('cuda', enabled=torch.cuda.is_available()):
                    dets = self.detection_model(frame_copy, verbose=False, conf=self.BALL_MODEL_CONF)
                for r in dets:
                    if r.boxes is None: continue
                    for box in r.boxes:
                        if int(box.cls) != 0: continue
                        xyxy = box.xyxy[0].cpu().numpy()
                        if np.any(np.isnan(xyxy)): continue
                        x1, y1, x2, y2 = map(int, xyxy)
                        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                        conf = float(box.conf)
                        if conf < self.BALL_POST_CONF: continue
                        balls.append(((cx, cy), conf, (x1, y1, x2, y2)))
                        cv2.rectangle(frame_copy, (x1, y1), (x2, y2), (255, 0, 0), 2)
            except Exception as e:
                print(f"Ball detection error: {e}")

        current_tracks = self.ball_tracks_per_action[action_idx]
        ball_assignments = {}
        if act_type in ['PASS', 'TARGET', 'GOAL'] and balls:
            for ball_data in balls:
                (cx, cy), conf, _ = ball_data
                best_match_id = None
                best_dist = float('inf')
                for track_id, positions in current_tracks.items():
                    if not positions: continue
                    _, last_cx, last_cy, _ = positions[-1]
                    dist = math.hypot(cx - last_cx, cy - last_cy)
                    if dist < best_dist and dist < 90:
                        best_dist = dist
                        best_match_id = track_id
                track_id = best_match_id if best_match_id is not None else f"t{len(current_tracks) + 1}"
                current_tracks[track_id].append((local_frame_idx, cx, cy, conf))
                ball_assignments[(cx, cy)] = track_id

        active_kp_dict = {}

        if act_type in ['PASS', 'TARGET', 'PRESS', 'SPRINT', 'GOAL'] and self.goal_model:
            allowed_screens = self.get_target_screens(action)
            
            allowed_screen_strings = [str(s).strip() for s in allowed_screens if s]
           
            if act_type == 'TARGET':
                for raw_target in self.parse_screens(action):
                    if raw_target:
                        allowed_screen_strings.append(str(raw_target).strip())
            elif act_type == 'GOAL':
                for screen in self.parse_screens(action):
                    if screen:
                        allowed_screen_strings.append(str(screen).strip())
            
            allowed_screen_strings = list(dict.fromkeys(allowed_screen_strings))
           
            try:
                with torch.amp.autocast('cuda', enabled=torch.cuda.is_available()):
                    screen_dets = self.goal_model(frame_copy, verbose=False, conf=self.GOAL_MODEL_CONF)
                
                for r in screen_dets:
                    if r.boxes is None: continue
                    for i_box, box in enumerate(r.boxes):
                        cls = int(box.cls)
                        if cls not in self.goal_model.names: continue
                        xyxy = box.xyxy[0].cpu().numpy()
                        if np.any(np.isnan(xyxy)): continue
                        screen_name = str(self.goal_model.names[cls]).strip()
                        
                        is_target_keypoint = 'target-' in screen_name.lower()
                        
                        if act_type == 'TARGET':
                            if not is_target_keypoint:
                                continue
                            is_allowed = self.is_screen_match(screen_name, allowed_screen_strings, act_type)
                        elif act_type in ['PRESS', 'SPRINT']:
                            if is_target_keypoint:
                                continue
                            if len(allowed_screen_strings) == 0:
                                is_allowed = True
                            else:
                                is_allowed = self.is_screen_match(screen_name, allowed_screen_strings, act_type)
                        else:
                            is_allowed = self.is_screen_match(screen_name, allowed_screen_strings, act_type)
                        
                        x1, y1, x2, y2 = map(int, xyxy)
                        screen_name_base = self.extract_screen_base(screen_name)
                        color = self.SCREEN_COLORS.get(screen_name_base, (200,200,200))
                        
                        if act_type == 'TARGET' and is_target_keypoint:
                            is_expected_target = False
                            expected_target_name = None
                            
                            for tgt in allowed_screen_strings:
                                tgt_str = str(tgt).strip().upper()
                                if tgt_str in self.TARGET_MAPPING:
                                    expected_target = self.TARGET_MAPPING[tgt_str]
                                    if screen_name == expected_target:
                                        is_expected_target = True
                                        expected_target_name = expected_target
                                        break
                            
                            if not is_expected_target:
                                continue
                            
                            thickness = 4
                            font_scale = 0.7
                            cv2.rectangle(frame_copy, (x1,y1), (x2,y2), (0, 255, 255), thickness)
                            cv2.putText(frame_copy, "TARGET: " + screen_name, (x1, y1-10), 
                                       cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 255, 255), 2)
                            cv2.circle(frame_copy, ((x1+x2)//2, (y1+y2)//2), 15, (0, 255, 255), -1)
                            draw_keypoints = True
                        else:
                            if is_allowed:
                                thickness = 4
                                font_scale = 0.7
                                draw_keypoints = True
                                cv2.rectangle(frame_copy, (x1,y1), (x2,y2), color, thickness)
                                cv2.putText(frame_copy, screen_name, (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, 2)
                            else:
                                thickness = 1
                                font_scale = 0.5
                                draw_keypoints = False
                                cv2.rectangle(frame_copy, (x1,y1), (x2,y2), color, thickness)
                                cv2.putText(frame_copy, screen_name, (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, 1)
                                continue
                        
                        if not draw_keypoints:
                            continue
                            
                        if r.keypoints is None or i_box >= len(r.keypoints.xy): continue
                        kps_xy = r.keypoints.xy[i_box].cpu().numpy()
                        if np.any(np.isnan(kps_xy)): continue
                        kp_conf_mean = 0.0
                        if hasattr(r.keypoints, 'conf') and r.keypoints.conf is not None:
                            kp_conf = r.keypoints.conf[i_box].cpu().numpy()
                            if len(kp_conf) >= 2 and not np.any(np.isnan(kp_conf)):
                                kp_conf_mean = np.mean(kp_conf[:2])
                        kp_right = kp_left = None
                        use_persisted = False
                        if len(kps_xy) >= 2 and np.all(kps_xy[0] > 0) and np.all(kps_xy[1] > 0) and kp_conf_mean >= self.KEYPOINT_MIN_CONF:
                            kp_right_new = tuple(map(int, kps_xy[0]))
                            kp_left_new = tuple(map(int, kps_xy[1]))
                            if screen_name_base in self.kp_ema:
                                pr, pl = self.kp_ema[screen_name_base]
                                kp_right = tuple(int(self.EMA_ALPHA * a + (1-self.EMA_ALPHA)*b) for a,b in zip(kp_right_new, pr))
                                kp_left = tuple(int(self.EMA_ALPHA * a + (1-self.EMA_ALPHA)*b) for a,b in zip(kp_left_new, pl))
                            else:
                                kp_right, kp_left = kp_right_new, kp_left_new
                            self.kp_ema[screen_name_base] = (kp_right, kp_left)
                            self.last_valid_kp[screen_name_base] = (kp_right, kp_left, global_frame)
                        elif screen_name_base in self.last_valid_kp:
                            pr, pl, pf = self.last_valid_kp[screen_name_base]
                            if global_frame - pf <= self.KP_PERSIST_FRAMES:
                                kp_right, kp_left = pr, pl
                                use_persisted = True
                        
                        if kp_right is None or kp_left is None: 
                            continue
                            
                        active_kp_dict[screen_name_base] = (kp_right, kp_left)
                        
                        if act_type != 'PRESS' and act_type != 'SPRINT':
                            line_color = (0, 255, 255) if not use_persisted else (180, 180, 255)
                            cv2.line(frame_copy, kp_left, kp_right, line_color, 4)
                            cv2.circle(frame_copy, kp_left, 8, (0,255,0), -1)
                            cv2.circle(frame_copy, kp_right, 8, (0,255,0), -1)
                        else:
                            cv2.circle(frame_copy, kp_left, 6, (0,255,0), -1)
                            cv2.circle(frame_copy, kp_right, 6, (0,255,0), -1)
                        
                        kp_history[screen_name_base].append((local_frame_idx, (kp_right, kp_left)))
                        is_right_oriented = screen_name_base in self.RIGHT_ORIENTED_SCREENS
                        goal_side_sign = -1 if is_right_oriented else 1
                       
                        if act_type in ['PASS', 'TARGET', 'GOAL']:
                            for (cx, cy), conf, _ in balls:
                                if conf < self.BALL_POST_CONF: continue
                                track_id = ball_assignments.get((cx, cy))
                                if track_id in self.fake_tracks_per_action[action_idx]:
                                    cv2.circle(frame_copy, (cx, cy), 14, (0, 0, 255), 3)
                                    cv2.putText(frame_copy, "FAKE", (cx-40, cy-30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,0,255), 3)
                                    continue
                              
                                if act_type == 'PASS':
                                    dist, _, _, proj_t, signed_raw = self.calculate_distance_to_line((cx, cy), kp_left, kp_right)
                                    signed = signed_raw * goal_side_sign
                                    
                                    USE_POST_DISTANCE_SCREENS = {'14', '7', '9', '2', '12', '13', '3'}  
                                    CUSTOM_THRESHOLDS = {
                                        '14': 45, '7': 36, '9': 36, '2': 37, '12': 20, '13':37, '3':31   
                                    }
                                    
                                    if not hasattr(self, 'best_distances'):
                                        self.best_distances = {}
                                    
                                    if screen_name_base in USE_POST_DISTANCE_SCREENS:
                                        dist_to_left = math.hypot(cx - kp_left[0], cy - kp_left[1])
                                        dist_to_right = math.hypot(cx - kp_right[0], cy - kp_right[1])
                                        effective_dist = min(dist_to_left, dist_to_right)
                                        track_key = f"{action_idx}_{screen_name_base}"
                                        current_best = self.best_distances.get(track_key, float('inf'))
                                        if effective_dist < current_best:
                                            self.best_distances[track_key] = effective_dist
                                        threshold = CUSTOM_THRESHOLDS.get(screen_name_base, self.PASS_ACCEPTED_DISTANCE)
                                        is_within_distance = effective_dist <= threshold
                                        is_position_valid = True
                                    else:
                                        effective_dist = dist
                                        is_within_distance = dist <= self.PASS_ACCEPTED_DISTANCE
                                    
                                    if screen_name_base in ['2', '3', '4', '9', '10', '11']:
                                        if screen_name_base in USE_POST_DISTANCE_SCREENS:
                                            is_correct_finishing = is_within_distance and is_position_valid
                                        else:
                                            is_position_valid = (-0.5 <= proj_t <= 1.5) and (signed > -25)
                                            is_correct_finishing = is_within_distance and is_position_valid
                                            
                                    elif screen_name_base in ['12', '13', '14', '5', '6', '7' ]:
                                        if screen_name_base in USE_POST_DISTANCE_SCREENS:
                                            is_correct_finishing = is_within_distance and is_position_valid
                                        else:
                                            is_position_valid = (-0.35 <= proj_t <= 1.35) and (signed > -25)
                                            is_correct_finishing = is_within_distance and is_position_valid
                                            
                                           
                                    else:
                                        is_within_goal_mouth = self.is_point_between_posts(proj_t)
                                        is_position_valid = is_within_goal_mouth and (signed > -25)
                                        is_correct_finishing = is_within_distance and is_position_valid
                                    
                                    if is_correct_finishing:
                                        final_distance = effective_dist
                                        if screen_name_base in CUSTOM_THRESHOLDS:
                                            is_strong = final_distance <= self.PASS_CROSSED_DISTANCE
                                        else:
                                            is_strong = final_distance <= self.PASS_CROSSED_DISTANCE
                                        
                                        ftype = "LATE" if is_late else "CORRECT"
                                        txt = "LATE FINISHING" if is_late else "CORRECT FINISHING"
                                        col = (0,165,255) if is_late else (0,255,0)
                                        correct_this = True
                                        if is_strong:
                                            self.goals_scored[screen_name_base] += 1
                                        current = self.action_validation[action_idx]
                                        if not current.get('goal_detected') or is_strong:
                                            current.update({
                                                'goal_detected': True, 'finishing_type': ftype, 'goal_screen': screen_name,
                                                'is_correct_screen': True, 'is_correct_side': True, 'is_late': is_late,
                                                'global_frame': global_frame, 'distance': round(final_distance, 1),
                                                'strong_cross': is_strong, 'proj_t': round(proj_t, 3)
                                            })
                                        if is_strong:
                                            cv2.rectangle(frame_copy, (x1,y1),(x2,y2), col, 6)
                                            cv2.line(frame_copy, kp_left, kp_right, col, 5)
                                            cx_txt = (kp_left[0] + kp_right[0]) // 2
                                            cy_txt = (kp_left[1] + kp_right[1]) // 2
                                            cv2.putText(frame_copy, "GOAL", (cx_txt-70, cy_txt-50), cv2.FONT_HERSHEY_SIMPLEX, 2.2, col, 7)
                                            cv2.putText(frame_copy, txt, (cx_txt-260, cy_txt+60), cv2.FONT_HERSHEY_SIMPLEX, 1.3, col, 4)
                                        if self.timestamps and global_frame < len(self.timestamps):
                                            finish_abs = self.time_to_seconds(self.timestamps[global_frame])
                                            slice_start_abs = self.time_to_seconds(action.get('adjusted_start_time', ''))
                                            if slice_start_abs == 0:
                                                slice_start_abs = self.time_to_seconds(action.get('original_start_time', ''))
                                            relative_time = finish_abs - slice_start_abs
                                            action_dur = self.time_to_seconds(action.get('original_end_time', '')) - self.time_to_seconds(action.get('original_start_time', ''))
                                            relative_time = min(relative_time, action_dur)
                                            relative_time = max(0.0, relative_time)
                                            self.finishing_times[action_idx] = round(relative_time, 3)
                                            current['finishing_time'] = self.finishing_times[action_idx]
                              
                                elif act_type == 'TARGET':
                                    finishing_ok = False
                                    target_side_detected = None
                                    offset_px = 0
                                    actual_target_keypoint = None
                                    
                                    if is_target_keypoint:
                                        for tgt in allowed_screen_strings:
                                            tgt_str = str(tgt).strip().upper()
                                            
                                            if tgt_str in self.TARGET_MAPPING:
                                                expected_target = self.TARGET_MAPPING[tgt_str]
                                                
                                                if screen_name == expected_target:
                                                    target_center_x = (x1 + x2) // 2
                                                    target_center_y = (y1 + y2) // 2
                                                    
                                                    is_left_side = (cx <= target_center_x)
                                                    is_right_side = (cx >= target_center_x)
                                                    
                                                    if tgt_str.endswith('L'):
                                                        if is_left_side:
                                                            offset_px = abs(cx - target_center_x)
                                                            finishing_ok = (offset_px <= self.TARGET_LEFT_OFFSET_THRESHOLD)
                                                            target_side_detected = 'LEFT'
                                                            actual_target_keypoint = expected_target
                                                    elif tgt_str.endswith('R'):
                                                        if is_right_side:
                                                            offset_px = abs(cx - target_center_x)
                                                            finishing_ok = (offset_px <= self.TARGET_RIGHT_OFFSET_THRESHOLD)
                                                            target_side_detected = 'RIGHT'
                                                            actual_target_keypoint = expected_target
                                                    else:
                                                        offset_px = abs(cx - target_center_x)
                                                        finishing_ok = (offset_px <= self.TARGET_LEFT_OFFSET_THRESHOLD)
                                                        target_side_detected = 'CENTER'
                                                        actual_target_keypoint = expected_target
                                                    
                                                    if finishing_ok:
                                                        break
                                    
                                    if finishing_ok:
                                        is_strong = (offset_px <= self.TARGET_CROSSED_DISTANCE)
                                        ftype = "LATE" if is_late else "CORRECT"
                                        txt = "LATE FINISHING" if is_late else "CORRECT FINISHING"
                                        col = (0,165,255) if is_late else (0,255,0)
                                        correct_this = True
                                        if is_strong:
                                            self.goals_scored[screen_name_base] += 1
                                        current = self.action_validation[action_idx]
                                        if not current.get('goal_detected') or is_strong:
                                            current.update({
                                                'goal_detected': True, 'finishing_type': ftype, 'goal_screen': actual_target_keypoint or screen_name,
                                                'is_correct_screen': True, 'is_correct_side': True, 'is_late': is_late,
                                                'global_frame': global_frame, 'distance': round(offset_px, 1),
                                                'strong_cross': is_strong, 'target_side': target_side_detected
                                            })
                                        if is_strong:
                                            cv2.rectangle(frame_copy, (x1,y1),(x2,y2), col, 6)
                                            cx_txt = (x1 + x2) // 2
                                            cy_txt = y1 - 40
                                            cv2.putText(frame_copy, "TARGET " + target_side_detected, (cx_txt-100, cy_txt), 
                                                       cv2.FONT_HERSHEY_SIMPLEX, 1.5, col, 5)
                                            cv2.putText(frame_copy, txt, (cx_txt-260, cy_txt+60), 
                                                       cv2.FONT_HERSHEY_SIMPLEX, 1.3, col, 4)
                                            cv2.putText(frame_copy, "Offset: " + str(offset_px) + "px", (cx-50, cy-30), 
                                                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
                                            cv2.circle(frame_copy, (cx, cy), 20, (0, 255, 0), 3)
                                            cv2.circle(frame_copy, ((x1+x2)//2, (y1+y2)//2), 15, col, 3)
                                            cv2.line(frame_copy, (cx, cy), ((x1+x2)//2, (y1+y2)//2), col, 2)
                                        
                                        if self.timestamps and global_frame < len(self.timestamps):
                                            finish_abs = self.time_to_seconds(self.timestamps[global_frame])
                                            slice_start_abs = self.time_to_seconds(action.get('adjusted_start_time', ''))
                                            if slice_start_abs == 0:
                                                slice_start_abs = self.time_to_seconds(action.get('original_start_time', ''))
                                            relative_time = finish_abs - slice_start_abs
                                            action_dur = self.time_to_seconds(action.get('original_end_time', '')) - self.time_to_seconds(action.get('original_start_time', ''))
                                            relative_time = min(relative_time, action_dur)
                                            relative_time = max(0.0, relative_time)
                                            self.finishing_times[action_idx] = round(relative_time, 3)
                                            current['finishing_time'] = self.finishing_times[action_idx]
                              
                                elif act_type == 'GOAL':
                                    dist, _, _, proj_t, signed_raw = self.calculate_distance_to_line((cx, cy), kp_left, kp_right)
                                    signed = signed_raw * goal_side_sign
                                    if not (self.PROJ_T_SANITY_MIN <= proj_t <= self.PROJ_T_SANITY_MAX):
                                        continue
                                    is_within_goal_mouth = self.is_point_between_posts(proj_t)
                                    if not is_within_goal_mouth:
                                        continue
                                    finishing_ok = signed > -25
                                    if finishing_ok:
                                        is_strong = dist <= self.GOAL_CROSSED_DISTANCE
                                        ftype = "LATE" if is_late else "CORRECT"
                                        txt = "LATE FINISHING" if is_late else "CORRECT FINISHING"
                                        col = (0,165,255) if is_late else (0,255,0)
                                        correct_this = True
                                        if is_strong:
                                            self.goals_scored[screen_name_base] += 1
                                        current = self.action_validation[action_idx]
                                        if not current.get('goal_detected') or is_strong:
                                            current.update({
                                                'goal_detected': True,
                                                'finishing_type': ftype,
                                                'goal_screen': screen_name,
                                                'is_correct_screen': True,
                                                'is_correct_side': True,
                                                'is_late': is_late,
                                                'global_frame': global_frame,
                                                'distance': round(dist, 1),
                                                'strong_cross': is_strong,
                                                'proj_t': round(proj_t, 3)
                                            })
                                        if is_strong:
                                            cv2.rectangle(frame_copy, (x1,y1),(x2,y2), col, 6)
                                            cv2.line(frame_copy, kp_left, kp_right, col, 5)
                                            cx_txt = (kp_left[0] + kp_right[0]) // 2
                                            cy_txt = (kp_left[1] + kp_right[1]) // 2
                                            cv2.putText(frame_copy, "GOAL", (cx_txt-70, cy_txt-50),
                                                       cv2.FONT_HERSHEY_SIMPLEX, 2.5, col, 8)
                                            cv2.putText(frame_copy, txt, (cx_txt-260, cy_txt+60),
                                                       cv2.FONT_HERSHEY_SIMPLEX, 1.3, col, 4)
                                            cv2.circle(frame_copy, (cx, cy), 18, (0, 255, 255), 3)
                                        if self.timestamps and global_frame < len(self.timestamps):
                                            finish_abs = self.time_to_seconds(self.timestamps[global_frame])
                                            slice_start_abs = self.time_to_seconds(action.get('adjusted_start_time', ''))
                                            if slice_start_abs == 0:
                                                slice_start_abs = self.time_to_seconds(action.get('original_start_time', ''))
                                            relative_time = finish_abs - slice_start_abs
                                            action_dur = self.time_to_seconds(action.get('original_end_time', '')) - self.time_to_seconds(action.get('original_start_time', ''))
                                            relative_time = min(relative_time, action_dur)
                                            relative_time = max(0.0, relative_time)
                                            self.finishing_times[action_idx] = round(relative_time, 3)
                                            current['finishing_time'] = self.finishing_times[action_idx]

                        elif act_type in ['PRESS', 'SPRINT']:
                            if person_boxes is not None and len(person_boxes) > 0:
                                try:
                                    if isinstance(person_boxes, np.ndarray):
                                        clean_boxes = person_boxes[~np.any(np.isnan(person_boxes), axis=1)]
                                    else:
                                        clean_boxes = np.array(person_boxes)
                                        clean_boxes = clean_boxes[~np.any(np.isnan(clean_boxes), axis=1)]
                                    
                                    if len(clean_boxes) > 0:
                                        areas = (clean_boxes[:,2]-clean_boxes[:,0]) * (clean_boxes[:,3]-clean_boxes[:,1])
                                        best_idx = int(np.argmax(areas))
                                        best_box = clean_boxes[best_idx]
                                        px = (best_box[0] + best_box[2]) / 2
                                        py = (best_box[1] + best_box[3]) / 2
                                        player_cx, player_cy = int(px), int(py)
                                        
                                        is_right_oriented = screen_name_base in self.RIGHT_ORIENTED_SCREENS
                                        
                                        if is_right_oriented:
                                            target_kp = kp_right
                                            cv2.circle(frame_copy, kp_right, 15, (0, 255, 255), -1)
                                            cv2.putText(frame_copy, "GOAL ZONE", (kp_right[0]-50, kp_right[1]-15), 
                                                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                                        else:
                                            target_kp = kp_left
                                            cv2.circle(frame_copy, kp_left, 15, (0, 255, 255), -1)
                                            cv2.putText(frame_copy, "GOAL ZONE", (kp_left[0]-50, kp_left[1]-15), 
                                                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                                        
                                        dist_to_target = math.hypot(player_cx - target_kp[0], player_cy - target_kp[1])
                                        
                                        crossed_threshold = self.DIST_GOAL_CROSSED_DEFAULT
                                        accepted_threshold = self.DIST_GOAL_ACCEPTED_DEFAULT
                                        
                                        finishing_ok = (dist_to_target <= accepted_threshold)
                                        
                                        if finishing_ok:
                                            is_strong = dist_to_target <= crossed_threshold
                                            ftype = "LATE" if is_late else "CORRECT"
                                            txt = "LATE FINISHING" if is_late else "CORRECT FINISHING"
                                            col = (0,165,255) if is_late else (0,255,0)
                                            correct_this = True
                                            
                                            current = self.action_validation[action_idx]
                                            if not current.get('goal_detected') or is_strong:
                                                current.update({
                                                    'goal_detected': True,
                                                    'finishing_type': ftype,
                                                    'goal_screen': screen_name,
                                                    'is_correct_screen': True,
                                                    'is_correct_side': True,
                                                    'is_late': is_late,
                                                    'global_frame': global_frame,
                                                    'distance': round(dist_to_target, 1),
                                                    'strong_cross': is_strong,
                                                    'proj_t': 0.5
                                                })
                                            
                                            if is_strong:
                                                cv2.line(frame_copy, (player_cx, player_cy), target_kp, col, 3)
                                                cv2.rectangle(frame_copy, (x1,y1),(x2,y2), col, 6)
                                                cv2.circle(frame_copy, target_kp, 20, col, 3)
                                                cv2.circle(frame_copy, (player_cx, player_cy), 25, col, 3)
                                                cx_txt = target_kp[0]
                                                cy_txt = target_kp[1] - 40
                                                cv2.putText(frame_copy, act_type, (cx_txt-50, cy_txt-20),
                                                           cv2.FONT_HERSHEY_SIMPLEX, 2.2, col, 7)
                                                cv2.putText(frame_copy, txt, (cx_txt-260, cy_txt+40),
                                                           cv2.FONT_HERSHEY_SIMPLEX, 1.3, col, 4)
                                                cv2.putText(frame_copy, "Distance: " + str(dist_to_target) + "px", 
                                                           (player_cx-80, player_cy-30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, 2)
                                            else:
                                                cv2.line(frame_copy, (player_cx, player_cy), target_kp, (255, 200, 100), 2)
                                            
                                            if self.timestamps and global_frame < len(self.timestamps):
                                                finish_abs = self.time_to_seconds(self.timestamps[global_frame])
                                                slice_start_abs = self.time_to_seconds(action.get('adjusted_start_time', ''))
                                                if slice_start_abs == 0:
                                                    slice_start_abs = self.time_to_seconds(action.get('original_start_time', ''))
                                                relative_time = finish_abs - slice_start_abs
                                                action_dur = self.time_to_seconds(action.get('original_end_time', '')) - self.time_to_seconds(action.get('original_start_time', ''))
                                                relative_time = min(relative_time, action_dur)
                                                relative_time = max(0.0, relative_time)
                                                self.finishing_times[action_idx] = round(relative_time, 3)
                                                current['finishing_time'] = self.finishing_times[action_idx]
                                except Exception as e:
                                    pass

            except Exception as e:
                print(f"Screen detection error: {e}")
      
        votes = self.yaw_direction_votes[action_idx]
        if local_frame_idx <= action['total_frames']:
            ts = self.cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if ts <= 0:
                ts = self.prev_timestamp + 1.0 / max(self.fps, 1)
            self.prev_timestamp = ts
            display_yaw = None
            is_held = False
            try:
                person_results_yaw = self.person_model_for_yaw(frame_copy, conf=0.35, verbose=False) if self.person_model_for_yaw else None
                person_boxes_yaw = []
                if person_results_yaw and len(person_results_yaw) > 0 and person_results_yaw[0].boxes is not None:
                    boxes_yaw = person_results_yaw[0].boxes.xyxy.cpu().numpy()
                    if len(boxes_yaw) > 0:
                        person_boxes_yaw = boxes_yaw[~np.any(np.isnan(boxes_yaw), axis=1)]
                best_area_face = 0
                for box in person_boxes_yaw:
                    x1, y1, x2, y2 = map(int, box[:4])
                    area_box = (x2 - x1) * (y2 - y1)
                    if area_box <= best_area_face: continue
                    best_area_face = area_box
                    pad = 70
                    x1 = max(0, x1 - pad)
                    y1 = max(0, y1 - pad)
                    x2 = min(self.width, x2 + pad)
                    y2 = min(self.height, y2 + pad)
                    crop = frame_copy[y1:y2, x1:x2]
                    if crop.size == 0: continue
                    faces = self.face_app.get(crop) if self.face_app else []
                    if not faces: continue
                    face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
                    best_face = face
                    break
            except Exception as e:
                print(f"Face detection error frame {global_frame}: {e}")
            
            # Draw player boxes and face landmarks
            frame_copy = self.draw_player_boxes_and_face_landmarks(frame_copy, person_boxes_yaw if 'person_boxes_yaw' in locals() else None, best_face if 'best_face' in locals() else None)
            
            if best_face is not None:
                raw_yaw = best_face.pose[1]
                if self.yaw_filter is None:
                    self.yaw_filter = OneEuroFilter(ts, raw_yaw, min_cutoff=0.7, beta=0.06, d_cutoff=1.0)
                smoothed_yaw = self.yaw_filter(ts, raw_yaw)
                display_yaw = smoothed_yaw
                self.last_display_yaw = smoothed_yaw
                self.frames_without_face = 0
                self.yaw_history_per_action[action_idx].append(smoothed_yaw)
                is_goal = self.is_goal_action(action)
                current_ft = self.action_validation[action_idx].get('finishing_type', None)
                
                if act_type in ['PRESS', 'SPRINT']:
                    max_frame = action['total_frames']
                    if self.finishing_times[action_idx] is not None:
                        max_frame = max(max_frame, int(self.finishing_times[action_idx] * self.fps) + 30)
                elif current_ft == "CORRECT" and self.finishing_times[action_idx] is not None:
                    max_frame = int(self.finishing_times[action_idx] * self.fps) + 10
                else:
                    max_frame = 40
                
                if is_goal:
                    mode = "GOAL (direct)"
                else:
                    if smoothed_yaw > 8:
                        self.seen_positive[action_idx] = True
                    elif smoothed_yaw < -8:
                        self.seen_negative[action_idx] = True
                    if local_frame_idx <= max_frame:
                        if self.seen_positive[action_idx] and self.seen_negative[action_idx]:
                            self.aware_detected_per_action[action_idx] = True
                    mode = "SCAN (swing)"
                if local_frame_idx <= max_frame and abs(smoothed_yaw) >= 8:
                    if smoothed_yaw < 0:
                        votes['right'] += 1
                    else:
                        votes['left'] += 1
            else:
                self.frames_without_face += 1
                if self.last_display_yaw is not None and self.frames_without_face <= self.MAX_HOLD_FRAMES:
                    display_yaw = self.last_display_yaw
                    is_held = True
                if self.frames_without_face >= 8:
                    self.aware_detected_per_action[action_idx] = True
                if self.last_display_yaw is not None:
                    self.yaw_history_per_action[action_idx].append(self.last_display_yaw)
            if display_yaw is not None:
                color = (0, 255, 0) if not is_held else (0, 180, 255)
                suffix = " (last)" if is_held else ""
                yaw_text = "YAW: " + str(int(round(display_yaw))) + " deg" + suffix
                cv2.putText(frame_copy, yaw_text, (50, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.6, color, 4, cv2.LINE_AA)
                if self.aware_detected_per_action[action_idx]:
                    col = (0, 220, 0) if not is_held else (0, 160, 220)
                    cv2.putText(frame_copy, "AWARE" + suffix, (50, 140), cv2.FONT_HERSHEY_SIMPLEX, 2.0, col, 6, cv2.LINE_AA)
        else:
            # Still draw boxes even if beyond action frames
            frame_copy = self.draw_player_boxes_and_face_landmarks(frame_copy, person_boxes, best_face if 'best_face' in locals() else None)
      
        frame_copy = self.draw_pose_skeleton(frame_copy)
      
        return frame_copy, correct_this, wrong_this

    def create_stitched_video(self, output_path=None):
        if output_path is None:
            output_path = f"processed_stitched_{datetime.now():%Y%m%d_%H%M%S}.mp4"
        codecs_to_try = ['avc1', 'mp4v', 'X264', 'H264']
        out = None
        for codec in codecs_to_try:
            try:
                fourcc = cv2.VideoWriter_fourcc(*codec)
                test_out = cv2.VideoWriter(output_path, fourcc, self.fps, (self.width, self.height))
                if test_out.isOpened():
                    out = test_out
                    print(f"Using codec: {codec}")
                    break
                else:
                    test_out.release()
            except:
                continue
        if out is None:
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_path, fourcc, self.fps, (self.width, self.height))
      
        intro = self.create_intro_frame()
        for _ in range(int(3 * self.fps)):
            out.write(intro)
      
        for i, action in enumerate(self.actions):
            print(f"\n=== Starting Action {i} ({action.get('block_id', '?')}) ===")
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, action.get('start_frame', 0))
            grace_frames = int(self.grace_seconds * self.fps + 0.5)
            self.yaw_filter = None
            self.prev_timestamp = 0.0
            self.last_display_yaw = None
            self.frames_without_face = 0
            kp_history = defaultdict(list)
          
            for local_idx in range(1, action['total_frames'] + self.EXTRA_FRAMES_AFTER_ACTION + grace_frames + 1):
                ret, frame = self.cap.read()
                if not ret: break
                processed, corr, wrong = self.detect_goals_in_frame(frame, action, i, local_idx, kp_history)
                if local_idx <= action['total_frames'] + self.EXTRA_FRAMES_AFTER_ACTION:
                    out.write(processed)
          
            fakes, trusted = self.classify_ball_tracks(i, kp_history)
            self.fake_tracks_per_action[i] = fakes
            self.trusted_tracks_per_action[i] = trusted
            if fakes:
                self.action_validation[i]['fake_static_ignored'] = True
                print(f"Action {i}: ignored {len(fakes)} fake/static ball track(s)")
          
            self.print_block_conclusion(i, action)
          
            votes = self.yaw_direction_votes[i]
            if votes['left'] > votes['right']:
                vision = "Vision Left Oriented"
            elif votes['right'] > votes['left']:
                vision = "Vision Right Oriented"
            else:
                vision = "Vision Mixed"
            self.action_validation[i]['vision_orientation'] = vision
          
            next_act = self.actions[i+1] if i+1 < len(self.actions) else None
            trans = self.create_transition_frame(action, next_act)
            for _ in range(int(2 * self.fps)):
                out.write(trans)
      
        print("\n" + "="*60)
        print("DETERMINING ACTION ORIENTATION FROM FINAL RESULTS")
        print("="*60)
        for i, action in enumerate(self.actions):
            self.determine_action_orientation_from_results(i, action)
      
        print("\n" + "="*60)
        print("ADDING FINISHING TIMES TO VALIDATION")
        print("="*60)
        for i, action in enumerate(self.actions):
            if self.finishing_times[i] is not None:
                self.action_validation[i]['finishing_time'] = self.finishing_times[i]
                print(f"Action {i} ({action.get('block_id', '?')}): finishing_time = {self.finishing_times[i]:.3f}s")
            else:
                print(f"Action {i} ({action.get('block_id', '?')}): No finishing_time recorded")
      
        outro = self.create_outro_frame()
        for _ in range(int(3 * self.fps)):
            out.write(outro)
      
        out.release()
        print(f"\nSaved: {output_path}")
        self.print_validation_report()
        return output_path
  
    def print_validation_report(self):
        print("\n" + "="*150)
        print("FINISHING AND ORIENTATION VALIDATION REPORT")
        print("="*150)
        header = f"{'Block ID':<10} {'Action':<10} {'Screens':<25} {'Screen':<8} {'Dist/Offset':<12} {'Aware':<8} {'Vision':<22} {'Action Orientation':<22} {'Finishing Time(s)':<18} Result"
        print(header)
        print("-"*200)
      
        def safe(v, default="-"):
            return str(v) if v is not None else default
      
        correct = late = wrong = no_goal = relevant = 0
        finishing_times_list = []
      
        for i, act in enumerate(self.actions):
            v = self.action_validation.get(i, {})
            bid = safe(act.get('block_id') or '??')
            a_type = safe(act.get('action') or 'UNKNOWN').upper()
            screens = ', '.join(str(s) for s in act.get('screens_index', [])) if act.get('screens_index') else "-"
            sc = safe(v.get('goal_screen'), '-')
            dist = safe(v.get('distance'), '-')
            aware_status = "Aware" if i < len(self.aware_detected_per_action) and self.aware_detected_per_action[i] else "Not Aware"
            vision = safe(v.get('vision_orientation'), '-')
            action_ori = safe(v.get('action_orientation'), '-')
            fake_note = " (fake ignored)" if v.get('fake_static_ignored') else ""
            finish_time = self.finishing_times[i] if i < len(self.finishing_times) else None
            finish_time_str = f"{finish_time:.3f}" if finish_time is not None else "-"
            ft = v.get('finishing_type', '-')
          
            if a_type in ['PASS','TARGET','PRESS','SPRINT','GOAL']:
                relevant += 1
                if ft == 'CORRECT':
                    correct += 1
                    res = "CORRECT"
                    if finish_time is not None:
                        finishing_times_list.append(finish_time)
                elif ft == 'LATE':
                    late += 1
                    res = "LATE"
                    if finish_time is not None:
                        finishing_times_list.append(finish_time)
                elif ft == 'WRONG':
                    wrong += 1
                    res = "WRONG"
                else:
                    no_goal += 1
                    res = "WRONG"
            else:
                res = "OTHER"
          
            print(f"{bid:<10} {a_type:<10} {screens:<25} {sc:<8} {dist:<12} {aware_status:<8} {vision:<22} {action_ori:<22} {finish_time_str:<18} {res}{fake_note}")
      
        print("-"*200)
      
        if relevant:
            print(f"\nFinishing Summary:")
            print(f" Total finishing actions: {relevant}")
            print(f" Correct: {correct:3d} ({correct/relevant*100:5.1f}%)")
            print(f" Late: {late:3d} ({late/relevant*100:5.1f}%)")
            print(f" Wrong: {wrong:3d} ({wrong/relevant*100:5.1f}%)")
            print(f" No goal: {no_goal:3d} ({no_goal/relevant*100:5.1f}%)")
      
        total_strong = sum(self.goals_scored.values())
        print(f"\nTotal strong goals: {total_strong}")
        if total_strong > 0:
            print("By screen:")
            for s, cnt in sorted(self.goals_scored.items(), key=lambda x: -x[1]):
                if cnt > 0:
                    print(f" {s:>8}: {cnt:3d}")
        print("\n" + "="*90 + "\n")


if __name__ == "__main__":
    processor = BlockIDVideoProcessor(
        video_path=r"C:\Users\siama\Documents\record\sia1\stitched_camera1+camera8.mp4",
        timestamps_file="timestamps.json",
        qr_file="qr_analysis.json",
        yolo_ball_model="best_b_p.pt",
        yolo_screen_model="best_pose.pt",
        yolo_pose_model="best_b_p.pt",
        pass_crossed_distance=8,
        pass_accepted_distance=15,
        target_crossed_distance=15,
        target_accepted_distance=150,
        goal_crossed_distance=8,
        goal_accepted_distance=15,
        target_side_threshold_left=0.3,
        target_side_threshold_right=0.7,
        frame_offset=21,
        min_duration_percentage=85,
        extra_frames_after_action=15
    )
    processor.create_stitched_video("processed_output.mp4")