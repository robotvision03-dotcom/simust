"""Replay a real SF-60N (or any) session from recognition.json footprints.

Ball (`b`), player (`p`), and hip (`hp`) are copied from the recording.
Nothing is synthesized from Correct/Miss/Late rules.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

REC_W = 1280.0
REC_H = 360.0


def default_sf60n_folder() -> str:
    env = os.environ.get("SIMUST_REPLAY_RECOGNITION", "").strip()
    if env and os.path.isdir(env):
        return env
    if env and os.path.isfile(env):
        return os.path.dirname(env)
    return os.path.join(
        os.path.expanduser("~"),
        "Documents",
        "simust_realtime_recordings",
        "realtime_20260907_133952_614",
    )


def recognition_path(folder: Optional[str] = None) -> str:
    root = folder or default_sf60n_folder()
    if os.path.isfile(root) and root.endswith(".json"):
        return root
    return os.path.join(root, "recognition.json")


def load_blocks(folder: Optional[str] = None) -> List[dict]:
    path = recognition_path(folder)
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def is_action_block(block: dict) -> bool:
    action = str(block.get("action") or "").upper()
    ident = str(block.get("id") or "")
    return action in ("PASS", "TARGET", "PRESS", "GOAL") and ident.startswith("S")


def _as_xy(pos) -> Optional[Tuple[int, int]]:
    if not isinstance(pos, (list, tuple)) or len(pos) < 2:
        return None
    try:
        return int(float(pos[0])), int(float(pos[1]))
    except (TypeError, ValueError):
        return None


def detections_from_entry(entry: dict, frame_w: int, frame_h: int) -> Tuple[list, list, Tuple[Optional[float], Optional[float]]]:
    """Copy one recognition frame into detector-shaped ball/player/hip objects."""
    sx = frame_w / REC_W
    sy = frame_h / REC_H
    balls = []
    for pos in entry.get("b") or []:
        xy = _as_xy(pos)
        if xy is None:
            continue
        cx, cy = int(xy[0] * sx), int(xy[1] * sy)
        balls.append({
            "center": [cx, cy],
            "bbox": [cx - 8, cy - 8, cx + 8, cy + 8],
            "confidence": 1.0,
            "replayed": True,
        })
    players = []
    for pos in entry.get("p") or []:
        xy = _as_xy(pos)
        if xy is None:
            continue
        cx, cy = int(xy[0] * sx), int(xy[1] * sy)
        players.append({
            "center": [cx, cy],
            "bbox": [cx - 18, cy - 50, cx + 18, cy + 8],
            "confidence": 1.0,
            "replayed": True,
        })
    hip: Tuple[Optional[float], Optional[float]] = (None, None)
    hp = entry.get("hp")
    if isinstance(hp, (list, tuple)) and len(hp) == 2 and hp[0] is not None and hp[1] is not None:
        try:
            hip = (float(hp[0]) * sx, float(hp[1]) * sy)
        except (TypeError, ValueError):
            hip = (None, None)
    return balls, players, hip


class RecognitionReplay:
    """Walk recognition.json in time order and emit the recorded detections."""

    def __init__(self, blocks: List[dict]):
        self.blocks = blocks
        self.block_index = 0
        self.frame_index = 0
        self.current_action_id = ""
        self.last_balls: list = []
        self.last_players: list = []
        self.last_hip: Tuple[Optional[float], Optional[float]] = (None, None)

    @classmethod
    def from_folder(cls, folder: Optional[str] = None) -> "RecognitionReplay":
        return cls(load_blocks(folder))

    def current_block(self) -> Optional[dict]:
        if 0 <= self.block_index < len(self.blocks):
            return self.blocks[self.block_index]
        return None

    def current_saved_result(self) -> str:
        return "replay"

    def begin_action(self, action: str, screens: List[str], action_id: Optional[str] = None) -> bool:
        action = (action or "").upper()
        want = [str(s) for s in (screens or [])]
        start = self.block_index
        for i in range(start, len(self.blocks)):
            block = self.blocks[i]
            if not is_action_block(block):
                continue
            if action_id and block.get("id") != action_id:
                continue
            if str(block.get("action") or "").upper() != action:
                continue
            if want and [str(s) for s in (block.get("screens") or [])] != want:
                continue
            self.block_index = i
            self.frame_index = 0
            self.current_action_id = str(block.get("id") or "")
            return True
        return False

    def begin_between(self) -> None:
        nxt = self.block_index + 1
        if nxt < len(self.blocks) and str(self.blocks[nxt].get("action") or "").upper() == "BETWEEN_SESSIONS":
            self.block_index = nxt
            self.frame_index = 0

    def step(self, frame_w: int, frame_h: int) -> Tuple[list, list, Tuple[Optional[float], Optional[float]]]:
        block = self.current_block()
        data = (block or {}).get("data") or []
        if self.frame_index >= len(data):
            return self.last_balls, self.last_players, self.last_hip
        entry = data[self.frame_index]
        self.frame_index += 1
        balls, players, hip = detections_from_entry(entry, frame_w, frame_h)
        self.last_balls, self.last_players, self.last_hip = balls, players, hip
        return balls, players, hip

    def remaining_frames(self) -> int:
        block = self.current_block()
        data = (block or {}).get("data") or []
        return max(0, len(data) - self.frame_index)

    def sample_at(self, elapsed_s: float, frame_w: int, frame_h: int):
        """Pick the recorded frame whose t matches elapsed session time."""
        block = self.current_block()
        data = (block or {}).get("data") or []
        if not data:
            return self.last_balls, self.last_players, self.last_hip
        elapsed_s = max(0.0, float(elapsed_s or 0.0))
        chosen = data[0]
        for entry in data:
            t = float(entry.get("t") or 0.0)
            if t <= elapsed_s + 1e-6:
                chosen = entry
            else:
                break
        balls, players, hip = detections_from_entry(chosen, frame_w, frame_h)
        self.last_balls, self.last_players, self.last_hip = balls, players, hip
        return balls, players, hip


def score_recognition(folder: Optional[str] = None) -> List[Dict[str, Any]]:
    """Score every recorded action with the live analyzer, using copied footprints."""
    import simust_realtime as rt

    blocks = load_blocks(folder)
    rows = []
    for index, block in enumerate(blocks):
        if not is_action_block(block):
            continue
        action = str(block.get("action") or "").upper()
        scored = rt.analyze_action_with_context(block, rt.GOAL_LINES, action, blocks, index)
        rows.append({
            "id": block.get("id"),
            "action": action,
            "screens": list(block.get("screens") or []),
            "result": scored.get("Result"),
            "winning_screen": scored.get("Winning Screen"),
            "min_dist": scored.get("Min Distance (px)"),
            "finishing_time": scored.get("Time of Min (s)"),
            "ae": scored.get("AE"),
            "movement": scored.get("Movement (px)"),
            "direction": scored.get("Direction"),
        })
    return rows


def hip_path(folder: Optional[str] = None) -> List[Tuple[float, float, float]]:
    """Absolute-time hip samples copied from recognition (player displacement)."""
    blocks = load_blocks(folder)
    path = []
    t0 = None
    for block in blocks:
        start_str = block.get("start_time")
        if not start_str:
            continue
        try:
            start = datetime.strptime(start_str, "%H:%M:%S.%f")
        except ValueError:
            continue
        if t0 is None:
            t0 = start
        for entry in block.get("data") or []:
            hp = entry.get("hp")
            if not (isinstance(hp, (list, tuple)) and len(hp) == 2 and hp[0] is not None and hp[1] is not None):
                continue
            t = (start - t0).total_seconds() + float(entry.get("t") or 0.0)
            path.append((t, float(hp[0]), float(hp[1])))
    return path
