"""Editable finish-cylinder surface mesh (≈200 control points).

Keeps the live finish-cylinder radius/height as the starting size. Operators
sculpt with PyVista/VTK; deformed vertex coordinates are stored per screen and
used for Realtime hit-testing / overlay drawing while connectivity stays fixed.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from copy import deepcopy
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None  # type: ignore

MESH_FILE = os.environ.get(
    "SIMUST_CYLINDER_MESH_FILE", "goal_cylinder_meshes.json"
)

# Lateral surface only: 20 × 10 = 200 control points (exact).
N_THETA = 20
N_HEIGHT = 10
N_CONTROL = N_THETA * N_HEIGHT  # 200

_lock = threading.Lock()
_cache: Optional[dict] = None
_cache_mtime: float = 0.0


def _empty_store() -> dict:
    return {"version": 1, "screens": {}}


def _load_unlocked() -> dict:
    global _cache, _cache_mtime
    path = MESH_FILE
    try:
        mtime = os.path.getmtime(path) if os.path.isfile(path) else 0.0
    except OSError:
        mtime = 0.0
    if _cache is not None and mtime == _cache_mtime:
        return _cache
    data = _empty_store()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                screens = raw.get("screens")
                if isinstance(screens, dict):
                    data["screens"] = {
                        str(k).strip().upper(): v
                        for k, v in screens.items()
                        if isinstance(v, dict)
                    }
                data["version"] = int(raw.get("version") or 1)
        except Exception as exc:
            logger.warning("Could not read cylinder mesh store: %s", exc)
    _cache = data
    _cache_mtime = mtime
    return data


def load_store() -> dict:
    with _lock:
        return deepcopy(_load_unlocked())


def save_store(data: dict) -> dict:
    global _cache, _cache_mtime
    payload = {
        "version": int((data or {}).get("version") or 1),
        "screens": {},
    }
    screens = (data or {}).get("screens") or {}
    if isinstance(screens, dict):
        for key, entry in screens.items():
            sid = str(key).strip().upper()
            if not sid or not isinstance(entry, dict):
                continue
            points = entry.get("points")
            if not isinstance(points, list) or len(points) != N_CONTROL:
                continue
            payload["screens"][sid] = {
                "screen": sid,
                "radius": float(entry.get("radius") or 0.0),
                "height": float(entry.get("height") or 0.0),
                "cx": float(entry.get("cx") or 0.0),
                "cy": float(entry.get("cy") or 0.0),
                "n_theta": int(entry.get("n_theta") or N_THETA),
                "n_height": int(entry.get("n_height") or N_HEIGHT),
                "smooth": bool(entry.get("smooth", True)),
                "points": [
                    [float(p[0]), float(p[1]), float(p[2])]
                    for p in points
                    if isinstance(p, (list, tuple)) and len(p) >= 3
                ],
            }
            if len(payload["screens"][sid]["points"]) != N_CONTROL:
                payload["screens"].pop(sid, None)
    path = MESH_FILE
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, path)
        _cache = deepcopy(payload)
        try:
            _cache_mtime = os.path.getmtime(path)
        except OSError:
            _cache_mtime = 0.0
    return deepcopy(payload)


def reload_store() -> dict:
    global _cache, _cache_mtime
    with _lock:
        _cache = None
        _cache_mtime = -1.0
        return deepcopy(_load_unlocked())


def clear_screen(screen: str) -> dict:
    store = load_store()
    sid = str(screen or "").strip().upper()
    store.get("screens", {}).pop(sid, None)
    return save_store(store)


def clear_all() -> dict:
    return save_store(_empty_store())


def get_screen_mesh(screen: str) -> Optional[dict]:
    sid = str(screen or "").strip().upper()
    if not sid:
        return None
    entry = (load_store().get("screens") or {}).get(sid)
    return deepcopy(entry) if isinstance(entry, dict) else None


def _require_numpy():
    if np is None:
        raise RuntimeError("numpy is required for cylinder mesh editing")


def control_point_count() -> int:
    return N_CONTROL


def point_on_classic_cylinder_xy(
    px: float,
    py: float,
    cx: float,
    cy: float,
    radius: float,
    height: float,
    *,
    eps: float = 0.75,
) -> bool:
    """True when (px, py) lies on/inside the classic green cylinder body."""
    r = max(4.0, float(radius))
    h = max(8.0, float(height))
    top_cy = float(cy) - h
    ry = max(3.0, r * 0.35)
    dx = float(px) - float(cx)
    dy = float(py) - float(cy)
    # Base circle
    if dx * dx + dy * dy <= (r + eps) * (r + eps):
        return True
    # Shaft rectangle
    if abs(dx) <= r + eps and (top_cy - eps) <= float(py) <= (float(cy) + eps):
        return True
    # Top ellipse
    if r > 0 and ry > 0:
        if (dx / r) ** 2 + ((float(py) - top_cy) / ry) ** 2 <= (1.0 + eps / max(r, ry)) ** 2:
            return True
    return False


def make_cylinder_points(
    cx: float,
    cy: float,
    radius: float,
    height: float,
    n_theta: int = N_THETA,
    n_height: int = N_HEIGHT,
):
    """Build a triangle-mesh sampling of the classic green finish cylinder.

    Every control point sits on that body (same shape as ``draw_finish_cylinder``):

    - bottom ring → base circle ``(cx, cy, r)``
    - top ring → foreshortened top ellipse ``(cx, cy-h, r, 0.35·r)``
    - middle rings → circular shaft wall of radius ``r`` (axis −Y)

    Z carries the round tube depth so the 3D volume matches the green body.
    Connectivity is fixed at ``n_theta × n_height`` (= 200) lateral samples.
    """
    _require_numpy()
    r = max(4.0, float(radius))
    h = max(8.0, float(height))
    n_theta = int(n_theta)
    n_height = int(n_height)
    ry = max(3.0, r * 0.35)
    cx = float(cx)
    cy = float(cy)
    top_cy = cy - h
    thetas = np.linspace(0.0, 2.0 * math.pi, n_theta, endpoint=False)
    pts = np.zeros((n_height * n_theta, 3), dtype=np.float64)
    i = 0
    for zi in range(n_height):
        t = 0.0 if n_height <= 1 else float(zi) / float(n_height - 1)
        for th in thetas:
            c = math.cos(th)
            s = math.sin(th)
            if zi == 0:
                # Classic base circle in image XY (green mouth).
                pts[i, 0] = cx + r * c
                pts[i, 1] = cy + r * s
                pts[i, 2] = r * s
            elif zi == n_height - 1:
                # Classic top ellipse in image XY.
                pts[i, 0] = cx + r * c
                pts[i, 1] = top_cy + ry * s
                pts[i, 2] = ry * s
            else:
                # Shaft wall: circular tube of radius r, axis −Y.
                pts[i, 0] = cx + r * c
                pts[i, 1] = cy - t * h
                pts[i, 2] = r * s
            i += 1
    return pts


def cylinder_faces(n_theta: int = N_THETA, n_height: int = N_HEIGHT):
    """Triangle faces for the lateral surface + top/bottom caps (fixed connectivity)."""
    _require_numpy()
    faces: List[List[int]] = []
    # Side quads → two triangles each.
    for z in range(n_height - 1):
        for t in range(n_theta):
            t2 = (t + 1) % n_theta
            a = z * n_theta + t
            b = z * n_theta + t2
            c = (z + 1) * n_theta + t2
            d = (z + 1) * n_theta + t
            faces.append([a, b, c])
            faces.append([a, c, d])
    # Bottom cap (z=0), outward normal -Z.
    for t in range(1, n_theta - 1):
        faces.append([0, t + 1, t])
    # Top cap (z=max), outward normal +Z.
    base = (n_height - 1) * n_theta
    for t in range(1, n_theta - 1):
        faces.append([base, base + t, base + t + 1])
    return np.asarray(faces, dtype=np.int32)


def faces_for_pyvista(faces) -> "np.ndarray":
    """Pack triangle indices as VTK/PyVista face array: [3,i,j,k, 3,...]."""
    _require_numpy()
    arr = np.asarray(faces, dtype=np.int64)
    out = np.empty((arr.shape[0], 4), dtype=np.int64)
    out[:, 0] = 3
    out[:, 1:] = arr
    return out.ravel()


def faces_as_triangles(
    n_theta: int = N_THETA,
    n_height: int = N_HEIGHT,
) -> List[List[int]]:
    """Triangle index list for WebGL TRIANGLES mode (LearnWebGL-style mesh)."""
    return cylinder_faces(n_theta, n_height).tolist()


def smooth_deform(
    points,
    index: int,
    delta: Sequence[float],
    *,
    smooth: bool = True,
    influence: float = 0.0,
    falloff: float = 2.0,
):
    """Move one control point; optionally pull neighbors with Gaussian weights.

    Connectivity is unchanged — only coordinates move.
    """
    _require_numpy()
    pts = np.asarray(points, dtype=np.float64).copy()
    idx = int(index)
    if idx < 0 or idx >= len(pts):
        return pts
    dxyz = np.asarray(delta, dtype=np.float64).reshape(3)
    if not smooth or influence <= 1e-6:
        pts[idx] = pts[idx] + dxyz
        return pts
    # Default influence ≈ 1.25 circumferential steps on the undeformed ring.
    sigma = float(influence)
    if sigma <= 0:
        # Estimate from nearest neighbor distance.
        diffs = pts - pts[idx]
        dist = np.linalg.norm(diffs, axis=1)
        dist[idx] = np.inf
        nearest = float(np.min(dist)) if np.isfinite(dist).any() else 1.0
        sigma = max(1.0, nearest * 1.75)
    sigma = max(1e-3, sigma)
    power = max(0.5, float(falloff))
    diffs = pts - pts[idx]
    dist2 = np.sum(diffs * diffs, axis=1)
    weights = np.exp(-dist2 / (2.0 * (sigma ** power)))
    weights[idx] = 1.0
    pts = pts + weights[:, None] * dxyz[None, :]
    return pts


def _point_in_ring(px: float, py: float, ring_xy) -> bool:
    """Even-odd winding point-in-polygon for one horizontal ring."""
    _require_numpy()
    xs = ring_xy[:, 0]
    ys = ring_xy[:, 1]
    n = len(xs)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = float(xs[i]), float(ys[i])
        xj, yj = float(xs[j]), float(ys[j])
        intersect = ((yi > py) != (yj > py)) and (
            px < (xj - xi) * (py - yi) / ((yj - yi) + 1e-12) + xi
        )
        if intersect:
            inside = not inside
        j = i
    return inside


def point_inside_mesh(
    point: Sequence[float],
    points,
    *,
    n_theta: int = N_THETA,
    n_height: int = N_HEIGHT,
) -> bool:
    """True when (x, y) lies inside the deformed cylinder's image silhouette.

    Height rings share the same image Y (axis −Y), so per-ring polygons are
    degenerate. Use the outer XY silhouette of all control points instead, then
    fall back to a band test between the lowest/highest ring Y for thin shapes.
    """
    _require_numpy()
    if point is None:
        return False
    px, py = float(point[0]), float(point[1])
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] != n_theta * n_height:
        return False
    sil = silhouette_polyline(pts, n_theta=n_theta, n_height=n_height, samples=72)
    if len(sil) >= 3 and _point_in_ring(px, py, np.asarray(sil, dtype=np.float64)):
        return True
    # Band fallback: inside [ymin, ymax] and within max |x-cx| at that height.
    ys = pts[:, 1]
    y_lo, y_hi = float(np.min(ys)), float(np.max(ys))
    if py < y_lo - 0.5 or py > y_hi + 0.5:
        return False
    # Interpolate leftmost/rightmost X across rings by Y.
    left = right = None
    for z in range(n_height):
        ring = pts[z * n_theta : (z + 1) * n_theta]
        ry = float(np.mean(ring[:, 1]))
        xmin = float(np.min(ring[:, 0]))
        xmax = float(np.max(ring[:, 0]))
        if left is None:
            left, right = [(ry, xmin)], [(ry, xmax)]
        else:
            left.append((ry, xmin))
            right.append((ry, xmax))
    def _interp(samples, y):
        samples = sorted(samples, key=lambda t: t[0])
        if y <= samples[0][0]:
            return samples[0][1]
        if y >= samples[-1][0]:
            return samples[-1][1]
        for i in range(len(samples) - 1):
            y0, v0 = samples[i]
            y1, v1 = samples[i + 1]
            if y0 <= y <= y1 or y1 <= y <= y0:
                if abs(y1 - y0) < 1e-9:
                    return v0
                t = (y - y0) / (y1 - y0)
                return v0 + t * (v1 - v0)
        return samples[-1][1]

    xmin = _interp(left or [(0.0, px)], py)
    xmax = _interp(right or [(0.0, px)], py)
    return xmin - 0.5 <= px <= xmax + 0.5


def _dist_point_segment(px, py, ax, ay, bx, by) -> float:
    abx, aby = bx - ax, by - ay
    length2 = abx * abx + aby * aby
    if length2 <= 1e-12:
        dx, dy = px - ax, py - ay
        return math.hypot(dx, dy)
    t = ((px - ax) * abx + (py - ay) * aby) / length2
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    dx = px - (ax + t * abx)
    dy = py - (ay + t * aby)
    return math.hypot(dx, dy)


def distance_to_wire(
    point: Sequence[float],
    points,
    *,
    n_theta: int = N_THETA,
    n_height: int = N_HEIGHT,
) -> float:
    """Pixels from (x, y) to the nearest drawn mesh link."""
    _require_numpy()
    if point is None:
        return 1e9
    px, py = float(point[0]), float(point[1])
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] != n_theta * n_height:
        return 1e9
    best = 1e9
    for z in range(n_height):
        row = z * n_theta
        for t in range(n_theta):
            a = pts[row + t]
            b = pts[row + ((t + 1) % n_theta)]
            dist = _dist_point_segment(px, py, float(a[0]), float(a[1]), float(b[0]), float(b[1]))
            if dist < best:
                best = dist
    for t in range(n_theta):
        for z in range(n_height - 1):
            a = pts[z * n_theta + t]
            b = pts[(z + 1) * n_theta + t]
            dist = _dist_point_segment(px, py, float(a[0]), float(a[1]), float(b[0]), float(b[1]))
            if dist < best:
                best = dist
    return best


def ball_hits_mesh(
    point: Sequence[float],
    points,
    *,
    radius: float = 0.0,
    n_theta: int = N_THETA,
    n_height: int = N_HEIGHT,
) -> bool:
    """True when the ball overlaps the drawn triangle mesh.

    Interior of the silhouette counts. So does the ball body touching a white
    link — the silhouette test alone leaves gaps on the wires.
    """
    if point_inside_mesh(point, points, n_theta=n_theta, n_height=n_height):
        return True
    try:
        reach = max(0.0, float(radius or 0.0))
    except (TypeError, ValueError):
        reach = 0.0
    # Drawn links are about 2px wide; the ball extends ``radius`` beyond its center.
    return distance_to_wire(
        point, points, n_theta=n_theta, n_height=n_height
    ) <= (reach + 2.0)


def silhouette_polyline(
    points,
    *,
    n_theta: int = N_THETA,
    n_height: int = N_HEIGHT,
    samples: int = 64,
):
    """Outer XY silhouette for 2D overlay (max radius per angle from centroid)."""
    _require_numpy()
    pts = np.asarray(points, dtype=np.float64)
    if pts.size == 0:
        return []
    cx = float(np.mean(pts[:, 0]))
    cy = float(np.mean(pts[:, 1]))
    angles = np.linspace(0.0, 2.0 * math.pi, int(samples), endpoint=False)
    out = []
    for ang in angles:
        dx, dy = math.cos(ang), math.sin(ang)
        best = 0.0
        for p in pts:
            # Project onto ray from centroid; keep farthest positive projection.
            vx, vy = float(p[0]) - cx, float(p[1]) - cy
            proj = vx * dx + vy * dy
            if proj > best:
                best = proj
        out.append([cx + best * dx, cy + best * dy])
    return out


def wire_segments(
    points,
    *,
    n_theta: int = N_THETA,
    n_height: int = N_HEIGHT,
):
    """Edge list for drawing deformed cylinder wireframe in the 2D overlay."""
    _require_numpy()
    pts = np.asarray(points, dtype=np.float64)
    segs = []
    for z in range(n_height):
        for t in range(n_theta):
            a = z * n_theta + t
            b = z * n_theta + ((t + 1) % n_theta)
            segs.append((pts[a, :2].tolist(), pts[b, :2].tolist()))
    for t in range(n_theta):
        for z in range(n_height - 1):
            a = z * n_theta + t
            b = (z + 1) * n_theta + t
            segs.append((pts[a, :2].tolist(), pts[b, :2].tolist()))
    return segs


def entry_from_preview(screen: str, preview: dict, points=None) -> dict:
    """Build a store entry from finish_cylinder_preview (keeps current size)."""
    _require_numpy()
    sid = str(screen or "").strip().upper()
    radius = float((preview or {}).get("radius") or 0.0)
    height = float((preview or {}).get("height") or 31.0)
    cx = float((preview or {}).get("cx") or 0.0)
    cy = float((preview or {}).get("cy") or 0.0)
    if points is None:
        pts = make_cylinder_points(cx, cy, radius, height)
    else:
        pts = np.asarray(points, dtype=np.float64)
    return {
        "screen": sid,
        "radius": radius,
        "height": height,
        "cx": cx,
        "cy": cy,
        "n_theta": N_THETA,
        "n_height": N_HEIGHT,
        "smooth": True,
        "points": pts.tolist(),
    }


def save_screen_points(screen: str, preview: dict, points, *, smooth: bool = True) -> dict:
    store = load_store()
    entry = entry_from_preview(screen, preview, points=points)
    entry["smooth"] = bool(smooth)
    store.setdefault("screens", {})[entry["screen"]] = entry
    return save_store(store)


def public_mesh_status(screens: Optional[Sequence[str]] = None) -> dict:
    store = load_store()
    saved = store.get("screens") or {}
    ids = list(screens) if screens else sorted(saved.keys())
    out = {}
    for sid in ids:
        key = str(sid).strip().upper()
        entry = saved.get(key)
        out[key] = {
            "sculpted": bool(entry),
            "n_points": N_CONTROL if entry else 0,
            "radius": float((entry or {}).get("radius") or 0.0),
            "height": float((entry or {}).get("height") or 0.0),
        }
    return {
        "n_control": N_CONTROL,
        "n_theta": N_THETA,
        "n_height": N_HEIGHT,
        "screens": out,
        "sculpted_count": sum(1 for v in out.values() if v.get("sculpted")),
    }
