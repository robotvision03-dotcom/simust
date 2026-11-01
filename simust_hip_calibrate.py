"""HIP person-zone calibration — 17-point player polygons on the 1280×360 stitch.

Field A / Field B closed polygons filter where pose HIP tracking is allowed.
Operator drags the red vertices in Settings; save overrides POLYGON_POINTS_*.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from copy import deepcopy
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

CALIBRATION_FILE = os.environ.get(
    "SIMUST_HIP_ZONE_FILE", "hip_zone_calibration.json"
)
SIM_WIDTH = 1280
SIM_HEIGHT = 360
POINT_COUNT = 17  # closed polygon (last point mirrors first)

_lock = threading.Lock()
_cache: Optional[dict] = None
_cache_mtime: float = 0.0
_preview: Dict[str, Any] = {}


def _empty_store() -> dict:
    return {
        "version": 1,
        "width": SIM_WIDTH,
        "height": SIM_HEIGHT,
        "fields": {},
        "updated_at": "",
    }


def _close_polygon(points: Sequence[Sequence[float]]) -> List[List[float]]:
    """Normalize to exactly 17 points with last == first."""
    cleaned: List[List[float]] = []
    for pt in points or []:
        try:
            cleaned.append([float(pt[0]), float(pt[1])])
        except Exception:
            continue
    if not cleaned:
        return []
    # Drop trailing duplicates of the first point, then close.
    while len(cleaned) > 1 and cleaned[-1] == cleaned[0]:
        cleaned.pop()
    if len(cleaned) > POINT_COUNT - 1:
        cleaned = cleaned[: POINT_COUNT - 1]
    while len(cleaned) < POINT_COUNT - 1:
        cleaned.append(list(cleaned[-1]))
    cleaned.append(list(cleaned[0]))
    return cleaned


def default_fields_from_polygons(
    poly_a: Sequence[Sequence[float]],
    poly_b: Sequence[Sequence[float]],
) -> Dict[str, dict]:
    return {
        "A": {
            "points": _close_polygon(poly_a),
            "field": "A",
            "calibrated": False,
        },
        "B": {
            "points": _close_polygon(poly_b),
            "field": "B",
            "calibrated": False,
        },
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
                    store.setdefault("fields", {})
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Could not read hip-zone calibration: %s", exc)
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
    fields: Dict[str, dict] = {}
    for fid, rec in (payload.get("fields") or {}).items():
        key = str(fid or "").strip().upper()
        if key not in ("A", "B"):
            continue
        pts = _close_polygon((rec or {}).get("points") or [])
        if len(pts) != POINT_COUNT:
            continue
        fields[key] = {"points": pts}
    payload["fields"] = fields
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


def _builtin_polygons():
    """Current software HIP zones (simust_fields defaults, before overrides)."""
    try:
        from simust_fields import (
            _BUILTIN_POLYGON_POINTS_A,
            _BUILTIN_POLYGON_POINTS_B,
        )

        return list(_BUILTIN_POLYGON_POINTS_A), list(_BUILTIN_POLYGON_POINTS_B)
    except Exception:
        try:
            from simust_fields import POLYGON_POINTS_A, POLYGON_POINTS_B

            return list(POLYGON_POINTS_A), list(POLYGON_POINTS_B)
        except Exception:
            return [], []


def _polygon_looks_valid(pts: Sequence[Sequence[float]]) -> bool:
    """Reject empty / degenerate saves (e.g. unit-test junk). Keep software defaults."""
    closed = _close_polygon(pts)
    if len(closed) != POINT_COUNT:
        return False
    xs = [p[0] for p in closed[:-1]]
    ys = [p[1] for p in closed[:-1]]
    if max(xs) - min(xs) < 40 or max(ys) - min(ys) < 40:
        return False
    return True


def apply_overrides_to_polygons(poly_a: list, poly_b: list) -> None:
    """Mutate Field A/B polygon lists in place from the saved calibration."""
    store = load_store()
    fields = store.get("fields") or {}
    for fid, target in (("A", poly_a), ("B", poly_b)):
        saved = fields.get(fid) or {}
        pts = _close_polygon(saved.get("points") or [])
        if not _polygon_looks_valid(pts) or target is None:
            continue
        target[:] = [(float(p[0]), float(p[1])) for p in pts]


def public_status(
    poly_a: Optional[Sequence[Sequence[float]]] = None,
    poly_b: Optional[Sequence[Sequence[float]]] = None,
) -> dict:
    store = load_store()
    # Always start from the software HIP zone; saved file only applies small tweaks.
    if not poly_a or not poly_b:
        built_a, built_b = _builtin_polygons()
        poly_a = poly_a or built_a
        poly_b = poly_b or built_b
    defaults = default_fields_from_polygons(poly_a or [], poly_b or [])
    fields = {}
    for fid in ("A", "B"):
        saved = (store.get("fields") or {}).get(fid)
        base = defaults.get(fid) or {"points": []}
        saved_pts = _close_polygon((saved or {}).get("points") or []) if saved else []
        if saved and _polygon_looks_valid(saved_pts):
            points = saved_pts
            calibrated = True
        else:
            points = _close_polygon(base.get("points") or [])
            calibrated = False
        fields[fid] = {
            "points": points,
            "field": fid,
            "calibrated": calibrated,
            "point_count": len(points),
            "source": "adjusted" if calibrated else "software",
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
    return {
        "width": SIM_WIDTH,
        "height": SIM_HEIGHT,
        "fields": fields,
        "updated_at": store.get("updated_at") or "",
        "frame": preview,
        "calibrated_count": sum(1 for f in fields.values() if f.get("calibrated")),
        "point_count": POINT_COUNT,
    }


def capture_stitched_preview(force_live: bool = True) -> dict:
    """Reuse goal-area stitch (same Realtime Play geometry)."""
    global _preview
    import simust_goal_calibrate as gc

    preview = gc.capture_stitched_preview(force_live=force_live)
    _preview = dict(preview)
    return preview


def save_fields(
    fields_payload: dict,
    poly_a: Optional[list] = None,
    poly_b: Optional[list] = None,
) -> dict:
    store = load_store()
    merged = dict(store.get("fields") or {})
    for fid, rec in (fields_payload or {}).items():
        key = str(fid or "").strip().upper()
        if key not in ("A", "B"):
            continue
        pts = _close_polygon((rec or {}).get("points") or [])
        if len(pts) != POINT_COUNT:
            continue
        merged[key] = {"points": pts}
    store["fields"] = merged
    store["width"] = SIM_WIDTH
    store["height"] = SIM_HEIGHT
    saved = save_store(store)
    if poly_a is not None and poly_b is not None:
        apply_overrides_to_polygons(poly_a, poly_b)
    return saved


def reset_store() -> dict:
    return save_store(_empty_store())
