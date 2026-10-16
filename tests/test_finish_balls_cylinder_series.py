"""Simulator: finish-balls cylinders stay up across every set, one side and both.

Covers Activated / High Performance / Elite / World Class (S1 + S2). Catches the
bug where a >5s cue looked "off" and tore down the green cylinder from series 2 on.
"""

from __future__ import annotations

import os
import sys
import time
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


def _patch_playlist_renders(testcase: unittest.TestCase) -> None:
    testcase._entry = player._render_entry_digit_image
    testcase._band = player._render_band_digit_image
    testcase._mid = player._render_middle_colored_text_image
    testcase._cam = player._render_camouflage_text_image
    testcase._motion = player._ensure_wc_motion_bg_video
    testcase._solid = player._wc_solid_theme_still
    testcase._compose = getattr(player, "_compose_bouncing_flowers_rgb", None)
    testcase._composite = getattr(player, "_composite_overlay_on_bg", None)
    player._render_entry_digit_image = lambda text, bg=None: f"img:{text}:{bg}"
    player._render_band_digit_image = lambda text, bg, fg: f"img:{text}:{bg}:{fg}"
    player._render_middle_colored_text_image = (
        lambda text, bg, outer_fg, mid_fg: f"mid:{text}:{bg}:{outer_fg}:{mid_fg}"
    )
    player._compose_bouncing_flowers_rgb = (
        lambda width, height, seed, frame_i=0, base_rgb=None, fleet=None, kind="flowers": (
            None, fleet
        )
    )
    player._composite_overlay_on_bg = lambda *a, **k: None
    player._render_camouflage_text_image = (
        lambda text, seed=1, camouflage=True, theme="flowers", phase=0.0, fast=True: (
            f"cam:{text}:{seed}:{camouflage}:{theme}"
        )
    )
    player._ensure_wc_motion_bg_video = (
        lambda theme, seed, base_rgb=None, blocking=False: f"motion:{theme}:{seed}.mp4"
    )
    player._wc_solid_theme_still = lambda theme, seed=1: f"solid:{theme}:{seed}"


def _unpatch_playlist_renders(testcase: unittest.TestCase) -> None:
    player._render_entry_digit_image = testcase._entry
    player._render_band_digit_image = testcase._band
    player._render_middle_colored_text_image = testcase._mid
    player._render_camouflage_text_image = testcase._cam
    player._ensure_wc_motion_bg_video = testcase._motion
    player._wc_solid_theme_still = testcase._solid
    if testcase._compose is not None:
        player._compose_bouncing_flowers_rgb = testcase._compose
    if testcase._composite is not None:
        player._composite_overlay_on_bg = testcase._composite


def _finish_balls_playlists():
    """(label, fields, playlist) for every finish-balls band, S1 + S2, 1-side + 2-side."""
    rows = []
    for series in (1, 2, 5):
        rows.append((
            f"Activated-S1.T{series}",
            ["A"],
            player._build_activated_playlist(series, ["A"]),
        ))
        rows.append((
            f"Activated-S1.T{series}-AB",
            ["A", "B"],
            player._build_activated_playlist(series, ["A", "B"]),
        ))
        rows.append((
            f"Activated-S2.T{series}",
            ["A"],
            player._build_activated_a1_playlist(series, ["A"]),
        ))
        rows.append((
            f"Activated-S2.T{series}-AB",
            ["A", "B"],
            player._build_activated_a1_playlist(series, ["A", "B"]),
        ))
        rows.append((
            f"HP-S1.T{series}",
            ["A"],
            player._build_high_performance_playlist(series, ["A"]),
        ))
        rows.append((
            f"HP-S1.T{series}-AB",
            ["A", "B"],
            player._build_high_performance_playlist(series, ["A", "B"]),
        ))
        rows.append((
            f"HP-S2.T{series}",
            ["A"],
            player._build_high_performance_s2_playlist(series, ["A"]),
        ))
        rows.append((
            f"HP-S2.T{series}-AB",
            ["A", "B"],
            player._build_high_performance_s2_playlist(series, ["A", "B"]),
        ))
        rows.append((
            f"Elite-S1.T{series}",
            ["A"],
            player._build_elite_playlist(series, "elite"),
        ))
        rows.append((
            f"Elite-S2.T{series}",
            ["A"],
            player._build_elite_s2_playlist(series),
        ))
        rows.append((
            f"WC-S1.T{series}",
            ["A"],
            player._build_elite_playlist(series, "world-class"),
        ))
        rows.append((
            f"WC-S2.T{series}",
            ["A"],
            player._build_world_class_s2_playlist(series),
        ))
    return rows


def _first_action_per_test(playlist):
    seen = set()
    out = []
    for entry in playlist or []:
        if not isinstance(entry, dict) or not entry.get("finish_balls"):
            continue
        test_num = int(entry.get("test_num") or 0)
        if test_num in seen:
            continue
        seen.add(test_num)
        out.append(entry)
    return out


class ImageCueStaleWindowTests(unittest.TestCase):
    def test_finish_balls_active_cue_survives_past_five_seconds(self):
        cue = {
            "active": True,
            "finish_balls": True,
            "on_sec": 54.0,
            "budget_total_sec": 54.0,
            "seq": 3,
            "timestamp": time.time() - 6.0,
            "fields": {"A": {"action": "PASS", "screens": ["A2"]}},
        }
        self.assertGreater(rt._image_cue_stale_sec(cue), 5.0)
        cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
        hit = rt.SimustRealtimeCamera._image_cue_for_field(cam, cue, "A")
        self.assertTrue(hit.get("screens"))
        self.assertIn("IMAGE|3|PASS|A2", hit.get("raw") or "")

    def test_plain_cue_still_expires_at_five_seconds(self):
        cue = {
            "active": True,
            "on_sec": 3.0,
            "seq": 1,
            "timestamp": time.time() - 6.0,
            "fields": {"A": {"action": "PASS", "screens": ["A2"]}},
        }
        self.assertEqual(rt._image_cue_stale_sec(cue), 5.0)
        cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
        hit = rt.SimustRealtimeCamera._image_cue_for_field(cam, cue, "A")
        self.assertEqual(hit.get("screens") or [], [])


class FinishBallsCylinderSeriesSimTests(unittest.TestCase):
    """Drive image-cue ticks like the camera loop for every finish-balls set."""

    def setUp(self):
        _patch_playlist_renders(self)
        # Windows consoles often can't print the cue-path arrows in realtime logs.
        self._stdout = sys.stdout
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
        self.cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
        self.cam.operator_paused = False
        self.cam.session_lock = __import__("threading").Lock()
        self.cam.active_fields = {"A", "B"}
        self.cam._field_is_active = lambda fid: fid in self.cam.active_fields
        self.cam._shared_cue_raw = None
        self.cam.shared_action_index = 0
        self.cam.simulation_enabled = False
        self.cam.simulators = {}
        self.cue = {}
        self.cam._read_image_action_cue = lambda: self.cue
        self.cam._image_cue_for_field = rt.SimustRealtimeCamera._image_cue_for_field.__get__(
            self.cam
        )
        self.cam._schedule_live_display = lambda ch: None
        self.cam.save_recognition_json = lambda ch: None
        self.cam.save_between_sessions_block = lambda ch: None
        self.channels = {}
        for fid in ("A", "B"):
            ch = types.SimpleNamespace(
                field_id=fid,
                label=fid,
                session_active=False,
                active_goal_lines={},
                current_qr_block=None,
                current_action=None,
                current_screens=[],
                current_keypoints=[],
                current_block_id=None,
                session_data=[],
                session_fps_sum=0,
                session_frame_count=0,
                keypoint_hold_frames=0,
                keypoint_frames_shown=0,
                keypoint_clear_armed=False,
                keypoint_hold_until=0.0,
                _planned_on_sec=None,
                between_sessions_active=False,
                between_session_data=[],
                between_session_start_time="",
                between_session_start_ts=0,
                between_session_end_time="",
                pending_start=None,
                pending_start_time=0,
                pending_end=False,
                pending_end_time=0,
                _frame_sync_cue_raw=None,
                _cylinder_goal_seq=None,
                kp_appear_frames_left=None,
                _pending_cue_info=None,
                kp_clear_frames_left=None,
                _gap_display_sent=False,
                _display_seq=0,
                block_counter=0,
                stats={"results": [], "sessions_completed": 0, "action_counts": {}},
                session_start_timestamp=0,
                analysis_timer=None,
                pending_analysis=None,
                qr_blocks=[],
                qr_state=None,
            )
            self.channels[fid] = ch
        self.cam.channels = self.channels
        # Use real start/end helpers so goal lines + finish_balls land on the channel.
        self.cam.schedule_session_start = rt.SimustRealtimeCamera.schedule_session_start.__get__(
            self.cam
        )
        self.cam._execute_start = rt.SimustRealtimeCamera._execute_start.__get__(self.cam)
        self.cam._end_session_locked = rt.SimustRealtimeCamera._end_session_locked.__get__(
            self.cam
        )
        self.cam._clear_goal_area_now = rt.SimustRealtimeCamera._clear_goal_area_now.__get__(
            self.cam
        )
        self.cam.get_goal_lines = rt.SimustRealtimeCamera.get_goal_lines.__get__(self.cam)
        self.cam._peer_for = lambda ch: None
        self.cam._sync_simulator_partner_mode = lambda: None
        self.cam._field_is_simulated = lambda fid: False

        def clear_goal(ch, _ts):
            ch.kp_clear_frames_left = None
            ch.active_goal_lines = {}
            ch.current_keypoints = []
            ch.session_active = False
            ch.current_qr_block = None

        def end_locked(_tstr, _ts, ch=None):
            if ch is None:
                return
            ch.session_active = False
            ch.kp_clear_frames_left = None
            ch.active_goal_lines = {}
            ch.current_keypoints = []

        self.cam._clear_goal_area_now = clear_goal
        self.cam._end_session_locked = end_locked

    def tearDown(self):
        try:
            sys.stdout.close()
        except Exception:
            pass
        sys.stdout = self._stdout
        _unpatch_playlist_renders(self)

    def _write_cue(self, entry, seq, age_sec=0.0):
        fields = {}
        for fid, screens in (entry.get("field_screens") or {}).items():
            if not screens:
                continue
            fields[str(fid).upper()[:1]] = {
                "action": "PASS",
                "screens": list(screens),
            }
        on_ms = int(entry.get("budget_ms") or entry.get("on_ms") or 3000)
        on_sec = max(0.1, on_ms / 1000.0)
        self.cue = {
            "active": True,
            "finish_balls": True,
            "seq": int(seq),
            "timestamp": time.time() - float(age_sec),
            "on_sec": on_sec,
            "budget_total_sec": on_sec,
            "efficiency_max_sec": on_sec,
            "action_in_set": entry.get("action_in_set"),
            "actions_in_set": entry.get("actions_in_set"),
            "test_num": entry.get("test_num"),
            "fields": fields,
        }
        return sorted(fields.keys())

    def _clear_cue(self):
        self.cue = {
            "active": False,
            "finish_balls": True,
            "seq": int(self.cue.get("seq") or 0),
            "timestamp": time.time(),
            "fields": {},
        }

    def _tick(self, n=1, t0=1000.0):
        for i in range(n):
            rt.SimustRealtimeCamera._tick_image_cue_frame_sync(
                self.cam, "00:00:00.000", t0 + i * 0.05
            )

    def _assert_cylinders(self, label, wanted_fields, context):
        for fid in wanted_fields:
            ch = self.channels[fid]
            self.assertTrue(
                ch.session_active,
                f"{label}: {context}: field {fid} session inactive (no cylinder)",
            )
            self.assertTrue(
                ch.active_goal_lines,
                f"{label}: {context}: field {fid} has no goal lines (no cylinder)",
            )
            block = ch.current_qr_block if isinstance(ch.current_qr_block, dict) else {}
            self.assertTrue(
                block.get("finish_balls"),
                f"{label}: {context}: field {fid} missing finish_balls on block",
            )

    def test_cylinders_on_every_set_one_side_and_both_sides(self):
        shift = int(rt.IMAGE_CUE_EDGE_SHIFT_FRAMES)
        failures = []
        checked = 0
        for label, active, playlist in _finish_balls_playlists():
            if not playlist:
                failures.append(f"{label}: empty playlist")
                continue
            self.cam.active_fields = set(active)
            for fid, ch in self.channels.items():
                ch.session_active = False
                ch.active_goal_lines = {}
                ch.current_qr_block = None
                ch._frame_sync_cue_raw = None
                ch._cylinder_goal_seq = None
                ch.kp_appear_frames_left = None
                ch._pending_cue_info = None
                ch.kp_clear_frames_left = None
                ch.pending_start = None
            actions = _first_action_per_test(playlist)
            if len(actions) < 2:
                failures.append(f"{label}: expected multiple tests, got {len(actions)}")
                continue
            for set_i, entry in enumerate(actions, start=1):
                wanted = self._write_cue(entry, seq=1000 + set_i * 10 + checked, age_sec=0)
                if not wanted:
                    failures.append(f"{label} set{set_i}: no field_screens")
                    continue
                # Restrict wanted to active fields present in the cue.
                wanted = [f for f in wanted if f in active]
                try:
                    self._tick(shift + 1)
                    self._assert_cylinders(label, wanted, f"set{set_i} after appear")
                    # Long finish-balls clock: cue file age > 5s must keep cylinders.
                    self.cue["timestamp"] = time.time() - 6.0
                    self._tick(3)
                    self._assert_cylinders(label, wanted, f"set{set_i} after 6s cue age")
                    self._clear_cue()
                    self._tick(2)
                    for fid in wanted:
                        ch = self.channels[fid]
                        self.assertFalse(
                            ch.session_active,
                            f"{label} set{set_i}: cylinder stuck after clear on {fid}",
                        )
                    checked += 1
                except AssertionError as exc:
                    failures.append(str(exc))
                    self._clear_cue()
                    self._tick(2)
        self.assertFalse(failures, "\n".join(failures[:40]))
        self.assertGreaterEqual(checked, 40, f"only checked {checked} set(s)")


if __name__ == "__main__":
    unittest.main()
