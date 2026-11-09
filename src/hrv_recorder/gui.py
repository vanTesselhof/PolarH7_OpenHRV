"""PySide6 live recorder interface. BLE, file I/O, and simulation stay off the UI path."""

from __future__ import annotations

import logging
import math
import queue
import sys
import time
from collections import deque
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)
import pyqtgraph as pg

from .analysis import analyze_session
from .ble import BleConnection, Sensor, discover_sensors
from .storage import CONDITIONS, SessionRecorder

LOGGER = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("HRV Recorder · Polar H7")
        self.resize(1120, 760)
        self.events: queue.SimpleQueue[tuple[str, object]] = queue.SimpleQueue()
        self.recorder: SessionRecorder | None = None
        self.ble_worker: BleConnection | None = None
        self.connected = False
        self.simulation_active = False
        self.simulation_index = 0
        self.record_started = 0.0
        self.points: deque[tuple[float, float]] = deque(maxlen=600)
        self.current_directory: Path | None = None
        self._build_ui()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh)
        self.refresh_timer.start(200)
        self.sim_timer = QTimer(self)
        self.sim_timer.timeout.connect(self._simulate_tick)
        self.scan_timer: QTimer | None = None

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)

        details = QGroupBox("Messungsdaten")
        form = QFormLayout(details)
        self.participant = QLineEdit()
        self.participant.setPlaceholderText("z. B. P001 (pseudonymisiert)")
        self.session = QLineEdit()
        self.session.setPlaceholderText("z. B. Session_01")
        self.output = QLineEdit(str(Path.home() / "Documents" / "HRV_Messungen"))
        browse = QPushButton("Ordner …")
        browse.clicked.connect(self._choose_output)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output, 1)
        output_row.addWidget(browse)
        output_widget = QWidget()
        output_widget.setLayout(output_row)
        form.addRow("Versuchsperson-ID", self.participant)
        form.addRow("Session-ID", self.session)
        form.addRow("Speicherort", output_widget)
        layout.addWidget(details)

        connection = QGroupBox("Sensorverbindung")
        connection_layout = QHBoxLayout(connection)
        self.simulation_check = QCheckBox("Simulationsmodus (ohne Sensor)")
        self.simulation_check.toggled.connect(self._simulation_toggled)
        self.scan_button = QPushButton("Sensoren suchen")
        self.scan_button.clicked.connect(self._scan)
        self.devices = QComboBox()
        self.devices.setMinimumWidth(360)
        self.connect_button = QPushButton("Verbinden")
        self.connect_button.clicked.connect(self._connect)
        self.disconnect_button = QPushButton("Trennen")
        self.disconnect_button.clicked.connect(self._disconnect)
        self.disconnect_button.setEnabled(False)
        connection_layout.addWidget(self.simulation_check)
        connection_layout.addWidget(self.scan_button)
        connection_layout.addWidget(self.devices, 1)
        connection_layout.addWidget(self.connect_button)
        connection_layout.addWidget(self.disconnect_button)
        layout.addWidget(connection)

        metrics = QGridLayout()
        self.metric_hr = self._metric(metrics, 0, "Herzfrequenz", "— bpm")
        self.metric_rr = self._metric(metrics, 1, "Letztes RR-Intervall", "— ms")
        self.metric_duration = self._metric(metrics, 2, "Messdauer", "00:00:00")
        self.metric_count = self._metric(metrics, 3, "RR-Intervalle", "0")
        metric_box = QGroupBox("Live-Messung")
        metric_box.setLayout(metrics)
        layout.addWidget(metric_box)

        self.plot = pg.PlotWidget()
        self.plot.setBackground("w")
        self.plot.setLabel("left", "RR-Intervall", units="ms")
        self.plot.setLabel("bottom", "Zeit seit Messbeginn", units="s")
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        self.plot_line = self.plot.plot([], [], pen=pg.mkPen("#147d92", width=2))
        layout.addWidget(self.plot, 1)

        controls = QHBoxLayout()
        self.start_button = QPushButton("Aufzeichnung starten")
        self.start_button.clicked.connect(self._start_recording)
        self.stop_button = QPushButton("Aufzeichnung stoppen")
        self.stop_button.clicked.connect(self._stop_recording)
        self.stop_button.setEnabled(False)
        self.analyze_button = QPushButton("CSV analysieren …")
        self.analyze_button.clicked.connect(self._analyze)
        controls.addWidget(self.start_button)
        controls.addWidget(self.stop_button)
        controls.addStretch(1)
        controls.addWidget(self.analyze_button)
        layout.addLayout(controls)

        conditions = QGroupBox("Versuchsbedingungen markieren")
        condition_layout = QHBoxLayout(conditions)
        for condition in CONDITIONS:
            button = QPushButton(condition)
            button.clicked.connect(lambda _checked=False, value=condition: self._mark_condition(value))
            condition_layout.addWidget(button)
        note_button = QPushButton("Freie Anmerkung …")
        note_button.clicked.connect(self._mark_note)
        condition_layout.addWidget(note_button)
        layout.addWidget(conditions)

        self.status = QLabel("Bereit · Bluetooth noch nicht verbunden")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.setCentralWidget(root)

    @staticmethod
    def _metric(layout: QGridLayout, column: int, title: str, value: str) -> QLabel:
        title_label = QLabel(title)
        title_label.setStyleSheet("color: #52606a; font-size: 12px")
        value_label = QLabel(value)
        value_label.setStyleSheet("font-size: 22px; font-weight: 600")
        layout.addWidget(title_label, 0, column)
        layout.addWidget(value_label, 1, column)
        return value_label

    def _choose_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Speicherordner wählen", self.output.text())
        if path:
            self.output.setText(path)

    def _simulation_toggled(self, enabled: bool) -> None:
        self.scan_button.setEnabled(not enabled)
        self.connect_button.setEnabled(not enabled)
        if enabled and self.ble_worker and self.ble_worker.is_alive():
            self._disconnect()
        if enabled:
            self.status.setText("Simulationsmodus bereit · Messdaten sind als Simulation gekennzeichnet")
        elif not self.connected:
            self.status.setText("Bereit · Bluetooth noch nicht verbunden")

    def _scan(self) -> None:
        self.scan_button.setEnabled(False)
        self.status.setText("Suche nach BLE-Herzfrequenzsensoren …")

        def worker() -> None:
            try:
                result = __import__("asyncio").run(discover_sensors())
                self.events.put(("devices", result))
            except Exception as exc:
                self.events.put(("scan_error", str(exc)))

        import threading
        threading.Thread(target=worker, name="ble-scanner", daemon=True).start()

    def _connect(self) -> None:
        sensor = self.devices.currentData()
        if not isinstance(sensor, Sensor):
            QMessageBox.information(self, "Sensor auswählen", "Bitte zuerst einen gefundenen Sensor auswählen.")
            return
        if self.ble_worker and self.ble_worker.is_alive():
            return
        self.ble_worker = BleConnection(sensor, lambda: self.recorder, self.events)
        self.ble_worker.start()
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(True)

    def _disconnect(self) -> None:
        if self.ble_worker:
            self.ble_worker.stop()
        self.disconnect_button.setEnabled(False)

    def _start_recording(self) -> None:
        if not self.simulation_check.isChecked() and not self.connected:
            QMessageBox.warning(self, "Keine Sensorverbindung", "Verbinde zuerst den Polar H7 oder aktiviere den Simulationsmodus.")
            return
        try:
            self.recorder = SessionRecorder(
                Path(self.output.text()).expanduser(), self.participant.text(), self.session.text(),
                source="simulation" if self.simulation_check.isChecked() else "ble",
                device_name="Simulated Polar H7" if self.simulation_check.isChecked() else (self.devices.currentData().name if self.devices.currentData() else ""),
                device_address="" if self.simulation_check.isChecked() else (self.devices.currentData().address if self.devices.currentData() else ""),
            )
        except Exception as exc:
            QMessageBox.critical(self, "Messung konnte nicht starten", str(exc))
            self.recorder = None
            return
        self.current_directory = self.recorder.directory
        self.points.clear()
        self.plot_line.setData([], [])
        self.record_started = time.monotonic()
        self.simulation_index = 0
        if self.simulation_check.isChecked():
            self.simulation_active = True
            self.sim_timer.start(1000)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.participant.setEnabled(False)
        self.session.setEnabled(False)
        self.output.setEnabled(False)
        self.simulation_check.setEnabled(False)
        self.status.setText(f"Aufzeichnung läuft · {self.current_directory}")

    def _stop_recording(self) -> None:
        self.simulation_active = False
        self.sim_timer.stop()
        self.stop_button.setEnabled(False)
        if self.recorder is None:
            return
        recorder = self.recorder
        self.recorder = None
        self.participant.setEnabled(True)
        self.session.setEnabled(True)
        self.output.setEnabled(True)
        self.simulation_check.setEnabled(True)
        try:
            directory = recorder.close()
            self.status.setText(f"Messung gespeichert · {directory}")
            self.current_directory = directory
            self.start_button.setEnabled(True)
        except Exception as exc:
            QMessageBox.critical(self, "Speicherfehler", str(exc))
            self.start_button.setEnabled(True)
        if recorder.snapshot().get("error"):
            QMessageBox.critical(self, "Schreibfehler", str(recorder.snapshot()["error"]))

    def _mark_condition(self, condition: str) -> None:
        if not self.recorder:
            self.status.setText("Bedingungsmarkierungen sind während einer Aufzeichnung verfügbar.")
            return
        try:
            self.recorder.start_event(condition)
            self.status.setText(f"Bedingung markiert: {condition}")
        except Exception as exc:
            QMessageBox.critical(self, "Ereignis konnte nicht gespeichert werden", str(exc))

    def _mark_note(self) -> None:
        if not self.recorder:
            self.status.setText("Anmerkungen sind während einer Aufzeichnung verfügbar.")
            return
        note, accepted = QInputDialog.getText(self, "Freie Anmerkung", "Ereignistext:")
        if accepted and note.strip():
            try:
                self.recorder.start_event("Freie Anmerkung", note.strip())
                self.status.setText("Anmerkung mit Zeitstempel gespeichert.")
            except Exception as exc:
                QMessageBox.critical(self, "Anmerkung konnte nicht gespeichert werden", str(exc))

    def _simulate_tick(self) -> None:
        if not self.recorder or not self.simulation_active:
            return
        index = self.simulation_index
        rr = 820.0 + 24.0 * math.sin(index * 0.21) + 8.0 * math.sin(index * 0.047)
        bpm = round(60_000 / rr)
        frame = ("HR", time.time_ns(), (bpm, [round(rr)]), None)
        self.recorder.submit_notification(frame)
        self.simulation_index += 1
        elapsed = time.monotonic() - self.record_started
        self.points.append((elapsed, rr))
        self.plot_line.setData([p[0] for p in self.points], [p[1] for p in self.points])

    def _analyze(self) -> None:
        raw_path, _ = QFileDialog.getOpenFileName(self, "raw_rr.csv auswählen", str(self.output.text()), "CSV-Dateien (*.csv)")
        if not raw_path:
            return
        raw_file = Path(raw_path)
        derived_files = [raw_file.parent / name for name in ("analysis_rr.csv", "hrv_results.csv", "rr_plot.png")]
        existing = [path.name for path in derived_files if path.exists()]
        if existing:
            answer = QMessageBox.question(
                self, "Analyse erneut ausführen?",
                "Diese erzeugten Analyse-Dateien werden aktualisiert: " + ", ".join(existing) +
                "\n\nraw_rr.csv bleibt unverändert. Fortfahren?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            summary = analyze_session(raw_file)
        except Exception as exc:
            QMessageBox.critical(self, "Analyse fehlgeschlagen", str(exc))
            return
        metrics = summary["metrics"]
        lines = [f"Status: {summary['status']}",
                 f"Dauer: {summary['duration_s']:.1f} s · gültig: {summary['valid_intervals']} · markiert: {summary['artifact_intervals']} ({summary['artifact_fraction']:.1%})"]
        if summary["status"] == "minimum_thresholds_met_stationarity_unassessed":
            units = {"mean_hr_bpm": "bpm", "mean_nn_ms": "ms", "sdnn_ms": "ms", "rmssd_ms": "ms", "pnn50_percent": "%"}
            lines.extend(f"{name}: {metrics[name]:.2f} {units[name]}" for name in metrics if metrics[name] is not None)
        else:
            lines.append("Kennwerte unterdrückt: mindestens 300 s, 30 gültige Intervalle und höchstens 20 % markierte Intervalle erforderlich.")
        lines.append("Die Software prüft keine Stationarität oder Arrhythmien; ein bestandener Mindestdaten-Check ist keine Validitätsgarantie.")
        lines.append(f"\nDateien gespeichert in:\n{summary['directory']}")
        QMessageBox.information(self, "HRV-Auswertung", "\n".join(lines))

    def _refresh(self) -> None:
        while not self.events.empty():
            kind, payload = self.events.get()
            if kind == "status":
                self.status.setText(str(payload))
                self.connected = str(payload).startswith("Verbunden") or str(payload).startswith("Verbunden ·")
                self.connect_button.setEnabled(not self.connected and not (self.ble_worker and self.ble_worker.is_alive()))
                self.disconnect_button.setEnabled(self.ble_worker is not None and self.ble_worker.is_alive())
            elif kind == "devices":
                self.devices.clear()
                for sensor in payload:
                    self.devices.addItem(str(sensor), sensor)
                self.scan_button.setEnabled(not self.simulation_check.isChecked())
                self.status.setText(f"{len(payload)} passender BLE-Sensor(en) gefunden" if payload else "Kein passender Herzfrequenzsensor gefunden.")
            elif kind == "scan_error":
                self.scan_button.setEnabled(not self.simulation_check.isChecked())
                self.status.setText(f"Sensorsuche fehlgeschlagen: {payload}")
            elif kind == "frame":
                try:
                    _tag, timestamp, (bpm, rr_values), _energy = payload
                    if rr_values:
                        for rr in rr_values:
                            elapsed = time.monotonic() - self.record_started if self.recorder else (self.points[-1][0] + 1 if self.points else 0)
                            self.points.append((elapsed, float(rr)))
                        self.plot_line.setData([p[0] for p in self.points], [p[1] for p in self.points])
                    if bpm is not None:
                        self.metric_hr.setText(f"{bpm} bpm")
                    if rr_values:
                        self.metric_rr.setText(f"{rr_values[-1]} ms")
                except (ValueError, TypeError):
                    LOGGER.debug("Unbekanntes Live-Frame: %r", payload)
        if self.recorder:
            snapshot = self.recorder.snapshot()
            if snapshot["heart_rate_bpm"] is not None:
                self.metric_hr.setText(f"{snapshot['heart_rate_bpm']:.0f} bpm")
            if snapshot["rr_ms"] is not None:
                self.metric_rr.setText(f"{snapshot['rr_ms']:.0f} ms")
            self.metric_count.setText(str(snapshot["rr_count"]))
            elapsed = int(time.monotonic() - self.record_started)
            hours, remainder = divmod(elapsed, 3600)
            minutes, seconds = divmod(remainder, 60)
            self.metric_duration.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
            if snapshot["error"]:
                self.status.setText(f"FEHLER beim Schreiben: {snapshot['error']}")

    def closeEvent(self, event: object) -> None:
        if self.recorder:
            answer = QMessageBox.question(self, "Aufzeichnung läuft", "Aufzeichnung speichern und beenden?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._stop_recording()
        if self.ble_worker:
            self.ble_worker.stop()
            self.ble_worker.join(timeout=3)
        event.accept()


def main() -> int:
    from .logging_config import configure_logging
    configure_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("HRV Recorder")
    window = MainWindow()
    window.show()
    return app.exec()

