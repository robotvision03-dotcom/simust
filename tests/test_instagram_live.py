"""Instagram live helper stays off unless a test asks it to start."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import simust_instagram_live  # noqa: E402
import simust_remote  # noqa: E402


class InstagramLiveTests(unittest.TestCase):
    def test_camera_is_field_a_camera_1(self):
        os.environ.pop("INSTAGRAM_CAMERA_URL", None)
        url = simust_instagram_live._camera_url()
        self.assertIn("192.168.2.1", url)
        self.assertTrue(url.startswith("rtsp://"))

    def test_missing_credentials(self):
        os.environ.pop("INSTAGRAM_USERNAME", None)
        os.environ.pop("INSTAGRAM_PASSWORD", None)
        with self.assertRaises(RuntimeError) as raised:
            simust_instagram_live._credentials()
        self.assertIn("lab.env", str(raised.exception))

    def test_stop_when_idle(self):
        live = simust_instagram_live.stop_live()
        self.assertFalse(live["on"])
        self.assertEqual(live["field"], "A")
        self.assertEqual(live["camera"], "camera-1")

    def test_operator_can_queue_instagram_live(self):
        self.assertIn("instagram-live", simust_remote.ALLOWED_ACTIONS)

    def test_upload_url_from_broadcast(self):
        url = simust_instagram_live._upload_url({"broadcast_id": "99"})
        self.assertTrue(url.endswith("/99"))
        direct = simust_instagram_live._upload_url({
            "broadcast_id": "99",
            "upload_url": "rtmps://example.test/rtmp/key",
        })
        self.assertEqual(direct, "rtmps://example.test/rtmp/key")

    def test_ineligible_account_message(self):
        message = simust_instagram_live.explain_instagram_failure({
            "message": "At this time, your account is not eligible to use this feature. Try again later!",
            "block_reason": ["ACCOUNT_AGE_LIMIT", "NOT_PASS_FOLLOWER_COUNT_CHECK"],
            "status": "fail",
        })
        self.assertIn("1,000 followers", message)
        self.assertNotIn("block_reason", message)
