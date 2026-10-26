"""Manual coach: command files, layout, and screen normalize."""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import simust_manual_coach as manual  # noqa: E402
import smart_simust_player as player  # noqa: E402


class ManualCoachHelpersTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old_cmd = manual.CMD_FILE
        self._old_status = manual.STATUS_FILE
        manual.CMD_FILE = os.path.join(self._tmpdir.name, "cmd.json")
        manual.STATUS_FILE = os.path.join(self._tmpdir.name, "status.json")

    def tearDown(self):
        manual.CMD_FILE = self._old_cmd
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

    def test_resolve_manual_coach_pass_image_finds_still(self):
        path = player._resolve_manual_coach_pass_image(
            "C:/Users/siama/Documents/simust_player"
        )
        # Repo pass.jpeg or Foundation SF-*/pass.jpeg must resolve.
        self.assertTrue(path, "expected a pass still image")
        self.assertTrue(os.path.isfile(path), path)
        self.assertIn(os.path.splitext(path)[1].lower(), {".png", ".jpg", ".jpeg", ".webp", ".bmp"})


if __name__ == "__main__":
    unittest.main()
