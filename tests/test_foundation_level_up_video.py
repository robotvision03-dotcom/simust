"""Band promotion videos under static/level_up_videos after finals unlock."""

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


class LevelUpVideoTests(unittest.TestCase):
    def test_resolve_all_band_promotion_clips(self):
        expected = {
            ("L00-Foundation", "L01-Entry"): "foundation_to_entry.mp4",
            ("L01-Entry", "L02-Activated"): "entry_to_activated.mp4",
            ("L02-Activated", "L03-HighPerformance"): "activated_to_high_performance.mp4",
            ("L03-HighPerformance", "L04-Elite"): "high_Performance_to_elite.mp4",
            ("L04-Elite", "L05-WorldClass"): "elite_to_world_class.mp4",
        }
        for key, name in expected.items():
            path = player._resolve_level_up_video(*key)
            self.assertTrue(path, key)
            self.assertTrue(os.path.isfile(path), path)
            self.assertEqual(os.path.basename(path), name)

        # Old static/level_UP_Foundation.mp4 must not be the Foundation→Entry source.
        path = player._resolve_foundation_level_up_video()
        self.assertTrue(path)
        self.assertIn("level_up_videos", path.replace("\\", "/"))
        self.assertEqual(os.path.basename(path), "foundation_to_entry.mp4")

    def test_main_band_id(self):
        self.assertEqual(player._main_band_id("L01-Entry/S1.T4"), "L01-Entry")
        self.assertEqual(player._main_band_id(r"C:\simust\L03-HighPerformance\S3.T4"), "L03-HighPerformance")
        self.assertEqual(player._main_band_id("SF-180N"), "L00-Foundation")
        self.assertEqual(player._main_band_id("L04-Elite/S3.T4"), "L04-Elite")

    def test_should_play_only_after_sf180_pass_to_entry(self):
        cls = player.SmartPlayerWindow
        fake = _fake(
            _level_up_video_played=False,
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
            _phase_field_levels={},
            _field_opening_playlists={},
        )
        fake._phase_was_foundation_sf180 = types.MethodType(
            cls._phase_was_foundation_sf180, fake
        )
        fake._phase_context_bits = types.MethodType(cls._phase_context_bits, fake)
        fake._phase_main_band = types.MethodType(cls._phase_main_band, fake)
        fake._continue_main_band = types.MethodType(cls._continue_main_band, fake)
        fake._level_up_transition = types.MethodType(cls._level_up_transition, fake)
        fake._should_play_foundation_level_up = types.MethodType(
            cls._should_play_foundation_level_up, fake
        )
        fake._should_play_level_up_video = types.MethodType(
            cls._should_play_level_up_video, fake
        )
        self.assertTrue(fake._phase_was_foundation_sf180())
        self.assertTrue(
            fake._should_play_foundation_level_up(
                {"level": "L01-Entry/S1.T1", "passed": True}
            )
        )

        # Failed 180N, still on Foundation — no celebration.
        fake._after_final = {"passed": False, "level": "L00-Foundation"}
        fake._level_up_video_played = False
        fake._foundation_level_up_played = False
        self.assertFalse(
            fake._should_play_foundation_level_up(
                {"level": "L00-Foundation", "subdirectory": "SF-180N"}
            )
        )

        # SF-110N pass must not show the Foundation→Entry celebration.
        fake._after_final = {"passed": True, "level": "L00-Foundation"}
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

    def test_entry_to_activated_and_later_bands(self):
        cls = player.SmartPlayerWindow
        cases = [
            (
                "L01-Entry/S1.T5",
                r"C:\simust\L01-Entry\S1.T5",
                "L02-Activated/S1.T1",
                "entry_to_activated.mp4",
            ),
            (
                "L02-Activated/S2.T5",
                r"C:\simust\L02-Activated\S2.T5",
                "L03-HighPerformance/S1.T1",
                "activated_to_high_performance.mp4",
            ),
            (
                "L03-HighPerformance/S3.T5",
                r"C:\simust\L03-HighPerformance\S3.T5",
                "L04-Elite/S1.T1",
                "high_Performance_to_elite.mp4",
            ),
            (
                "L04-Elite/S3.T5",
                r"C:\simust\L04-Elite\S3.T5",
                "L05-WorldClass/S1.T1",
                "elite_to_world_class.mp4",
            ),
        ]
        for played, directory, nxt, basename in cases:
            with self.subTest(played=played):
                fake = _fake(
                    _level_up_video_played=False,
                    _foundation_level_up_played=False,
                    _finals_from_band=None,
                    _phase_index=0,
                    _run_phases=[
                        {
                            "subdirectory": "",
                            "mode_id": "",
                            "directory": directory,
                            "label": played,
                            "field_levels": {"A": played},
                        }
                    ],
                    _after_final={"passed": True, "level": nxt},
                    mode_id="",
                    video_directory=directory,
                    _phase_subdirectory="",
                    _phase_field_levels={"A": played},
                    _field_opening_playlists={},
                )
                fake._phase_context_bits = types.MethodType(cls._phase_context_bits, fake)
                fake._phase_main_band = types.MethodType(cls._phase_main_band, fake)
                fake._continue_main_band = types.MethodType(cls._continue_main_band, fake)
                fake._phase_was_foundation_sf180 = types.MethodType(
                    cls._phase_was_foundation_sf180, fake
                )
                fake._level_up_transition = types.MethodType(cls._level_up_transition, fake)
                hit = fake._level_up_transition({"level": nxt, "passed": True})
                self.assertIsNotNone(hit, played)
                self.assertEqual(os.path.basename(hit[2]), basename)

                # Same-band continue must not play a promotion clip.
                fake._after_final = {"passed": True, "level": played}
                self.assertIsNone(
                    fake._level_up_transition({"level": played, "passed": True})
                )

    def test_prefer_disk_band_over_stale_final_level(self):
        """Stale after_final (played set) must not hide Activated→HP when disk advanced."""
        cls = player.SmartPlayerWindow
        fake = _fake(
            _level_up_video_played=False,
            _foundation_level_up_played=False,
            _finals_from_band="L02-Activated",
            _phase_index=0,
            _run_phases=[
                {
                    "subdirectory": "",
                    "mode_id": "",
                    "directory": r"C:\simust\L02-Activated\S2.T5",
                    "label": "L02-Activated/S2.T5",
                    "field_levels": {"A": "L02-Activated/S2.T5"},
                }
            ],
            # Stale stamp still says Activated; live merge should prefer HP.
            _after_final={"passed": True, "level": "L02-Activated/S2.T5"},
            mode_id="",
            video_directory=r"C:\simust\L02-Activated\S2.T5",
            _phase_subdirectory="",
            _phase_field_levels={"A": "L02-Activated/S2.T5"},
            _field_opening_playlists={},
        )
        fake._phase_context_bits = types.MethodType(cls._phase_context_bits, fake)
        fake._phase_main_band = types.MethodType(cls._phase_main_band, fake)
        fake._continue_main_band = types.MethodType(cls._continue_main_band, fake)
        fake._phase_was_foundation_sf180 = types.MethodType(
            cls._phase_was_foundation_sf180, fake
        )
        fake._level_up_transition = types.MethodType(cls._level_up_transition, fake)
        hit = fake._level_up_transition(
            {"level": "L03-HighPerformance/S1.T1", "passed": True}
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "L02-Activated")
        self.assertEqual(hit[1], "L03-HighPerformance")
        self.assertEqual(os.path.basename(hit[2]), "activated_to_high_performance.mp4")

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
            _level_up_video_played=False,
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
            _phase_field_levels={},
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
        fake._phase_context_bits = types.MethodType(cls._phase_context_bits, fake)
        fake._phase_was_foundation_sf180 = types.MethodType(
            cls._phase_was_foundation_sf180, fake
        )
        fake._phase_main_band = types.MethodType(cls._phase_main_band, fake)
        fake._continue_main_band = types.MethodType(cls._continue_main_band, fake)
        fake._level_up_transition = types.MethodType(cls._level_up_transition, fake)
        fake._publish_field_controls = lambda: None
        fake._restart_highest_level = lambda info: (
            calls.__setitem__("restart", calls["restart"] + 1) or True
        )

        def _play_then(on_done, path=None):
            calls["level_up"] += 1
            self.assertTrue(path)
            self.assertEqual(os.path.basename(path), "foundation_to_entry.mp4")
            if callable(on_done):
                on_done()

        fake._play_level_up_then = _play_then
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
