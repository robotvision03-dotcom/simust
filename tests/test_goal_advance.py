"""Elite / World Class: a ball in the cylinder must switch screens immediately."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

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


class CylinderGoalPublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self.tmp.close()
        self.path_patch = patch.object(rt, "LIVE_ACTION_RESULT_FILE", self.tmp.name)
        self.path_patch.start()
        cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
        cam.operator_paused = False
        cam._live_file_lock = threading.Lock()
        cam.channels = {}
        cam.session_lock = threading.Lock()
        cam.simulation_enabled = False
        cam.simulators = {}
        self.ended = []

        def fake_end(_s, _t, ch=None):
            target = ch or self.ch
            self.ended.append(True)
            target.session_active = False
            target.active_goal_lines = {}
            target.current_keypoints = []

        cam._end_session_locked = fake_end
        self.cam = cam
        line = rt.GOAL_LINES["13"]
        self.ch = types.SimpleNamespace(
            session_active=True,
            current_qr_block={"finish_balls": True},
            _display_seq=4,
            _cylinder_goal_seq=None,
            current_action="PASS",
            active_goal_lines={"13": {"p0": line["p0"], "p1": line["p1"]}},
            current_screens=["13"],
            current_block_id="S4",
            field_id="A",
            current_keypoints=["13"],
        )
        cx = (line["p0"][0] + line["p1"][0]) / 2.0
        cy = (line["p0"][1] + line["p1"][1]) / 2.0
        self.inside = (cx, cy)

    def tearDown(self):
        self.path_patch.stop()
        try:
            os.remove(self.tmp.name)
        except OSError:
            pass

    def test_ball_in_cylinder_writes_correct_live_result(self):
        self.cam._publish_goal_if_in_cylinder(self.ch, [{"center": self.inside}])
        with open(self.tmp.name, encoding="utf-8") as handle:
            payload = json.load(handle)
        entry = payload["fields"]["A"]
        self.assertEqual(entry["result"], "Correct")
        self.assertEqual(entry["seq"], 4)
        self.assertEqual(self.ch._cylinder_goal_seq, 4)
        self.assertEqual(self.ended, [True])
        self.assertFalse(self.ch.session_active)
        self.assertEqual(self.ch.active_goal_lines, {})

    def test_ball_outside_does_not_write(self):
        self.cam._publish_goal_if_in_cylinder(self.ch, [{"center": (0.0, 0.0)}])
        self.assertFalse(os.path.getsize(self.tmp.name))
        self.assertEqual(self.ended, [])
        self.assertTrue(self.ch.session_active)


class EliteGoalAdvancePollTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self.tmp.close()
        self.path_patch = patch.object(player, "LIVE_ACTION_RESULT_FILE", self.tmp.name)
        self.path_patch.start()
        inst = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        inst.operator_paused = False
        inst.display_phase = "action"
        inst._label_phase = "action"
        inst._goal_arrived = False
        inst.current_video_index = 0
        inst._flash_seq = 4
        inst._action_cue_wall = 1.0
        inst._active_fields = lambda: ["A", "B"]
        inst._stop_goal_advance_poll = lambda: None
        inst.finished = []
        inst._finish_label_action = lambda: inst.finished.append(True)
        inst.video_files = [{
            "advance_on_goal": True,
            "field_screens": {"A": ["A2"]},
        }]
        self.inst = inst

    def tearDown(self):
        self.path_patch.stop()
        try:
            os.remove(self.tmp.name)
        except OSError:
            pass

    def _write(self, payload):
        with open(self.tmp.name, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_correct_on_current_field_switches_screen(self):
        self._write({
            "fields": {
                "A": {
                    "seq": 4,
                    "ts": 10.0,
                    "result": "Correct",
                    "by_seq": {"4": {"seq": 4, "ts": 10.0, "result": "Correct"}},
                }
            }
        })
        self.inst._poll_goal_advance()
        self.assertTrue(self.inst._goal_arrived)
        self.assertEqual(self.inst.finished, [True])

    def test_other_field_correct_does_not_switch(self):
        self._write({
            "fields": {
                "B": {
                    "seq": 4,
                    "ts": 10.0,
                    "result": "Correct",
                    "by_seq": {"4": {"seq": 4, "ts": 10.0, "result": "Correct"}},
                }
            }
        })
        self.inst._poll_goal_advance()
        self.assertFalse(self.inst._goal_arrived)
        self.assertEqual(self.inst.finished, [])

    def test_miss_does_not_switch(self):
        self._write({
            "fields": {
                "A": {
                    "seq": 4,
                    "ts": 10.0,
                    "result": "Miss",
                    "by_seq": {"4": {"seq": 4, "ts": 10.0, "result": "Miss"}},
                }
            }
        })
        self.inst._poll_goal_advance()
        self.assertFalse(self.inst._goal_arrived)


if __name__ == "__main__":
    unittest.main()
