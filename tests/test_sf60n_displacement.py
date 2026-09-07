"""SF-60N simulation: hip displacement uses saved camera-1 homography."""

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
import simust_realtime as rt  # noqa: E402

CAL_FILE = os.path.join(ROOT, "homography_calibration.json")
FALLBACK = 0.0259
STITCH_W, STITCH_H = 1280, 360


def _load_lab_calibration():
    homo.CALIBRATION_FILE = CAL_FILE
    homo._cache = None
    homo._cache_mtime = 0.0
    return homo.load_store()


class Sf60nHomographyDisplacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(CAL_FILE):
            raise unittest.SkipTest("homography_calibration.json is missing")
        cls.store = _load_lab_calibration()
        rec = homo.camera_record(cls.store, "camera-1")
        if not homo.is_calibrated(rec):
            raise unittest.SkipTest("camera-1 is not calibrated")

    def test_saved_pair_11_87m_roundtrip(self):
        rec = homo.camera_record(self.store, "camera-1")
        pair = next(p for p in rec["pairs"] if abs(p["distance"] - 11.87) < 0.02)
        a = homo.pixel_to_world(pair["a"]["u"], pair["a"]["v"], rec["H"])
        b = homo.pixel_to_world(pair["b"]["u"], pair["b"]["v"], rec["H"])
        dist = math.hypot(b[0] - a[0], b[1] - a[1])
        self.assertAlmostEqual(dist, pair["distance"], places=1)

    def test_sf60n_simulator_press_uses_homography(self):
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
        homo_m = homo.path_distance_meters(positions, store=self.store, fallback_m_per_px=FALLBACK)
        px = 0.0
        for i in range(1, len(positions)):
            _, x1, y1 = positions[i - 1]
            _, x2, y2 = positions[i]
            px += math.hypot(x2 - x1, y2 - y1)
        scale_m = px * FALLBACK
        self.assertGreater(homo_m, 0.05)
        self.assertTrue(math.isfinite(homo_m))
        self.assertNotAlmostEqual(homo_m, scale_m, places=2)

    def test_straight_segment_on_calibrated_line(self):
        rec = homo.camera_record(self.store, "camera-1")
        pair = next(p for p in rec["pairs"] if abs(p["distance"] - 11.87) < 0.02)
        au, av = pair["a"]["u"], pair["a"]["v"]
        bu, bv = pair["b"]["u"], pair["b"]["v"]
        samples = []
        for i in range(9):
            f = i / 8.0
            samples.append((i, au + (bu - au) * f, av + (bv - av) * f))
        dist = homo.path_distance_meters(samples, store=self.store, fallback_m_per_px=FALLBACK)
        self.assertAlmostEqual(dist, 11.87, delta=0.4)


if __name__ == "__main__":
    unittest.main()
