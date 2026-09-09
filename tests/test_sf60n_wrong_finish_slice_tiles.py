"""SF-60N simulator: Wrong finishing clips integrated into results tiles 14 and 2."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime, timedelta

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

for name in ("ultralytics", "mss"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["ultralytics"].YOLO = object
sys.modules["mss"].mss = lambda *a, **k: None
if "torch" not in sys.modules:
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: False, empty_cache=lambda: None)
    sys.modules["torch"] = torch

import app  # noqa: E402
import simust_realtime as rt  # noqa: E402

SLICE_NUMBERS = [12, 13, 14, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
WIDTH, HEIGHT = 3712, 512
TILE_W = WIDTH // len(SLICE_NUMBERS)
IDX_14 = SLICE_NUMBERS.index(14)
IDX_2 = SLICE_NUMBERS.index(2)
IDX_12 = SLICE_NUMBERS.index(12)


def _tile(frame, idx):
    x0 = idx * TILE_W
    return frame[:, x0 : x0 + TILE_W]


def _is_field_tile(tile, min_green=70.0, min_std=20.0):
    g = float(tile[:, :, 1].mean())
    r = float(tile[:, :, 2].mean())
    b = float(tile[:, :, 0].mean())
    return g >= min_green and g > r + 8 and g > b + 8 and float(tile.std()) >= min_std


def _write_sim_recording(path, fps=25, seconds=8):
    sim = rt.ArenaSimulator()
    sim.outcome_index = 3
    sim.start_action("PASS", ["2", "7"])
    assert sim.intended == "wrong", sim.intended

    w, h = 1280, 360
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    assert writer.isOpened(), path
    n = int(seconds * fps)
    wall0 = time.time()
    for i in range(n):
        now = wall0 + i / float(fps)
        sim.start_ts = now - min(2.5, i / float(fps))
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        frame[:, :] = (40, 140, 40)
        balls, players, _hip = sim.step(w, h)
        frame = sim.draw_on_frame(frame, balls, players)
        writer.write(frame)
    writer.release()
    return sim


class Sf60nWrongFinishSliceTilesTests(unittest.TestCase):
    def test_wrong_finish_integrated_in_tiles_14_and_2(self):
        start = datetime(2026, 9, 9, 16, 10, 0, 250000)
        stamp = start.strftime("%Y%m%d_%H%M%S_") + f"{start.microsecond // 1000:03d}"
        root = tempfile.mkdtemp(prefix="sf60n_wrong_slice_")
        folder = os.path.join(root, f"realtime_{stamp}")
        os.makedirs(folder, exist_ok=True)

        avi = os.path.join(folder, "realtime_recording.avi")
        _write_sim_recording(avi, fps=25, seconds=8)

        s1_start = start.strftime("%H:%M:%S.%f")[:-3]
        s1_end = (start + timedelta(seconds=1.2)).strftime("%H:%M:%S.%f")[:-3]
        wrong_start = (start + timedelta(seconds=2.0)).strftime("%H:%M:%S.%f")[:-3]
        wrong_end = (start + timedelta(seconds=3.5)).strftime("%H:%M:%S.%f")[:-3]
        blocks = [
            {
                "id": "S1",
                "action": "PASS",
                "screens": ["3", "6"],
                "start_time": s1_start,
                "end_time": s1_end,
                "data": [{"t": 0.0, "b": [[100, 100]], "hp": [[110, 120]]}],
            },
            {
                "id": "S4",
                "action": "PASS",
                "screens": ["2", "7"],
                "start_time": wrong_start,
                "end_time": wrong_end,
                "data": [{"t": 0.0, "b": [[200, 180]], "hp": [[210, 190]]}],
            },
        ]
        results = [
            {
                "id": "S1",
                "action": "PASS",
                "result": "Correct",
                "video_index": 1,
                "ae": 55,
                "total_distance": 12.0,
                "finishing_time": 0.55,
                "session_duration": 1.2,
            },
            {
                "id": "S4",
                "action": "PASS",
                "result": "Wrong",
                "video_index": 1,
                "ae": 0,
                "total_distance": 12.0,
            },
        ]
        with open(os.path.join(folder, "recognition.json"), "w", encoding="utf-8") as f:
            json.dump(blocks, f)
        with open(os.path.join(folder, "results.json"), "w", encoding="utf-8") as f:
            json.dump(results, f)

        out = os.path.join(folder, "results_video_1.mp4")
        ok = app.generate_results_video_from_results(
            results,
            out,
            duration_seconds=6,
            is_final=False,
            session_folder=folder,
            video_index=1,
        )
        self.assertTrue(ok)
        self.assertTrue(os.path.isfile(out))
        self.assertEqual(os.path.dirname(out), folder)

        cap = cv2.VideoCapture(out)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.assertGreater(n, 20)
        # Mid-play: rings still on 12, wrong clips on 14 & 2
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, n // 2))
        ok_mid, mid = cap.read()
        cap.release()
        self.assertTrue(ok_mid)
        self.assertTrue(
            _is_field_tile(_tile(mid, IDX_14)),
            msg=f"tile14 mean={_tile(mid, IDX_14).mean(axis=(0, 1))}",
        )
        self.assertTrue(
            _is_field_tile(_tile(mid, IDX_2)),
            msg=f"tile2 mean={_tile(mid, IDX_2).mean(axis=(0, 1))}",
        )
        # Metric tile 12 should still be ring HUD (not full green field)
        self.assertFalse(_is_field_tile(_tile(mid, IDX_12), min_green=90))


class FlushBeforeResultsTests(unittest.TestCase):
    def test_wait_ready_when_results_already_complete(self):
        start = datetime(2026, 9, 9, 16, 20, 0, 0)
        stamp = start.strftime("%Y%m%d_%H%M%S_") + "000"
        root = tempfile.mkdtemp(prefix="flush_ready_")
        folder = os.path.join(root, f"realtime_{stamp}")
        os.makedirs(folder, exist_ok=True)
        blocks = [
            {"id": "S1", "action": "PASS", "screens": ["2"], "start_time": "16:20:00.000", "end_time": "16:20:01.000", "data": []},
            {"id": "S4", "action": "PASS", "screens": ["2"], "start_time": "16:20:02.000", "end_time": "16:20:03.000", "data": []},
        ]
        results = [
            {"id": "S1", "action": "PASS", "result": "Correct", "video_index": 1},
            {"id": "S4", "action": "PASS", "result": "Wrong", "video_index": 1},
        ]
        with open(os.path.join(folder, "recognition.json"), "w", encoding="utf-8") as f:
            json.dump(blocks, f)
        with open(os.path.join(folder, "results.json"), "w", encoding="utf-8") as f:
            json.dump(results, f)
        info = app.request_flush_pending_analysis_and_wait(folder, timeout_s=0.6)
        self.assertTrue(info["ready"])
        self.assertEqual(info["missing"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
