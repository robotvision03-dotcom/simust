# recorder/video_recorder.py

import ctypes
import multiprocessing
import queue
import threading
import time
import cv2
import logging
import os
import mss
import numpy as np
from datetime import datetime
from . import settings
import re
import json
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

_TIMEOUT = 1 / 1000

# Windows multi-monitor support
if os.name == 'nt':
    user = ctypes.windll.user32
    class RECT(ctypes.Structure):
        _fields_ = [
            ('left', ctypes.c_ulong),
            ('top', ctypes.c_ulong),
            ('right', ctypes.c_ulong),
            ('bottom', ctypes.c_ulong)
        ]
        def dump(self):
            return list(map(int, (self.left, self.top, self.right, self.bottom)))

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ('cbSize', ctypes.c_ulong),
            ('rcMonitor', RECT),
            ('rcWork', RECT),
            ('dwFlags', ctypes.c_ulong)
        ]

    def get_monitors():
        retval = []
        CBFUNC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.POINTER(RECT), ctypes.c_double)
        def cb(hMonitor, hdcMonitor, lprcMonitor, dwData):
            r = lprcMonitor.contents
            data = [hMonitor]
            data.append(list(r.dump()))
            retval.append(data)
            return 1
        cbfunc = CBFUNC(cb)
        user.EnumDisplayMonitors(0, 0, cbfunc, 0)
        return retval

    def monitor_areas():
        retval = []
        monitors = get_monitors()
        for hMonitor, extents in monitors:
            data = [hMonitor]
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            mi.rcMonitor = RECT()
            mi.rcWork = RECT()
            user.GetMonitorInfoA(hMonitor, ctypes.byref(mi))
            data.append(list(mi.rcMonitor.dump()))
            data.append(list(mi.rcWork.dump()))
            retval.append(data)
        return retval

# ============================================================================
# QR Code Detection and Parsing Functions
# ============================================================================

def detect_qr_in_roi(frame, roi):
    """Detect QR code in the specified region of interest"""
    x1, y1, x2, y2 = roi
    # Ensure ROI is within frame bounds
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
        
        # If bbox is detected, adjust coordinates back to original frame
        if bbox is not None and len(bbox) > 0:
            bbox = bbox.astype(int)
            # Adjust bbox coordinates back to original frame
            bbox[:,:,0] += x1
            bbox[:,:,1] += y1
        
        return data.strip() if data else "", bbox
    except Exception as e:
        logger.debug(f"QR detection error: {e}")
        return "", None

def parse_qr_data(raw_data):
    """Parse QR data to extract action and screens_index"""
    action = ""
    screens = []
    
    if not raw_data:
        return action, screens
    
    # Try to parse as JSON first
    try:
        qr = json.loads(raw_data)
        action = str(qr.get("action", "")).strip()
        val = qr.get("screens_index", [])
        
        if isinstance(val, str):
            screens = [s.strip() for s in val.split(',') if s.strip()]
        elif isinstance(val, (list, tuple)):
            screens = [str(s).strip() for s in val if s is not None]
        
        if action or screens:
            return action.upper(), screens
    except Exception:
        pass
    
    # Try regex patterns for various formats
    patterns = [
        # JSON-like pattern
        (r'"action"\s*:\s*"([^"]*)"', r'"screens_index"\s*:\s*\[([^\]]*)\]'),
        # Simple key:value patterns
        (r'action\s*[:=]\s*["\']?([^,"\'}\s]+)', r'screens_index\s*[:=]\s*["\']?([^,"\'}\s]+)'),
        # Comma-separated format
        (r'action=([^,\s]+)', r'screens?=([^,\s]+)'),
    ]
    
    for action_pattern, screens_pattern in patterns:
        # Extract action
        if not action:
            m = re.search(action_pattern, raw_data, re.IGNORECASE)
            if m:
                action = m.group(1).strip().upper()
        
        # Extract screens
        if not screens:
            m = re.search(screens_pattern, raw_data, re.IGNORECASE)
            if m:
                content = m.group(1).strip('[]').strip('"\'')
                # Split by comma and clean
                items = [item.strip().strip('"\'').strip() 
                        for item in content.split(',') if item.strip()]
                screens = [s for s in items if s]
                # Remove duplicates while preserving order
                screens = list(dict.fromkeys(screens))
    
    # If still no screens but we have action, try to get screens from action
    if not screens and action:
        # Check if action contains screen info (e.g., "TARGET 7L")
        parts = action.split()
        if len(parts) > 1:
            action = parts[0]
            screens = [parts[1]]
    
    return action, screens

def save_analysis_to_json(analysis_data, filename, video_path):
    """Save QR analysis data to JSON file in the required format"""
    data = {
        "analysis": [
            {
                "block_id": b["block_id"],
                "action": b["action"],
                "screens_index": b["screens_index"],
                "start_time": b["start_time"],
                "end_time": b["end_time"],
                "status": b.get("status", "valid")
            } for b in analysis_data
        ],
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "total_blocks": len(analysis_data),
            "source_video": os.path.basename(video_path)
        }
    }
    
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved QR analysis to {filename} with {len(analysis_data)} blocks")
    except Exception as e:
        logger.error(f"Failed to save {filename}: {e}")
        print(f"Failed to save {filename}: {e}", file=sys.stderr)

# ============================================================================
# VideoRecorder Class
# ============================================================================

class VideoRecorder:
    def __init__(self, camera_name, camera_address, config, timeout=5):
        self._camera_name = camera_name
        self._camera_address = camera_address
        self.config = config
        self._timeout = timeout
        self._fps = config.get("fps", 25.0) if config else 25.0
        self.is_screen_record = config.get("screen_record", False) if config else False
        self._cancellation_pending = None
        self._main_process = None
        self._video_capture = None
        self._video_writer = None
        self._start_barrier = None
        self._stop_event = None
        self.ffmpeg_proc = None

    @property
    def is_busy(self):
        return self._main_process is not None and self._main_process.is_alive()

    def set_start_barrier(self, barrier):
        self._start_barrier = barrier

    def set_stop_event(self, event):
        self._stop_event = event

    def _enter_silent_mode(self):
        if not hasattr(self, '_original_level'):
            self._original_level = logger.level
            logger.setLevel(100)
        if not hasattr(self, '_original_stdout'):
            import sys, os
            self._original_stdout = sys.stdout
            self._original_stderr = sys.stderr
            devnull = open(os.devnull, 'w')
            sys.stdout = devnull
            sys.stderr = devnull

    def _restore_output(self):
        if hasattr(self, '_original_level'):
            logger.setLevel(self._original_level)
        if hasattr(self, '_original_stdout'):
            import sys
            sys.stdout = self._original_stdout
            sys.stderr = self._original_stderr

    def start(self, video_path):
        if self.is_busy:
            return
        self._cancellation_pending = multiprocessing.Value(ctypes.c_bool, False)
        self._main_process = multiprocessing.Process(
            target=self._main, args=(video_path,), daemon=True
        )
        self._main_process.start()
        time.sleep(0.08)
        self._enter_silent_mode()

    def cancel(self):
        if self.is_busy:
            self._cancellation_pending.value = True
            if self._stop_event:
                self._stop_event.set()
        self._restore_output()

    def stop(self):
        """Stop recording with proper cleanup"""
        if self.is_busy:
            self._cancellation_pending.value = True
            if self._stop_event:
                self._stop_event.set()
            self._main_process.join(timeout=4.0)
            if self._main_process.is_alive():
                self._main_process.terminate()
                self._main_process.join(timeout=2.0)
                if self._main_process.is_alive():
                    self._main_process.kill()
        
        # FORCE cleanup of RTSP connections
        self._force_cleanup_rtsp()
        
        self._cancellation_pending = None
        self._main_process = None
        self._restore_output()
        self._cleanup()
    def _force_cleanup_rtsp(self):
        """Forcefully cleanup RTSP connections"""
        if self._video_capture:
            try:
                self._video_capture.release()
                if hasattr(self._video_capture, 'open'):
                    self._video_capture.open()
                    self._video_capture.release()
            except:
                pass
            self._video_capture = None
        
        # Small delay to allow sockets to close
        time.sleep(0.5)
    

    def _cleanup(self):
        if self.is_screen_record:
            if self.ffmpeg_proc and self.ffmpeg_proc.poll() is None:
                self.ffmpeg_proc.terminate()
                try:
                    self.ffmpeg_proc.wait(timeout=5)
                except:
                    self.ffmpeg_proc.kill()
            self.ffmpeg_proc = None
            return
        if self._video_writer and self._video_writer.isOpened():
            self._video_writer.release()
        if self._video_capture and self._video_capture.isOpened():
            self._video_capture.release()
        self._video_writer = None
        self._video_capture = None

    def _add_timestamp_overlay(self, frame):
        now = datetime.now()
        ms = now.microsecond // 1000
        ts = now.strftime("%m-%d-%Y %H:%M:%S") + f":{ms:03d}"
        font = cv2.FONT_HERSHEY_SIMPLEX
        size = cv2.getTextSize(ts, font, 0.8, 2)[0]
        h, w = frame.shape[:2]
        x, y = 10, h - 10
        cv2.rectangle(frame, (x-5, y-size[1]-5), (x+size[0]+5, y+5), (0,0,0), -1)
        cv2.putText(frame, ts, (x, y), font, 0.8, (255,255,255), 2)
        return frame
    def _main(self, video_path):
        if self._camera_name == "qr-camera":
            self._main_screen_record(video_path)
            return
        if self._camera_address == "stitched-dummy":
            self._main_stitched_recording(video_path)
            return

        video_capture = None
        video_writer = None
        
        # ── NEW ────────────────────────────────────────────────
        should_save_timestamps = self._camera_name in ("camera-1", "camera-8")
        timestamps = [] if should_save_timestamps else None
        # ───────────────────────────────────────────────────────

        try:
            address = int(self._camera_address) if self._camera_address.isnumeric() else self._camera_address
            video_capture = self._connect_camera(address)
            self._video_capture = video_capture
            video_capture.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, self._timeout * 1000)
            video_capture.set(cv2.CAP_PROP_FPS, self._fps)
            video_capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not video_capture.isOpened():
                raise RuntimeError(f"Cannot open {address}")

            if self._start_barrier:
                self._start_barrier.wait(timeout=10)

            fps = self._fps
            fourcc = cv2.VideoWriter_fourcc(*settings.VIDEOS_FOURCC)
            w = int(video_capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(video_capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            video_writer = cv2.VideoWriter(video_path, fourcc, fps, (w, h))
            self._video_writer = video_writer

            q = queue.Queue(maxsize=settings.FRAMES_QUEUE_SIZE * 8)

            t_read = threading.Thread(target=self._read_frames, args=(video_capture, q), daemon=True)
            t_write = threading.Thread(target=self._write_frames, args=(video_path, video_writer, q, timestamps), daemon=True)
            #                                                     ↑ added timestamps argument

            t_read.start()
            t_write.start()
            t_read.join()
            t_write.join()

        except Exception as e:
            if self._stop_event:
                self._stop_event.set()
            raise

        finally:
            if video_writer and video_writer.isOpened():
                video_writer.release()
            if video_capture and video_capture.isOpened():
                video_capture.release()

            # ── NEW ───────────────────────────────────────────────────────────────
            if should_save_timestamps and timestamps:
                json_path = video_path.replace(settings.VIDEOS_FILE_EXTENSION, ".json")
                try:
                    with open(json_path, 'w', encoding='utf-8') as f:
                        # Pretty print with indentation + one item per line
                        json.dump(timestamps, f, ensure_ascii=False, indent=2)
                    logger.info(f"Saved {len(timestamps)} frame timestamps → {os.path.basename(json_path)}")
                except Exception as e:
                    logger.error(f"Failed to save timestamps {json_path}: {e}")
            # ──────────────────────────────────────────────────────────────────────

    def _main_stitched_recording(self, video_path):
        cap1 = cap8 = writer = None
        timestamps = []

        try:
            cap1 = self._connect_camera(settings.CAMERAS["camera-1"]["address"])
            cap8 = self._connect_camera(settings.CAMERAS["camera-8"]["address"])

            cap1.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            cap8.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            w = int(cap1.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap1.get(cv2.CAP_PROP_FRAME_HEIGHT))
            w8 = int(cap8.get(cv2.CAP_PROP_FRAME_WIDTH))
            h8 = int(cap8.get(cv2.CAP_PROP_FRAME_HEIGHT))

            if w != w8 or h != h8:
                raise RuntimeError(f"Resolution mismatch: cam1={w}x{h}, cam8={w8}x{h8}")

            if self._start_barrier:
                self._start_barrier.wait(timeout=15)

            fourcc = cv2.VideoWriter_fourcc(*settings.VIDEOS_FOURCC)
            fps = 25.0
            writer = cv2.VideoWriter(video_path, fourcc, fps, (w * 2, h))

            if not writer.isOpened():
                raise RuntimeError("Cannot open VideoWriter")

            print(f"Started stitched recording → {os.path.basename(video_path)}")

            while not (self._stop_event.is_set() or self._cancellation_pending.value):
                ret1, frame1 = cap1.read()
                ret8, frame8 = cap8.read()

                if not ret1 or not ret8:
                    print("One camera dropped frame or disconnected → stopping")
                    break

                stitched = cv2.hconcat([frame1, frame8])
                writer.write(stitched)

                now = datetime.now()
                ts_str = now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"
                timestamps.append(ts_str)

            json_path = video_path.replace(settings.VIDEOS_FILE_EXTENSION, "_timestamps.json")
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(timestamps, f, indent=2, ensure_ascii=False)

            print(f"Saved {len(timestamps)} frame timestamps → {os.path.basename(json_path)}")

        except Exception as e:
            print(f"Stitched recording failed: {e}", file=sys.stderr)
        finally:
            if writer is not None and writer.isOpened():
                writer.release()
            if cap1 is not None and cap1.isOpened():
                cap1.release()
            if cap8 is not None and cap8.isOpened():
                cap8.release()

    def _main_screen_record(self, video_path):
        """Main screen recording function with QR code detection for qr-camera"""
        video_writer = None
        try:
            # Sync point: Wait for all cameras to be ready before proceeding
            if self._start_barrier:
                logger.info(f"{self._camera_name} waiting at start barrier (screen)")
                try:
                    self._start_barrier.wait(timeout=10)
                    logger.info(f"{self._camera_name} passed start barrier - starting capture")
                except Exception as e:
                    logger.error(f"Barrier wait failed for {self._camera_name}: {e}")
                    if self._stop_event:
                        self._stop_event.set()
                    raise

            # Get screen recording parameters from config
            left = self.config.get("offset_x", 1920)  # Note: default is 1920 for second monitor
            top = self.config.get("offset_y", 0)
            width = self.config.get("width", 1920)    # Single monitor width
            height = self.config.get("height", 1080)
            framerate = self.config.get("framerate", 30.0)

            # Initialize video writer
            fourcc = cv2.VideoWriter_fourcc(*settings.VIDEOS_FOURCC)
            video_writer = cv2.VideoWriter(
                video_path, fourcc, framerate, (width, height)
            )
            if not video_writer.isOpened():
                raise Exception(f"Unable to open video writer: {video_path}")

            # Screen capture region - use single monitor size, not dual
            region = {"left": left, "top": top, "width": width, "height": height}
            
            # Frame timing control
            frame_interval = 1.0 / framerate
            next_frame_time = time.time()
            
            # QR code detection state (only for qr-camera)
            qr_state = None
            if self._camera_name == "qr-camera":
                # Use larger ROI for better detection - scan the entire frame
                roi = (
                    0,                    # x1
                    0,                    # y1
                    width,              # x2 (full width)
                    height // 2         # y2 (top half)
                )
                
                # Get cooldown period from config
                qr_cooldown = self.config.get("qr_cooldown", 0.5)
                
                qr_state = {
                    "blocks": [],           # Completed QR blocks
                    "current": None,        # Current active block
                    "counter": 0,          # Block counter (A1, A2, ...)
                    "last_time": None,     # Last frame timestamp
                    "last_raw_data": None, # Last detected QR data
                    "last_detection_time": 0,  # Last detection timestamp for cooldown
                    "roi": roi,            # Region of interest for QR detection
                    "draw_roi": self.config.get("draw_roi", True),  # Enable for debugging
                    "cooldown": qr_cooldown,  # Cooldown period between detections
                    "detection_count": 0,  # Total detections for debugging
                    "last_frame_time": 0   # Last frame time for FPS calculation
                }
                
                logger.info(f"QR camera initialized - Recording area: {width}x{height}")
                logger.info(f"QR detection ROI: {roi} (full width, top half)")
                logger.info(f"Cooldown: {qr_cooldown}s, Draw ROI: {qr_state['draw_roi']}")

            # Main recording loop
            frame_count = 0
            with mss.mss() as sct:
                while not (self._stop_event.is_set() or self._cancellation_pending.value):
                    current_time = time.time()
                    
                    # Control frame rate
                    if current_time >= next_frame_time:
                        frame_count += 1
                        
                        # Capture screen
                        img = sct.grab(region)
                        frame = np.array(img)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                        
                        # Resize if needed (should match expected dimensions)
                        if frame.shape[:2] != (height, width):
                            frame = cv2.resize(frame, (width, height))
                        
                        # Get current timestamp with milliseconds
                        now = datetime.now()
                        frame_time_str = now.strftime("%Y-%m-%d %H:%M:%S.") + \
                                       f"{now.microsecond // 1000:03d}"
                        
                        # QR code detection and processing (only for qr-camera)
                        if qr_state:
                            # Detect QR code in ROI (scan entire top half of frame)
                            raw_data, bbox = detect_qr_in_roi(frame, qr_state["roi"])
                            
                            # Draw ROI rectangle if enabled
                            if qr_state["draw_roi"]:
                                x1, y1, x2, y2 = qr_state["roi"]
                                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                                cv2.putText(frame, "QR Detection Area", (x1 + 10, y1 + 30),
                                          cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                            
                            # Parse QR data if detected
                            action, screens = parse_qr_data(raw_data) if raw_data else ("", [])
                            
                            # Log every detection for debugging
                            if raw_data:
                                qr_state["detection_count"] += 1
                                logger.info(f"QR DETECTED [{qr_state['detection_count']}]: '{raw_data[:50]}...'")
                                logger.info(f"Parsed: action='{action}', screens={screens}")
                                
                                # Draw detection on frame for visual feedback
                                if bbox is not None and len(bbox) > 0:
                                    pts = bbox[0].astype(int)
                                    cv2.polylines(frame, [pts], True, (0, 255, 0), 3)
                                    cv2.putText(frame, f"QR: {action} {screens}", 
                                              (pts[0][0], pts[0][1]-10),
                                              cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                            
                            # Check if this is a new valid QR code (with cooldown)
                            current_detection_time = time.time()
                            is_new_qr = (
                                raw_data and 
                                raw_data != qr_state["last_raw_data"] and 
                                action and 
                                screens and
                                (current_detection_time - qr_state["last_detection_time"] >= qr_state["cooldown"])
                            )
                            
                            if is_new_qr:
                                # Close previous block if exists
                                if qr_state["current"]:
                                    qr_state["current"]["end_time"] = qr_state["last_time"] or frame_time_str
                                    qr_state["blocks"].append(qr_state["current"])
                                    logger.info(f"Closed block {qr_state['current']['block_id']}")
                                
                                # Create new block
                                qr_state["counter"] += 1
                                block_id = f"A{qr_state['counter']}"
                                qr_state["current"] = {
                                    "block_id": block_id,
                                    "action": action.upper(),
                                    "screens_index": screens,
                                    "start_time": frame_time_str,
                                    "end_time": frame_time_str,  # Will be updated while QR visible
                                    "status": "valid"
                                }
                                qr_state["last_raw_data"] = raw_data
                                qr_state["last_detection_time"] = current_detection_time
                                
                                logger.info(f"✅ NEW QR BLOCK CREATED: {block_id} - {action} {screens}")
                                print(f"\n✅ QR DETECTED: Block {block_id} - {action} {screens} at {frame_time_str}")
                            
                            # Update end_time for current block while same QR is visible
                            elif qr_state["current"] and raw_data == qr_state["last_raw_data"]:
                                qr_state["current"]["end_time"] = frame_time_str
                                qr_state["last_time"] = frame_time_str
                            
                            # QR disappeared or invalid
                            elif not raw_data and qr_state["current"]:
                                # Close the block
                                qr_state["current"]["end_time"] = qr_state["last_time"] or frame_time_str
                                qr_state["blocks"].append(qr_state["current"])
                                logger.info(f"QR disappeared - closed block {qr_state['current']['block_id']}")
                                qr_state["current"] = None
                                qr_state["last_raw_data"] = None
                            
                            # Display current block info on frame
                            if qr_state["current"]:
                                block = qr_state["current"]
                                info_text = f"Block: {block['block_id']} - {block['action']} {block['screens_index']}"
                                cv2.putText(frame, info_text, (10, 30),
                                          cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                                
                                # Also show duration
                                duration_text = f"Duration: {block['start_time']} → {block['end_time']}"
                                cv2.putText(frame, duration_text, (10, 70),
                                          cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                            
                            # Show detection count on frame
                            cv2.putText(frame, f"QR Detections: {qr_state['detection_count']}", 
                                      (10, height - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
                        
                        # Add timestamp overlay for qr-camera
                        if self._camera_name == "qr-camera":
                            frame = self._add_timestamp_overlay(frame)
                        
                        # Write frame to video
                        video_writer.write(frame)
                        
                        # Schedule next frame
                        next_frame_time += frame_interval
                        
                        # Calculate FPS occasionally
                        if frame_count % 30 == 0 and qr_state:
                            current_frame_time = time.time()
                            if qr_state["last_frame_time"] > 0:
                                fps = 30 / (current_frame_time - qr_state["last_frame_time"])
                                logger.debug(f"Recording FPS: {fps:.1f}")
                            qr_state["last_frame_time"] = current_frame_time
                        
                        # Small sleep to prevent CPU overuse
                        time.sleep(min(0.001, frame_interval / 10))
                    else:
                        # Sleep until next frame
                        sleep_time = next_frame_time - current_time
                        if sleep_time > 0:
                            time.sleep(min(sleep_time, 0.002))
            
            # Save QR analysis JSON when recording stops
            if qr_state:
                # Close any open block
                if qr_state["current"]:
                    qr_state["current"]["end_time"] = qr_state["last_time"] or frame_time_str
                    qr_state["blocks"].append(qr_state["current"])
                    logger.info(f"Closed final block {qr_state['current']['block_id']}")
                
                # Generate JSON filename (same as video but .json extension)
                json_path = video_path.replace(settings.VIDEOS_FILE_EXTENSION, ".json")
                
                # Save analysis to JSON
                save_analysis_to_json(qr_state["blocks"], json_path, video_path)
                
                # Print summary to console
                print(f"\n{'='*60}")
                print(f"📊 QR CAMERA RECORDING COMPLETE")
                print(f"{'='*60}")
                print(f"   Total frames recorded: {frame_count}")
                print(f"   Total QR detections: {qr_state['detection_count']}")
                print(f"   Valid QR blocks created: {len(qr_state['blocks'])}")
                print(f"   JSON saved to: {os.path.basename(json_path)}")
                
                if qr_state['blocks']:
                    print(f"\n   Blocks detected:")
                    for i, block in enumerate(qr_state['blocks'], 1):
                        print(f"   {i}. {block['block_id']}: {block['action']} {block['screens_index']}")
                        print(f"      {block['start_time']} → {block['end_time']}")
                else:
                    print(f"\n   ⚠️  No valid QR blocks detected!")
                    print(f"      Check that QR codes are visible in the ROI")
                    print(f"      ROI: {qr_state['roi']}")
                    print(f"      Recording area: {width}x{height} at offset ({left}, {top})")
                print(f"{'='*60}\n")
            
            elif self._camera_name == "qr-camera":
                logger.info(f"No QR codes detected during recording session")
                # Still create an empty JSON file
                json_path = video_path.replace(settings.VIDEOS_FILE_EXTENSION, ".json")
                save_analysis_to_json([], json_path, video_path)
                print(f"\n⚠️ No QR codes detected during recording session")
                print(f"   Empty JSON file created: {os.path.basename(json_path)}")
        
        except Exception as e:
            logger.error(f"Screen record failed for {self._camera_name}: {e}")
            import traceback
            traceback.print_exc()
            if self._stop_event:
                self._stop_event.set()
            raise
        
        finally:
            # Clean up resources
            if video_writer and video_writer.isOpened():
                video_writer.release()
                logger.info(f"Released VideoWriter for {self._camera_name}")

    def _connect_camera(self, address, retries=7, delay=0.5):
        for i in range(retries):
            try:
                # Force software decoding
                cap = cv2.VideoCapture(address, cv2.CAP_FFMPEG)
                if cap.isOpened():
                    return cap
            except:
                pass
            
            # Fallback to default
            cap = cv2.VideoCapture(address)
            if cap.isOpened():
                return cap
            
            time.sleep(delay)
        raise RuntimeError(f"Cannot connect to camera: {address}")

    def _read_frames(self, cap, q):
        retry = 0
        max_retries = 20
        start = time.time()
        trim = 0.1
        while not (self._cancellation_pending.value or self._stop_event.is_set()):
            ok, frame = cap.read()
            if ok:
                retry = 0
                if time.time() - start < trim:
                    continue
                if not q.full():
                    q.put(frame)
            else:
                retry += 1
                if retry >= max_retries:
                    break
                time.sleep(_TIMEOUT)

    def _write_frames(self, path, writer, q, timestamps=None):
        while not (self._cancellation_pending.value or self._stop_event.is_set()) or not q.empty():
            try:
                frame = q.get(timeout=_TIMEOUT)

                # ── NEW ────────────────────────────────────────────────
                if timestamps is not None:
                    now = datetime.now()
                    ms = now.microsecond // 1000
                    ts_str = now.strftime("%H:%M:%S.") + f"{ms:03d}"
                    timestamps.append(ts_str)
                # ───────────────────────────────────────────────────────

                writer.write(frame)
            except queue.Empty:
                pass