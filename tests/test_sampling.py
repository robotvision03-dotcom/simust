"""Sampling live On/Off + Start/Stop clean 3840×1080 video."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

import simust_sampling as samp


class SamplingRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ctrl = os.path.join(self.tmp.name, "sampling_control.json")
        self.disp = os.path.join(self.tmp.name, "sampling_display.json")
        self.rec = os.path.join(self.tmp.name, "recordings")
        os.makedirs(self.rec, exist_ok=True)
        self._env = patch.dict(
            os.environ,
            {
                "SIMUST_SAMPLING_CONTROL": self.ctrl,
                "SIMUST_SAMPLING_DISPLAY": self.disp,
                "SIMUST_PLAYER_DIRECTORY": self.tmp.name,
                "SIMUST_REALTIME_DIR": self.rec,
            },
            clear=False,
        )
        self._env.start()
        samp.set_live(False)
        with samp._lock:
            samp._control.update(
                {
                    "live": False,
                    "active": False,
                    "saved_count": 0,
                    "last_path": "",
                    "video_path": "",
                    "started_at": "",
                    "stopped_at": "",
                    "frame_count": 0,
                    "error": "",
                }
            )
            samp._preview = {}

    def tearDown(self):
        samp.set_live(False)
        samp.stop_sample()
        try:
            samp._stop_cam_workers()
        except Exception:
            pass
        self._env.stop()
        self.tmp.cleanup()

    def test_save_raw_frame_is_always_3840x1080(self):
        small = np.zeros((360, 1280, 3), dtype=np.uint8)
        path = samp.save_raw_frame(small)
        self.assertTrue(path and os.path.isfile(path))
        import cv2

        saved = cv2.imread(path)
        self.assertEqual(saved.shape[1], 3840)
        self.assertEqual(saved.shape[0], 1080)

    def test_live_on_shows_preview_without_recording(self):
        frame = np.zeros((1080, 3840, 3), dtype=np.uint8)
        frame[:] = (10, 20, 30)

        with patch.object(samp, "capture_full_stitch_frame", return_value=frame.copy()):
            with patch.object(
                samp,
                "_stitch_pair",
                return_value=frame.copy(),
            ):
                with patch.object(samp, "_camera_urls", return_value=("", "")):
                    ctrl = samp.set_live(True)
                    self.assertTrue(ctrl.get("live"))
                    self.assertFalse(samp.is_active())
                    deadline = time.time() + 2.0
                    preview = {}
                    while time.time() < deadline:
                        st = samp.public_status()
                        preview = (st.get("frame") or {})
                        if preview.get("data_url"):
                            break
                        time.sleep(0.05)
                    self.assertTrue(preview.get("data_url"))
                    self.assertTrue(samp.public_status().get("live"))
                    samp.set_live(False)
                    self.assertFalse(samp.is_live())
                    self.assertFalse((samp.public_status().get("frame") or {}).get("data_url"))

    def test_start_stop_writes_video(self):
        frame = np.zeros((1080, 3840, 3), dtype=np.uint8)
        frame[:] = (20, 40, 60)

        def fake_capture():
            return frame.copy()

        with patch.object(samp, "capture_full_stitch_frame", side_effect=fake_capture):
            with patch.object(samp, "_camera_urls", return_value=("", "")):
                samp.set_live(True)
                ctrl = samp.start_sample()
                self.assertTrue(samp.is_active())
                self.assertTrue(samp.is_live())
                self.assertTrue(ctrl.get("video_path") or ctrl.get("last_path"))
                deadline = time.time() + 2.5
                while time.time() < deadline:
                    st = samp.public_status()
                    if int(st.get("frame_count") or 0) >= 3:
                        break
                    time.sleep(0.05)
                st = samp.public_status()
                self.assertGreaterEqual(int(st.get("frame_count") or 0), 1)
                self.assertTrue((st.get("frame") or {}).get("data_url"))
                # Playlist should have published a screen pair for A1/B1 quickly.
                self.assertGreaterEqual(int(st.get("playlist_screen") or 0), 1)
                display_path = samp.display_file_path()
                self.assertTrue(os.path.isfile(display_path))
                stopped = samp.stop_sample()
                self.assertFalse(samp.is_active())
                self.assertTrue(samp.is_live())
                path = stopped.get("video_path") or stopped.get("last_path") or ""
                self.assertTrue(path and os.path.isfile(path))
                self.assertIn("data_samples", path)
                self.assertTrue(
                    path.lower().endswith(".mp4") or path.lower().endswith(".avi")
                )
                self.assertGreater(os.path.getsize(path), 1000)
                samp.set_live(False)

    def test_slow_capture_keeps_wall_clock_duration(self):
        """Slow stitches must not shrink playback (writer repeats last frame)."""
        frame = np.zeros((1080, 3840, 3), dtype=np.uint8)
        frame[:] = (30, 50, 70)

        def slow_capture():
            time.sleep(0.20)  # ~5fps capture, video marked 15fps
            return frame.copy()

        with patch.object(samp, "capture_full_stitch_frame", side_effect=slow_capture):
            with patch.object(samp, "_camera_urls", return_value=("", "")):
                # Skip heavy playlist / display work for this timing test.
                with patch.object(samp, "_start_playlist"):
                    with patch.object(samp, "_stop_playlist"):
                        samp.set_live(True)
                        # Seed one frame so the paced writer can start immediately.
                        samp._set_last_frame(frame)
                        t0 = time.time()
                        samp.start_sample()
                        time.sleep(1.2)
                        stopped = samp.stop_sample()
                        elapsed = time.time() - t0
                        frames = int(stopped.get("frame_count") or 0)
                        expected = int(samp.RECORD_FPS * max(0.9, elapsed - 0.25))
                        self.assertGreaterEqual(frames, max(10, expected - 8))
                        path = stopped.get("video_path") or stopped.get("last_path") or ""
                        self.assertTrue(path and os.path.isfile(path))
                        import cv2

                        cap = cv2.VideoCapture(path)
                        self.assertTrue(cap.isOpened())
                        ok, _ = cap.read()
                        self.assertTrue(ok)
                        n = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                        fps = float(cap.get(cv2.CAP_PROP_FPS) or samp.RECORD_FPS) or 15.0
                        cap.release()
                        duration = n / fps
                        self.assertGreaterEqual(duration, 0.85)
                        samp.set_live(False)

    def test_open_writer_prefers_playable_codec(self):
        path = os.path.join(self.rec, "codec_probe.mp4")
        writer, out = samp._open_writer(path)
        self.assertIsNotNone(writer)
        self.assertTrue(writer.isOpened())
        # Prefer independent-frame MJPG AVI so clips do not look frozen.
        self.assertTrue(str(out).lower().endswith(".avi"))
        frame = np.zeros((1080, 3840, 3), dtype=np.uint8)
        frame[:] = (10, 20, 30)
        for _ in range(15):
            writer.write(frame)
        writer.release()
        self.assertTrue(os.path.isfile(out))
        import cv2

        cap = cv2.VideoCapture(out)
        self.assertTrue(cap.isOpened())
        ok, got = cap.read()
        self.assertTrue(ok)
        self.assertIsNotNone(got)
        cap.release()

    def test_rejects_bottom_half_smear(self):
        good = np.zeros((1080, 1920, 3), dtype=np.uint8)
        rng = np.random.default_rng(0)
        good[:] = rng.integers(40, 200, size=good.shape, dtype=np.uint8)
        self.assertFalse(samp._frame_looks_corrupt(good))
        bad = good.copy()
        # Purple/black smear on bottom half (camera-1 incomplete decode).
        bad[540:, :, :] = np.array([90, 10, 40], dtype=np.uint8)
        self.assertTrue(samp._frame_looks_corrupt(bad))

    def test_publish_screen_pair_writes_a_and_b(self):
        left = {"path": __file__, "kind": "pass", "name": "pass.png"}
        right = {"path": __file__, "kind": "number", "name": "3.png"}
        samp._publish_screen_pair(2, left, right, seq=99)
        with open(samp.display_file_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertTrue(data.get("active"))
        self.assertEqual(data.get("screen_n"), 2)
        self.assertIn("A2", data.get("images") or {})
        self.assertIn("B2", data.get("images") or {})
        samp.clear_display()

    def test_cabinet_fills_all_12_with_targets_and_distractors(self):
        pools = samp.collect_content_pools()
        self.assertTrue(pools.get("players_targets") or pools.get("number_packs"))
        images, scale, kinds, label, style = samp._build_cabinet_images(3, pools)
        self.assertEqual(len(images), 12)
        for field in ("A", "B"):
            for slot in range(1, 7):
                sid = f"{field}{slot}"
                self.assertIn(sid, images)
                self.assertTrue(os.path.isfile(images[sid]))
        self.assertTrue(str(kinds.get("A3") or "").startswith("target:"))
        self.assertTrue(str(kinds.get("B3") or "").startswith("target:"))
        self.assertTrue(str(kinds.get("A1") or "").startswith("distractor:"))
        self.assertTrue(str(kinds.get("B6") or "").startswith("distractor:"))
        if style == "players":
            self.assertAlmostEqual(scale, samp.PLAYERS_IMAGE_SCALE, places=3)
        else:
            self.assertAlmostEqual(scale, samp.NUMBER_TILE_SCALE, places=3)
        samp._publish_cabinet(
            3,
            images,
            scale,
            kinds,
            label,
            seq=42,
            uniform_player_stills=(style == "players"),
        )
        with open(samp.display_file_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(data.get("screen_n"), 3)
        self.assertEqual(len(data.get("images") or {}), 12)
        self.assertAlmostEqual(float(data.get("scale") or 0), float(scale), places=3)
        if style == "players":
            self.assertTrue(data.get("uniform_player_stills"))
        samp.clear_display()

    def test_display_scales_match_real_tests(self):
        # Same constants as smart_simust_player Entry/Activated/HP/Elite players.
        self.assertAlmostEqual(samp.PLAYERS_IMAGE_SCALE, 0.9427, places=3)
        self.assertEqual(samp.NUMBER_TILE_SCALE, 1.0)

    def test_publish_start_cue_on_focus_screens(self):
        samp._publish_start_cue(4, seq=7)
        with open(samp.display_file_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(data.get("screen_n"), 4)
        images = data.get("images") or {}
        self.assertEqual(len(images), 12)
        self.assertIn("A4", images)
        self.assertIn("B4", images)
        self.assertTrue(os.path.isfile(images["A4"]))
        self.assertEqual((data.get("kinds") or {}).get("A4"), "cue:sta")
        self.assertEqual((data.get("kinds") or {}).get("B4"), "cue:sta")
        self.assertEqual((data.get("kinds") or {}).get("A1"), "cue:blank")
        self.assertAlmostEqual(float(data.get("scale") or 0), 1.0, places=3)
        self.assertEqual(samp.START_CUE_TEXT, "STA")
        self.assertEqual(samp.START_FLASH_S, 1.0)
        # STA tile must exist and be the focus image.
        sta = samp._start_tile_path()
        self.assertTrue(sta and os.path.isfile(sta))
        self.assertEqual(images["A4"], sta)
        samp.clear_display()


if __name__ == "__main__":
    unittest.main()
