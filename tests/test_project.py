"""project.py 학생 함수 테스트. 교보재와 충돌하지 않도록 빈 포트에 짧은 지연 장치를 띄운다."""
import asyncio
import socket
import time
import unittest
from unittest import mock

import project
from device_server import DeviceServers


# Windows는 닫힌 포트의 연결 거부에 약 2초가 걸려 0.5초 제한이 먼저 끝날 수 있다.
CLOSED_PORT_ERRORS = ("ConnectionError", "TimeoutError")


def make_devices():
    return DeviceServers(ports=(0, 0), delays=(0.2, 0.4))


def closed_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Recorder:
    def __init__(self):
        self.events = []
        self.started = time.monotonic()

    def __call__(self, kind, device=None, **fields):
        event = {"elapsed": round(time.monotonic() - self.started, 4),
                 "type": kind, "device": device, **fields}
        self.events.append(event)
        return event

    def of(self, kind, device=None):
        return [e for e in self.events
                if e["type"] == kind and (device is None or e["device"] == device)]


async def wait_until(condition, limit=5.0):
    deadline = time.monotonic() + limit
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("조건 대기 시간 초과")
        await asyncio.sleep(0.01)


class DeviceCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.servers = make_devices()
        self.addCleanup(self.servers.close)
        self.a, self.b = self.servers.devices
        self.port_a, self.port_b = self.servers.ports
        self.rec = Recorder()


class WatchTests(DeviceCase):
    def setUp(self):
        super().setUp()
        self.item = {"last_output": None, "last_ok": None, "error": None}

    def start(self, port=None):
        task = asyncio.create_task(
            project.watch("A", port or self.port_a, self.item, self.rec))
        self.addCleanup(task.cancel)
        return task

    async def test_success_updates_item(self):
        self.start()
        await wait_until(lambda: self.rec.of("observation"))
        await asyncio.sleep(0)
        self.assertEqual(self.item["last_output"], 0)
        self.assertEqual(self.item["last_ok"], self.rec.of("observation")[-1]["elapsed"])
        self.assertIsNone(self.item["error"])

    async def test_failure_keeps_last_good(self):
        self.start()
        await wait_until(lambda: self.item["last_ok"] is not None)
        self.a.set_mode("silent")
        await wait_until(lambda: self.item["error"] is not None)
        self.assertEqual(self.item["error"], "TimeoutError")
        self.assertEqual(self.item["last_output"], 0)
        self.assertEqual(self.item["last_ok"], self.rec.of("observation")[-1]["elapsed"])
        self.assertTrue(self.rec.of("observation_error", "A"))

    async def test_recovery_clears_error(self):
        self.a.set_mode("silent")
        self.start()
        await wait_until(lambda: self.item["error"] is not None)
        self.assertIsNone(self.item["last_ok"])
        self.a.set_mode("normal")
        await wait_until(lambda: self.item["error"] is None)
        self.assertIsNotNone(self.item["last_ok"])

    async def test_closed_port_keeps_none(self):
        self.start(closed_port())
        await wait_until(lambda: self.item["error"] is not None)
        self.assertIn(self.item["error"], CLOSED_PORT_ERRORS)
        self.assertIsNone(self.item["last_output"])
        self.assertIsNone(self.item["last_ok"])

    async def test_cancel_propagates(self):
        task = self.start()
        await wait_until(lambda: self.rec.of("observation"))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


if __name__ == "__main__":
    unittest.main()
