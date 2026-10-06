"""Pause simulator: freeze countdown / clocks, then resume with pause time applied."""

from __future__ import annotations

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


class DummyTimer:
    instances = []

    def __init__(self, delay, fn):
        self.delay = delay
        self.fn = fn
        self.cancelled = False
        self.started = False
        self.daemon = False
        DummyTimer.instances.append(self)

    def cancel(self):
        self.cancelled = True

    def start(self):
        self.started = True
        return self


class FakeQtTimer:
    def __init__(self, remaining=1800):
        self._active = True
        self._remaining = remaining
        self.started_with = None

    def isActive(self):
        return self._active

    def remainingTime(self):
        return self._remaining

    def stop(self):
        self._active = False

    def start(self, ms):
        self._active = True
        self.started_with = ms
        self._remaining = ms


class FakeVlc:
    def __init__(self):
        self.t = 12345
        self.paused = False

    def get_time(self):
        return self.t

    def set_pause(self, value):
        self.paused = bool(value)

    def is_playing(self):
        return not self.paused

    def pause(self):
        self.paused = True

    def play(self):
        self.paused = False

    def set_time(self, value):
        self.t = value


def _snapshot(cam):
    out = {}
    for fid, ch in cam.channels.items():
        out[fid] = {
            "appear": ch.kp_appear_frames_left,
            "clear": ch.kp_clear_frames_left,
            "pending_start_time": ch.pending_start_time,
            "pending_end_time": ch.pending_end_time,
            "pending_end_time_str": ch.pending_end_time_str,
            "session_start": ch.session_start_timestamp,
            "session_frames": ch.session_frame_count,
            "between_ts": ch.between_session_start_ts,
            "qr_last": (ch.qr_state or {}).get("last_detection_time"),
            "block_start": (ch.current_qr_block or {}).get("start_time"),
            "offset_start": (ch.pending_start or {}).get("offset_start_time_str"),
            "analysis_remaining": ch._paused_analysis_remaining,
        }
    return out


def _tick_countdowns(cam):
    """What process_qr_detection would do to frame countdowns if not paused."""
    for ch in cam.channels.values():
        if ch.kp_appear_frames_left is not None:
            ch.kp_appear_frames_left -= 1
        if ch.kp_clear_frames_left is not None and ch.session_active:
            ch.kp_clear_frames_left -= 1
        ch.session_frame_count += 1


class PauseSimulatorTests(unittest.TestCase):
    def setUp(self):
        DummyTimer.instances = []
        self.clock = {"t": 1000.0}
        self.time_patch = patch("simust_realtime.time.time", side_effect=lambda: self.clock["t"])
        self.timer_patch = patch("simust_realtime.threading.Timer", DummyTimer)
        self.time_patch.start()
        self.timer_patch.start()

        cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
        cam.operator_paused = False
        cam._pause_lock = threading.Lock()
        cam._pause_started_at = 0
        cam._paused_analysis_remaining = None
        cam.channels = {"A": rt.FieldRuntime("A"), "B": rt.FieldRuntime("B")}
        cam.simulators = {
            "A": types.SimpleNamespace(start_ts=990.0, late_start_ts=991.0),
            "B": types.SimpleNamespace(start_ts=990.0, late_start_ts=0.0),
        }
        cam._field_is_active = lambda fid: True
        cam._perform_late_analysis = lambda fid: None
        self.cam = cam

        for fid, ch in cam.channels.items():
            ch.session_active = True
            ch.session_start_timestamp = 997.0
            ch.session_frame_count = 40
            ch.kp_appear_frames_left = 10
            ch.kp_clear_frames_left = 45
            ch.pending_start = {
                "action": "PASS",
                "offset_start_time_str": "12:00:01.200",
            }
            ch.pending_start_time = 1002.0
            ch.pending_end = True
            ch.pending_end_time = 1005.0
            ch.pending_end_time_str = "12:00:04.200"
            ch.current_qr_block = {"id": "S3", "start_time": "12:00:00.000"}
            ch.between_sessions_active = True
            ch.between_session_start_ts = 996.5
            ch.between_session_start_time = "12:00:00.500"
            ch.qr_state["last_detection_time"] = 999.0
            ch.analysis_started_at = 999.7
            ch.analysis_timer = DummyTimer(rt.LATE_ANALYSIS_DELAY, lambda: None)
            ch.analysis_timer.start()
            ch._paused_analysis_remaining = None

        self.analysis_timers = {
            fid: cam.channels[fid].analysis_timer for fid in cam.channels
        }
        self.frozen_before = _snapshot(cam)

    def tearDown(self):
        self.time_patch.stop()
        self.timer_patch.stop()

    def _run_pause(self, seconds, fps=30):
        frames = int(round(seconds * fps))
        if not self.cam.operator_paused:
            self.cam._freeze_for_pause()
        for _ in range(frames):
            # Main loop while paused: show last frame and sleep. No countdown.
            self.assertTrue(self.cam.operator_paused)
            self.clock["t"] += 1.0 / fps
            self.assertEqual(_snapshot(self.cam), self.frozen_after_lock)

    def test_pause_freezes_countdown_and_clocks_then_resume_shifts_by_pause_dt(self):
        pause_sec = 2.5
        before = self.frozen_before
        self.assertEqual(before["A"]["appear"], 10)
        self.assertEqual(before["A"]["clear"], 45)

        self.cam._freeze_for_pause()
        self.frozen_after_lock = _snapshot(self.cam)
        self.assertTrue(self.cam.operator_paused)
        self.assertTrue(self.analysis_timers["A"].cancelled)
        self.assertTrue(self.analysis_timers["B"].cancelled)
        self.assertIsNone(self.cam.channels["A"].analysis_timer)
        remaining = self.cam.channels["A"]._paused_analysis_remaining
        expected_remaining = max(0.05, rt.LATE_ANALYSIS_DELAY - (1000.0 - 999.7))
        self.assertAlmostEqual(remaining, expected_remaining, places=3)
        self.assertAlmostEqual(
            self.cam.channels["B"]._paused_analysis_remaining, expected_remaining, places=3
        )

        self._run_pause(pause_sec)
        after_pause = _snapshot(self.cam)
        self.assertEqual(after_pause["A"]["appear"], 10)
        self.assertEqual(after_pause["A"]["clear"], 45)
        self.assertEqual(after_pause["B"]["appear"], 10)
        self.assertEqual(after_pause["B"]["clear"], 45)
        self.assertEqual(after_pause["A"]["session_frames"], 40)
        self.assertEqual(after_pause["A"]["pending_start_time"], 1002.0)
        self.assertEqual(after_pause["A"]["session_start"], 997.0)
        self.assertEqual(after_pause["A"]["offset_start"], "12:00:01.200")
        self.assertEqual(after_pause["A"]["block_start"], "12:00:00.000")
        elapsed_during_pause = self.clock["t"] - 997.0
        self.assertGreater(elapsed_during_pause, pause_sec)
        # Wall clock moved; session elapsed must wait until resume shift.
        self.assertAlmostEqual(self.clock["t"], 1000.0 + pause_sec, places=2)

        DummyTimer.instances = []
        self.cam._unfreeze_after_pause()
        self.assertFalse(self.cam.operator_paused)

        after = _snapshot(self.cam)
        dt = pause_sec
        for fid in ("A", "B"):
            self.assertEqual(after[fid]["appear"], 10)
            self.assertEqual(after[fid]["clear"], 45)
            self.assertEqual(after[fid]["session_frames"], 40)
            self.assertAlmostEqual(after[fid]["pending_start_time"], 1002.0 + dt, places=2)
            self.assertAlmostEqual(after[fid]["pending_end_time"], 1005.0 + dt, places=2)
            self.assertAlmostEqual(after[fid]["session_start"], 997.0 + dt, places=2)
            self.assertAlmostEqual(after[fid]["between_ts"], 996.5 + dt, places=2)
            self.assertAlmostEqual(after[fid]["qr_last"], 999.0 + dt, places=2)
            self.assertEqual(after[fid]["offset_start"], rt.add_offset_to_time("12:00:01.200", dt))
            self.assertEqual(after[fid]["pending_end_time_str"], rt.add_offset_to_time("12:00:04.200", dt))
            self.assertEqual(after[fid]["block_start"], rt.add_offset_to_time("12:00:00.000", dt))
            # Session elapsed at resume equals elapsed at pause (3.0s).
            self.assertAlmostEqual(self.clock["t"] - after[fid]["session_start"], 3.0, places=2)

        self.assertAlmostEqual(self.cam.simulators["A"].start_ts, 990.0 + dt, places=2)
        self.assertAlmostEqual(self.cam.simulators["A"].late_start_ts, 991.0 + dt, places=2)
        self.assertAlmostEqual(self.cam.simulators["B"].start_ts, 990.0 + dt, places=2)
        self.assertEqual(self.cam.simulators["B"].late_start_ts, 0.0)

        restarted = [t for t in DummyTimer.instances if t.started]
        self.assertEqual(len(restarted), 2)
        for timer in restarted:
            self.assertAlmostEqual(timer.delay, expected_remaining, places=3)

    def test_without_pause_countdown_would_run_down(self):
        frames = 75
        _tick_countdowns(self.cam)
        self.assertEqual(self.cam.channels["A"].kp_appear_frames_left, 9)
        for _ in range(frames - 1):
            _tick_countdowns(self.cam)
        self.assertLess(self.cam.channels["A"].kp_appear_frames_left, 0)
        self.assertEqual(self.cam.channels["A"].session_frame_count, 40 + frames)

    def test_analysis_remaining_does_not_include_paused_wall_time(self):
        self.cam._freeze_for_pause()
        remaining_at_pause = self.cam.channels["A"]._paused_analysis_remaining
        self.clock["t"] += 8.0
        DummyTimer.instances = []
        self.cam._unfreeze_after_pause()
        self.assertAlmostEqual(DummyTimer.instances[0].delay, remaining_at_pause, places=3)
        self.assertLess(DummyTimer.instances[0].delay, rt.LATE_ANALYSIS_DELAY)


class PlayerPauseSimulatorTests(unittest.TestCase):
    def setUp(self):
        self.clock = {"t": 500.0}
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self.tmp.close()
        self.time_patch = patch("smart_simust_player.time.time", side_effect=lambda: self.clock["t"])
        self.perf_patch = patch(
            "smart_simust_player.time.perf_counter",
            side_effect=lambda: self.clock["t"],
        )
        self.time_patch.start()
        self.perf_patch.start()

        inst = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        inst.operator_paused = False
        inst._pause_started_at = 0
        inst._pause_perf_started_at = 0
        inst.video_start_time = 480.0
        inst._final_play_started_at = 470.0
        inst._paused_media_time = None
        inst._pending_start_after_pause = False
        inst._frozen_qt_timers = []
        inst.player = FakeVlc()
        inst.current_video_index = 2
        inst.video_files = ["a", "b", "c", "d"]
        inst.status_file = self.tmp.name
        inst.action_timer = FakeQtTimer(remaining=1800)
        inst.results_timer = FakeQtTimer(remaining=4000)
        inst.close_timer = FakeQtTimer(remaining=0)
        inst.close_timer._active = False
        inst.play_delay_timer = None
        inst._force_close_timer = None
        inst._is_closing = False
        inst.playlist_finished = False
        self.inst = inst

    def tearDown(self):
        self.time_patch.stop()
        self.perf_patch.stop()
        try:
            os.remove(self.tmp.name)
        except OSError:
            pass

    def test_player_pause_freezes_vlc_and_action_countdown_then_applies_dt(self):
        inst = self.inst
        elapsed_before = self.clock["t"] - inst.video_start_time
        self.assertAlmostEqual(elapsed_before, 20.0, places=3)

        inst._apply_operator_pause(True)
        self.assertTrue(inst.operator_paused)
        self.assertTrue(inst.player.paused)
        self.assertEqual(inst._paused_media_time, 12345)
        self.assertFalse(inst.action_timer.isActive())
        frozen = dict(inst._frozen_qt_timers)
        self.assertEqual(frozen["action_timer"], 1800)
        self.assertEqual(frozen["results_timer"], 4000)
        self.assertNotIn("close_timer", frozen)

        # Wall clock + 3s while paused: VLC time and action remaining stay put.
        self.clock["t"] += 3.0
        inst.player.t = 99999
        self.assertEqual(inst._paused_media_time, 12345)
        self.assertEqual(dict(inst._frozen_qt_timers)["action_timer"], 1800)
        self.assertTrue(inst.operator_paused)

        inst._check_video_position()
        self.assertEqual(inst.player.t, 99999)

        inst._apply_operator_pause(False)
        self.assertFalse(inst.operator_paused)
        self.assertFalse(inst.player.paused)
        self.assertEqual(inst.player.t, 12345)
        self.assertAlmostEqual(inst.video_start_time, 483.0, places=3)
        self.assertAlmostEqual(inst._final_play_started_at, 473.0, places=3)
        self.assertAlmostEqual(self.clock["t"] - inst.video_start_time, elapsed_before, places=3)
        self.assertTrue(inst.action_timer.isActive())
        self.assertEqual(inst.action_timer.started_with, 1800)
        self.assertEqual(inst.results_timer.started_with, 4000)
        self.assertEqual(inst._frozen_qt_timers, [])

    def test_activated_18s_budget_survives_10s_pause(self):
        """Pause 2s into an 18s Activated clock; 10s pause must leave 16s."""
        inst = self.inst
        inst._pass_on_ms = 18000
        inst._pass_shown_at = self.clock["t"] - 2.0
        inst._budget_started_at = self.clock["t"] - 2.0
        inst._budget_test = 1
        inst._set_start_time = self.clock["t"] - 2.0
        inst.video_start_time = inst._set_start_time
        inst.action_timer = FakeQtTimer(remaining=50)

        inst._apply_operator_pause(True)
        frozen = dict(inst._frozen_qt_timers)
        self.assertAlmostEqual(frozen["action_timer"], 16000, delta=20)

        self.clock["t"] += 10.0
        inst._apply_operator_pause(False)

        remain = int(inst._pass_on_ms - (self.clock["t"] - inst._pass_shown_at) * 1000.0)
        self.assertAlmostEqual(remain, 16000, delta=20)
        budget = inst._budget_remaining_ms(
            {"budget_ms": 18000, "test_num": 1, "action_in_set": 1}
        )
        self.assertAlmostEqual(budget, 16000, delta=20)
        self.assertAlmostEqual(
            self.clock["t"] - inst._set_start_time, 2.0, places=3
        )
        self.assertEqual(inst.action_timer.started_with, 16000)


if __name__ == "__main__":
    unittest.main()
