"""Foundation SF-180N pass shows level_UP_Foundation before Entry continue."""

import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import smart_simust_player as player  # noqa: E402


def _fake(**kwargs):
    obj = types.SimpleNamespace(**kwargs)
    return obj


class FoundationLevelUpVideoTests(unittest.TestCase):
    def test_resolve_finds_static_level_up_foundation(self):
        path = player._resolve_foundation_level_up_video()
        self.assertTrue(path, "expected static/level_UP_Foundation.mp4")
        self.assertTrue(os.path.isfile(path), path)
        self.assertIn("foundation", os.path.basename(path).lower())
        self.assertIn("level", os.path.basename(path).lower())

    def test_should_play_only_after_sf180_pass_to_entry(self):
        cls = player.SmartPlayerWindow
        fake = _fake(
            _foundation_level_up_played=False,
            _phase_index=0,
            _run_phases=[
                {
                    "subdirectory": "SF-180N",
                    "mode_id": "SF-180N",
                    "directory": r"C:\simust\L00-Foundation\SF-180N",
                    "label": "L00-Foundation/SF-180N",
                }
            ],
            _after_final={"passed": True, "level": "L01-Entry/S1.T1"},
            mode_id="SF-180N",
            video_directory=r"C:\simust\L00-Foundation\SF-180N",
            _phase_subdirectory="SF-180N",
            _field_opening_playlists={},
        )
        fake._phase_was_foundation_sf180 = types.MethodType(
            cls._phase_was_foundation_sf180, fake
        )
        fake._should_play_foundation_level_up = types.MethodType(
            cls._should_play_foundation_level_up, fake
        )
        self.assertTrue(fake._phase_was_foundation_sf180())
        self.assertTrue(
            fake._should_play_foundation_level_up(
                {"level": "L01-Entry/S1.T1", "passed": True}
            )
        )

        # Failed 180N, still on Foundation — no celebration.
        fake._after_final = {"passed": False}
        fake._foundation_level_up_played = False
        self.assertFalse(
            fake._should_play_foundation_level_up(
                {"level": "L00-Foundation", "subdirectory": "SF-180N"}
            )
        )

        # SF-110N pass must not show the Foundation→Entry celebration.
        fake._after_final = {"passed": True}
        fake._run_phases[0].update(
            {
                "subdirectory": "SF-110N",
                "mode_id": "SF-110N",
                "directory": r"C:\simust\L00-Foundation\SF-110N",
                "label": "L00-Foundation/SF-110N",
            }
        )
        fake.mode_id = "SF-110N"
        fake._phase_subdirectory = "SF-110N"
        fake.video_directory = r"C:\simust\L00-Foundation\SF-110N"
        self.assertFalse(fake._phase_was_foundation_sf180())
        self.assertFalse(
            fake._should_play_foundation_level_up(
                {"level": "L00-Foundation", "subdirectory": "SF-180N"}
            )
        )

    def test_admin_manual_play_continues_without_booking(self):
        """Admin password play (no reservation) must still continue after finals."""
        cls = player.SmartPlayerWindow
        cam = cls.__new__(cls)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "players_fields.json")
            level_txt = os.path.join(tmp, "current_level.txt")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "admin_test": True,
                        "score_field": "A",
                        "level": "L01-Entry/S1.T1",
                        "fields": {
                            "A": {
                                "player_id": "jj",
                                "level": "L01-Entry/S1.T1",
                                "subdirectory": "",
                                "directory": r"C:\simust\L01-Entry\S1.T1",
                                "booking_end": "",
                            }
                        },
                    },
                    handle,
                )
            with open(level_txt, "w", encoding="utf-8") as handle:
                handle.write("L01-Entry/S1.T1")
            with patch.object(player, "PLAYERS_FIELDS_FILE", path), patch.object(
                player, "CURRENT_LEVEL_FILE", level_txt
            ), patch.object(
                player,
                "_read_players_fields_payload",
                side_effect=lambda: json.load(open(path, encoding="utf-8")),
            ), patch.object(
                cam, "_booking_seconds_left_for_field", return_value=None
            ):
                cam._is_admin_test_session = types.MethodType(
                    cls._is_admin_test_session, cam
                )
                cam._live_continue_info = types.MethodType(
                    cls._live_continue_info, cam
                )
                cam._should_continue_booked_play = types.MethodType(
                    cls._should_continue_booked_play, cam
                )
                cam._is_terminal_training_level = cls._is_terminal_training_level
                merged = cam._live_continue_info(
                    {"passed": True, "continue_play": True, "level": "L01-Entry/S1.T1"}
                )
                self.assertTrue(merged.get("admin_test"))
                self.assertGreater(float(merged.get("seconds_left") or 0), 30)
                self.assertTrue(
                    cam._should_continue_booked_play(
                        {
                            "passed": True,
                            "continue_play": True,
                            "level": "L01-Entry/S1.T1",
                            "admin_test": True,
                            "seconds_left": 0,
                        }
                    )
                )

    def test_continue_booked_plays_foundation_level_up_for_admin(self):
        cls = player.SmartPlayerWindow
        calls = {"level_up": 0, "restart": 0}

        fake = _fake(
            _foundation_level_up_played=False,
            _phase_index=0,
            _run_phases=[
                {
                    "subdirectory": "SF-180N",
                    "mode_id": "SF-180N",
                    "directory": r"C:\simust\L00-Foundation\SF-180N",
                    "label": "L00-Foundation/SF-180N",
                    "active": ["A"],
                }
            ],
            _after_final={
                "passed": True,
                "continue_play": True,
                "admin_test": True,
                "seconds_left": 0,
                "level": "L01-Entry/S1.T1",
                "subdirectory": "",
                "directory": r"C:\simust\L01-Entry\S1.T1",
            },
            mode_id="SF-180N",
            video_directory=r"C:\simust\L00-Foundation\SF-180N",
            _phase_subdirectory="SF-180N",
            _field_opening_playlists={},
            playlist_finished=True,
        )

        def _live(info):
            out = dict(info or {})
            out.setdefault("admin_test", True)
            out.setdefault("seconds_left", 24 * 3600)
            out.setdefault("continue_play", True)
            return out

        fake._live_continue_info = _live
        fake._should_continue_booked_play = lambda info: True
        fake._phase_was_foundation_sf180 = types.MethodType(
            cls._phase_was_foundation_sf180, fake
        )
        fake._should_play_foundation_level_up = types.MethodType(
            cls._should_play_foundation_level_up, fake
        )
        fake._publish_field_controls = lambda: None
        fake._restart_highest_level = lambda info: (
            calls.__setitem__("restart", calls["restart"] + 1) or True
        )

        def _play_then(on_done):
            calls["level_up"] += 1
            if callable(on_done):
                on_done()

        fake._play_foundation_level_up_then = _play_then
        fake._continue_booked_after_finals = types.MethodType(
            cls._continue_booked_after_finals, fake
        )
        self.assertTrue(
            fake._continue_booked_after_finals(dict(fake._after_final))
        )
        self.assertEqual(calls["level_up"], 1)
        self.assertEqual(calls["restart"], 1)


if __name__ == "__main__":
    unittest.main()
