"""Fast-tempo (T1.2) sessions must not drop pending result labels."""

import os
import sys
import types
import threading
import unittest
from unittest import mock

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

import simust_realtime as rt  # noqa: E402


class FastTempoAnalysisFlushTests(unittest.TestCase):
    def test_ending_next_shot_flushes_previous_pending_result(self):
        cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
        cam.session_lock = threading.Lock()
        cam.stats = {"results": [], "sessions_completed": 0, "action_counts": {}}
        cam.session_active = False
        cam.simulation_enabled = False
        cam.qr_blocks = []
        cam.between_session_data = []
        cam.between_sessions_active = False
        cam.between_session_start_time = "12:00:00.000"
        cam.recording_dir = None
        cam.pending_analysis = None
        cam.analysis_timer = None
        cam.analysis_started_at = 0.0

        scored = []

        def fake_analyze(pending):
            scored.append(pending["block_id"])
            cam.stats["results"].append({"id": pending["block_id"], "result": "Correct"})
            cam.pending_analysis = None
            cam.analysis_timer = None

        cam._perform_late_analysis_locked = lambda: fake_analyze(cam.pending_analysis) if cam.pending_analysis else None

        # First shot scheduled, timer armed (as on T1.2 before next QR).
        cam.pending_analysis = {
            "action_data": {"id": "S1", "data": []},
            "action_type": "PASS",
            "video_index": 1,
            "block_id": "S1",
            "screens": ["2"],
        }
        cam.analysis_timer = threading.Timer(2.5, lambda: None)
        cam.analysis_timer.daemon = True

        # Next shot ends ~2s later: must flush S1, not drop it.
        cam._flush_pending_analysis_locked()
        self.assertEqual(scored, ["S1"])
        self.assertIsNone(cam.pending_analysis)
        self.assertEqual([r["id"] for r in cam.stats["results"]], ["S1"])

    def test_t12_session_rescore_has_all_actions(self):
        folder = os.path.join(
            os.path.expanduser("~"),
            "Documents",
            "simust_realtime_recordings",
            "realtime_20260909_101747_499",
        )
        if not os.path.isfile(os.path.join(folder, "recognition.json")):
            self.skipTest("T1.2 SF-30N recognition missing")
        import simust_replay as replay
        rows = replay.score_recognition(folder)
        with open(os.path.join(folder, "results.json"), encoding="utf-8") as handle:
            saved = __import__("json").load(handle)
        if isinstance(saved, dict):
            saved = saved.get("actions") or []
        self.assertEqual(len(rows), 30)
        # Bug symptom: live save kept only last few labels per run.
        self.assertLess(len(saved), len(rows))
        self.assertGreaterEqual(len(rows), 20)


if __name__ == "__main__":
    unittest.main()
