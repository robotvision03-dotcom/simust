"""Simulator: walk the calibrated 0.9 m segment exactly 4 times → expect 3.6 m (homography)."""

import math
import os
import sys
import types
import unittest

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

import simust_homography as homo  # noqa: E402

CAL_FILE = os.path.join(ROOT, "homography_calibration.json")
FALLBACK = 0.0259

# Calibration pair 1 (camera-1): exactly 0.9 m
POINT_A = (25.3, 197.5)
POINT_B = (49.3, 176.5)
SEGMENT_M = 0.9
TRIPS = 4
EXPECTED_M = SEGMENT_M * TRIPS  # 3.6


def _samples_along(a, b, steps=8):
    """Inclusive samples from a to b (no overshoot)."""
    out = []
    for i in range(steps + 1):
        f = i / float(steps)
        out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
    return out


def _four_legs_between_points(a, b, steps_per_leg=10):
    """Move only between A and B, four times: A→B→A→B (four legs, no extra motion).

    Total ground truth = 4 × 0.9 m = 3.6 m.
    """
    positions = []
    t = 0.0
    # legs: A→B, B→A, A→B, B→A
    sequence = [(a, b), (b, a), (a, b), (b, a)]
    for start, end in sequence:
        pts = _samples_along(start, end, steps_per_leg)
        # skip duplicate junction point when chaining legs
        if positions:
            pts = pts[1:]
        for u, v in pts:
            positions.append((t, u, v))
            t += 1.0
    return positions


class FourTripHomographyAccuracyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(CAL_FILE):
            raise unittest.SkipTest("homography_calibration.json is missing")
        homo.CALIBRATION_FILE = CAL_FILE
        homo._cache = None
        homo._cache_mtime = 0.0
        cls.store = homo.load_store()
        rec = homo.camera_record(cls.store, "camera-1")
        if not homo.is_calibrated(rec):
            raise unittest.SkipTest("camera-1 is not calibrated")
        cls.rec = rec

    def test_single_leg_is_0_9m(self):
        a = POINT_A
        b = POINT_B
        wa = homo.pixel_to_world(a[0], a[1], self.rec["H"])
        wb = homo.pixel_to_world(b[0], b[1], self.rec["H"])
        dist = math.hypot(wb[0] - wa[0], wb[1] - wa[1])
        print(f"\nSingle A->B: H={dist:.4f} m (expect {SEGMENT_M})")
        self.assertAlmostEqual(dist, SEGMENT_M, delta=0.05)

    def test_simulator_four_trips_equals_3_6m(self):
        """Simulator-mode hip path: only A<->B, four legs -> 3.6 m."""
        positions = _four_legs_between_points(POINT_A, POINT_B, steps_per_leg=10)
        ax, ay = POINT_A
        bx, by = POINT_B
        for _, u, v in positions:
            dx, dy = bx - ax, by - ay
            denom = dx * dx + dy * dy
            t = ((u - ax) * dx + (v - ay) * dy) / denom
            self.assertGreaterEqual(t, -1e-6)
            self.assertLessEqual(t, 1.0 + 1e-6)
            pu, pv = ax + t * dx, ay + t * dy
            self.assertLess(math.hypot(u - pu, v - pv), 0.05)

        homo_m = homo.path_distance_meters(
            positions, store=self.store, fallback_m_per_px=FALLBACK
        )
        ppm_m = 0.0
        for i in range(1, len(positions)):
            _, x1, y1 = positions[i - 1]
            _, x2, y2 = positions[i]
            ppm_m += math.hypot(x2 - x1, y2 - y1) * FALLBACK

        print(
            f"\n4x A<->B simulator path: samples={len(positions)}  "
            f"H={homo_m:.4f} m  ppm={ppm_m:.4f} m  expect={EXPECTED_M:.1f} m"
        )
        self.assertAlmostEqual(homo_m, EXPECTED_M, delta=0.08)
        self.assertLess(abs(homo_m - EXPECTED_M), abs(ppm_m - EXPECTED_M))


if __name__ == "__main__":
    unittest.main(verbosity=2)
