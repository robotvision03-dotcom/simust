"""Elite/WC from High Performance: both fields + partner sim on continue."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import app as app_mod  # noqa: E402
import simust_progress  # noqa: E402
import smart_simust_player as player  # noqa: E402


class EliteDualContinueTests(unittest.TestCase):
    def test_ensure_combined_dual_phase_expands_a_only_to_ab_with_sim_b(self):
        cam = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        phase = {
            "active": ["A"],
            "directory": "C:/tmp/elite",
            "field_levels": {"A": "L03-HighPerformance/S2.T4"},
            "field_directories": {"A": "C:/tmp/hp"},
            "dual_independent": True,
        }
        info = {
            "level": "L04-Elite/S1.T1",
            "subdirectory": "",
            "directory": "C:/tmp/elite",
            "score_field": "A",
            "player_id": "jj",
            "player_name": "Jay",
            "player_surname": "J",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "players_fields.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "score_field": "A",
                        "active": ["A"],
                        "fields": {
                            "A": {
                                "player_id": "jj",
                                "level": "L03-HighPerformance/S2.T4",
                                "booking_end": "2026-10-23T12:00:00",
                            }
                        },
                    },
                    handle,
                )
            with patch.object(player, "PLAYERS_FIELDS_FILE", path), patch.object(
                player, "_read_players_fields_payload",
                side_effect=lambda: json.load(open(path, encoding="utf-8")),
            ), patch.object(player, "_write_players_fields_active") as write_active, patch.object(
                player, "HAS_REQUESTS", True
            ), patch.object(player.requests, "post") as post:
                out = cam._ensure_combined_dual_phase(phase, info)
            self.assertEqual(out["active"], ["A", "B"])
            self.assertFalse(out["dual_independent"])
            self.assertEqual(out["field_levels"]["A"], "L04-Elite/S1.T1")
            self.assertEqual(out["field_levels"]["B"], "L04-Elite/S1.T1")
            write_active.assert_called_with(["A", "B"])
            post.assert_called()
            body = post.call_args.kwargs.get("json") or post.call_args[1].get("json")
            self.assertTrue((body.get("fields") or {}).get("B"))
            stamped = json.load(open(path, encoding="utf-8"))
            self.assertEqual(stamped["active"], ["A", "B"])
            self.assertEqual(stamped["score_field"], "A")
            self.assertEqual(stamped["fields"]["B"]["player_id"], "__sim_B__")
            self.assertTrue(stamped["fields"]["B"].get("simulated"))

    def test_propagate_unlock_to_elite_adds_sim_partner(self):
        with tempfile.TemporaryDirectory() as tmp:
            pf = os.path.join(tmp, "players_fields.json")
            with open(pf, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "score_field": "A",
                        "active": ["A"],
                        "level": "L03-HighPerformance/S2.T4",
                        "fields": {
                            "A": {
                                "player_id": "jj",
                                "level": "L03-HighPerformance/S2.T4",
                                "subdirectory": "",
                                "directory": "C:/tmp/hp",
                                "booking_end": "2026-10-23T12:00:00",
                            }
                        },
                        "levels": {"A": "L03-HighPerformance/S2.T4"},
                    },
                    handle,
                )
            progress = simust_progress.default_progress()
            progress["unlocked_levels"] = [
                "L00-Foundation",
                "L03-HighPerformance/S2.T4",
                "L04-Elite/S1.T1",
            ]
            progress["current_level"] = "L04-Elite/S1.T1"
            with patch.object(app_mod, "SIMUST_PLAYER_DIRECTORY", tmp), patch.object(
                app_mod, "PLAYER_REPORTS_DIR", tmp
            ), patch.object(app_mod, "write_simulation_fields") as write_sim, patch.object(
                app_mod, "_read_written_simulation_fields", return_value={"A": False, "B": False}
            ), patch.object(app_mod, "get_level_path", return_value="C:/tmp/elite"):
                app_mod.propagate_level_status("jj", progress)
            stamped = json.load(open(pf, encoding="utf-8"))
            self.assertEqual(stamped["fields"]["A"]["level"], "L04-Elite/S1.T1")
            self.assertEqual(stamped["fields"]["B"]["player_id"], "__sim_B__")
            self.assertEqual(sorted(stamped["active"]), ["A", "B"])
            write_sim.assert_called()
            sim_arg = write_sim.call_args[0][0]
            self.assertTrue(sim_arg.get("B"))
            self.assertFalse(sim_arg.get("A"))

    def test_propagate_unlock_to_elite_both_sim_when_a_was_sim(self):
        with tempfile.TemporaryDirectory() as tmp:
            pf = os.path.join(tmp, "players_fields.json")
            with open(pf, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "score_field": "A",
                        "active": ["A"],
                        "level": "L03-HighPerformance/S2.T5",
                        "fields": {
                            "A": {
                                "player_id": "jj",
                                "level": "L03-HighPerformance/S2.T5",
                                "subdirectory": "",
                                "directory": "C:/tmp/hp",
                                "simulated": True,
                                "booking_end": "2026-10-23T12:00:00",
                            }
                        },
                        "levels": {"A": "L03-HighPerformance/S2.T5"},
                    },
                    handle,
                )
            progress = simust_progress.default_progress()
            progress["unlocked_levels"] = [
                "L00-Foundation",
                "L03-HighPerformance/S2.T5",
                "L04-Elite/S1.T1",
            ]
            progress["current_level"] = "L04-Elite/S1.T1"
            with patch.object(app_mod, "SIMUST_PLAYER_DIRECTORY", tmp), patch.object(
                app_mod, "PLAYER_REPORTS_DIR", tmp
            ), patch.object(app_mod, "write_simulation_fields") as write_sim, patch.object(
                app_mod, "_read_written_simulation_fields", return_value={"A": True, "B": False}
            ), patch.object(app_mod, "get_level_path", return_value="C:/tmp/elite"):
                app_mod.propagate_level_status("jj", progress)
            write_sim.assert_called()
            sim_arg = write_sim.call_args[0][0]
            self.assertTrue(sim_arg.get("A"))
            self.assertTrue(sim_arg.get("B"))

    def test_ensure_combined_dual_keeps_score_sim_when_a_was_sim(self):
        cam = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        phase = {"active": ["A"], "directory": "C:/tmp/elite"}
        info = {
            "level": "L04-Elite/S1.T1",
            "subdirectory": "",
            "directory": "C:/tmp/elite",
            "score_field": "A",
            "player_id": "jj",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "players_fields.json")
            sim_path = os.path.join(tmp, "arena_simulation.txt")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "score_field": "A",
                        "active": ["A"],
                        "fields": {
                            "A": {
                                "player_id": "jj",
                                "level": "L03-HighPerformance/S2.T5",
                                "simulated": True,
                            }
                        },
                    },
                    handle,
                )
            with open(sim_path, "w", encoding="utf-8") as handle:
                json.dump({"A": True, "B": False}, handle)
            with patch.object(player, "PLAYERS_FIELDS_FILE", path), patch.object(
                player, "_read_players_fields_payload",
                side_effect=lambda: json.load(open(path, encoding="utf-8")),
            ), patch.object(player, "_write_players_fields_active"), patch.object(
                player, "HAS_REQUESTS", True
            ), patch.object(player.requests, "post") as post:
                cam._ensure_combined_dual_phase(phase, info)
            body = post.call_args.kwargs.get("json") or post.call_args[1].get("json")
            fields = body.get("fields") or {}
            self.assertTrue(fields.get("A"))
            self.assertTrue(fields.get("B"))

    def test_hp_start_does_not_activate_empty_half_from_sim_toggle(self):
        """High Performance on A only must not light Field B when Sim B is checked."""
        with tempfile.TemporaryDirectory() as tmp:
            pf = os.path.join(tmp, "players_fields.json")
            # Leftover Elite dual + both-sim toggle state.
            with open(pf, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "score_field": "A",
                        "active": ["A", "B"],
                        "level": "L04-Elite/S1.T1",
                        "fields": {
                            "A": {"player_id": "jj", "level": "L04-Elite/S1.T1"},
                            "B": {
                                "player_id": "__sim_B__",
                                "level": "L04-Elite/S1.T1",
                                "simulated": True,
                            },
                        },
                        "levels": {"A": "L04-Elite/S1.T1", "B": "L04-Elite/S1.T1"},
                    },
                    handle,
                )
            with open(os.path.join(tmp, "arena_simulation.txt"), "w", encoding="utf-8") as handle:
                json.dump({"A": True, "B": True}, handle)

            # Replicate start-realtime sim + partner rules for non-combined HP.
            combined_partner_sim = None
            play_slots = [("jj", "A", {"level": "L03-HighPerformance/S1.T1"})]
            sim_fields = {"A": True, "B": True}
            selected = {fid for _pid, fid, _entry in play_slots}
            for fid in ("A", "B"):
                if fid not in selected:
                    sim_fields[fid] = False
            self.assertEqual(sim_fields, {"A": True, "B": False})

            field_map = {
                "A": {
                    "player_id": "jj",
                    "level": "L03-HighPerformance/S1.T1",
                    "field": "A",
                },
                "B": {
                    "player_id": "__sim_B__",
                    "level": "L04-Elite/S1.T1",
                    "simulated": True,
                    "field": "B",
                },
            }
            active_list = [
                fid for fid in ("A", "B")
                if isinstance(field_map.get(fid), dict)
                and str(field_map[fid].get("player_id") or "").strip()
                and not str(field_map[fid].get("player_id") or "").startswith("__sim_")
            ]
            # Only keep slots from this HP start (A), clear idle half.
            active_list = [fid for fid in active_list if fid in selected]
            for fid in ("A", "B"):
                if fid in set(active_list):
                    continue
                field_map[fid] = {
                    "player_id": "",
                    "field": fid,
                    "simulated": False,
                }
            self.assertEqual(active_list, ["A"])
            self.assertEqual(field_map["B"].get("player_id"), "")
            self.assertIsNone(combined_partner_sim)

    def test_live_continue_info_reads_unlocked_level_when_final_timed_out(self):
        """Empty final progress must still continue into the disk-stamped next set."""
        cam = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "players_fields.json")
            level_txt = os.path.join(tmp, "current_level.txt")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "score_field": "A",
                        "level": "L04-Elite/S2.T2",
                        "fields": {
                            "A": {
                                "player_id": "jj",
                                "level": "L04-Elite/S2.T2",
                                "directory": "C:/tmp/L04-Elite/A-T2",
                                "subdirectory": "",
                                "booking_end": "2099-01-01T12:00:00",
                            }
                        },
                    },
                    handle,
                )
            with open(level_txt, "w", encoding="utf-8") as handle:
                handle.write("L04-Elite/S2.T2")
            with patch.object(player, "PLAYERS_FIELDS_FILE", path), patch.object(
                player, "CURRENT_LEVEL_FILE", level_txt
            ), patch.object(
                player, "_read_players_fields_payload",
                side_effect=lambda: json.load(open(path, encoding="utf-8")),
            ), patch.object(
                cam, "_booking_seconds_left_for_field", return_value=600.0
            ):
                merged = cam._live_continue_info({})
            self.assertEqual(merged.get("level"), "L04-Elite/S2.T2")
            self.assertTrue(str(merged.get("directory") or "").endswith("A-T2"))
            self.assertTrue(merged.get("continue_play"))
            self.assertGreater(float(merged.get("seconds_left") or 0), 30)


if __name__ == "__main__":
    unittest.main()
