import queue
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch

from hrv_recorder.ble import BleConnection, Sensor


class ReconnectTests(unittest.TestCase):
    def test_disconnect_triggers_reconnect_without_stopping_session_callback(self):
        attempts = []
        frames = []

        class FakeClient:
            def __init__(self, address, disconnected_callback, timeout):
                self.address = address
                self.disconnected_callback = disconnected_callback
                self.is_connected = False
                attempts.append(address)

            async def __aenter__(self):
                self.is_connected = True
                return self

            async def __aexit__(self, *_args):
                self.is_connected = False

        class FakeHeartRate:
            def __init__(self, client, callback, instant_rate, unpack):
                self.client = client
                self.callback = callback
                self.asserted_options = (instant_rate, unpack)

            async def start_notify(self):
                self.callback(("HR", time.time_ns(), (70, [850, 860]), None))

                def disconnect():
                    self.client.is_connected = False
                    self.client.disconnected_callback(self.client)

                threading.Timer(0.025, disconnect).start()

            async def stop_notify(self):
                return None

        bleak_module = types.ModuleType("bleak")
        bleak_module.BleakClient = FakeClient
        heart_module = types.ModuleType("bleakheart")
        heart_module.HeartRate = FakeHeartRate

        class FakeRecorder:
            def submit_notification(self, data):
                frames.append(data)

        events = queue.SimpleQueue()
        worker = BleConnection(Sensor("Polar H7", "AA:BB"), lambda: FakeRecorder(), events,
                               retry_initial_seconds=0.02)
        with patch.dict(sys.modules, {"bleak": bleak_module, "bleakheart": heart_module}):
            worker.start()
            time.sleep(0.55)
            worker.stop()
            worker.join(timeout=1)

        self.assertFalse(worker.is_alive())
        self.assertGreaterEqual(len(attempts), 2)
        self.assertTrue(frames)
        self.assertTrue(all(frame[0] == "HR" for frame in frames))


if __name__ == "__main__":
    unittest.main()
