import csv
import json
import tempfile
import time
import unittest
from pathlib import Path

from hrv_recorder.storage import SessionRecorder


class SessionStorageTests(unittest.TestCase):
    def test_multiple_rr_values_are_written_in_order_with_distinct_estimates(self):
        with tempfile.TemporaryDirectory() as temporary:
            recorder = SessionRecorder(Path(temporary), "P 01", "S1", source="simulation")
            packet_ns = time.time_ns()
            mono_ns = time.monotonic_ns()
            recorder.start_event("Baseline")
            recorder.submit_notification(("HR", packet_ns, (72, [800, 810, 820]), None),
                                         received_ns=packet_ns + 5_000_000,
                                         monotonic_ns=mono_ns + 5_000_000)
            directory = recorder.close()

            with (directory / "raw_rr.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([float(row["rr_ms"]) for row in rows], [800.0, 810.0, 820.0])
            self.assertEqual([row["sequence"] for row in rows], ["1", "2", "3"])
            self.assertEqual(len({row["received_timestamp_utc"] for row in rows}), 1)
            self.assertEqual(len({row["heartbeat_timestamp_utc"] for row in rows}), 3)
            self.assertTrue(all(row["heartbeat_timestamp_basis"] == "estimated_from_rr_within_packet" for row in rows))
            self.assertTrue(all(row["condition"] == "Baseline" for row in rows))

            with (directory / "events.csv").open(newline="", encoding="utf-8") as handle:
                events = list(csv.DictReader(handle))
            self.assertEqual(events[0]["event"], "Baseline")
            metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["received_rr_intervals"], 3)
            self.assertTrue(metadata["ended_timestamp_utc"])

    def test_same_session_creates_non_overwriting_measurement_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = SessionRecorder(Path(temporary), "P1", "S1", source="simulation")
            second = SessionRecorder(Path(temporary), "P1", "S1", source="simulation")
            self.assertNotEqual(first.directory, second.directory)
            self.assertEqual(first.measurement_number, 1)
            self.assertEqual(second.measurement_number, 2)
            first.close()
            second.close()
