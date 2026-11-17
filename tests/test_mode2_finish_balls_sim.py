"""Mode 2 sim must finish-balls into the goal and stay (not return home)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import simust_realtime as rt  # noqa: E402


class Mode2FinishBallsSimTests(unittest.TestCase):
    def _sim(self):
        sim = rt.ArenaSimulator(field_id="A")
        sim.always_correct = True
        sim.always_fail = False
        return sim

    def test_mode2_finish_balls_stays_in_goal_intent(self):
        sim = self._sim()
        target = (250.0, 200.0)
        p0, p1 = (100.0, 200.0), (400.0, 200.0)
        with patch.object(sim, "_line_target", return_value=(target, p0, p1)), patch.object(
            sim, "_next_region_border", return_value=("border_far", target)
        ), patch.object(sim, "_center_inside_goal", return_value=target):
            sim.start_action(
                "PASS",
                ["A1"],
                finish_balls=True,
                action_in_set=2,
                actions_in_set=12,
                test_num=5,
            )
        self.assertEqual(sim.intended, "finish")
        self.assertAlmostEqual(float(sim.finish_travel_s), 0.40)

    def test_mode2_non_finish_balls_still_finishes_in_goal(self):
        """Mode 2 always holds in-goal (finish), even outside finish-balls bands."""
        sim = self._sim()
        target = (250.0, 200.0)
        p0, p1 = (100.0, 200.0), (400.0, 200.0)
        with patch.object(sim, "_line_target", return_value=(target, p0, p1)), patch.object(
            sim, "_next_region_border", return_value=("border_far", target)
        ), patch.object(sim, "_center_inside_goal", return_value=target):
            sim.start_action("PASS", ["A1"], finish_balls=False)
        self.assertEqual(sim.intended, "finish")
        self.assertAlmostEqual(float(sim.finish_travel_s), 0.40)

    def test_finish_plan_always_correct_is_finish(self):
        sim = self._sim()
        self.assertEqual(sim._finish_plan(3, 5, 12), "finish")

    def test_pass_correct_ae_needs_aet_60_to_clear_80(self):
        """Document why Mode 2 was stuck at 79%: AET 55% + full displacement = 79."""
        import app as app_mod

        row = {
            "action": "PASS",
            "result": "Correct",
            "movement": 100,
            "finish_balls": True,
        }
        self.assertAlmostEqual(app_mod.finish_balls_action_ae(row, 55.0), 79.0)
        self.assertAlmostEqual(app_mod.finish_balls_action_ae(row, 60.0), 80.0)
        self.assertGreaterEqual(app_mod.finish_balls_action_ae(row, 65.0), 80.0)

    def test_mode2_clock_is_action_times_travel(self):
        clock = rt.mode2_finish_balls_clock_sec(
            action_data={"action_in_set": 6},
            travel_sec=0.40,
        )
        self.assertAlmostEqual(clock, 2.4)

    def test_mode2_clock_clears_80_on_short_budgets_all_bands(self):
        """HP S1.T5 (~11.7s) and Elite/WC 12-ball sets must clear AE 80 in Mode 2."""
        import app as app_mod

        travel = 0.40
        # (actions, budget_sec) mirrors stamp_finish_balls = on_ms * actions
        cases = (
            ("Entry/Activated/HP S1.T1", 6, 18.0),
            ("HP S1.T5 short budget", 6, 11.7),
            ("Elite/WC S1.T5", 12, 35.4),
            ("Elite S2.T5 floor", 12, 31.2),
        )
        for label, actions, budget in cases:
            rows = []
            for i in range(1, actions + 1):
                clock = rt.mode2_finish_balls_clock_sec(
                    action_data={"action_in_set": i},
                    travel_sec=travel,
                )
                rows.append({
                    "action": "PASS",
                    "result": "Correct",
                    "movement": 100,
                    "finish_balls": True,
                    "mode2_sim": True,
                    "balls_budget_sec": budget,
                    "balls_clock_sec": clock,
                })
            score = app_mod.finish_balls_clock(rows, mode=2)
            ae = app_mod.finish_balls_efficiency(rows, score["aet_percent"], mode=2)
            self.assertGreaterEqual(
                score["aet_percent"],
                60.0,
                msg=f"{label}: AET%={score['aet_percent']:.1f} used={score['aet']}",
            )
            self.assertGreater(
                ae,
                75.0,
                msg=f"{label}: AE={ae:.1f} AET%={score['aet_percent']:.1f}",
            )
            self.assertGreaterEqual(
                ae,
                80.0,
                msg=f"{label}: AE={ae:.1f} AET%={score['aet_percent']:.1f}",
            )

    def test_mode2_clock_ignores_cumulative_elapsed(self):
        """Missing action_in_set must not fall back to cumulative elapsed (~budget)."""
        clock = rt.mode2_finish_balls_clock_sec(
            action_data={},
            elapsed_sec=11.0,
            arrive_sec=0.55,
            travel_sec=0.40,
        )
        self.assertLessEqual(clock, 0.52)

    def test_mode2_pass_ae_helper_clears_75(self):
        # movement=100 + AET 60% → AE 80; low AET still floors above 75.
        self.assertGreaterEqual(rt.mode2_pass_finish_ae(60.0, 100.0), 80.0)
        self.assertGreater(rt.mode2_pass_finish_ae(0.0, 100.0), 75.0)
        self.assertGreaterEqual(rt.mode2_pass_finish_ae(0.0, 100.0), rt.MODE2_MIN_AE)

    def test_entry_mode2_section_average_clears_75(self):
        """Entry 6-ball / 18s budget: Mode 2 clocks must put each test AE above 75."""
        import app as app_mod

        actions, budget, travel = 6, 18.0, 0.40
        rows = []
        for i in range(1, actions + 1):
            clock = rt.mode2_finish_balls_clock_sec(
                action_data={"action_in_set": i},
                travel_sec=travel,
            )
            rows.append({
                "action": "PASS",
                "result": "Correct",
                "movement": 100,
                "finish_balls": True,
                "mode2_sim": True,
                "balls_budget_sec": budget,
                "balls_clock_sec": clock,
            })
        section = app_mod.summarize_results_section_metrics(rows)
        self.assertGreaterEqual(section["avg_ae"], 75.0)
        # Five identical tests → final = mean of tests
        final = app_mod._combine_section_metrics([section] * 5)
        self.assertAlmostEqual(final["avg_ae"], section["avg_ae"])
        self.assertGreaterEqual(final["avg_ae"], 75.0)

    def test_timeout_filler_wrongs_do_not_zero_aet(self):
        """Budget-timeout Wrong stamps must not force AET=0 / AE~60 for Mode 2."""
        import app as app_mod

        budget = 30.0
        rows = []
        for i in range(1, 7):
            rows.append({
                "id": "S%s" % i,
                "action": "PASS",
                "result": "Correct",
                "movement": 100,
                "finish_balls": True,
                "mode2_sim": True,
                "balls_budget_sec": budget,
                "balls_clock_sec": i * 0.40,
            })
        # Leftover unplayed actions when shared clock expired (old Mode 2 bug).
        rows.append({
            "id": "T5a10",
            "action": "PASS",
            "result": "Wrong",
            "movement": 0,
            "finish_balls": True,
            "mode2_sim": True,
            "balls_budget_sec": budget,
            "balls_clock_sec": budget,
            "ae": 3.0,
        })
        clock = app_mod.finish_balls_clock(rows, mode=2)
        self.assertGreaterEqual(clock["aet_percent"], 60.0)
        ae = app_mod.finish_balls_efficiency(rows, clock["aet_percent"], mode=2)
        self.assertGreater(ae, 75.0)
        section = app_mod.summarize_results_section_metrics(rows)
        self.assertGreater(section["avg_ae"], 75.0)

    def test_mode2_wallclock_continues_past_first_action(self):
        """Regression: A1 Correct then A6 hung with no heading flip (dropped frames)."""
        screens = ["A1", "A6", "A2", "A5"]
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        tmp.close()
        open(tmp.name, "w", encoding="utf-8").write(json.dumps({"fields": {}}))
        cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
        cam.operator_paused = False
        cam._paused_fields = set()
        cam._live_file_lock = threading.Lock()
        cam.session_lock = threading.Lock()
        cam.simulation_fields = {"A": True, "B": False}
        cam._live_frame_w = 1280.0
        cam._live_frame_h = 360.0
        sim = rt.ArenaSimulator(field_id="A")
        sim.always_correct = True
        cam.simulators = {"A": sim}
        cam._field_is_simulated = lambda fid: True

        ch = types.SimpleNamespace(
            session_active=False,
            current_qr_block=None,
            _display_seq=0,
            current_action="PASS",
            active_goal_lines={},
            current_screens=[],
            current_block_id="S0",
            field_id="A",
            label="A",
            current_keypoints=[],
            kp_clear_frames_left=40,
            _pass_hip_pending={},
            _goal_ball_trail=[],
            _hidden_goal_lines={},
            _played_ball_xy=None,
            _false_hip_spots=[],
            _cylinder_scored_screens=set(),
        )
        cam.channels = {"A": ch}

        def fake_end(_s, _t, channel=None):
            target = channel or ch
            target.session_active = False
            target.active_goal_lines = {}
            sim.end_action()

        cam._end_session_locked = fake_end

        try:
            with patch.object(rt, "LIVE_ACTION_RESULT_FILE", tmp.name):
                for i, name in enumerate(screens, start=1):
                    line = rt.GOAL_LINES[rt.geometry_screen_id(name)]
                    ch.session_active = True
                    ch.current_action = "PASS"
                    ch.current_screens = [name]
                    ch.active_goal_lines = {name: {"p0": line["p0"], "p1": line["p1"]}}
                    ch.current_block_id = f"S{i}"
                    ch._display_seq = 300 + i
                    ch._cylinder_scored_screens = set()
                    ch._pass_hip_pending = {}
                    ch._goal_ball_trail = []
                    ch._hidden_goal_lines = {}
                    ch._played_ball_xy = None
                    ch._false_hip_spots = []
                    ch.current_qr_block = {
                        "finish_balls": True,
                        "data": [],
                        "id": f"S{i}",
                        "action_in_set": i,
                        "actions_in_set": 6,
                        "test_num": 1,
                    }
                    sim.start_action(
                        "PASS",
                        [name],
                        finish_balls=True,
                        action_in_set=i,
                        actions_in_set=6,
                        test_num=1,
                    )
                    t0 = time.time()
                    while time.time() - t0 < 2.5 and ch.session_active:
                        balls, _p, _h = sim.step(1280, 360)
                        for ball in balls:
                            ball["simulated"] = True
                            ball["field"] = "A"
                        cam._publish_goal_if_in_cylinder(ch, balls)
                        time.sleep(0.015)
                    self.assertFalse(
                        ch.session_active,
                        msg=f"{name} stuck pending={ch._pass_hip_pending}",
                    )
        finally:
            try:
                os.remove(tmp.name)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
