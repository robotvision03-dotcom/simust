"""SF-60N simulator: walk the calibrated 0.9 m segment 4 times on a realtime video and check 3.6 m."""

from __future__ import annotations

import math
import os
import sys
import types
import unittest
from datetime import datetime

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

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import simust_homography as homo  # noqa: E402
import simust_realtime as rt  # noqa: E402

CAL_FILE = os.path.join(ROOT, "homography_calibration.json")
FALLBACK = 0.0259
POINT_A = (25.3, 197.5)
POINT_B = (49.3, 176.5)
SEGMENT_M = 0.9
EXPECTED_M = 3.6
W, H = 1280, 360
FPS = 25

SF60N_VIDEO = os.path.join(
    "C:/Users/siama/Documents/simust_player",
    "L00-Foundation-Challenge",
    "SF-60N",
    "pass.mp4",
)
RECORDINGS_DIR = os.path.join(
    os.path.expanduser("~"), "Documents", "simust_realtime_recordings"
)


def _samples_along(a, b, steps=10):
    out = []
    for i in range(steps + 1):
        f = i / float(steps)
        out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
    return out


def _four_legs(a, b, steps_per_leg=10):
    positions = []
    for start, end in ((a, b), (b, a), (a, b), (b, a)):
        pts = _samples_along(start, end, steps_per_leg)
        if positions:
            pts = pts[1:]
        positions.extend(pts)
    return positions


def _find_sf60n_realtime_background():
    """Prefer an existing realtime_recording.avi; else first frame from SF-60N playlist."""
    if os.path.isdir(RECORDINGS_DIR):
        candidates = []
        for name in sorted(os.listdir(RECORDINGS_DIR), reverse=True):
            avi = os.path.join(RECORDINGS_DIR, name, "realtime_recording.avi")
            if os.path.isfile(avi):
                candidates.append(avi)
        for avi in candidates[:12]:
            cap = cv2.VideoCapture(avi)
            ok, frame = cap.read()
            cap.release()
            if ok and frame is not None and frame.shape[0] >= 300:
                return frame, avi
    if os.path.isfile(SF60N_VIDEO):
        cap = cv2.VideoCapture(SF60N_VIDEO)
        ok, frame = cap.read()
        cap.release()
        if ok and frame is not None:
            return cv2.resize(frame, (W, H)), SF60N_VIDEO
    return np.zeros((H, W, 3), dtype=np.uint8), None


def _player_blob(hip_xy):
    """Build ArenaSimulator-style player/hip at stitch coordinates."""
    hx, hy = float(hip_xy[0]), float(hip_xy[1])
    # ArenaSimulator: hip is near top of bbox; invert that for draw.
    px_s = int(hx)
    py_s = int(hy + 28)
    bw, bh = 36, 88
    x1 = max(0, px_s - bw // 2)
    y1 = max(0, py_s - bh)
    x2 = min(W - 1, px_s + bw // 2)
    y2 = min(H - 1, py_s + 6)
    players = [{
        "center": [px_s, py_s - bh // 3],
        "bbox": [x1, y1, x2, y2],
        "confidence": 1.0,
        "simulated": True,
    }]
    balls = [{
        "center": [px_s + 18, py_s - 10],
        "bbox": [px_s + 8, py_s - 20, px_s + 28, py_s],
        "confidence": 1.0,
        "simulated": True,
    }]
    return balls, players, (hx, hy)


@unittest.skipUnless(os.path.isfile(CAL_FILE), "homography_calibration.json missing")
class Sf60nSimulatorPathVideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        homo.CALIBRATION_FILE = CAL_FILE
        homo._cache = None
        homo._cache_mtime = 0.0
        cls.store = homo.load_store()
        rec = homo.camera_record(cls.store, "camera-1")
        if not homo.is_calibrated(rec):
            raise unittest.SkipTest("camera-1 not calibrated")

    def test_sf60n_simulator_video_four_legs_3_6m(self):
        bg, src = _find_sf60n_realtime_background()
        bg = cv2.resize(bg, (W, H))
        path = _four_legs(POINT_A, POINT_B, steps_per_leg=12)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = os.path.join(RECORDINGS_DIR, f"homo_sf60n_path_{stamp}")
        os.makedirs(out_dir, exist_ok=True)
        out_avi = os.path.join(out_dir, "realtime_recording.avi")

        saver = rt.VideoSaver()
        self.assertTrue(saver.start(out_avi, W, H, FPS))

        sim = rt.ArenaSimulator()
        sim.active = True
        sim.intended = "correct"
        sim.action = "PRESS"
        hip_samples = []
        trail = []

        # Hold a few frames at start, then walk, then hold.
        for _ in range(8):
            frame = bg.copy()
            balls, players, hip = _player_blob(POINT_A)
            frame = sim.draw_on_frame(frame, balls, players)
            cv2.putText(
                frame,
                "SF-60N SIM  path A<->B x4  expect 3.6m",
                (12, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 255),
                2,
            )
            saver.write_frame(frame)

        for i, (u, v) in enumerate(path):
            # Interpolate extra frames between sparse samples for smooth video.
            if i == 0:
                dens = [(u, v)]
            else:
                pu, pv = path[i - 1]
                dens = []
                for k in range(1, 4):
                    f = k / 3.0
                    dens.append((pu + (u - pu) * f, pv + (v - pv) * f))
            for hu, hv in dens:
                frame = bg.copy()
                # Draw travel segment + trail
                cv2.line(
                    frame,
                    (int(POINT_A[0]), int(POINT_A[1])),
                    (int(POINT_B[0]), int(POINT_B[1])),
                    (0, 200, 255),
                    2,
                )
                trail.append((int(hu), int(hv)))
                for j in range(1, len(trail)):
                    cv2.line(frame, trail[j - 1], trail[j], (0, 255, 180), 1)
                balls, players, hip = _player_blob((hu, hv))
                frame = sim.draw_on_frame(frame, balls, players)
                hip_samples.append((len(hip_samples) / float(FPS), hip[0], hip[1]))
                metres_so_far = homo.path_distance_meters(
                    hip_samples, store=self.store, fallback_m_per_px=FALLBACK
                )
                cv2.putText(
                    frame,
                    f"SF-60N SIM  H={metres_so_far:.2f}m / 3.60m",
                    (12, 28),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 255, 255),
                    2,
                )
                cv2.circle(frame, (int(POINT_A[0]), int(POINT_A[1])), 5, (0, 255, 0), -1)
                cv2.circle(frame, (int(POINT_B[0]), int(POINT_B[1])), 5, (0, 0, 255), -1)
                saver.write_frame(frame)

        for _ in range(8):
            frame = bg.copy()
            balls, players, hip = _player_blob(path[-1])
            frame = sim.draw_on_frame(frame, balls, players)
            cv2.putText(
                frame,
                "SF-60N SIM  path done",
                (12, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 255),
                2,
            )
            saver.write_frame(frame)

        saver.stop()
        self.assertTrue(os.path.isfile(out_avi))
        self.assertGreater(os.path.getsize(out_avi), 10_000)

        homo_m = homo.path_distance_meters(
            hip_samples, store=self.store, fallback_m_per_px=FALLBACK
        )
        ppm_m = 0.0
        for i in range(1, len(hip_samples)):
            _, x1, y1 = hip_samples[i - 1]
            _, x2, y2 = hip_samples[i]
            ppm_m += math.hypot(x2 - x1, y2 - y1) * FALLBACK

        meta = {
            "background_source": src,
            "path": {"a": POINT_A, "b": POINT_B, "segment_m": SEGMENT_M, "legs": 4},
            "homography_m": round(homo_m, 4),
            "ppm_m": round(ppm_m, 4),
            "expected_m": EXPECTED_M,
            "video": out_avi,
            "frames": saver.frame_count,
            "hip_samples": len(hip_samples),
        }
        meta_path = os.path.join(out_dir, "homo_path_result.json")
        import json

        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump(meta, handle, indent=2)

        print("\nSF-60N simulator path video:", out_avi)
        print(f"  background: {src}")
        print(f"  H={homo_m:.4f} m  ppm={ppm_m:.4f} m  expect={EXPECTED_M:.1f} m")
        print(f"  frames={saver.frame_count}  hips={len(hip_samples)}")

        self.assertAlmostEqual(homo_m, EXPECTED_M, delta=0.12)
        self.assertLess(abs(homo_m - EXPECTED_M), abs(ppm_m - EXPECTED_M))


if __name__ == "__main__":
    unittest.main(verbosity=2)
