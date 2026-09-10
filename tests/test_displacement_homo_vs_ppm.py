"""Compare ground-plane homography vs old constant pixel→metre scale on SF-60N.

Ground truth = measured court pair lengths used for calibration.
Old method   = pixel path length * 0.0259 m/px (uniform scale).
New method   = path_distance_meters via fitted H.
"""

from __future__ import annotations

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

try:
    import cv2  # noqa: F401
    import numpy as np  # noqa: F401
    HAS_CV2 = True
except Exception:
    HAS_CV2 = False

import simust_homography as homo  # noqa: E402
import simust_realtime as rt  # noqa: E402

FALLBACK = 0.0259
STITCH_W, STITCH_H = 1280, 360

# Lab court segments previously used for camera-1 calibration (metres are ground truth).
LAB_PAIRS = [
    {"a": [41.3, 187.5], "b": [527.3, 137.5], "distance": 11.87},
    {"a": [131.3, 133.5], "b": [206.3, 95.5], "distance": 7.2},
    {"a": [118.3, 136.5], "b": [610.3, 183.5], "distance": 11.87},
    {"a": [130.3, 131.5], "b": [517.3, 134.5], "distance": 10.9},
]


def _ppm_distance(a, b) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1]) * FALLBACK


def _sample_pair(pair, n=9):
    au, av = pair["a"]
    bu, bv = pair["b"]
    out = []
    for i in range(n):
        f = i / float(n - 1)
        out.append((i, au + (bu - au) * f, av + (bv - av) * f))
    return out


def _ppm_path(samples) -> float:
    total = 0.0
    for i in range(1, len(samples)):
        _, x1, y1 = samples[i - 1]
        _, x2, y2 = samples[i]
        total += math.hypot(x2 - x1, y2 - y1)
    return total * FALLBACK


@unittest.skipUnless(HAS_CV2, "OpenCV required")
class HomographyVsPpmAccuracyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        computed = homo.compute_homography_from_pairs(LAB_PAIRS)
        cls.H = computed["H"]
        cls.rmse = float(computed["rmse_m"])
        cls.store = {
            "cameras": {
                "camera-1": {
                    "calibrated": True,
                    "H": cls.H,
                    "image_width": 640,
                    "image_height": 360,
                    "pairs": LAB_PAIRS,
                    "rmse_m": cls.rmse,
                }
                # camera-8 intentionally missing — matches common lab state
            }
        }

    def test_calibration_rmse_is_usable(self):
        # Homography fit residual on the measured pairs.
        self.assertLess(self.rmse, 3.0)
        self.assertLess(self.rmse, 1.5)  # prefer tighter fit for displacement

    def test_pair_lengths_homography_beats_ppm(self):
        rows = []
        for pair in LAB_PAIRS:
            truth = pair["distance"]
            a, b = pair["a"], pair["b"]
            wa = homo.pixel_to_world(a[0], a[1], self.H)
            wb = homo.pixel_to_world(b[0], b[1], self.H)
            homo_m = math.hypot(wb[0] - wa[0], wb[1] - wa[1])
            ppm_m = _ppm_distance(a, b)
            rows.append(
                {
                    "truth": truth,
                    "homo": homo_m,
                    "ppm": ppm_m,
                    "homo_err_pct": abs(homo_m - truth) / truth * 100.0,
                    "ppm_err_pct": abs(ppm_m - truth) / truth * 100.0,
                    "px": math.hypot(b[0] - a[0], b[1] - a[1]),
                }
            )

        mean_homo = sum(r["homo_err_pct"] for r in rows) / len(rows)
        mean_ppm = sum(r["ppm_err_pct"] for r in rows) / len(rows)
        print("\n=== Calibration pair accuracy (camera-1) ===")
        print(f"Homography fit RMSE: {self.rmse:.3f} m")
        for i, r in enumerate(rows, 1):
            print(
                f"  pair{i}: truth={r['truth']:.2f}m  "
                f"H={r['homo']:.2f}m ({r['homo_err_pct']:.1f}%)  "
                f"ppm={r['ppm']:.2f}m ({r['ppm_err_pct']:.1f}%)  "
                f"px={r['px']:.1f}  implied_m/px={r['truth']/r['px']:.4f}"
            )
        print(f"Mean abs error: homography {mean_homo:.1f}%  vs  ppm {mean_ppm:.1f}%")

        self.assertLess(mean_homo, mean_ppm)
        self.assertLess(mean_homo, 8.0)
        # Constant scale cannot match segments at different depths / angles.
        self.assertGreater(mean_ppm, 15.0)

    def test_sf60n_press_path_both_methods(self):
        sim = rt.ArenaSimulator()
        sim.start_action("PRESS", ["2", "7"])
        sx = STITCH_W / float(rt.SIM_FRAME_WIDTH)
        sy = STITCH_H / float(rt.SIM_FRAME_HEIGHT)
        positions = []
        for i in range(40):
            t = i * 0.05
            _bx, _by, px, py = sim._ball_player_for_outcome(t, sim.start_ts + t)
            px, py = sim._clip(px, py)
            hip = (float(int(px * sx)), float(max(0, int(py * sy) - int(28 * sy))))
            positions.append((t, hip[0], hip[1]))

        homo_m = homo.path_distance_meters(
            positions, store=self.store, fallback_m_per_px=FALLBACK
        )
        ppm_m = _ppm_path(positions)
        xs = [p[1] for p in positions]
        ys = [p[2] for p in positions]
        crossed_split = min(xs) < 640 <= max(xs)
        right_only = min(xs) >= 640

        print("\n=== SF-60N PRESS simulated hip path ===")
        print(f"  samples={len(positions)}  x=[{min(xs):.0f},{max(xs):.0f}]  y=[{min(ys):.0f},{max(ys):.0f}]")
        print(f"  crossed camera split (u=640): {crossed_split}  right-only: {right_only}")
        print(f"  homography displacement: {homo_m:.3f} m")
        print(f"  ppm (0.0259) displacement: {ppm_m:.3f} m")
        if ppm_m > 1e-6:
            print(f"  relative difference: {abs(homo_m - ppm_m) / ppm_m * 100:.1f}%")

        self.assertGreater(homo_m, 0.05)
        self.assertGreater(ppm_m, 0.05)
        self.assertTrue(math.isfinite(homo_m))
        # Methods must disagree when left camera is calibrated — otherwise H unused.
        if not right_only:
            self.assertGreater(abs(homo_m - ppm_m), 0.02)

    def test_right_half_falls_back_when_camera8_missing(self):
        """Issue check: without camera-8 calibration, right-stitch hips use ppm."""
        # Point entirely on camera-8 side of the stitch.
        a = (700.0, 180.0)
        b = (900.0, 160.0)
        samples = [(0, a[0], a[1]), (1, b[0], b[1])]
        mixed = homo.path_distance_meters(samples, store=self.store, fallback_m_per_px=FALLBACK)
        pure_ppm = _ppm_distance(a, b)
        print("\n=== Issue: camera-8 not calibrated ===")
        print(f"  right-half segment H-or-fallback: {mixed:.3f} m  ppm: {pure_ppm:.3f} m")
        self.assertAlmostEqual(mixed, pure_ppm, places=4)

    def test_path_along_known_11_87m_line(self):
        pair = next(p for p in LAB_PAIRS if abs(p["distance"] - 11.87) < 0.02 and p["a"][0] < 50)
        samples = _sample_pair(pair, 9)
        homo_m = homo.path_distance_meters(samples, store=self.store, fallback_m_per_px=FALLBACK)
        ppm_m = _ppm_path(samples)
        print("\n=== Path along measured 11.87 m court line ===")
        print(f"  truth=11.87 m  H={homo_m:.2f} m  ppm={ppm_m:.2f} m")
        self.assertAlmostEqual(homo_m, 11.87, delta=0.5)
        # On this long near-horizontal line ppm is only ~0.8 m off; other pairs are far worse.
        self.assertLess(abs(homo_m - 11.87), abs(ppm_m - 11.87))

    def test_leave_one_out_shows_pair_fit_is_unstable(self):
        """Training RMSE≈0 can still explode on held-out court lines — calibration issue."""
        errors_h = []
        errors_ppm = []
        print("\n=== Leave-one-out (stability) ===")
        for i, hold in enumerate(LAB_PAIRS):
            train = [p for j, p in enumerate(LAB_PAIRS) if j != i]
            try:
                computed = homo.compute_homography_from_pairs(train)
            except ValueError as exc:
                print(f"  hold pair{i+1}: fit failed ({exc})")
                continue
            a, b = hold["a"], hold["b"]
            wa = homo.pixel_to_world(a[0], a[1], computed["H"])
            wb = homo.pixel_to_world(b[0], b[1], computed["H"])
            pred = math.hypot(wb[0] - wa[0], wb[1] - wa[1])
            ppm = _ppm_distance(a, b)
            eh = abs(pred - hold["distance"])
            ep = abs(ppm - hold["distance"])
            errors_h.append(eh)
            errors_ppm.append(ep)
            print(
                f"  hold pair{i+1}: truth={hold['distance']:.2f}  "
                f"H={pred:.2f} (err {eh:.2f})  ppm={ppm:.2f} (err {ep:.2f})"
            )
        self.assertTrue(errors_h)
        mean_h = sum(errors_h) / len(errors_h)
        mean_p = sum(errors_ppm) / len(errors_ppm)
        print(f"Mean hold-out abs error: H={mean_h:.2f}m  ppm={mean_p:.2f}m")
        # Current 4-pair fit is NOT stable under hold-out — ppm wins here.
        self.assertGreater(mean_h, mean_p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
