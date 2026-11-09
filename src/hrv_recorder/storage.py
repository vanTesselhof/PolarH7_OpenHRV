"""Thread-safe session creation and lossless append-only RR/event storage."""

from __future__ import annotations

import csv
import json
import logging
import queue
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)
CONDITIONS = ("Baseline", "Music only", "Music + Vibration", "Rest")
RAW_FIELDS = (
    "participant_id", "session_id", "measurement_number", "sequence",
    "received_timestamp_utc", "relative_time_s", "heartbeat_timestamp_utc",
    "heartbeat_timestamp_basis", "rr_ms", "heart_rate_bpm", "condition",
    "quality_flag", "source",
)
EVENT_FIELDS = ("event_number", "timestamp_utc", "relative_time_s", "event", "note")


def utc_from_ns(value: int) -> str:
    return datetime.fromtimestamp(value / 1_000_000_000, tz=UTC).isoformat(timespec="microseconds")


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-") or "unknown"


class SessionRecorder:
    """Accept callbacks quickly and serialize every row on a dedicated writer thread."""

    def __init__(
        self,
        output_root: Path,
        participant_id: str,
        session_id: str,
        *,
        source: str = "ble",
        device_name: str = "",
        device_address: str = "",
    ) -> None:
        if not participant_id.strip() or not session_id.strip():
            raise ValueError("Versuchsperson-ID und Session-ID dürfen nicht leer sein.")
        self.participant_id = participant_id.strip()
        self.session_id = session_id.strip()
        self.source = source
        self.device_name = device_name
        self.device_address = device_address
        self.started_ns = time.time_ns()
        self.started_mono_ns = time.monotonic_ns()
        self.measurement_number, self.directory = self._reserve_directory(
            output_root, self.participant_id, self.session_id
        )
        self.raw_path = self.directory / "raw_rr.csv"
        self.events_path = self.directory / "events.csv"
        self.metadata_path = self.directory / "metadata.json"
        self._queue: queue.Queue[tuple[Any, ...] | None] = queue.Queue()
        self._lock = threading.Lock()
        self._condition = ""
        self._latest_hr: float | None = None
        self._latest_rr: float | None = None
        self._count = 0
        self._sequence = 0
        self._event_number = 0
        self._closed = False
        self._error: str | None = None
        self._metadata: dict[str, Any] = {
            "participant_id": self.participant_id,
            "session_id": self.session_id,
            "measurement_number": self.measurement_number,
            "sensor": {"name": self.device_name, "address": self.device_address,
                       "model": self.device_name if source == "ble" else "Simulated Polar H7"},
            "source": source,
            "settings": {
                "ble_library": "BleakHeart HeartRate callback",
                "unpack": False,
                "instant_rate": False,
                "reconnect_backoff_seconds": [1, 2, 4, 8, 16],
                "raw_csv_flush": "after each received heart-rate notification",
                "analysis": "separate offline step; raw_rr.csv is not modified",
            },
            "started_timestamp_utc": utc_from_ns(self.started_ns),
            "ended_timestamp_utc": None,
            "timestamp_notes": {
                "received_timestamp_utc": "BleakHeart client receive timestamp (time.time_ns); system wall clock.",
                "relative_time_s": "Monotonic elapsed time from recording start.",
                "heartbeat_timestamp_utc": "Estimate reconstructed from RR values within one notification; not a measured ECG R-peak timestamp.",
            },
            "rr_unit": "ms",
            "rr_precision_note": "Values are saved as returned by BleakHeart; its current HR decoder rounds RR intervals to whole milliseconds.",
            "heart_rate_unit": "beats/min",
            "condition_events_file": "events.csv",
            "raw_data_policy": "Append-only; no smoothing, interpolation, correction, or deletion.",
            "reconnect_policy": "Existing session stays open and appended data are retained during reconnect attempts.",
        }
        self._write_metadata()
        self._thread = threading.Thread(target=self._writer, name="rr-csv-writer", daemon=True)
        self._thread.start()

    @staticmethod
    def _reserve_directory(output_root: Path, participant_id: str,
                           session_id: str) -> tuple[int, Path]:
        root = output_root / _slug(participant_id) / _slug(session_id)
        root.mkdir(parents=True, exist_ok=True)
        n = 1
        while True:
            path = root / f"measurement_{n:03d}"
            try:
                path.mkdir()
                return n, path
            except FileExistsError:
                n += 1

    def _write_metadata(self) -> None:
        temp = self.metadata_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(self._metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temp.replace(self.metadata_path)

    def start_event(self, event: str, note: str = "") -> None:
        """Record a condition or user note without waiting for disk I/O."""
        now_ns, mono_ns = time.time_ns(), time.monotonic_ns()
        with self._lock:
            if self._closed or self._error:
                raise RuntimeError("Messung ist beendet oder der Schreibvorgang ist fehlgeschlagen.")
            if event in CONDITIONS:
                self._condition = event
            self._event_number += 1
            number = self._event_number
            # Keep state change and queue order atomic relative to BLE callbacks.
            self._queue.put(("event", number, now_ns, mono_ns, event, note))

    def submit_notification(self, data: tuple[Any, ...], *, received_ns: int | None = None,
                            monotonic_ns: int | None = None) -> None:
        """Enqueue one documented BleakHeart frame; callback work remains non-blocking."""
        now_ns = received_ns or time.time_ns()
        mono_ns = monotonic_ns or time.monotonic_ns()
        if len(data) != 4 or data[0] != "HR":
            LOGGER.warning("Unbekanntes BleakHeart-Datenformat: %r", data)
            return
        _, client_timestamp_ns, heart_rate_data, _energy = data
        bpm, rr_values = heart_rate_data
        with self._lock:
            if self._closed or self._error:
                return
            self._latest_hr = float(bpm) if bpm is not None else self._latest_hr
            self._latest_rr = float(rr_values[-1]) if rr_values else self._latest_rr
            condition = self._condition
            packet_ns = int(client_timestamp_ns) if client_timestamp_ns else now_ns
            self._queue.put(("frame", packet_ns, mono_ns, bpm, tuple(rr_values or ()), condition))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"heart_rate_bpm": self._latest_hr, "rr_ms": self._latest_rr,
                    "rr_count": self._count, "condition": self._condition,
                    "error": self._error, "directory": self.directory}

    def _writer(self) -> None:
        try:
            with self.raw_path.open("x", newline="", encoding="utf-8") as raw_file, \
                    self.events_path.open("x", newline="", encoding="utf-8") as events_file:
                raw_writer = csv.DictWriter(raw_file, fieldnames=RAW_FIELDS)
                event_writer = csv.DictWriter(events_file, fieldnames=EVENT_FIELDS)
                raw_writer.writeheader()
                event_writer.writeheader()
                raw_file.flush()
                events_file.flush()
                while True:
                    item = self._queue.get()
                    if item is None:
                        self._queue.task_done()
                        break
                    if item[0] == "event":
                        _, number, wall_ns, mono_ns, event, note = item
                        event_writer.writerow({"event_number": number, "timestamp_utc": utc_from_ns(wall_ns),
                                               "relative_time_s": f"{(mono_ns - self.started_mono_ns) / 1e9:.6f}",
                                               "event": event, "note": note})
                        events_file.flush()
                    else:
                        _, packet_ns, mono_ns, bpm, rr_values, condition = item
                        elapsed = (mono_ns - self.started_mono_ns) / 1e9
                        for index, rr in enumerate(rr_values):
                            self._sequence += 1
                            rr_ms = float(rr)
                            # BleakHeart's documented reconstruction estimates the heartbeat at
                            # packet time minus all following RR intervals in this same frame.
                            trailing_ns = round(sum(float(x) for x in rr_values[index + 1:]) * 1_000_000)
                            beat_ns = packet_ns - trailing_ns
                            raw_writer.writerow({
                                "participant_id": self.participant_id,
                                "session_id": self.session_id,
                                "measurement_number": self.measurement_number,
                                "sequence": self._sequence,
                                "received_timestamp_utc": utc_from_ns(packet_ns),
                                "relative_time_s": f"{elapsed:.6f}",
                                "heartbeat_timestamp_utc": utc_from_ns(beat_ns),
                                "heartbeat_timestamp_basis": "estimated_from_rr_within_packet",
                                "rr_ms": f"{rr_ms:.3f}",
                                "heart_rate_bpm": "" if bpm is None else f"{float(bpm):.2f}",
                                "condition": condition,
                                "quality_flag": "",
                                "source": self.source,
                            })
                            with self._lock:
                                self._count += 1
                        # Flush per notification so short UI stalls do not hold data in buffers.
                        raw_file.flush()
                    self._queue.task_done()
        except Exception as exc:  # propagate writer failures to UI snapshots
            LOGGER.exception("Fehler beim Schreiben der Messdaten")
            with self._lock:
                self._error = str(exc)

    def close(self) -> Path:
        with self._lock:
            if self._closed:
                return self.directory
            self._closed = True
        self._queue.put(None)
        self._thread.join(timeout=10)
        if self._thread.is_alive():
            raise RuntimeError("Der CSV-Schreibthread wurde nicht rechtzeitig beendet.")
        self._metadata["ended_timestamp_utc"] = utc_from_ns(time.time_ns())
        self._metadata["received_rr_intervals"] = self._count
        if self._error:
            self._metadata["writer_error"] = self._error
        self._write_metadata()
        return self.directory

