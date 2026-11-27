"""Pencil-painted goal areas. One mask per screen, built when the file changes.

Strokes are stored in logical 1280×360 pixels. The mask is the painted
boundary with its interior filled. A ball counts when its bounding box
touches that area, so the center may sit outside while an edge still hits.
"""

from __future__ import annotations

import json
import math
import os
import threading
from typing import Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
PAINT_FILE = os.environ.get(
    "SIMUST_GOAL_PAINT_FILE",
    os.path.join(_DIR, "goal_area_paint.json"),
)
SIM_W = 1280
SIM_H = 360

# Live scoring may pass A6 or cabinet 4 for the same Field A mouth.
_PAINT_SCREEN_ALIASES = {
    "A1": ("A1", "12"),
    "A2": ("A2", "13"),
    "A3": ("A3", "14"),
    "A4": ("A4", "2"),
    "A5": ("A5", "3"),
    "A6": ("A6", "4"),
    "A7": ("A7",),
    "B1": ("B1", "5"),
    "B2": ("B2", "6"),
    "B3": ("B3", "7"),
    "B4": ("B4", "9"),
    "B5": ("B5", "10"),
    "B6": ("B6", "11"),
    "B7": ("B7",),
    "12": ("A1", "12"),
    "13": ("A2", "13"),
    "14": ("A3", "14"),
    "2": ("A4", "2"),
    "3": ("A5", "3"),
    "4": ("A6", "4"),
    "5": ("B1", "5"),
    "6": ("B2", "6"),
    "7": ("B3", "7"),
    "9": ("B4", "9"),
    "10": ("B5", "10"),
    "11": ("B6", "11"),
}

# Field B mouths often have no pencil yet. Reuse the matching Field A paint
# shifted by the A→B goal offset so Elite / dual-field finishes still use
# Goal Area (same Settings paint Entry already uses on A).
_PAINT_MIRROR_B_FROM_A = {
    "B1": ("A1", 640.0, -20.5),
    "B2": ("A2", 640.0, -18.5),
    "B3": ("A3", 637.0, -17.5),
    "B4": ("A4", 639.5, -11.5),
    "B5": ("A5", 639.0, -16.0),
    "B6": ("A6", 639.5, -18.5),
    "B7": ("A7", 640.0, -2.0),
    "5": ("A1", 640.0, -20.5),
    "6": ("A2", 640.0, -18.5),
    "7": ("A3", 637.0, -17.5),
    "9": ("A4", 639.5, -11.5),
    "10": ("A5", 639.0, -16.0),
    "11": ("A6", 639.5, -18.5),
    "8": ("A7", 640.0, -2.0),
}

_lock = threading.Lock()
_cache = None
_cache_mtime = -1.0
_masks = None
_masks_mtime = -1.0
_mirror_cache = {}
_mirror_cache_mtime = -1.0


def _empty() -> dict:
    return {"version": 1, "screens": {}}


def _load_unlocked() -> dict:
    global _cache, _cache_mtime
    path = PAINT_FILE
    try:
        mtime = os.path.getmtime(path) if os.path.isfile(path) else 0.0
    except OSError:
        mtime = 0.0
    if _cache is not None and mtime == _cache_mtime:
        return _cache
    data = _empty()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            if isinstance(raw, dict) and isinstance(raw.get("screens"), dict):
                data["screens"] = raw["screens"]
                data["version"] = int(raw.get("version") or 1)
        except Exception:
            data = _empty()
    _cache = data
    _cache_mtime = mtime
    return data


def load_store() -> dict:
    with _lock:
        return _load_unlocked()


def _clean_strokes(strokes) -> list:
    out = []
    if not isinstance(strokes, list):
        return out
    for stroke in strokes[:80]:
        if not isinstance(stroke, dict):
            continue
        pts = []
        for p in (stroke.get("pts") or [])[:2500]:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                try:
                    pts.append([
                        max(0.0, min(float(SIM_W), float(p[0]))),
                        max(0.0, min(float(SIM_H), float(p[1]))),
                    ])
                except (TypeError, ValueError):
                    continue
        if len(pts) < 1:
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


def bake_eraser_strokes(strokes) -> list:
    """Remove pencil points under eraser strokes so old white lines do not linger."""
    cleaned = _clean_strokes(strokes)
    erasers = [s for s in cleaned if s.get("erase")]
    pencils = [s for s in cleaned if not s.get("erase")]
    if not erasers:
        return pencils

    def _hit(px: float, py: float, eraser: dict) -> bool:
        pts = eraser.get("pts") or []
        if not pts:
            return False
        radius = max(2.0, float(eraser.get("brush") or 16) * 0.65)
        prev = None
        for pt in pts:
            x, y = float(pt[0]), float(pt[1])
            if math.hypot(px - x, py - y) <= radius:
                return True
            if prev is not None:
                ax, ay = prev
                dx, dy = x - ax, y - ay
                len2 = dx * dx + dy * dy
                if len2 <= 1e-6:
                    dist = math.hypot(px - ax, py - ay)
                else:
                    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
                    qx, qy = ax + t * dx, ay + t * dy
                    dist = math.hypot(px - qx, py - qy)
                if dist <= radius:
                    return True
            prev = (x, y)
        return False

    out = []
    for stroke in pencils:
        brush = float(stroke.get("brush") or 16)
        seg = []

        def flush() -> None:
            nonlocal seg
            if len(seg) >= 2:
                out.append({"erase": False, "brush": brush, "pts": list(seg)})
            elif len(seg) == 1:
                out.append({"erase": False, "brush": brush, "pts": list(seg)})
            seg = []

        for pt in stroke.get("pts") or []:
            if any(_hit(float(pt[0]), float(pt[1]), eraser) for eraser in erasers):
                flush()
            else:
                seg.append([float(pt[0]), float(pt[1])])
        flush()
    return out


def save_screen(screen: str, strokes) -> dict:
    global _cache, _cache_mtime, _masks, _masks_mtime
    sid = str(screen or "").strip().upper()
    if not sid:
        raise ValueError("screen is required")
    with _lock:
        store = _load_unlocked()
        screens = dict(store.get("screens") or {})
        # Bake eraser into pencil so a later reload cannot bring old white lines back.
        cleaned = bake_eraser_strokes(strokes)
        if cleaned:
            screens[sid] = {"strokes": cleaned}
        else:
            screens.pop(sid, None)
        payload = {"version": 1, "screens": screens}
        parent = os.path.dirname(os.path.abspath(PAINT_FILE))
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = PAINT_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
        os.replace(tmp, PAINT_FILE)
        _cache = payload
        try:
            _cache_mtime = os.path.getmtime(PAINT_FILE)
        except OSError:
            _cache_mtime = 0.0
        _masks = None
        _masks_mtime = -1.0
    return public_paints()


def clear_screen(screen: str = "") -> dict:
    sid = str(screen or "").strip().upper()
    if not sid:
        return save_all({})
    store = load_store()
    screens = dict(store.get("screens") or {})
    screens.pop(sid, None)
    return save_all(screens)


def save_all(screens: dict) -> dict:
    global _cache, _cache_mtime, _masks, _masks_mtime
    cleaned = {}
    for key, entry in (screens or {}).items():
        sid = str(key or "").strip().upper()
        strokes = _clean_strokes((entry or {}).get("strokes") if isinstance(entry, dict) else entry)
        if sid and strokes:
            cleaned[sid] = {"strokes": strokes}
    payload = {"version": 1, "screens": cleaned}
    with _lock:
        tmp = PAINT_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
        os.replace(tmp, PAINT_FILE)
        _cache = payload
        try:
            _cache_mtime = os.path.getmtime(PAINT_FILE)
        except OSError:
            _cache_mtime = 0.0
        _masks = None
        _masks_mtime = -1.0
    return public_paints()


def public_paints() -> dict:
    screens = {}
    for sid, entry in (load_store().get("screens") or {}).items():
        strokes = (entry or {}).get("strokes") if isinstance(entry, dict) else None
        if not strokes:
            continue
        screens[str(sid).upper()] = {
            "strokes": strokes,
            "stroke_count": len(strokes),
        }
    return {"screens": screens, "painted_count": len(screens)}


def _rasterize(screens: dict):
    try:
        import cv2
        import numpy as np
    except Exception:
        return {}
    masks = {}
    for sid, entry in (screens or {}).items():
        strokes = (entry or {}).get("strokes") if isinstance(entry, dict) else None
        if not strokes:
            continue
        mask = np.zeros((SIM_H, SIM_W), dtype=np.uint8)
        for stroke in strokes:
            pts = stroke.get("pts") or []
            if not pts:
                continue
            color = 0 if stroke.get("erase") else 255
            brush = max(1, int(round(float(stroke.get("brush") or 16))))
            p0 = (int(round(pts[0][0])), int(round(pts[0][1])))
            cv2.circle(mask, p0, max(1, brush // 2), color, -1, lineType=cv2.LINE_8)
            for p in pts[1:]:
                p1 = (int(round(p[0])), int(round(p[1])))
                cv2.line(mask, p0, p1, color, brush, lineType=cv2.LINE_8)
                p0 = p1
        if int(mask.max()) == 0:
            continue
        # Interior of each painted outline is part of the goal. Done once.
        contours, _hier = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            cv2.drawContours(mask, contours, -1, 255, thickness=-1)
        ys, xs = np.where(mask > 0)
        if len(xs) == 0:
            continue
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        masks[str(sid).upper()] = {
            "mask": mask,
            "bbox": (x0, y0, x1, y1),
        }
    return masks


def _masks_unlocked() -> dict:
    global _masks, _masks_mtime
    store = _load_unlocked()
    try:
        mtime = os.path.getmtime(PAINT_FILE) if os.path.isfile(PAINT_FILE) else 0.0
    except OSError:
        mtime = 0.0
    if _masks is not None and mtime == _masks_mtime:
        return _masks
    _masks = _rasterize(store.get("screens") or {})
    _masks_mtime = mtime
    return _masks


def _split_paint_suffix(screen: str):
    """Split A2R / A1T → (body, L|R|T|B|''). Keep Field B bodies intact."""
    sid = str(screen or "").strip().upper()
    if not sid:
        return "", ""
    if len(sid) >= 3 and sid[0] in ("A", "B") and sid[-1] in ("L", "R", "T", "B"):
        body = sid[:-1]
        if body[1:].isdigit() and 1 <= int(body[1:]) <= 6:
            return body, sid[-1]
    if sid[-1:] in ("L", "R") and sid[:-1].isdigit():
        return sid[:-1], sid[-1]
    return sid, ""


def _paint_screen_keys(screen: str):
    sid = str(screen or "").strip().upper()
    if not sid:
        return ()
    body, suffix = _split_paint_suffix(sid)
    aliases = _PAINT_SCREEN_ALIASES.get(body) or (body,)
    keys = []
    for alias in aliases:
        name = str(alias) + suffix
        if name and name not in keys:
            keys.append(name)
    if sid not in keys:
        keys.insert(0, sid)
    return tuple(keys)


def _shift_paint_view(view: dict, dx: float, dy: float) -> Optional[dict]:
    """Copy a paint mask by (dx, dy) in SIM pixels (A paint → B mouth)."""
    try:
        import numpy as np
    except Exception:
        return None
    mask = view.get("mask")
    bbox = view.get("bbox")
    if mask is None or not bbox or len(bbox) < 4:
        return None
    height, width = mask.shape[:2]
    ox = int(round(float(dx)))
    oy = int(round(float(dy)))
    x0, y0, x1, y1 = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
    nx0 = max(0, min(width, x0 + ox))
    ny0 = max(0, min(height, y0 + oy))
    nx1 = max(0, min(width, x1 + ox))
    ny1 = max(0, min(height, y1 + oy))
    if nx1 <= nx0 or ny1 <= ny0:
        return None
    out = np.zeros_like(mask)
    # Source crop that lands inside the destination bbox.
    sx0 = nx0 - ox
    sy0 = ny0 - oy
    sx1 = nx1 - ox
    sy1 = ny1 - oy
    if sx1 <= sx0 or sy1 <= sy0:
        return None
    out[ny0:ny1, nx0:nx1] = mask[sy0:sy1, sx0:sx1]
    if not out.any():
        return None
    return {"mask": out, "bbox": (nx0, ny0, nx1, ny1)}


def _mirrored_paint_view(screen: str) -> Optional[dict]:
    """Field B mouth with no pencil: reuse matching Field A paint, shifted.

    Also mirrors Top/Bottom paints (B1T←A1T, B1B←A1B) when Field B has none.
    """
    global _mirror_cache, _mirror_cache_mtime
    body, suffix = _split_paint_suffix(screen)
    spec = _PAINT_MIRROR_B_FROM_A.get(body)
    if not spec:
        return None
    src_sid, dx, dy = spec
    cache_key = f"{body}{suffix}"
    with _lock:
        try:
            mtime = os.path.getmtime(PAINT_FILE) if os.path.isfile(PAINT_FILE) else 0.0
        except OSError:
            mtime = 0.0
        if _mirror_cache_mtime != mtime:
            _mirror_cache = {}
            _mirror_cache_mtime = mtime
        cached = _mirror_cache.get(cache_key)
        if cached is not None:
            return cached or None
        masks = _masks_unlocked()
        src = None
        for key in _paint_screen_keys(f"{src_sid}{suffix}"):
            src = masks.get(key)
            if src:
                break
        if not src:
            _mirror_cache[cache_key] = False
            return None
        shifted = _shift_paint_view(src, dx, dy)
        _mirror_cache[cache_key] = shifted or False
        return shifted


def _parent_paint_view(body: str) -> Optional[dict]:
    """Center-mouth paint for A2 / B3 / … (no Top/Bottom split)."""
    keys = _paint_screen_keys(body)
    if not keys:
        return None
    with _lock:
        masks = _masks_unlocked()
        for key in keys:
            view = masks.get(key)
            if view:
                return view
    return _mirrored_paint_view(body)


def _tb_half_from_parent(screen: str) -> Optional[dict]:
    """When A2T/A2B has no pencil, use the top/bottom half of the A2 Goal Area paint.

    Elders Focus lights A2T / A2B; operators often paint only the center mouth
    (A2). Splitting that mask keeps every screen on Settings Goal Area regions,
    not only A1T / A1B.
    """
    try:
        import numpy as np
    except Exception:
        return None
    body, suffix = _split_paint_suffix(screen)
    if suffix not in ("T", "B") or not body:
        return None
    parent = _parent_paint_view(body)
    if not parent or parent.get("mask") is None:
        return None
    mask = parent["mask"]
    bbox = parent.get("bbox")
    if not bbox or len(bbox) < 4:
        return None
    x0, y0, x1, y1 = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
    if x1 <= x0 or y1 <= y0:
        return None
    mid = y0 + max(1, (y1 - y0) // 2)
    out = np.zeros_like(mask)
    if suffix == "T":
        out[y0:mid, x0:x1] = mask[y0:mid, x0:x1]
        ny0, ny1 = y0, mid
    else:
        out[mid:y1, x0:x1] = mask[mid:y1, x0:x1]
        ny0, ny1 = mid, y1
    if not out.any():
        return None
    return {"mask": out, "bbox": (x0, ny0, x1, ny1)}


def paint_view(screen: str) -> Optional[dict]:
    """Cached mask for one screen, or None when that screen has no paint.

    Field B mouths without their own pencil reuse the matching Field A paint
    (shifted), so Elite / dual-field goals still use Goal Area.

    Top/Bottom ids (A2T / A2B …) prefer their own pencil; if missing, the
    matching half of the parent center Goal Area paint is used.
    """
    keys = _paint_screen_keys(screen)
    if not keys:
        return None
    with _lock:
        masks = _masks_unlocked()
        for key in keys:
            view = masks.get(key)
            if view:
                return view
    mirrored = _mirrored_paint_view(screen)
    if mirrored:
        return mirrored
    return _tb_half_from_parent(screen)


def contains(screen: str, x: float, y: float, radius=0.0, radius_x=None, radius_y=None):
    """True/False when this screen is painted. None when it has no paint.

    ``radius_x`` / ``radius_y`` are the ball bounding-box half-width and
    half-height. The center counts, and so does any edge of that box that
    reaches the painted area.
    """
    view = paint_view(screen)
    if not view:
        # Distinguish "no paint stored" from "stored but empty".
        screens = (load_store().get("screens") or {})
        keys = list(_paint_screen_keys(screen))
        body, suffix = _split_paint_suffix(screen)
        mirrored = _PAINT_MIRROR_B_FROM_A.get(body)
        if mirrored:
            keys.extend(_paint_screen_keys(f"{mirrored[0]}{suffix}"))
        # T/B may score from parent center paint when A2T/A2B was never drawn.
        if suffix in ("T", "B") and body:
            keys.extend(_paint_screen_keys(body))
            if mirrored:
                keys.extend(_paint_screen_keys(mirrored[0]))
        if not any(key in screens for key in keys):
            return None
        return False
    try:
        xf = float(x)
        yf = float(y)
        rx = float(radius if radius_x is None else radius_x)
        ry = float(radius if radius_y is None else radius_y)
    except (TypeError, ValueError):
        return False
    if rx < 0.0:
        rx = 0.0
    if ry < 0.0:
        ry = 0.0
    mask = view["mask"]
    height, width = mask.shape[:2]
    xi = int(round(xf))
    yi = int(round(yf))
    if 0 <= xi < width and 0 <= yi < height and mask[yi, xi]:
        return True
    if rx <= 0.0 and ry <= 0.0:
        return False
    x0 = max(0, int(math.floor(xf - rx)))
    y0 = max(0, int(math.floor(yf - ry)))
    x1 = min(width, int(math.ceil(xf + rx)) + 1)
    y1 = min(height, int(math.ceil(yf + ry)) + 1)
    if x1 <= x0 or y1 <= y0:
        return False
    px0, py0, px1, py1 = view["bbox"]
    if x1 <= px0 or x0 >= px1 or y1 <= py0 or y0 >= py1:
        return False
    return bool(mask[y0:y1, x0:x1].any())
