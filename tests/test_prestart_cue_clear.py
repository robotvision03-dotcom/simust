"""Leftover finish-balls must not arm before beginning information (World Class).

Realtime boots ~3s before the smart player. A prior finish-balls cue can still be
active for the shared-clock window and fire the cylinder/sim shot before logos.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class AppPrestartCueClearTests(unittest.TestCase):
    def test_clear_image_action_cue_force_ends_stale_finish_balls(self):
        import app as simust_app

        with tempfile.TemporaryDirectory() as tmp:
            cue_path = os.path.join(tmp, "image_action_cue.json")
            with open(cue_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "active": True,
                        "finish_balls": True,
                        "seq": 12,
                        "budget_total_sec": 54.0,
                        "timestamp": time.time(),
                        "fields": {"A": {"action": "PASS", "screens": ["A3"], "seq": 12}},
                    },
                    handle,
                )
            with patch.object(simust_app, "SIMUST_PLAYER_DIRECTORY", tmp):
                simust_app.clear_image_action_cue(force_end=True)
            with open(cue_path, "r", encoding="utf-8") as handle:
                cue = json.load(handle)
            self.assertFalse(cue.get("active"))
            self.assertTrue(cue.get("force_end"))
            self.assertEqual(cue.get("fields") or {}, {})


class RealtimeBootCueClearTests(unittest.TestCase):
    def test_boot_clear_writes_force_end(self):
        import simust_realtime as rt

        with tempfile.TemporaryDirectory() as tmp:
            cue_path = os.path.join(tmp, "image_action_cue.json")
            with open(cue_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "active": True,
                        "finish_balls": True,
                        "seq": 3,
                        "timestamp": time.time(),
                        "fields": {"A": {"action": "PASS", "screens": ["A1"]}},
                    },
                    handle,
                )
            with patch.object(rt, "SIMUST_PLAYER_DIRECTORY", tmp), patch.object(
                rt, "IMAGE_ACTION_CUE_FILE", cue_path
            ):
                rt._boot_clear_image_action_cue()
            with open(cue_path, "r", encoding="utf-8") as handle:
                cue = json.load(handle)
            self.assertFalse(cue.get("active"))
            self.assertTrue(cue.get("force_end"))

    def test_force_end_blocks_arm_before_opening(self):
        import simust_realtime as rt

        cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
        cam.operator_paused = False
        cam.session_lock = __import__("threading").Lock()
        cam.active_fields = {"A"}
        cam._field_is_active = lambda fid: fid == "A"
        cam._paused_fields = set()
        cam._shared_cue_raw = None
        cam.shared_action_index = 0
        cleared = []

        ch = types.SimpleNamespace(
            field_id="A",
            label="A",
            session_active=False,
            active_goal_lines={"A3": {"p0": (1, 1), "p1": (2, 2)}},
            current_qr_block={"finish_balls": True},
            pending_start={"action": "PASS"},
            kp_appear_frames_left=10,
            _pending_cue_info={"finish_balls": True},
            _frame_sync_cue_raw="IMAGE|1|PASS|A3",
            kp_clear_frames_left=None,
        )
        cam.channels = {"A": ch}
        cam._read_image_action_cue = lambda: {
            "active": False,
            "force_end": True,
            "seq": 0,
            "fields": {},
            "timestamp": time.time(),
        }

        def clear_goal(channel, _ts):
            cleared.append(channel.field_id)
            channel.active_goal_lines = {}
            channel.session_active = False
            channel.current_qr_block = None

        cam._clear_goal_area_now = clear_goal
        rt.SimustRealtimeCamera._tick_image_cue_frame_sync(cam, "00:00:00.000", 1000.0)
        self.assertIsNone(ch.kp_appear_frames_left)
        self.assertIsNone(ch._pending_cue_info)
        self.assertIsNone(ch.pending_start)
        self.assertEqual(cleared, ["A"])
        self.assertFalse(ch.active_goal_lines)


if __name__ == "__main__":
    unittest.main()
