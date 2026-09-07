"""Ground-plane homography: image pixels -> real-world metres.

Used only for displacement/distance. YOLO Pose hip tracking is unchanged.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import cv2
    import numpy as np
except Exception:  # pragma: no cover - public host has no OpenCV
    cv2 = None
    np = None

logger = logging.getLogger(__name__)

CALIBRATION_FILE = os.environ.get("SIMUST_HOMOGRAPHY_FILE", "homography_calibration.json")
FRAME_DIR = os.environ.get("SIMUST_HOMOGRAPHY_FRAME_DIR", "homography_frames")
TRACKING_FRAME_HEIGHT = 360
MIN_POINTS = 4
MIN_PAIRS = 2
SNAP_PX = 12.0
FALLBACK_M_PER_PX = 0.0259
LEFT_CAMERA = "camera-1"
RIGHT_CAMERA = "camera-8"
MAX_RMSE_M = 3.0
FRAME_RESIDUAL_WEIGHT = 6.0

_lock = threading.Lock()
_cache: Optional[dict] = None
_cache_mtime: float = 0.0


def _empty_store() -> dict:
    return {"cameras": {}}


def load_store(path: str = CALIBRATION_FILE) -> dict:
    global _cache, _cache_mtime
    with _lock:
        try:
            mtime = os.path.getmtime(path) if os.path.isfile(path) else 0.0
        except OSError:
            mtime = 0.0
        if _cache is not None and mtime == _cache_mtime:
            return _cache
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    data.setdefault("cameras", {})
                    _cache = data
                    _cache_mtime = mtime
                    return data
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Could not read homography file: %s", exc)
        _cache = _empty_store()
        _cache_mtime = mtime
        return _cache


def save_store(store: dict, path: str = CALIBRATION_FILE) -> None:
    global _cache, _cache_mtime
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(store, handle, indent=2)
    os.replace(tmp, path)
    with _lock:
        _cache = store
        try:
            _cache_mtime = os.path.getmtime(path)
        except OSError:
            _cache_mtime = time.time()


def camera_record(store: dict, camera_name: str) -> dict:
    cameras = store.setdefault("cameras", {})
    return cameras.get(camera_name) or {}


def is_calibrated(record: Optional[dict]) -> bool:
    if not record:
        return False
    h = record.get("H")
    return bool(record.get("calibrated")) and isinstance(h, list) and len(h) == 3


def public_camera_status(camera_name: str, record: Optional[dict] = None) -> dict:
    rec = record or camera_record(load_store(), camera_name)
    points = rec.get("points") or []
    pairs = rec.get("pairs") or []
    return {
        "camera": camera_name,
        "status": "Calibrated" if is_calibrated(rec) else "Not Calibrated",
        "calibrated": is_calibrated(rec),
        "point_count": len(points),
        "pair_count": len(pairs),
        "rmse_m": rec.get("rmse_m"),
        "image_width": rec.get("image_width"),
        "image_height": rec.get("image_height"),
        "updated_at": rec.get("updated_at"),
        "points": points,
        "pairs": pairs,
        "frame_url": rec.get("frame_file") and f"/homography/saved-frame/{camera_name}",
    }


def _as_xy(points: Sequence) -> List[Tuple[float, float]]:
    out = []
    for item in points:
        if isinstance(item, dict):
            if "u" in item and "v" in item:
                out.append((float(item["u"]), float(item["v"])))
            else:
                out.append((float(item["x"]), float(item["y"])))
        else:
            out.append((float(item[0]), float(item[1])))
    return out


def _uv(item) -> Tuple[float, float]:
    if isinstance(item, dict):
        if "u" in item:
            return float(item["u"]), float(item["v"])
        return float(item["x"]), float(item["y"])
    return float(item[0]), float(item[1])


def parse_pairs(raw: Sequence) -> List[dict]:
    pairs = []
    for item in raw or []:
        if not isinstance(item, dict):
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                raise ValueError("Each pair needs Point A, Point B, and a distance in metres")
            a, b, dist = item[0], item[1], item[2]
        else:
            a = item.get("a") if item.get("a") is not None else item.get("A")
            b = item.get("b") if item.get("b") is not None else item.get("B")
            dist = item.get("distance", item.get("meters", item.get("d")))
        if a is None or b is None or dist is None or dist == "":
            raise ValueError("Each pair needs Point A, Point B, and a distance in metres")
        distance = float(dist)
        if distance <= 0:
            raise ValueError("Real-world distance must be greater than 0 metres")
        ua, va = _uv(a)
        ub, vb = _uv(b)
        if ((ua - ub) ** 2 + (va - vb) ** 2) ** 0.5 < 2:
            raise ValueError("Point A and Point B of a pair are too close in the image")
        pairs.append({"a": (ua, va), "b": (ub, vb), "distance": distance})
    if len(pairs) < MIN_PAIRS:
        raise ValueError("Add at least two point pairs with known real-world distances")
    return pairs


def _near(p: Tuple[float, float], q: Tuple[float, float], snap: float = SNAP_PX) -> bool:
    return math.hypot(p[0] - q[0], p[1] - q[1]) <= snap


def _apply_h(H, u: float, v: float) -> Optional[Tuple[float, float]]:
    vec = H @ np.array([u, v, 1.0], dtype=np.float64)
    if abs(vec[2]) < 1e-12:
        return None
    x, y = float(vec[0] / vec[2]), float(vec[1] / vec[2])
    if not (np.isfinite(x) and np.isfinite(y)):
        return None
    return x, y


def _pack_H(H) -> np.ndarray:
    H = np.asarray(H, dtype=np.float64)
    if abs(H[2, 2]) < 1e-12:
        raise ValueError("Homography is invalid")
    H = H / H[2, 2]
    return H.reshape(9)[:8]


def _unpack_H(params) -> np.ndarray:
    vals = np.append(np.asarray(params, dtype=np.float64), 1.0)
    return vals.reshape(3, 3)


def similarity_H_from_pair(a: Tuple[float, float], b: Tuple[float, float], dist: float):
    """Map image pair A→(0,0), B→(dist, 0) with a similarity."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    pix = math.hypot(dx, dy)
    if pix < 2:
        raise ValueError("Point A and Point B of a pair are too close in the image")
    scale = dist / pix
    ang = math.atan2(dy, dx)
    c, s = math.cos(ang), math.sin(ang)
    r00, r01 = scale * c, scale * s
    r10, r11 = -scale * s, scale * c
    return np.array(
        [
            [r00, r01, -(r00 * a[0] + r01 * a[1])],
            [r10, r11, -(r10 * a[0] + r11 * a[1])],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )


def _stretch_y_to_pairs(H, pairs: List[dict]):
    """Anisotropic Y scale so the most vertical pair matches its metre length."""
    best = None
    for pair in pairs[1:]:
        wa = _apply_h(H, *pair["a"])
        wb = _apply_h(H, *pair["b"])
        if wa is None or wb is None:
            continue
        dx, dy = wb[0] - wa[0], wb[1] - wa[1]
        if abs(dy) < 1e-6:
            continue
        score = abs(dy) / (math.hypot(dx, dy) + 1e-9)
        k_sq = (pair["distance"] ** 2 - dx * dx) / (dy * dy)
        if k_sq <= 0:
            continue
        cand = (score, math.sqrt(k_sq))
        if best is None or cand[0] > best[0]:
            best = cand
    if best is None:
        return H
    k = best[1]
    S = np.array([[1.0, 0.0, 0.0], [0.0, k, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    return S @ H


def pair_distance_rmse(H, pairs: Sequence[dict]) -> float:
    err = []
    for pair in pairs:
        wa = _apply_h(H, *pair["a"])
        wb = _apply_h(H, *pair["b"])
        if wa is None or wb is None:
            return 1e9
        pred = math.hypot(wb[0] - wa[0], wb[1] - wa[1])
        err.append((pred - pair["distance"]) ** 2)
    return math.sqrt(sum(err) / len(err)) if err else 1e9


def _distance_residuals(params, pairs: List[dict]) -> np.ndarray:
    H = _unpack_H(params)
    first = pairs[0]
    residuals = []
    wa = _apply_h(H, *first["a"])
    wb = _apply_h(H, *first["b"])
    if wa is None or wb is None:
        return np.full(8 + len(pairs), 1e3)
    w = FRAME_RESIDUAL_WEIGHT
    residuals.extend([w * wa[0], w * wa[1], w * (wb[0] - first["distance"]), w * wb[1]])
    for pair in pairs:
        pa = _apply_h(H, *pair["a"])
        pb = _apply_h(H, *pair["b"])
        if pa is None or pb is None:
            residuals.append(1e3)
            continue
        residuals.append(math.hypot(pb[0] - pa[0], pb[1] - pa[1]) - pair["distance"])
    return np.asarray(residuals, dtype=np.float64)


def _fit_H_to_pair_distances(pairs: List[dict], H0) -> np.ndarray:
    x0 = _pack_H(H0)
    try:
        from scipy.optimize import least_squares

        fit = least_squares(
            _distance_residuals,
            x0,
            args=(pairs,),
            method="trf",
            max_nfev=800,
            ftol=1e-10,
            xtol=1e-10,
            gtol=1e-10,
        )
        return _unpack_H(fit.x)
    except Exception:
        H = np.array(H0, dtype=np.float64)
        lam = 1e-2
        for _ in range(80):
            r0 = _distance_residuals(_pack_H(H), pairs)
            base = float(np.dot(r0, r0))
            J = np.zeros((len(r0), 8), dtype=np.float64)
            for i in range(8):
                step = np.zeros(8)
                packed = _pack_H(H)
                delta = 1e-6 if abs(packed[i]) < 1 else 1e-6 * abs(packed[i])
                packed[i] += delta
                J[:, i] = (_distance_residuals(packed, pairs) - r0) / delta
            try:
                delta_x = np.linalg.solve(J.T @ J + lam * np.eye(8), -J.T @ r0)
            except np.linalg.LinAlgError:
                break
            trial = _unpack_H(_pack_H(H) + delta_x)
            r1 = _distance_residuals(_pack_H(trial), pairs)
            if float(np.dot(r1, r1)) < base:
                H = trial
                lam = max(lam * 0.3, 1e-8)
            else:
                lam *= 3.0
        return H


def compute_homography_from_pairs(raw_pairs: Sequence) -> dict:
    """Fit image→metre homography so each clicked pair matches its measured length."""
    if cv2 is None or np is None:
        raise RuntimeError("OpenCV is required for homography calibration")
    pairs = parse_pairs(raw_pairs)
    best_H = None
    best_rmse = 1e9
    for i in range(len(pairs)):
        ordered = [pairs[i]] + [p for j, p in enumerate(pairs) if j != i]
        H0 = similarity_H_from_pair(ordered[0]["a"], ordered[0]["b"], ordered[0]["distance"])
        H0 = _stretch_y_to_pairs(H0, ordered)
        H = _fit_H_to_pair_distances(ordered, H0)
        rmse = pair_distance_rmse(H, pairs)
        if rmse < best_rmse:
            best_rmse = rmse
            best_H = H
    H = best_H
    rmse = best_rmse
    if rmse > MAX_RMSE_M:
        raise ValueError(
            f"Calibration error is too high ({rmse:.2f} m). "
            "Use pairs in different directions on the ground and check the metre values."
        )
    img_pts = []
    world_pts = []
    seen = []
    for pair in pairs:
        for pt in (pair["a"], pair["b"]):
            if any(_near(pt, prev) for prev in seen):
                continue
            mapped = _apply_h(H, *pt)
            if mapped is None:
                continue
            seen.append(pt)
            img_pts.append(list(pt))
            world_pts.append([mapped[0], mapped[1]])
    return {
        "H": H.tolist(),
        "rmse_m": round(rmse, 4),
        "inliers": len(pairs),
        "point_count": len(img_pts),
        "valid": True,
        "image_points": img_pts,
        "world_points": world_pts,
        "pairs": [
            {
                "a": {"u": p["a"][0], "v": p["a"][1]},
                "b": {"u": p["b"][0], "v": p["b"][1]},
                "distance": p["distance"],
            }
            for p in pairs
        ],
    }


def compute_from_payload(data: dict) -> dict:
    pairs = data.get("pairs")
    if pairs:
        return compute_homography_from_pairs(pairs)
    return compute_homography(data.get("image_points") or [], data.get("world_points") or [])


def compute_homography(
    image_points: Sequence,
    world_points: Sequence,
) -> dict:
    if cv2 is None or np is None:
        raise RuntimeError("OpenCV is required for homography calibration")
    img = _as_xy(image_points)
    world = _as_xy(world_points)
    if len(img) != len(world):
        raise ValueError("Each image point needs a matching real-world (X, Y) coordinate")
    if len(img) < MIN_POINTS:
        raise ValueError(f"Select at least {MIN_POINTS} ground-plane points")
    src = np.array(img, dtype=np.float64)
    dst = np.array(world, dtype=np.float64)
    if np.unique(src, axis=0).shape[0] < MIN_POINTS:
        raise ValueError("Image points are too similar; spread them across the ground plane")
    if np.unique(dst, axis=0).shape[0] < MIN_POINTS:
        raise ValueError("World points are too similar; use distinct metre coordinates")
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 0.05)
    if H is None:
        raise ValueError("Homography is invalid. Check that points lie on the ground plane.")
    pred = cv2.perspectiveTransform(src.reshape(-1, 1, 2).astype(np.float32), H).reshape(-1, 2)
    err = pred - dst.astype(np.float32)
    rmse = float(np.sqrt(np.mean(np.sum(err * err, axis=1))))
    inliers = int(mask.sum()) if mask is not None else len(img)
    if inliers < MIN_POINTS:
        raise ValueError("Calibration is invalid: fewer than 4 inlier points")
    if rmse > MAX_RMSE_M:
        raise ValueError(f"Calibration error is too high ({rmse:.2f} m). Recheck the measured distances.")
    return {
        "H": H.tolist(),
        "rmse_m": round(rmse, 4),
        "inliers": inliers,
        "point_count": len(img),
        "valid": True,
    }


def pixel_to_world(u: float, v: float, H) -> Optional[Tuple[float, float]]:
    if cv2 is None or np is None or H is None:
        return None
    matrix = np.array(H, dtype=np.float64)
    if matrix.shape != (3, 3):
        return None
    pt = np.array([[[float(u), float(v)]]], dtype=np.float32)
    try:
        out = cv2.perspectiveTransform(pt, matrix)
    except cv2.error:
        return None
    x, y = float(out[0, 0, 0]), float(out[0, 0, 1])
    if not (np.isfinite(x) and np.isfinite(y)):
        return None
    return x, y


def stitch_split_x(store: Optional[dict] = None) -> float:
    rec = camera_record(store or load_store(), LEFT_CAMERA)
    width = rec.get("image_width")
    try:
        return float(width) if width else 640.0
    except (TypeError, ValueError):
        return 640.0


def hip_pixel_to_world(u: float, v: float, store: Optional[dict] = None) -> Optional[Tuple[float, float]]:
    """Map a stitched-frame hip pixel onto the matching camera homography."""
    data = store or load_store()
    split = stitch_split_x(data)
    if u < split:
        rec = camera_record(data, LEFT_CAMERA)
        local_u = u
    else:
        rec = camera_record(data, RIGHT_CAMERA)
        local_u = u - split
    if not is_calibrated(rec):
        return None
    return pixel_to_world(local_u, v, rec.get("H"))


def path_distance_meters(
    positions: Iterable[Sequence],
    store: Optional[dict] = None,
    fallback_m_per_px: float = FALLBACK_M_PER_PX,
) -> float:
    """Sum ground-plane distance from hip samples (t, u, v) or (u, v)."""
    data = store or load_store()
    pts = []
    for item in positions:
        if item is None:
            continue
        if len(item) >= 3:
            u, v = item[1], item[2]
        elif len(item) == 2:
            u, v = item[0], item[1]
        else:
            continue
        if u is None or v is None:
            continue
        pts.append((float(u), float(v)))
    if len(pts) < 2:
        return 0.0
    any_h = is_calibrated(camera_record(data, LEFT_CAMERA)) or is_calibrated(camera_record(data, RIGHT_CAMERA))
    total = 0.0
    for i in range(1, len(pts)):
        u1, v1 = pts[i - 1]
        u2, v2 = pts[i]
        if any_h:
            w1 = hip_pixel_to_world(u1, v1, data)
            w2 = hip_pixel_to_world(u2, v2, data)
            if w1 and w2:
                total += ((w2[0] - w1[0]) ** 2 + (w2[1] - w1[1]) ** 2) ** 0.5
                continue
        total += (((u2 - u1) ** 2 + (v2 - v1) ** 2) ** 0.5) * fallback_m_per_px
    return float(total)


def resize_to_tracking_height(frame):
    h, w = frame.shape[:2]
    target_h = TRACKING_FRAME_HEIGHT
    target_w = int(w * target_h / h)
    return cv2.resize(frame, (target_w, target_h))


def grab_camera_jpeg(url: str, timeout_s: float = 8.0) -> Tuple[bytes, int, int]:
    if cv2 is None:
        raise RuntimeError("OpenCV is required to capture a calibration frame")
    holder: Dict[str, Any] = {"jpeg": None, "w": 0, "h": 0, "error": None}

    def _grab() -> None:
        cap = None
        try:
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not cap.isOpened():
                holder["error"] = "Could not open camera"
                return
            frame = None
            for _ in range(15):
                ok, grabbed = cap.read()
                if ok and grabbed is not None:
                    frame = grabbed
            if frame is None:
                holder["error"] = "No frame from camera"
                return
            frame = resize_to_tracking_height(frame)
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok:
                holder["error"] = "Could not encode frame"
                return
            h, w = frame.shape[:2]
            holder["jpeg"] = buf.tobytes()
            holder["w"] = int(w)
            holder["h"] = int(h)
        except Exception as exc:
            holder["error"] = str(exc)
        finally:
            if cap is not None:
                cap.release()

    thread = threading.Thread(target=_grab, daemon=True)
    thread.start()
    thread.join(timeout_s)
    if thread.is_alive():
        raise TimeoutError("Camera capture timed out")
    if holder["error"] or not holder["jpeg"]:
        raise RuntimeError(holder["error"] or "Camera capture failed")
    return holder["jpeg"], holder["w"], holder["h"]


def save_camera_calibration(
    camera_name: str,
    image_points: Sequence = (),
    world_points: Sequence = (),
    image_width: int = 0,
    image_height: int = 0,
    frame_jpeg: Optional[bytes] = None,
    pairs: Optional[Sequence] = None,
) -> dict:
    if pairs:
        computed = compute_homography_from_pairs(pairs)
        img = [(float(p[0]), float(p[1])) for p in computed["image_points"]]
        world = [(float(p[0]), float(p[1])) for p in computed["world_points"]]
        stored_pairs = computed["pairs"]
    else:
        computed = compute_homography(image_points, world_points)
        img = _as_xy(image_points)
        world = _as_xy(world_points)
        stored_pairs = []
    points = []
    for (u, v), (x, y) in zip(img, world):
        points.append({"u": u, "v": v, "x": x, "y": y})
    frame_file = None
    if frame_jpeg:
        os.makedirs(FRAME_DIR, exist_ok=True)
        frame_file = os.path.join(FRAME_DIR, f"{camera_name}.jpg")
        with open(frame_file, "wb") as handle:
            handle.write(frame_jpeg)
    store = load_store()
    store.setdefault("cameras", {})[camera_name] = {
        "calibrated": True,
        "H": computed["H"],
        "rmse_m": computed["rmse_m"],
        "inliers": computed["inliers"],
        "points": points,
        "pairs": stored_pairs,
        "image_width": int(image_width),
        "image_height": int(image_height),
        "frame_file": frame_file,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    save_store(store)
    return public_camera_status(camera_name, store["cameras"][camera_name])


def reset_camera_calibration(camera_name: str) -> dict:
    store = load_store()
    cameras = store.setdefault("cameras", {})
    cameras.pop(camera_name, None)
    save_store(store)
    frame_file = os.path.join(FRAME_DIR, f"{camera_name}.jpg")
    try:
        if os.path.isfile(frame_file):
            os.remove(frame_file)
    except OSError:
        pass
    return public_camera_status(camera_name, {})
