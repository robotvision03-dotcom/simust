import cv2
import numpy as np
import json
from datetime import datetime
import os
import time
from ultralytics import YOLO
from insightface.app import FaceAnalysis
import torch
import math

class OneEuroFilter:
    def __init__(self, t0, x0, min_cutoff=0.4, beta=0.03, d_cutoff=1.0):
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


class FinalYawDetector:
    def __init__(self, video_path, timestamps_file, qr_actions_file, output_json="final_detection.json"):
        self.video_path = video_path
        self.timestamps_file = timestamps_file
        self.qr_actions_file = qr_actions_file
        self.output_json = output_json
        
        # Load YOLO model
        print("Loading YOLO model...")
        self.detection_model = YOLO('best_b_p.pt')
        
        if torch.cuda.is_available():
            self.detection_model.to('cuda')
            print("✓ Using GPU for YOLO")
        else:
            print("⚠️ Using CPU for YOLO")
        
        # Initialize InsightFace
        print("Initializing InsightFace...")
        try:
            import onnxruntime as ort
            providers = ['CUDAExecutionProvider', 'CPUExecutionProvider'] if 'CUDAExecutionProvider' in ort.get_available_providers() else ['CPUExecutionProvider']
            self.face_app = FaceAnalysis(name='buffalo_l', providers=providers)
            self.face_app.prepare(ctx_id=0 if 'CUDAExecutionProvider' in providers else -1, det_size=(640, 640))
            print("✓ InsightFace loaded successfully")
        except Exception as e:
            print(f"❌ InsightFace load error: {e}")
            self.face_app = None
            raise
        
        # Processing parameters (NO OFFSET)
        self.process_scale = 1.0
        self.yolo_imgsz = 1280
        self.face_roi_size = 640
        
        # Confidence thresholds
        self.BALL_CONF = 0.12
        self.PLAYER_CONF = 0.20
        
        # Face detection parameters
        self.face_height_factor = 0.5
        self.face_width_expand = 0.15
        self.face_padding = 0.3
        
        # Filter parameters
        self.filter_min_cutoff = 0.4
        self.filter_beta = 0.03
        self.filter_d_cutoff = 1.0
        
        # Processing options
        self.enable_sharpening = True
        self.max_players = 2
        
        # Yaw tracking
        self.yaw_filter = None
        
        # Load data
        self.load_data()
    
    def load_data(self):
        """Load timestamps and QR actions"""
        with open(self.timestamps_file, 'r') as f:
            self.video_timestamps = json.load(f)
        
        with open(self.qr_actions_file, 'r') as f:
            qr_data = json.load(f)
            self.qr_actions = qr_data['analysis']
        
        print(f"✓ Loaded {len(self.video_timestamps)} video frames")
        print(f"✓ Loaded {len(self.qr_actions)} QR actions")
        
        # Parse timestamps
        self.frame_times = []
        base_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        for ts_str in self.video_timestamps:
            time_parts = ts_str.split(':')
            hour = int(time_parts[0])
            minute = int(time_parts[1])
            second_parts = time_parts[2].split('.')
            second = int(second_parts[0])
            microsecond = int(second_parts[1]) * 1000 if len(second_parts) > 1 else 0
            
            dt = base_date.replace(hour=hour, minute=minute, second=second, microsecond=microsecond)
            self.frame_times.append(dt)
    
    def get_frame_index(self, target_time):
        """Find closest frame index"""
        min_diff = float('inf')
        closest_idx = 0
        
        for i, frame_time in enumerate(self.frame_times):
            diff = abs((frame_time - target_time).total_seconds())
            if diff < min_diff:
                min_diff = diff
                closest_idx = i
        
        return closest_idx
    
    def detect_objects(self, frame):
        """Detect balls and players"""
        result = self.detection_model(frame, verbose=False, conf=self.BALL_CONF, 
                                     iou=0.45, imgsz=self.yolo_imgsz)[0]
        
        balls = []
        players = []
        
        if result.boxes is not None:
            for box in result.boxes:
                class_id = int(box.cls)
                xyxy = box.xyxy[0].cpu().numpy()
                x1, y1, x2, y2 = map(int, xyxy)
                center_x = (x1 + x2) // 2
                center_y = (y1 + y2) // 2
                confidence = float(box.conf)
                
                if class_id == 0 and confidence >= self.BALL_CONF:
                    balls.append({
                        'bbox': [int(x1), int(y1), int(x2), int(y2)],
                        'center': [int(center_x), int(center_y)],
                        'confidence': round(confidence, 3)
                    })
                elif class_id == 1 and confidence >= self.PLAYER_CONF:
                    players.append({
                        'bbox': [int(x1), int(y1), int(x2), int(y2)],
                        'center': [int(center_x), int(center_y)],
                        'confidence': round(confidence, 3)
                    })
        
        return balls, players
    
    def select_best_players(self, players, max_players=2):
        """Select best players by confidence"""
        if not players:
            return []
        
        players_sorted = sorted(players, key=lambda x: x['confidence'], reverse=True)
        return players_sorted[:max_players]
    
    def detect_yaw_from_player(self, frame, player_box, timestamp):
        """Detect yaw angle from player"""
        x1, y1, x2, y2 = player_box
        
        face_height = int((y2 - y1) * self.face_height_factor)
        face_y1 = max(0, y1)
        face_y2 = min(frame.shape[0], y1 + face_height)
        
        face_width = x2 - x1
        face_x1 = max(0, x1 - int(face_width * self.face_width_expand))
        face_x2 = min(frame.shape[1], x2 + int(face_width * self.face_width_expand))
        
        pad_w = int((face_x2 - face_x1) * self.face_padding)
        pad_h = int(face_height * self.face_padding)
        face_x1 = max(0, face_x1 - pad_w)
        face_x2 = min(frame.shape[1], face_x2 + pad_w)
        face_y1 = max(0, face_y1 - pad_h)
        face_y2 = min(frame.shape[0], face_y2 + pad_h)
        
        if face_x2 <= face_x1 or face_y2 <= face_y1:
            return None
        
        face_roi = frame[face_y1:face_y2, face_x1:face_x2]
        if face_roi.size == 0:
            return None
        
        face_roi = cv2.resize(face_roi, (self.face_roi_size, self.face_roi_size), 
                             interpolation=cv2.INTER_LANCZOS4)
        
        if self.enable_sharpening:
            kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
            face_roi = cv2.filter2D(face_roi, -1, kernel)
        
        try:
            faces = self.face_app.get(face_roi)
            if faces:
                face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
                raw_yaw = float(face.pose[1])
                
                if self.yaw_filter is None:
                    self.yaw_filter = OneEuroFilter(timestamp, raw_yaw, 
                                                   min_cutoff=self.filter_min_cutoff,
                                                   beta=self.filter_beta,
                                                   d_cutoff=self.filter_d_cutoff)
                smoothed_yaw = self.yaw_filter(timestamp, raw_yaw)
                
                face_bbox = face.bbox
                scale_factor = self.face_roi_size
                fx1 = int(face_bbox[0] * (face_x2 - face_x1) / scale_factor + face_x1)
                fy1 = int(face_bbox[1] * (face_y2 - face_y1) / scale_factor + face_y1)
                fx2 = int(face_bbox[2] * (face_x2 - face_x1) / scale_factor + face_x1)
                fy2 = int(face_bbox[3] * (face_y2 - face_y1) / scale_factor + face_y1)
                
                return {
                    'yaw_angle': round(smoothed_yaw, 1),
                    'raw_yaw': round(raw_yaw, 1),
                    'confidence': float(face.det_score),
                    'face_bbox': [int(fx1), int(fy1), int(fx2), int(fy2)],
                    'face_center': [int((fx1+fx2)//2), int((fy1+fy2)//2)]
                }
        except Exception:
            pass
        
        return None
    
    def process_video(self):
        """Main processing - NO FRAME OFFSET"""
        print("\n" + "="*70)
        print("FINAL YAW DETECTION SYSTEM (NO FRAME OFFSET)")
        print("="*70)
        
        cap = cv2.VideoCapture(self.video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        
        print(f"Video: {self.video_path}")
        print(f"Total frames: {total_frames}, FPS: {fps:.2f}")
        print(f"Resolution: {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
        print("-" * 70)
        print("OPTIMIZED PARAMETERS:")
        print(f"  • Process scale: {self.process_scale} (full resolution)")
        print(f"  • YOLO imgsz: {self.yolo_imgsz}")
        print(f"  • Ball confidence: {self.BALL_CONF}")
        print(f"  • Player confidence: {self.PLAYER_CONF}")
        print(f"  • Face ROI size: {self.face_roi_size}x{self.face_roi_size}")
        print(f"  • Frame offset: DISABLED (using original timestamps)")
        print("-" * 70)
        
        all_sessions = []
        overall_start = time.time()
        total_frames_processed = 0
        
        for action_idx, action in enumerate(self.qr_actions):
            # Parse times
            start_dt = datetime.strptime(action['start_time'], "%Y-%m-%d %H:%M:%S.%f")
            end_dt = datetime.strptime(action['end_time'], "%Y-%m-%d %H:%M:%S.%f")
            
            base_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            start_time_only = start_dt.replace(year=base_date.year, month=base_date.month, day=base_date.day)
            end_time_only = end_dt.replace(year=base_date.year, month=base_date.month, day=base_date.day)
            
            # Get frames - NO OFFSET
            start_frame = self.get_frame_index(start_time_only)
            end_frame = self.get_frame_index(end_time_only)
            
            # Ensure valid range
            if end_frame <= start_frame:
                end_frame = min(start_frame + int(3 * fps), total_frames - 1)
            
            if start_frame >= total_frames - 1:
                print(f"⚠️ Skipping {action['block_id']} - out of range")
                continue
            
            print(f"\n📊 {action['block_id']}: {action['action']} {action['screens_index']}")
            print(f"   Original frames: {start_frame} to {end_frame} ({end_frame - start_frame + 1} frames)")
            print(f"   NO OFFSET applied - using exact timestamps")
            
            # Seek to start frame
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            
            session_data = []
            session_start_time = time.time()
            frames_with_yaw = 0
            self.yaw_filter = None
            
            for frame_idx in range(start_frame, end_frame + 1):
                ret, frame = cap.read()
                if not ret:
                    break
                
                timestamp = frame_idx / fps
                relative_time = round((frame_idx - start_frame) / fps, 3)
                
                # Detect balls and players
                balls, players = self.detect_objects(frame)
                
                # Select best players
                best_players = self.select_best_players(players, max_players=self.max_players)
                
                # Detect yaw for each best player
                yaw_results = []
                for player in best_players:
                    yaw_data = self.detect_yaw_from_player(frame, player['bbox'], timestamp)
                    if yaw_data:
                        frames_with_yaw += 1
                        yaw_results.append({
                            'player_center': player['center'],
                            'player_confidence': player['confidence'],
                            'yaw': yaw_data
                        })
                
                # Prepare frame data
                frame_data = {
                    'frame_number': int(frame_idx),
                    'timestamp_seconds': float(relative_time),
                    'absolute_timestamp': float(timestamp),
                    'balls': [
                        {
                            'id': idx + 1,
                            'bbox': ball['bbox'],
                            'center': ball['center'],
                            'confidence': ball['confidence']
                        } for idx, ball in enumerate(balls)
                    ],
                    'players': [
                        {
                            'player_id': idx + 1,
                            'player_bbox': player['bbox'],
                            'player_center': player['center'],
                            'player_confidence': player['confidence']
                        } for idx, player in enumerate(players)
                    ],
                    'face_detections': [
                        {
                            'player_center': fd['player_center'],
                            'player_confidence': fd['player_confidence'],
                            'yaw_angle': fd['yaw']['yaw_angle'],
                            'yaw_confidence': fd['yaw']['confidence'],
                            'face_bbox': fd['yaw']['face_bbox'],
                            'face_center': fd['yaw']['face_center']
                        } for fd in yaw_results
                    ],
                    'summary': {
                        'total_balls': len(balls),
                        'total_players': len(players),
                        'players_with_yaw': len(yaw_results),
                        'avg_ball_confidence': round(np.mean([b['confidence'] for b in balls]), 3) if balls else 0,
                        'avg_player_confidence': round(np.mean([p['confidence'] for p in players]), 3) if players else 0
                    }
                }
                
                session_data.append(frame_data)
                total_frames_processed += 1
                
                # Progress update
                frames_done = frame_idx - start_frame + 1
                if frames_done % 30 == 0:
                    progress = (frames_done / (end_frame - start_frame + 1)) * 100
                    elapsed = time.time() - session_start_time
                    fps_current = frames_done / elapsed if elapsed > 0 else 0
                    print(f"\r   Progress: {progress:.0f}% | FPS: {fps_current:.1f} | Yaw frames: {frames_with_yaw}", end="\r")
            
            session_time = time.time() - session_start_time
            session_fps = len(session_data) / session_time if session_time > 0 else 0
            
            # Calculate statistics
            total_balls = sum(len(frame['balls']) for frame in session_data)
            total_players = sum(len(frame['players']) for frame in session_data)
            total_yaw_frames = sum(1 for frame in session_data if frame['face_detections'])
            
            # Collect all yaw angles
            all_yaws = []
            for frame in session_data:
                for fd in frame['face_detections']:
                    all_yaws.append(fd['yaw_angle'])
            
            avg_yaw = np.mean(all_yaws) if all_yaws else None
            
            all_sessions.append({
                'block_id': str(action['block_id']),
                'action': str(action['action']),
                'target_screens': [str(s) for s in action['screens_index']],
                'start_frame': int(start_frame),
                'end_frame': int(end_frame),
                'total_frames': len(session_data),
                'frame_data': session_data,
                'statistics': {
                    'total_frames': len(session_data),
                    'frames_with_yaw': total_yaw_frames,
                    'detection_rate': round(total_yaw_frames / len(session_data) * 100, 1),
                    'average_yaw': round(avg_yaw, 1) if avg_yaw else None,
                    'min_yaw': round(min(all_yaws), 1) if all_yaws else None,
                    'max_yaw': round(max(all_yaws), 1) if all_yaws else None,
                    'total_balls_detected': total_balls,
                    'total_players_detected': total_players,
                    'average_balls_per_frame': round(total_balls / len(session_data), 2),
                    'average_players_per_frame': round(total_players / len(session_data), 2),
                    'processing_fps': round(session_fps, 1)
                }
            })
            
            yaw_info = f"Avg Yaw: {avg_yaw:.1f}°" if avg_yaw else "No yaw"
            print(f"\n   ✅ Complete: {len(session_data)} frames | {total_yaw_frames} with yaw ({all_sessions[-1]['statistics']['detection_rate']:.1f}%) | {yaw_info} | Speed: {session_fps:.1f} FPS")
        
        cap.release()
        
        total_time = time.time() - overall_start
        overall_fps = total_frames_processed / total_time if total_time > 0 else 0
        
        # Calculate overall statistics
        total_frames_with_yaw = sum(s['statistics']['frames_with_yaw'] for s in all_sessions)
        total_frames_all = sum(s['statistics']['total_frames'] for s in all_sessions)
        total_balls_all = sum(s['statistics']['total_balls_detected'] for s in all_sessions)
        total_players_all = sum(s['statistics']['total_players_detected'] for s in all_sessions)
        
        # Calculate overall average yaw
        all_yaws_overall = []
        for session in all_sessions:
            for frame in session['frame_data']:
                for fd in frame['face_detections']:
                    all_yaws_overall.append(fd['yaw_angle'])
        
        overall_avg_yaw = np.mean(all_yaws_overall) if all_yaws_overall else None
        
        # Save JSON
        output_data = {
            'metadata': {
                'video': str(self.video_path),
                'processed_at': datetime.now().isoformat(),
                'fps': float(fps),
                'total_frames': int(total_frames),
                'resolution': {'width': int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), 'height': int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))},
                'frame_offset': 'DISABLED (using original timestamps)',
                'face_detection_method': 'InsightFace buffalo_l',
                'optimized_params': {
                    'process_scale': float(self.process_scale),
                    'yolo_imgsz': int(self.yolo_imgsz),
                    'ball_confidence': float(self.BALL_CONF),
                    'player_confidence': float(self.PLAYER_CONF),
                    'face_roi_size': int(self.face_roi_size),
                    'face_height_factor': float(self.face_height_factor),
                    'face_padding': float(self.face_padding),
                    'enable_sharpening': bool(self.enable_sharpening)
                },
                'total_processing_time_sec': round(float(total_time), 1),
                'overall_fps': round(float(overall_fps), 1)
            },
            'qr_actions': all_sessions,
            'overall_summary': {
                'total_actions': int(len(all_sessions)),
                'total_frames_processed': int(total_frames_processed),
                'total_frames_with_yaw': int(total_frames_with_yaw),
                'overall_detection_rate': round(float(total_frames_with_yaw / total_frames_all * 100), 1) if total_frames_all > 0 else 0,
                'overall_average_yaw': round(float(overall_avg_yaw), 1) if overall_avg_yaw is not None else None,
                'total_balls_detected': int(total_balls_all),
                'total_players_detected': int(total_players_all),
                'average_balls_per_frame': round(float(total_balls_all / total_frames_all), 2) if total_frames_all > 0 else 0,
                'average_players_per_frame': round(float(total_players_all / total_frames_all), 2) if total_frames_all > 0 else 0
            }
        }
        
        with open(self.output_json, 'w') as f:
            json.dump(output_data, f, indent=2)
        
        print("\n" + "="*70)
        print("PROCESSING COMPLETE")
        print("="*70)
        print(f"✅ Total frames processed: {total_frames_processed}")
        print(f"✅ Frames with yaw detected: {total_frames_with_yaw}")
        print(f"✅ Overall detection rate: {output_data['overall_summary']['overall_detection_rate']}%")
        print(f"✅ Overall average yaw: {output_data['overall_summary']['overall_average_yaw']}°")
        print(f"✅ Total balls detected: {total_balls_all}")
        print(f"✅ Total players detected: {total_players_all}")
        print(f"✅ Average balls/frame: {output_data['overall_summary']['average_balls_per_frame']}")
        print(f"✅ Processing time: {total_time:.1f}s")
        print(f"✅ Processing speed: {overall_fps:.1f} FPS")
        print(f"✅ Output saved to: {self.output_json}")
        print("="*70)
        
        return output_data


def main():
    video_path = "stitched_camera1+camera8.mp4"
    timestamps_file = "stitched_camera1+camera8.json"
    qr_actions_file = "qr-camera.json"
    output_file = "complete_tracking_data_no_offset.json"
    
    print("="*70)
    print("COMPLETE TRACKING SYSTEM (NO FRAME OFFSET)")
    print("Using original timestamps without offset")
    print("="*70)
    
    # Check files
    for f in [video_path, timestamps_file, qr_actions_file]:
        if not os.path.exists(f):
            print(f"❌ File not found: {f}")
            return
    
    detector = FinalYawDetector(video_path, timestamps_file, qr_actions_file, output_file)
    detector.process_video()
    
    print("\n✅ Done! Tracking complete without frame offset.")


if __name__ == "__main__":
    main()