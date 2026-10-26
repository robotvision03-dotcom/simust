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
            {"result": "Wrong", "finishing_time": "0.90", "session_duration": "1.00", "ae": 33},
        ]
        m = simust_app.summarize_results_section_metrics(rows)
        # Wrong excluded: avg goal=(1.0+0.5)/2=0.75, avg session=(1.5+0.8)/2=1.15
        self.assertAlmostEqual(m["aet"], 0.75)
        self.assertEqual(m["aet_display"], "0.75s")
        self.assertEqual(m["aet_session_display"], "1.15s")
        # Ring = (1 - 0.75/1.15) * 100
        self.assertAlmostEqual(m["aet_percent"], (1.0 - 0.75 / 1.15) * 100.0)
        self.assertAlmostEqual(m["aac"], 200.0 / 3.0)
        self.assertAlmostEqual(m["avg_ae"], (80 + 60 + 33) / 3.0)

    def test_section_aet_ignores_wrong_completely(self):
        rows = [
            {"result": "Wrong", "finishing_time": "0.10", "session_duration": "2.00", "ae": 10},
            {"result": "Wrong", "finishing_time": "0.20", "session_duration": "2.00", "ae": 10},
        ]
        m = simust_app.summarize_results_section_metrics(rows)
        self.assertIsNone(m["aet"])
        self.assertEqual(m["aet_display"], "-")
        self.assertIsNone(m["aet_session_display"])
        self.assertEqual(m["aet_percent"], 0.0)

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
        # Displacement prefers saved boards 3 / 3 / 11 → average (not sum 17).
        self.assertEqual(final["distance_m_display"], round((3 + 3 + 11) / 3.0))
        self.assertAlmostEqual(final["total_distance"], (3 + 3 + 11) / 3.0)
        # AE/ACC/AET recompute from results when rows exist; video 3 is saved-only.
        self.assertAlmostEqual(final["avg_ae"], (80.0 + 40.0 + 43.0) / 3.0)
        self.assertAlmostEqual(final["aac"], (100.0 + 100.0 + 44.0) / 3.0)
        aet1 = (1.0 - (1.0 / 1.2)) * 100.0
        self.assertAlmostEqual(final["aet_percent"], (aet1 + aet1 + 40.0) / 3.0)

    def test_final_fallback_averages_recomputed_sections(self):
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
        # Display metres averaged: (37+42+54)/3
        self.assertEqual(final["distance_m_display"], round((37 + 42 + 54) / 3.0))
        self.assertAlmostEqual(final["total_distance"], (37 + 42 + 54) / 3.0)
        # Per video avg goals: (1.2+0.6)/2=0.9, 0.8, 1.0 → final avg 0.9
        self.assertAlmostEqual(final["aet"], 0.9)
        self.assertAlmostEqual(final["aac"], 100.0)
        self.assertAlmostEqual(final["avg_ae"], (70 + 70 + 50) / 3.0)
        self.assertGreaterEqual(final["aet_percent"], 0.0)
        self.assertLessEqual(final["aet_percent"], 100.0)

    def test_final_does_not_lock_zero_displacement_from_mid_session(self):
        """A mid-session blank Displacement board must not beat later hip stamps."""
        all_results = [
            {"id": "S1", "video_index": 1, "result": "Correct", "finishing_time": "1.0",
             "session_duration": "2.0", "ae": 80, "total_distance": 33.2},
            {"id": "S2", "video_index": 2, "result": "Correct", "finishing_time": "1.0",
             "session_duration": "2.0", "ae": 80, "total_distance": 35.6},
            {"id": "S3", "video_index": 3, "result": "Correct", "finishing_time": "1.0",
             "session_duration": "2.0", "ae": 80, "total_distance": 36.1},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            # Video 1 board was fine; videos 2–3 were saved as "-" mid-session.
            simust_app.save_section_metrics_entry(tmp, 1, {
                "total_distance": 33.2, "distance_m_display": 33,
                "aac": 100.0, "avg_ae": 80.0, "aet": 1.0, "aet_percent": 50.0,
                "aet_display": "1.00s", "ae_display": "80%",
                "correct": 1, "late": 0, "wrong": 0, "miss": 0, "total_actions": 1,
            })
            simust_app.save_section_metrics_entry(tmp, 2, {
                "total_distance": 0.0, "distance_m_display": 0,
                "aac": 100.0, "avg_ae": 80.0, "aet": 1.0, "aet_percent": 50.0,
                "aet_display": "1.00s", "ae_display": "80%",
                "correct": 1, "late": 0, "wrong": 0, "miss": 0, "total_actions": 1,
            })
            simust_app.save_section_metrics_entry(tmp, 3, {
                "total_distance": 0.0, "distance_m_display": 0,
                "aac": 100.0, "avg_ae": 80.0, "aet": 1.0, "aet_percent": 50.0,
                "aet_display": "1.00s", "ae_display": "80%",
                "correct": 1, "late": 0, "wrong": 0, "miss": 0, "total_actions": 1,
            })
            final = simust_app.aggregate_final_section_metrics(all_results, session_folder=tmp)
            panel = simust_app.build_results_ring_panel(final)
        self.assertEqual(final["distance_m_display"], round((33 + 36 + 36) / 3.0))
        self.assertGreater(panel["distance_shown"], 0)
        self.assertNotEqual(panel["distance_shown"], 0)

    def test_save_section_metrics_repairs_zero_display_when_raw_positive(self):
        with tempfile.TemporaryDirectory() as tmp:
            simust_app.save_section_metrics_entry(tmp, 2, {
                "total_distance": 35.605, "distance_m_display": 0,
                "aac": 100.0, "avg_ae": 80.0, "aet": 1.0, "aet_percent": 50.0,
                "aet_display": "1.00s", "ae_display": "80%",
                "correct": 1, "late": 0, "wrong": 0, "miss": 0, "total_actions": 1,
            })
            saved = simust_app.load_saved_section_metrics(tmp)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["distance_m_display"], 36)


if __name__ == "__main__":
    unittest.main()
