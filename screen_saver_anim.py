"""Pixel clips built from mp4 into .ssav (JPEG frame packs).

Used for the cabinet screensaver and for Foundation / Omid pass playback.
The clip is decoded once. Each frame is stored as JPEG pixels and replayed
by the projector canvas, so play never opens the video file.
"""

from __future__ import annotations

import os
import struct
import sys
import threading

SCREEN_SAVER_FRAME_SIZE = 480
SCREEN_SAVER_JPEG_QUALITY = 74
_CACHE_MAGIC = b"SSAV1"
_lock = threading.Lock()
_cached = None  # (jpeg_bytes_list, interval_ms, source_stamp)
_file_cache = {}  # abspath -> (jpeg_bytes_list, interval_ms, mtime, size)


def _source_stamp(path):
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (os.path.abspath(path), int(stat.st_mtime), int(stat.st_size))


def _cache_path(source):
    folder = os.path.dirname(os.path.abspath(source))
    return os.path.join(folder, "screen_saver_pixels.ssav")


def ssav_path_for_video(source, name="pass_pixels.ssav"):
    """Default .ssav path beside a pass (or other) video."""
    folder = os.path.dirname(os.path.abspath(source))
    return os.path.join(folder, name)


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


def convert_video_to_ssav(video_path, ssav_path=None, size=SCREEN_SAVER_FRAME_SIZE, quality=SCREEN_SAVER_JPEG_QUALITY):
    """Decode an mp4 into a .ssav pixel pack. Returns the .ssav path or ''."""
    video_path = os.path.abspath(str(video_path or ""))
    if not video_path or not os.path.isfile(video_path):
        return ""
    out = os.path.abspath(ssav_path) if ssav_path else ssav_path_for_video(video_path)
    stamp = _source_stamp(video_path)
    if not stamp:
        return ""
    existing = _read_cache(out, stamp)
    if existing is not None:
        return out
    frames, interval_ms = extract_screensaver_frames(video_path, size=size, quality=quality)
    if not frames:
        return ""
    _write_cache(out, frames, interval_ms, stamp)
    with _lock:
        _file_cache[out] = (frames, interval_ms, stamp[1], stamp[2])
    return out if os.path.isfile(out) else ""


def load_ssav_pixels_file(ssav_path):
    """Load JPEG frames from a .ssav file only — never opens an mp4 at play time."""
    path = os.path.abspath(str(ssav_path or ""))
    if not path or not os.path.isfile(path):
        return [], 33
    try:
        stat = os.stat(path)
        stamp = (int(stat.st_mtime), int(stat.st_size))
    except OSError:
        return [], 33
    with _lock:
        hit = _file_cache.get(path)
        if hit is not None and hit[2] == stamp[0] and hit[3] == stamp[1]:
            return hit[0], hit[1]
    loaded = _read_cache_any(path)
    if loaded is None:
        return [], 33
    frames, interval_ms = loaded
    with _lock:
        _file_cache[path] = (frames, interval_ms, stamp[0], stamp[1])
    return frames, interval_ms


def ensure_pass_ssav(directory_or_video, name="pass_pixels.ssav"):
    """Return pass_pixels.ssav beside pass.mp4, converting the video if needed."""
    path = str(directory_or_video or "")
    if not path:
        return ""
    if os.path.isfile(path) and path.lower().endswith((".mp4", ".mov", ".avi", ".mkv")):
        video = path
        folder = os.path.dirname(path)
    elif os.path.isdir(path):
        folder = path
        video = os.path.join(folder, "pass.mp4")
    else:
        return ""
    ssav = os.path.join(folder, name)
    if os.path.isfile(ssav):
        loaded = _read_cache_any(ssav)
        if loaded:
            return ssav
    if os.path.isfile(video):
        return convert_video_to_ssav(video, ssav)
    return ssav if os.path.isfile(ssav) else ""


if __name__ == "__main__":
    targets = sys.argv[1:] or []
    if not targets:
        print("Usage: python screen_saver_anim.py <pass.mp4> [more.mp4 ...]")
        sys.exit(1)
    for item in targets:
        out = convert_video_to_ssav(item)
        if out:
            frames, interval = load_ssav_pixels_file(out)
            print(f"OK {item} -> {out} ({len(frames)} frames, {interval}ms)")
        else:
            print(f"FAIL {item}")
            sys.exit(2)
