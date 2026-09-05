"""
SIMUST PLAY IT SMART - Main Application (REALTIME ONLY)
Soccer Action Analysis System with Player Tracking
"""

import os
import json
import socket
import logging
import tempfile
import subprocess
import multiprocessing
import urllib.parse
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import uvicorn
import asyncio
import math
import shutil
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, ValidationError
import sys
import threading
import time
import atexit
import gc
import re

import hashlib
import json
import uuid
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr

from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from simust_security import (
    PUBLIC_MODE,
    can_access_player,
    check_auth_rate,
    cors_origins,
    current_user,
    hash_password,
    is_lab_only_path,
    issue_token,
    verify_password,
)
import simust_push

if PUBLIC_MODE:
    cv2 = None
    np = None
    Image = ImageDraw = ImageFont = None
else:
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch

app = FastAPI()
_CORS_ORIGINS = cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=_CORS_ORIGINS != ["*"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-SIMUST-PUSH-KEY", "X-SIMUST-TS", "X-SIMUST-SIGN"],
)


@app.middleware("http")
async def guard_lab_only_on_public_host(request: Request, call_next):
    if PUBLIC_MODE and is_lab_only_path(request.url.path):
        return JSONResponse(
            {"detail": "This action is only available on the training machine."},
            status_code=403,
        )
    return await call_next(request)

os.makedirs("static", exist_ok=True)   

USERS_FILE = "users.json"

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2, ensure_ascii=False)


ADMIN_NOTIFY_EMAIL = os.environ.get("ADMIN_NOTIFY_EMAIL", "robotvision03@gmail.com")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9][0-9\s\-()]{5,20}$")


def send_registration_email(user_info: dict) -> bool:
    """Notify admin of a new registration. Uses SMTP_USER / SMTP_PASSWORD env vars."""
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", os.environ.get("SMTP_USERNAME", "")).strip()
    smtp_pass = os.environ.get("SMTP_PASSWORD", os.environ.get("SMTP_PASS", "")).strip()
    smtp_from = os.environ.get("SMTP_FROM", smtp_user).strip()
    admin_to = ADMIN_NOTIFY_EMAIL

    log = logging.getLogger(__name__)
    if not smtp_user or not smtp_pass:
        log.warning(
            "SMTP_USER / SMTP_PASSWORD are not set. Registration email to %s was not sent.",
            admin_to,
        )
        return False

    lines = [
        "A new user registered on My SIMUST.",
        "",
        f"Username: {user_info.get('username', '')}",
        f"Name: {user_info.get('name', '')} {user_info.get('surname', '')}",
        f"Email: {user_info.get('email', '')}",
        f"Phone: {user_info.get('phone', '')}",
        f"Role: {user_info.get('role', '')}",
        f"Club: {user_info.get('club', '')}",
        f"Team: {user_info.get('team', '')}",
        f"Age: {user_info.get('age', '')}",
        f"Gender: {user_info.get('gender', '')}",
        f"Time: {datetime.now().isoformat(timespec='seconds')}",
    ]
    msg = MIMEText("\n".join(lines), "plain", "utf-8")
    msg["Subject"] = f"SIMUST registration: {user_info.get('username', '')}"
    msg["From"] = formataddr(("SIMUST", smtp_from or smtp_user))
    msg["To"] = admin_to
    if user_info.get("email"):
        msg["Reply-To"] = user_info["email"]

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from or smtp_user, [admin_to], msg.as_string())
        log.info("Registration email sent to %s for user %s", admin_to, user_info.get("username"))
        return True
    except Exception as e:
        log.error("Failed to send registration email: %s", e, exc_info=True)
        return False


# ============================================================
# TRAINING PLACE RESERVATIONS
# Shared calendar: 30-minute grid, 07:00–22:00 local, 30–180 min slots
# ============================================================

RESERVATIONS_FILE = "reservations.json"
RESERVATION_LOCK = threading.Lock()
RESERVATION_OPEN_HOUR = 7
RESERVATION_CLOSE_HOUR = 22
RESERVATION_SLOT_MINUTES = 30
RESERVATION_MIN_MINUTES = 30
RESERVATION_MAX_MINUTES = 180
RESERVATION_STAFF_ROLES = {"coach", "manager", "admin"}


def load_reservations():
    if not os.path.exists(RESERVATIONS_FILE):
        return []
    try:
        with open(RESERVATIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            items = data.get("reservations", [])
            return items if isinstance(items, list) else []
    except (json.JSONDecodeError, OSError) as e:
        logging.getLogger(__name__).error("Failed to load reservations.json: %s", e)
    return []


def save_reservations(items):
    tmp = RESERVATIONS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    os.replace(tmp, RESERVATIONS_FILE)


def _parse_iso_dt(value: str, field: str = "datetime") -> datetime:
    if not value or not str(value).strip():
        raise HTTPException(400, f"{field} is required")
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise HTTPException(400, f"Invalid {field}")
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.replace(microsecond=0)


def _parse_range_bound(value: str, end_of_day: bool = False) -> Optional[datetime]:
    if not value or not str(value).strip():
        return None
    raw = str(value).strip()
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        try:
            day = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, "Invalid date range")
        if end_of_day:
            return day + timedelta(days=1)
        return day
    return _parse_iso_dt(raw, "date range")


def _on_half_hour_grid(dt: datetime) -> bool:
    return dt.second == 0 and dt.minute in (0, 30)


def _intervals_overlap(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a < end_b and start_b < end_a


def _player_display_name(user: dict, username: str) -> str:
    name = " ".join(
        part for part in [(user or {}).get("name", ""), (user or {}).get("surname", "")] if part
    ).strip()
    return name or username


def _public_reservation(item: dict) -> dict:
    start = _parse_iso_dt(item.get("start", ""), "start")
    end = _parse_iso_dt(item.get("end", ""), "end")
    duration = int((end - start).total_seconds() // 60)
    public = {
        "id": item.get("id"),
        "player_id": item.get("player_id", ""),
        "player_name": item.get("player_name") or "Booked",
        "start": start.isoformat(timespec="seconds"),
        "end": end.isoformat(timespec="seconds"),
        "duration_minutes": duration,
    }
    if item.get("payment_status"):
        public["payment_status"] = item.get("payment_status")
    return public


def _format_duration_label(minutes: int) -> str:
    hours, mins = divmod(int(minutes), 60)
    parts = []
    if hours:
        parts.append(f"{hours} hour" if hours == 1 else f"{hours} hours")
    if mins:
        parts.append(f"{mins} minutes")
    return " ".join(parts) if parts else f"{minutes} minutes"


def send_reservation_email(booking: dict, user_info: dict) -> bool:
    """Notify admin of a new training-place reservation. Same SMTP pattern as registration."""
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", os.environ.get("SMTP_USERNAME", "")).strip()
    smtp_pass = os.environ.get("SMTP_PASSWORD", os.environ.get("SMTP_PASS", "")).strip()
    smtp_from = os.environ.get("SMTP_FROM", smtp_user).strip()
    admin_to = ADMIN_NOTIFY_EMAIL

    log = logging.getLogger(__name__)
    if not smtp_user or not smtp_pass:
        log.warning(
            "SMTP_USER / SMTP_PASSWORD are not set. Reservation email to %s was not sent.",
            admin_to,
        )
        return False

    start = _parse_iso_dt(booking.get("start", ""), "start")
    end = _parse_iso_dt(booking.get("end", ""), "end")
    duration = int((end - start).total_seconds() // 60)
    player_email = (user_info or {}).get("email", "")
    lines = [
        "A training-place reservation was confirmed on My SIMUST.",
        "",
        f"Player: {booking.get('player_name', '')}",
        f"Username: {booking.get('player_id', '')}",
        f"Email: {player_email}",
        f"Date: {start.strftime('%A, %d %B %Y')}",
        f"Start: {start.strftime('%H:%M')}",
        f"End: {end.strftime('%H:%M')}",
        f"Duration: {_format_duration_label(duration)} ({duration} minutes)",
        f"Reservation ID: {booking.get('id', '')}",
        f"Time: {datetime.now().isoformat(timespec='seconds')}",
    ]
    msg = MIMEText("\n".join(lines), "plain", "utf-8")
    msg["Subject"] = f"SIMUST reservation: {booking.get('player_name', booking.get('player_id', ''))} {start.strftime('%Y-%m-%d %H:%M')}"
    msg["From"] = formataddr(("SIMUST", smtp_from or smtp_user))
    msg["To"] = admin_to
    if player_email:
        msg["Reply-To"] = player_email

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from or smtp_user, [admin_to], msg.as_string())
        log.info("Reservation email sent to %s for %s", admin_to, booking.get("player_id"))
        return True
    except Exception as e:
        log.error("Failed to send reservation email: %s", e, exc_info=True)
        return False


def _validate_reservation_window(start: datetime, end: datetime) -> int:
    now = datetime.now().replace(microsecond=0)
    if end <= start:
        raise HTTPException(400, "End time must be after start time")
    if start < now:
        raise HTTPException(400, "Reservations cannot start in the past")
    duration = int((end - start).total_seconds() // 60)
    if (end - start).total_seconds() % 60:
        raise HTTPException(400, "Reservations must use whole minutes")
    if duration < RESERVATION_MIN_MINUTES or duration > RESERVATION_MAX_MINUTES:
        raise HTTPException(400, "Slot length must be between 30 minutes and 3 hours")
    if duration % RESERVATION_SLOT_MINUTES != 0:
        raise HTTPException(400, "Slot length must be a multiple of 30 minutes")
    if start.date() != end.date():
        raise HTTPException(400, "Reservations must stay within a single day")
    open_t = datetime.combine(start.date(), datetime.min.time()).replace(hour=RESERVATION_OPEN_HOUR)
    close_t = datetime.combine(start.date(), datetime.min.time()).replace(hour=RESERVATION_CLOSE_HOUR)
    if start < open_t or end > close_t:
        raise HTTPException(400, "Reservations are only available from 07:00 to 22:00")
    if not _on_half_hour_grid(start) or not _on_half_hour_grid(end):
        raise HTTPException(400, "Start and end must align to the 30-minute grid")
    return duration
        
# ============================================================
# PROGRESSION SYSTEM (UPDATED for Foundation thresholds)
# ============================================================

PROGRESSION = {
    "L00-Foundation": {
        "display": "Foundation",
        # Thresholds for SF-180N: need 70% AE and 70% ACC to unlock Entry
        "threshold_acc": 70,
        "threshold_ae": 70,
        "themes": {"Foundation": ["Foundation"]}
    },
    "L01-Entry": {
        "display": "Entry",
        "threshold_acc": 80,
        "threshold_ae": 75,
        "themes": {
            "A-T1": ["C1","C2","C3","C4","C5"],
            "A-T2": ["C1","C2","C3","C4","C5"],
            "A-T3": ["C1","C2","C3","C4","C5"],
            "A-T4": ["C1","C2","C3","C4","C5"],
            "A-T5": ["C1","C2","C3","C4","C5"]
        }
    },
    "L02-Activated": {
        "display": "Activated",
        "threshold_acc": 85,
        "threshold_ae": 80,
        "themes": {
            "A-T1": ["C1","C2","C3","C4","C5"],
            "A-T2": ["C1","C2","C3","C4","C5"],
            "A-T3": ["C1","C2","C3","C4","C5"],
            "A-T4": ["C1","C2","C3","C4","C5"],
            "A-T5": ["C1","C2","C3","C4","C5"]
        }
    },
    "L03-HighPerformance": {
        "display": "High Performance",
        "threshold_acc": 90,
        "threshold_ae": 85,
        "themes": {
            "A-T1": ["C1","C2","C3","C4","C5"],
            "A-T2": ["C1","C2","C3","C4","C5"],
            "A-T3": ["C1","C2","C3","C4","C5"],
            "A-T4": ["C1","C2","C3","C4","C5"],
            "A-T5": ["C1","C2","C3","C4","C5"]
        }
    },
    "L04-Elite": {
        "display": "Elite",
        "threshold_acc": 95,
        "threshold_ae": 90,
        "themes": {
            "A-T1": ["C1","C2","C3","C4","C5"],
            "A-T2": ["C1","C2","C3","C4","C5"],
            "A-T3": ["C1","C2","C3","C4","C5"],
            "A-T4": ["C1","C2","C3","C4","C5"],
            "A-T5": ["C1","C2","C3","C4","C5"]
        }
    },
    "L05-WorldClass": {
        "display": "World Class",
        "threshold_acc": 98,
        "threshold_ae": 95,
        "themes": {
            "A-T1": ["C1","C2","C3","C4","C5"],
            "A-T2": ["C1","C2","C3","C4","C5"],
            "A-T3": ["C1","C2","C3","C4","C5"],
            "A-T4": ["C1","C2","C3","C4","C5"],
            "A-T5": ["C1","C2","C3","C4","C5"]
        }
    }
}

def get_all_level_ids():
    """
    Returns a flat list of all challenge IDs in order.
    For Foundation: "L00-Foundation"
    For others: "L01-Entry/A-T1/A.T1.C1" etc.
    """
    ids = []
    for main_id, config in PROGRESSION.items():
        if main_id == "L00-Foundation":
            ids.append("L00-Foundation")
        else:
            for theme, challenges in config["themes"].items():
                for ch in challenges:
                    # e.g., A.T1.C1
                    challenge_name = f"A.{theme[2:]}.{ch}" if theme.startswith("A-") else f"{theme}.{ch}"
                    ids.append(f"{main_id}/{theme}/{challenge_name}")
    return ids

ALL_LEVELS = get_all_level_ids()

def get_level_path(level_id: str) -> str:
    """
    Convert level ID to filesystem path under SIMUST_PLAYER_DIRECTORY.
    For L00-Foundation, we return a special path (will be handled as a special case).
    """
    if level_id == "L00-Foundation":
        return os.path.join(SIMUST_PLAYER_DIRECTORY, "L00-Foundation-Challenge")
    # e.g., "L01-Entry/A-T1/A.T1.C1" -> "L01-Entry/A-T1/A.T1.C1"
    return os.path.join(SIMUST_PLAYER_DIRECTORY, *level_id.split('/'))

def get_main_level(level_id: str) -> str:
    """Return the main level ID (e.g., 'L01-Entry') from a challenge ID."""
    if level_id == "L00-Foundation":
        return "L00-Foundation"
    return level_id.split('/')[0]  # first part

def get_next_level(current_level_id: str) -> Optional[str]:
    """Return the next level ID in ALL_LEVELS after current_level_id, or None if it's the last."""
    try:
        idx = ALL_LEVELS.index(current_level_id)
        if idx + 1 < len(ALL_LEVELS):
            return ALL_LEVELS[idx + 1]
    except ValueError:
        pass
    return None

def get_level_thresholds(level_id: str) -> Tuple[float, float]:
    """Return (threshold_acc, threshold_ae) for the given level ID."""
    main = get_main_level(level_id)
    config = PROGRESSION.get(main)
    if config:
        return config["threshold_acc"], config["threshold_ae"]
    return 0, 0

# Force TCP for RTSP (more reliable than UDP)
os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp'
os.environ['OPENCV_LOG_LEVEL'] = 'ERROR'

# Add current directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# ============================================================
# Directory Configuration
# ============================================================
# Training-lab Windows paths stay the default on Windows.
# On a public Linux host (my.simust.com) use local folders unless env vars are set,
# so player reports are not expected at C:\Users\siama\...
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if os.name == "nt":
    _DEFAULT_PLAYER_DIR = "C:/Users/siama/Documents/simust_player"
    _DEFAULT_REPORTS_DIR = "C:/Users/siama/Documents/simust_reports"
    _DEFAULT_REALTIME_DIR = "C:/Users/siama/Documents/simust_realtime_recordings"
    _DEFAULT_ANIMATIONS_DIR = "C:/Users/siama/Documents/_Sia/Animations"
else:
    _DEFAULT_PLAYER_DIR = os.path.join(_APP_DIR, "simust_player")
    _DEFAULT_REPORTS_DIR = os.path.join(_APP_DIR, "simust_reports")
    _DEFAULT_REALTIME_DIR = os.path.join(_APP_DIR, "simust_realtime_recordings")
    _DEFAULT_ANIMATIONS_DIR = os.path.join(_APP_DIR, "animations")

SIMUST_PLAYER_DIRECTORY = os.environ.get("SIMUST_PLAYER_DIRECTORY", _DEFAULT_PLAYER_DIR)
PLAYER_REPORTS_DIR = os.environ.get("SIMUST_REPORTS_DIR", _DEFAULT_REPORTS_DIR)
REALTIME_RECORDINGS_DIR = os.environ.get("SIMUST_REALTIME_DIR", _DEFAULT_REALTIME_DIR)
ANIMATIONS_DIR = os.environ.get("SIMUST_ANIMATIONS_DIR", _DEFAULT_ANIMATIONS_DIR)

# Ensure directories exist
os.makedirs(PLAYER_REPORTS_DIR, exist_ok=True)
os.makedirs(SIMUST_PLAYER_DIRECTORY, exist_ok=True)
os.makedirs(REALTIME_RECORDINGS_DIR, exist_ok=True)
os.makedirs(ANIMATIONS_DIR, exist_ok=True)

# ============================================================
# Calibration
# ============================================================
PIXEL_TO_METER_SCALE = 0.0259

# ============================================================
# Local imports
# ============================================================
if PUBLIC_MODE:
    prepare_video_recorders = None
    capture_videos = None

    class _PublicRecorderSettings:
        CAMERAS: Dict[str, dict] = {}

    recorder_settings = _PublicRecorderSettings()
else:
    from recorder.main import prepare_video_recorders, capture_videos
    from recorder import settings as recorder_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ============================================================
# Global Variables
# ============================================================

recording_process: Optional[multiprocessing.Process] = None
video_recorders: Optional[Dict] = None
barrier: Optional[multiprocessing.Barrier] = None
stop_event: Optional[multiprocessing.Event] = None
last_output_path: Optional[str] = None
current_results_dir: Optional[str] = None
current_camera_statuses: Dict[str, str] = {}
current_selections: Dict[str, bool] = {}
output_path = "C:/Users/siama/Documents/record"
smart_player_process = None
realtime_camera_process = None

# ============================================================
# Helper Functions
# ============================================================

def is_frozen():
    return getattr(sys, 'frozen', False)

def get_newest_realtime_session_folder():
    if not os.path.exists(REALTIME_RECORDINGS_DIR):
        return None
    subdirs = [d for d in os.listdir(REALTIME_RECORDINGS_DIR) if os.path.isdir(os.path.join(REALTIME_RECORDINGS_DIR, d))]
    if not subdirs:
        return None
    subdirs.sort(key=lambda d: os.path.getctime(os.path.join(REALTIME_RECORDINGS_DIR, d)), reverse=True)
    return os.path.join(REALTIME_RECORDINGS_DIR, subdirs[0])

def get_latest_recording_directory():
    if not output_path or not os.path.exists(output_path):
        return None
    try:
        subdirs = [d for d in os.listdir(output_path) if os.path.isdir(os.path.join(output_path, d))]
        if not subdirs:
            return None
        latest = max(subdirs, key=lambda d: os.path.getctime(os.path.join(output_path, d)))
        return os.path.join(output_path, latest)
    except Exception as e:
        logger.error(f"Failed to get latest directory: {e}")
        return None

def force_kill_smart_player():
    global smart_player_process
    try:
        if smart_player_process and smart_player_process.poll() is None:
            smart_player_process.terminate()
            time.sleep(1)
            if smart_player_process.poll() is None:
                smart_player_process.kill()
            smart_player_process = None
    except:
        pass
    if sys.platform == "win32":
        try:
            subprocess.run(['taskkill', '/F', '/FI', 'WINDOWTITLE eq Smart Player*'], capture_output=True)
            os.system('taskkill /F /IM python.exe /FI "CMDLine eq *smart_simust_player*" 2>nul')
        except:
            pass
    gc.collect()
    time.sleep(1)

atexit.register(force_kill_smart_player)

def get_video_duration(video_path: str) -> float:
    try:
        cap = cv2.VideoCapture(video_path)
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()
            if fps > 0:
                return frame_count / fps
    except Exception as e:
        logger.error(f"Failed to get duration for {video_path}: {e}")
    return 0

def _get_video_info(directory: str) -> dict:
    if not os.path.exists(directory):
        raise HTTPException(404, "Directory not found")
    info = []
    ffprobe_cmd = None
    ffprobe_paths = [
        r"C:\Program Files\ffmpeg\bin\ffprobe.exe",
        r"C:\ffmpeg\bin\ffprobe.exe",
        "ffprobe",
    ]
    for path in ffprobe_paths:
        try:
            subprocess.run([path, "-version"], capture_output=True, check=True, timeout=5)
            ffprobe_cmd = path
            break
        except:
            continue
    video_files = [f for f in os.listdir(directory) if f.endswith(".mp4")]
    for f in video_files:
        file_path = os.path.join(directory, f)
        video_info = {
            "camera": f[:-4],
            "frame_count": "N/A",
            "start_time": "N/A",
            "duration": "N/A",
            "file_size": "N/A",
            "resolution": "N/A"
        }
        try:
            file_size = os.path.getsize(file_path)
            video_info["file_size"] = f"{file_size / (1024*1024):.2f} MB"
        except:
            pass
        try:
            cap = cv2.VideoCapture(file_path, cv2.CAP_FFMPEG)
            if cap.isOpened():
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                fps = cap.get(cv2.CAP_PROP_FPS)
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                if frame_count > 0:
                    video_info["frame_count"] = str(frame_count)
                    video_info["duration"] = f"{frame_count / fps:.2f} s" if fps > 0 else "N/A"
                if width > 0 and height > 0:
                    video_info["resolution"] = f"{width}x{height}"
                cap.release()
        except Exception as e:
            logger.warning(f"OpenCV failed for {f}: {e}")
        if ffprobe_cmd and (video_info["frame_count"] == "N/A" or video_info["duration"] == "N/A"):
            try:
                cmd = [
                    ffprobe_cmd, "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=width,height,r_frame_rate,duration",
                    "-of", "json", file_path
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    js = json.loads(result.stdout)
                    if js.get("streams"):
                        s = js["streams"][0]
                        duration = s.get("duration")
                        fps_str = s.get("r_frame_rate")
                        if duration and fps_str and '/' in fps_str:
                            num, den = map(int, fps_str.split('/'))
                            fps = num / den if den > 0 else 0
                            if fps > 0:
                                video_info["frame_count"] = str(int(float(duration) * fps))
                        video_info["duration"] = duration or "N/A"
                        video_info["start_time"] = s.get("start_time", "N/A")
                        if video_info["resolution"] == "N/A":
                            w, h = s.get("width"), s.get("height")
                            if w and h:
                                video_info["resolution"] = f"{w}x{h}"
            except Exception as e:
                logger.warning(f"ffprobe failed for {f}: {e}")
        info.append(video_info)
    return {
        "results": info,
        "directory": directory,
        "ffprobe_available": ffprobe_cmd is not None
    }

# ============================================================
# FastAPI App
# ============================================================

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

class OutputPath(BaseModel):
    path: str
    cameras: dict

class CameraSelections(BaseModel):
    cameras: dict
    output_path: str

# ============================================================
# Camera Status Functions
# ============================================================

async def _check_single_camera(cam_name: str, cfg: dict, timeout: float = 2.0) -> Dict[str, str]:
    status = "Not Ready"
    sock = None
    try:
        if cfg.get("screen_record", False):
            status = "Ready"
            return {"name": cam_name, "status": status}
        url = urllib.parse.urlparse(cfg["address"])
        host = url.hostname
        port = url.port or 554
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None, lambda: sock.connect((host, int(port)))
            ),
            timeout=timeout,
        )
        status = "Ready"
    except asyncio.TimeoutError:
        logger.warning(f"{cam_name} timed out")
    except Exception as exc:
        logger.error(f"{cam_name} error: {exc}")
    finally:
        if sock:
            sock.close()
    return {"name": cam_name, "status": status}

async def check_all_cameras_status() -> List[Dict[str, str]]:
    tasks = [
        _check_single_camera(name, cfg)
        for name, cfg in recorder_settings.CAMERAS.items()
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    cams = []
    for r in results:
        if isinstance(r, Exception):
            continue
        current_camera_statuses[r["name"]] = r["status"]
        cams.append(r)
    return cams

# ============================================================
# Lifespan Management
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global current_selections, current_results_dir, output_path
    if PUBLIC_MODE:
        current_selections = {}
        current_results_dir = None
        logger.info("Public host mode: training-machine APIs are blocked; player data requires sign-in")
    else:
        logger.info("App start – checking cameras")
        await check_all_cameras_status()
        current_selections = {c: False for c in recorder_settings.CAMERAS.keys()}
        current_results_dir = None
        logger.info(f"Initialized selections: {list(current_selections.keys())}")
    logger.info(f"SIMUST_PLAYER directory: {SIMUST_PLAYER_DIRECTORY}")
    logger.info(f"Player reports directory: {PLAYER_REPORTS_DIR}")
    if not os.environ.get("SIMUST_SESSION_SECRET"):
        logger.warning("SIMUST_SESSION_SECRET is not set; login sessions reset when the app restarts")
    if simust_push.push_configured():
        logger.info("Lab→host JSON push is enabled")
        try:
            flushed = simust_push.flush_queue()
            if flushed:
                logger.info("Flushed %s queued player JSON payloads to the host", flushed)
        except Exception as exc:
            logger.warning("Could not flush push queue: %s", exc)
    yield
    logger.info("App shutdown")
    force_kill_smart_player()

app.router.lifespan_context = lifespan

# ============================================================
# API Endpoints
# ============================================================

@app.exception_handler(ValidationError)
async def validation_exc(_: Request, exc: ValidationError):
    return JSONResponse(status_code=400, content={"detail": exc.errors()})

@app.get("/", response_class=FileResponse)
async def root():
    if PUBLIC_MODE:
        return _my_simust_page()
    return FileResponse("index.html")

@app.get("/cameras")
async def get_cameras():
    cams = [{"name": n, "status": current_camera_statuses.get(n, "Not Ready")} for n in recorder_settings.CAMERAS.keys()]
    return {"cameras": cams}

@app.post("/check-status")
async def check_status():
    await check_all_cameras_status()
    return {"status": "check_complete"}

@app.get("/selections")
async def get_selections():
    return {
        "cameras": current_selections,
        "output_path": output_path,
    }

@app.post("/selections")
async def save_selections(sel: CameraSelections):
    global current_selections, output_path
    current_selections = {k: bool(v) for k, v in sel.cameras.items()}
    output_path = sel.output_path
    return {"status": "saved"}

@app.post("/start")
async def start_recording(req: Request):
    global recording_process, video_recorders, barrier, stop_event, last_output_path, current_results_dir
    if recording_process and recording_process.is_alive():
        raise HTTPException(400, "Recording already running")
    payload = await req.json()
    out = OutputPath(**payload)
    last_output_path = out.path
    current_results_dir = None
    selected = [c for c, on in out.cameras.items() if on]
    if not selected:
        raise HTTPException(400, "No cameras selected")
    ready = {c: recorder_settings.CAMERAS[c] for c in selected if current_camera_statuses.get(c) == "Ready"}
    if not ready:
        raise HTTPException(400, "No ready cameras")
    video_recorders, barrier, stop_event = prepare_video_recorders(list(ready.keys()))
    recording_process = multiprocessing.Process(
        target=capture_videos,
        args=(video_recorders, barrier, stop_event, out.path),
        daemon=False,
    )
    recording_process.start()
    logger.info(f"Recording started with cameras: {list(ready.keys())} to {out.path}")
    return {"status": "Recording started"}

@app.post("/stop")
async def stop_recording():
    global recording_process, stop_event, video_recorders, current_results_dir
    if not recording_process or not recording_process.is_alive():
        raise HTTPException(400, "No recording in progress")
    stop_event.set()
    recording_process.join(timeout=12)
    if recording_process.is_alive():
        recording_process.terminate()
    await asyncio.sleep(3)
    gc.collect()
    if video_recorders:
        for r in video_recorders.values():
            try:
                r.stop()
            except:
                pass
    recording_process = None
    video_recorders = None
    barrier = None
    stop_event = None
    current_results_dir = None
    logger.info("Recording stopped and cleaned up")
    return {"status": "Recording stopped"}

# ============================================================
# SIMUST_PLAYER Integration Endpoints
# ============================================================

@app.post("/set-simust-speed")
async def set_simust_speed(req: Request):
    try:
        data = await req.json()
        speed = float(data.get("speed", 1.0))
        speed = max(0.25, min(4.0, speed))
        speed_file = os.path.join(SIMUST_PLAYER_DIRECTORY, "simust_speed.txt")
        with open(speed_file, 'w') as f:
            f.write(str(speed))
        logger.info(f"SIMUST_PLAYER speed set to: {speed}x")
        return {"status": "success", "speed": speed}
    except Exception as e:
        logger.error(f"Failed to set speed: {e}")
        raise HTTPException(500, f"Failed to set speed: {str(e)}")
        
@app.get("/get-simust-speed")
async def get_simust_speed():
    try:
        speed_file = os.path.join(SIMUST_PLAYER_DIRECTORY, "simust_speed.txt")
        if os.path.exists(speed_file):
            with open(speed_file, 'r') as f:
                speed = float(f.read().strip())
            return {"speed": speed}
        else:
            return {"speed": 1.0}
    except Exception as e:
        logger.error(f"Failed to get speed: {e}")
        return {"speed": 1.0}

@app.get("/get-levels")
async def get_levels():
    try:
        # Return the list of ALL_LEVELS with existence info
        levels_info = []
        for level_id in ALL_LEVELS:
            path = get_level_path(level_id)
            exists = os.path.isdir(path)
            # For Foundation, we may not have videos; we'll treat it as always existing
            if level_id == "L00-Foundation":
                exists = True  # we'll create a virtual entry
            video_count = 0
            if exists:
                videos = [f for f in os.listdir(path) if f.lower().endswith('.mp4')]
                video_count = len(videos)
            # Determine display name
            main = get_main_level(level_id)
            display = PROGRESSION[main]["display"]
            # For challenge levels, append theme/challenge
            if level_id != "L00-Foundation":
                parts = level_id.split('/')
                display += f" {parts[1]} {parts[2]}"
            levels_info.append({
                "id": level_id,
                "display": display,
                "path": path,
                "exists": exists,
                "video_count": video_count,
                "level_num": ALL_LEVELS.index(level_id) + 1  # just for ordering
            })
        return {"levels": levels_info}
    except Exception as e:
        logger.error(f"Failed to get levels: {e}")
        raise HTTPException(500, f"Failed to get levels: {str(e)}")
        
@app.get("/playback-status")
async def get_playback_status():
    status_file = os.path.join(SIMUST_PLAYER_DIRECTORY, "playback_status.json")
    if os.path.exists(status_file):
        try:
            with open(status_file, 'r') as f:
                return json.load(f)
        except:
            return {"state": "unknown", "message": "Could not read status"}
    return {"state": "idle", "message": "No active playback"}

# ============================================================
# REALTIME PLAYBACK ENDPOINTS (with unlock check)
# ============================================================

@app.post("/start-realtime-playback")
async def start_realtime_playback(req: Request):
    global smart_player_process, realtime_camera_process, current_results_dir
    try:
        data = await req.json()
        level_id = data.get("level")  # e.g., "L00-Foundation" or "L01-Entry/A-T1/A.T1.C1"
        player_speed = data.get("speed", 1.0)
        player_id = data.get("player_id")
        player_name = data.get("player_name")
        player_surname = data.get("player_surname", "")
        player_player_id = data.get("player_player_id", player_id)
        subdirectory = data.get("subdirectory")  # optional, e.g., "SF-30N"

        if not level_id:
            raise HTTPException(400, "No level selected")
        if level_id not in ALL_LEVELS:
            raise HTTPException(400, f"Invalid level: {level_id}")

        # --- Check if level is unlocked for this player ---
        if player_id:
            users = load_users()
            if player_id not in users:
                raise HTTPException(404, "Player not found")

            # Ensure progress exists
            if "progress" not in users[player_id]:
                users[player_id]["progress"] = {
                    "current_level": "L00-Foundation",
                    "unlocked_levels": ["L00-Foundation"],
                    "completed_levels": [],
                    "challenge_results": {}
                }
                save_users(users)

            progress = users[player_id].get("progress", {})
            unlocked = progress.get("unlocked_levels", [])

            # Allow L00-Foundation always, even if not in unlocked list
            if level_id != "L00-Foundation" and level_id not in unlocked:
                raise HTTPException(403, f"Level {level_id} is not unlocked for this player")

        level_path = get_level_path(level_id)

        # ---- If subdirectory is provided, append it to the path ----
        if subdirectory:
            level_path = os.path.join(level_path, subdirectory)
            # Ensure the path exists
            if not os.path.isdir(level_path):
                raise HTTPException(400, f"Subdirectory not found: {level_path}")

        # For Foundation, we may need to create a dummy path if it doesn't exist
        if level_id == "L00-Foundation" and not subdirectory:
            # If no subdirectory given, we default to the main folder (but we want to enforce subdirectory selection)
            # Actually the frontend should always send a subdirectory for Foundation.
            if not os.path.exists(level_path):
                os.makedirs(level_path, exist_ok=True)

        if not os.path.isdir(level_path):
            raise HTTPException(400, f"Level directory not found: {level_path}")

        force_kill_smart_player()
        try:
            status_file = os.path.join(SIMUST_PLAYER_DIRECTORY, "playback_status.json")
            os.makedirs(SIMUST_PLAYER_DIRECTORY, exist_ok=True)
            with open(status_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "state": "playing",
                    "current_video": 0,
                    "total_videos": 0,
                    "progress": 0,
                    "message": "Starting playback",
                    "timestamp": time.time()
                }, f)
        except Exception as e:
            logger.warning(f"Could not reset playback status file: {e}")
        if realtime_camera_process:
            try:
                if realtime_camera_process.poll() is None:
                    realtime_camera_process.terminate()
                    time.sleep(1)
                    if realtime_camera_process.poll() is None:
                        realtime_camera_process.kill()
            except Exception as e:
                logger.warning(f"Error cleaning up old process: {e}")
            finally:
                realtime_camera_process = None

        script_dir = os.path.dirname(os.path.abspath(__file__))
        python_exe = sys.executable

        # Launch realtime camera
        realtime_script = os.path.join(script_dir, "simust_realtime.py")
        if not os.path.exists(realtime_script):
            realtime_script = os.path.join(os.getcwd(), "simust_realtime.py")
        if not os.path.exists(realtime_script):
            logger.warning(f"simust_realtime.py not found - only video player will run")
        else:
            if sys.platform == "win32":
                CREATE_NO_WINDOW = 0x08000000
                realtime_camera_process = subprocess.Popen(
                    [python_exe, realtime_script, level_path, str(player_speed)],
                    shell=False,
                    creationflags=subprocess.CREATE_NEW_CONSOLE | CREATE_NO_WINDOW
                )
            else:
                realtime_camera_process = subprocess.Popen(
                    [python_exe, realtime_script, level_path, str(player_speed)],
                    shell=False
                )
            logger.info("Realtime camera/QR detection started.")
            time.sleep(3)

        # Launch smart player
        smart_script = os.path.join(script_dir, "smart_simust_player.py")
        if not os.path.exists(smart_script):
            smart_script = os.path.join(os.getcwd(), "smart_simust_player.py")
        if not os.path.exists(smart_script):
            raise HTTPException(500, f"smart_simust_player.py not found")

        if sys.platform == "win32":
            CREATE_NO_WINDOW = 0x08000000
            smart_player_process = subprocess.Popen(
                [python_exe, smart_script, level_path, str(player_speed), "1"],
                shell=False,
                creationflags=subprocess.CREATE_NEW_CONSOLE | CREATE_NO_WINDOW
            )
        else:
            smart_player_process = subprocess.Popen(
                [python_exe, smart_script, level_path, str(player_speed), "1"],
                shell=False
            )
        logger.info(f"Smart player launched with level: {level_id}, subdir: {subdirectory or 'None'}, speed: {player_speed}x on Screen 2")

        # Also store the current level in a file for the player (optional)
        if player_id:
            try:
                user_progress_file = os.path.join(PLAYER_REPORTS_DIR, player_id, "progress.json")
                os.makedirs(os.path.dirname(user_progress_file), exist_ok=True)
                with open(user_progress_file, 'w') as f:
                    json.dump({"current_level": level_id}, f)
            except Exception as e:
                logger.warning(f"Could not save current level for player: {e}")

        return {
            "status": "success",
            "level": level_id,
            "screen": "Screen 2 (Video Player + Camera Feed)",
            "player_id": player_id,
            "player_name": player_name,
            "message": "Realtime started."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start realtime: {e}")
        raise HTTPException(500, f"Failed to start: {str(e)}")

@app.post("/stop-realtime")
async def stop_realtime():
    global smart_player_process, realtime_camera_process
    try:
        logger.info("Stopping realtime playback...")
        force_kill_smart_player()
        if realtime_camera_process:
            try:
                if realtime_camera_process.poll() is None:
                    realtime_camera_process.terminate()
                    for _ in range(50):
                        if realtime_camera_process.poll() is not None:
                            break
                        time.sleep(0.1)
                    if realtime_camera_process.poll() is None:
                        realtime_camera_process.kill()
                        realtime_camera_process.wait(timeout=2)
            except Exception as e:
                logger.warning(f"Error stopping realtime camera process: {e}")
            finally:
                realtime_camera_process = None
        try:
            speed_file = os.path.join(SIMUST_PLAYER_DIRECTORY, "simust_speed.txt")
            if os.path.exists(speed_file):
                os.remove(speed_file)
        except:
            pass
        return {"status": "success", "message": "Realtime playback stopped"}
    except Exception as e:
        logger.error(f"Failed to stop realtime: {e}")
        raise HTTPException(500, f"Failed to stop: {str(e)}")

@app.post("/stop-realtime-camera")
async def stop_realtime_camera():
    global realtime_camera_process
    try:
        if realtime_camera_process and realtime_camera_process.poll() is None:
            realtime_camera_process.terminate()
            for _ in range(50):
                if realtime_camera_process.poll() is not None:
                    break
                await asyncio.sleep(0.1)
            if realtime_camera_process.poll() is None:
                realtime_camera_process.kill()
                realtime_camera_process.wait(timeout=2)
            realtime_camera_process = None
            logger.info("Realtime camera process stopped.")
            return {"status": "success", "message": "Camera stopped"}
        else:
            return {"status": "info", "message": "No camera process running"}
    except Exception as e:
        logger.error(f"Failed to stop camera: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/set-visualization")
async def set_visualization(req: Request):
    try:
        data = await req.json()
        enabled = data.get("enabled", False)
        viz_file = os.path.join(SIMUST_PLAYER_DIRECTORY, "visualization.txt")
        os.makedirs(SIMUST_PLAYER_DIRECTORY, exist_ok=True)
        with open(viz_file, 'w') as f:
            f.write(str(enabled).lower())
        logger.info(f"Visualization set to: {enabled}")
        return {"status": "success", "visualization_enabled": enabled}
    except Exception as e:
        logger.error(f"Failed to set visualization: {e}")
        raise HTTPException(500, f"Failed to set visualization: {str(e)}")

# ============================================================
# RESULTS ENDPOINTS
# ============================================================

@app.get("/results")
async def get_results():
    global current_results_dir
    realtime_folder = get_newest_realtime_session_folder()
    if realtime_folder:
        if os.path.exists(os.path.join(realtime_folder, "results.json")) or os.path.exists(os.path.join(realtime_folder, "recognition.json")):
            current_results_dir = realtime_folder
            return _get_video_info(realtime_folder)
    if not (recording_process and recording_process.is_alive()):
        latest_dir = get_latest_recording_directory()
        if latest_dir:
            current_results_dir = latest_dir
    if current_results_dir and os.path.exists(current_results_dir):
        try:
            return _get_video_info(current_results_dir)
        except Exception as e:
            logger.error(f"/results failed: {e}")
            return {"results": [], "directory": None, "error": str(e)}
    if output_path and os.path.exists(output_path):
        try:
            subdirs = [d for d in os.listdir(output_path) if os.path.isdir(os.path.join(output_path, d))]
            if subdirs:
                latest = max(subdirs, key=lambda d: os.path.getctime(os.path.join(output_path, d)))
                candidate = os.path.join(output_path, latest)
                if any(f.endswith('.mp4') for f in os.listdir(candidate)):
                    current_results_dir = candidate
                    return _get_video_info(candidate)
        except Exception as e:
            logger.error(f"Fallback detection failed: {e}")
    return {"results": [], "directory": None, "message": "No recording directory found"}

@app.post("/video-results")
async def video_results(req: Request):
    global current_results_dir
    try:
        data = await req.json()
        directory = data.get("directory")
        if not directory:
            raise HTTPException(400, "No directory provided")
        if not os.path.isdir(directory):
            raise HTTPException(400, f"Directory does not exist: {directory}")
        current_results_dir = directory
        result = _get_video_info(directory)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/video-results failed: {e}")
        raise HTTPException(500, f"Failed to load video results: {str(e)}")

@app.get("/realtime-results")
async def get_realtime_results():
    try:
        realtime_folder = get_newest_realtime_session_folder()
        if realtime_folder:
            results_json_path = os.path.join(realtime_folder, "results.json")
            if os.path.exists(results_json_path):
                with open(results_json_path, 'r', encoding='utf-8') as f:
                    results_data = json.load(f)

                formatted_results = []
                ae_values = []
                for entry in results_data:
                    ae_val = entry.get('ae', 0.0)
                    formatted_results.append({
                        'id': entry.get('id', ''),
                        'action': entry.get('action', ''),
                        'screens': entry.get('screens', []),
                        'result': entry.get('result', 'N/A'),
                        'winning_screen': entry.get('winning_screen', 'N/A'),
                        'min_distance': entry.get('min_dist', '-'),
                        'time_of_min': entry.get('finishing_time', '-'),
                        'session_duration': entry.get('session_duration', '-'),
                        'movement': entry.get('movement', 0),
                        'direction': entry.get('direction', 'NONE'),
                        'aep': entry.get('aep', 'N/A'),
                        'proj_t': entry.get('proj_t', '-'), 
                        'ae': ae_val,
                        'video_index': entry.get('video_index', None)
                    })
                    if ae_val is not None:
                        ae_values.append(ae_val)

                correct = sum(1 for r in formatted_results if r['result'] == 'Correct')
                late   = sum(1 for r in formatted_results if r['result'] == 'Late')
                wrong  = sum(1 for r in formatted_results if r['result'] == 'Wrong')
                miss   = sum(1 for r in formatted_results if r['result'] == 'Miss')
                total  = len(formatted_results)

                correct_times = []
                for r in formatted_results:
                    if r['result'] == 'Correct':
                        tm = r.get('time_of_min')
                        try:
                            if tm is not None and tm != '-' and tm != 'N/A':
                                val = float(tm)
                                if val > 0:
                                    correct_times.append(val)
                        except:
                            pass
                avg_finishing_time = sum(correct_times) / len(correct_times) if correct_times else 0

                total_distance = 0.0
                recognition_path = os.path.join(realtime_folder, "recognition.json")
                if os.path.exists(recognition_path):
                    total_distance = compute_total_distance_from_recognition(realtime_folder)

                goals_by_screen = {}
                for r in formatted_results:
                    if r['result'] == 'Correct' and r['winning_screen'] and r['winning_screen'] != 'N/A':
                        screen = r['winning_screen']
                        goals_by_screen[screen] = goals_by_screen.get(screen, 0) + 1

                avg_ae = sum(ae_values) / len(ae_values) if ae_values else 0

                stats = {
                    'correct': correct,
                    'late': late,
                    'wrong': wrong,
                    'miss': miss,
                    'total': total,
                    'avg_finishing_time': avg_finishing_time,
                    'total_distance': total_distance,
                    'goals_by_screen': goals_by_screen,
                    'avg_ae': avg_ae
                }

                return {
                    "status": "success",
                    "report": {
                        "actions": formatted_results,
                        "statistics": stats,
                        "total_actions": total
                    },
                    "directory": realtime_folder,
                    "timestamp": datetime.now().isoformat()
                }
        return {"status": "no_data", "message": "No results available yet"}
    except Exception as e:
        logger.error(f"Failed to get realtime results: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/save-results-to-json")
async def save_results_to_json(req: Request):
    try:
        data = await req.json()
        session_folder = data.get("session_folder")
        action_result = data.get("action_result", {})
        if not session_folder or not os.path.exists(session_folder):
            return {"status": "error", "message": "Session folder not found"}
        results_json_path = os.path.join(session_folder, "results.json")
        results = []
        if os.path.exists(results_json_path):
            with open(results_json_path, 'r', encoding='utf-8') as f:
                results = json.load(f)
        results.append(action_result)
        with open(results_json_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        return {"status": "success", "total_results": len(results)}
    except Exception as e:
        logger.error(f"save-results-to-json error: {e}")
        return {"status": "error", "message": str(e)}

# ============================================================
# CAPTURE ENDPOINT
# ============================================================

@app.post("/capture-frame")
async def capture_frame():
    trigger_path = os.path.join(SIMUST_PLAYER_DIRECTORY, "capture_trigger.txt")
    if os.path.exists(trigger_path):
        os.remove(trigger_path)
    with open(trigger_path, 'w') as f:
        f.write("capture")
    for _ in range(20):
        await asyncio.sleep(0.1)
        if os.path.exists(os.path.join(os.path.dirname(__file__), "last_capture.txt")):
            with open(os.path.join(os.path.dirname(__file__), "last_capture.txt"), 'r') as f:
                path = f.read().strip()
            os.remove(os.path.join(os.path.dirname(__file__), "last_capture.txt"))
            return {"status": "success", "path": path}
    raise HTTPException(408, "Capture timeout – ensure realtime is running.")

# ============================================================
# HELPER: Compute total distance from recognition.json  
# ============================================================

def compute_total_distance_from_recognition(session_folder: str) -> float:
    json_path = os.path.join(session_folder, "recognition.json")
    if not os.path.exists(json_path):
        return 0.0
    try:
        with open(json_path, 'r') as f:
            blocks = json.load(f)
    except Exception:
        return 0.0
    all_positions = []
    for block in blocks:
        start_time_str = block.get('start_time')
        if not start_time_str:
            continue
        try:
            block_start = datetime.strptime(start_time_str, "%H:%M:%S.%f")
        except Exception:
            continue
        data = block.get('data', [])
        for entry in data:
            t = entry.get('t', 0.0)
            hp = entry.get('hp')
            if hp is not None and isinstance(hp, list) and len(hp) == 2:
                x, y = hp[0], hp[1]
                abs_time = block_start + timedelta(seconds=t)
                all_positions.append((abs_time, x, y))
    if len(all_positions) < 2:
        return 0.0
    all_positions.sort(key=lambda p: p[0])
    sampled = all_positions[::4]
    if len(sampled) < 2:
        return 0.0
    total_dist_px = 0.0
    for i in range(1, len(sampled)):
        _, x1, y1 = sampled[i-1]
        _, x2, y2 = sampled[i]
        total_dist_px += math.hypot(x2 - x1, y2 - y1)
    return total_dist_px * PIXEL_TO_METER_SCALE

# ============================================================
# SLICE VIDEO SELECTION BASED ON DECISION ACCURACY
# ============================================================

def get_slice_video_for_accuracy(accuracy: float) -> str:
    if accuracy >= 100:
        return "PRO_CI_100%_V01.mp4"
    elif accuracy >= 90:
        return "PRO_CI_90-100%_V01.mp4"
    elif accuracy >= 80:
        return "PRO_CI_80-90%_V01.mp4"
    elif accuracy >= 70:
        return "PRO_CI_70-80%_V01.mp4"
    elif accuracy >= 60:
        return "PRO_CI_60-70%_V01.mp4"
    elif accuracy >= 50:
        if abs(accuracy - 50.0) < 0.01:
            return "PRO_CI_50%_V01.mp4"
        else:
            return "PRO_CI_50-60%_V01.mp4"
    else:
        return "PRO_CI_UPTO_50%_V01.mp4"

# ============================================================
# VIDEO GENERATION FUNCTIONS
# ============================================================

# ---------- AE Function ----------
def compute_action_efficiency(action_type: str,
                              result: str,
                              finishing_time: float,
                              movement_px: int,
                              winning_screen: str = None,
                              max_movement_px: int = 100) -> float:
    """
    Compute Action Efficiency (AE) score for a single action.
    Returns a value between 0 and 100.

    Parameters
    ----------
    action_type : str
        The type of action: 'GOAL', 'PASS', 'TARGET', 'PRESS', or other.
    result : str
        The outcome: 'Correct', 'Late', 'Wrong', or 'Miss'.
    finishing_time : float
        Time taken to complete the action (in seconds). Expected > 0.
    movement_px : int
        Body displacement during the action (in pixels).
    winning_screen : str, optional
        The target screen for TARGET actions, e.g., '9L', '6R', etc.
        Used to assign a higher priority for specific target zones.
    max_movement_px : int, optional
        Maximum displacement considered optimal (default 100 px).

    Returns
    -------
    float
        AE score clamped between 0 and 100.
    """

    # --- Priority (P) ---
    # Base priorities
    priority_map = {
        'GOAL': 90,
        'PASS': 70,
        'TARGET': 50,          # default for generic targets
        'PRESS': 30
    }
    P = priority_map.get(action_type, 50)   # default 50 for unknown

    # Override for specific TARGET screens: 9L, 6L, 9R, 6R
    if action_type == 'TARGET' and winning_screen in ['9L', '6L', '9R', '6R']:
        P = 85

    # --- Accuracy (A) ---
    if result == 'Correct':
        A = 100
    elif result == 'Late':
        A = 80
    else:   # 'Wrong' or 'Miss' (or any other)
        A = 0

    # --- Finishing Time (T) ---
    # Optimal time is 3 seconds; faster gives higher score.
    if finishing_time and finishing_time > 0:
        # Normalise: 0% at 3s, 100% at 0s (but cap at 100%)
        T = min(finishing_time / 3.0, 1.0) * 100
    else:
        T = 0

    # --- Body Displacement (D) ---
    # Less movement is better; 0 px gives 100%, max_movement_px gives 0%.
    if movement_px > 0:
        D = max(0, min(100, 100 - (movement_px / max_movement_px) * 100))
    else:
        D = 100

    # --- Penalties (binary) ---
    W = 1 if result == 'Wrong' else 0
    M = 1 if result == 'Miss'  else 0
    L = 1 if result == 'Late'  else 0

    # --- AE raw value ---
    ae_raw = (0.40 * P) + (0.30 * A) + (0.20 * (100 - T)) + (0.10 * (100 - D)) \
             - (25 * W) - (35 * M) - (15 * L)

    # Clamp to [0, 100]
    ae = max(0, min(100, ae_raw))
    return ae   
    
# ---------- AEP Orientation ----------
def get_aep_orientation(screens: List[str], winning_screen: Optional[str]) -> str:
    """
    Returns 'Right' or 'Left' based on the AEP rules (Code A).
    """
    if not screens or len(screens) != 2:
        return 'N/A'
    if winning_screen is None or winning_screen == 'N/A':
        return 'N/A'
    try:
        s1, s2 = [int(s) for s in screens]
        win = int(winning_screen)
    except (ValueError, TypeError):
        return 'N/A'

    right_screens = {2,3,4,9,10,11}
    left_screens = {5,6,7,12,13,14}
    special_pairs = [{2,4}, {12,14}, {9,11}, {5,7}]
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

# ---------- generate_results_video_from_results ----------
def generate_results_video_from_results(results_list, output_path, duration_seconds=5, is_final=False,
                                        slice_video_path=None, session_folder=None):
    try:
        # ---- Compute total BDP (Body Displacement) by summing per‑action BDP ----
        total_distance = 0.0
        for r in results_list:
            total_distance += r.get('bpd', 0.0)
        logger.info(f"Sum of BDPs from results_list: {total_distance:.2f} m")

        if total_distance == 0 and session_folder and os.path.exists(os.path.join(session_folder, "recognition.json")):
            computed_distance = compute_total_distance_from_recognition(session_folder)
            if computed_distance > 0:
                total_distance = computed_distance
                logger.info(f"Fallback: using computed total distance from recognition.json: {total_distance:.2f} m")
            else:
                logger.warning("computed_distance from recognition.json is 0, BDP will show '-'.")

        correct = sum(1 for r in results_list if r.get('result') == 'Correct')
        late = sum(1 for r in results_list if r.get('result') == 'Late')
        wrong = sum(1 for r in results_list if r.get('result') == 'Wrong')
        miss = sum(1 for r in results_list if r.get('result') == 'Miss')
        total_actions = len(results_list)

        aac = ((correct + late) / total_actions) * 100 if total_actions > 0 else 0

        ae_values = [r.get('ae', 0.0) for r in results_list if r.get('ae') is not None]
        avg_ae = sum(ae_values) / len(ae_values) if ae_values else 0.0
        ae_display = f"{avg_ae:.0f}%" if avg_ae > 0 else "-"

        if is_final:
            selected_video = get_slice_video_for_accuracy(avg_ae)
            if selected_video:
                selected_path = os.path.join(ANIMATIONS_DIR, selected_video)
                if os.path.exists(selected_path):
                    slice_video_path = selected_path
                    logger.info(f"Using slice video for AE {avg_ae:.1f}%: {selected_video}")
                else:
                    logger.warning(f"Selected slice video {selected_video} not found, falling back to default.")
                    slice_video_path = None
            else:
                slice_video_path = None

        REFERENCE_DISTANCE_METERS = 77.0
        economy_percent = min(100.0, (total_distance / REFERENCE_DISTANCE_METERS) * 100) if total_distance > 0 else 0

        correct_times = []
        correct_ratios = []
        for r in results_list:
            if r.get('result') == 'Correct':
                tm = r.get('finishing_time')
                if tm is None or tm == 0:
                    tm = r.get('time_of_min')
                sd = r.get('session_duration')
                try:
                    tm = float(tm) if tm is not None else None
                except (ValueError, TypeError):
                    tm = None
                try:
                    sd = float(sd) if sd is not None else None
                except (ValueError, TypeError):
                    sd = None
                if tm is not None and tm > 0 and sd is not None and sd > 0:
                    correct_times.append(tm)
                    correct_ratios.append(tm / sd)
        if correct_times:
            aet = sum(correct_times) / len(correct_times)
            avg_ratio = sum(correct_ratios) / len(correct_ratios)
            aet_percent = max(0, min(100, (1 - avg_ratio) * 100))
            aet_display = f"{aet:.2f}s"
        else:
            aet = None
            aet_percent = 0
            aet_display = "-"

        # ---- Slice video handling (UPDATED: use ffprobe for true FPS) ----
        width, height = 3712, 512
        use_slice_video = False
        slice_frames = []
        output_fps = 2
        total_frames = 30
        video_duration = 0.0

        # Helper to get stream info via ffprobe
        def get_stream_info(filepath):
            vid_info = {}
            aud_info = {}
            try:
                # Video
                cmd = [
                    'ffprobe', '-v', 'error',
                    '-select_streams', 'v:0',
                    '-show_entries', 'stream=codec_type,width,height,r_frame_rate,duration,time_base,nb_frames',
                    '-of', 'json', filepath
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    if data.get('streams'):
                        s = data['streams'][0]
                        vid_info = {
                            'codec_type': s.get('codec_type'),
                            'width': s.get('width'),
                            'height': s.get('height'),
                            'r_frame_rate': s.get('r_frame_rate'),
                            'duration': s.get('duration'),
                            'time_base': s.get('time_base'),
                            'nb_frames': s.get('nb_frames')
                        }
                # Audio
                cmd_audio = [
                    'ffprobe', '-v', 'error',
                    '-select_streams', 'a:0',
                    '-show_entries', 'stream=codec_type,duration,sample_rate,time_base,nb_frames',
                    '-of', 'json', filepath
                ]
                result_audio = subprocess.run(cmd_audio, capture_output=True, text=True, timeout=10)
                if result_audio.returncode == 0:
                    data = json.loads(result_audio.stdout)
                    if data.get('streams'):
                        s = data['streams'][0]
                        aud_info = {
                            'codec_type': s.get('codec_type'),
                            'duration': s.get('duration'),
                            'sample_rate': s.get('sample_rate'),
                            'time_base': s.get('time_base'),
                            'nb_frames': s.get('nb_frames')
                        }
            except Exception as e:
                logger.warning(f"ffprobe failed: {e}")
            return vid_info, aud_info

        if is_final:
            if slice_video_path and os.path.exists(slice_video_path):
                # Try ffprobe first
                vid_info, aud_info = get_stream_info(slice_video_path)
                if vid_info and vid_info.get('r_frame_rate'):
                    fps_str = vid_info['r_frame_rate']
                    if '/' in fps_str:
                        num, den = map(int, fps_str.split('/'))
                        true_fps = num / den if den > 0 else 25.0
                    else:
                        true_fps = float(fps_str)
                    output_fps = true_fps
                    logger.info(f"Using true FPS from ffprobe: {output_fps:.2f}")
                    # Get frame count
                    if vid_info.get('nb_frames'):
                        total_frames = int(vid_info['nb_frames'])
                    else:
                        # fallback
                        cap = cv2.VideoCapture(slice_video_path)
                        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                        cap.release()
                    video_duration = total_frames / output_fps
                    logger.info(f"Frame count: {total_frames}, duration: {video_duration:.3f}s")
                else:
                    # fallback to OpenCV
                    cap = cv2.VideoCapture(slice_video_path)
                    if cap.isOpened():
                        output_fps = cap.get(cv2.CAP_PROP_FPS)
                        if output_fps <= 0:
                            output_fps = 25
                        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                        video_duration = total_frames / output_fps
                        cap.release()
                        logger.info(f"Using OpenCV FPS: {output_fps:.2f}, frames: {total_frames}, duration: {video_duration:.3f}s")

                # Load frames
                cap = cv2.VideoCapture(slice_video_path)
                if cap.isOpened():
                    all_frames = []
                    while True:
                        ret, frame = cap.read()
                        if not ret:
                            break
                        all_frames.append(frame)
                    cap.release()
                    if all_frames:
                        slice_frames = all_frames
                        # Use loaded frame count if different from ffprobe
                        if len(slice_frames) != total_frames:
                            logger.warning(f"Loaded {len(slice_frames)} frames, but expected {total_frames}. Using loaded count.")
                            total_frames = len(slice_frames)
                            video_duration = total_frames / output_fps
                        use_slice_video = True
                        logger.info(f"Final video using {total_frames} frames at {output_fps:.2f} FPS (duration {video_duration:.3f}s) from slice video")
                    else:
                        logger.warning("Slice video had no frames, falling back to static background.")
                else:
                    logger.warning("Could not open slice video, falling back to static background.")

            if not use_slice_video:
                output_fps = 2
                total_frames = 60
                video_duration = 30.0
                logger.info("Using static background for final video (30s, 2 FPS)")
        else:
            # Per‑video: always 2 FPS, 30 frames (15s)
            output_fps = 2
            total_frames = 30
            video_duration = 15.0
            if slice_video_path and os.path.exists(slice_video_path):
                cap = cv2.VideoCapture(slice_video_path)
                if cap.isOpened():
                    all_frames = []
                    while True:
                        ret, frame = cap.read()
                        if not ret:
                            break
                        all_frames.append(frame)
                    cap.release()
                    if all_frames:
                        if len(all_frames) >= total_frames:
                            indices = np.linspace(0, len(all_frames)-1, total_frames, dtype=int)
                            slice_frames = [all_frames[i] for i in indices]
                        else:
                            slice_frames = []
                            while len(slice_frames) < total_frames:
                                for f in all_frames:
                                    slice_frames.append(f)
                                    if len(slice_frames) >= total_frames:
                                        break
                        use_slice_video = True
                        logger.info(f"Per‑video using {len(slice_frames)} sampled frames from slice video")
                else:
                    cap = None

            if not use_slice_video:
                logger.info("Using static background for per‑video")

        # ---- Create temporary AVI (MJPEG) ----
        temp_avi = output_path.replace(".mp4", "_temp.avi")
        fourcc = cv2.VideoWriter_fourcc(*'MJPG')
        out = cv2.VideoWriter(temp_avi, fourcc, output_fps, (width, height))
        if not out.isOpened():
            logger.error(f"Could not open temporary video writer for {temp_avi}")
            return False

        slice_numbers = [12, 13, 14, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
        num_tiles = len(slice_numbers)
        tile_width = width // num_tiles

        CHART_CENTER_Y = 160
        RING_RADIUS = 60
        RING_THICKNESS = 22
        LABEL_VERTICAL_GAP = 45
        RING_TEXT_Y_OFFSET = -10
        LABEL_TEXT_Y_OFFSET = -10

        # ----- PIL helpers (unchanged) -----
        def get_segoe_font(size, bold=True):
            try:
                if bold:
                    font_path = "C:/Windows/Fonts/segoeuib.ttf"
                else:
                    font_path = "C:/Windows/Fonts/segoeui.ttf"
                if not os.path.exists(font_path):
                    font_path = "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"
                return ImageFont.truetype(font_path, size)
            except:
                return ImageFont.load_default()

        def draw_text_on_pil(draw, text, x, y, font_size, color=(255,255,255), bold=True, anchor='lt'):
            font = get_segoe_font(font_size, bold)
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            if anchor == 'mm':
                x -= tw // 2
                y -= th // 2
            elif anchor == 'lm':
                y -= th // 2
            draw.text((x, y), text, font=font, fill=color)

        def draw_text_inside_ring_on_pil(draw, center_x, center_y, lines, color=(255,255,255)):
            if not lines:
                return
            font_size = 24 if len(lines) > 1 else 28
            font = get_segoe_font(font_size, bold=True)
            total_h = 0
            for line in lines:
                bbox = draw.textbbox((0, 0), line, font=font)
                th = bbox[3] - bbox[1]
                total_h += th
            total_h += (len(lines) - 1) * 8
            y_start = center_y - total_h // 2
            y_pos = y_start
            for line in lines:
                bbox = draw.textbbox((0, 0), line, font=font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                x_pos = center_x - tw // 2
                draw.text((x_pos, y_pos), line, font=font, fill=color)
                y_pos += th + 8

        def draw_metric_label(draw, text, center_x, rect_y):
            """Draw a metric name centered in the label rectangle, wrapping long names."""
            words = text.split()
            if len(words) >= 2:
                lines = [words[0], " ".join(words[1:])]
            else:
                lines = [text]
            font_size = 15 if max(len(line) for line in lines) > 6 else 22
            line_gap = 4
            font = get_segoe_font(font_size, True)
            heights = []
            widths = []
            for line in lines:
                bbox = draw.textbbox((0, 0), line, font=font)
                widths.append(bbox[2] - bbox[0])
                heights.append(bbox[3] - bbox[1])
            total_h = sum(heights) + line_gap * (len(lines) - 1)
            y = rect_y + 35 + LABEL_TEXT_Y_OFFSET - total_h // 2
            for i, line in enumerate(lines):
                x = center_x - widths[i] // 2
                draw.text((x, y), line, font=font, fill=(255, 255, 255))
                y += heights[i] + line_gap

        def draw_label_rectangle(img, center_x, tile_width, rect_y, text,
                                 color=(255,255,255), bg=(0,165,255)):
            rect_h = 70
            rect_x1 = center_x - tile_width // 2
            rect_y1 = rect_y
            rect_x2 = rect_x1 + tile_width
            rect_y2 = rect_y1 + rect_h
            cv2.rectangle(img, (rect_x1, rect_y1), (rect_x2, rect_y2), bg, -1)
            cv2.rectangle(img, (rect_x1, rect_y1), (rect_x2, rect_y2), (0, 0, 0), 1)

        def draw_ring_chart(img, center_x, center_y, radius, value, max_value=100,
                            bg_color=(255,255,255), fill_color=(0,215,255)):
            thickness = RING_THICKNESS
            outer_radius = radius + thickness // 2
            cv2.circle(img, (center_x, center_y), outer_radius, bg_color, thickness, lineType=cv2.LINE_AA)
            if value > 0:
                percent = min(100, max(0, (value / max_value) * 100))
                start_angle = -90
                end_angle = start_angle + 360 * (percent / 100.0)
                num_points = max(2, int(abs(end_angle - start_angle) / 1.0))
                pts = []
                for i in range(num_points + 1):
                    angle = math.radians(start_angle + (end_angle - start_angle) * i / num_points)
                    x = int(center_x + outer_radius * math.cos(angle))
                    y = int(center_y + outer_radius * math.sin(angle))
                    pts.append([x, y])
                pts = np.array(pts, dtype=np.int32)
                cv2.polylines(img, [pts], isClosed=False, color=fill_color, thickness=thickness, lineType=cv2.LINE_AA)
            cv2.circle(img, (center_x, center_y), outer_radius - thickness//2, (10, 12, 18), -1)

        def get_coach_advice(decision_acc, action_econ, aet_val, total_actions):
            advice = []
            if total_actions == 0:
                return ["No actions recorded", "Start a session to get feedback", ""]
            if aet_val is None:
                aet_val = 3.0
            if decision_acc >= 80 and aet_val < 0.6:
                advice.append("Excellent decision‑making & speed!")
            else:
                if decision_acc < 70:
                    advice.append("Work on precision – more accurate passes")
                if aet_val > 1.0:
                    advice.append("React faster – reduce decision time")
            if not advice:
                advice.append("Keep up the great performance!")
            return advice[:3]

        advice_lines = get_coach_advice(aac, avg_ae, aet, total_actions)
        while len(advice_lines) < 3:
            advice_lines.append("")

        content_offset = {
            0: -6,   # tile 0 (slice 12) – shift left 6px
            1: -17,  # tile 1 (slice 13) – shift left 17px
            5: 17,   # tile 5 (slice 3)  – shift right 17px
            6: 6     # tile 6 (slice 4)  – shift right 6px
        }

        # ---- Main drawing loop ----
        for frame_idx in range(total_frames):
            try:
                if use_slice_video and slice_frames:
                    img = slice_frames[frame_idx % len(slice_frames)].copy()
                else:
                    img = np.zeros((height, width, 3), dtype=np.uint8)
                    img[:] = (10, 12, 18)

                # Draw OpenCV shapes
                for i, num in enumerate(slice_numbers):
                    x_offset = i * tile_width
                    offset_x = content_offset.get(i, 0)
                    center_x = x_offset + tile_width // 2 + offset_x
                    rect_y = CHART_CENTER_Y + RING_RADIUS + LABEL_VERTICAL_GAP

                    if num == 12:
                        draw_ring_chart(img, center_x, CHART_CENTER_Y, RING_RADIUS, aet_percent, 100)
                        draw_label_rectangle(img, center_x, tile_width, rect_y, "Reaction Time")
                    elif num == 3:
                        draw_ring_chart(img, center_x, CHART_CENTER_Y, RING_RADIUS, avg_ae, 100)
                        draw_label_rectangle(img, center_x, tile_width, rect_y, "Efficiency")
                    elif num == 13:
                        draw_ring_chart(img, center_x, CHART_CENTER_Y, RING_RADIUS, aac, 100)
                        draw_label_rectangle(img, center_x, tile_width, rect_y, "Accuracy")
                    elif num == 4:
                        draw_ring_chart(img, center_x, CHART_CENTER_Y, RING_RADIUS, economy_percent, 100)
                        draw_label_rectangle(img, center_x, tile_width, rect_y, "Displacement")

                # Convert to PIL and draw text
                pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                draw = ImageDraw.Draw(pil_img)

                for i, num in enumerate(slice_numbers):
                    x_offset = i * tile_width
                    offset_x = content_offset.get(i, 0)
                    center_x = x_offset + tile_width // 2 + offset_x
                    rect_y = CHART_CENTER_Y + RING_RADIUS + LABEL_VERTICAL_GAP

                    if num == 12:
                        aet_text = aet_display if aet_display != "-" else "-"
                        draw_text_inside_ring_on_pil(draw, center_x, CHART_CENTER_Y + RING_TEXT_Y_OFFSET, [aet_text])
                        draw_metric_label(draw, "Reaction Time", center_x, rect_y)
                    elif num == 3:
                        ae_text = ae_display if ae_display != "-" else "-"
                        draw_text_inside_ring_on_pil(draw, center_x, CHART_CENTER_Y + RING_TEXT_Y_OFFSET, [ae_text])
                        draw_metric_label(draw, "Efficiency", center_x, rect_y)
                    elif num == 13:
                        aac_text = f"{aac:.0f}%" if aac > 0 else "-"
                        draw_text_inside_ring_on_pil(draw, center_x, CHART_CENTER_Y + RING_TEXT_Y_OFFSET, [aac_text])
                        draw_metric_label(draw, "Accuracy", center_x, rect_y)
                    elif num == 4:
                        bdp_text = f"{total_distance:.1f} m" if total_distance > 0 else "-"
                        draw_text_inside_ring_on_pil(draw, center_x, CHART_CENTER_Y + RING_TEXT_Y_OFFSET, [bdp_text])
                        draw_metric_label(draw, "Displacement", center_x, rect_y)
                    elif num == 14 and is_final:
                        pass

                # Footer
                footer = "SIMUST RESULTS – Analysis Complete"
                (fw, fh), _ = cv2.getTextSize(footer, cv2.FONT_HERSHEY_DUPLEX, 0.9, 3)
                draw_text_on_pil(draw, footer,
                                (width - fw)//2, height - 10 - fh,
                                font_size=24, color=(150,150,150), bold=False, anchor='lt')

                img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
                out.write(img)

            except Exception as e:
                logger.error(f"Error writing frame {frame_idx}: {e}")
                continue

        out.release()

        # ---- Re-encode with ffmpeg (force constant FPS) ----
        if os.path.exists(temp_avi) and os.path.getsize(temp_avi) > 0:
            logger.info(f"Temporary AVI created: {temp_avi} ({os.path.getsize(temp_avi)} bytes)")
            cmd = [
                "ffmpeg", "-y",
                "-i", temp_avi,
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "28",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-r", str(output_fps),
                "-vsync", "1",
                "-fflags", "+genpts",
                output_path
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                if result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    logger.info(f"Successfully re-encoded to H.264: {output_path}")
                    if os.path.exists(temp_avi):
                        os.remove(temp_avi)
                else:
                    logger.error(f"ffmpeg re-encode failed: {result.stderr}")
                    if os.path.exists(temp_avi) and not os.path.exists(output_path):
                        os.rename(temp_avi, output_path)
                        logger.warning(f"Fell back to AVI file (renamed to .mp4): {output_path}")
                    else:
                        return False
            except Exception as e:
                logger.error(f"ffmpeg error: {e}")
                if os.path.exists(temp_avi) and not os.path.exists(output_path):
                    os.rename(temp_avi, output_path)
                    logger.warning(f"Fell back to AVI file (renamed to .mp4): {output_path}")
                else:
                    return False
        else:
            logger.error("Temporary AVI file is missing or empty.")
            return False

        # ---- Add audio from slice video (with padding) ----
        if is_final and slice_video_path and os.path.exists(slice_video_path) and os.path.exists(output_path):
            try:
                # Check if slice video has audio
                probe_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'default=noprint_wrappers=1:nokey=1', slice_video_path]
                probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
                if 'audio' not in probe_result.stdout:
                    logger.info("Slice video has no audio track.")
                    return True

                # Get generated video duration (ensure it matches)
                duration_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', output_path]
                duration_result = subprocess.run(duration_cmd, capture_output=True, text=True, timeout=10)
                video_duration = float(duration_result.stdout.strip()) if duration_result.stdout else None
                if video_duration is None or video_duration <= 0:
                    video_duration = total_frames / output_fps
                logger.info(f"Generated video duration for audio padding: {video_duration:.3f}s")

                temp_with_audio = output_path.replace('.mp4', '_with_audio.mp4')

                # Get audio sample rate from slice (to avoid resampling drift)
                slice_sample_rate = "44100"  # default
                try:
                    cmd_sr = ['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=sample_rate', '-of', 'default=noprint_wrappers=1:nokey=1', slice_video_path]
                    sr_result = subprocess.run(cmd_sr, capture_output=True, text=True, timeout=10)
                    if sr_result.returncode == 0 and sr_result.stdout.strip():
                        slice_sample_rate = sr_result.stdout.strip()
                except Exception:
                    pass

                # Pad audio to video duration
                cmd_audio = [
                    'ffmpeg', '-y',
                    '-i', output_path,
                    '-i', slice_video_path,
                    '-map', '0:v:0',
                    '-map', '1:a:0',
                    '-c:v', 'copy',
                    '-c:a', 'aac',
                    '-b:a', '192k',
                    '-ar', slice_sample_rate,
                    '-t', str(video_duration),
                    '-af', 'apad',
                    '-fflags', '+genpts',
                    temp_with_audio
                ]

                subprocess.run(cmd_audio, capture_output=True, timeout=120)
                if os.path.exists(temp_with_audio) and os.path.getsize(temp_with_audio) > 0:
                    os.remove(output_path)
                    os.rename(temp_with_audio, output_path)
                    logger.info("Audio merged successfully with padding and sample rate sync.")
                else:
                    logger.warning("Audio merge failed, keeping video without audio.")
            except Exception as e:
                logger.warning(f"Could not add audio: {e}")

        logger.info(f"Video generation completed: {output_path}")
        return True

    except Exception as e:
        logger.error(f"Error generating results video: {e}", exc_info=True)
        return False


# ============================================================
# VIDEO RESULTS ENDPOINTS (UPDATED to use correct session folder)
# ============================================================
@app.post("/create-video-results")
async def create_video_results(req: Request):
    try:
        data = await req.json()
        directory = data.get("directory")
        video_index = data.get("video_index", 1)

        # If directory not provided, fallback to newest realtime folder
        if not directory or not os.path.exists(directory):
            realtime_folder = get_newest_realtime_session_folder()
            if realtime_folder:
                directory = realtime_folder
                logger.info(f"Using newest realtime folder: {directory}")
            else:
                return {"status": "error", "message": "No session folder found"}

        results_json_path = os.path.join(directory, "results.json")
        if not os.path.exists(results_json_path):
            logger.error(f"results.json not found in {directory}")
            return {"status": "error", "message": "results.json not found"}

        with open(results_json_path, 'r', encoding='utf-8') as f:
            all_results = json.load(f)

        # Filter by video_index (if any match)
        video_results = [r for r in all_results if r.get('video_index') == video_index]
        if not video_results:
            logger.warning(f"No results for video_index {video_index}, using all results.")
            video_results = all_results

        if not video_results:
            return {"status": "error", "message": "No results available"}

        video_path = os.path.join(directory, f"results_video_{video_index}.mp4")
        logger.info(f"Generating results video for video {video_index}: {video_path}")

        success = generate_results_video_from_results(
            video_results,
            video_path,
            duration_seconds=15,
            is_final=False,
            slice_video_path=None,
            session_folder=directory
        )

        if not success:
            return {"status": "error", "message": "Video generation failed"}

        if not os.path.exists(video_path):
            return {"status": "error", "message": "Video file not created"}

        # Play the video on Screen 2
        script_dir = os.path.dirname(os.path.abspath(__file__))
        player_script = os.path.join(script_dir, "play_results_video.py")
        if not os.path.exists(player_script):
            player_script = os.path.join(os.getcwd(), "play_results_video.py")
        if os.path.exists(player_script):
            subprocess.Popen([sys.executable, player_script, video_path, "1"], shell=False)
            return {"status": "success", "video_path": video_path}
        else:
            logger.error("Player script not found")
            return {"status": "error", "message": "Player script not found"}

    except Exception as e:
        logger.error(f"create-video-results error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
        

@app.post("/create-results-video")
async def create_results_video(req: Request):
    try:
        data = await req.json()
        directory = data.get("directory")

        # If no directory, try to find newest
        if not directory or not os.path.exists(directory):
            realtime_folder = get_newest_realtime_session_folder()
            if realtime_folder:
                directory = realtime_folder
                logger.info(f"Using newest realtime folder: {directory}")
            else:
                return {"status": "error", "message": "No session folder found"}

        results_json_path = os.path.join(directory, "results.json")
        if not os.path.exists(results_json_path):
            return {"status": "error", "message": "results.json not found"}

        with open(results_json_path, 'r', encoding='utf-8') as f:
            all_results = json.load(f)

        if not all_results:
            return {"status": "error", "message": "No results found"}

        video_path = os.path.join(directory, "final_results_video.mp4")
        logger.info(f"Generating final summary video: {video_path}")

        success = generate_results_video_from_results(
            all_results,
            video_path,
            duration_seconds=0,
            is_final=True,
            slice_video_path=None,
            session_folder=directory
        )

        if not success:
            return {"status": "error", "message": "Video generation failed"}

        if not os.path.exists(video_path):
            return {"status": "error", "message": "Video file not created"}

        # Play the video on Screen 2
        script_dir = os.path.dirname(os.path.abspath(__file__))
        player_script = os.path.join(script_dir, "play_results_video.py")
        if not os.path.exists(player_script):
            player_script = os.path.join(os.getcwd(), "play_results_video.py")
        if os.path.exists(player_script):
            subprocess.Popen([sys.executable, player_script, video_path, "1"], shell=False)
            return {"status": "success", "video_path": video_path}
        else:
            return {"status": "error", "message": "Player script not found"}

    except Exception as e:
        logger.error(f"create-results-video error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

# ============================================================
# Player Report Management Endpoints (UPDATED with progress)
# ============================================================

@app.post("/save-session-to-player")
async def save_session_to_player(req: Request):
    try:
        data = await req.json()
        player_id = data.get("player_id")
        player_name = data.get("player_name")
        player_surname = data.get("player_surname", "")
        player_player_id = data.get("player_player_id", player_id)
        session_data = data.get("session_data", {})
        if not player_id:
            raise HTTPException(400, "Missing player_id")
        
        # --- NEW: load user data to get club, team, age, image ---
        users = load_users()
        user_data = users.get(player_id, {})
        club = user_data.get("club", "")
        team = user_data.get("team", "")
        age = user_data.get("age", "")
        image = user_data.get("image", "")

        player_dir = os.path.join(PLAYER_REPORTS_DIR, player_id)
        os.makedirs(player_dir, exist_ok=True)
        session_id = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]

        directory = session_data.get("directory", "")
        total_distance = 0.0
        if directory and os.path.exists(directory):
            total_distance = compute_total_distance_from_recognition(directory)

        avg_finishing_time = session_data.get("avg_finishing_time", 0)

        statistics = session_data.get("statistics", {})
        statistics["avg_finishing_time"] = avg_finishing_time
        statistics["total_distance"] = total_distance

        # Compute AEP Left/Right from actions
        actions = session_data.get("actions", [])
        left_count = 0
        right_count = 0
        for action in actions:
            screens = action.get("screens", [])
            winning_screen = action.get("goal_screen")
            if winning_screen and winning_screen != 'N/A' and screens:
                aep = get_aep_orientation(screens, winning_screen)
                if aep == 'Right':
                    right_count += 1
                elif aep == 'Left':
                    left_count += 1
        total_aep = left_count + right_count
        aep_right_pct = (right_count / total_aep * 100) if total_aep > 0 else 0.0
        aep_left_pct = (left_count / total_aep * 100) if total_aep > 0 else 0.0
        statistics["aep_left"] = aep_left_pct
        statistics["aep_right"] = aep_right_pct

        # --- Level played ---
        level_played = session_data.get("level", "Unknown")
        subdirectory = session_data.get("subdirectory", "")  # <-- get subdirectory

        session_report = {
            "player": {
                "id": player_id,
                "name": player_name,
                "surname": player_surname,
                "playerId": player_player_id,
                "club": club,
                "team": team,
                "age": age,
                "image": image
            },
            "session": {
                "id": session_id,
                "timestamp": datetime.now().isoformat(),
                "level": level_played,
                "subdirectory": subdirectory,
                "total_duration_minutes": session_data.get("total_duration_minutes", 0),
                "video_count": session_data.get("video_count", 0),
                "directory": directory,
                "original_report_path": session_data.get("report_path", "")
            },
            "statistics": statistics,
            "goals_by_screen": session_data.get("goals_by_screen", {}),
            "actions": actions,
            "total_actions": session_data.get("total_actions", 0)
        }

        session_file = os.path.join(player_dir, f"{session_id}.json")
        with open(session_file, 'w', encoding='utf-8') as f:
            json.dump(session_report, f, indent=2, ensure_ascii=False)

        index_file = os.path.join(player_dir, "index.json")
        index = []
        if os.path.exists(index_file):
            with open(index_file, 'r', encoding='utf-8') as f:
                index = json.load(f)
        index.append({
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "level": level_played,
            "subdirectory": subdirectory,
            "total_actions": session_data.get("total_actions", 0),
            "correct": statistics.get("correct", 0),
            "late": statistics.get("late", 0),
            "wrong": statistics.get("wrong", 0),
            "file": f"{session_id}.json"
        })
        index.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        with open(index_file, 'w', encoding='utf-8') as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved session to player folder: {session_file}")

        try:
            simust_push.push_session_async(
                player_id,
                session_report,
                users.get(player_id),
                index[-1] if index else None,
            )
        except Exception as push_exc:
            logger.warning("Host push could not start: %s", push_exc)

        # ============================================================
        # PROGRESSION EVALUATION (UPDATED for Foundation subdirectory)
        # ============================================================
        # Compute AAC and AE from the session data
        correct = statistics.get("correct", 0)
        late = statistics.get("late", 0)
        total = correct + late + statistics.get("wrong", 0) + statistics.get("miss", 0)
        aac = (correct + late) / total * 100 if total > 0 else 0.0
        ae = statistics.get("avg_ae", 0.0)

        if level_played in ALL_LEVELS:
            if player_id in users:
                progress = users[player_id].get("progress", {})
                unlocked_levels = progress.get("unlocked_levels", [])
                completed_levels = progress.get("completed_levels", [])
                challenge_results = progress.get("challenge_results", {})

                # Check if this level is unlocked and not yet completed
                if level_played in unlocked_levels and level_played not in completed_levels:
                    main = get_main_level(level_played)
                    th_acc, th_ae = get_level_thresholds(level_played)

                    # ----- SPECIAL HANDLING FOR FOUNDATION -----
                    passed = False
                    if level_played == "L00-Foundation":
                        # Only unlock if subdirectory is exactly "SF-180N" AND thresholds are met
                        if subdirectory == "SF-180N":
                            if aac >= th_acc and ae >= th_ae:
                                passed = True
                                logger.info(f"Foundation SF-180N passed: AAC={aac:.1f}%, AE={ae:.1f}%")
                            else:
                                logger.info(f"Foundation SF-180N failed: AAC={aac:.1f}%, AE={ae:.1f}% (need ≥{th_acc}% ACC and ≥{th_ae}% AE)")
                        else:
                            logger.info(f"Foundation subdirectory '{subdirectory}' does not unlock Entry.")
                    else:
                        # Normal progression for other levels
                        passed = (aac >= th_acc and ae >= th_ae)

                    if passed:
                        completed_levels.append(level_played)
                        challenge_results[level_played] = {"aac": aac, "ae": ae, "passed": True}

                        # Find the next level to unlock
                        next_level = get_next_level(level_played)
                        if next_level and next_level not in unlocked_levels:
                            unlocked_levels.append(next_level)
                            progress["current_level"] = next_level
                            logger.info(f"Unlocked next level for {player_id}: {next_level}")
                        else:
                            logger.info(f"Next level {next_level} already unlocked or none.")

                        # Update progress
                        progress["completed_levels"] = completed_levels
                        progress["unlocked_levels"] = unlocked_levels
                        progress["challenge_results"] = challenge_results
                        users[player_id]["progress"] = progress
                        save_users(users)
                        logger.info(f"Progress updated for {player_id}: completed {level_played}")
                    else:
                        # Not passed, store the result but don't unlock
                        challenge_results[level_played] = {"aac": aac, "ae": ae, "passed": False}
                        progress["challenge_results"] = challenge_results
                        users[player_id]["progress"] = progress
                        save_users(users)
                        logger.info(f"Player {player_id} did not pass {level_played}: AAC={aac:.1f}, AE={ae:.1f}")
                else:
                    logger.info(f"Level {level_played} already completed or not unlocked for {player_id}")
            else:
                logger.warning(f"Player {player_id} not found in users, progress not updated")
        else:
            logger.warning(f"Level {level_played} is not in the progression system")

        return {"status": "success", "session_id": session_id, "file_path": session_file}
    except Exception as e:
        logger.error(f"Failed to save session to player: {e}")
        raise HTTPException(500, f"Failed to save session: {str(e)}")

def compute_player_ae_acc(player_id):
    """AE and ACC averages across all saved sessions for a player (same defs as the UI)."""
    player_dir = os.path.join(PLAYER_REPORTS_DIR, str(player_id))
    index_file = os.path.join(player_dir, "index.json")
    if not os.path.exists(index_file):
        return 0.0, 0.0
    try:
        with open(index_file, 'r', encoding='utf-8') as f:
            index = json.load(f)
    except Exception:
        return 0.0, 0.0

    total_correct = 0
    total_late = 0
    total_wrong = 0
    total_miss = 0
    ae_weighted = 0.0
    ae_weight = 0

    for entry in index or []:
        report_name = entry.get("file") or ""
        report_file = os.path.join(player_dir, report_name)
        if os.path.exists(report_file):
            try:
                with open(report_file, 'r', encoding='utf-8') as f:
                    session_data = json.load(f)
            except Exception:
                session_data = None
        else:
            session_data = None

        if session_data:
            stats = session_data.get("statistics") or {}
            actions = session_data.get("actions") or []
            correct = stats.get("correct", 0) or 0
            late = stats.get("late", 0) or 0
            wrong = stats.get("wrong", 0) or 0
            miss = stats.get("miss", 0) or 0
            total = stats.get("total") or session_data.get("total_actions") or (
                correct + late + wrong + miss) or len(actions)
            avg_ae = stats.get("avg_ae") or 0
            if not avg_ae and actions:
                ae_vals = []
                for a in actions:
                    v = a.get("ae")
                    if v is not None and v != 'N/A':
                        try:
                            ae_vals.append(float(v))
                        except (TypeError, ValueError):
                            pass
                avg_ae = sum(ae_vals) / len(ae_vals) if ae_vals else 0
        else:
            correct = entry.get("correct", 0) or 0
            late = entry.get("late", 0) or 0
            wrong = entry.get("wrong", 0) or 0
            miss = 0
            total = entry.get("total_actions", 0) or (correct + late + wrong)
            avg_ae = 0

        total_correct += correct
        total_late += late
        total_wrong += wrong
        total_miss += miss
        if avg_ae and total:
            ae_weighted += float(avg_ae) * total
            ae_weight += total

    pooled = total_correct + total_late + total_wrong + total_miss
    avg_acc = ((total_correct + total_late) / pooled * 100) if pooled > 0 else 0.0
    avg_ae = (ae_weighted / ae_weight) if ae_weight > 0 else 0.0
    return round(avg_ae, 1), round(avg_acc, 1)


def _public_sessions(raw_sessions):
    if not PUBLIC_MODE:
        return raw_sessions
    return [simust_push.sanitize_session(s) for s in raw_sessions]


@app.get("/get-player-reports/{player_id}")
async def get_player_reports(player_id: str, request: Request):
    users = load_users()
    viewer = current_user(request, users, required=PUBLIC_MODE)
    player_meta = users.get(player_id) or {}
    if not can_access_player(viewer, player_id, player_meta):
        raise HTTPException(403, "You can only view your own training data")
    try:
        player_dir = os.path.join(PLAYER_REPORTS_DIR, player_id)
        index_file = os.path.join(player_dir, "index.json")
        if not os.path.exists(index_file):
            return {"sessions": []}
        with open(index_file, 'r', encoding='utf-8') as f:
            index = json.load(f)
        sessions = []
        for entry in index:
            report_file = os.path.join(player_dir, entry["file"])
            if os.path.exists(report_file):
                with open(report_file, 'r', encoding='utf-8') as f:
                    session_data = json.load(f)
                    sessions.append(session_data)
        sessions.sort(key=lambda x: x.get("session", {}).get("timestamp", ""), reverse=True)
        return {"sessions": _public_sessions(sessions)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get player reports: {e}")
        return {"sessions": [], "error": str(e)}

@app.delete("/delete-player-report/{player_id}/{session_id}")
async def delete_player_report(player_id: str, session_id: str):
    try:
        player_dir = os.path.join(PLAYER_REPORTS_DIR, player_id)
        report_file = os.path.join(player_dir, f"{session_id}.json")
        if os.path.exists(report_file):
            os.remove(report_file)
        index_file = os.path.join(player_dir, "index.json")
        if os.path.exists(index_file):
            with open(index_file, 'r', encoding='utf-8') as f:
                index = json.load(f)
            index = [s for s in index if s.get("session_id") != session_id]
            with open(index_file, 'w', encoding='utf-8') as f:
                json.dump(index, f, indent=2, ensure_ascii=False)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Failed to delete player report: {e}")
        raise HTTPException(500, f"Failed to delete report: {str(e)}")

# ============================================================
# NEW: Unlock Level Endpoint (Admin Only)
# ============================================================

@app.post("/unlock-level")
async def unlock_level(req: Request):
    try:
        data = await req.json()
        player_id = data.get("player_id")
        level_id = data.get("level_id")

        if not player_id or not level_id:
            raise HTTPException(400, "Missing player_id or level_id")

        if level_id not in ALL_LEVELS:
            raise HTTPException(400, "Invalid level ID")

        users = load_users()
        if player_id not in users:
            raise HTTPException(404, "Player not found")

        progress = users[player_id].get("progress", {})
        unlocked = progress.get("unlocked_levels", [])
        if level_id not in unlocked:
            unlocked.append(level_id)
            progress["unlocked_levels"] = unlocked
            # Optionally update current_level to the first unlocked not completed
            completed = progress.get("completed_levels", [])
            for lvl in ALL_LEVELS:
                if lvl in unlocked and lvl not in completed:
                    progress["current_level"] = lvl
                    break
            users[player_id]["progress"] = progress
            save_users(users)
            return {"status": "success", "message": f"Level {level_id} unlocked for player {player_id}"}
        else:
            return {"status": "info", "message": "Level already unlocked"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unlock level error: {e}")
        raise HTTPException(500, f"Failed to unlock level: {str(e)}")


@app.post("/lock-level")
async def lock_level(req: Request):
    try:
        data = await req.json()
        player_id = data.get("player_id")
        level_id = data.get("level_id")

        if not player_id or not level_id:
            raise HTTPException(400, "Missing player_id or level_id")

        if level_id not in ALL_LEVELS:
            raise HTTPException(400, "Invalid level ID")

        if level_id == "L00-Foundation":
            raise HTTPException(400, "Foundation cannot be locked")

        users = load_users()
        if player_id not in users:
            raise HTTPException(404, "Player not found")

        progress = users[player_id].get("progress", {})
        unlocked = list(progress.get("unlocked_levels", []))
        completed = list(progress.get("completed_levels", []))

        if level_id not in unlocked:
            return {"status": "info", "message": "Level already locked"}

        unlocked = [lvl for lvl in unlocked if lvl != level_id]
        completed = [lvl for lvl in completed if lvl != level_id]
        if "L00-Foundation" not in unlocked:
            unlocked.insert(0, "L00-Foundation")

        current = progress.get("current_level")
        if current == level_id or current not in unlocked:
            current = "L00-Foundation"
            for lvl in ALL_LEVELS:
                if lvl in unlocked and lvl not in completed:
                    current = lvl
                    break
            progress["current_level"] = current

        progress["unlocked_levels"] = unlocked
        progress["completed_levels"] = completed
        users[player_id]["progress"] = progress
        save_users(users)
        return {"status": "success", "message": f"Level {level_id} locked for player {player_id}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Lock level error: {e}")
        raise HTTPException(500, f"Failed to lock level: {str(e)}")

# ============================================================
# Manual Stitching Endpoint (unchanged)
# ============================================================

@app.post("/stitch")
async def stitch_videos(req: Request):
    try:
        data = await req.json()
        directory = data.get("directory")
        if not directory or not os.path.isdir(directory):
            raise HTTPException(400, "Valid directory path required")
        cam1_path = os.path.join(directory, "camera-1.mp4")
        cam8_path = os.path.join(directory, "camera-8.mp4")
        if not os.path.exists(cam1_path):
            raise HTTPException(400, "camera-1.mp4 not found")
        if not os.path.exists(cam8_path):
            raise HTTPException(400, "camera-8.mp4 not found")
        cap = cv2.VideoCapture(cam1_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        duration_minutes = (frame_count / fps) / 60 if fps > 0 else 0
        output_path_stitched = os.path.join(directory, "stitched_camera1+camera8.mp4")
        preset = "fast" if duration_minutes > 30 else "medium"
        cmd = [
            "ffmpeg", "-i", cam1_path, "-i", cam8_path,
            "-filter_complex", "[0:v][1:v]hstack=inputs=2[v]",
            "-map", "[v]", "-c:v", "libx264", "-preset", preset, "-crf", "23",
            "-c:a", "aac", "-b:a", "192k", "-y", output_path_stitched
        ]
        timeout_seconds = max(600, int(duration_minutes * 2 * 60))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds)
        if result.returncode != 0:
            logger.error(f"ffmpeg stitching failed:\n{result.stderr}")
            raise HTTPException(500, f"ffmpeg failed: {result.stderr[:400]}")
        logger.info(f"Stitched video created: {output_path_stitched}")
        return {"status": "success", "output": os.path.basename(output_path_stitched), "path": output_path_stitched}
    except subprocess.TimeoutExpired:
        logger.error(f"Stitching timed out after {timeout_seconds} seconds")
        raise HTTPException(500, f"Stitching timed out")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Stitch failed")
        raise HTTPException(500, f"Stitching failed: {str(e)}")

# ============================================================
# NEW: Open Directory Endpoint
# ============================================================

@app.post("/open-directory")
async def open_directory(req: Request):
    try:
        data = await req.json()
        path = data.get("path")
        if not path or not os.path.isdir(path):
            raise HTTPException(400, "Invalid directory path")
        # Normalize path for Windows
        path = os.path.normpath(path)
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return {"status": "success", "message": f"Opened {path}"}
    except Exception as e:
        logger.error(f"Failed to open directory: {e}")
        raise HTTPException(500, f"Failed to open directory: {str(e)}")

# ============================================================
# NEW: Create PDF Report Endpoint
# ============================================================
def _my_simust_page():
    return FileResponse("my_simust.html")

@app.get("/my_simust.html", response_class=FileResponse)
async def my_simust():
    return _my_simust_page()

@app.get("/my-simust", response_class=FileResponse)
async def my_simust_root():
    """Public My SIMUST portal."""
    return _my_simust_page()

@app.get("/my-simust/{page}", response_class=FileResponse)
async def my_simust_view(page: str):
    """Public views: /my-simust/login, /register, /dashboard."""
    if page not in ("login", "register", "dashboard"):
        raise HTTPException(404, "Not found")
    return _my_simust_page()

@app.get("/login", response_class=FileResponse)
@app.get("/register", response_class=FileResponse)
@app.get("/dashboard", response_class=FileResponse)
async def my_simust_host_pages():
    """Short paths for my.simust.com (GET only; POST /login and POST /register stay the API)."""
    return _my_simust_page()

@app.get("/get-players")
async def get_players(request: Request):
    """Return players visible to the caller. Public host: own record only for players."""
    users = load_users()
    viewer = current_user(request, users, required=PUBLIC_MODE)
    players = []
    seen = set()

    # 1. Load from users.json (role = "player")
    for username, user_data in users.items():
        if user_data.get("role") == "player":
            player_id = username
            # Ensure progress exists
            if "progress" not in user_data:
                user_data["progress"] = {
                    "current_level": "L00-Foundation",
                    "unlocked_levels": ["L00-Foundation"],
                    "completed_levels": [],
                    "challenge_results": {}
                }
                # Save the updated user data
                users[username] = user_data
                save_users(users)

            progress = user_data.get("progress", {})
            avg_ae, avg_acc = compute_player_ae_acc(player_id)
            players.append({
                "id": player_id,
                "name": user_data.get("name", player_id),
                "surname": user_data.get("surname", ""),
                "playerId": player_id,
                "club": user_data.get("club", ""),
                "team": user_data.get("team", ""),
                "age": user_data.get("age", ""),
                "image": user_data.get("image", ""),
                "progress": progress,
                "avgAe": avg_ae,
                "avgAcc": avg_acc,
                "sessions": []   # will be loaded separately
            })
            seen.add(player_id)

    # 2. Load from reports directory (existing folders) – fallback for players not in users
    if os.path.exists(PLAYER_REPORTS_DIR):
        for folder in os.listdir(PLAYER_REPORTS_DIR):
            player_dir = os.path.join(PLAYER_REPORTS_DIR, folder)
            if not os.path.isdir(player_dir):
                continue
            if folder in seen:
                continue
            # Try to read name, surname, club, team, age from first session file
            index_file = os.path.join(player_dir, "index.json")
            player_name = folder
            player_surname = ""
            player_player_id = folder
            club = ""
            team = ""
            age = ""
            image = ""
            progress = {"current_level": "L00-Foundation", "unlocked_levels": ["L00-Foundation"], "completed_levels": []}
            if os.path.exists(index_file):
                try:
                    with open(index_file, 'r') as f:
                        index = json.load(f)
                    if index:
                        first_file = index[0].get("file")
                        if first_file:
                            session_file = os.path.join(player_dir, first_file)
                            if os.path.exists(session_file):
                                with open(session_file, 'r') as sf:
                                    session_data = json.load(sf)
                                    player_info = session_data.get("player", {})
                                    player_name = player_info.get("name", folder)
                                    player_surname = player_info.get("surname", "")
                                    player_player_id = player_info.get("playerId", folder)
                                    club = player_info.get("club", "")
                                    team = player_info.get("team", "")
                                    age = player_info.get("age", "")
                                    image = player_info.get("image", "")
                except Exception as e:
                    print(f"Error reading player {folder}: {e}")
            # Try to load progress from a progress file if exists
            progress_file = os.path.join(player_dir, "progress.json")
            if os.path.exists(progress_file):
                try:
                    with open(progress_file, 'r') as f:
                        progress = json.load(f)
                except:
                    pass
            avg_ae, avg_acc = compute_player_ae_acc(folder)
            players.append({
                "id": folder,
                "name": player_name,
                "surname": player_surname,
                "playerId": player_player_id,
                "club": club,
                "team": team,
                "age": age,
                "image": image,
                "progress": progress,
                "avgAe": avg_ae,
                "avgAcc": avg_acc,
                "sessions": []
            })

    visible = []
    for player in players:
        image = player.get("image") or ""
        if PUBLIC_MODE and isinstance(image, str) and image.startswith("data:"):
            player = dict(player)
            player["image"] = ""
        if can_access_player(viewer, player.get("id"), player):
            visible.append(player)
    return {"players": visible}

@app.post("/internal/ingest-player-data")
async def ingest_player_data(request: Request):
    """Receive sanitized player JSON from the lab PC. Requires SIMUST_PUSH_KEY."""
    body = await request.body()
    try:
        simust_push.verify_ingest_headers(
            request.headers.get("x-simust-push-key", ""),
            request.headers.get("x-simust-ts", ""),
            request.headers.get("x-simust-sign", ""),
            body,
        )
    except PermissionError as exc:
        raise HTTPException(401, str(exc))
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    player_id = (data.get("player_id") or "").strip()
    if not simust_push.PLAYER_ID_RE.match(player_id):
        raise HTTPException(400, "Invalid player_id")

    account = data.get("account") or {}
    session_report = simust_push.sanitize_session(data.get("session") or {})
    index_entry = data.get("index_entry") or {}

    users = load_users()
    existing = users.get(player_id) or {}
    merged = dict(existing)
    for field in ("name", "surname", "role", "club", "team", "age", "gender", "email"):
        value = account.get(field)
        if value not in (None, ""):
            merged[field] = value
    if account.get("progress"):
        merged["progress"] = account.get("progress")
    if not existing and account.get("password_hash"):
        merged["password"] = account.get("password_hash")
        merged.setdefault("role", "player")
    if not merged.get("progress"):
        merged["progress"] = {
            "current_level": "L00-Foundation",
            "unlocked_levels": ["L00-Foundation"],
            "completed_levels": [],
            "challenge_results": {},
        }
    users[player_id] = merged
    save_users(users)

    session_id = (session_report.get("session") or {}).get("id") or datetime.now().strftime("%Y%m%d_%H%M%S")
    player_dir = os.path.join(PLAYER_REPORTS_DIR, player_id)
    os.makedirs(player_dir, exist_ok=True)
    session_file = os.path.join(player_dir, f"{session_id}.json")
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(session_report, f, indent=2, ensure_ascii=False)

    index_file = os.path.join(player_dir, "index.json")
    index = []
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            try:
                index = json.load(f)
            except Exception:
                index = []
    index = [row for row in index if row.get("session_id") != session_id]
    if not index_entry:
        index_entry = {
            "session_id": session_id,
            "timestamp": (session_report.get("session") or {}).get("timestamp", ""),
            "level": (session_report.get("session") or {}).get("level", ""),
            "file": f"{session_id}.json",
        }
    index_entry["file"] = f"{session_id}.json"
    index.append(index_entry)
    index.sort(key=lambda row: row.get("timestamp", ""), reverse=True)
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    logger.info("Ingested pushed session %s for %s", session_id, player_id)
    return {"status": "success", "player_id": player_id, "session_id": session_id}
    
@app.post("/create-pdf-report")
async def create_pdf_report(req: Request):
    try:
        data = await req.json()
        directory = data.get("directory")
        if not directory or not os.path.isdir(directory):
            raise HTTPException(400, "Invalid directory")

        # Locate the session JSON file associated with this directory
        session_data = None
        for player_id in os.listdir(PLAYER_REPORTS_DIR):
            player_dir = os.path.join(PLAYER_REPORTS_DIR, player_id)
            if os.path.isdir(player_dir):
                index_file = os.path.join(player_dir, "index.json")
                if os.path.exists(index_file):
                    with open(index_file, 'r') as f:
                        index = json.load(f)
                    for entry in index:
                        report_file = os.path.join(player_dir, entry["file"])
                        if os.path.exists(report_file):
                            with open(report_file, 'r') as f:
                                report = json.load(f)
                                if report.get("session", {}).get("directory") == directory:
                                    session_data = report
                                    break
                    if session_data:
                        break

        if not session_data:
            # Fallback: read results.json from the directory
            results_json = os.path.join(directory, "results.json")
            if os.path.exists(results_json):
                with open(results_json, 'r') as f:
                    results = json.load(f)
                session_data = {
                    "session": {"directory": directory, "level": "Unknown"},
                    "statistics": {},
                    "actions": results
                }
            else:
                raise HTTPException(404, "No session data found for this directory")

        # Generate PDF
        pdf_path = os.path.join(directory, "session_report.pdf")
        doc = SimpleDocTemplate(pdf_path, pagesize=A4)
        styles = getSampleStyleSheet()
        title_style = styles['Title']
        heading_style = styles['Heading2']
        normal_style = styles['Normal']

        story = []

        # Title
        story.append(Paragraph("SIMUST Session Report", title_style))
        story.append(Spacer(1, 0.25*inch))

        # Player info
        player = session_data.get("player", {})
        story.append(Paragraph(f"Player: {player.get('name', '')} {player.get('surname', '')} (ID: {player.get('playerId', 'N/A')})", normal_style))
        story.append(Paragraph(f"Session Date: {session_data.get('session', {}).get('timestamp', 'N/A')}", normal_style))
        story.append(Paragraph(f"Level: {session_data.get('session', {}).get('level', 'N/A')}", normal_style))
        story.append(Spacer(1, 0.2*inch))

        # Statistics
        stats = session_data.get("statistics", {})
        story.append(Paragraph("Statistics", heading_style))
        stats_data = [
            ["Correct", str(stats.get("correct", 0))],
            ["Late", str(stats.get("late", 0))],
            ["Wrong", str(stats.get("wrong", 0))],
            ["Miss", str(stats.get("miss", 0))],
            ["Average AE", f"{stats.get('avg_ae', 0):.1f}%"],
            ["Total Actions", str(stats.get("total_actions", 0))],
            ["Avg Finishing Time", f"{stats.get('avg_finishing_time', 0):.2f}s"],
            ["Total Distance", f"{stats.get('total_distance', 0):.1f} m"],
            ["AEP Left", f"{stats.get('aep_left', 0):.1f}%"],
            ["AEP Right", f"{stats.get('aep_right', 0):.1f}%"]
        ]
        t = Table(stats_data, colWidths=[2*inch, 2*inch])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.grey),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,0), 12),
            ('BOTTOMPADDING', (0,0), (-1,0), 12),
            ('BACKGROUND', (0,1), (-1,-1), colors.beige),
            ('GRID', (0,0), (-1,-1), 1, colors.black)
        ]))
        story.append(t)
        story.append(Spacer(1, 0.3*inch))

        # Actions table
        actions = session_data.get("actions", [])
        if actions:
            story.append(Paragraph("Actions", heading_style))
            action_table_data = [["ID", "Action", "Screens", "Result", "Goal Screen", "AEP", "AE"]]
            for act in actions:
                action_table_data.append([
                    act.get("block_id", ""),
                    act.get("action", ""),
                    ", ".join(act.get("screens", [])),
                    act.get("finishing_type", ""),
                    act.get("goal_screen", "N/A"),
                    act.get("aep", "N/A"),
                    str(act.get("ae", 0))
                ])
            t2 = Table(action_table_data, colWidths=[0.8*inch, 0.8*inch, 1.2*inch, 1*inch, 1*inch, 0.8*inch, 0.8*inch])
            t2.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.grey),
                ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('FONTSIZE', (0,0), (-1,0), 10),
                ('BOTTOMPADDING', (0,0), (-1,0), 12),
                ('BACKGROUND', (0,1), (-1,-1), colors.beige),
                ('GRID', (0,0), (-1,-1), 1, colors.black),
                ('FONTSIZE', (0,1), (-1,-1), 8),
            ]))
            story.append(t2)

        doc.build(story)

        return FileResponse(pdf_path, filename="session_report.pdf", media_type='application/pdf')
    except Exception as e:
        logger.error(f"PDF generation failed: {e}", exc_info=True)
        raise HTTPException(500, f"PDF generation failed: {str(e)}")


@app.post("/register")
async def register(req: Request):
    try:
        data = await req.json()
    except:
        raise HTTPException(400, "Invalid JSON")

    check_auth_rate(req)
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    name = data.get("name", "").strip()
    surname = data.get("surname", "").strip()
    age = data.get("age", "").strip()
    club = data.get("club", "").strip()
    team = data.get("team", "").strip()
    role = data.get("role", "player").strip()
    image = data.get("image", "").strip()
    if PUBLIC_MODE and image.startswith("data:"):
        image = ""
    gender = data.get("gender", "").strip()
    email = data.get("email", "").strip().lower()
    country_code = data.get("country_code", "").strip()
    phone_number = data.get("phone", "").strip()

    if not username or not password or not name or not surname or not role:
        raise HTTPException(400, "Missing required fields")
    if PUBLIC_MODE and len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if not email or not EMAIL_RE.match(email):
        raise HTTPException(400, "Valid email is required")
    if not country_code.startswith("+"):
        raise HTTPException(400, "Phone country code is required")
    if not phone_number or not PHONE_RE.match(phone_number):
        raise HTTPException(400, "Valid phone number is required")
    phone = f"{country_code} {phone_number}"

    users = load_users()
    if username in users:
        raise HTTPException(400, "Username already exists")

    # pbkdf2 on the public host; legacy MD5 hashes are upgraded on next sign-in
    hashed = hash_password(password)

    # Initialize progress
    progress = {
        "current_level": "L00-Foundation",
        "unlocked_levels": ["L00-Foundation"],
        "completed_levels": [],
        "challenge_results": {}
    }

    users[username] = {
        "password": hashed,
        "name": name,
        "surname": surname,
        "age": age,
        "gender": gender,
        "club": club,
        "team": team,
        "role": role,
        "email": email,
        "phone": phone,
        "country_code": country_code,
        "image": image,
        "progress": progress
    }
    save_users(users)

    email_payload = {
        "username": username,
        "name": name,
        "surname": surname,
        "email": email,
        "phone": phone,
        "role": role,
        "club": club,
        "team": team,
        "age": age,
        "gender": gender,
    }
    threading.Thread(target=send_registration_email, args=(email_payload,), daemon=True).start()
    return {"status": "success", "message": "User registered"}

@app.post("/login")
async def login(req: Request):
    try:
        data = await req.json()
    except:
        raise HTTPException(400, "Invalid JSON")

    check_auth_rate(req)
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        raise HTTPException(400, "Missing credentials")

    users = load_users()
    if username not in users:
        raise HTTPException(401, "Invalid credentials")

    user = users[username]
    ok, upgraded = verify_password(password, user.get("password", ""))
    if not ok:
        raise HTTPException(401, "Invalid credentials")
    if upgraded:
        users[username]["password"] = upgraded
        save_users(users)

    image = user.get("image") or ""
    if PUBLIC_MODE and isinstance(image, str) and image.startswith("data:"):
        image = ""

    return {
        "username": username,
        "role": user["role"],
        "name": user["name"],
        "surname": user["surname"],
        "club": user["club"],
        "team": user["team"],
        "age": user["age"],
        "gender": user.get("gender", "Male"),
        "image": image,
        "progress": user.get("progress", {}),
        "token": issue_token(username, user.get("role", "player")),
    }
    
@app.post("/update-profile")
async def update_profile(req: Request):
    try:
        data = await req.json()
    except:
        raise HTTPException(400, "Invalid JSON")

    username = data.get("username", "").strip()
    name = data.get("name", "").strip()
    surname = data.get("surname", "").strip()
    age = data.get("age", "").strip()
    club = data.get("club", "").strip()
    team = data.get("team", "").strip()
    image = data.get("image", "").strip()

    if not username:
        raise HTTPException(400, "Username required")

    users = load_users()
    viewer = current_user(req, users, required=PUBLIC_MODE)
    if viewer and viewer["username"] != username:
        raise HTTPException(403, "You can only update your own profile")
    if username not in users:
        raise HTTPException(404, "User not found")

    # Update fields
    users[username]["name"] = name
    users[username]["surname"] = surname
    users[username]["age"] = age
    users[username]["club"] = club
    users[username]["team"] = team
    if image:
        users[username]["image"] = image

    save_users(users)
    return {"status": "success", "message": "Profile updated"}


# ============================================================
# RESERVATION ENDPOINTS (training place shared calendar)
# ============================================================

@app.get("/reservations/today")
async def reservations_today():
    """Public compact list of today's bookings (names + times only)."""
    today = datetime.now().date()
    day_start = datetime.combine(today, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    items = []
    with RESERVATION_LOCK:
        bookings = load_reservations()
    for item in bookings:
        try:
            start = _parse_iso_dt(item.get("start", ""), "start")
            end = _parse_iso_dt(item.get("end", ""), "end")
        except HTTPException:
            continue
        if not _intervals_overlap(start, end, day_start, day_end):
            continue
        items.append({
            "id": item.get("id"),
            "player_name": item.get("player_name") or "Booked",
            "start": start.strftime("%H:%M"),
            "end": end.strftime("%H:%M"),
            "start_iso": start.isoformat(timespec="seconds"),
            "end_iso": end.isoformat(timespec="seconds"),
        })
    items.sort(key=lambda row: row.get("start_iso", ""))
    return {
        "date": today.isoformat(),
        "open": f"{RESERVATION_OPEN_HOUR:02d}:00",
        "close": f"{RESERVATION_CLOSE_HOUR:02d}:00",
        "reservations": items,
    }


@app.get("/reservations")
async def list_reservations(request: Request):
    """List bookings in a date range. No emails or passwords."""
    range_from = _parse_range_bound(request.query_params.get("from", ""), end_of_day=False)
    range_to = _parse_range_bound(request.query_params.get("to", ""), end_of_day=True)
    if range_from is None:
        range_from = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if range_to is None:
        range_to = range_from + timedelta(days=14)
    if range_to <= range_from:
        raise HTTPException(400, "Invalid date range")
    with RESERVATION_LOCK:
        bookings = load_reservations()
    results = []
    for item in bookings:
        try:
            start = _parse_iso_dt(item.get("start", ""), "start")
            end = _parse_iso_dt(item.get("end", ""), "end")
        except HTTPException:
            continue
        if _intervals_overlap(start, end, range_from, range_to):
            results.append(_public_reservation(item))
    results.sort(key=lambda row: row.get("start", ""))
    return {"reservations": results}


@app.post("/reservations")
async def create_reservation(req: Request):
    try:
        data = await req.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    username = (data.get("player_id") or data.get("username") or "").strip()
    if not username:
        raise HTTPException(400, "player_id or username is required")

    start = _parse_iso_dt(data.get("start", ""), "start")
    end = _parse_iso_dt(data.get("end", ""), "end")
    duration = _validate_reservation_window(start, end)

    users = load_users()
    user = users.get(username)
    if not user:
        raise HTTPException(404, "Player not found")

    display_name = _player_display_name(user, username)
    created = None
    with RESERVATION_LOCK:
        bookings = load_reservations()
        for item in bookings:
            try:
                existing_start = _parse_iso_dt(item.get("start", ""), "start")
                existing_end = _parse_iso_dt(item.get("end", ""), "end")
            except HTTPException:
                continue
            if _intervals_overlap(start, end, existing_start, existing_end):
                raise HTTPException(409, "That time overlaps an existing reservation")
        payment_status = str(data.get("payment_status") or "").strip() or "simulated"
        created = {
            "id": str(uuid.uuid4()),
            "player_id": username,
            "player_name": display_name,
            "start": start.isoformat(timespec="seconds"),
            "end": end.isoformat(timespec="seconds"),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "payment_status": payment_status,
        }
        bookings.append(created)
        save_reservations(bookings)

    email_user = {
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "surname": user.get("surname", ""),
    }
    threading.Thread(
        target=send_reservation_email,
        args=(created, email_user),
        daemon=True,
    ).start()
    public = _public_reservation(created)
    public["duration_minutes"] = duration
    return public


@app.delete("/reservations/{id}")
async def delete_reservation(id: str, request: Request):
    username = request.query_params.get("username", "").strip()
    try:
        body = await request.json()
        if isinstance(body, dict):
            username = username or (body.get("username") or body.get("player_id") or "").strip()
    except Exception:
        pass
    if not username:
        raise HTTPException(400, "username is required")

    users = load_users()
    actor = users.get(username)
    if not actor:
        raise HTTPException(404, "User not found")
    staff = str(actor.get("role", "")).strip().lower() in RESERVATION_STAFF_ROLES

    with RESERVATION_LOCK:
        bookings = load_reservations()
        found = None
        remaining = []
        for item in bookings:
            if item.get("id") == id:
                found = item
            else:
                remaining.append(item)
        if not found:
            raise HTTPException(404, "Reservation not found")
        owner = found.get("player_id", "")
        if owner != username and not staff:
            raise HTTPException(403, "You can only cancel your own reservation")
        save_reservations(remaining)

    return {"status": "success", "id": id}


# ============================================================
# Main Entry Point
# ============================================================

if __name__ == "__main__":
    multiprocessing.freeze_support()
    host = os.environ.get("SIMUST_HOST", "0.0.0.0")
    port = int(os.environ.get("SIMUST_PORT", "8000"))
    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        timeout_keep_alive=300,
        timeout_graceful_shutdown=60,
        log_level="info",
    )