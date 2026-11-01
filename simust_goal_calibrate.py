"""Goal-area line calibration on the stitched 1280×360 processing frame.

Operator clicks p0/p1 for A1–A6 and B1–B6. Saved lines override GOAL_LINES
cabinets used for green cylinder scoring/display in simust_realtime.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
except Exception:  # pragma: no cover
    cv2 = None
    np = None

CALIBRATION_FILE = os.environ.get(
    "SIMUST_GOAL_LINES_FILE", "goal_lines_calibration.json"
)
FRAME_DIR = os.environ.get("SIMUST_GOAL_FRAME_DIR", "goal_calibration_frames")
FRAME_NAME = "stitched_preview.jpg"
SIM_WIDTH = 1280
SIM_HEIGHT = 360

# Same mapping as simust_realtime._NEW_SCREEN_TO_CABINET
SCREEN_TO_CABINET = {
    "A1": "12",
    "A2": "13",
    "A3": "14",
    "A4": "2",
    "A5": "3",
    "A6": "4",
    "B1": "5",
    "B2": "6",
    "B3": "7",
    "B4": "9",
    "B5": "10",
    "B6": "11",
}
FIELD_A_ORDER = ["A1", "A2", "A3", "A4", "A5", "A6"]
FIELD_B_ORDER = ["B1", "B2", "B3", "B4", "B5", "B6"]
ALL_SCREENS = FIELD_A_ORDER + FIELD_B_ORDER

_lock = threading.Lock()
_cache: Optional[dict] = None
_cache_mtime: float = 0.0
_preview: Dict[str, Any] = {}


def _empty_store() -> dict:
    return {
        "version": 1,
        "width": SIM_WIDTH,
        "height": SIM_HEIGHT,
        "screens": {},
        "updated_at": "",
    }


def load_store(path: str = CALIBRATION_FILE) -> dict:
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
                    store.setdefault("screens", {})
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Could not read goal-lines calibration: %s", exc)
        _cache = store
        _cache_mtime = mtime
        return deepcopy(store)


def save_store(store: dict, path: str = CALIBRATION_FILE) -> dict:
    global _cache, _cache_mtime
    payload = dict(store or _empty_store())
    payload["version"] = 1
    payload["width"] = int(payload.get("width") or SIM_WIDTH)
    payload["height"] = int(payload.get("height") or SIM_HEIGHT)
    payload["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    screens = {}
    for sid, line in (payload.get("screens") or {}).items():
        key = str(sid or "").strip().upper()
        if key not in SCREEN_TO_CABINET:
            continue
        try:
            p0 = line.get("p0")
            p1 = line.get("p1")
            screens[key] = {
                "p0": [float(p0[0]), float(p0[1])],
                "p1": [float(p1[0]), float(p1[1])],
            }
        except Exception:
            continue
    payload["screens"] = screens
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, path)
    with _lock:
        _cache = deepcopy(payload)
        try:
            _cache_mtime = os.path.getmtime(path)
        except OSError:
            _cache_mtime = time.time()
    return deepcopy(payload)


def _line_points(line) -> Optional[Tuple[List[float], List[float]]]:
    try:
        p0 = line.get("p0")
        p1 = line.get("p1")
        a = [float(p0[0]), float(p0[1])]
        b = [float(p1[0]), float(p1[1])]
        return a, b
    except Exception:
        return None


def _line_looks_valid(line) -> bool:
    """Reject junk / test stubs (e.g. 10px segments). Real posts are longer."""
    pts = _line_points(line or {})
    if not pts:
        return False
    p0, p1 = pts
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    return (dx * dx + dy * dy) ** 0.5 >= 18.0


def default_screens_from_goal_lines(goal_lines: dict) -> Dict[str, dict]:
    """Build A1–A6 / B1–B6 lines from current GOAL_LINES cabinets."""
    out = {}
    for sid, cab in SCREEN_TO_CABINET.items():
        line = (goal_lines or {}).get(cab) or {}
        pts = _line_points(line)
        if not pts:
            continue
        p0, p1 = pts
        out[sid] = {"p0": p0, "p1": p1}
    return out


def apply_overrides_to(goal_lines: dict) -> dict:
    """Merge saved calibration into a GOAL_LINES dict (mutates and returns it)."""
    store = load_store()
    dirty = False
    screens = dict(store.get("screens") or {})
    for sid, line in list(screens.items()):
        cab = SCREEN_TO_CABINET.get(str(sid).upper())
        if not cab:
            continue
        if not _line_looks_valid(line):
            screens.pop(sid, None)
            dirty = True
            continue
        try:
            pts = _line_points(line)
            if not pts:
                continue
            p0, p1 = pts
            goal_lines[cab] = {"p0": (p0[0], p0[1]), "p1": (p1[0], p1[1])}
        except Exception:
            continue
    if dirty:
        store["screens"] = screens
        try:
            save_store(store)
        except Exception:
            pass
    return goal_lines


def public_status(goal_lines: Optional[dict] = None) -> dict:
    store = load_store()
    defaults = default_screens_from_goal_lines(goal_lines or {})
    screens = {}
    cleaned = dict(store.get("screens") or {})
    dirty = False
    for sid in ALL_SCREENS:
        saved = cleaned.get(sid)
        if saved and not _line_looks_valid(saved):
            cleaned.pop(sid, None)
            dirty = True
            saved = None
        base = defaults.get(sid) or {"p0": [0, 0], "p1": [0, 0]}
        use = saved if saved else base
        pts = _line_points(use) or ([0.0, 0.0], [0.0, 0.0])
        screens[sid] = {
            "p0": list(pts[0]),
            "p1": list(pts[1]),
            "cabinet": SCREEN_TO_CABINET[sid],
            "calibrated": bool(saved),
            "field": "A" if sid.startswith("A") else "B",
            "source": "adjusted" if saved else "software",
        }
    if dirty:
        store["screens"] = cleaned
        try:
            save_store(store)
        except Exception:
            pass
    preview = dict(_preview) if _preview else {}
    if not preview.get("data_url"):
        path = os.path.join(FRAME_DIR, FRAME_NAME)
        if os.path.isfile(path) and cv2 is not None:
            try:
                img = cv2.imread(path)
                if img is not None:
                    preview = _encode_preview(img)
            except Exception:
                pass
    return {
        "width": int(store.get("width") or SIM_WIDTH),
        "height": int(store.get("height") or SIM_HEIGHT),
        "screens": screens,
        "order": {"A": list(FIELD_A_ORDER), "B": list(FIELD_B_ORDER)},
        "updated_at": store.get("updated_at") or "",
        "frame": preview,
        "calibrated_count": sum(1 for s in screens.values() if s.get("calibrated")),
    }


def _encode_preview(img) -> dict:
    h, w = img.shape[:2]
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        raise RuntimeError("Could not encode stitched preview")
    jpeg = buf.tobytes()
    return {
        "data_url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii"),
        "width": int(w),
        "height": int(h),
        "captured_at": time.time(),
    }


def _resize_cam_like_realtime(frame, target_h: int = SIM_HEIGHT):
    """Same resize as simust_realtime.capture_stream — height 360, aspect kept."""
    if frame is None:
        return None
    h, w = frame.shape[:2]
    if h == target_h:
        return frame
    target_w = max(1, int(w * target_h / float(h)))
    return cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)


def _stitch_halves(left, right):
    """Same stitch as simust_realtime.stitch_frames (hstack after equal height)."""
    if left is None or right is None:
        return None
    h_l, w_l = left.shape[:2]
    h_r, w_r = right.shape[:2]
    if h_l != h_r:
        target_h = min(h_l, h_r)
        if h_l != target_h:
            left = cv2.resize(left, (max(1, int(w_l * target_h / h_l)), target_h))
        if h_r != target_h:
            right = cv2.resize(right, (max(1, int(w_r * target_h / h_r)), target_h))
    return np.hstack([left, right])


def _to_sim_frame(stitched):
    """Map live stitch → exact SIM 1280×360 (same space as GOAL_LINES / cylinder).

    Live draws cylinders with sx = frame_w/1280. Resizing the stitch to 1280×360
    is the inverse of that scale, so goal posts and GOAL_LINES line up 1:1.
    """
    if stitched is None:
        return None
    h, w = stitched.shape[:2]
    if w == SIM_WIDTH and h == SIM_HEIGHT:
        return stitched, "exact"
    out = cv2.resize(stitched, (SIM_WIDTH, SIM_HEIGHT), interpolation=cv2.INTER_AREA)
    return out, "sim_scale"


def capture_stitched_preview(
    force_live: bool = True, goal_lines: Optional[dict] = None
) -> dict:
    """Grab the same stitched 1280×360 frame Realtime uses for green cylinders.

    Path: camera-1 + camera-8 → height 360 (aspect kept) → hstack → scale into
    SIM 1280×360 (GOAL_LINES / cylinder coordinate space).
    """
    global _preview
    if cv2 is None or np is None:
        raise RuntimeError("OpenCV is required on the lab PC for goal calibration")
    try:
        import simust_homography
    except Exception as exc:
        raise RuntimeError(f"Homography camera helpers unavailable: {exc}") from exc

    cams = getattr(simust_homography, "LAB_CAMERAS", {}) or {}
    left_name = getattr(simust_homography, "LEFT_CAMERA", "camera-1")
    right_name = getattr(simust_homography, "RIGHT_CAMERA", "camera-8")
    left_url = cams.get(left_name) or ""
    right_url = cams.get(right_name) or ""
    if not left_url or not right_url:
        raise RuntimeError("Lab cameras are not configured")

    def _grab_raw(url: str):
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            cap.release()
            raise RuntimeError("Could not open camera")
        frame = None
        try:
            for _ in range(20):
                ok, grabbed = cap.read()
                if ok and grabbed is not None:
                    frame = grabbed
        finally:
            cap.release()
        if frame is None:
            raise RuntimeError("No frame from camera")
        return frame

    left = _resize_cam_like_realtime(_grab_raw(left_url), SIM_HEIGHT)
    right = _resize_cam_like_realtime(_grab_raw(right_url), SIM_HEIGHT)
    stitched = _stitch_halves(left, right)
    if stitched is None:
        raise RuntimeError("Could not stitch camera frames")

    raw_h, raw_w = stitched.shape[:2]
    out, fit_mode = _to_sim_frame(stitched)
    # Light field split only — cylinders are drawn live in the Settings overlay
    # from the same GOAL_LINES the Realtime cylinder uses.
    try:
        mid = SIM_WIDTH // 2
        cv2.line(out, (mid, 0), (mid, SIM_HEIGHT - 1), (0, 200, 255), 1)
        cv2.putText(
            out, "Field A", (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 2
        )
        cv2.putText(
            out,
            "Field B",
            (mid + 12, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 200, 255),
            2,
        )
        cv2.putText(
            out,
            f"{SIM_WIDTH}x{SIM_HEIGHT} stitched (same as cylinder)",
            (12, SIM_HEIGHT - 12),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (200, 200, 200),
            1,
        )
    except Exception:
        pass

    os.makedirs(FRAME_DIR, exist_ok=True)
    path = os.path.join(FRAME_DIR, FRAME_NAME)
    cv2.imwrite(path, out)
    preview = _encode_preview(out)
    preview["path"] = path
    preview["force_live"] = bool(force_live)
    preview["raw_width"] = int(raw_w)
    preview["raw_height"] = int(raw_h)
    preview["fit_mode"] = fit_mode
    preview["sim_width"] = SIM_WIDTH
    preview["sim_height"] = SIM_HEIGHT
    preview["width"] = SIM_WIDTH
    preview["height"] = SIM_HEIGHT
    _preview = preview
    return preview


def save_screens(screens_payload: dict, goal_lines: Optional[dict] = None) -> dict:
    """Persist operator-edited A1–A6 / B1–B6 lines and apply to GOAL_LINES."""
    store = load_store()
    merged = default_screens_from_goal_lines(goal_lines or {})
    merged.update(store.get("screens") or {})
    for sid, line in (screens_payload or {}).items():
        key = str(sid or "").strip().upper()
        if key not in SCREEN_TO_CABINET:
            continue
        try:
            merged[key] = {
                "p0": [float(line["p0"][0]), float(line["p0"][1])],
                "p1": [float(line["p1"][0]), float(line["p1"][1])],
            }
        except Exception:
            continue
    store["screens"] = merged
    store["width"] = SIM_WIDTH
    store["height"] = SIM_HEIGHT
    saved = save_store(store)
    if goal_lines is not None:
        apply_overrides_to(goal_lines)
    return saved


def reset_store(goal_lines: Optional[dict] = None) -> dict:
    saved = save_store(_empty_store())
    # Caller may restore builtins; we only clear overrides.
    return saved
