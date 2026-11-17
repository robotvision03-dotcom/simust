"""Sampling zones on the 1280×360 stitch (Field A + Field B).

Settings draws a red loop per field on one stitched image. When Start Sample
is pressed, Realtime saves raw (no overlay) frames while a ball is inside
either red zone into <realtime_recordings>/data_samples/.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

_DIR = os.path.dirname(os.path.abspath(__file__))
CALIBRATION_FILE = os.environ.get(
    "SIMUST_SAMPLING_FILE",
    os.path.join(_DIR, "sampling_calibration.json"),
)
SIM_WIDTH = 1280
SIM_HEIGHT = 360
FIELD_HALF = SIM_WIDTH // 2
# Saved data_samples frames are always full stitch size (no labels).
SAVE_WIDTH = 3840
SAVE_HEIGHT = 1080

_lock = threading.Lock()
_cache: Optional[dict] = None
_cache_mtime: float = 0.0
_preview: Dict[str, Any] = {}
_zones: Dict[str, dict] = {}
_zones_key: Any = None
_seq_lock = threading.Lock()
_seq_stamp = ""
_seq_n = 0


def _player_dir() -> str:
    """Same folder Realtime uses for pause/cue control files."""
    env = os.environ.get("SIMUST_PLAYER_DIRECTORY")
    if env:
        return env
    # Match simust_realtime.SIMUST_PLAYER_DIRECTORY default.
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


def _empty_store() -> dict:
    return {
        "version": 1,
        "width": SIM_WIDTH,
        "height": SIM_HEIGHT,
        "fields": {},
        "updated_at": "",
    }


def _clean_strokes(strokes) -> List[dict]:
    import simust_hip_calibrate as hip

    return hip._clean_strokes(strokes)


def _close_polygon(points: Sequence[Sequence[float]]) -> List[List[float]]:
    import simust_hip_calibrate as hip

    return hip._close_polygon(points)


def _polygon_looks_valid(points) -> bool:
    pts = list(points or [])
    return len(pts) >= 4


def load_store(path: Optional[str] = None) -> dict:
    path = path or CALIBRATION_FILE
    global _cache, _cache_mtime
    with _lock:
        try:
            mtime = os.path.getmtime(path) if os.path.isfile(path) else 0.0
        except OSError:
            mtime = 0.0
        if _cache is not None and mtime == _cache_mtime:
            return deepcopy(_cache)
        store = _empty_store()
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    store.update(data)
                    store.setdefault("fields", {})
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Could not read sampling calibration: %s", exc)
        _cache = store
        _cache_mtime = mtime
        return deepcopy(store)


def save_store(store: dict, path: Optional[str] = None) -> dict:
    path = path or CALIBRATION_FILE
    global _cache, _cache_mtime, _zones, _zones_key
    out = dict(store or _empty_store())
    out["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    out["width"] = SIM_WIDTH
    out["height"] = SIM_HEIGHT
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=2)
    os.replace(tmp, path)
    with _lock:
        _cache = deepcopy(out)
        try:
            _cache_mtime = os.path.getmtime(path)
        except OSError:
            _cache_mtime = time.time()
        _zones = {}
        _zones_key = None
    return deepcopy(out)


def live_zones() -> Dict[str, dict]:
    """Build filled masks for Field A / B sampling loops."""
    global _zones, _zones_key
    import simust_hip_calibrate as hip

    store = load_store()
    key = (
        store.get("updated_at"),
        tuple(
            (
                fid,
                len((rec or {}).get("points") or []),
                len((rec or {}).get("strokes") or []),
            )
            for fid, rec in sorted((store.get("fields") or {}).items())
        ),
    )
    if _zones and _zones_key == key:
        return _zones
    zones: Dict[str, dict] = {}
    for fid in ("A", "B"):
        rec = (store.get("fields") or {}).get(fid) or {}
        strokes = _clean_strokes(rec.get("strokes") or [])
        pts = []
        mask = None
        if strokes:
            pts, mask = hip.raster_zone(strokes)
        if not _polygon_looks_valid(pts):
            pts = _close_polygon(rec.get("points") or [])
            if _polygon_looks_valid(pts) and mask is None:
                mask = hip._mask_from_polygon(pts)
        zones[fid] = {
            "points": pts if _polygon_looks_valid(pts) else [],
            "mask": mask,
            "painted": bool(_polygon_looks_valid(pts) and mask is not None),
            "strokes": strokes,
        }
    _zones = zones
    _zones_key = key
    return zones


def zone_contains(field: str, x: float, y: float, radius: float = 0.0) -> bool:
    fid = str(field or "A").strip().upper()[:1]
    zone = live_zones().get(fid)
    if not zone or not zone.get("painted"):
        return False
    mask = zone.get("mask")
    if mask is None:
        return False
    try:
        xf = float(x)
        yf = float(y)
        reach = max(0.0, float(radius or 0.0))
    except (TypeError, ValueError):
        return False
    height, width = mask.shape[:2]
    xi = int(round(xf))
    yi = int(round(yf))
    if 0 <= xi < width and 0 <= yi < height and mask[yi, xi]:
        return True
    if reach <= 0.0:
        return False
    x0 = max(0, int(xf - reach))
    y0 = max(0, int(yf - reach))
    x1 = min(width, int(xf + reach) + 1)
    y1 = min(height, int(yf + reach) + 1)
    if x1 <= x0 or y1 <= y0:
        return False
    return bool(mask[y0:y1, x0:x1].any())


def point_in_any_zone(x: float, y: float, radius: float = 0.0) -> Optional[str]:
    """Return 'A' or 'B' if the point hits that sampling zone, else None."""
    for fid in ("A", "B"):
        if zone_contains(fid, x, y, radius):
            return fid
    return None


def read_control() -> dict:
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


def write_control(active: bool, **extra) -> dict:
    path = _control_path()
    cur = read_control()
    cur["active"] = bool(active)
    cur["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    for key, value in extra.items():
        cur[key] = value
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(cur, handle, indent=2)
    os.replace(tmp, path)
    return cur


def is_active() -> bool:
    return bool(read_control().get("active"))


def _frame_from_preview(preview: Optional[dict] = None):
    """Decode a stitched JPEG preview to a raw BGR image (no drawings)."""
    try:
        import base64
        import cv2
        import numpy as np
    except Exception:
        return None
    if not isinstance(preview, dict) or not preview.get("data_url"):
        preview = dict(_preview) if _preview else {}
    data_url = str((preview or {}).get("data_url") or "")
    if not data_url.startswith("data:image/jpeg;base64,"):
        try:
            preview = capture_stitched_preview(force_live=True)
            data_url = str((preview or {}).get("data_url") or "")
        except Exception as exc:
            logger.warning("sampling test capture failed: %s", exc)
            return None
    if not data_url.startswith("data:image/jpeg;base64,"):
        return None
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1])
        arr = np.frombuffer(raw, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception as exc:
        logger.warning("sampling preview decode failed: %s", exc)
        return None
    return frame


def save_test_frame(preview: Optional[dict] = None) -> Optional[str]:
    """Save one clean 3840×1080 stitch for checking Start Sample (no red/labels)."""
    errors: List[str] = []
    frame = None
    try:
        frame = capture_full_stitch_frame()
    except Exception as exc:
        errors.append(f"full:{exc}")
        frame = None
    if frame is None:
        try:
            frame = _frame_from_preview(preview)
        except Exception as exc:
            errors.append(f"preview:{exc}")
            frame = None
    if frame is None:
        # Last resort: solid frame so Start Sample still produces a check file.
        try:
            import numpy as np

            frame = np.zeros((SAVE_HEIGHT, SAVE_WIDTH, 3), dtype=np.uint8)
            errors.append("fallback_black")
            logger.warning("sampling test frame used black fallback (%s)", "; ".join(errors))
        except Exception:
            logger.warning("sampling test frame failed (%s)", "; ".join(errors) or "unknown")
            return None
    path = save_raw_frame(frame)
    if path:
        logger.info("sampling test frame saved: %s", path)
    return path


def start_sample() -> dict:
    """Arm sampling and always save one clean test frame immediately."""
    prior = read_control()
    write_control(
        True,
        started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        # Realtime also dumps the next live raw frame once (ball not required).
        force_save_once=True,
        saved_count=int(prior.get("saved_count") or 0),
        test_path="",
        last_path=prior.get("last_path") or "",
    )
    test_path = save_test_frame()
    ctrl = read_control()
    return write_control(
        True,
        started_at=ctrl.get("started_at") or time.strftime("%Y-%m-%dT%H:%M:%S"),
        force_save_once=True,
        saved_count=int(ctrl.get("saved_count") or 0),
        last_path=test_path or ctrl.get("last_path") or "",
        test_path=test_path or "",
        test_error="" if test_path else "could_not_capture_test_frame",
    )


def stop_sample() -> dict:
    return write_control(
        False,
        stopped_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        force_save_once=False,
    )


def consume_force_save_once() -> bool:
    """True once when Realtime should dump a raw frame regardless of ball."""
    ctrl = read_control()
    if not ctrl.get("force_save_once"):
        return False
    write_control(
        bool(ctrl.get("active")),
        force_save_once=False,
        saved_count=int(ctrl.get("saved_count") or 0),
        last_path=ctrl.get("last_path") or "",
        test_path=ctrl.get("test_path") or "",
        started_at=ctrl.get("started_at") or "",
    )
    return True


def next_sample_path(ext: str = ".jpg") -> str:
    """date_hour_minute_second_NNNN.jpg under data_samples."""
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
    """Force exactly 3840×1080 for every data_samples JPEG."""
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


def capture_full_stitch_frame():
    """Grab camera-1 + camera-8 at full stitch size (3840×1080), no labels."""
    try:
        import cv2
        import simust_homography
        import simust_goal_calibrate as gc
    except Exception as exc:
        logger.warning("full stitch capture unavailable: %s", exc)
        return None
    cams = getattr(simust_homography, "LAB_CAMERAS", {}) or {}
    left_url = cams.get(getattr(simust_homography, "LEFT_CAMERA", "camera-1")) or ""
    right_url = cams.get(getattr(simust_homography, "RIGHT_CAMERA", "camera-8")) or ""
    if not left_url or not right_url:
        return None

    def _grab(url: str):
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            cap.release()
            return None
        frame = None
        try:
            for _ in range(20):
                ok, grabbed = cap.read()
                if ok and grabbed is not None:
                    frame = grabbed
        finally:
            cap.release()
        return frame

    try:
        left = gc._resize_cam_like_realtime(_grab(left_url), SAVE_HEIGHT)
        right = gc._resize_cam_like_realtime(_grab(right_url), SAVE_HEIGHT)
        stitched = gc._stitch_halves(left, right)
    except Exception as exc:
        logger.warning("full stitch grab failed: %s", exc)
        return None
    return _to_save_size(stitched)


def save_raw_frame(frame) -> Optional[str]:
    """Write a raw BGR frame at 3840×1080 with no overlays / labels / red zones.

    Callers must pass a clean stitch copy — never the annotated display frame.
    """
    if frame is None:
        return None
    try:
        import cv2
    except Exception:
        return None
    clean = _to_save_size(frame)
    if clean is None:
        return None
    path = next_sample_path(".jpg")
    try:
        ok = cv2.imwrite(path, clean)
    except Exception as exc:
        logger.warning("sampling save failed: %s", exc)
        return None
    if not ok:
        return None
    try:
        ctrl = read_control()
        write_control(
            bool(ctrl.get("active")),
            saved_count=int(ctrl.get("saved_count") or 0) + 1,
            last_path=path,
            started_at=ctrl.get("started_at") or "",
            force_save_once=bool(ctrl.get("force_save_once")),
            test_path=ctrl.get("test_path") or "",
        )
    except Exception:
        pass
    return path


def public_status() -> dict:
    store = load_store()
    zones = live_zones()
    fields = {}
    for fid in ("A", "B"):
        zone = zones.get(fid) or {}
        saved = (store.get("fields") or {}).get(fid) or {}
        fields[fid] = {
            "points": zone.get("points") or [],
            "strokes": _clean_strokes(saved.get("strokes") or zone.get("strokes") or []),
            "field": fid,
            "calibrated": bool(zone.get("painted")),
            "point_count": len(zone.get("points") or []),
        }
    preview = dict(_preview) if _preview else {}
    if not preview.get("data_url"):
        try:
            import simust_goal_calibrate as gc

            frame = (gc.public_status().get("frame") or {}) if hasattr(gc, "public_status") else {}
            if frame.get("data_url"):
                preview = dict(frame)
        except Exception:
            pass
    ctrl = read_control()
    return {
        "width": SIM_WIDTH,
        "height": SIM_HEIGHT,
        "fields": fields,
        "updated_at": store.get("updated_at") or "",
        "frame": preview,
        "calibrated_count": sum(1 for f in fields.values() if f.get("calibrated")),
        "active": bool(ctrl.get("active")),
        "saved_count": int(ctrl.get("saved_count") or 0),
        "samples_dir": samples_dir(),
        "last_path": ctrl.get("last_path") or "",
        "test_path": ctrl.get("test_path") or "",
        "save_width": SAVE_WIDTH,
        "save_height": SAVE_HEIGHT,
    }


def capture_stitched_preview(force_live: bool = True) -> dict:
    """Stitch without Field A/B text — sampling UI + data_samples stay unlabeled."""
    global _preview
    import simust_goal_calibrate as gc

    preview = gc.capture_stitched_preview(force_live=force_live, annotate=False)
    _preview = dict(preview)
    return preview


def save_fields(fields_payload: dict) -> dict:
    import simust_hip_calibrate as hip

    store = load_store()
    merged = dict(store.get("fields") or {})
    saved_any = False
    for fid, rec in (fields_payload or {}).items():
        key = str(fid or "").strip().upper()
        if key not in ("A", "B"):
            continue
        if bool((rec or {}).get("clear")):
            merged[key] = {"strokes": [], "points": [], "cleared": True}
            saved_any = True
            continue
        strokes = hip.bake_eraser_strokes((rec or {}).get("strokes") or [])
        pts = hip.polygon_from_strokes(strokes) if strokes else _close_polygon(
            (rec or {}).get("points") or []
        )
        # If the loop did not close cleanly, still keep stroke points so Start
        # Sample / zone hit-tests have something to work with.
        if not _polygon_looks_valid(pts) and strokes:
            flat: List[List[float]] = []
            for stroke in strokes:
                for p in stroke.get("pts") or []:
                    flat.append([float(p[0]), float(p[1])])
            pts = _close_polygon(flat)
        if not _polygon_looks_valid(pts):
            raise ValueError(
                f"Field {key}: draw a closed red loop (more points) before Save Zone"
            )
        # Keep points inside the field half when possible.
        clamped = []
        for p in pts:
            x = float(p[0])
            y = float(p[1])
            if key == "A":
                x = max(0.0, min(float(FIELD_HALF), x))
            else:
                x = max(float(FIELD_HALF), min(float(SIM_WIDTH), x))
            clamped.append([x, max(0.0, min(float(SIM_HEIGHT), y))])
        if clamped and clamped[0] != clamped[-1]:
            clamped.append(list(clamped[0]))
        entry: Dict[str, Any] = {"points": clamped, "cleared": False}
        if strokes:
            entry["strokes"] = strokes
        merged[key] = entry
        saved_any = True
    if not saved_any:
        raise ValueError("Nothing to save — draw a red sampling loop first")
    store["fields"] = merged
    return save_store(store)


def reset_store() -> dict:
    stop_sample()
    return save_store(_empty_store())
