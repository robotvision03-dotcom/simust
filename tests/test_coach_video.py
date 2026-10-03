"""Coach clip selection for the final results film."""
import os
import tempfile
import unittest

from app import (  # noqa: E402
    _coach_for_player,
    _file_accuracy_span,
    _span_holds_accuracy,
    select_coach_video,
)


class CoachSelectionTests(unittest.TestCase):
    def test_age_and_gender_folders(self):
        self.assertEqual(_coach_for_player("Male", "10"), "Jason")
        self.assertEqual(_coach_for_player("Male", "13"), "Jason")
        self.assertEqual(_coach_for_player("Male", "16"), "Carlos")
        self.assertEqual(_coach_for_player("Male", "19"), "Khalid")
        self.assertEqual(_coach_for_player("Male", "25"), "Victor")
        self.assertEqual(_coach_for_player("Female", "8"), "Mila")
        self.assertEqual(_coach_for_player("Female", "16"), "Noor")
        self.assertEqual(_coach_for_player("Female", "30"), "Elena")

    def test_irregular_filenames(self):
        self.assertEqual(_file_accuracy_span("U-13-Jason-50_-V01.mp4"), (0, 50))
        self.assertEqual(_file_accuracy_span("U-13-Jason95-100_-V01.mp4"), (95, 100))
        self.assertEqual(_file_accuracy_span("U-13-Mila-0-50_-V01.mp4"), (0, 50))
        self.assertEqual(_file_accuracy_span("U-16-Carlos-00-50_-V01.mp4"), (0, 50))
        self.assertEqual(_file_accuracy_span("Senior-Victor-90-95_-V01.mp4"), (90, 95))

    def test_band_edges(self):
        self.assertTrue(_span_holds_accuracy(0, 0, 50))
        self.assertTrue(_span_holds_accuracy(50, 0, 50))
        self.assertFalse(_span_holds_accuracy(50, 50, 60))
        self.assertTrue(_span_holds_accuracy(50.1, 50, 60))
        self.assertTrue(_span_holds_accuracy(95, 90, 95))
        self.assertTrue(_span_holds_accuracy(100, 95, 100))
        self.assertFalse(_span_holds_accuracy(95, 95, 100))

    def test_picks_matching_file(self):
        with tempfile.TemporaryDirectory() as root:
            folder = os.path.join(root, "Carlos")
            os.makedirs(folder)
            names = [
                "U-16-Carlos-00-50_-V01.mp4",
                "U-16-Carlos-50-60_-V01.mp4",
                "U-16-Carlos-95-100_-V01.mp4",
            ]
            for name in names:
                open(os.path.join(folder, name), "wb").close()
            chosen = select_coach_video("Male", "15", 42, coach_dir=root)
            self.assertTrue(chosen.endswith("U-16-Carlos-00-50_-V01.mp4"))
            chosen = select_coach_video("Male", "15", 100, coach_dir=root)
            self.assertTrue(chosen.endswith("U-16-Carlos-95-100_-V01.mp4"))

    def test_real_coach_files_when_present(self):
        root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "coach")
        if not os.path.isdir(os.path.join(root, "Jason")):
            self.skipTest("coach videos are not in this checkout")
        low = select_coach_video("Male", "12", 10, coach_dir=root)
        top = select_coach_video("Male", "12", 97, coach_dir=root)
        mila = select_coach_video("Female", "11", 20, coach_dir=root)
        self.assertTrue(os.path.basename(low).startswith("U-13-Jason-50"))
        self.assertIn("95-100", os.path.basename(top))
        self.assertIn("0-50", os.path.basename(mila))
        senior = select_coach_video("Female", "22", 55, coach_dir=root)
        self.assertIn("Senior-Elena-50-60", os.path.basename(senior))


if __name__ == "__main__":
    unittest.main()
