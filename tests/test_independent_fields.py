"""Dual fields stay independent except Elite / World Class."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import smart_simust_player as player  # noqa: E402


class IndependentComposeTests(unittest.TestCase):
    def test_compose_keeps_each_fields_own_goal(self):
        parts = {
            "A": [
                {
                    "test_num": 1,
                    "action_in_set": 1,
                    "actions_in_set": 2,
                    "on_ms": 3000,
                    "finish_balls": True,
                    "advance_on_goal": True,
                    "field_screens": {"A": ["A2"]},
                    "screen_images": {"A2": "a2.png", "A3": "a3.png"},
                    "budget_ms": 6000,
                },
                {
                    "test_num": 1,
                    "action_in_set": 2,
                    "actions_in_set": 2,
                    "on_ms": 3000,
                    "finish_balls": True,
                    "advance_on_goal": True,
                    "field_screens": {"A": ["A3"]},
                    "screen_images": {"A2": "a2.png", "A3": "a3.png"},
                    "budget_ms": 6000,
                },
            ],
            "B": [
                {
                    "test_num": 1,
                    "action_in_set": 1,
                    "actions_in_set": 2,
                    "on_ms": 2400,
                    "finish_balls": True,
                    "advance_on_goal": True,
                    "field_screens": {"B": ["B1"]},
                    "screen_images": {"B1": "b1.png", "B2": "b2.png"},
                    "budget_ms": 4800,
                },
                {
                    "test_num": 1,
                    "action_in_set": 2,
                    "actions_in_set": 2,
                    "on_ms": 2400,
                    "finish_balls": True,
                    "advance_on_goal": True,
                    "field_screens": {"B": ["B2"]},
                    "screen_images": {"B1": "b1.png", "B2": "b2.png"},
                    "budget_ms": 4800,
                },
            ],
        }
        first = player._compose_independent_entry(parts, {"A": 0, "B": 0})
        self.assertEqual(first["field_screens"], {"A": ["A2"], "B": ["B1"]})
        self.assertTrue(first["independent_fields"])
        advanced_a = player._compose_independent_entry(parts, {"A": 1, "B": 0})
        self.assertEqual(advanced_a["field_screens"], {"A": ["A3"], "B": ["B1"]})
        self.assertEqual(advanced_a["field_meta"]["A"]["action_in_set"], 2)
        self.assertEqual(advanced_a["field_meta"]["B"]["action_in_set"], 1)

    def test_zip_seeds_one_live_entry(self):
        parts = {
            "A": [{"test_num": 1, "field_screens": {"A": ["A1"]}, "screen_images": {"A1": "x"}}],
            "B": [{"test_num": 1, "field_screens": {"B": ["B1"]}, "screen_images": {"B1": "y"}}],
        }
        merged = player._zip_field_action_playlists(parts)
        self.assertEqual(len(merged), 1)
        self.assertTrue(merged[0]["independent_fields"])

    def test_opening_card_puts_band_and_test_on_own_lines(self):
        text = player._level_card_text(
            "L04-Elite/S1.T2",
            "",
            {"test_num": 3, "budget_ms": 54000, "actions_in_set": 12, "finish_balls": True},
            [],
        )
        self.assertEqual(text.split("\n"), ["S1.T2", "12 Actions"])
        self.assertNotIn("Elite", text)
        self.assertNotIn("54.00", text)


class IndependentClockTests(unittest.TestCase):
    def test_spent_shared_clock_does_not_end_the_other_field(self):
        """Foundation's 30s clock must not be one action. The next step stays open."""
        inst = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        entry = {
            "independent_fields": True,
            "budget_ms": 30000,
            "test_num": 1,
            "on_ms": 3000,
            "fixed_timing": True,
            "field_screens": {"A": ["A2"], "B": ["B1"]},
        }
        inst.player_speed = 1.0
        inst.video_files = [entry]
        inst.current_video_index = 0
        inst._budget_test = 1
        inst._budget_started_at = player.time.perf_counter() - 40.0
        delay = inst._label_action_delay_ms(entry)
        self.assertGreater(delay, 40)
        self.assertEqual(delay, 3000)


class FieldContinuesAloneTests(unittest.TestCase):
    def _player(self, parts):
        inst = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        inst._field_opening_playlists = parts
        inst._independent_index = {"A": 0, "B": 0}
        inst._independent_done = {"A": False, "B": False}
        inst._field_result_state = {}
        inst._field_hold_until = {}
        inst._field_wait_overlays = {}
        inst.image_canvas = None
        inst.video_files = player._zip_field_action_playlists(parts)
        inst.current_video_index = 0
        inst.display_phase = "action"
        inst._action_phase = "label"
        inst._flash_seq = 4
        inst._apply_label_phase = lambda: None
        inst._stop_action_timer = lambda: None
        inst._stop_goal_advance_poll = lambda: None
        inst._start_goal_advance_poll = lambda: None
        return inst

    def test_one_field_goal_does_not_advance_the_other(self):
        def row(fid, n, test_num=1):
            screen = f"{fid}{n}"
            return {
                "test_num": test_num,
                "action_in_set": n,
                "actions_in_set": 2,
                "on_ms": 3000,
                "field_screens": {fid: [screen]},
                "screen_images": {screen: f"{screen}.png"},
            }
        parts = {
            "A": [row("A", 1), row("A", 2)],
            "B": [row("B", 1), row("B", 2)],
        }
        inst = self._player(parts)
        inst._field_hold_until = {
            "A": player.time.perf_counter() + 5.0,
            "B": 0.0,
        }
        patched = []
        inst._patch_independent_fields = lambda entry, fields: patched.append(set(fields))
        inst._finish_due_independent_fields()
        self.assertEqual(inst._independent_index, {"A": 0, "B": 1})
        self.assertEqual(patched, [{"B"}])
        self.assertFalse(inst._independent_done["B"])

    def test_finished_field_starts_next_test_while_the_other_continues(self):
        def steps(fid, tests):
            rows = []
            for test_num, count in tests:
                for n in range(1, count + 1):
                    screen = f"{fid}{((n - 1) % 6) + 1}"
                    rows.append({
                        "test_num": test_num,
                        "action_in_set": n,
                        "actions_in_set": count,
                        "on_ms": 3000,
                        "field_screens": {fid: [screen]},
                        "screen_images": {screen: f"{screen}.png"},
                    })
            return rows

        parts = {"A": steps("A", [(1, 10)]), "B": steps("B", [(1, 6), (2, 6)])}
        inst = self._player(parts)
        inst._independent_index = {"A": 6, "B": 5}
        inst._independent_done = {"A": False, "B": True}
        inst._field_result_state = {"B": {"phase": "playing"}}
        patched = []
        inst._patch_independent_fields = lambda entry, fields: patched.append(
            (set(fields), dict(entry.get("field_screens") or {}), dict(entry.get("field_meta") or {}))
        )
        inst._continue_field_after_results("B")
        self.assertEqual(inst._independent_index["A"], 6)
        self.assertEqual(inst._independent_index["B"], 6)
        self.assertFalse(inst._independent_done["A"])
        self.assertFalse(inst._independent_done["B"])
        self.assertNotIn("B", inst._field_result_state)
        self.assertEqual(patched[0][0], {"B"})
        self.assertIn("A", patched[0][1])
        self.assertIn("B", patched[0][1])
        self.assertEqual(patched[0][2]["A"]["action_in_set"], 7)
        self.assertEqual(patched[0][2]["B"]["test_num"], 2)
        self.assertEqual(patched[0][2]["B"]["action_in_set"], 1)

    def test_shorter_field_goals_do_not_close_the_longer_test(self):
        """Foundation stays on all 10 actions while Activated finishes its 6."""
        def steps(fid, count, test_num=1):
            rows = []
            for n in range(1, count + 1):
                screen = f"{fid}{((n - 1) % 6) + 1}"
                rows.append({
                    "test_num": test_num,
                    "action_in_set": n,
                    "actions_in_set": count,
                    "on_ms": 3000,
                    "field_screens": {fid: [screen]},
                    "screen_images": {screen: f"{screen}.png"},
                })
            return rows

        parts = {"A": steps("A", 10), "B": steps("B", 6)}
        inst = self._player(parts)
        inst._patch_independent_fields = lambda entry, fields: None
        for _ in range(6):
            inst._field_hold_until = {
                "A": player.time.perf_counter() + 5.0,
                "B": 0.0,
            }
            inst._finish_due_independent_fields()
        self.assertEqual(inst._independent_index["A"], 0)
        self.assertFalse(inst._independent_done["A"])
        self.assertNotIn("A", inst._field_result_state)
        self.assertTrue(inst._independent_done["B"])
        self.assertEqual(inst._field_result_state["B"]["phase"], "wait")
        inst._field_hold_until = {"A": 0.0}
        for _ in range(9):
            inst._finish_due_independent_fields()
            inst._field_hold_until["A"] = 0.0
        self.assertFalse(inst._independent_done["A"])
        inst._finish_due_independent_fields()
        self.assertTrue(inst._independent_done["A"])
        self.assertEqual(inst._independent_index["A"], 9)
        self.assertEqual(inst._field_result_state["A"]["phase"], "wait")

    def test_a_field_without_a_clock_is_not_skipped(self):
        def row(fid, n):
            screen = f"{fid}{n}"
            return {
                "test_num": 1,
                "action_in_set": n,
                "actions_in_set": 10,
                "on_ms": 3000,
                "field_screens": {fid: [screen]},
                "screen_images": {screen: f"{screen}.png"},
            }
        parts = {
            "A": [row("A", 1), row("A", 2)],
            "B": [row("B", 1), row("B", 2)],
        }
        inst = self._player(parts)
        inst._field_hold_until = {"B": 0.0}
        inst._patch_independent_fields = lambda entry, fields: None
        inst._finish_due_independent_fields()
        self.assertEqual(inst._independent_index["A"], 0)
        self.assertEqual(inst._independent_index["B"], 1)

    def test_field_still_on_its_clock_is_not_restarted(self):
        inst = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        inst._field_hold_until = {
            "A": player.time.perf_counter() + 2.0,
            "B": player.time.perf_counter() + 2.5,
        }
        inst._field_cue_identity = {
            "A": (1, 1, ("A1",)),
            "B": (1, 1, ("B1",)),
        }
        entry = {
            "independent_fields": True,
            "field_meta": {
                "A": {"test_num": 1, "action_in_set": 2},
                "B": {"test_num": 1, "action_in_set": 1},
            },
            "field_screens": {"A": ["A2"], "B": ["B1"]},
        }
        continuing = inst._independent_continuing_fields(entry, entry["field_screens"])
        self.assertEqual(continuing, {"B"})

    def test_early_timer_rearms_instead_of_dropping_the_clock(self):
        def row(fid):
            return {
                "test_num": 1,
                "action_in_set": 1,
                "actions_in_set": 2,
                "on_ms": 3000,
                "field_screens": {fid: [f"{fid}1"]},
                "screen_images": {f"{fid}1": "x.png"},
            }
        inst = self._player({"A": [row("A"), row("A")], "B": [row("B"), row("B")]})
        inst._field_hold_until = {
            "A": player.time.perf_counter() + 2.0,
            "B": player.time.perf_counter() + 2.0,
        }
        armed = []
        inst._arm_independent_timer = lambda: armed.append(True)
        inst._finish_due_independent_fields()
        self.assertEqual(armed, [True])
        self.assertEqual(inst._independent_index, {"A": 0, "B": 0})

    def test_real_field_stays_on_its_screen_until_a_goal(self):
        def row(fid):
            return {
                "test_num": 1,
                "action_in_set": 1,
                "actions_in_set": 2,
                "on_ms": 3000,
                "field_screens": {fid: [f"{fid}1"]},
                "screen_images": {f"{fid}1": "x.png"},
            }
        inst = self._player({"A": [row("A"), row("A")], "B": [row("B"), row("B")]})
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, ignore_errors=True))
        inst.speed_file_dir = folder
        with open(os.path.join(folder, "arena_simulation.txt"), "w", encoding="utf-8") as handle:
            handle.write('{"A": false, "B": true}')
        now = player.time.perf_counter()
        inst._field_hold_until = {"A": now - 1.0, "B": now + 5.0}
        patched = []
        inst._patch_independent_fields = lambda entry, fields: patched.append(set(fields))
        inst._finish_due_independent_fields()
        self.assertEqual(inst._independent_index, {"A": 0, "B": 0})
        self.assertEqual(patched, [])
        self.assertGreater(inst._field_hold_until["A"], now + 1000.0)
        inst._field_hold_until["A"] = 0.0
        inst._finish_due_independent_fields()
        self.assertEqual(inst._independent_index["A"], 1)
        self.assertEqual(inst._independent_index["B"], 0)
        self.assertEqual(patched, [{"A"}])

    def test_pause_and_stop_apply_to_one_field(self):
        def row(fid):
            return {
                "test_num": 1,
                "action_in_set": 1,
                "actions_in_set": 2,
                "on_ms": 3000,
                "field_screens": {fid: [f"{fid}1"]},
                "screen_images": {f"{fid}1": "x.png"},
            }
        inst = self._player({"A": [row("A"), row("A")], "B": [row("B"), row("B")]})
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, ignore_errors=True))
        inst.speed_file_dir = folder
        inst.pause_file_path = os.path.join(folder, "pause.txt")
        with open(inst.pause_file_path, "w", encoding="utf-8") as handle:
            handle.write('{"A": true, "B": false}')
        with open(os.path.join(folder, "arena_simulation.txt"), "w", encoding="utf-8") as handle:
            handle.write('{"A": true, "B": true}')
        now = player.time.perf_counter()
        inst._field_hold_until = {"A": now - 1.0, "B": 0.0}
        patched = []
        inst._patch_independent_fields = lambda entry, fields: patched.append(set(fields))
        inst._show_field_final = lambda fid: patched.append(("final", fid))
        inst._request_field_final = lambda *args, **kwargs: None
        written = []
        original_write = player._write_players_fields_active
        player._write_players_fields_active = lambda active: written.append(list(active))
        self.addCleanup(lambda: setattr(player, "_write_players_fields_active", original_write))
        inst._finish_due_independent_fields()
        self.assertEqual(inst._independent_index, {"A": 0, "B": 1})
        self.assertEqual(patched, [{"B"}])
        inst._stop_independent_field("A")
        self.assertTrue(inst._independent_done["A"])
        self.assertFalse(inst._independent_done["B"])
        self.assertEqual(inst._independent_index["B"], 1)
        self.assertNotIn(("final", "A"), patched)
        self.assertNotIn("A", inst._control_fields_playing())
        self.assertIn("B", inst._control_fields_playing())
        self.assertEqual(written, [["B"]])
        self.assertEqual(inst._phase_active, ["B"])

    def test_second_field_starts_without_moving_the_first(self):
        def row(fid, n):
            return {
                "test_num": 1,
                "action_in_set": n,
                "actions_in_set": 2,
                "on_ms": 3000,
                "field_screens": {fid: [f"{fid}{n}"]},
                "screen_images": {f"{fid}{n}": "x.png"},
            }
        inst = self._player({"A": [row("A", 1), row("A", 2)]})
        inst._phase_active = ["A"]
        inst._independent_index = {"A": 1}
        inst._phase_field_levels = {"A": "L00-Foundation"}
        inst._phase_field_directories = {}
        inst._phase_field_modes = {}
        inst._build_one_field_playlist = lambda fid: [row(fid, 1), row(fid, 2)]
        reloaded = []
        inst._reload_independent_entry = lambda restart_fields=None: reloaded.append(set(restart_fields or []))
        original_write = player._write_players_fields_active
        player._write_players_fields_active = lambda active: None
        self.addCleanup(lambda: setattr(player, "_write_players_fields_active", original_write))
        self.assertTrue(inst._join_independent_field("B", {
            "level": "L01-Entry",
            "directory": "entry",
            "subdirectory": "A-T1",
        }))
        self.assertEqual(len(inst._field_opening_playlists["A"]), 1)
        self.assertEqual(inst._field_opening_playlists["A"][0]["action_in_set"], 2)
        self.assertEqual(len(inst._field_opening_playlists["B"]), 2)
        self.assertEqual(inst._phase_active, ["A", "B"])
        self.assertEqual(reloaded, [{"B"}])
        self.assertFalse(inst._all_live_fields_paused({"A": True, "B": False}))
        inst._phase_active = ["A"]
        self.assertTrue(inst._all_live_fields_paused({"A": True, "B": False}))

    def test_joined_field_shows_opening_before_its_test(self):
        def row(fid, n):
            return {
                "test_num": 1,
                "action_in_set": n,
                "actions_in_set": 2,
                "on_ms": 3000,
                "field_screens": {fid: [f"{fid}{n}"]},
                "screen_images": {f"{fid}{n}": "x.png"},
            }
        inst = self._player({"A": [row("A", 1), row("A", 2)]})
        inst._phase_active = ["A"]
        inst._phase_field_levels = {"A": "L00-Foundation"}
        inst._phase_field_directories = {}
        inst._phase_field_modes = {}
        inst._build_one_field_playlist = lambda fid: [row(fid, 1)]
        opened = []
        inst.image_canvas = types.SimpleNamespace(
            show_field_opening=lambda fid, card: opened.append(fid),
        )
        reloaded = []
        inst._reload_independent_entry = lambda restart_fields=None: reloaded.append(set(restart_fields or []))
        original_write = player._write_players_fields_active
        player._write_players_fields_active = lambda active: None
        self.addCleanup(lambda: setattr(player, "_write_players_fields_active", original_write))
        self.assertTrue(inst._join_independent_field("B", {
            "level": "L01-Entry",
            "directory": "entry",
            "subdirectory": "A-T1",
        }))
        self.assertEqual(opened, ["B"])
        self.assertEqual(reloaded, [])
        self.assertIn("B", inst._fields_opening)
        inst._start_joined_field_test("B")
        self.assertEqual(reloaded, [{"B"}])
        self.assertNotIn("B", inst._fields_opening)

    def test_starting_one_field_during_results_keeps_the_other(self):
        def row(fid, test_num):
            return {
                "test_num": test_num,
                "action_in_set": 1,
                "actions_in_set": 1,
                "on_ms": 3000,
                "field_screens": {fid: [f"{fid}1"]},
                "screen_images": {f"{fid}1": "x.png"},
            }
        inst = self._player({
            "A": [row("A", 1), row("A", 2)],
            "B": [row("B", 1)],
        })
        inst._independent_index = {"A": 0, "B": 0}
        inst._independent_done = {"A": True, "B": False}
        inst._phase_active = ["A"]
        inst._phase_field_levels = {"A": "L00-Foundation", "B": "L01-Entry"}
        inst._phase_field_directories = {}
        inst._phase_field_modes = {}
        inst._build_one_field_playlist = lambda fid: [row(fid, 1), row(fid, 2)]
        inst.image_canvas = types.SimpleNamespace(show_field_opening=lambda fid, card: None)
        inst._reload_independent_entry = lambda restart_fields=None: None
        original_write = player._write_players_fields_active
        player._write_players_fields_active = lambda active: None
        self.addCleanup(lambda: setattr(player, "_write_players_fields_active", original_write))
        self.assertFalse(inst._field_series_finished("A"))
        self.assertTrue(inst._join_independent_field("B", {
            "level": "L01-Entry",
            "directory": "entry",
            "subdirectory": "A-T1",
        }))
        kept = inst._field_opening_playlists["A"]
        self.assertEqual([step["test_num"] for step in kept], [1, 2])
        self.assertTrue(inst._independent_done["A"])
        self.assertIn("A", inst._phase_active)
        self.assertIn("A", inst._control_fields_playing())

    def test_finished_field_releases_only_its_stop_button(self):
        def row(fid, n):
            return {
                "test_num": 1,
                "action_in_set": n,
                "actions_in_set": 2,
                "on_ms": 3000,
                "field_screens": {fid: [f"{fid}{n}"]},
                "screen_images": {f"{fid}{n}": "x.png"},
            }
        inst = self._player({
            "A": [row("A", 1), row("A", 2)],
            "B": [row("B", 1), row("B", 2)],
        })
        inst._independent_index = {"A": 1, "B": 0}
        inst._independent_done = {"A": True, "B": False}
        inst.playlist_finished = False
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        handle.close()
        inst.status_file = handle.name
        self.addCleanup(lambda: os.path.exists(handle.name) and os.remove(handle.name))
        inst._publish_field_controls()
        with open(handle.name, "r", encoding="utf-8") as status:
            data = json.load(status)
        self.assertEqual(data["fields"], {"A": "idle", "B": "playing"})
        inst._update_status_file("playing", 1, 2, "running")
        with open(handle.name, "r", encoding="utf-8") as status:
            data = json.load(status)
        self.assertEqual(data["fields"], {"A": "idle", "B": "playing"})
        self.assertEqual(data["state"], "playing")

    def test_start_stop_cycles_leave_the_live_field_running(self):
        """Field A stays up while B starts and stops, then the reverse, for about a minute of actions."""
        def rows(fid, tests=4, actions=10):
            playlist = []
            for test_num in range(1, tests + 1):
                for action in range(1, actions + 1):
                    screen = f"{fid}{((action - 1) % 6) + 1}"
                    playlist.append({
                        "test_num": test_num,
                        "action_in_set": action,
                        "actions_in_set": actions,
                        "on_ms": 3000,
                        "field_screens": {fid: [screen]},
                        "screen_images": {screen: f"{fid}-t{test_num}-a{action}.png"},
                    })
            return playlist

        class Canvas:
            def __init__(self):
                self.screens = {}
                self.finals = []

            def set_screen_images(self, images, keep_videos=False, replace_fields=None, scale=None):
                replace = {str(name).upper()[:1] for name in (replace_fields or set())}
                if replace:
                    self.screens = {
                        name: pix for name, pix in self.screens.items()
                        if str(name)[:1] not in replace
                    }
                    self.screens.update(images or {})
                elif images:
                    self.screens = dict(images)

            def show(self):
                return None

            def raise_(self):
                return None

            def show_field_opening(self, fid, card):
                return None

            def play_field_intro(self, fid, path):
                return False

        inst = self._player({"A": rows("A"), "B": rows("B")})
        inst._phase_active = ["A"]
        inst._independent_index = {"A": 0, "B": 0}
        inst._independent_done = {"A": False, "B": False}
        inst._phase_field_levels = {"A": "L00-Foundation"}
        inst._phase_field_directories = {}
        inst._phase_field_modes = {}
        inst._field_operator_stopped = {}
        inst._field_epochs = {}
        inst._fields_opening = set()
        inst.image_canvas = Canvas()
        inst.image_canvas.screens = {"A1": "a-live", "B1": "b-live"}
        inst._build_one_field_playlist = lambda fid: rows(fid)
        inst._patch_independent_fields = lambda entry, fields: None
        inst._queue_field_results = lambda fid, step: None
        inst._request_field_results = lambda *args, **kwargs: None
        inst._request_field_final = lambda *args, **kwargs: None
        inst._show_field_final = lambda fid: inst.image_canvas.finals.append(fid)
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        handle.close()
        inst.status_file = handle.name
        self.addCleanup(lambda: os.path.exists(handle.name) and os.remove(handle.name))
        original_write = player._write_players_fields_active
        player._write_players_fields_active = lambda active: None
        self.addCleanup(lambda: setattr(player, "_write_players_fields_active", original_write))

        def step(fid, count):
            for _ in range(count):
                if fid not in inst._control_fields_playing():
                    break
                if inst._independent_done.get(fid):
                    inst._continue_field_after_results(fid)
                else:
                    inst._advance_independent_field(fid, reload=False)

        def start(fid):
            self.assertTrue(inst._join_independent_field(fid, {
                "level": "L01-Entry/S1.T1",
                "directory": "entry",
                "subdirectory": "S1.T1",
            }))
            inst._start_joined_field_test(fid)
            self.assertIn(fid, inst._control_fields_playing())

        def stop(fid):
            epoch = inst._field_epoch(fid)
            inst._stop_independent_field(fid)
            inst._reveal_field_final(fid, epoch)
            inst._finish_field_final(fid, epoch)
            inst._continue_field_after_results(fid, epoch)
            inst._start_joined_field_test(fid, epoch)
            self.assertNotIn(fid, inst._control_fields_playing())
            self.assertNotIn(fid, inst.image_canvas.finals)
            self.assertFalse(any(str(name).startswith(fid) for name in inst.image_canvas.screens))

        step("A", 6)
        start("B")
        self.assertIn("A", inst._control_fields_playing())
        self.assertIn("A1", inst.image_canvas.screens)
        step("A", 4)
        step("B", 4)
        b_mark = (
            inst._field_opening_playlists["B"][inst._independent_index["B"]]["test_num"],
            inst._field_opening_playlists["B"][inst._independent_index["B"]]["action_in_set"],
        )
        stop("A")
        self.assertIn("B", inst._control_fields_playing())
        self.assertEqual(
            (
                inst._field_opening_playlists["B"][inst._independent_index["B"]]["test_num"],
                inst._field_opening_playlists["B"][inst._independent_index["B"]]["action_in_set"],
            ),
            b_mark,
        )
        self.assertIn("B1", inst.image_canvas.screens)
        step("B", 20)
        self.assertIn("B", inst._control_fields_playing())
        self.assertFalse(inst._field_series_finished("B"))
        start("A")
        self.assertIn("B", inst._control_fields_playing())
        self.assertGreater(len(inst._field_opening_playlists["A"]), 1)
        for _cycle in range(3):
            step("A", 3)
            step("B", 3)
            stop("B")
            self.assertIn("A", inst._control_fields_playing())
            start("B")
            step("B", 2)
            live_a = (
                inst._field_opening_playlists["A"][inst._independent_index["A"]]["test_num"],
                inst._field_opening_playlists["A"][inst._independent_index["A"]]["action_in_set"],
            )
            b_step = inst._field_opening_playlists["B"][inst._independent_index["B"]]
            stop("A")
            self.assertIn("B", inst._control_fields_playing())
            self.assertIs(
                inst._field_opening_playlists["B"][inst._independent_index["B"]],
                b_step,
            )
            start("A")
            self.assertIn("A", inst._control_fields_playing())
            self.assertIn("B", inst._control_fields_playing())
            self.assertFalse(inst._field_series_finished("A"))
            self.assertFalse(inst._field_series_finished("B"))
            self.assertIsNotNone(live_a)


class PassImageClearTests(unittest.TestCase):
    def test_a_goal_clears_only_that_fields_pass(self):
        entry = {
            "screen_images": {
                "A3": "a3-next.png",
                "B1": "b1.png",
                "B2": "b2.png",
                "B6": "b6.png",
            },
            "field_screens": {"A": ["A3"], "B": ["B6"]},
        }
        shown = player._images_for_fields(entry, {"A"})
        self.assertEqual(shown, {"A3": "a3-next.png"})
        kept = player._without_field_screens(
            {"A2": "old-pass", "A5": "older-pass", "B1": "entry"},
            {"A"},
        )
        kept.update(shown)
        self.assertEqual(kept, {"B1": "entry", "A3": "a3-next.png"})
        self.assertNotIn("A2", kept)
        self.assertNotIn("A5", kept)

    def test_foundation_goal_clears_its_pass_while_entry_continues(self):
        """A scored Foundation pass leaves the screen. Entry can finish first."""
        def foundation(fid="A"):
            rows = []
            for test_num in range(1, 6):
                for n in range(1, 11):
                    screen = f"{fid}{((n - 1) % 6) + 1}"
                    rows.append({
                        "test_num": test_num,
                        "action_in_set": n,
                        "actions_in_set": 10,
                        "on_ms": 3000,
                        "budget_ms": 30000,
                        "finish_balls": True,
                        "field_screens": {fid: [screen]},
                        "screen_images": {screen: f"{screen}-t{test_num}.png"},
                    })
            return rows

        def entry(fid="B"):
            rows = []
            for test_num in range(1, 6):
                for n in range(1, 7):
                    visible = {
                        f"{fid}{screen}": f"digit-{digit}"
                        for screen, digit in enumerate(range(n, 7), start=1)
                    }
                    goal = f"{fid}{n}"
                    rows.append({
                        "test_num": test_num,
                        "action_in_set": n,
                        "actions_in_set": 6,
                        "on_ms": 3000,
                        "budget_ms": 18000,
                        "finish_balls": True,
                        "entry_digits": True,
                        "field_screens": {fid: [goal]},
                        "screen_images": visible,
                    })
            return rows

        class Canvas:
            def __init__(self):
                self._screen_pixmaps = {}
                self._band_screens = set()

            def set_screen_images(self, images, keep_videos=False, replace_fields=None):
                merged = player._without_field_screens(self._screen_pixmaps, replace_fields)
                merged.update(images or {})
                self._screen_pixmaps = merged

        parts = {"A": foundation(), "B": entry()}
        inst = types.SimpleNamespace()
        for name in (
            "_advance_independent_field",
            "_reload_independent_entry",
            "_patch_independent_fields",
            "_bump_field_cue_seqs",
            "_stamp_field_clocks",
            "_field_series_finished",
            "_field_action_identity",
        ):
            setattr(inst, name, getattr(player.SmartPlayerWindow, name).__get__(inst))
        inst._field_opening_playlists = parts
        inst._independent_index = {"A": 0, "B": 0}
        inst._independent_done = {"A": False, "B": False}
        inst._field_cue_seq = {"A": 1, "B": 1}
        inst._field_action_wall = {}
        inst._field_hold_until = {}
        inst._flash_seq = 1
        inst.video_files = player._zip_field_action_playlists(parts)
        inst.current_video_index = 0
        inst.display_phase = "action"
        inst.image_canvas = Canvas()
        inst.image_canvas._screen_pixmaps = dict(inst.video_files[0]["screen_images"])
        inst._arm_independent_timer = lambda: None
        inst._start_goal_advance_poll = lambda: None
        inst._queue_field_results = lambda fid, step: None
        cues = []
        original = player._write_image_action_cue
        player._write_image_action_cue = lambda *args, **kwargs: cues.append(kwargs.get("field_seqs"))
        try:
            inst._advance_independent_field("A", reload=False)
            inst._reload_independent_entry(restart_fields={"A"})
        finally:
            player._write_image_action_cue = original
        shown = inst.image_canvas._screen_pixmaps
        self.assertEqual(shown.get("A2"), "A2-t1.png")
        self.assertNotIn("A1", shown)
        self.assertEqual(shown.get("B1"), "digit-1")
        self.assertEqual(shown.get("B6"), "digit-6")
        self.assertFalse(inst._field_series_finished("A"))
        self.assertFalse(inst._field_series_finished("B"))
        sim = DualSeriesSimulator(parts)
        sim.play_all()
        self.assertEqual(sim.summaries, 1)
        closed_a = [row for row in sim.closed if row[0] == "A"]
        closed_b = [row for row in sim.closed if row[0] == "B"]
        self.assertEqual([row[1] for row in closed_a], [1, 2, 3, 4, 5])
        self.assertEqual([row[1] for row in closed_b], [1, 2, 3, 4, 5])
        self.assertTrue(all(row[2] == 10 for row in closed_a))
        self.assertTrue(all(row[2] == 6 for row in closed_b))


class ResultRingTests(unittest.TestCase):
    def test_rings_land_on_each_fields_screens(self):
        field_a = player._result_ring_specs({
            "slice_aet": "A1",
            "slice_acc": "A2",
            "slice_ae": "A5",
            "slice_disp": "A6",
            "aet_display": "15.50s",
            "aet_session_display": "30.00s",
            "aet_percent": 48.3,
            "aac": 100.0,
            "ae_display": "78%",
            "avg_ae": 77.6,
            "economy_percent": 31.0,
            "distance_shown": 24,
        })
        self.assertEqual(field_a["A1"]["lines"], ["15.50s", "30.00s"])
        self.assertEqual(field_a["A2"]["lines"], ["100%"])
        self.assertEqual(field_a["A5"]["label"], "Efficiency")
        self.assertEqual(field_a["A6"]["lines"], ["24m"])
        field_b = player._result_ring_specs({
            "slice_aet": "B1",
            "slice_acc": "B2",
            "slice_ae": "B5",
            "slice_disp": "B6",
            "aet_display": "1.59s",
            "aet_session_display": "16.20s",
            "aet_percent": 90.0,
            "aac": 100.0,
            "ae_display": "87%",
            "avg_ae": 86.9,
            "economy_percent": 17.0,
            "distance_shown": 13,
        })
        self.assertEqual(set(field_b), {"B1", "B2", "B5", "B6"})
        self.assertNotIn("A1", field_b)

    def test_accuracy_zero_shows_percent_not_dash(self):
        specs = player._result_ring_specs({
            "slice_aet": "A1",
            "slice_acc": "A2",
            "slice_ae": "A5",
            "slice_disp": "A6",
            "aet_display": "-",
            "aet_percent": 0,
            "aac": 0.0,
            "ae_display": "-",
            "avg_ae": 0,
            "economy_percent": 0,
            "distance_shown": 0,
        })
        self.assertEqual(specs["A2"]["lines"], ["0%"])
        missing = player._result_ring_specs({
            "slice_aet": "A1",
            "slice_acc": "A2",
            "slice_ae": "A5",
            "slice_disp": "A6",
            "aet_display": "-",
            "aet_percent": 0,
            "ae_display": "-",
            "avg_ae": 0,
            "economy_percent": 0,
            "distance_shown": 0,
        })
        self.assertEqual(missing["A2"]["lines"], ["-"])


class CombinedLevelTests(unittest.TestCase):
    def test_elite_and_world_class_stay_together(self):
        elite = player._combined_play_decision(
            {"A", "B"},
            {"A": "L04-Elite/S1.T1", "B": "L04-Elite/S1.T1"},
        )
        self.assertEqual(elite[0], "play")
        self.assertEqual(elite[1], "elite")
        world = player._combined_play_decision(
            {"A", "B"},
            {"A": "L05-WorldClass/S1.T2", "B": "L05-WorldClass/S1.T2"},
        )
        self.assertEqual(world[0], "play")
        self.assertEqual(world[1], "world-class")
        mixed = player._combined_play_decision(
            {"A", "B"},
            {"A": "L00-Foundation/SF-30N", "B": "L02-Activated/S1.T1"},
        )
        self.assertIsNone(mixed)


class UnevenActionCountTests(unittest.TestCase):
    def test_foundation_keeps_playing_after_entry_finishes(self):
        """Foundation 10 actions must not close when Entry finishes its 6."""
        def steps(fid, count, prefix):
            rows = []
            for n in range(1, count + 1):
                screen = f"{prefix}{(n - 1) % 6 + 1}"
                rows.append({
                    "test_num": 1,
                    "action_in_set": n,
                    "actions_in_set": count,
                    "field_screens": {fid: [screen]},
                    "screen_images": {screen: f"{screen}.png"},
                })
            return rows

        parts = {"A": steps("A", 10, "A"), "B": steps("B", 6, "B")}
        inst = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        inst._field_opening_playlists = parts
        inst._independent_index = {"A": 0, "B": 0}
        inst._independent_done = {"A": False, "B": False}
        inst.video_files = player._zip_field_action_playlists(parts)
        inst.current_video_index = 0
        inst.display_phase = "action"
        inst._apply_label_phase = lambda: None
        for _ in range(6):
            inst._advance_independent_field("A", reload=False)
            inst._advance_independent_field("B", reload=False)
        inst._reload_independent_entry()
        self.assertTrue(inst._independent_done["B"])
        self.assertFalse(inst._independent_done["A"])
        self.assertNotIn("A", inst._field_result_state)
        self.assertEqual(inst._field_result_state["B"]["phase"], "wait")
        self.assertEqual(inst.video_files[0]["field_screens"], {"A": ["A1"]})
        self.assertEqual(inst.video_files[0]["field_meta"]["A"]["action_in_set"], 7)
        self.assertEqual(inst.video_files[0]["field_meta"]["A"]["actions_in_set"], 10)
        for _ in range(3):
            inst._advance_independent_field("A", reload=False)
        self.assertFalse(inst._independent_done["A"])
        inst._advance_independent_field("A", reload=False)
        self.assertTrue(inst._independent_done["A"])
        self.assertEqual(inst._field_result_state["A"]["phase"], "wait")
        self.assertEqual(inst._independent_index["A"], 9)


class IndependentAdvanceTests(unittest.TestCase):
    def test_advancing_field_a_does_not_move_field_b(self):
        inst = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        parts = {
            "A": [
                {
                    "test_num": 1,
                    "action_in_set": 1,
                    "actions_in_set": 2,
                    "finish_balls": True,
                    "advance_on_goal": True,
                    "field_screens": {"A": ["A1"]},
                    "screen_images": {"A1": "a1", "A2": "a2"},
                },
                {
                    "test_num": 1,
                    "action_in_set": 2,
                    "actions_in_set": 2,
                    "finish_balls": True,
                    "advance_on_goal": True,
                    "field_screens": {"A": ["A2"]},
                    "screen_images": {"A1": "a1", "A2": "a2"},
                },
            ],
            "B": [
                {
                    "test_num": 1,
                    "action_in_set": 1,
                    "actions_in_set": 2,
                    "finish_balls": True,
                    "advance_on_goal": True,
                    "field_screens": {"B": ["B3"]},
                    "screen_images": {"B3": "b3", "B4": "b4"},
                },
                {
                    "test_num": 1,
                    "action_in_set": 2,
                    "actions_in_set": 2,
                    "finish_balls": True,
                    "advance_on_goal": True,
                    "field_screens": {"B": ["B4"]},
                    "screen_images": {"B3": "b3", "B4": "b4"},
                },
            ],
        }
        inst._field_opening_playlists = parts
        inst._independent_index = {"A": 0, "B": 0}
        inst._independent_done = {"A": False, "B": False}
        inst._goal_arrived_fields = set()
        inst.video_files = player._zip_field_action_playlists(parts)
        inst.current_video_index = 0
        inst.display_phase = "action"
        inst._action_phase = "label"
        inst._label_phase = "action"
        inst._goal_arrived = False
        inst.action_timer = None
        calls = []
        inst._apply_label_phase = lambda: calls.append("reload")
        inst._stop_action_timer = lambda: None
        inst._advance_independent_field("A")
        self.assertEqual(inst._independent_index["A"], 1)
        self.assertEqual(inst._independent_index["B"], 0)
        entry = inst.video_files[0]
        self.assertEqual(entry["field_screens"]["A"], ["A2"])
        self.assertEqual(entry["field_screens"]["B"], ["B3"])
        self.assertEqual(calls, ["reload"])


def _scripted_series(fid, tests, actions, on_ms, budget_ms):
    rows = []
    for test_num in range(1, tests + 1):
        for n in range(1, actions + 1):
            screen = f"{fid}{((n - 1) % 6) + 1}"
            rows.append({
                "test_num": test_num,
                "action_in_set": n,
                "actions_in_set": actions,
                "on_ms": on_ms,
                "budget_ms": budget_ms,
                "finish_balls": True,
                "field_screens": {fid: [screen]},
                "screen_images": {screen: f"{screen}.png"},
            })
    return rows


class DualSeriesSimulator:
    """Step both fields the way the player does, without the screen or the camera."""

    def __init__(self, parts):
        self.inst = FieldContinuesAloneTests()._player(parts)
        self.closed = []
        self.finals = []
        self.summaries = 0
        self.inst._queue_field_results = self._queue
        self.inst._show_final_summary = self._summary
        self.inst._show_field_final = self._final
        self.inst._patch_independent_fields = lambda entry, fields: None

    def _queue(self, fid, step):
        self.closed.append((
            str(fid).upper()[:1],
            int(step.get("test_num") or 0),
            int(step.get("action_in_set") or 0),
            int(step.get("actions_in_set") or 0),
        ))

    def _summary(self):
        self.summaries += 1

    def _final(self, fid):
        fid = str(fid).upper()[:1]
        if fid in self.finals:
            return
        self.finals.append(fid)
        parts = self.inst._field_opening_playlists or {}
        names = [name for name, rows in parts.items() if rows]
        if names and all(name in self.finals for name in names):
            self.summaries = 1

    def advance(self, fid):
        self.inst._advance_independent_field(fid, reload=False)
        if not self.inst._independent_done.get(fid):
            self.inst._reload_independent_entry(restart_fields={fid})

    def finish_results(self, fid):
        self.inst._continue_field_after_results(fid)

    def play_all(self):
        guard = 0
        while guard < 500 and self.summaries == 0:
            guard += 1
            moved = False
            for fid in ("A", "B"):
                rows = (self.inst._field_opening_playlists or {}).get(fid) or []
                if not rows:
                    continue
                if self.inst._field_series_finished(fid):
                    if fid not in self.finals:
                        self.finish_results(fid)
                    continue
                if self.inst._independent_done.get(fid):
                    self.finish_results(fid)
                else:
                    self.advance(fid)
                moved = True
                if self.summaries:
                    break
            if self.summaries or not moved:
                for fid in ("A", "B"):
                    if self.summaries:
                        break
                    if self.inst._field_series_finished(fid):
                        self.finish_results(fid)
                break
        return guard


class DualSeriesSimTests(unittest.TestCase):
    def _expect(self, parts, expected):
        sim = DualSeriesSimulator(parts)
        sim.play_all()
        self.assertEqual(sim.summaries, 1)
        self.assertTrue(sim.inst._every_independent_series_finished())
        for fid, tests, actions in expected:
            closed = [row for row in sim.closed if row[0] == fid]
            self.assertEqual([row[1] for row in closed], list(range(1, tests + 1)))
            self.assertTrue(all(row[2] == actions and row[3] == actions for row in closed))
        return sim

    def test_foundation_30n_script_has_five_tests(self):
        """SF-30N, SF-60N, SF-110N, and SF-180N each play 5 tests of 10 actions."""
        for name in ("SF-30N", "SF-60N", "SF-110N", "SF-180N"):
            script = player.SF_SCRIPTED_PLAYLISTS[name]
            self.assertEqual(list(script), [1, 2, 3, 4, 5])
            self.assertTrue(all(len(script[n]["pairs"]) == 10 for n in script))
        self.assertEqual(player.SF30N_SCRIPT[1]["pairs"][0], (1, 1))
        self.assertEqual(player.SF30N_SCRIPT[2]["pairs"][0], (3, 3))
        self.assertEqual(player.SF30N_SCRIPT[4]["pairs"][0], (3, 3))
        self.assertEqual(player.SF30N_SCRIPT[5]["pairs"][0], (1, 1))

    def test_foundation_110_and_high_performance_s2_both_finish(self):
        """Field A 5×10 and Field B 5×6 each save every test before the session ends."""
        parts = {
            "A": _scripted_series("A", 5, 10, 3000, 30000),
            "B": _scripted_series("B", 5, 6, 2700, 16200),
        }
        sim = self._expect(parts, (("A", 5, 10), ("B", 5, 6)))
        self.assertEqual(sim.finals, ["B", "A"])

    def test_several_uneven_pairs_each_save_their_own_tests(self):
        cases = [
            ("A", 5, 6, 2700, 16200, "B", 3, 10, 3000, 30000),
            ("A", 5, 6, 3000, 18000, "B", 5, 6, 2700, 16200),
            ("A", 3, 10, 3000, 30000, "B", 5, 6, 3000, 18000),
            ("A", 5, 6, 1800, 10800, "B", 3, 10, 3000, 30000),
        ]
        for spec in cases:
            with self.subTest(spec=spec):
                parts = {
                    "A": _scripted_series("A", spec[1], spec[2], spec[3], spec[4]),
                    "B": _scripted_series("B", spec[6], spec[7], spec[8], spec[9]),
                }
                self._expect(parts, (("A", spec[1], spec[2]), ("B", spec[6], spec[7])))

    def test_results_pause_does_not_end_the_other_series(self):
        parts = {
            "A": _scripted_series("A", 2, 2, 3000, 6000),
            "B": _scripted_series("B", 2, 2, 2700, 5400),
        }
        sim = DualSeriesSimulator(parts)
        sim.advance("A")
        sim.advance("A")
        self.assertTrue(sim.inst._independent_done["A"])
        self.assertFalse(sim.inst._field_series_finished("A"))
        while not sim.inst._field_series_finished("B"):
            if sim.inst._independent_done.get("B"):
                sim.finish_results("B")
            else:
                sim.advance("B")
        if "B" not in sim.finals:
            sim.finish_results("B")
        self.assertEqual(sim.summaries, 0)
        self.assertEqual(sim.finals, ["B"])
        self.assertEqual([row[1] for row in sim.closed if row[0] == "B"], [1, 2])
        sim.finish_results("A")
        sim.advance("A")
        sim.advance("A")
        sim.finish_results("A")
        self.assertEqual(sim.summaries, 1)
        self.assertEqual(sim.finals, ["B", "A"])
        self.assertEqual([row[1] for row in sim.closed if row[0] == "A"], [1, 2])

    def test_each_field_test_is_its_own_results_video(self):
        self.assertEqual(player._result_video_index(1, 1), 1)
        self.assertEqual(player._result_video_index(3, 1), 3)
        self.assertEqual(player._result_video_index(None, 1), 1)
        parts = {
            "A": _scripted_series("A", 3, 10, 3000, 30000),
            "B": _scripted_series("B", 5, 6, 2700, 16200),
        }
        entry = player._compose_independent_entry(parts, {"A": 0, "B": 0})
        inst = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        inst._stamp_field_clocks(entry)
        self.assertEqual(entry["field_meta"]["A"]["budget_total_sec"], 30.0)
        self.assertEqual(entry["field_meta"]["B"]["budget_total_sec"], 16.2)
        self.assertEqual(entry["field_meta"]["A"]["on_sec"], 3.0)
        self.assertAlmostEqual(entry["field_meta"]["B"]["on_sec"], 2.7)
        videos = {"A": set(), "B": set()}
        for fid, meta in entry["field_meta"].items():
            videos[fid].add(player._result_video_index(meta["test_num"], 1))
        later = player._compose_independent_entry(parts, {"A": 20, "B": 18})
        inst._stamp_field_clocks(later)
        self.assertEqual(later["field_meta"]["A"]["test_num"], 3)
        self.assertEqual(later["field_meta"]["B"]["test_num"], 4)
        self.assertEqual(
            player._result_video_index(later["field_meta"]["A"]["test_num"], 1),
            3,
        )
        self.assertEqual(
            player._result_video_index(later["field_meta"]["B"]["test_num"], 1),
            4,
        )


class SeriesRestartTests(unittest.TestCase):
    """After both fields finish, the next level must keep going past the first tests."""

    def _row(self, fid, test_num, action, actions):
        screen = f"{fid}{((action - 1) % 6) + 1}"
        return {
            "test_num": test_num,
            "action_in_set": action,
            "actions_in_set": actions,
            "on_ms": 3000,
            "field_screens": {fid: [screen]},
            "screen_images": {screen: f"{fid}-t{test_num}-a{action}.png"},
        }

    def _series(self, fid, tests, actions):
        return [
            self._row(fid, test_num, action, actions)
            for test_num in range(1, tests + 1)
            for action in range(1, actions + 1)
        ]

    def _base_player(self):
        inst = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        inst._field_opening_playlists = {}
        inst._independent_index = {}
        inst._independent_done = {}
        inst._field_result_state = {}
        inst._field_final_queued = {}
        inst._field_final_done = {}
        inst._field_hold_until = {}
        inst._field_wait_overlays = {}
        inst._field_epochs = {}
        inst._field_operator_stopped = {}
        inst._fields_opening = set()
        inst._phase_active = []
        inst._phase_field_levels = {}
        inst._phase_field_directories = {}
        inst._phase_field_modes = {}
        inst._independent_close_started = False
        inst._independent_close_token = 0
        inst._status_completed = False
        inst.playlist_finished = False
        inst.close_timer = None
        inst._force_close_timer = None
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        handle.close()
        inst.status_file = handle.name
        self.addCleanup(lambda: os.path.exists(inst.status_file) and os.remove(inst.status_file))
        inst._after_final = {}
        # No canvas: join applies the playlist immediately (no opening timers).
        inst.image_canvas = None
        inst.video_files = []
        inst.current_video_index = 0
        inst.display_phase = "action"
        inst._action_phase = "label"
        inst._label_mode = True
        inst._flash_seq = 1
        inst._apply_label_phase = lambda: None
        inst._stop_action_timer = lambda: None
        inst._stop_goal_advance_poll = lambda: None
        inst._start_goal_advance_poll = lambda: None
        inst._patch_independent_fields = lambda entry, fields: None
        inst._queue_field_results = lambda fid, step: None
        inst._request_field_final = lambda fid, display=True: None
        inst._show_field_final = lambda fid: None
        inst._hide_field_result_rings = lambda fid: None
        inst._intro_video_for_field = lambda fid: None
        original_write = player._write_players_fields_active
        player._write_players_fields_active = lambda active: None
        self.addCleanup(lambda: setattr(player, "_write_players_fields_active", original_write))
        return inst

    def _play_through(self, inst, fid, count):
        for _ in range(count):
            if inst._field_series_finished(fid):
                break
            if inst._independent_done.get(fid):
                inst._continue_field_after_results(fid)
            else:
                inst._advance_independent_field(fid, reload=False)
                if not inst._independent_done.get(fid):
                    inst._reload_independent_entry(restart_fields={fid})

    def test_stale_series_close_does_not_kill_the_next_level(self):
        inst = self._base_player()
        first_a = self._series("A", 2, 10)
        first_b = self._series("B", 2, 6)
        inst._field_opening_playlists = {"A": first_a, "B": first_b}
        inst._independent_index = {"A": len(first_a) - 1, "B": len(first_b) - 1}
        inst._independent_done = {"A": True, "B": True}
        inst._field_final_done = {"A": True, "B": True}
        inst._start_independent_session_close()
        stale = inst._independent_close_token
        self.assertTrue(inst._independent_close_started)

        next_a = self._series("A", 5, 10)
        next_b = self._series("B", 5, 6)
        inst._build_one_field_playlist = lambda fid: list(next_a if fid == "A" else next_b)
        self.assertTrue(inst._join_independent_field("A", {
            "level": "L00-Foundation",
            "directory": "foundation",
            "subdirectory": "SF-30N",
        }))
        self.assertFalse(inst._independent_close_started)
        self.assertNotEqual(inst._independent_close_token, stale)
        self.assertTrue(inst._join_independent_field("B", {
            "level": "L01-Entry",
            "directory": "entry",
            "subdirectory": "S1.T1",
        }))

        # Late close from the previous series must be ignored.
        inst.independent_close_ready = types.SimpleNamespace(
            emit=lambda payload: inst._on_independent_close_ready(payload)
        )
        inst._on_independent_close_ready(json.dumps({
            "progress": {},
            "token": stale,
        }))
        self.assertEqual(len(inst._field_opening_playlists.get("A") or []), 50)
        self.assertEqual(len(inst._field_opening_playlists.get("B") or []), 30)

        self._play_through(inst, "A", 10)
        self._play_through(inst, "B", 6)
        self.assertTrue(inst._independent_done.get("A"))
        self.assertTrue(inst._independent_done.get("B"))
        self.assertFalse(inst._field_series_finished("A"))
        self.assertFalse(inst._field_series_finished("B"))

        inst._continue_field_after_results("A")
        inst._continue_field_after_results("B")
        self.assertEqual(inst._independent_index["A"], 10)
        self.assertEqual(inst._independent_index["B"], 6)
        self.assertFalse(inst._independent_done["A"])
        self.assertFalse(inst._independent_done["B"])
        self.assertIn("A", inst._control_fields_playing())
        self.assertIn("B", inst._control_fields_playing())

    def test_finished_session_releases_stop_and_stays_ready(self):
        inst = self._base_player()
        inst._field_opening_playlists = {
            "A": self._series("A", 1, 2),
            "B": self._series("B", 1, 2),
        }
        inst._independent_index = {"A": 1, "B": 1}
        inst._independent_done = {"A": True, "B": True}
        inst._field_final_done = {"A": True, "B": True}
        inst._independent_close_started = True
        inst._independent_close_token = 3
        inst._realtime_stopped = False
        closed = []
        inst._flash_idle_display = lambda *args, **kwargs: closed.append("flash")
        inst._close_camera_feed_display = lambda: closed.append("camera")
        # Keep System/Saver off so finish stays on the ready path (no idle saver).
        inst._enter_idle_screensaver = lambda: closed.append("idle")
        original_read = player._read_cabinet_controls
        player._read_cabinet_controls = lambda *_args, **_kwargs: {
            "system_on": True,
            "screensaver_on": False,
        }
        self.addCleanup(lambda: setattr(player, "_read_cabinet_controls", original_read))
        inst._finish_independent_session()
        self.assertEqual(inst._field_opening_playlists, {})
        self.assertEqual(inst._control_fields_playing(), [])
        self.assertFalse(inst.playlist_finished)
        self.assertFalse(inst._status_completed)
        self.assertEqual(closed, ["flash", "camera"])
        with open(inst.status_file, "r", encoding="utf-8") as handle:
            status = json.load(handle)
        self.assertEqual(status.get("state"), "ready")
        self.assertEqual(status.get("fields"), {"A": "idle", "B": "idle"})

    def test_levels_can_run_one_after_another(self):
        cases = [
            (5, 10, 5, 6),
            (5, 6, 5, 6),
            (3, 10, 5, 6),
            (5, 10, 3, 10),
        ]
        for a_tests, a_actions, b_tests, b_actions in cases:
            with self.subTest(a=(a_tests, a_actions), b=(b_tests, b_actions)):
                sim = DualSeriesSimulator({
                    "A": _scripted_series("A", a_tests, a_actions, 3000, a_actions * 3000),
                    "B": _scripted_series("B", b_tests, b_actions, 2700, b_actions * 2700),
                })
                sim.play_all()
                self.assertEqual(sim.summaries, 1)
                self.assertTrue(sim.inst._every_independent_series_finished())
                self.assertEqual(
                    [row[1] for row in sim.closed if row[0] == "A"],
                    list(range(1, a_tests + 1)),
                )
                self.assertEqual(
                    [row[1] for row in sim.closed if row[0] == "B"],
                    list(range(1, b_tests + 1)),
                )


class SingleFieldThenJoinTests(unittest.TestCase):
    """Operator starts Field A alone, then joins Field B mid-session."""

    def _row(self, fid, test_num, action, actions):
        screen = f"{fid}{((action - 1) % 6) + 1}"
        return {
            "test_num": test_num,
            "action_in_set": action,
            "actions_in_set": actions,
            "on_ms": 3000,
            "field_screens": {fid: [screen]},
            "screen_images": {screen: f"{fid}-t{test_num}-a{action}.png"},
        }

    def _series(self, fid, tests=5, actions=10):
        return [
            self._row(fid, test_num, action, actions)
            for test_num in range(1, tests + 1)
            for action in range(1, actions + 1)
        ]

    def _single_field_player(self, fid="A", progressed=6):
        playlist = self._series(fid)
        inst = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        inst._field_opening_playlists = {}
        inst._independent_index = {}
        inst._independent_done = {}
        inst._field_result_state = {}
        inst._field_final_queued = {}
        inst._field_final_done = {}
        inst._field_hold_until = {}
        inst._field_wait_overlays = {}
        inst._field_epochs = {}
        inst._field_operator_stopped = {}
        inst._fields_opening = set()
        inst._phase_active = [fid]
        inst._phase_field_levels = {fid: "L00-Foundation"}
        inst._phase_field_directories = {}
        inst._phase_field_modes = {}
        inst._independent_close_started = False
        inst._independent_close_token = 0
        inst._status_completed = False
        inst.playlist_finished = False
        inst.close_timer = None
        inst._force_close_timer = None
        inst.results_timer = None
        inst._after_final = {}
        inst._post_results_index = None
        inst._results_epoch = 0
        inst._results_finished_epoch = None
        inst.waiting_for_results = False
        inst.video_end_called = False
        inst.operator_paused = False
        inst.image_canvas = None
        inst.video_files = list(playlist)
        inst.current_video_index = int(progressed)
        inst.display_phase = "action"
        inst._action_phase = "label"
        inst._label_mode = True
        inst._flash_seq = 1
        inst._screensaver_hold_until = {}
        inst._idle_screensaver_mode = False
        inst._apply_label_phase = lambda: None
        inst._stop_action_timer = lambda: None
        inst._stop_goal_advance_poll = lambda: None
        inst._start_goal_advance_poll = lambda: None
        inst._patch_independent_fields = lambda entry, fields: None
        inst._queue_field_results = lambda field, step: None
        inst._request_field_final = lambda field, display=True: None
        finals = []
        inst._show_field_final = lambda field: finals.append(field)
        inst._hide_field_result_rings = lambda field: None
        inst._hide_waiting_overlay = lambda: None
        inst._hide_projected_results = lambda: None
        inst._intro_video_for_field = lambda field: None
        inst._begin_level_intro = lambda idx: None
        inst._show_waiting_overlay = lambda: None
        original_write = player._write_players_fields_active
        player._write_players_fields_active = lambda active: None
        self.addCleanup(lambda: setattr(player, "_write_players_fields_active", original_write))
        inst._finals = finals
        return inst

    def _play_through(self, inst, fid, count):
        for _ in range(count):
            if inst._field_series_finished(fid):
                break
            if inst._independent_done.get(fid):
                inst._continue_field_after_results(fid)
            else:
                inst._advance_independent_field(fid, reload=False)
                if not inst._independent_done.get(fid):
                    inst._reload_independent_entry(restart_fields={fid})

    def test_join_from_flat_playlist_keeps_full_second_field_series(self):
        """A alone (flat video_files) → join B → B must run all 5 tests, not final early."""
        inst = self._single_field_player("A", progressed=6)
        full_b = self._series("B")
        inst._build_one_field_playlist = lambda fid: list(full_b if fid == "B" else self._series(fid))
        self.assertTrue(inst._join_independent_field("B", {
            "level": "L00-Foundation",
            "directory": "foundation",
            "subdirectory": "SF-30N",
        }))
        self.assertEqual(len(inst._field_opening_playlists["A"]), 50 - 6)
        self.assertEqual(len(inst._field_opening_playlists["B"]), 50)
        # Play through test 1 only — must not jump to final.
        self._play_through(inst, "B", 11)
        self.assertEqual(
            inst._field_opening_playlists["B"][inst._independent_index["B"]]["test_num"],
            2,
        )
        self.assertNotIn("B", inst._finals)
        # Finish the rest of B's series (continue after last action shows final).
        guard = 0
        while "B" not in inst._finals and guard < 80:
            guard += 1
            if inst._independent_done.get("B"):
                inst._continue_field_after_results("B")
            else:
                inst._advance_independent_field("B", reload=False)
        self.assertEqual(inst._finals, ["B"])
        self.assertTrue(inst._field_series_finished("B"))
        # A must still have later tests left — cabinet final must not have wiped B early.
        self.assertFalse(inst._field_series_finished("A"))
        self.assertEqual(len(inst._field_opening_playlists["B"]), 50)

    def test_join_during_single_field_results_does_not_open_cabinet_final(self):
        """Pending wait_per_video → _do_continue must not final after join."""
        inst = self._single_field_player("A", progressed=9)
        # End of test 1: single-field path armed the next-test index.
        inst._post_results_index = 10
        inst.display_phase = "wait_per_video"
        inst.waiting_for_results = True
        inst.video_end_called = True
        full_b = self._series("B")
        inst._build_one_field_playlist = lambda fid: list(full_b if fid == "B" else self._series(fid))
        cabinet_finals = []
        inst._show_waiting_overlay = lambda: cabinet_finals.append("wait")
        self.assertTrue(inst._join_independent_field("B", {
            "level": "L00-Foundation",
            "directory": "foundation",
            "subdirectory": "SF-30N",
        }))
        self.assertEqual(inst.display_phase, "action")
        self.assertIsNone(inst._post_results_index)
        self.assertFalse(inst.waiting_for_results)
        # A's remaining starts at test 2 (index 10), not the finished last action.
        self.assertEqual(inst._field_opening_playlists["A"][0]["test_num"], 2)
        self.assertEqual(len(inst._field_opening_playlists["B"]), 50)
        # Late single-field continue must be ignored.
        inst._do_continue()
        inst._show_final_summary()
        self.assertEqual(cabinet_finals, [])
        self.assertEqual(inst.display_phase, "action")
        self._play_through(inst, "B", 12)
        self.assertFalse(inst._field_series_finished("B"))
        self.assertEqual(inst._finals, [])

    def test_sim_a_then_b_both_complete_all_tests(self):
        """Sim: advance A a few actions, join B, both finish every test."""
        inst = self._single_field_player("A", progressed=4)
        full_a = self._series("A")
        full_b = self._series("B")
        inst._build_one_field_playlist = lambda fid: list(full_b if fid == "B" else full_a)
        self.assertTrue(inst._join_independent_field("B", {
            "level": "L01-Entry",
            "directory": "entry",
            "subdirectory": "S1.T1",
        }))
        # Drain both fields through all remaining/full actions + finals.
        guard = 0
        while sorted(inst._finals) != ["A", "B"] and guard < 200:
            guard += 1
            progressed = False
            for fid in ("A", "B"):
                if fid in inst._finals:
                    continue
                if inst._independent_done.get(fid):
                    inst._continue_field_after_results(fid)
                    progressed = True
                else:
                    inst._advance_independent_field(fid, reload=False)
                    progressed = True
            if not progressed:
                break
        self.assertEqual(sorted(inst._finals), ["A", "B"])
        self.assertTrue(inst._field_series_finished("A"))
        self.assertTrue(inst._field_series_finished("B"))
        self.assertEqual(len(inst._field_opening_playlists["A"]), 46)
        self.assertEqual(len(inst._field_opening_playlists["B"]), 50)


class JoinClearsScreensaverTests(unittest.TestCase):
    def test_stop_screensaver_clears_tiles_even_when_field_not_tracked(self):
        inst = player.SmartPlayerWindow.__new__(player.SmartPlayerWindow)
        inst._screensaver_fields = set()  # out of sync on purpose
        cleared = []

        class Canvas:
            def __init__(self):
                self._screensaver_scale_screens = {"B1", "B2", "B3", "B4", "B5", "B6", "A1"}
                self._saver_pix = object()

            def _release_field_videos(self, fields):
                cleared.append(("release", set(fields)))

            def set_screen_images(self, mapping, keep_videos=False, replace_fields=None):
                cleared.append(("images", set(replace_fields or set())))

            def repaint(self):
                cleared.append("repaint")

            def _stop_coded_screensaver_timer(self):
                cleared.append("timer")

        canvas = Canvas()
        inst.image_canvas = canvas
        player.QtWidgets = types.SimpleNamespace(
            QApplication=types.SimpleNamespace(processEvents=lambda: None)
        )
        inst._stop_field_screensaver("B")
        self.assertFalse(any(name.startswith("B") for name in canvas._screensaver_scale_screens))
        self.assertIn("A1", canvas._screensaver_scale_screens)
        self.assertIn(("images", {"B"}), cleared)

    def test_set_screen_images_drops_saver_ownership_for_replaced_field(self):
        canvas = player.ImageActionCanvas.__new__(player.ImageActionCanvas)
        canvas._bounce_screens = set()
        canvas._image_overlays = {}
        canvas._text_overlays = {}
        canvas._text_overlay_positions = {}
        canvas._keep_text_overlays = False
        canvas._video_fill_screens = set()
        canvas._logo_scale_screens = set()
        canvas._band_screens = set()
        canvas._screensaver_scale_screens = {"A1", "A2", "B1", "B2"}
        canvas._screen_pixmaps = {"A1": object(), "B1": object()}
        canvas._still_pixmaps = {}
        canvas._pixmap_cache = {}
        canvas._summary_lines = []
        canvas._summary_screens = None
        canvas._summary_by_screen = {}
        canvas._result_badges = {}
        canvas._release_field_videos = lambda fields: None
        canvas._clear_field_summary = lambda fields: None
        canvas._stop_bounce_motion = lambda: None
        canvas._stop_screen_video = lambda: None
        canvas._load_pixmap = lambda path: None
        canvas._stamp_screensaver_pixels = lambda pixmaps, screens: None
        canvas.update = lambda: None
        canvas.set_screen_images({}, keep_videos=True, replace_fields={"B"})
        self.assertEqual(canvas._screensaver_scale_screens, {"A1", "A2"})


if __name__ == "__main__":
    unittest.main()
