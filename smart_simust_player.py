"""
smart_simust_player.py - Plays videos sequentially, generates a results video after each video,
displays it for 15 seconds (or 0.5s for the last video), then continues. After the last video,
displays a final summary video. Writes current video index to file for simust_realtime.py.
Auto‑stops only the camera process when final summary is displayed; the player itself closes
after the summary video finishes, updating the status file so the frontend disables the Stop button.
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
from pathlib import Path
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt, QTimer, QRect, pyqtSignal, QUrl
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QFont
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
import vlc

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

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


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
    - Spinning gold rings in all 14 slices (floating‑point centered)
    - "Processing" / "Results" text on rounded, semi‑transparent backgrounds
    - 2–3 colourful bouncing balls per tile for a lively, professional look
    - (Slice numbers are not displayed)
    - Optional status text override (for "Generating final summary…")
    """
    def __init__(self, parent=None):
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
        self.ring_radius = 60          # matches final video ring size

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
            for i in range(self.num_slices):
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

        # Draw tile boundaries
        painter.setPen(QPen(QColor(80, 80, 100, 80), 1))
        for i in range(1, self.num_slices):
            x_line = int(i * tile_width)
            painter.drawLine(x_line, 0, x_line, h)

        # Create balls on first paint
        if self.balls_by_slice is None:
            self.balls_by_slice = []
            colors = [
                QColor(255, 50, 50), QColor(50, 255, 50), QColor(50, 150, 255),
                QColor(255, 200, 50), QColor(255, 50, 200), QColor(50, 255, 200),
                QColor(255, 150, 50), QColor(200, 50, 255), QColor(100, 255, 100),
                QColor(255, 100, 100)
            ]
            for i in range(self.num_slices):
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

        # Draw each slice
        for i, slice_num in enumerate(self.slice_order):
            offset_x = self.content_offset.get(i, 0)
            cx = int((i + 0.5) * tile_width) + offset_x
            cy = h // 2

            # Ring
            radius = min(self.ring_radius, int(tile_width // 2))
            if radius < 5:
                radius = 5

            # Background ring
            painter.setPen(QPen(QColor(60, 60, 80), int(radius * 0.25)))
            painter.drawEllipse(cx - radius, cy - radius, 2*radius, 2*radius)

            # Spinning arc
            painter.setPen(QPen(QColor(255, 193, 7), int(radius * 0.3)))
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
    # Signal now emits the video path (or empty string on failure)
    final_summary_done = pyqtSignal(str)

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

        # Waiting overlay (initially None)
        self.waiting_overlay = None

        # Connect signal for final summary completion
        self.final_summary_done.connect(self._on_final_summary_done)

        # Get video files
        self.video_files = self._get_video_files(video_directory)
        self._update_status_file("playing", 0, len(self.video_files), "Starting playback")

        if not self.video_files:
            self._update_status_file("error", 0, 0, "No video files found")
            QtWidgets.QMessageBox.critical(None, "Error", f"No video files found in:\n{video_directory}")
            self._auto_close(1000)
            sys.exit(1)

        logger.info(f"Found {len(self.video_files)} video files.")
        self.video_count = len(self.video_files)
        self.total_videos = self.video_count

        # Speed file
        self.speed_file_dir = "C:/Users/siama/Documents/simust_player"
        self.speed_file_path = os.path.join(self.speed_file_dir, "simust_speed.txt")
        self.video_index_file = os.path.join(self.speed_file_dir, "current_video_index.txt")
        try:
            os.makedirs(self.speed_file_dir, exist_ok=True)
            with open(self.speed_file_path, 'w') as f:
                f.write(str(self.player_speed))
        except:
            pass

        # VLC instance
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


        # Window
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setStyleSheet("background-color: transparent;")

        self.videoframe = QtWidgets.QFrame(self)
        self.videoframe.setStyleSheet("background-color: black; border: none;")
        self.videoframe.setFixedSize(self.video_width, self.video_height)
        self.videoframe.installEventFilter(self)

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

        # Embed VLC
        if sys.platform.startswith('linux'):
            self.player.set_xwindow(self.videoframe.winId())
        elif sys.platform == "win32":
            self.player.set_hwnd(int(self.videoframe.winId()))
        elif sys.platform == "darwin":
            self.player.set_nsobject(int(self.videoframe.winId()))

        # Start first video
        self._load_video(0)

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
        if not self._realtime_stopped:
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
            self._update_status_file("closed", self.current_video_index + 1, len(self.video_files), "Player closed")
            time.sleep(0.1)
            if os.path.exists(self.status_file):
                os.remove(self.status_file)
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

    def _load_video(self, index):
        self._hide_waiting_overlay()
        if 0 <= index < len(self.video_files):
            self.player.stop()
            self.check_timer.stop()
            self.current_video_index = index
            self.current_video_path = self.video_files[index]
            self.video_start_time = time.time()
            self.video_end_called = False
            logger.info(f"Loading video {index+1}/{len(self.video_files)}: {os.path.basename(self.current_video_path)}")
            self._update_status_file("loading", index+1, len(self.video_files), f"Loading: {os.path.basename(self.current_video_path)}")
            try:
                with open(self.video_index_file, 'w') as f:
                    f.write(str(index + 1))
            except Exception as e:
                logger.error(f"Failed to write video index file: {e}")
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
        if self.play_delay_timer:
            self.play_delay_timer.stop()
            self.play_delay_timer = None
        logger.info("Starting playback now.")
        self.player.set_time(0)
        self.player.video_set_aspect_ratio("3712:512")
        self.player.video_set_scale(1.0)
        self.player.video_set_crop_geometry("0:0:3712:512")
        self.player.play()
        self._update_progress_display()
        self.completion_label.hide()
        self.playlist_finished = False
        self.waiting_for_results = False
        self.check_timer.start()

    def _update_progress_display(self):
        current = self.current_video_index + 1
        total = len(self.video_files)
        name = os.path.basename(self.current_video_path)
        if len(name) > 40:
            name = name[:37] + "..."
        self.progress_label.setText(f"Video {current}/{total} | {name}")
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
        self._update_status_file("playing", 0, total, f"Playlist loaded: {total} videos")
        logger.info(f"Playlist loaded: {total} videos")

    def _show_waiting_overlay(self, status_text="Processing Results..."):
        if self.waiting_overlay is None:
            self.waiting_overlay = WaitingOverlay(self.videoframe)
            self.videoframe.installEventFilter(self)
        self.waiting_overlay.set_status_text(status_text)
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

    def _find_latest_report(self):
        realtime_dir = "C:/Users/siama/Documents/simust_realtime_recordings"
        if os.path.exists(realtime_dir):
            subdirs = [d for d in os.listdir(realtime_dir) if os.path.isdir(os.path.join(realtime_dir, d))]
            if subdirs:
                subdirs.sort(key=lambda d: os.path.getctime(os.path.join(realtime_dir, d)), reverse=True)
                newest = os.path.join(realtime_dir, subdirs[0])
                for fname in ["recognition.json", "recognition_report.json"]:
                    path = os.path.join(newest, fname)
                    if os.path.exists(path):
                        return path
        return None

    def _trigger_results_for_video(self, report_path, video_num, start_time, end_time, is_last_video=False):
        logger.info(f"Triggering results for video {video_num} (start={start_time}, end={end_time})")
        backend_url = "http://127.0.0.1:8000/create-video-results"
        payload = {
            "report_path": report_path,
            "start_time": start_time,
            "end_time": end_time,
            "video_index": video_num,
            "total_videos": self.total_videos
        }
        success = False
        if HAS_REQUESTS:
            try:
                response = requests.post(backend_url, json=payload, timeout=30)
                if response.status_code == 200:
                    success = True
                    logger.info(f"Results video for video {video_num} generated.")
                else:
                    logger.error(f"Backend error: {response.text}")
            except Exception as e:
                logger.error(f"Request failed: {e}")
        else:
            try:
                import urllib.request
                req = urllib.request.Request(backend_url, data=json.dumps(payload).encode('utf-8'),
                                             headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    if resp.getcode() == 200:
                        success = True
            except Exception as e:
                logger.error(f"urllib failed: {e}")

        if success:
            self._hide_waiting_overlay()
            self.waiting_for_results = True
            self.show_status(f"Video {video_num} results on Screen 2", 1000)
            if self.results_timer:
                self.results_timer.stop()
            self.results_timer = QtCore.QTimer(singleShot=True)
            delay_ms = 500 if is_last_video else 15000
            self.results_timer.timeout.connect(self._continue_to_next_video)
            self.results_timer.start(delay_ms)
        else:
            self._hide_waiting_overlay()
            self._continue_to_next_video()

    def _continue_to_next_video(self):
        self.waiting_for_results = False
        if self.results_timer:
            self.results_timer.stop()
            self.results_timer = None
        self._hide_waiting_overlay()
        self._do_continue()

    def _do_continue(self):
        self.current_video_index += 1
        if self.current_video_index < len(self.video_files):
            self._load_video(self.current_video_index)
        else:
            self._show_final_summary()

    def _show_final_summary(self):
        logger.info("Processing Final Results")
        self._show_waiting_overlay("Processing Final Results")
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
        try:
            response = requests.post(backend_url, json={"report_path": report_path}, timeout=60)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    video_path = data.get("video_path")
                    if video_path and os.path.exists(video_path):
                        self.final_summary_done.emit(video_path)
                        return
            # If we reach here, something went wrong
            self.final_summary_done.emit("")
        except Exception as e:
            logger.error(f"Final summary request failed: {e}")
            self.final_summary_done.emit("")

    def _force_close_with_completion(self):
        """Fallback: close player and set status to completed."""
        if not self._is_closing:
            self._update_status_file("completed", self.total_videos, self.total_videos, "Playback completed (timeout)")
            self.close()

    def _on_final_summary_done(self, video_path):
        self._hide_waiting_overlay()
        if video_path and os.path.exists(video_path):
            # Set status to "playing_final" – not "completed" yet
            self._update_status_file("playing_final", self.total_videos, self.total_videos, "Playing final summary...")
            logger.info(f"Playing final summary video: {video_path}")
            self.player.stop()
            self.media = self.instance.media_new(os.path.abspath(video_path))
            self.player.set_media(self.media)
            self.player.video_set_aspect_ratio("3712:512")
            self.player.video_set_scale(1.0)
            self.player.video_set_crop_geometry("0:0:3712:512")
            self.player.play()

            self.completion_label.setText("Final summary playing...")
            self.completion_label.adjustSize()
            self.completion_label.move((self.video_width - self.completion_label.width()) // 2,
                                       (self.video_height - self.completion_label.height()) // 2)
            self.completion_label.show()

            # Indicate that we are in final video mode
            self.playlist_finished = True
            self.check_timer.start()

            # Fallback: close after 60 seconds (in case the video never ends)
            QTimer.singleShot(60000, self._force_close_with_completion)
        else:
            self._update_status_file("error", self.total_videos, self.total_videos, "Final summary failed to generate")
            self.completion_label.setText("Final summary failed to generate.")
            self.completion_label.adjustSize()
            self.completion_label.move((self.video_width - self.completion_label.width()) // 2,
                                       (self.video_height - self.completion_label.height()) // 2)
            self.completion_label.show()
            self._auto_close(5000)

        self._stop_camera_only()
        # Do not set status to "completed" here – it will be set when video ends

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
        if self.video_end_called or self.waiting_for_results:
            return
        self.video_end_called = True
        self.check_timer.stop()
        self._show_waiting_overlay("Processing Results...")
        video_num = self.current_video_index + 1
        is_last_video = (video_num == self.total_videos)
        logger.info(f"Video {video_num} ended. is_last_video={is_last_video}")
        self.player.stop()
        QTimer.singleShot(3000, lambda: self._trigger_results_after_delay(video_num, is_last_video))

    def _trigger_results_after_delay(self, video_num, is_last_video):
        report_path = self._find_latest_report()
        if not report_path:
            logger.warning("No report found – skipping per‑video results.")
            self._hide_waiting_overlay()
            QTimer.singleShot(500, self._continue_to_next_video)
            return
        start_time = self.video_start_time
        end_time = time.time()
        self._trigger_results_for_video(report_path, video_num, start_time, end_time, is_last_video)

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

    def _check_video_position(self):
        if self._is_closing:
            return
        if not self.player:
            return

        try:
            state = self.player.get_state()

            # If we're playing the final video (playlist_finished is True)
            if self.playlist_finished:
                if state == vlc.State.Ended:
                    logger.info("Final video finished – updating status and closing.")
                    self._update_status_file("completed", self.total_videos, self.total_videos, "Playback completed")
                    self.close()
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
    if len(sys.argv) < 2:
        app = QtWidgets.QApplication(sys.argv)
        QtWidgets.QMessageBox.critical(None, "Error",
            "Usage: smart_simust_player.py <video-directory> [player_speed] [screen_index]")
        sys.exit(1)

    video_dir = sys.argv[1]
    if not os.path.isdir(video_dir):
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