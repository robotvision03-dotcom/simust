"""Booking deadline abort: stop a field in the last minute of its reservation."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import app as app_mod  # noqa: E402
import smart_simust_player as player  # noqa: E402


class ContiguousBookingEndTests(unittest.TestCase):
    def test_single_active_booking_end(self):
        now = datetime(2026, 10, 23, 10, 15, 0)
        bookings = [
            {
                "player_id": "jj",
                "field": "A",
                "payment_status": "paid",
                "start": "2026-10-23T10:00:00",
                "end": "2026-10-23T10:30:00",
            }
        ]
        with patch.object(app_mod, "load_reservations", return_value=bookings):
            end = app_mod.resolve_contiguous_booking_end("jj", "A", now=now)
        self.assertEqual(end, datetime(2026, 10, 23, 10, 30, 0))

    def test_back_to_back_bookings_extend_deadline(self):
        now = datetime(2026, 10, 23, 10, 15, 0)
        bookings = [
            {
                "player_id": "jj",
                "field": "A",
                "payment_status": "paid",
                "start": "2026-10-23T10:00:00",
                "end": "2026-10-23T10:30:00",
            },
            {
                "player_id": "jj",
                "field": "A",
                "payment_status": "paid",
                "start": "2026-10-23T10:30:00",
                "end": "2026-10-23T11:00:00",
            },
        ]
        with patch.object(app_mod, "load_reservations", return_value=bookings):
            end = app_mod.resolve_contiguous_booking_end("jj", "A", now=now)
            info = app_mod.booking_play_deadline_info("jj", "A", now=now)
        self.assertEqual(end, datetime(2026, 10, 23, 11, 0, 0))
        self.assertTrue(info["contiguous"])
        self.assertAlmostEqual(info["seconds_left"], 45 * 60, delta=1)

    def test_gap_too_large_does_not_extend(self):
        now = datetime(2026, 10, 23, 10, 15, 0)
        bookings = [
            {
                "player_id": "jj",
                "field": "A",
                "payment_status": "paid",
                "start": "2026-10-23T10:00:00",
                "end": "2026-10-23T10:30:00",
            },
            {
                "player_id": "jj",
                "field": "A",
                "payment_status": "paid",
                "start": "2026-10-23T11:00:00",
                "end": "2026-10-23T11:30:00",
            },
        ]
        with patch.object(app_mod, "load_reservations", return_value=bookings):
            end = app_mod.resolve_contiguous_booking_end("jj", "A", now=now)
        self.assertEqual(end, datetime(2026, 10, 23, 10, 30, 0))


class BookingDeadlineHelpersTests(unittest.TestCase):
    def test_parse_booking_end_ts(self):
        cam = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        end = datetime(2026, 10, 22, 12, 0, 0)
        ts = cam._parse_booking_end_ts(end.isoformat(timespec="seconds"))
        self.assertGreater(ts, 0)
        self.assertEqual(cam._parse_booking_end_ts(""), 0.0)

    def test_seconds_left_none_without_booking_end(self):
        cam = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        cam.__dict__["_booking_deadline_cache"] = {}
        payload = {
            "score_field": "A",
            "fields": {
                "A": {"player_id": "jj", "booking_end": ""},
                "B": {"player_id": "__sim_B__", "booking_end": ""},
            },
        }
        with patch.object(player, "_read_players_fields_payload", return_value=payload), patch.object(
            cam, "_refresh_booking_end_from_server", return_value=None
        ):
            self.assertIsNone(cam._booking_seconds_left_for_field("A"))

    def test_seconds_left_uses_booking_end(self):
        cam = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        cam.__dict__["_booking_deadline_cache"] = {}
        end = datetime.now() + timedelta(seconds=90)
        payload = {
            "score_field": "A",
            "fields": {
                "A": {"player_id": "jj", "booking_end": end.isoformat(timespec="seconds")},
                "B": {"player_id": "__sim_B__", "booking_end": end.isoformat(timespec="seconds")},
            },
        }
        with patch.object(player, "_read_players_fields_payload", return_value=payload), patch.object(
            cam, "_refresh_booking_end_from_server", return_value=None
        ):
            left = cam._booking_seconds_left_for_field("A")
            self.assertIsNotNone(left)
            self.assertGreater(left, 60)
            self.assertLessEqual(left, 91)

    def test_needs_abort_when_under_one_minute_and_live(self):
        cam = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        cam._booking_abort_done = set()
        cam._idle_screensaver_mode = False
        cam.display_phase = "action"
        cam._phase_active = ["A", "B"]
        cam._field_opening_playlists = {}
        cam.video_files = [{"independent_fields": False}]
        cam.playlist_finished = False
        with patch.object(
            cam,
            "_booking_seconds_left_for_field",
            side_effect=lambda fid: 45.0 if fid == "A" else None,
        ), patch.object(cam, "_field_is_live", side_effect=lambda fid: fid == "A"):
            self.assertTrue(cam._field_needs_booking_abort("A"))
            self.assertFalse(cam._field_needs_booking_abort("B"))

    def test_no_abort_when_more_than_one_minute_left(self):
        cam = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        cam._booking_abort_done = set()
        with patch.object(cam, "_booking_seconds_left_for_field", return_value=120.0), patch.object(
            cam, "_field_is_live", return_value=True
        ):
            self.assertFalse(cam._field_needs_booking_abort("A"))

    def test_no_abort_after_done_flag(self):
        cam = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        cam._booking_abort_done = {"A"}
        with patch.object(cam, "_booking_seconds_left_for_field", return_value=10.0), patch.object(
            cam, "_field_is_live", return_value=True
        ):
            self.assertFalse(cam._field_needs_booking_abort("A"))

    def test_sim_partner_follows_score_field_clock(self):
        cam = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        cam.__dict__["_booking_deadline_cache"] = {}
        end = datetime.now() + timedelta(seconds=30)
        payload = {
            "score_field": "A",
            "fields": {
                "A": {"player_id": "jj", "booking_end": end.isoformat(timespec="seconds")},
                "B": {"player_id": "__sim_B__", "booking_end": ""},
            },
        }
        with patch.object(player, "_read_players_fields_payload", return_value=payload), patch.object(
            cam, "_refresh_booking_end_from_server", return_value=None
        ):
            left = cam._booking_seconds_left_for_field("B")
            self.assertIsNotNone(left)
            self.assertLessEqual(left, 31)

    def test_cancel_results_wait_hides_overlay_and_clears_cue(self):
        cam = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        cam._results_epoch = 3
        cam.waiting_for_results = True
        cam.video_end_called = True
        cam.results_timer = None
        cam._field_wait_overlays = {}
        cam._field_result_state = {"A": {"phase": "wait"}}
        cam.waiting_overlay = None
        with patch.object(player, "_clear_image_action_cue") as clear_cue, patch.object(
            cam, "_stop_action_timer"
        ), patch.object(cam, "_stop_goal_advance_poll"), patch.object(
            cam, "_hide_waiting_overlay"
        ) as hide_wait, patch.object(cam, "_hide_projected_results"), patch.object(
            cam, "_hide_field_result_rings"
        ), patch.object(cam, "_stop_results_playback"):
            cam._cancel_results_wait_animation()
        self.assertFalse(cam.waiting_for_results)
        self.assertEqual(cam._results_epoch, 4)
        hide_wait.assert_called_once()
        clear_cue.assert_called_once_with(force_end=True)

    def test_hard_clear_blanks_screens_without_screensaver(self):
        cam = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        cam.__dict__["stop_screen_players"] = MagicMock()
        cam.__dict__["_stop_screen_video"] = MagicMock()
        cam.__dict__["_flash_idle_display"] = MagicMock()
        cam.__dict__["_cancel_results_wait_animation"] = MagicMock()
        with patch.object(player, "_clear_image_action_cue"):
            cam._hard_clear_play_display()
        cam.stop_screen_players.assert_called_once()
        cam._stop_screen_video.assert_called_once_with(clear_screensaver=True)
        cam._flash_idle_display.assert_called_once_with(then_screensaver=False)

    def test_release_posts_full_stop(self):
        cam = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        cam._phase_active = ["A"]
        cam._fields_opening = {"A"}
        cam.check_timer = MagicMock()
        posted = {}

        def fake_post(url, json=None, timeout=None):
            posted["url"] = url
            posted["json"] = json
            return MagicMock()

        with patch.object(cam, "_hard_clear_play_display"), patch.object(
            player, "_write_players_fields_active"
        ), patch.object(cam, "_publish_field_controls"), patch.object(
            cam, "_update_status_file"
        ), patch.object(player, "HAS_REQUESTS", True), patch.object(
            player.requests, "post", side_effect=fake_post
        ), patch.object(player.QtCore, "QTimer") as qtimer:
            qtimer.singleShot = MagicMock()
            cam._close_camera_feed_display_nonblocking()
        self.assertIn("booking-deadline-release", posted.get("url", ""))
        self.assertTrue((posted.get("json") or {}).get("full_stop"))


if __name__ == "__main__":
    unittest.main()
