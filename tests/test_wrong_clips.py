"""Wrong-action slices use the session duration and skip everything else."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import simust_wrong_clips as clips  # noqa: E402


class WrongClipTests(unittest.TestCase):
    def test_only_wrong_actions_for_this_test_keep_their_session_time(self):
        results = [
            {"id": "S1", "result": "Correct", "video_index": 1, "session_duration": "3.000", "video_start_sec": 0.0, "field": "A"},
            {"id": "S2", "result": "Wrong", "video_index": 1, "session_duration": "3.000", "video_start_sec": 4.0, "field": "A"},
            {"id": "S3", "result": "Miss", "video_index": 1, "session_duration": "3.000", "video_start_sec": 8.0, "field": "A"},
            {"id": "S4", "result": "Wrong", "video_index": 2, "session_duration": "3.000", "video_start_sec": 12.0, "field": "A"},
            {"id": "S5", "result": "Late", "video_index": 1, "session_duration": "3.000", "video_start_sec": 16.0, "field": "A"},
            {"id": "S6", "result": "Wrong", "video_index": 1, "session_duration": "1.500", "video_start_sec": 20.0, "field": "B"},
        ]
        windows = clips.wrong_clip_windows(results, [], video_index=1)
        self.assertEqual([item["id"] for item in windows], ["S2", "S6"])
        self.assertEqual(windows[0]["duration"], 3.0)
        self.assertEqual(windows[0]["start"], 4.0)
        self.assertEqual(windows[1]["field"], "B")
        self.assertEqual(windows[1]["duration"], 1.5)
        self.assertEqual(clips.cycle_seconds(windows), 3.0 + 1.0 + 1.5 + 1.0)

    def test_duration_and_start_can_come_from_the_recognition_block(self):
        results = [{"id": "S2", "result": "Wrong", "video_index": 1, "field": "A"}]
        blocks = [{"id": "S2", "video_start_sec": 1.25, "on_sec": 3.0, "field": "A"}]
        windows = clips.wrong_clip_windows(results, blocks, video_index=1)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["start"], 1.25)
        self.assertEqual(windows[0]["duration"], 3.0)

    def test_missing_video_position_is_skipped(self):
        results = [{"id": "S1", "result": "Wrong", "video_index": 1, "session_duration": "3.0"}]
        self.assertEqual(clips.wrong_clip_windows(results, [], video_index=1), [])

    def test_simulator_puts_wrong_video_on_screens_3_and_4(self):
        """A Wrong action's frames must show on screens 3 and 4, then go dark for 1s."""
        import json
        import tempfile

        import cv2
        import numpy as np

        from simust_display_layout import (
            COACH_BAND_HEIGHT,
            COACH_BAND_WIDTH,
            DISPLAY_SLICE_ORDER,
            content_x_box,
            slice_x_span,
        )

        if clips._ffmpeg_bin() is None:
            self.skipTest("ffmpeg is not installed")

        fps = clips.REEL_FPS
        clip_frames = 8
        width, height = 320, 180

        def paint(field, index):
            # Left and right halves differ so a shared two-screen picture fails.
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            if field == "A":
                frame[:, :width // 2] = (0, 0, 220)
                frame[:, width // 2:] = (0, 220, 220)
            else:
                frame[:, :width // 2] = (220, 0, 0)
                frame[:, width // 2:] = (220, 220, 0)
            frame[:, 24 + index * 30:40 + index * 30] = (0, 0, 255)
            return frame

        with tempfile.TemporaryDirectory(prefix="wrong_sim_") as root:
            field_a = os.path.join(root, "field_A")
            field_b = os.path.join(root, "field_B")
            os.makedirs(field_a)
            os.makedirs(field_b)
            clip_a = os.path.join(root, "wrong_a.mp4")
            clip_b = os.path.join(root, "wrong_b.mp4")
            self.assertTrue(clips.write_frames_clip(
                clip_a, [paint("A", i) for i in range(clip_frames)], fps
            ))
            self.assertTrue(clips.write_frames_clip(
                clip_b, [paint("B", i) for i in range(clip_frames)], fps
            ))
            duration = clip_frames / float(fps)
            rows_a = [{
                "id": "W1", "result": "Wrong", "video_index": 1, "field": "A",
                "session_duration": duration, "video_start_sec": 0.0, "wrong_clip": clip_a,
                "ae": 0, "total_distance": 0,
            }, {
                "id": "C1", "result": "Correct", "video_index": 1, "field": "A",
                "session_duration": duration, "video_start_sec": 2.0,
            }]
            rows_b = [{
                "id": "W2", "result": "Wrong", "video_index": 1, "field": "B",
                "session_duration": duration, "video_start_sec": 0.0, "wrong_clip": clip_b,
                "ae": 0, "total_distance": 0,
            }]
            with open(os.path.join(field_a, "recognition.json"), "w", encoding="utf-8") as handle:
                json.dump([{"id": "W1", "field": "A", "on_sec": duration, "video_start_sec": 0.0}], handle)
            with open(os.path.join(field_b, "recognition.json"), "w", encoding="utf-8") as handle:
                json.dump([{"id": "W2", "field": "B", "on_sec": duration, "video_start_sec": 0.0}], handle)

            reel = clips.build_wrong_results_background(
                root, [("A", field_a, rows_a), ("B", field_b, rows_b)], 1,
            )
            self.assertIsNotNone(reel, "wrong-action reel was not built")

            from app import generate_results_video_from_results

            out_path = os.path.join(root, "results_video_1.mp4")
            ok = generate_results_video_from_results(
                rows_a,
                out_path,
                duration_seconds=reel["duration"],
                is_final=False,
                slice_video_path=reel["path"],
                session_folder=field_a,
                video_index=1,
                field="A",
                native_background=True,
            )
            self.assertTrue(ok and os.path.isfile(out_path))

            def grab(seconds):
                cap = cv2.VideoCapture(out_path)
                cap.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000.0)
                got, frame = cap.read()
                cap.release()
                self.assertTrue(got and frame is not None)
                if frame.shape[1] != COACH_BAND_WIDTH or frame.shape[0] != COACH_BAND_HEIGHT:
                    frame = cv2.resize(frame, (COACH_BAND_WIDTH, COACH_BAND_HEIGHT))
                return frame

            def patch_mean(frame, screen_id, side):
                index = DISPLAY_SLICE_ORDER.index(screen_id)
                left, right, rect_w = content_x_box(index, screen_id, COACH_BAND_WIDTH, len(DISPLAY_SLICE_ORDER))
                x = left + rect_w // 4 if side == "left" else right - rect_w // 4
                y = COACH_BAND_HEIGHT // 2
                sample = frame[y - 8:y + 8, x - 8:x + 8]
                return sample.mean(axis=(0, 1))

            showing = grab(0.05)
            gap = grab(duration + 0.4)
            again = grab(duration + clips.WRONG_GAP_SEC + 0.05)
            for screen_id in ("A3", "A4", "B3", "B4"):
                left = patch_mean(showing, screen_id, "left")
                right = patch_mean(showing, screen_id, "right")
                dark = patch_mean(gap, screen_id, "left")
                looped = patch_mean(again, screen_id, "right")
                if screen_id.startswith("A"):
                    self.assertGreater(float(left[2]), 80, f"{screen_id} left is not the whole Field A clip ({left})")
                    self.assertLess(float(left[0]), 80, f"{screen_id} left is shared with the other screen ({left})")
                    self.assertGreater(float(right[1]), 80, f"{screen_id} right is not the whole Field A clip ({right})")
                    self.assertGreater(float(right[2]), 80, f"{screen_id} right is not the whole Field A clip ({right})")
                else:
                    self.assertGreater(float(left[0]), 80, f"{screen_id} left is not the whole Field B clip ({left})")
                    self.assertLess(float(left[2]), 80, f"{screen_id} left is shared with the other screen ({left})")
                    self.assertGreater(float(right[0]), 80, f"{screen_id} right is not the whole Field B clip ({right})")
                    self.assertGreater(float(right[1]), 80, f"{screen_id} right is not the whole Field B clip ({right})")
                    self.assertLess(float(right[2]), 80, f"{screen_id} right is not the whole Field B clip ({right})")
                self.assertLess(float(dark.mean()), 40, f"{screen_id} did not go dark in the gap ({dark})")
                self.assertGreater(float(looped[1]), 80, f"{screen_id} did not continue after the gap ({looped})")

            # The empty cabinet between 3 and 4 stays black while the video plays.
            gap_index = DISPLAY_SLICE_ORDER.index("A3") + 1
            x0, x1 = slice_x_span(gap_index, COACH_BAND_WIDTH, len(DISPLAY_SLICE_ORDER))
            hole = showing[:, (x0 + x1) // 2 - 4:(x0 + x1) // 2 + 4]
            self.assertLess(float(hole.mean()), 40)

    def test_screens_3_and_4_are_separate(self):
        field_a = clips.screens_3_and_4("A")
        field_b = clips.screens_3_and_4("B")
        self.assertEqual([box["screen"] for box in field_a], ["A3", "A4"])
        self.assertEqual([box["screen"] for box in field_b], ["B3", "B4"])
        self.assertLess(field_a[0]["x"] + field_a[0]["width"], field_a[1]["x"])
        self.assertLess(field_b[0]["x"] + field_b[0]["width"], field_b[1]["x"])
        self.assertLess(field_a[1]["x"], field_b[0]["x"])
        self.assertEqual(clips.WRONG_GAP_SEC, 1.0)


if __name__ == "__main__":
    unittest.main()
