"""Dual-field regression: QR ROI geometry, booking overlap, dual simulator."""

from datetime import datetime, timedelta
import json

import numpy as np

import simust_fields


def test_qr_roi_b_is_right_half_xyxy():
    """detect_qr_in_roi uses (x1,y1,x2,y2). B must span 1920..3840, not a 1px strip."""
    xa1, ya1, xa2, ya2 = simust_fields.QR_ROI_A
    xb1, yb1, xb2, yb2 = simust_fields.QR_ROI_B
    assert (xa1, ya1, xa2, ya2) == (0, 0, 1920, 540)
    assert (xb1, yb1, xb2, yb2) == (1920, 0, 3840, 540)
    assert xb2 - xb1 >= 1900
    assert xa2 <= xb1  # halves abut, no overlap


def test_detect_qr_roi_crop_sizes():
    from simust_realtime import detect_qr_in_roi

    frame = np.zeros((1080, 3840, 3), dtype=np.uint8)
    # Should not raise; empty crops return ""
    data_a, _ = detect_qr_in_roi(frame, simust_fields.QR_ROI_A)
    data_b, _ = detect_qr_in_roi(frame, simust_fields.QR_ROI_B)
    assert data_a == ""
    assert data_b == ""
    # Old buggy ROI was (1920,0,1920,540) → ~1px wide; ensure B crop is wide
    x1, y1, x2, y2 = simust_fields.QR_ROI_B
    assert frame[y1:y2, x1:x2].shape[1] >= 1900


def test_slot_free_on_other_field():
    import app as app_mod

    start = datetime(2026, 9, 12, 10, 0, 0)
    end = start + timedelta(minutes=60)
    bookings = [{
        "id": "1",
        "player_id": "christiano",
        "start": start.isoformat(timespec="seconds"),
        "end": end.isoformat(timespec="seconds"),
        "field": "A",
    }]
    app_mod._assert_slot_free(bookings, start, end, "B")
    raised = False
    try:
        app_mod._assert_slot_free(bookings, start, end, "A")
    except Exception as exc:
        raised = True
        assert getattr(exc, "status_code", None) == 409
    assert raised


def test_detect_qr_roi_b_reads_screen_7_pair():
    """SF-60N dual: OpenCV fails on tall B ROI; top-band fallback must still get PASS/7."""
    import os
    import cv2
    import numpy as np
    from simust_realtime import detect_qr_in_roi, parse_qr_data, QR_ROI_A, QR_ROI_B

    path = r"C:\Users\siama\Documents\simust_player\L00-Foundation-Challenge\SF-60N\01-SF-C-PLY-180N-T2.8-S01.mp4"
    if not os.path.isfile(path):
        return
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(8.4 * 30))
    ok, frame = cap.read()
    cap.release()
    assert ok and frame is not None
    canvas = np.zeros((1080, 3840, 3), dtype=np.uint8)
    scaled = cv2.resize(frame, (3840, 528))
    canvas[0:528, :] = scaled
    raw_a, _ = detect_qr_in_roi(canvas, QR_ROI_A)
    raw_b, _ = detect_qr_in_roi(canvas, QR_ROI_B)
    act_a, scr_a, _ = parse_qr_data(raw_a)
    act_b, scr_b, _ = parse_qr_data(raw_b)
    assert act_a == "PASS" and scr_a == ["14"]
    assert act_b == "PASS" and scr_b == ["7"]


def test_dual_arena_simulators_step():
    from simust_realtime import ArenaSimulator

    sim_a = ArenaSimulator(field_id="A")
    sim_b = ArenaSimulator(field_id="B")
    assert sim_a.PLAYER_HOME[0] < 640
    assert sim_b.PLAYER_HOME[0] >= 640

    sim_a.start_action("PASS", ["12", "13"])
    sim_b.start_action("GOAL", ["8"])
    assert sim_a.active and sim_b.active

    balls_a, players_a, hip_a = sim_a.step(1280, 360)
    balls_b, players_b, hip_b = sim_b.step(1280, 360)
    assert players_a and players_b
    assert hip_a[0] < 640
    assert hip_b[0] >= 640
    # Field B player should sit on the right half of the stitched frame
    assert players_b[0]["center"][0] >= 640


def test_field_runtime_screens_belong():
    from simust_realtime import FieldRuntime

    ch_a = FieldRuntime("A")
    ch_b = FieldRuntime("B")
    assert ch_a.screens_belong(["1", "12"])
    assert not ch_a.screens_belong(["8", "9"]) or ch_a.screens_belong(["8", "9"]) is False
    # Belong is "any screen in allowed" — Field A rejects pure-B lists
    assert ch_b.screens_belong(["8", "5"])
    assert ch_a.qr_roi == simust_fields.QR_ROI_A
    assert ch_b.qr_roi == simust_fields.QR_ROI_B


def test_screen_7_is_goal_mouth_line_and_send():
    from simust_realtime import (
        GOAL_LINES,
        GOAL_MOUTH_SCREENS,
        ArenaSimulator,
        SimustRealtimeCamera,
        goal_send_origin,
        normalize_screen_id,
    )

    assert "7" in GOAL_MOUTH_SCREENS
    assert "7" in GOAL_LINES
    assert normalize_screen_id("07") == "7"
    assert goal_send_origin(["7"]) == goal_send_origin(["07"])

    cam = object.__new__(SimustRealtimeCamera)
    lines = SimustRealtimeCamera.get_goal_lines(cam, ["5"], "PRESS", ["7"])
    assert "7" in lines
    lines_goal = SimustRealtimeCamera.get_goal_lines(cam, ["7"], "GOAL", [])
    assert "7" in lines_goal

    sim = ArenaSimulator(field_id="B")
    sim.start_action("GOAL", ["7"])
    assert sim.line_p0 is not None and sim.line_p1 is not None
    assert abs(sim.start_xy[0] - goal_send_origin(["7"])[0]) < 1.0


def test_late_field_b_joins_peer_block_without_bump():
    """Late QR on B must reuse A's S{n} instead of allocating S{n+1}."""
    import threading
    from simust_realtime import SimustRealtimeCamera, FieldRuntime

    cam = object.__new__(SimustRealtimeCamera)
    cam.channels = {"A": FieldRuntime("A"), "B": FieldRuntime("B")}
    cam.shared_action_index = 0
    cam.session_lock = threading.RLock()
    a = cam.channels["A"]
    b = cam.channels["B"]
    a.session_active = True
    a.current_block_id = "S3"
    a.session_start_timestamp = 1000.0
    a.block_counter = 3
    cam.shared_action_index = 3

    info = SimustRealtimeCamera._peer_join_info(cam, b, 1001.5)
    assert info is not None
    assert info["block_id"] == "S3"
    assert info["paired_session_start"] == 1000.0


def test_no_rejoin_after_completed_block_sf60n_bug():
    """SF-60N dual: Field A must not re-enter S1 after finishing while B still active."""
    import threading
    from simust_realtime import SimustRealtimeCamera, FieldRuntime

    cam = object.__new__(SimustRealtimeCamera)
    cam.channels = {"A": FieldRuntime("A"), "B": FieldRuntime("B")}
    cam.session_lock = threading.RLock()
    cam.shared_action_index = 1
    a, b = cam.channels["A"], cam.channels["B"]

    a.session_active = False
    a.current_block_id = "S1"
    a.qr_blocks = [{"id": "S1", "action": "PASS", "screens": ["12"]}]
    b.session_active = True
    b.current_block_id = "S1"
    b.session_start_timestamp = 1000.0
    b.block_counter = 1

    assert SimustRealtimeCamera._peer_join_info(cam, a, 1003.0) is None
    assert SimustRealtimeCamera._field_completed_block(cam, a, "S1") is True

    # Active field with a new QR must not "join" peer either
    a.session_active = True
    a.qr_blocks = []
    assert SimustRealtimeCamera._peer_join_info(cam, a, 1003.0) is None


def test_sf60n_style_alternating_qr_keeps_ab_aligned():
    """Simulate A ending early then seeing a new QR while B still in S1 → A gets S2, not second S1."""
    import json
    import threading
    import numpy as np
    import simust_realtime as rt

    cam = object.__new__(rt.SimustRealtimeCamera)
    cam.channels = {"A": rt.FieldRuntime("A"), "B": rt.FieldRuntime("B")}
    cam.qr_rois = {"A": (0, 0, 1920, 540), "B": (1920, 0, 3840, 540)}
    cam.session_lock = threading.RLock()
    cam.shared_action_index = 0
    cam.simulators = {}
    cam.simulation_enabled = False
    cam.visualization_enabled = False
    cam.recording_dir = None

    def _end_locked(time_str, ts, ch=None):
        if ch is None:
            return
        if not ch.session_active:
            return
        if ch.current_qr_block:
            ch.current_qr_block["end_time"] = time_str
            ch.qr_blocks.append(ch.current_qr_block.copy())
            ch.current_qr_block = None
        ch.session_active = False
        ch.pending_end = False
        if ch.qr_state:
            ch.qr_state["last_raw_data"] = None

    def _exec_start(ts, ch):
        p = ch.pending_start
        if not p:
            return
        ch.current_action = p["action"]
        ch.current_screens = p["screens"]
        ch.current_keypoints = p.get("keypoints") or []
        ch.current_block_id = p["block_id"]
        ch.active_goal_lines = p.get("goal_lines") or {}
        ch.session_active = True
        ch.session_start_timestamp = float(p.get("paired_session_start") or ts)
        ch.session_data = []
        ch.current_qr_block = {
            "id": ch.current_block_id,
            "action": ch.current_action,
            "screens": ch.current_screens,
            "start_time": p.get("offset_start_time_str"),
            "field": ch.field_id,
            "data": [],
        }
        ch.pending_start = None

    cam._end_session_locked = _end_locked
    cam._execute_start = _exec_start
    cam._flush_pending_analysis_locked = lambda ch=None: None
    cam._schedule_late_analysis_locked = lambda ch, delay=None: None

    qrs = {
        1000.0: {
            "A": json.dumps({"action": "PASS", "screens_index": ["12"]}),
            "B": json.dumps({"action": "PASS", "screens_index": ["5"]}),
        },
        1003.5: {
            "A": json.dumps({"action": "PASS", "screens_index": ["14"]}),
            "B": json.dumps({"action": "PASS", "screens_index": ["5"]}),
        },
        1005.0: {
            "A": json.dumps({"action": "PASS", "screens_index": ["4"]}),
            "B": json.dumps({"action": "PASS", "screens_index": ["11"]}),
        },
    }
    current = {"t": 1000.0}
    orig_detect = rt.detect_qr_in_roi

    def fake_detect(frame, roi):
        payload = qrs.get(current["t"], {})
        if roi[0] >= 1920:
            raw = payload.get("B")
        else:
            raw = payload.get("A")
        return (raw or ""), None

    rt.detect_qr_in_roi = fake_detect
    frame = np.zeros((1080, 3840, 3), dtype=np.uint8)
    try:
        current["t"] = 1000.0
        cam.process_qr_detection(frame, "00:00:00.000", 1000.0)
        cam.check_pending(1000.9, "00:00:00.900")
        assert cam.channels["A"].session_active and cam.channels["B"].session_active
        assert cam.channels["A"].current_block_id == cam.channels["B"].current_block_id == "S1"

        current["t"] = 1003.5
        cam.process_qr_detection(frame, "00:00:03.500", 1003.5)
        cam.check_pending(1004.5, "00:00:04.500")
        a_ids = [b["id"] for b in cam.channels["A"].qr_blocks]
        assert a_ids.count("S1") == 1
        assert cam.channels["A"].current_block_id == "S2"
        assert cam.channels["A"].session_active
        assert not cam.channels["B"].session_active

        current["t"] = 1005.0
        cam.channels["B"].qr_state["last_raw_data"] = None
        cam.channels["A"].qr_state["last_raw_data"] = None
        if cam.channels["A"].session_active:
            cam._end_paired_sessions_now("00:00:04.900", 1004.9, cam.channels["A"])
        cam.process_qr_detection(frame, "00:00:05.000", 1005.0)
        cam.check_pending(1005.9, "00:00:05.900")
        assert cam.channels["A"].current_block_id == cam.channels["B"].current_block_id
        assert cam.channels["A"].current_block_id != "S1"
        assert [b["id"] for b in cam.channels["A"].qr_blocks].count("S1") == 1
    finally:
        rt.detect_qr_in_roi = orig_detect

def test_load_active_fields_from_players_json(tmp_path):
    path = tmp_path / "players_fields.json"
    path.write_text(
        json.dumps({
            "fields": {
                "A": None,
                "B": {"player_id": "p2", "player_name": "B", "field": "B"},
            },
            "players": [{"player_id": "p2", "field": "B"}],
        }),
        encoding="utf-8",
    )
    assert simust_fields.load_active_fields(str(path)) == {"B"}

    path.write_text(
        json.dumps({
            "fields": {
                "A": {"player_id": "p1", "field": "A"},
                "B": None,
            }
        }),
        encoding="utf-8",
    )
    assert simust_fields.load_active_fields(str(path)) == {"A"}

    path.write_text(
        json.dumps({
            "fields": {
                "A": {"player_id": "p1", "field": "A"},
                "B": {"player_id": "p2", "field": "B"},
            }
        }),
        encoding="utf-8",
    )
    assert simust_fields.load_active_fields(str(path)) == {"A", "B"}


def test_inactive_field_skips_qr_start():
    import threading
    import numpy as np
    import simust_realtime as rt

    cam = rt.SimustRealtimeCamera.__new__(rt.SimustRealtimeCamera)
    cam.session_lock = threading.Lock()
    cam.channels = {"A": rt.FieldRuntime("A"), "B": rt.FieldRuntime("B")}
    cam.simulators = {
        "A": type("S", (), {"outcome_index": 0})(),
        "B": type("S", (), {"outcome_index": 0})(),
    }
    cam.shared_action_index = 0
    cam.visualization_enabled = False
    cam.qr_rois = {"A": simust_fields.QR_ROI_A, "B": simust_fields.QR_ROI_B}
    cam.active_fields = {"B"}
    started = []

    def schedule(action, screens, keypoints, block_id, time_str, ts, ch,
                 paired_session_start=None, paired_offset_str=None):
        started.append(ch.field_id)
        ch.pending_start = {"block_id": block_id}
        ch.current_block_id = block_id

    cam.schedule_session_start = schedule
    cam.schedule_session_end = lambda *a, **k: None
    cam._end_paired_sessions_now = lambda *a, **k: None
    cam._end_session_locked = lambda *a, **k: None

    qrs = {
        "A": json.dumps({"action": "PASS", "screens_index": ["12"]}),
        "B": json.dumps({"action": "PASS", "screens_index": ["5"]}),
    }
    orig = rt.detect_qr_in_roi

    def fake_detect(frame, roi):
        return (qrs["B"] if roi[0] >= 1920 else qrs["A"]), None

    rt.detect_qr_in_roi = fake_detect
    try:
        frame = np.zeros((1080, 3840, 3), dtype=np.uint8)
        cam.process_qr_detection(frame, "00:00:00.000", 1000.0)
        assert started == ["B"]
        assert cam.channels["A"].pending_start is None
    finally:
        rt.detect_qr_in_roi = orig
