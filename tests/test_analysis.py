import csv
import tempfile
import unittest
from pathlib import Path

from hrv_recorder.analysis import analyze_session, mark_artifacts


class AnalysisTests(unittest.TestCase):
    def test_artifact_rules_flag_extremes_and_isolated_deviation(self):
        flags = mark_artifacts([1000, 1010, 990, 1600, 1005, 1000, 2500])
        self.assertEqual(flags[3], "local_deviation_over_20pct_or_200_ms")
        self.assertEqual(flags[6], "outside_300_2000_ms")
        self.assertEqual(flags[0], "")

    def test_known_sdnn_rmssd_and_pnn50(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "raw_rr.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["sequence", "relative_time_s", "rr_ms"])
                writer.writeheader()
                for index in range(40):
                    writer.writerow({"sequence": index + 1, "relative_time_s": index * 300 / 39,
                                     "rr_ms": 800 if index % 2 == 0 else 900})
            result = analyze_session(path)
            self.assertEqual(result["status"], "minimum_thresholds_met_stationarity_unassessed")
            self.assertAlmostEqual(result["metrics"]["sdnn_ms"], 50 * (40 / 39) ** 0.5, places=8)
            self.assertAlmostEqual(result["metrics"]["rmssd_ms"], 100.0, places=8)
            self.assertAlmostEqual(result["metrics"]["pnn50_percent"], 100.0, places=8)
            self.assertTrue((Path(temporary) / "analysis_rr.csv").exists())
            self.assertTrue((Path(temporary) / "hrv_results.csv").exists())
            self.assertTrue((Path(temporary) / "rr_plot.png").exists())

    def test_metrics_are_suppressed_when_duration_is_too_short(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "raw_rr.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["sequence", "relative_time_s", "rr_ms"])
                writer.writeheader()
                for index in range(40):
                    writer.writerow({"sequence": index + 1, "relative_time_s": index * 0.5,
                                     "rr_ms": 800 + (index % 2) * 10})
            result = analyze_session(path)
            self.assertEqual(result["status"], "insufficient_quality_or_duration")
            self.assertIsNone(result["metrics"]["sdnn_ms"])


if __name__ == "__main__":
    unittest.main()
