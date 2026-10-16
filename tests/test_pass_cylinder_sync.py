"""Pass image and green cylinder must share the same On window (e.g. 3.0s)."""

from __future__ import annotations

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

import simust_realtime as rt  # noqa: E402
import smart_simust_player as player  # noqa: E402


class PassCylinderSyncTests(unittest.TestCase):
    def test_edge_shift_matches_realtime_and_player(self):
        self.assertEqual(
            player.IMAGE_CUE_EDGE_SHIFT_FRAMES, rt.IMAGE_CUE_EDGE_SHIFT_FRAMES
        )
        self.assertEqual(player.IMAGE_CUE_EDGE_SHIFT_MS, 850)
        self.assertAlmostEqual(
            rt.IMAGE_CUE_EDGE_SHIFT_FRAMES / rt.IMAGE_CUE_FPS, 0.85, places=3
        )

    def test_three_second_on_is_sixty_hold_frames_after_appear(self):
        self.assertEqual(rt._on_hold_frames(3.0), 60)
        # Old bug: clearing the cylinder when the next cue arrived left only
        # On − edge_shift ≈ 2.15s on screen while the pass stayed ~3s.
        cut_early = 3.0 - (rt.IMAGE_CUE_EDGE_SHIFT_FRAMES / rt.IMAGE_CUE_FPS)
        self.assertAlmostEqual(cut_early, 2.15, places=2)
        self.assertGreater(rt._on_hold_frames(3.0) / rt.IMAGE_CUE_FPS, cut_early)

    def test_new_finish_balls_cue_does_not_kill_active_hold(self):
        cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
        cam.operator_paused = False
        cam.session_lock = __import__("threading").Lock()
        cam.active_fields = {"A"}
        cam._field_is_active = lambda fid: fid == "A"
        cam._shared_cue_raw = None
        cam.shared_action_index = 0
        cleared = []

        def clear(ch, _ts):
            cleared.append(True)
            ch.session_active = False

        cam._clear_goal_area_now = clear
        cam._image_cue_for_field = rt.SimustRealtimeCamera._image_cue_for_field.__get__(cam)
        cue = {
            "active": True,
            "finish_balls": True,
            "seq": 2,
            "timestamp": __import__("time").time(),
            "on_sec": 3.0,
            "fields": {"A": {"action": "PASS", "screens": ["A1"]}},
        }
        cam._read_image_action_cue = lambda: cue
        ch = types.SimpleNamespace(
            field_id="A",
            label="A",
            session_active=True,
            active_goal_lines={"A1": {"p0": (0, 0), "p1": (1, 0)}},
            current_qr_block={"finish_balls": True},
            _frame_sync_cue_raw="IMAGE|1|PASS|A2",
            _cylinder_goal_seq=1,
            kp_appear_frames_left=None,
            _pending_cue_info=None,
            kp_clear_frames_left=40,
            pending_start=None,
            between_sessions_active=False,
            stats={"results": []},
        )
        cam.channels = {"A": ch}
        old = sys.stdout
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
        try:
            rt.SimustRealtimeCamera._tick_image_cue_frame_sync(
                cam, "00:00:00.000", 1000.0
            )
        finally:
            try:
                sys.stdout.close()
            except Exception:
                pass
            sys.stdout = old
        self.assertEqual(cleared, [], "next cue must not cut the current On hold")
        self.assertEqual(ch.kp_appear_frames_left, rt.IMAGE_CUE_EDGE_SHIFT_FRAMES)
        self.assertTrue(ch.session_active)


if __name__ == "__main__":
    unittest.main()
