"""Sampling: Start/Stop records a clean 3840×1080 stitch video.

No red zones, no overlays, no labels. Each Start creates a new playable
MJPG AVI (motion-safe) under <data_samples>/. A live JPEG preview is updated
for the Settings screen. Cabinet images refresh every 2s for ~3 min.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_DIR = os.path.dirname(os.path.abspath(__file__))
SIM_WIDTH = 1280
SIM_HEIGHT = 360
SAVE_WIDTH = 3840
SAVE_HEIGHT = 1080
RECORD_FPS = 15.0

_lock = threading.Lock()
_seq_lock = threading.Lock()
_seq_stamp = ""
_seq_n = 0

_preview: Dict[str, Any] = {}
_control: Dict[str, Any] = {
    "live": False,  # On/Off live view in Settings
    "active": False,  # recording
    "saved_count": 0,
    "last_path": "",
    "video_path": "",
    "started_at": "",
    "stopped_at": "",
    "frame_count": 0,
    "error": "",
    "playlist_screen": 0,
    "playlist_content": "",
}

_stop_event: Optional[threading.Event] = None
_worker: Optional[threading.Thread] = None
_writer = None
_writer_path = ""
_writer_lock = threading.Lock()
_last_frame = None
_last_frame_lock = threading.Lock()
_last_frame_seq = 0
_last_frame_at = 0.0
_record_t0 = 0.0
_record_origin_frames = 0
_writer_stop: Optional[threading.Event] = None
_writer_worker: Optional[threading.Thread] = None
_cam_stop: Optional[threading.Event] = None
_cam_workers: list = []
_cam_frames: Dict[str, Any] = {"left": None, "right": None}
_cam_frame_at: Dict[str, float] = {"left": 0.0, "right": 0.0}
_cam_lock = threading.Lock()

# Cabinet playlist while recording: screens 1→6, 30s each, new content every 2s.
SCREEN_HOLD_S = 30.0
CONTENT_SWAP_S = 2.0
# Brief "STA" cue on the focus screens before each 30s block.
START_FLASH_S = 1.0
START_CUE_TEXT = "STA"
# Match smart_simust_player display sizes for real tests.
PASS_IMAGE_BASE_SCALE = 0.564
PASS_IMAGE_SCALE = round(PASS_IMAGE_BASE_SCALE * 1.05, 4)
# Entry / Activated / HP / Elite Players stills (same formula as player).
ENTRY_S0_PASS_IMAGE_SCALE = round(
    PASS_IMAGE_BASE_SCALE * 1.10 * 1.30 * 1.15 * 1.10 * 0.80 * 1.10 * 1.05, 4
)
PLAYERS_IMAGE_SCALE = float(ENTRY_S0_PASS_IMAGE_SCALE)
# Numbers / divergent letters fill the screen like entry_digits / Elite / WC.
NUMBER_TILE_SCALE = 1.0
_playlist_stop: Optional[threading.Event] = None
_playlist_worker: Optional[threading.Thread] = None
_playlist_state: Dict[str, Any] = {
    "screen_n": 0,
    "elapsed_s": 0.0,
    "content": "",
}


def _player_dir() -> str:
    env = os.environ.get("SIMUST_PLAYER_DIRECTORY")
    if env:
        return env
    return "C:/Users/siama/Documents/simust_player"


def _control_path() -> str:
    env = os.environ.get("SIMUST_SAMPLING_CONTROL")
    if env:
        return env
    return os.path.join(_player_dir(), "sampling_control.json")


def _recordings_root() -> str:
    default = "C:/Users/siama/Documents/simust_realtime_recordings"
    return os.environ.get("SIMUST_REALTIME_DIR", default)


def samples_dir() -> str:
    path = os.path.join(_recordings_root(), "data_samples")
    os.makedirs(path, exist_ok=True)
    return path


def display_file_path() -> str:
    env = os.environ.get("SIMUST_SAMPLING_DISPLAY")
    if env:
        return env
    return os.path.join(_player_dir(), "sampling_display.json")


def cache_dir() -> str:
    path = os.path.join(_player_dir(), "sampling_content_cache")
    os.makedirs(path, exist_ok=True)
    return path


def _write_control_file(payload: dict) -> None:
    path = _control_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    os.replace(tmp, path)


def _sync_control() -> dict:
    with _lock:
        cur = dict(_control)
    cur["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        _write_control_file(cur)
    except OSError as exc:
        logger.warning("sampling control write failed: %s", exc)
    return cur


def read_control() -> dict:
    with _lock:
        cur = dict(_control)
    if cur.get("active") or cur.get("last_path") or cur.get("video_path"):
        return cur
    path = _control_path()
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"active": False, "saved_count": 0}


def is_active() -> bool:
    with _lock:
        return bool(_control.get("active"))


def is_live() -> bool:
    with _lock:
        return bool(_control.get("live"))


def next_sample_path(ext: str = ".mp4") -> str:
    """date_hour_minute_second_NNNN.mp4 under data_samples."""
    global _seq_stamp, _seq_n
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    with _seq_lock:
        if stamp != _seq_stamp:
            _seq_stamp = stamp
            _seq_n = 0
        _seq_n += 1
        n = _seq_n
    name = f"{stamp}_{n:04d}{ext}"
    return os.path.join(samples_dir(), name)


def _to_save_size(frame):
    try:
        import cv2
    except Exception:
        return None
    if frame is None:
        return None
    try:
        h, w = frame.shape[:2]
    except Exception:
        return None
    if int(w) == int(SAVE_WIDTH) and int(h) == int(SAVE_HEIGHT):
        try:
            return frame.copy()
        except Exception:
            return frame
    try:
        return cv2.resize(
            frame,
            (int(SAVE_WIDTH), int(SAVE_HEIGHT)),
            interpolation=cv2.INTER_LINEAR,
        )
    except Exception:
        return None


def _camera_urls():
    try:
        import simust_homography
    except Exception:
        return "", ""
    cams = getattr(simust_homography, "LAB_CAMERAS", {}) or {}
    left_url = cams.get(getattr(simust_homography, "LEFT_CAMERA", "camera-1")) or ""
    right_url = cams.get(getattr(simust_homography, "RIGHT_CAMERA", "camera-8")) or ""
    return left_url, right_url


def _open_cap(url: str):
    import cv2

    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    if not cap.isOpened():
        cap.release()
        return None
    return cap


def _read_latest(cap, flush: int = 2):
    if cap is None:
        return None
    frame = None
    for _ in range(max(1, int(flush))):
        ok, grabbed = cap.read()
        if ok and grabbed is not None:
            frame = grabbed
    return frame


def _frame_looks_corrupt(frame) -> bool:
    """Detect incomplete RTSP decode (bottom-half purple smear / dead band)."""
    try:
        import numpy as np
    except Exception:
        return frame is None
    if frame is None:
        return True
    try:
        h, w = frame.shape[:2]
    except Exception:
        return True
    if h < 32 or w < 32:
        return True
    mid = h // 2
    # Use luminance so channel imbalance does not inflate std.
    try:
        top_y = frame[:mid].astype(np.float32).mean(axis=2)
        bot_y = frame[mid:].astype(np.float32).mean(axis=2)
        top_std = float(top_y.std())
        bot_std = float(bot_y.std())
    except Exception:
        return True
    # Classic cam-1 tear: top OK, bottom almost flat / smeared.
    if top_std > 12.0 and bot_std < max(3.5, top_std * 0.22):
        return True
    # Purple/black smear: low green, elevated blue relative to top.
    try:
        top_g = float(frame[:mid, :, 1].mean())
        bot_g = float(frame[mid:, :, 1].mean())
        bot_b = float(frame[mid:, :, 0].mean())
        if top_g > 40 and bot_g < top_g * 0.45 and bot_b > bot_g * 1.15 and bot_std < 10:
            return True
    except Exception:
        pass
    # Many bottom rows nearly identical (vertical streak / tear).
    try:
        row_means = bot_y.mean(axis=1)
        row_std = float(np.std(row_means))
        # Strong vertical gradient with flat rows → smear pulled downward.
        if top_std > 12.0 and row_std < 2.5 and bot_std < 8.0:
            return True
        if top_std > 12.0 and row_std < 6.0:
            # Abrupt energy drop below mid-frame.
            edge = abs(float(top_y[-3:].mean()) - float(bot_y[:3].mean()))
            if edge > 25.0 and bot_std < top_std * 0.5:
                return True
    except Exception:
        pass
    return False


def _stitch_pair(left, right):
    try:
        import simust_goal_calibrate as gc
    except Exception:
        return None
    try:
        if _frame_looks_corrupt(left) or _frame_looks_corrupt(right):
            return None
        left_r = gc._resize_cam_like_realtime(left, SAVE_HEIGHT)
        right_r = gc._resize_cam_like_realtime(right, SAVE_HEIGHT)
        if _frame_looks_corrupt(left_r) or _frame_looks_corrupt(right_r):
            return None
        return _to_save_size(gc._stitch_halves(left_r, right_r))
    except Exception as exc:
        logger.warning("full stitch grab failed: %s", exc)
        return None


def _cam_grab_loop(name: str, url: str, stop_event: threading.Event) -> None:
    """Keep a fresh good frame for one camera (reconnect on stall/corruption)."""
    import cv2

    fails = 0
    while not stop_event.is_set():
        cap = _open_cap(url)
        if cap is None:
            stop_event.wait(1.0)
            continue
        try:
            while not stop_event.is_set():
                ok, grabbed = cap.read()
                if not ok or grabbed is None:
                    fails += 1
                    if fails >= 15:
                        break
                    continue
                # Drop stale buffered packets, keep the newest readable frame.
                for _ in range(2):
                    more, nxt = cap.read()
                    if more and nxt is not None:
                        grabbed = nxt
                    else:
                        break
                if _frame_looks_corrupt(grabbed):
                    fails += 1
                    if fails >= 20:
                        break
                    continue
                fails = 0
                try:
                    copy = grabbed.copy()
                except Exception:
                    copy = grabbed
                with _cam_lock:
                    _cam_frames[name] = copy
                    _cam_frame_at[name] = time.time()
        finally:
            try:
                cap.release()
            except Exception:
                pass
        if not stop_event.is_set():
            stop_event.wait(0.35)


def _start_cam_workers() -> None:
    global _cam_stop, _cam_workers
    left_url, right_url = _camera_urls()
    if not left_url or not right_url:
        return
    if _cam_workers and all(t.is_alive() for t in _cam_workers):
        return
    _stop_cam_workers()
    stop_event = threading.Event()
    _cam_stop = stop_event
    workers = []
    for name, url in (("left", left_url), ("right", right_url)):
        thread = threading.Thread(
            target=_cam_grab_loop,
            args=(name, url, stop_event),
            name=f"simust-sampling-cam-{name}",
            daemon=True,
        )
        workers.append(thread)
        thread.start()
    _cam_workers = workers


def _stop_cam_workers() -> None:
    global _cam_stop, _cam_workers
    event = _cam_stop
    workers = list(_cam_workers or [])
    if event is not None:
        event.set()
    for thread in workers:
        if thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
    _cam_stop = None
    _cam_workers = []
    with _cam_lock:
        _cam_frames["left"] = None
        _cam_frames["right"] = None
        _cam_frame_at["left"] = 0.0
        _cam_frame_at["right"] = 0.0


def _latest_cam_pair(max_age_s: float = 1.25):
    now = time.time()
    with _cam_lock:
        left = _cam_frames.get("left")
        right = _cam_frames.get("right")
        left_at = float(_cam_frame_at.get("left") or 0.0)
        right_at = float(_cam_frame_at.get("right") or 0.0)
        if left is not None:
            try:
                left = left.copy()
            except Exception:
                pass
        if right is not None:
            try:
                right = right.copy()
            except Exception:
                pass
    if left is None or right is None:
        return None, None
    if now - left_at > max_age_s or now - right_at > max_age_s:
        return None, None
    return left, right


def capture_full_stitch_frame():
    """Grab camera-1 + camera-8 at 3840×1080 with no labels / overlays."""
    left, right = _latest_cam_pair()
    if left is not None and right is not None:
        stitched = _stitch_pair(left, right)
        if stitched is not None:
            return stitched
    left_url, right_url = _camera_urls()
    if not left_url or not right_url:
        return None
    left_cap = _open_cap(left_url)
    right_cap = _open_cap(right_url)
    try:
        left = None
        right = None
        for _ in range(12):
            left = _read_latest(left_cap, flush=3) or left
            right = _read_latest(right_cap, flush=3) or right
            if (
                left is not None
                and right is not None
                and not _frame_looks_corrupt(left)
                and not _frame_looks_corrupt(right)
            ):
                break
            time.sleep(0.02)
        return _stitch_pair(left, right)
    finally:
        if left_cap is not None:
            left_cap.release()
        if right_cap is not None:
            right_cap.release()


def _set_preview_from_frame(frame) -> None:
    """Store a lightweight JPEG preview for the Settings live view."""
    global _preview
    try:
        import cv2
    except Exception:
        return
    if frame is None:
        return
    try:
        preview = cv2.resize(
            frame,
            (int(SIM_WIDTH), int(SIM_HEIGHT)),
            interpolation=cv2.INTER_AREA,
        )
        ok, buf = cv2.imencode(".jpg", preview, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ok:
            return
        data_url = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")
        with _lock:
            _preview = {
                "data_url": data_url,
                "width": SIM_WIDTH,
                "height": SIM_HEIGHT,
                "captured_at": time.time(),
            }
    except Exception as exc:
        logger.warning("sampling preview encode failed: %s", exc)


def capture_stitched_preview(force_live: bool = True) -> dict:
    """One clean stitch preview (no annotation) for the Settings screen."""
    del force_live
    frame = capture_full_stitch_frame()
    if frame is None:
        with _lock:
            return dict(_preview) if _preview else {}
    _set_preview_from_frame(frame)
    with _lock:
        return dict(_preview)


def _prepare_write_frame(frame):
    """Ensure a contiguous BGR uint8 frame at SAVE_WIDTH×SAVE_HEIGHT."""
    try:
        import numpy as np
    except Exception:
        return None
    if frame is None:
        return None
    try:
        out = _to_save_size(frame)
        if out is None:
            return None
        if out.dtype != np.uint8:
            out = out.astype(np.uint8)
        if not out.flags["C_CONTIGUOUS"]:
            out = np.ascontiguousarray(out)
        if out.ndim != 3 or out.shape[2] < 3:
            return None
        if out.shape[2] > 3:
            out = out[:, :, :3]
        return out
    except Exception:
        return None


def _open_writer(path: str):
    """Open a playable writer. Prefer MJPG AVI (no inter-frame freeze), then H.264."""
    import cv2

    base = os.path.splitext(path)[0]
    # MJPG first: every frame is independent, so motion stays visible even when
    # capture briefly stalls. H.264 often collapses a stall into a "frozen" clip.
    candidates = (
        (base + ".avi", "MJPG"),
        (base + ".avi", "XVID"),
        (base + ".mp4", "avc1"),
        (base + ".mp4", "H264"),
        (base + ".mp4", "mp4v"),
    )
    for out_path, tag in candidates:
        try:
            fourcc = cv2.VideoWriter_fourcc(*tag)
            writer = cv2.VideoWriter(
                out_path,
                fourcc,
                float(RECORD_FPS),
                (int(SAVE_WIDTH), int(SAVE_HEIGHT)),
            )
        except Exception:
            continue
        if writer is not None and writer.isOpened():
            logger.info("sampling writer opened %s (%s)", out_path, tag)
            return writer, out_path
        try:
            writer.release()
        except Exception:
            pass
    return None, path


def _close_writer(finalize: bool = True) -> None:
    """Release the current VideoWriter; bump saved_count when a clip was written."""
    global _writer, _writer_path
    with _writer_lock:
        writer = _writer
        path = _writer_path
        _writer = None
        _writer_path = ""
    if writer is None:
        return
    try:
        writer.release()
    except Exception:
        pass
    if not finalize:
        return
    with _lock:
        frames = int(_control.get("frame_count") or 0)
        _control["active"] = False
        _control["stopped_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        if frames > 0:
            _control["saved_count"] = int(_control.get("saved_count") or 0) + 1
            _control["last_path"] = path or _control.get("last_path") or ""
            _control["video_path"] = path or _control.get("video_path") or ""
    _sync_control()
    logger.info("sampling video finalized: %s", path)


def _set_last_frame(frame) -> None:
    global _last_frame, _last_frame_seq, _last_frame_at
    prepared = _prepare_write_frame(frame)
    if prepared is None:
        return
    if _frame_looks_corrupt(prepared):
        return
    with _last_frame_lock:
        _last_frame = prepared
        _last_frame_seq = int(_last_frame_seq or 0) + 1
        _last_frame_at = time.time()


def _get_last_frame():
    with _last_frame_lock:
        frame = _last_frame
        if frame is None:
            return None
        try:
            return frame.copy()
        except Exception:
            return frame


def _last_frame_info() -> tuple:
    with _last_frame_lock:
        return int(_last_frame_seq or 0), float(_last_frame_at or 0.0)


def _write_one_frame(frame) -> bool:
    """Write exactly one paced frame (no burst). Returns False on hard failure."""
    prepared = _prepare_write_frame(frame)
    if prepared is None:
        return True
    with _writer_lock:
        writer = _writer
        path = _writer_path
    if writer is None:
        return True
    try:
        writer.write(prepared)
    except Exception as exc:
        logger.warning("sampling write failed: %s", exc)
        with _lock:
            _control["error"] = str(exc)
        _close_writer(finalize=True)
        return False
    with _lock:
        _control["frame_count"] = int(_control.get("frame_count") or 0) + 1
        _control["last_path"] = path or _control.get("last_path") or ""
        _control["video_path"] = path or _control.get("video_path") or ""
        frames = int(_control.get("frame_count") or 0)
    if frames and frames % 30 == 0:
        _sync_control()
    return True


def _writer_loop(stop_event: threading.Event) -> None:
    """Pace exactly RECORD_FPS frames/sec from the latest good stitch."""
    period = 1.0 / max(1.0, float(RECORD_FPS))
    next_due = time.time()
    last_seq_written = -1
    stall_logged = False
    while not stop_event.is_set():
        with _lock:
            recording = bool(_control.get("active"))
        if not recording:
            break
        # Prefer a brand-new stitch; fall back to last good only briefly.
        seq, stamped = _last_frame_info()
        frame = _get_last_frame()
        if frame is not None:
            age = time.time() - stamped if stamped else 999.0
            if seq != last_seq_written or age <= 0.75:
                if not _write_one_frame(frame):
                    break
                last_seq_written = seq
                stall_logged = False
            elif not stall_logged and age > 1.5:
                logger.warning("sampling capture stalled (%.1fs) — holding last good frame", age)
                stall_logged = True
                if not _write_one_frame(frame):
                    break
            else:
                if not _write_one_frame(frame):
                    break
        next_due += period
        now = time.time()
        delay = next_due - now
        if delay > 0:
            stop_event.wait(delay)
        elif delay < -1.0:
            # Avoid runaway backlog after a stall.
            next_due = now


def _start_writer_thread() -> None:
    global _writer_stop, _writer_worker
    _stop_writer_thread()
    stop_event = threading.Event()
    _writer_stop = stop_event
    worker = threading.Thread(
        target=_writer_loop,
        args=(stop_event,),
        name="simust-sampling-writer",
        daemon=True,
    )
    _writer_worker = worker
    worker.start()


def _stop_writer_thread() -> None:
    global _writer_stop, _writer_worker
    event = _writer_stop
    worker = _writer_worker
    if event is not None:
        event.set()
    if worker is not None and worker.is_alive() and worker is not threading.current_thread():
        worker.join(timeout=3.0)
    _writer_stop = None
    _writer_worker = None


def _ensure_live_worker() -> None:
    """Keep one camera stitch thread running for live view and/or record."""
    global _stop_event, _worker
    if _worker is not None and _worker.is_alive():
        return
    stop_event = threading.Event()
    _stop_event = stop_event
    worker = threading.Thread(
        target=_live_loop,
        args=(stop_event,),
        name="simust-sampling-live",
        daemon=True,
    )
    _worker = worker
    worker.start()


def _stop_live_worker() -> None:
    global _stop_event, _worker
    event = _stop_event
    worker = _worker
    if event is not None:
        event.set()
    if worker is not None and worker.is_alive():
        worker.join(timeout=8.0)
    _stop_event = None
    _worker = None


def _live_loop(stop_event: threading.Event) -> None:
    """Continuous clean stitch for live preview + latest-frame feed for the writer."""
    try:
        _start_cam_workers()
        period = 1.0 / max(1.0, float(RECORD_FPS))
        while not stop_event.is_set():
            with _lock:
                live = bool(_control.get("live"))
                recording = bool(_control.get("active"))
            if not live and not recording:
                break
            t0 = time.time()
            left, right = _latest_cam_pair()
            frame = None
            if left is not None and right is not None:
                frame = _stitch_pair(left, right)
            if frame is None:
                frame = capture_full_stitch_frame()
            if frame is not None and not _frame_looks_corrupt(frame):
                _set_last_frame(frame)
                if live:
                    _set_preview_from_frame(frame)
            elapsed = time.time() - t0
            delay = period - elapsed
            if delay > 0:
                stop_event.wait(delay)
            else:
                stop_event.wait(0.01)
    finally:
        # If the loop exits while still marked live/recording, clear live;
        # recording is finalized by stop_sample / set_live(False).
        with _lock:
            still_live = bool(_control.get("live"))
            still_rec = bool(_control.get("active"))
        if still_rec:
            try:
                _stop_writer_thread()
            except Exception:
                pass
            _close_writer(finalize=True)
        if still_live:
            with _lock:
                _control["live"] = False
            _sync_control()
        if not still_live and not still_rec:
            _stop_cam_workers()


def set_live(on: bool) -> dict:
    """Settings On/Off switch for the online Sampling video view."""
    global _preview
    want = bool(on)
    with _lock:
        was = bool(_control.get("live"))
        _control["live"] = want
    if want:
        _start_cam_workers()
        if not was:
            try:
                capture_stitched_preview(force_live=True)
            except Exception:
                pass
        _ensure_live_worker()
    else:
        # Turning live Off also stops recording.
        if is_active():
            with _lock:
                _control["live"] = False
            stop_sample()
        with _lock:
            _control["live"] = False
            _preview = {}
        _stop_live_worker()
        _stop_cam_workers()
    return _sync_control()


def _write_display(payload: dict) -> None:
    path = display_file_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    os.replace(tmp, path)


def clear_display() -> None:
    _write_display(
        {
            "active": False,
            "seq": int(time.time()),
            "screen_n": 0,
            "images": {},
            "scale": PLAYERS_IMAGE_SCALE,
            "uniform_player_stills": False,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    )


# Level colors match smart_simust_player (RGB).
ACTIVATED_A1_BG = (175, 195, 213)
HP_TEST_BG = {
    1: (21, 101, 192),
    2: (46, 125, 50),
    3: (239, 108, 0),
    4: (106, 27, 154),
    5: (183, 28, 28),
}
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
ENTRY_NUMBER_SAMPLES = ("01", "03", "05", "07", "08", "10", "11", "12", "13", "15", "20", "30")
ACTIVATED_NUMBER_SAMPLES = (
    "10", "30", "50", "60", "40", "20", "08", "06", "01", "11", "7", "3",
    "22", "16", "12", "17", "21", "13",
)
ELITE_NUMBER_SAMPLES = (
    "01", "03", "05", "07", "08", "10", "11", "12", "13", "15",
    "16", "17", "18", "19", "20", "21", "22", "23", "25", "30", "40", "50",
)
ACTIVATED_LETTER_GROUPS = (
    ("L", "T", "I", "J"),
    ("O", "Q", "D", "C", "G"),
    ("E", "F", "B", "P", "R"),
    ("U", "V", "W"),
    ("M", "N", "H"),
    ("S", "Z"),
    ("X", "Y", "K"),
)
ELITE_SYMBOLS = ("$", "%", "#", "@", "&", "*", "!", "?", "+", "=")


def _rgb_to_bgr(rgb) -> tuple:
    r, g, b = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
    return (b, g, r)


def _render_styled_text(
    text: str,
    *,
    bg_rgb=None,
    fg_rgb=(255, 255, 255),
    tag: str = "digit",
    max_chars: int = 3,
) -> Optional[str]:
    """Digit/letter tile with level background + foreground (OpenCV BGR write)."""
    try:
        import cv2
        import numpy as np
    except Exception:
        return None
    limit = max(1, int(max_chars or 3))
    label = str(text or "").strip()[:limit]
    if not label:
        return None
    safe = "".join(ch if ch.isalnum() else "_" for ch in label)
    if bg_rgb is None:
        br = bgc = bb = -1
    else:
        br, bgc, bb = (int(bg_rgb[0]), int(bg_rgb[1]), int(bg_rgb[2]))
    fr, fg_c, fb = (int(fg_rgb[0]), int(fg_rgb[1]), int(fg_rgb[2]))
    path = os.path.join(
        cache_dir(),
        f"{tag}_bg_{br}_{bgc}_{bb}_fg_{fr}_{fg_c}_{fb}_{safe}.png",
    )
    if os.path.isfile(path):
        return path
    w = h = 512
    img = np.zeros((h, w, 3), dtype=np.uint8)
    if bg_rgb is None:
        img[:] = (0, 0, 0)
    else:
        img[:] = _rgb_to_bgr(bg_rgb)
    font = cv2.FONT_HERSHEY_SIMPLEX
    if len(label) == 1:
        scale, thickness = 8.0, 18
    elif len(label) == 2:
        scale, thickness = 5.5, 12
    elif len(label) == 3:
        scale, thickness = 4.6, 14
    else:
        scale, thickness = 3.2, 10
    (tw, th), _ = cv2.getTextSize(label, font, scale, thickness)
    # Shrink until the glyph fits inside the tile with a small margin.
    while tw > w - 24 and scale > 1.0:
        scale -= 0.2
        thickness = max(4, int(round(thickness * 0.9)))
        (tw, th), _ = cv2.getTextSize(label, font, scale, thickness)
    x = max(0, (w - tw) // 2)
    y = max(th, (h + th) // 2)
    cv2.putText(
        img, label, (x, y), font, scale, _rgb_to_bgr(fg_rgb), thickness, cv2.LINE_AA
    )
    try:
        if not cv2.imwrite(path, img):
            return None
    except Exception:
        return None
    return path


def _render_glyph(text: str, kind: str = "digit") -> Optional[str]:
    """Backward-compatible digit / letter tile."""
    if kind == "digit":
        return _render_styled_text(
            text, bg_rgb=HP_TEST_BG[1], fg_rgb=(255, 255, 255), tag="digit"
        )
    if kind == "letter":
        return _render_styled_text(
            text, bg_rgb=ACTIVATED_A1_BG, fg_rgb=(20, 40, 70), tag="letter"
        )
    return _render_styled_text(
        text, bg_rgb=(40, 40, 40), fg_rgb=(240, 220, 120), tag=kind or "glyph"
    )


def _item(path: str, kind: str, name: str = "", style: str = "") -> dict:
    return {
        "path": os.path.abspath(path) if path else "",
        "kind": kind or "",
        "name": name or (os.path.basename(path) if path else ""),
        "style": style or "",
    }


def _scan_player_assets() -> tuple:
    """Targets = pass/goal stills; distractors = opponent / defending / teammate."""
    roots = [
        os.path.join(_DIR, "static", "players"),
        _DIR,
        os.path.join(_player_dir(), "L00-Foundation-Challenge"),
    ]
    targets = []
    distractors = []
    seen = set()

    def _add(path: str, bucket: list, kind: str):
        ap = os.path.abspath(path)
        if ap in seen or not os.path.isfile(ap):
            return
        seen.add(ap)
        bucket.append(_item(ap, kind, os.path.basename(ap), "players"))

    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for fname in filenames:
                low = fname.lower()
                if not low.endswith((".png", ".jpg", ".jpeg")):
                    continue
                full = os.path.join(dirpath, fname)
                if low.startswith("pass") or "post" in low:
                    _add(full, targets, "pass")
                elif (
                    "opponent" in low
                    or "defending" in low
                    or "teammate" in low
                    or "offside" in low
                    or "cross" in low
                ):
                    _add(full, distractors, "distractor")
    return targets, distractors


def _build_number_packs() -> list:
    """One pack per level style: shared bg, target + distractor number tiles."""
    packs = []

    # Entry: red digit on black (same look as entry digitring_red_*).
    entry_targets = []
    entry_distractors = []
    for text in ENTRY_NUMBER_SAMPLES:
        path = _render_styled_text(
            text, bg_rgb=(0, 0, 0), fg_rgb=(255, 0, 0), tag="entry"
        )
        if not path:
            continue
        item = _item(path, "number", text, "entry")
        # Lowest-looking / early values as sample "pass" numbers.
        if text in ("01", "03", "05", "07", "08", "10"):
            entry_targets.append(item)
        else:
            entry_distractors.append(item)
    if entry_targets and entry_distractors:
        packs.append(
            {
                "style": "entry",
                "targets": entry_targets,
                "distractors": entry_distractors,
                "scale": NUMBER_TILE_SCALE,
            }
        )

    # Activated Numbers: white on Activated band color.
    act_targets = []
    act_distractors = []
    for text in ACTIVATED_NUMBER_SAMPLES:
        path = _render_styled_text(
            text, bg_rgb=ACTIVATED_A1_BG, fg_rgb=(255, 255, 255), tag="activated"
        )
        if not path:
            continue
        item = _item(path, "number", text, "activated")
        try:
            val = int(text)
        except ValueError:
            val = 99
        if val <= 12:
            act_targets.append(item)
        else:
            act_distractors.append(item)
    if act_targets and act_distractors:
        packs.append(
            {
                "style": "activated",
                "targets": act_targets,
                "distractors": act_distractors,
                "scale": NUMBER_TILE_SCALE,
            }
        )

    # High Performance: white on per-test HP_TEST_BG.
    for test_num, bg in HP_TEST_BG.items():
        hp_t = []
        hp_d = []
        for n in range(1, 101, 7):
            text = str(n)
            path = _render_styled_text(
                text, bg_rgb=bg, fg_rgb=(255, 255, 255), tag=f"hp{test_num}"
            )
            if not path:
                continue
            item = _item(path, "number", text, f"hp{test_num}")
            if n <= 30:
                hp_t.append(item)
            else:
                hp_d.append(item)
        if hp_t and hp_d:
            packs.append(
                {
                    "style": f"hp{test_num}",
                    "targets": hp_t,
                    "distractors": hp_d,
                    "scale": NUMBER_TILE_SCALE,
                }
            )

    # Elite / World Class: colored digit on Elite fills.
    for test_num, bg in ELITE_TEST_BG.items():
        fg = ELITE_DIGIT_ON_BG[test_num]
        el_t = []
        el_d = []
        for text in ELITE_NUMBER_SAMPLES:
            path = _render_styled_text(
                text, bg_rgb=bg, fg_rgb=fg, tag=f"elite{test_num}"
            )
            if not path:
                continue
            item = _item(path, "number", text, f"elite{test_num}")
            try:
                val = int(text)
            except ValueError:
                val = 99
            if val <= 12:
                el_t.append(item)
            else:
                el_d.append(item)
        if el_t and el_d:
            packs.append(
                {
                    "style": f"elite{test_num}",
                    "targets": el_t,
                    "distractors": el_d,
                    "scale": NUMBER_TILE_SCALE,
                }
            )
            # WC reuses Elite palette visually.
            packs.append(
                {
                    "style": f"wc{test_num}",
                    "targets": list(el_t),
                    "distractors": list(el_d),
                    "scale": NUMBER_TILE_SCALE,
                }
            )
    return packs


def _build_letter_packs() -> list:
    """Divergent: odd-one-out letter = target; majority / symbols = distractors."""
    packs = []
    for gi, group in enumerate(ACTIVATED_LETTER_GROUPS):
        if len(group) < 2:
            continue
        odd = group[0]
        majority = group[1:]
        targets = []
        distractors = []
        for ch in group:
            path = _render_styled_text(
                ch, bg_rgb=ACTIVATED_A1_BG, fg_rgb=(20, 40, 70), tag="div_act"
            )
            if not path:
                continue
            item = _item(path, "divergent", ch, "activated_div")
            if ch == odd:
                targets.append(item)
            else:
                distractors.append(item)
        # Extra distractors from other groups.
        for other in ACTIVATED_LETTER_GROUPS:
            if other is group:
                continue
            for ch in other[:2]:
                path = _render_styled_text(
                    ch, bg_rgb=ACTIVATED_A1_BG, fg_rgb=(20, 40, 70), tag="div_act"
                )
                if path:
                    distractors.append(_item(path, "divergent", ch, "activated_div"))
        if targets and distractors:
            packs.append(
                {
                    "style": f"activated_div{gi}",
                    "targets": targets,
                    "distractors": distractors,
                    "scale": NUMBER_TILE_SCALE,
                }
            )

    # Elite divergent: digit target vs symbol distractors (and reverse packs).
    for test_num, bg in list(ELITE_TEST_BG.items())[:3]:
        fg = ELITE_DIGIT_ON_BG[test_num]
        digit_items = []
        for text in ("01", "03", "05", "07", "08", "10"):
            path = _render_styled_text(
                text, bg_rgb=bg, fg_rgb=fg, tag=f"elite_div{test_num}"
            )
            if path:
                digit_items.append(_item(path, "number", text, f"elite_div{test_num}"))
        symbol_items = []
        for sym in ELITE_SYMBOLS:
            path = _render_styled_text(
                sym, bg_rgb=bg, fg_rgb=(255, 255, 255), tag=f"elite_sym{test_num}"
            )
            if path:
                symbol_items.append(
                    _item(path, "divergent", sym, f"elite_sym{test_num}")
                )
        if digit_items and symbol_items:
            packs.append(
                {
                    "style": f"elite_div{test_num}",
                    "targets": digit_items,
                    "distractors": symbol_items,
                    "scale": NUMBER_TILE_SCALE,
                }
            )
    return packs


def collect_content_pools() -> dict:
    """Targets (send ball) vs distractors (do not send) for Sampling cabinet fill."""
    player_t, player_d = _scan_player_assets()
    number_packs = _build_number_packs()
    letter_packs = _build_letter_packs()
    # Fallback glyph if a bucket is empty.
    blank = _render_glyph("?", "letter")
    blank_item = _item(blank, "divergent", "?", "fallback") if blank else None
    if not player_t and blank_item:
        player_t = [blank_item]
    if not player_d and blank_item:
        player_d = [blank_item]
    return {
        "players_targets": player_t,
        "players_distractors": player_d,
        "number_packs": number_packs,
        "letter_packs": letter_packs,
        "fallback": blank_item,
    }


def collect_content_pool() -> list:
    """Flat pool (compat): targets + distractors from all styles."""
    pools = collect_content_pools()
    found = []
    found.extend(pools.get("players_targets") or [])
    found.extend(pools.get("players_distractors") or [])
    for pack in pools.get("number_packs") or []:
        found.extend(pack.get("targets") or [])
        found.extend(pack.get("distractors") or [])
    for pack in pools.get("letter_packs") or []:
        found.extend(pack.get("targets") or [])
        found.extend(pack.get("distractors") or [])
    if not found and pools.get("fallback"):
        found.append(pools["fallback"])
    return found


def _pick_content(pool: list) -> dict:
    import random

    if not pool:
        return {"path": "", "kind": "", "name": "", "style": ""}
    return dict(random.choice(pool))


def _pick_theme_frame(pools: dict) -> tuple:
    """Pick theme + target/distractor lists + scale for one 2s swap."""
    import random

    themes = []
    if pools.get("players_targets") and pools.get("players_distractors"):
        themes.append("players")
    if pools.get("number_packs"):
        themes.append("numbers")
    if pools.get("letter_packs"):
        themes.append("letters")
    if not themes:
        fb = pools.get("fallback") or _item("", "divergent", "?", "fallback")
        return "fallback", [fb], [fb], NUMBER_TILE_SCALE, "fallback"

    theme = random.choice(themes)
    if theme == "players":
        return (
            "players",
            list(pools["players_targets"]),
            list(pools["players_distractors"]),
            PLAYERS_IMAGE_SCALE,
            "players",
        )
    if theme == "numbers":
        pack = random.choice(pools["number_packs"])
        return (
            "numbers",
            list(pack["targets"]),
            list(pack["distractors"]),
            float(pack.get("scale") or NUMBER_TILE_SCALE),
            pack.get("style") or "numbers",
        )
    pack = random.choice(pools["letter_packs"])
    return (
        "letters",
        list(pack["targets"]),
        list(pack["distractors"]),
        float(pack.get("scale") or NUMBER_TILE_SCALE),
        pack.get("style") or "letters",
    )


def _build_cabinet_images(screen_n: int, pools: dict) -> tuple:
    """Fill A1–B6: focus screen_n gets targets; all other screens get distractors."""
    import random

    n = max(1, min(6, int(screen_n)))
    theme, targets, distractors, scale, style = _pick_theme_frame(pools)
    images = {}
    kinds = {}
    target_a = _pick_content(targets)
    target_b = _pick_content(targets)
    for field, item in (("A", target_a), ("B", target_b)):
        sid = f"{field}{n}"
        if item.get("path"):
            images[sid] = item["path"]
            kinds[sid] = f"target:{item.get('kind') or theme}"
    for slot in range(1, 7):
        if slot == n:
            continue
        for field in ("A", "B"):
            item = _pick_content(distractors)
            sid = f"{field}{slot}"
            if item.get("path"):
                images[sid] = item["path"]
                kinds[sid] = f"distractor:{item.get('kind') or theme}"
    label = (
        f"focus S{n} {style} | "
        f"A{n}:{target_a.get('name') or '?'} B{n}:{target_b.get('name') or '?'} "
        f"| others=distractors"
    )
    return images, scale, kinds, label, style


def _publish_cabinet(
    screen_n: int,
    images: dict,
    scale: float,
    kinds: dict,
    label: str,
    seq: int,
    *,
    uniform_player_stills: bool = False,
) -> None:
    n = max(1, min(6, int(screen_n)))
    use_scale = float(scale if scale is not None else PLAYERS_IMAGE_SCALE)
    # Players use Entry/Activated/HP/Elite still box; digits fill the screen.
    uniform = bool(uniform_player_stills) or abs(use_scale - PLAYERS_IMAGE_SCALE) < 0.001
    _write_display(
        {
            "active": True,
            "seq": int(seq),
            "screen_n": n,
            "images": dict(images or {}),
            "scale": use_scale,
            "uniform_player_stills": bool(uniform and use_scale < 0.999),
            "kinds": dict(kinds or {}),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    )
    with _lock:
        _control["playlist_screen"] = n
        _control["playlist_content"] = label or ""
        _playlist_state["screen_n"] = n
        _playlist_state["content"] = _control["playlist_content"]
    _sync_control()


def _publish_screen_pair(screen_n: int, left: dict, right: dict, seq: int) -> None:
    """Compat helper: target on A{n}/B{n}; other screens stay empty."""
    n = max(1, min(6, int(screen_n)))
    images = {}
    kinds = {}
    if left.get("path"):
        images[f"A{n}"] = left["path"]
        kinds[f"A{n}"] = f"target:{left.get('kind') or ''}"
    if right.get("path"):
        images[f"B{n}"] = right["path"]
        kinds[f"B{n}"] = f"target:{right.get('kind') or ''}"
    label = (
        f"A{n}:{left.get('name') or left.get('kind')} | "
        f"B{n}:{right.get('name') or right.get('kind')}"
    )
    _publish_cabinet(
        n,
        images,
        PLAYERS_IMAGE_SCALE,
        kinds,
        label,
        seq,
        uniform_player_stills=True,
    )


def _start_tile_path() -> Optional[str]:
    """Full-screen STA cue (bright text, same tile size as digit displays)."""
    return _render_styled_text(
        START_CUE_TEXT,
        bg_rgb=(0, 0, 0),
        fg_rgb=(0, 255, 120),
        tag="cue_sta",
        max_chars=3,
    )


def _blank_tile_path() -> Optional[str]:
    """Solid black tile used to clear non-focus screens during the STA cue."""
    try:
        import cv2
        import numpy as np
    except Exception:
        return None
    path = os.path.join(cache_dir(), "cue_blank_black.png")
    if os.path.isfile(path):
        return path
    img = np.zeros((512, 512, 3), dtype=np.uint8)
    try:
        if not cv2.imwrite(path, img):
            return None
    except Exception:
        return None
    return path


def _publish_start_cue(screen_n: int, seq: int) -> None:
    """Show STA on focus A/B screens; black out the other 10 screens."""
    n = max(1, min(6, int(screen_n)))
    path = _start_tile_path()
    blank = _blank_tile_path()
    images = {}
    kinds = {}
    for slot in range(1, 7):
        for field in ("A", "B"):
            sid = f"{field}{slot}"
            if slot == n and path:
                images[sid] = path
                kinds[sid] = "cue:sta"
            elif blank:
                images[sid] = blank
                kinds[sid] = "cue:blank"
    _publish_cabinet(
        n,
        images,
        NUMBER_TILE_SCALE,
        kinds,
        f"STA S{n}",
        seq,
        uniform_player_stills=False,
    )


def _wait_until(stop_event: threading.Event, deadline: float) -> bool:
    """Wait until deadline. Returns True if stop was requested."""
    while True:
        if stop_event.is_set() or not is_active():
            return True
        remaining = deadline - time.time()
        if remaining <= 0:
            return False
        if stop_event.wait(min(0.2, remaining)):
            return True


def _playlist_loop(stop_event: threading.Event) -> None:
    """Focus 1→6: 1s START, then 30s with all 12 screens refreshed every 2s."""
    pools = collect_content_pools()
    seq = int(time.time())
    try:
        for screen_n in range(1, 7):
            if stop_event.is_set() or not is_active():
                break
            seq += 1
            # Publish first, then hold a full second so STA is actually visible.
            _publish_start_cue(screen_n, seq)
            cue_end = time.time() + float(START_FLASH_S)
            hold_end = cue_end + float(SCREEN_HOLD_S)
            if _wait_until(stop_event, cue_end):
                break
            swap_i = 0
            while True:
                if stop_event.is_set() or not is_active():
                    break
                now = time.time()
                if now >= hold_end:
                    break
                images, scale, kinds, label, style = _build_cabinet_images(
                    screen_n, pools
                )
                seq += 1
                _publish_cabinet(
                    screen_n,
                    images,
                    scale,
                    kinds,
                    label,
                    seq,
                    uniform_player_stills=(style == "players"),
                )
                swap_i += 1
                next_swap = cue_end + (swap_i * float(CONTENT_SWAP_S))
                if next_swap > hold_end:
                    next_swap = hold_end
                if _wait_until(stop_event, next_swap):
                    break
        if is_active():
            logger.info("sampling playlist finished screen 6 — auto-stop recording")
            stop_sample()
    finally:
        clear_display()
        with _lock:
            _control["playlist_screen"] = 0
            _control["playlist_content"] = ""
        _sync_control()


def _start_playlist() -> None:
    global _playlist_stop, _playlist_worker
    _stop_playlist()
    stop_event = threading.Event()
    _playlist_stop = stop_event
    worker = threading.Thread(
        target=_playlist_loop,
        args=(stop_event,),
        name="simust-sampling-playlist",
        daemon=True,
    )
    _playlist_worker = worker
    worker.start()


def _stop_playlist() -> None:
    global _playlist_stop, _playlist_worker
    event = _playlist_stop
    worker = _playlist_worker
    if event is not None:
        event.set()
    if worker is not None and worker.is_alive() and worker is not threading.current_thread():
        worker.join(timeout=3.0)
    _playlist_stop = None
    _playlist_worker = None
    clear_display()


def start_sample() -> dict:
    """Start recording + cabinet playlist (screens 1→6, both fields)."""
    global _writer, _writer_path
    if is_active():
        stop_sample()
    path = next_sample_path(".avi")
    writer, out_path = _open_writer(path)
    if writer is None:
        with _lock:
            _control["error"] = "could_not_open_video_writer"
            _control["active"] = False
        return _sync_control()
    with _writer_lock:
        _writer = writer
        _writer_path = out_path
    with _lock:
        _control.update(
            {
                "live": True,  # recording always shows live view
                "active": True,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "stopped_at": "",
                "video_path": out_path,
                "last_path": out_path,
                "frame_count": 0,
                "error": "",
                "playlist_screen": 1,
                "playlist_content": "starting",
            }
        )
    _sync_control()
    _start_cam_workers()
    _ensure_live_worker()
    _start_writer_thread()
    _start_playlist()
    return read_control()


def stop_sample() -> dict:
    """Stop recording / playlist and finalize the video; live view can stay On."""
    _stop_playlist()
    was_recording = is_active()
    if was_recording:
        with _lock:
            _control["active"] = False
        _stop_writer_thread()
        _close_writer(finalize=True)
    with _lock:
        _control["active"] = False
        _control["playlist_screen"] = 0
        _control["playlist_content"] = ""
        if not _control.get("stopped_at"):
            _control["stopped_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        keep_live = bool(_control.get("live"))
    if not keep_live:
        _stop_live_worker()
    else:
        _ensure_live_worker()
    return _sync_control()


def public_status() -> dict:
    with _lock:
        preview = dict(_preview) if _preview else {}
        ctrl = dict(_control)
        live = bool(ctrl.get("live"))
    # Only expose the live frame while the On switch is active.
    if not live:
        preview = {}
    return {
        "width": SIM_WIDTH,
        "height": SIM_HEIGHT,
        "save_width": SAVE_WIDTH,
        "save_height": SAVE_HEIGHT,
        "frame": preview,
        "live": live,
        "active": bool(ctrl.get("active")),
        "saved_count": int(ctrl.get("saved_count") or 0),
        "frame_count": int(ctrl.get("frame_count") or 0),
        "samples_dir": samples_dir(),
        "last_path": ctrl.get("last_path") or "",
        "video_path": ctrl.get("video_path") or ctrl.get("last_path") or "",
        "started_at": ctrl.get("started_at") or "",
        "stopped_at": ctrl.get("stopped_at") or "",
        "error": ctrl.get("error") or "",
        "fps": RECORD_FPS,
        "playlist_screen": int(ctrl.get("playlist_screen") or 0),
        "playlist_content": ctrl.get("playlist_content") or "",
        "screen_hold_s": SCREEN_HOLD_S,
        "content_swap_s": CONTENT_SWAP_S,
    }


# --- Compatibility stubs (old zone APIs no longer used by Settings) ---

def zone_contains(field: str, x: float, y: float, radius: float = 0.0) -> bool:
    del field, x, y, radius
    return False


def point_in_any_zone(x: float, y: float, radius: float = 0.0) -> Optional[str]:
    del x, y, radius
    return None


def save_raw_frame(frame) -> Optional[str]:
    """Legacy still-frame helper (kept for tests); writes a clean JPEG."""
    try:
        import cv2
    except Exception:
        return None
    clean = _to_save_size(frame)
    if clean is None:
        return None
    path = next_sample_path(".jpg")
    try:
        if not cv2.imwrite(path, clean):
            return None
    except Exception as exc:
        logger.warning("sampling still save failed: %s", exc)
        return None
    with _lock:
        _control["last_path"] = path
        _control["saved_count"] = int(_control.get("saved_count") or 0) + 1
    _sync_control()
    return path


def save_fields(fields_payload: dict) -> dict:
    del fields_payload
    raise ValueError("Sampling zones were removed — use Start / Stop only")


def reset_store() -> dict:
    stop_sample()
    return {"ok": True}


def consume_force_save_once() -> bool:
    return False
