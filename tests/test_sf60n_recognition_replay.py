"""Replay SF-60N from a real player's recognition.json (ball + hip footprints)."""

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
import simust_replay as replay  # noqa: E402

FOLDER = replay.default_sf60n_folder()
VISUAL = {
    "S4": "Correct",
    "S5": "Miss",
    "S9": "Late",
    "S10": "Miss",
    "S13": "Late",
    "S19": "Miss",
    "S24": "Correct",
}


class Sf60nRecognitionReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = replay.recognition_path(FOLDER)
        if not os.path.isfile(path):
            raise unittest.SkipTest("SF-60N recognition.json not found at %s" % path)
        cls.folder = FOLDER
        cls.rows = replay.score_recognition(FOLDER)

    def test_visual_shots_match_copied_footprints(self):
        by_id = {row["id"]: row for row in self.rows}
        for shot, expected in VISUAL.items():
            self.assertIn(shot, by_id)
            self.assertEqual(by_id[shot]["result"], expected, msg=by_id[shot])

    def test_simulator_copies_real_ball_not_rule_path(self):
        blocks = replay.load_blocks(self.folder)
        block = next(b for b in blocks if b.get("id") == "S4")
        rp = replay.RecognitionReplay.from_folder(self.folder)
        self.assertTrue(rp.begin_action("PASS", block["screens"], action_id="S4"))
        entry = block["data"][0]
        balls, _players, hip = rp.step(1280, 360)
        real_b = entry["b"][0]
        self.assertEqual(balls[0]["center"], [int(real_b[0]), int(real_b[1])])
        if entry.get("hp"):
            self.assertAlmostEqual(hip[0], float(entry["hp"][0]), delta=0.6)
            self.assertAlmostEqual(hip[1], float(entry["hp"][1]), delta=0.6)

    def test_replay_follows_recorded_time_not_frame_rate(self):
        blocks = replay.load_blocks(self.folder)
        block = next(b for b in blocks if b.get("id") == "S4")
        mid = next(row for row in block["data"] if float(row.get("t") or 0) >= 1.5 and row.get("b"))
        rp = replay.RecognitionReplay.from_folder(self.folder)
        rp.begin_action("PASS", block["screens"], action_id="S4")
        balls, _p, _h = rp.sample_at(float(mid["t"]), 1280, 360)
        self.assertEqual(balls[0]["center"], [int(mid["b"][0][0]), int(mid["b"][0][1])])

    def test_hip_path_uses_recognition_not_synthetic_home(self):
        path = replay.hip_path(self.folder)
        self.assertGreater(len(path), 100)
        xs = [p[1] for p in path]
        self.assertGreater(max(xs) - min(xs), 40)
        meters = homo.path_distance_meters(
            [(t, x, y) for t, x, y in path[::4]],
            fallback_m_per_px=0.0259,
        )
        self.assertGreater(meters, 0.5)


if __name__ == "__main__":
    rows = replay.score_recognition(FOLDER)
    print("SF-60N recognition replay:", FOLDER)
    print("id   action  screens     result")
    for row in rows:
        mark = ""
        if row["id"] in VISUAL:
            mark = "  visual=%s %s" % (
                VISUAL[row["id"]],
                "OK" if row["result"] == VISUAL[row["id"]] else "DIFF",
            )
        print("%s  %-6s  %-10s  %-8s%s" % (
            row["id"], row["action"], ",".join(row["screens"]), row["result"], mark,
        ))
    unittest.main()
