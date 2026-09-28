"""Save each Wrong action and play those slices on screens 3 and 4.

A 3 second action that is Wrong becomes a 3 second slice of the session
video. During that test's per-video results each slice plays whole on
screen 3 and, separately, whole on screen 4. Field A uses A3 and A4.
Field B uses B3 and B4. One second of black follows each slice.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Any, Dict, List, Optional

import cv2

logger = logging.getLogger(__name__)

WRONG_GAP_SEC = 1.0
MIN_RESULTS_SEC = 20.0
REEL_FPS = 20


def _as_float(value: Any) -> Optional[float]:
    if value in (None, "", "-", "N/A"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return number


def wrong_clip_windows(results, blocks, video_index=None) -> List[Dict[str, Any]]:
    """Wrong actions for one test, in session order.

    Each window is the action's own session time (the On duration), starting
    at the frame the session video had already saved.
    """
    by_id = {}
    for block in blocks or []:
        if isinstance(block, dict) and block.get("id") is not None:
            by_id[str(block.get("id"))] = block
    clips = []
    for row in results or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("result") or "").strip().lower() != "wrong":
            continue
        if video_index is not None:
            try:
                if int(row.get("video_index") or 0) != int(video_index):
                    continue
            except (TypeError, ValueError):
                continue
        block = by_id.get(str(row.get("id") or ""))
        start = _as_float(row.get("video_start_sec"))
        if start is None and block:
            start = _as_float(block.get("video_start_sec"))
        duration = _as_float(row.get("session_duration"))
        if duration is None and block:
            duration = _as_float(block.get("on_sec") or block.get("planned_on_sec"))
        source = str((row.get("wrong_clip") or (block or {}).get("wrong_clip") or "")).strip()
        if source and not os.path.isfile(source):
            source = ""
        if not source and (start is None or duration is None):
            continue
        fid = str(row.get("field") or (block or {}).get("field") or "A").upper()[:1]
        if fid not in ("A", "B"):
            fid = "A"
        clips.append({
            "id": str(row.get("id") or ""),
            "field": fid,
            "start": float(start or 0.0),
            "duration": float(duration or 0.0),
            "source": source,
        })
    clips.sort(key=lambda item: (item["start"], item["id"]))
    return clips


def cycle_seconds(clips) -> float:
    """Playback length of the wrong slices plus a 1 second gap after each."""
    if not clips:
        return 0.0
    return sum(float(item["duration"]) for item in clips) + WRONG_GAP_SEC * len(clips)


def screens_3_and_4(field_id: str):
    """One box per screen. Screen 3 and screen 4 do not share a picture."""
    from simust_display_layout import (
        COACH_BAND_HEIGHT,
        COACH_BAND_WIDTH,
        DISPLAY_SLICE_ORDER,
        slice_x_span,
    )
    fid = "B" if str(field_id or "A").upper().startswith("B") else "A"
    ids = ("B3", "B4") if fid == "B" else ("A3", "A4")
    height = _even(COACH_BAND_HEIGHT)
    boxes = []
    for screen_id in ids:
        index = DISPLAY_SLICE_ORDER.index(screen_id)
        x0, x1 = slice_x_span(index)
        boxes.append({
            "field": fid,
            "screen": screen_id,
            "x": int(x0),
            "width": _even(int(x1) - int(x0)),
            "height": height,
            "band_width": int(COACH_BAND_WIDTH),
        })
    return boxes


def _ffmpeg_bin() -> Optional[str]:
    for path in (
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        "ffmpeg",
    ):
        try:
            subprocess.run([path, "-version"], capture_output=True, timeout=5)
            return path
        except Exception:
            continue
    return None


def _run_ffmpeg(cmd, timeout=180) -> bool:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        logger.warning("ffmpeg failed to start: %s", exc)
        return False
    if result.returncode != 0:
        logger.warning("ffmpeg failed: %s", (result.stderr or "")[-800:])
        return False
    return True


def _load_blocks(field_dir: str):
    path = os.path.join(field_dir, "recognition.json")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return []
    return data if isinstance(data, list) else []


def _even(value: int) -> int:
    value = int(value)
    if value % 2:
        value -= 1
    return max(2, value)


def write_frames_clip(path: str, frames, fps: float = REEL_FPS) -> bool:
    """Write one action's frames to an mp4. Frames are BGR images of one field."""
    if not frames:
        return False
    ffmpeg = _ffmpeg_bin()
    if not ffmpeg:
        return False
    first = frames[0]
    height, width = first.shape[:2]
    width = _even(width)
    height = _even(height)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    cmd = [
        ffmpeg, "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{width}x{height}",
        "-r", str(int(fps)),
        "-i", "-",
        "-an",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        path,
    ]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except Exception as exc:
        logger.warning("Could not start clip writer: %s", exc)
        return False
    try:
        for frame in frames:
            if frame.shape[1] != width or frame.shape[0] != height:
                frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        proc.wait(timeout=60)
    except Exception as exc:
        logger.warning("Clip write failed: %s", exc)
        try:
            proc.kill()
        except Exception:
            pass
        return False
    return os.path.isfile(path) and os.path.getsize(path) > 0


def _concat_scaled(ffmpeg, inputs, width, height, out_path) -> bool:
    """inputs are file paths or None for a 1 second black gap."""
    cmd = [ffmpeg, "-y"]
    file_inputs = [item for item in inputs if item]
    for path in file_inputs:
        cmd += ["-i", path]
    parts = []
    labels = []
    file_index = 0
    for item in inputs:
        label = f"p{len(labels)}"
        if item:
            parts.append(
                f"[{file_index}:v]scale={width}:{height}:flags=fast_bilinear,"
                f"setsar=1,fps={REEL_FPS}[{label}]"
            )
            file_index += 1
        else:
            parts.append(
                f"color=c=0x0a0c12:s={width}x{height}:r={REEL_FPS}:d={WRONG_GAP_SEC:.3f}[{label}]"
            )
        labels.append(f"[{label}]")
    parts.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0[v]")
    cmd += [
        "-filter_complex", ";".join(parts),
        "-map", "[v]", "-an",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-r", str(REEL_FPS),
        out_path,
    ]
    return _run_ffmpeg(cmd, timeout=180) and os.path.isfile(out_path) and os.path.getsize(out_path) > 0


def _build_field_reel(ffmpeg, recording, clips, box, out_path) -> bool:
    """One field's wrong slices, each followed by one second of black."""
    width = _even(box["width"])
    height = _even(box["height"])
    if clips and all(clip.get("source") for clip in clips):
        sequence = []
        for clip in clips:
            sequence.append(clip["source"])
            sequence.append(None)
        return _concat_scaled(ffmpeg, sequence, width, height, out_path)

    crop_x = "0" if box["field"] == "A" else "iw/2"
    if len(clips) == 1:
        parts = []
        sources = ["0:v"]
    else:
        parts = ["[0:v]split=" + str(len(clips)) + "".join(f"[s{index}]" for index in range(len(clips)))]
        sources = [f"s{index}" for index in range(len(clips))]
    labels = []
    for index, clip in enumerate(clips):
        start = float(clip["start"])
        end = start + float(clip["duration"])
        parts.append(
            f"[{sources[index]}]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS,"
            f"crop=iw/2:ih:{crop_x}:0,scale={width}:{height}:flags=fast_bilinear,"
            f"setsar=1,fps={REEL_FPS}[c{index}]"
        )
        parts.append(
            f"color=c=0x0a0c12:s={width}x{height}:r={REEL_FPS}:d={WRONG_GAP_SEC:.3f}[g{index}]"
        )
        labels.append(f"[c{index}]")
        labels.append(f"[g{index}]")
    parts.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0[v]")
    cmd = [
        ffmpeg, "-y",
        "-i", recording,
        "-filter_complex", ";".join(parts),
        "-map", "[v]", "-an",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-r", str(REEL_FPS),
        out_path,
    ]
    return _run_ffmpeg(cmd, timeout=180) and os.path.isfile(out_path) and os.path.getsize(out_path) > 0


def build_wrong_results_background(session_root, field_jobs, video_index, output_path=None):
    """Full results-band video: each wrong slice whole on screen 3 and on screen 4.

    Returns {"path", "duration", "fps"} or None when this test has no Wrong
    action that can be cut from the session video.
    """
    recording = os.path.join(session_root, "realtime_recording.mp4")
    ffmpeg = _ffmpeg_bin()
    if not ffmpeg:
        logger.warning("ffmpeg was not found; wrong-action slices were not built")
        return None

    by_field = {}
    for fid, fdir, rows in field_jobs or []:
        clips = wrong_clip_windows(rows, _load_blocks(fdir), video_index)
        field_clips = [clip for clip in clips if clip["field"] == str(fid).upper()[:1]]
        if field_clips:
            by_field[str(fid).upper()[:1]] = field_clips
    if not by_field:
        return None
    needs_recording = any(
        not clip.get("source")
        for clips in by_field.values()
        for clip in clips
    )
    if needs_recording and not os.path.isfile(recording):
        logger.info("No session video at %s; per-video results stay on the static background", recording)
        return None

    duration = max(MIN_RESULTS_SEC, max(cycle_seconds(clips) for clips in by_field.values()))
    work = os.path.join(session_root, "wrong_clips")
    os.makedirs(work, exist_ok=True)
    if not output_path:
        output_path = os.path.join(work, f"wrong_screens_3_4_video_{int(video_index)}.mp4")

    placements = []
    for fid, clips in by_field.items():
        boxes = screens_3_and_4(fid)
        reel_path = os.path.join(work, f"field_{fid}_video_{int(video_index)}.mp4")
        if not _build_field_reel(ffmpeg, recording, clips, boxes[0], reel_path):
            logger.warning("Could not cut Field %s wrong slices for video %s", fid, video_index)
            continue
        for box in boxes:
            placements.append((box, reel_path))
    if not placements:
        return None

    band_w = placements[0][0]["band_width"]
    band_h = placements[0][0]["height"]
    cmd = [
        ffmpeg, "-y", "-f", "lavfi",
        "-i", f"color=c=0x0a0c12:s={band_w}x{band_h}:r={REEL_FPS}:d={duration:.3f}",
    ]
    for _box, path in placements:
        cmd += ["-stream_loop", "-1", "-i", path]
    filters = []
    prev = "0:v"
    for index, (box, _path) in enumerate(placements):
        src = index + 1
        scaled = f"s{index}"
        nxt = f"o{index}"
        filters.append(
            f"[{src}:v]scale={box['width']}:{box['height']}:flags=fast_bilinear,setsar=1[{scaled}]"
        )
        filters.append(f"[{prev}][{scaled}]overlay=x={box['x']}:y=0:shortest=1[{nxt}]")
        prev = nxt
    filters.append(f"[{prev}]format=yuv420p[v]")
    cmd += [
        "-filter_complex", ";".join(filters),
        "-map", "[v]", "-an",
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-r", str(REEL_FPS),
        output_path,
    ]
    if not _run_ffmpeg(cmd, timeout=180):
        return None
    logger.info(
        "Wrong-action reel for video %s on screens 3 and 4 (%.1fs, fields %s)",
        video_index,
        duration,
        ",".join(sorted(by_field)),
    )
    return {"path": output_path, "duration": duration, "fps": REEL_FPS}
