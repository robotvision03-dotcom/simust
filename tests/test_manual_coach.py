"""Manual coach: command files, layout, and screen normalize."""

import json
import os
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import simust_manual_coach as manual  # noqa: E402
import smart_simust_player as player  # noqa: E402


class ManualCoachHelpersTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old_cmd = manual.CMD_FILE
        self._old_queue = manual.QUEUE_FILE
        self._old_status = manual.STATUS_FILE
        manual.CMD_FILE = os.path.join(self._tmpdir.name, "cmd.json")
        manual.QUEUE_FILE = os.path.join(self._tmpdir.name, "queue.json")
        manual.STATUS_FILE = os.path.join(self._tmpdir.name, "status.json")

    def tearDown(self):
        manual.CMD_FILE = self._old_cmd
        manual.QUEUE_FILE = self._old_queue
        manual.STATUS_FILE = self._old_status
        self._tmpdir.cleanup()

    def test_normalize_and_layout(self):
        self.assertEqual(manual.normalize_screen("a3"), "A3")
        self.assertEqual(manual.normalize_screen("B6"), "B6")
        self.assertIsNone(manual.normalize_screen("C1"))
        self.assertEqual(manual.field_for_screen("A2"), "A")
        self.assertEqual(manual.field_for_screen("B4"), "B")
        layout = manual.layout_for_operator()
        self.assertEqual(len(layout["A"]), 6)
        self.assertEqual(len(layout["B"]), 6)
        self.assertEqual({row["id"] for row in layout["A"]}, set(manual.FIELD_A_LAYOUT))
        self.assertEqual({row["id"] for row in layout["B"]}, set(manual.FIELD_B_LAYOUT))
        # A1–A6 use the same panel positions as B1–B6.
        for n in range(1, 7):
            a = next(row for row in layout["A"] if row["id"] == f"A{n}")
            b = next(row for row in layout["B"] if row["id"] == f"B{n}")
            self.assertEqual(a["left"], b["left"], n)
            self.assertEqual(a["top"], b["top"], n)

    def test_write_command_increments_seq(self):
        first = manual.write_command("cue", screen="A1")
        second = manual.write_command("cue", screen="B3")
        self.assertEqual(first["cmd"], "cue")
        self.assertEqual(first["screen"], "A1")
        self.assertEqual(second["screen"], "B3")
        self.assertEqual(int(second["seq"]), int(first["seq"]) + 1)
        status = manual.write_status(
            active=True, lit_screen="B3", waiting_hit=True, message="Lit B3"
        )
        self.assertTrue(status["active"])
        self.assertEqual(manual.read_status()["lit_screen"], "B3")
        clear = manual.write_command("clear")
        self.assertEqual(clear["cmd"], "clear")
        self.assertIsNone(clear["screen"])

    def test_queue_keeps_rapid_cues(self):
        """Rapid Field A/B taps must all survive until the player drains them."""
        a = manual.write_command("cue", screen="A1")
        b = manual.write_command("cue", screen="B2")
        c = manual.write_command("cue", screen="A3")
        pending = manual.drain_commands(0)
        self.assertEqual(
            [row["screen"] for row in pending],
            ["A1", "B2", "A3"],
        )
        self.assertEqual(
            [int(row["seq"]) for row in pending],
            [int(a["seq"]), int(b["seq"]), int(c["seq"])],
        )
        self.assertEqual(manual.drain_commands(int(c["seq"])), [])
        # New tap after drain is still delivered.
        d = manual.write_command("cue", screen="B6")
        again = manual.drain_commands(int(c["seq"]))
        self.assertEqual([row["screen"] for row in again], ["B6"])
        self.assertEqual(int(again[0]["seq"]), int(d["seq"]))

    def test_resolve_manual_coach_pass_image_finds_still(self):
        path = player._resolve_manual_coach_pass_image(
            "C:/Users/siama/Documents/simust_player"
        )
        # Repo pass.jpeg or Foundation SF-*/pass.jpeg must resolve.
        self.assertTrue(path, "expected a pass still image")
        self.assertTrue(os.path.isfile(path), path)
        self.assertIn(os.path.splitext(path)[1].lower(), {".png", ".jpg", ".jpeg", ".webp", ".bmp"})

    def test_retarget_sim_does_not_restart_live_aim(self):
        """Soft expands must not restart a sim ball already flying at a lit screen."""
        try:
            import simust_realtime as rt
        except Exception as exc:
            self.skipTest(f"simust_realtime unavailable: {exc}")

        class FakeSim:
            def __init__(self):
                self.active = True
                self.screens = ["A1"]
                self.starts = []

            def start_action(self, *args, **kwargs):
                self.starts.append((args, kwargs))
                screens = args[1] if len(args) > 1 else []
                self.screens = [str(s) for s in screens][:1]
                self.active = True

            def end_action(self):
                self.active = False

        owner = rt.SimustRealtimeCamera
        proc = SimpleNamespace(
            simulators={"A": FakeSim()},
            _field_is_simulated=lambda fid: True,
        )
        proc._manual_or_finish_retarget_sim = owner._manual_or_finish_retarget_sim.__get__(
            proc, owner
        )
        ch = SimpleNamespace(
            current_action="PASS",
            current_qr_block={"action_in_set": 1, "actions_in_set": 12, "test_num": 1},
            _cylinder_scored_screens=set(),
        )
        # Expanding A1→A1,A2 while A1 is still the live aim must not restart.
        proc._manual_or_finish_retarget_sim(
            "A", ch, ["A1", "A2"], scored=set(), force=True
        )
        self.assertEqual(proc.simulators["A"].starts, [])
        # After A1 scores, force retarget to A2.
        proc._manual_or_finish_retarget_sim(
            "A", ch, ["A2"], scored={"A1"}, force=True
        )
        self.assertEqual(len(proc.simulators["A"].starts), 1)
        self.assertEqual(proc.simulators["A"].screens, ["A2"])

    def test_stale_correct_does_not_clear_fresh_light(self):
        """Old live_action_result Corrects must not wipe a newly lit Manual screen."""
        result_path = os.path.join(self._tmpdir.name, "live_action_result.json")
        lit_at = time.time()
        with open(result_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "fields": {
                        "A": {
                            "result": "Correct",
                            "winning_screen": "A1",
                            "seq": 4,
                            "ts": lit_at - 30.0,
                            "clear_now": True,
                            "by_seq": {
                                "4": {
                                    "result": "Correct",
                                    "winning_screen": "A1",
                                    "seq": 4,
                                    "ts": lit_at - 30.0,
                                    "clear_now": True,
                                }
                            },
                        }
                    }
                },
                handle,
            )
        cleared = []
        coach = SimpleNamespace(
            _manual_coach_lit_screens={"A1"},
            _manual_coach_lit_at={"A1": lit_at},
            _manual_coach_hit_seen=set(),
            _flash_seq=1,
            _goal_token_matches=lambda sid, win, fid: str(sid).upper() == str(win).upper(),
            _manual_coach_lit_list=lambda: ["A1"],
            _manual_coach_clear_screen=lambda sid, reason="hit": cleared.append(sid),
        )
        with patch.object(player, "LIVE_ACTION_RESULT_FILE", result_path):
            player.SmartPlayerWindow._manual_coach_check_hit(coach)
        self.assertEqual(cleared, [])
        # A Correct timestamped after the light must still clear the screen.
        with open(result_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "fields": {
                        "A": {
                            "result": "Correct",
                            "winning_screen": "A1",
                            "seq": 1,
                            "ts": lit_at + 0.2,
                            "clear_now": True,
                        }
                    }
                },
                handle,
            )
        with patch.object(player, "LIVE_ACTION_RESULT_FILE", result_path):
            player.SmartPlayerWindow._manual_coach_check_hit(coach)
        self.assertEqual(cleared, ["A1"])


if __name__ == "__main__":
    unittest.main()
