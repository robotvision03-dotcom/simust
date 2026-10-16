"""Pixel screensaver built from static/screen_saver.mp4.

The clip is decoded once. Each frame is stored as JPEG pixels and replayed
by the projector canvas, so idle cabinets no longer open the video file.
"""

import os
import struct
import threading

SCREEN_SAVER_FRAME_SIZE = 480
SCREEN_SAVER_JPEG_QUALITY = 74
_CACHE_MAGIC = b"SSAV1"
_lock = threading.Lock()
_cached = None  # (jpeg_bytes_list, interval_ms, source_stamp)


def _source_stamp(path):
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (os.path.abspath(path), int(stat.st_mtime), int(stat.st_size))


def _cache_path(source):
    folder = os.path.dirname(os.path.abspath(source))
    return os.path.join(folder, "screen_saver_pixels.ssav")


def _read_cache(path, stamp):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as handle:
            magic = handle.read(5)
            if magic != _CACHE_MAGIC:
                return None
            header = handle.read(struct.calcsize("<4I"))
            if len(header) < struct.calcsize("<4I"):
                return None
            width, count, interval_ms, stamp_size = struct.unpack("<4I", header)
            if width < 8 or count < 1 or interval_ms < 1:
                return None
            raw_stamp = handle.read(stamp_size)
            if raw_stamp != _pack_stamp(stamp):
                return None
            frames = []
            for _ in range(count):
                size_raw = handle.read(4)
                if len(size_raw) < 4:
                    return None
                size = struct.unpack("<I", size_raw)[0]
                blob = handle.read(size)
                if len(blob) != size:
                    return None
                frames.append(blob)
    except OSError:
        return None
    return frames, int(interval_ms)


def _pack_stamp(stamp):
    text = "|".join(str(part) for part in stamp).encode("utf-8")
    return text


def _write_cache(path, frames, interval_ms, stamp):
    stamp_bytes = _pack_stamp(stamp)
    try:
        tmp = path + ".tmp"
        with open(tmp, "wb") as handle:
            handle.write(_CACHE_MAGIC)
            handle.write(struct.pack(
                "<4I",
                int(SCREEN_SAVER_FRAME_SIZE),
                int(len(frames)),
                int(interval_ms),
                int(len(stamp_bytes)),
            ))
            handle.write(stamp_bytes)
            for blob in frames:
                handle.write(struct.pack("<I", len(blob)))
                handle.write(blob)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(path + ".tmp")
        except OSError:
            pass


def extract_screensaver_frames(path, size=SCREEN_SAVER_FRAME_SIZE, quality=SCREEN_SAVER_JPEG_QUALITY):
    """Decode the source clip into JPEG pixel frames. Returns (frames, interval_ms)."""
    import cv2

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return [], 33
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    if fps < 1.0 or fps > 120.0:
        fps = 30.0
    frames = []
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            small = cv2.resize(frame, (int(size), int(size)), interpolation=cv2.INTER_AREA)
            encoded, buf = cv2.imencode(
                ".jpg",
                small,
                [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)],
            )
            if encoded:
                frames.append(bytes(buf))
    finally:
        cap.release()
    interval_ms = max(16, int(round(1000.0 / fps)))
    return frames, interval_ms


def _read_cache_any(path):
    """Load .ssav frames ignoring stamp — used so play never needs the video open."""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as handle:
            magic = handle.read(5)
            if magic != _CACHE_MAGIC:
                return None
            header = handle.read(struct.calcsize("<4I"))
            if len(header) < struct.calcsize("<4I"):
                return None
            width, count, interval_ms, stamp_size = struct.unpack("<4I", header)
            if width < 8 or count < 1 or interval_ms < 1:
                return None
            handle.read(stamp_size)  # skip stamp
            frames = []
            for _ in range(count):
                size_raw = handle.read(4)
                if len(size_raw) < 4:
                    return None
                size = struct.unpack("<I", size_raw)[0]
                blob = handle.read(size)
                if len(blob) != size:
                    return None
                frames.append(blob)
    except OSError:
        return None
    return frames, int(interval_ms)


def load_screensaver_pixels(path):
    """Return JPEG frames from .ssav cache (extract from video only if cache missing)."""
    global _cached
    stamp = _source_stamp(path) if path else None
    cache_file = _cache_path(path) if path else None
    if not cache_file and path:
        return [], 33
    # Prefer static/screen_saver_pixels.ssav beside the clip.
    if not cache_file:
        static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
        cache_file = os.path.join(static_dir, "screen_saver_pixels.ssav")
    with _lock:
        if _cached is not None and (stamp is None or _cached[2] == stamp):
            return _cached[0], _cached[1]
        loaded = _read_cache(cache_file, stamp) if stamp else None
        if loaded is None:
            loaded = _read_cache_any(cache_file)
        if loaded is None and path and os.path.isfile(path):
            frames, interval_ms = extract_screensaver_frames(path)
            if frames and stamp:
                _write_cache(cache_file, frames, interval_ms, stamp)
            loaded = (frames, interval_ms) if frames else None
        if loaded is None:
            return [], 33
        frames, interval_ms = loaded
        _cached = (frames, interval_ms, stamp or ("ssav", cache_file, len(frames)))
        return frames, interval_ms
