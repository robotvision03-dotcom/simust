"""
Audit ArenaSimulator trajectories against analyze_action_with_context.
Does not modify simust_realtime.py. Prints intended vs analyzed results
and the reason when they disagree.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import List, Tuple

import simust_realtime as rt

rt.ArenaSimulator.GOAL_PROBE = False


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def time(self) -> float:
        return self.now

    def advance(self, dt: float) -> None:
        self.now += dt


def fmt_dt(dt: datetime) -> str:
    return dt.strftime("%H:%M:%S.%f")


def sample_xy(sim: rt.ArenaSimulator) -> Tuple[List[int], List[int]]:
    balls, players, _hip = sim.step(rt.SIM_FRAME_WIDTH, rt.SIM_FRAME_HEIGHT)
    return balls[0]["center"], players[0]["center"]


def build_frames(sim: rt.ArenaSimulator, clock: FakeClock, duration: float, fps: float = 25.0):
    data = []
    n = max(1, int(duration * fps))
    dt = 1.0 / fps
    t0 = clock.now
    for i in range(n):
        b, p = sample_xy(sim)
        data.append({"t": round(clock.now - t0, 3), "b": [b], "p": [p], "hp": p})
        clock.advance(dt)
    return data


def run_case(action: str, screens: List[str], intended: str, session_s: float = 3.2, late_s: float = 1.2, after_s: float = 0.0):
    clock = FakeClock(2000.0)
    rt.time.time = clock.time
    sim = rt.ArenaSimulator()
    sim.start_action(action, screens)
    sim.intended = intended

    session_start = datetime.strptime("12:00:00.000000", "%H:%M:%S.%f")
    session_data = build_frames(sim, clock, session_s)
    session_end = session_start + timedelta(seconds=session_s)

    sim.end_action()
    if intended == "late":
        between_data = build_frames(sim, clock, late_s) if late_s else []
    elif after_s > 0:
        between_data = build_frames(sim, clock, after_s)
    else:
        between_data = []

    action_data = {
        "id": f"{action}-{intended}",
        "action": action,
        "screens": screens,
        "start_time": fmt_dt(session_start),
        "end_time": fmt_dt(session_end),
        "data": session_data,
    }
    between_block = {
        "id": "BETWEEN",
        "action": "BETWEEN_SESSIONS",
        "screens": [],
        "start_time": fmt_dt(session_end),
        "end_time": fmt_dt(session_end + timedelta(seconds=late_s)),
        "data": between_data,
    }
    all_data = [action_data, between_block] if between_data else [action_data]

    key = "p" if action == "PRESS" else "b"
    positions = rt.get_positions_from_data(session_data, key)
    min_info = None
    if positions and screens[0] in rt.GOAL_LINES:
        p0 = rt.GOAL_LINES[screens[0]]["p0"]
        p1 = rt.GOAL_LINES[screens[0]]["p1"]
        best = min(rt.get_effective_distance((x, y), p0, p1)[0] for _, x, y in positions)
        last = positions[-1]
        last_d, last_pt = rt.get_effective_distance((last[1], last[2]), p0, p1)
        thresh = rt.get_threshold_for_screen(screens[0], action)
        min_info = {
            "session_min_dist": round(best, 1),
            "session_last_dist": round(last_d, 1),
            "session_last_proj": round(last_pt, 3),
            "threshold": thresh,
            "finish_dist": rt.FINISH_DIST,
            "moving": rt.is_ball_moving(positions),
        }

    result = rt.analyze_action_with_context(action_data, rt.GOAL_LINES, action, all_data, 0)
    actual = result.get("Result")
    ok = actual.lower() == intended.lower()
    reason = diagnose(action, intended, actual, min_info, result, between_data)
    return {
        "action": action,
        "screens": screens,
        "intended": intended,
        "actual": actual,
        "match": ok,
        "winning": result.get("Winning Screen"),
        "min_dist": result.get("Min Distance (px)"),
        "time": result.get("Time of Min (s)"),
        "geom": min_info,
        "reason": reason,
    }


def diagnose(action, intended, actual, geom, result, between_data):
    if actual.lower() == intended.lower():
        return "OK — analysis matches intended finishing result"
    g = geom or {}
    lines = []
    if intended == "correct" and actual == "Miss":
        lines.append(
            "PASS treats a near finish as Miss unless the ball stays/returns within "
            f"threshold*3.4 after the closest frame (check_ball_return). "
            f"session_min_dist={g.get('session_min_dist')} threshold={g.get('threshold')} "
            f"FINISH_DIST={g.get('finish_dist')}."
        )
        lines.append("Code: analyze_action_with_context PASS branch + check_ball_return (~1144–1210).")
    elif intended == "correct" and actual == "Wrong":
        lines.append(
            f"Never entered the accept radius. min_dist={g.get('session_min_dist')} "
            f"threshold={g.get('threshold')} FINISH_DIST={g.get('finish_dist')} moving={g.get('moving')}."
        )
        if action == "GOAL":
            lines.append("GOAL also requires 0<=proj_t<=1 (valid_projection). Code ~973–1019.")
        elif action in ("PRESS", "TARGET"):
            lines.append("PRESS/TARGET require is_ball_moving before any distance check. Code ~1044–1078.")
        elif action == "PASS":
            lines.append("PASS Correct requires min_dist <= FINISH_DIST (100px) AND return. Code ~1166–1206.")
    elif intended == "miss" and actual == "Correct":
        lines.append(
            "Miss path still counted as returned: after closest approach, later frames were still "
            f"within threshold*3.4 ({g.get('threshold')}*3.4={None if g.get('threshold') is None else round(g['threshold']*3.4,1)}px). "
            "Jump-home is not far enough for this screen, or home is still near that goal line."
        )
        lines.append("Code: check_ball_return + PASS entry_threshold=threshold*3.4 (~1182–1206).")
    elif intended == "miss" and actual != "Miss":
        lines.append(
            f"Miss needs min_dist <= FINISH_DIST ({g.get('finish_dist')}) and no return. "
            f"Got min_dist={g.get('session_min_dist')} result={actual}."
        )
        lines.append("If min_dist > 100 the PASS branch goes Wrong/Late, never Miss. Code ~1182–1228.")
    elif intended == "late" and actual == "Correct":
        lines.append("Ball/player already reached the threshold during the QR session, so late search never runs.")
        lines.append("Simulator late_hold (210px) may still be inside PRESS threshold (120px) or a large GOAL threshold.")
        lines.append("Code: Correct check before search_late_* (~997–1006 GOAL, ~1098–1109 PRESS/TARGET, ~1182–1228 PASS).")
    elif intended == "late" and actual == "Wrong":
        lines.append(
            "Late finish was not accepted from the BETWEEN block. Causes: "
            "late search time window (absolute_time > LATE_SEARCH_DURATION=2.5), "
            "PASS near-line movement filter (MOVEMENT_RADIUS=120), "
            "GOAL invalid proj_t during the session (skips late search entirely), "
            "or between-session key/positions empty."
        )
        lines.append("Code: search_late_across_blocks (~689–757) and search_goal_late (~624–684).")
        if action == "GOAL":
            lines.append("GOAL late only runs if the in-session closest point has 0<=proj_t<=1. Code ~991–1019.")
        if not between_data:
            lines.append("No between-session frames were generated.")
    elif intended == "wrong" and actual != "Wrong":
        lines.append(
            f"Wrong path still scored {actual}. min_dist={g.get('session_min_dist')} "
            f"last_proj={g.get('session_last_proj')}. The 'beyond line end' point may still have "
            "valid projection or fall inside a large PRESS threshold."
        )
        lines.append("Code: get_effective_distance (~467–475) and Correct/Late branches.")
    else:
        lines.append(f"Mismatch intended={intended} actual={actual} geom={g} analyzed={result.get('Min Distance (px)')}")
    return " ".join(lines)


def main():
    cases = []
    for screen in ["4", "8", "2", "13", "14"]:
        cases.append(("PASS", [screen], "correct"))
        cases.append(("PASS", [screen], "miss"))
        cases.append(("PASS", [screen], "late"))
        cases.append(("PASS", [screen], "wrong"))
    for pair in (["2", "14"], ["12", "4"], ["3", "13"], ["12", "14"]):
        cases.append(("PASS", pair, "correct"))
        cases.append(("PASS", pair, "miss"))
        cases.append(("PASS", pair, "late"))
        cases.append(("PASS", pair, "wrong"))
    for action in ["GOAL", "TARGET", "PRESS"]:
        screen = "8" if action == "GOAL" else "2"
        cases.append((action, [screen], "correct"))
        if action != "GOAL":
            cases.append((action, [screen], "miss"))
        cases.append((action, [screen], "late"))
        cases.append((action, [screen], "wrong"))
    cases.append(("GOAL", ["1"], "correct"))
    cases.append(("GOAL", ["1"], "late"))
    cases.append(("GOAL", ["1"], "wrong"))
    cases.append(("GOAL", ["8"], "correct"))
    cases.append(("GOAL", ["8"], "late"))
    cases.append(("GOAL", ["8"], "wrong"))

    print("=" * 88)
    print("SIMUST finishing audit: intended simulator outcome vs analyze_action_with_context")
    print("=" * 88)
    mismatches = []
    for action, screens, intended in cases:
        row = run_case(action, screens, intended)
        flag = "MATCH" if row["match"] else "FAIL "
        print(
            f"{flag} {action:6} {str(screens):8} intend={intended:8} got={str(row['actual']):8} "
            f"min={row['min_dist']} win={row['winning']} t={row['time']}"
        )
        if not row["match"]:
            print(f"       {row['reason']}")
            print(f"       geom={row['geom']}")
            mismatches.append(row)

    print("-" * 88)
    print(f"{len(cases) - len(mismatches)}/{len(cases)} matched. {len(mismatches)} mismatches.")
    return 0 if not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
