"""Polar BLE discovery and resilient BleakHeart connection worker."""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable

LOGGER = logging.getLogger(__name__)
HEART_RATE_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"


@dataclass(frozen=True)
class Sensor:
    name: str
    address: str
    device: object | None = None

    def __str__(self) -> str:
        return f"{self.name}  ·  {self.address}"


async def discover_sensors(timeout: float = 8.0) -> list[Sensor]:
    """Discover devices advertising the standard heart-rate service or Polar name."""
    try:
        from bleak import BleakScanner
    except ImportError as exc:
        raise RuntimeError("Bleak fehlt. Installiere die Abhängigkeiten aus requirements.txt.") from exc
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    devices: list[Sensor] = []
    for device, advertisement in found.values():
        name = device.name or advertisement.local_name or "Unbenanntes BLE-Gerät"
        uuids = {str(value).lower() for value in (advertisement.service_uuids or [])}
        if HEART_RATE_SERVICE_UUID in uuids or "polar" in name.lower() or "h7" in name.lower():
            devices.append(Sensor(name=name, address=device.address, device=device))
    return sorted(devices, key=lambda item: (item.name.lower(), item.address))


class BleConnection(threading.Thread):
    """Run BleakHeart on its own asyncio loop so UI updates cannot block notifications."""

    def __init__(self, sensor: Sensor, recorder_getter: Callable[[], object | None],
                 events: queue.SimpleQueue[tuple[str, object]], *, retry_initial_seconds: float = 1.0) -> None:
        super().__init__(name="polar-ble-connection", daemon=True)
        self.sensor = sensor
        self.recorder_getter = recorder_getter
        self.events = events
        self.retry_initial_seconds = retry_initial_seconds
        self._stop_requested = threading.Event()
        self._rr_received = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    def stop(self) -> None:
        self._stop_requested.set()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(lambda: None)

    def _status(self, message: str) -> None:
        self.events.put(("status", message))

    def _frame(self, data: tuple[object, ...]) -> None:
        try:
            if data[0] == "HR" and data[2][1]:
                self._rr_received.set()
        except (IndexError, TypeError):
            pass
        recorder = self.recorder_getter()
        if recorder is not None:
            recorder.submit_notification(data)
        self.events.put(("frame", data))

    def run(self) -> None:
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._run())
        except Exception as exc:
            LOGGER.exception("BLE-Verbindungsfehler")
            self._status(f"Bluetooth-Fehler: {exc}")
        finally:
            if self._loop is not None:
                self._loop.close()
            self._status("Getrennt")

    async def _run(self) -> None:
        try:
            from bleak import BleakClient
            from bleakheart import HeartRate
        except ImportError as exc:
            self._status("Bleak/BleakHeart fehlt. Bitte requirements.txt installieren.")
            raise RuntimeError("Bluetooth-Abhängigkeit fehlt") from exc

        retry = self.retry_initial_seconds
        while not self._stop_requested.is_set():
            disconnected = asyncio.Event()
            try:
                self._status(f"Verbinde mit {self.sensor.name} …")

                def on_disconnect(_client: object) -> None:
                    disconnected.set()

                async with BleakClient(self.sensor.device or self.sensor.address, disconnected_callback=on_disconnect,
                                       timeout=20.0) as client:
                    if not client.is_connected:
                        raise ConnectionError("Gerät meldet keine aktive Verbindung.")
                    heart_rate = HeartRate(client, callback=self._frame, instant_rate=False, unpack=False)
                    self._rr_received.clear()
                    await heart_rate.start_notify()
                    self._status("Verbunden · Herzfrequenz-Benachrichtigungen aktiv")
                    connected_at = time.monotonic()
                    while not self._stop_requested.is_set() and not disconnected.is_set():
                        if not self._rr_received.is_set() and time.monotonic() - connected_at > 12:
                            self._status("Verbunden, aber noch keine RR-Intervalle empfangen")
                            connected_at = float("inf")
                        await asyncio.sleep(0.2)
                    if client.is_connected:
                        await heart_rate.stop_notify()
                    if time.monotonic() - connected_at >= 30:
                        retry = self.retry_initial_seconds
                if self._stop_requested.is_set():
                    break
                self._status("Verbindung unterbrochen · gespeicherte Daten bleiben erhalten")
            except Exception as exc:
                if self._stop_requested.is_set():
                    break
                self._status(f"Verbindung fehlgeschlagen/unterbrochen: {exc}")
            if not self._stop_requested.is_set():
                self._status(f"Wiederverbindung in {retry} s …")
                deadline = asyncio.get_running_loop().time() + retry
                while asyncio.get_running_loop().time() < deadline:
                    if self._stop_requested.is_set():
                        break
                    await asyncio.sleep(min(0.2, max(0.01, deadline - asyncio.get_running_loop().time())))
                retry = min(retry * 2, 16.0)

