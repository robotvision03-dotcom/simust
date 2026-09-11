"""Final results video aggregates per-video rings correctly."""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("SIMUST_PUBLIC_MODE", "1")
os.environ.setdefault("SIMUST_SESSION_SECRET", "test-session-secret-not-for-production")

import app as simust_app  # noqa: E402


class FinalMetricsAggregationTests(unittest.TestCase):
    def test_section_aet_uses_correct_finishing_times(self):
        rows = [
            {"result": "Correct", "finishing_time": "1.00", "session_duration": "1.50", "ae": 80},
            {"result": "Late", "finishing_time": "0.50", "session_duration": "0.80", "ae": 60},
            {"result": "Wrong", "finishing_time": "-", "session_duration": "-", "ae": 33},
        ]
        m = simust_app.summarize_results_section_metrics(rows)
        self.assertAlmostEqual(m["aet"], 1.0)
        self.assertEqual(m["aet_display"], "1.00s")
        self.assertAlmostEqual(m["aac"], 200.0 / 3.0)
        self.assertAlmostEqual(m["avg_ae"], (80 + 60 + 33) / 3.0)

    def test_final_uses_saved_section_rings(self):
        all_results = [
            {"id": "S1", "video_index": 1, "result": "Correct", "finishing_time": "1.0",
             "session_duration": "1.2", "ae": 80, "total_distance": 99},
            {"id": "S2", "video_index": 2, "result": "Correct", "finishing_time": "1.0",
             "session_duration": "1.2", "ae": 40, "total_distance": 99},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            simust_app.save_section_metrics_entry(tmp, 1, {
                "total_distance": 3.089, "aac": 50.0, "avg_ae": 53.0,
                "aet": 0.70, "aet_percent": 40.0, "aet_display": "0.70s",
                "ae_display": "53%", "correct": 1, "late": 1, "wrong": 1, "miss": 1,
                "total_actions": 4,
            })
            simust_app.save_section_metrics_entry(tmp, 2, {
                "total_distance": 3.026, "aac": 50.0, "avg_ae": 53.0,
                "aet": 0.73, "aet_percent": 40.0, "aet_display": "0.73s",
                "ae_display": "53%", "correct": 1, "late": 1, "wrong": 1, "miss": 1,
                "total_actions": 4,
            })
            simust_app.save_section_metrics_entry(tmp, 3, {
                "total_distance": 11.498, "aac": 44.0, "avg_ae": 43.0,
                "aet": 0.77, "aet_percent": 40.0, "aet_display": "0.77s",
                "ae_display": "43%", "correct": 2, "late": 2, "wrong": 2, "miss": 3,
                "total_actions": 9,
            })
            final = simust_app.aggregate_final_section_metrics(all_results, session_folder=tmp)
        # Boards showed 3+3+11; must NOT become 18 from summing raw floats.
        self.assertEqual(final["distance_m_display"], 17)
        self.assertAlmostEqual(final["total_distance"], 17.0)
        self.assertAlmostEqual(final["avg_ae"], (53.0 + 53.0 + 43.0) / 3.0)

    def test_final_fallback_sums_recomputed_sections(self):
        all_results = [
            {"id": "S1", "video_index": 1, "result": "Correct", "finishing_time": "1.20",
             "session_duration": "1.50", "ae": 80, "total_distance": 37.2},
            {"id": "S2", "video_index": 1, "result": "Late", "finishing_time": "0.60",
             "session_duration": "0.90", "ae": 60, "total_distance": 37.2},
            {"id": "S3", "video_index": 2, "result": "Correct", "finishing_time": "0.80",
             "session_duration": "1.00", "ae": 70, "total_distance": 42.4},
            {"id": "S4", "video_index": 3, "result": "Correct", "finishing_time": "1.00",
             "session_duration": "1.20", "ae": 50, "total_distance": 54.4},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            final = simust_app.aggregate_final_section_metrics(all_results, session_folder=tmp)
        # Display metres 37+42+54 = 133 (not raw float sum).
        self.assertEqual(final["distance_m_display"], 37 + 42 + 54)
        self.assertAlmostEqual(final["aet"], 1.0)
        self.assertAlmostEqual(final["aac"], 100.0)
        self.assertAlmostEqual(final["avg_ae"], (70 + 70 + 50) / 3.0)


if __name__ == "__main__":
    unittest.main()
