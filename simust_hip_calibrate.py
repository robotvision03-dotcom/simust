"""HIP person-zone calibration on the 1280×360 stitch.

Field A / Field B zones are drawn with the same pencil as the goal area.
Save closes the pencil loop and stores that outline as the HIP polygon.
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

_DIR = os.path.dirname(os.path.abspath(__file__))
CALIBRATION_FILE = os.environ.get(
    "SIMUST_HIP_ZONE_FILE",
    os.path.join(_DIR, "hip_zone_calibration.json"),
)
SIM_WIDTH = 1280
SIM_HEIGHT = 360
MAX_ZONE_POINTS = 2400

_lock = threading.Lock()
_cache: Optional[dict] = None
_cache_mtime: float = 0.0
_preview: Dict[str, Any] = {}
_zone_key: Any = None
_zone_cache: Dict[str, dict] = {}


def _empty_store() -> dict:
    return {
        "version": 1,
        "width": SIM_WIDTH,
        "height": SIM_HEIGHT,
        "fields": {},
        "updated_at": "",
    }


def _clean_strokes(strokes) -> List[dict]:
    out: List[dict] = []
    if not isinstance(strokes, list):
        return out
    for stroke in strokes[:80]:
        if not isinstance(stroke, dict):
            continue
        pts: List[List[float]] = []
        for p in (stroke.get("pts") or [])[:2500]:
            if not isinstance(p, (list, tuple)) or len(p) < 2:
                continue
            try:
                pts.append([
                    max(0.0, min(float(SIM_WIDTH), float(p[0]))),
                    max(0.0, min(float(SIM_HEIGHT), float(p[1]))),
                ])
            except (TypeError, ValueError):
                continue
        if not pts:
            continue
        try:
            brush = float(stroke.get("brush") or 16)
        except (TypeError, ValueError):
            brush = 16.0
        out.append({
            "erase": bool(stroke.get("erase")),
            "brush": max(1.0, min(48.0, brush)),
            "pts": pts,
        })
    return out


def _close_polygon(points: Sequence[Sequence[float]]) -> List[List[float]]:
    """Drop a repeated end point, then connect the loop (last == first)."""
    cleaned: List[List[float]] = []
    for pt in points or []:
        try:
            cleaned.append([
                max(0.0, min(float(SIM_WIDTH), float(pt[0]))),
                max(0.0, min(float(SIM_HEIGHT), float(pt[1]))),
            ])
        except Exception:
            continue
    if len(cleaned) < 3:
        return []
    while len(cleaned) > 1 and cleaned[-1] == cleaned[0]:
        cleaned.pop()
    if len(cleaned) < 3:
        return []
    cleaned.append(list(cleaned[0]))
    return cleaned


def _brush_px(stroke: dict) -> int:
    try:
        brush = int(round(float(stroke.get("brush") or 1)))
    except (TypeError, ValueError):
        brush = 1
    return max(1, min(48, brush))


def _draw_stroke(mask, stroke: dict, close_ends: bool) -> None:
    import cv2

    pts = stroke.get("pts") or []
    if not pts:
        return
    color = 0 if stroke.get("erase") else 255
    brush = _brush_px(stroke)
    seq = list(pts)
    if close_ends and not stroke.get("erase") and len(seq) >= 2 and seq[0] != seq[-1]:
        seq = seq + [seq[0]]
    p0 = (int(round(seq[0][0])), int(round(seq[0][1])))
    cv2.circle(mask, p0, max(1, brush // 2), color, -1, lineType=cv2.LINE_8)
    for p in seq[1:]:
        p1 = (int(round(p[0])), int(round(p[1])))
        cv2.line(mask, p0, p1, color, brush, lineType=cv2.LINE_8)
        p0 = p1


def _mask_from_polygon(points: Sequence[Sequence[float]]):
    """Filled interior of a saved loop, in the 1280×360 frame."""
    try:
        import cv2
        import numpy as np
    except Exception:
        return None
    closed = _close_polygon(points)
    if len(closed) < 4:
        return None
    mask = np.zeros((SIM_HEIGHT, SIM_WIDTH), dtype=np.uint8)
    arr = np.array([[int(round(p[0])), int(round(p[1]))] for p in closed], dtype=np.int32)
    cv2.fillPoly(mask, [arr], 255)
    return mask


def _loop_points(pencil: Sequence[dict]) -> List[List[float]]:
    """Pencil points, in the order they were drawn. Short lifts stay on one loop."""
    path: List[List[float]] = []
    for stroke in pencil:
        pts = [list(p) for p in (stroke.get("pts") or [])]
        if len(pts) < 2:
            continue
        if path:
            a = path[-1]
            b = pts[0]
            gap = ((float(a[0]) - float(b[0])) ** 2 + (float(a[1]) - float(b[1])) ** 2) ** 0.5
            if gap > max(48.0, float(_brush_px(stroke)) * 3.0):
                if len(pts) > len(path):
                    path = pts
                continue
        path.extend(pts)
    return _close_polygon(path)


def _polygon_from_mask(mask) -> List[List[float]]:
    """Outer contour of the painted mask after pencil + erase."""
    try:
        import cv2
        import numpy as np
    except Exception:
        return []
    if mask is None:
        return []
    binary = (mask > 0).astype("uint8") * 255
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < 80:
        return []
    peri = float(cv2.arcLength(largest, True))
    epsilon = max(1.0, peri * 0.004)
    approx = cv2.approxPolyDP(largest, epsilon, True)
    pts = [[float(p[0][0]), float(p[0][1])] for p in approx]
    return _close_polygon(pts)


def bake_eraser_strokes(strokes) -> List[dict]:
    """Remove pencil points under eraser strokes so old lines do not linger."""
    cleaned = _clean_strokes(strokes)
    erasers = [s for s in cleaned if s.get("erase")]
    pencils = [s for s in cleaned if not s.get("erase")]
    if not erasers:
        return pencils

    def _hit(px: float, py: float, eraser: dict) -> bool:
        pts = eraser.get("pts") or []
        if not pts:
            return False
        radius = max(2.0, float(_brush_px(eraser)) * 0.65)
        prev = None
        for pt in pts:
            x, y = float(pt[0]), float(pt[1])
            if ((px - x) ** 2 + (py - y) ** 2) ** 0.5 <= radius:
                return True
            if prev is not None:
                ax, ay = prev
                dx, dy = x - ax, y - ay
                len2 = dx * dx + dy * dy
                if len2 <= 1e-6:
                    dist = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
                else:
                    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
                    qx, qy = ax + t * dx, ay + t * dy
                    dist = ((px - qx) ** 2 + (py - qy) ** 2) ** 0.5
                if dist <= radius:
                    return True
            prev = (x, y)
        return False

    out: List[dict] = []
    for stroke in pencils:
        brush = float(stroke.get("brush") or 16)
        seg: List[List[float]] = []

        def flush() -> None:
            nonlocal seg
            if len(seg) >= 2:
                out.append({"erase": False, "brush": brush, "pts": list(seg)})
            seg = []

        for pt in stroke.get("pts") or []:
            if any(_hit(float(pt[0]), float(pt[1]), eraser) for eraser in erasers):
                flush()
            else:
                seg.append([float(pt[0]), float(pt[1])])
        flush()
    return out


def raster_zone(strokes):
    """The pencil path itself, plus the area inside that loop.

    Returns ``(polygon, mask)``. Without erase strokes the polygon keeps the
    drawn vertices. After erase, the polygon is rebuilt from the final mask so
    removed segments do not survive as a ghost outline.
    """
    cleaned = _clean_strokes(strokes)
    has_erase = any(bool(s.get("erase")) for s in cleaned)
    if has_erase:
        cleaned = bake_eraser_strokes(cleaned)
    pencil = [s for s in cleaned if not s.get("erase") and len(s.get("pts") or []) >= 2]
    if not pencil:
        return [], None
    polygon = _loop_points(pencil)
    try:
        import cv2
        import numpy as np
    except Exception:
        return polygon, None
    mask = np.zeros((SIM_HEIGHT, SIM_WIDTH), dtype=np.uint8)
    if len(polygon) >= 4:
        arr = np.array(
            [[int(round(p[0])), int(round(p[1]))] for p in polygon],
            dtype=np.int32,
        )
        cv2.fillPoly(mask, [arr], 255)
    for stroke in pencil:
        _draw_stroke(mask, stroke, close_ends=False)
    if has_erase:
        rebuilt = _polygon_from_mask(mask)
        if rebuilt:
            polygon = rebuilt
    return polygon, mask


def polygon_from_strokes(strokes) -> List[List[float]]:
    """Close the pencil and use that loop as the HIP outline."""
    points, _mask = raster_zone(strokes)
    return points


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
                logger.warning("Could not read hip-zone calibration: %s", exc)
        _cache = store
        _cache_mtime = mtime
        return deepcopy(store)


def save_store(store: dict, path: Optional[str] = None) -> dict:
    path = path or CALIBRATION_FILE
    global _cache, _cache_mtime
    payload = dict(store or _empty_store())
    payload["version"] = 1
    payload["width"] = int(payload.get("width") or SIM_WIDTH)
    payload["height"] = int(payload.get("height") or SIM_HEIGHT)
    payload["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    fields: Dict[str, dict] = {}
    for fid, rec in (payload.get("fields") or {}).items():
        key = str(fid or "").strip().upper()
        if key not in ("A", "B") or not isinstance(rec, dict):
            continue
        strokes = _clean_strokes(rec.get("strokes") or [])
        if rec.get("cleared") and not strokes:
            fields[key] = {"strokes": [], "points": [], "cleared": True}
            continue
        pts = polygon_from_strokes(strokes) if strokes else _close_polygon(rec.get("points") or [])
        if not _polygon_looks_valid(pts):
            continue
        entry: Dict[str, Any] = {"points": pts}
        if strokes:
            entry["strokes"] = strokes
        fields[key] = entry
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
        global _zone_key, _zone_cache
        _zone_key = None
        _zone_cache = {}
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
    """Reject empty / degenerate saves. A painted loop only needs a closed outline."""
    closed = _close_polygon(pts)
    if len(closed) < 4:
        return False
    xs = [p[0] for p in closed[:-1]]
    ys = [p[1] for p in closed[:-1]]
    if max(xs) - min(xs) < 40 or max(ys) - min(ys) < 40:
        return False
    return True


def live_zones() -> Dict[str, dict]:
    """Painted HIP zones, rebuilt only when the calibration file changes."""
    global _zone_key, _zone_cache
    store = load_store()
    key = (CALIBRATION_FILE, _cache_mtime)
    if _zone_cache and _zone_key == key:
        return _zone_cache
    zones: Dict[str, dict] = {}
    for fid in ("A", "B"):
        saved = (store.get("fields") or {}).get(fid) or {}
        strokes = _clean_strokes(saved.get("strokes") or [])
        points = _close_polygon(saved.get("points") or [])
        mask = None
        # The pencil pixels are the zone. Their outer border is the HIP line.
        if strokes:
            points, mask = raster_zone(strokes)
        if not _polygon_looks_valid(points):
            continue
        if mask is None and strokes:
            mask = _mask_from_polygon(points)
        zones[fid] = {
            "points": points,
            "mask": mask,
            "strokes": strokes,
            "painted": bool(strokes),
        }
    _zone_key = key
    _zone_cache = zones
    return zones


def zone_strokes(field: str) -> List[dict]:
    """Saved pencil strokes for one field. Empty when that field has no paint."""
    fid = str(field or "A").strip().upper()[:1]
    zone = live_zones().get(fid) or {}
    if not zone.get("painted"):
        return []
    return list(zone.get("strokes") or [])


def zone_hidden(field: str) -> bool:
    """True after New HIP loop removes the saved line and before the next save."""
    fid = str(field or "A").strip().upper()[:1]
    store = load_store()
    saved = (store.get("fields") or {}).get(fid) or {}
    if not saved.get("cleared"):
        return False
    return not _clean_strokes(saved.get("strokes") or [])


def draw_strokes(frame, strokes, sx: float, sy: float, color) -> None:
    """Draw the saved pencil at the same width it had in Settings."""
    import cv2

    scale = float(sy or 1.0)
    for stroke in strokes or []:
        if not isinstance(stroke, dict) or stroke.get("erase"):
            continue
        pts = stroke.get("pts") or []
        if not pts:
            continue
        brush = max(1, int(round(_brush_px(stroke) * scale)))

        def _xy(pt):
            return (
                int(round(float(pt[0]) * float(sx))),
                int(round(float(pt[1]) * scale)),
            )

        p0 = _xy(pts[0])
        cv2.circle(frame, p0, max(0, brush // 2), color, -1, lineType=cv2.LINE_8)
        for pt in pts[1:]:
            p1 = _xy(pt)
            cv2.line(frame, p0, p1, color, brush, lineType=cv2.LINE_8)
            p0 = p1


def zone_contains(field: str, x: float, y: float, radius: float = 0.0):
    """True/False for a painted HIP loop. None when that field has no pencil."""
    fid = str(field or "A").strip().upper()[:1]
    zone = live_zones().get(fid)
    if not zone or not zone.get("painted"):
        return None
    mask = zone.get("mask")
    if mask is None:
        return None
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


def apply_overrides_to_polygons(poly_a: list, poly_b: list) -> None:
    """Mutate Field A/B polygon lists in place from the saved calibration."""
    zones = live_zones()
    for fid, target in (("A", poly_a), ("B", poly_b)):
        zone = zones.get(fid)
        if not zone or target is None:
            continue
        pts = zone.get("points") or []
        if not _polygon_looks_valid(pts):
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
        if saved and saved.get("cleared") and not _clean_strokes(saved.get("strokes") or []):
            fields[fid] = {
                "points": [],
                "strokes": [],
                "field": fid,
                "calibrated": False,
                "point_count": 0,
                "source": "cleared",
            }
            continue
        zone = live_zones().get(fid) if saved else None
        saved_pts = (zone or {}).get("points") or []
        if saved and _polygon_looks_valid(saved_pts):
            points = saved_pts
            calibrated = True
        else:
            points = _close_polygon(base.get("points") or [])
            calibrated = False
        fields[fid] = {
            "points": points,
            "strokes": _clean_strokes((saved or {}).get("strokes") or []) if saved else [],
            "field": fid,
            "calibrated": calibrated,
            "point_count": len(points),
            "source": "paint" if calibrated and (saved or {}).get("strokes") else (
                "adjusted" if calibrated else "software"
            ),
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
        if bool((rec or {}).get("clear")):
            merged[key] = {"strokes": [], "points": [], "cleared": True}
            continue
        strokes = bake_eraser_strokes((rec or {}).get("strokes") or [])
        pts = polygon_from_strokes(strokes) if strokes else _close_polygon((rec or {}).get("points") or [])
        if not _polygon_looks_valid(pts):
            continue
        entry: Dict[str, Any] = {"points": pts}
        if strokes:
            entry["strokes"] = strokes
        merged[key] = entry
    store["fields"] = merged
    store["width"] = SIM_WIDTH
    store["height"] = SIM_HEIGHT
    saved = save_store(store)
    if poly_a is not None and poly_b is not None:
        apply_overrides_to_polygons(poly_a, poly_b)
    return saved


def reset_store() -> dict:
    return save_store(_empty_store())
