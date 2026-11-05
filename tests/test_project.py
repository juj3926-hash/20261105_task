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


    async def test_cancel_during_request_propagates(self):
        self.a.set_mode("silent")
        task = self.start()
        await asyncio.sleep(0.1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        self.assertFalse(self.rec.of("observation_error"))

    async def test_rejected_status_keeps_watching(self):
        with mock.patch("project.request_async", side_effect=ValueError("거부")):
            task = self.start()
            await wait_until(lambda: len(self.rec.of("observation_error")) >= 2)
        self.assertEqual(self.item["error"], "ValueError")
        self.assertFalse(task.done())


class WorkTests(DeviceCase):
    def kinds(self):
        return [e["type"] for e in self.rec.events]

    async def test_on_records_in_order(self):
        result = await project.work("A", self.port_a, "on", self.rec)
        self.assertEqual(result, {"ok": True, "output": 1})
        self.assertEqual(self.kinds(), ["command_request", "accepted", "completed"])
        self.assertEqual(self.rec.of("completed")[0]["output"], 1)

    async def test_off_targets_zero(self):
        await project.work("A", self.port_a, "on", self.rec)
        result = await project.work("A", self.port_a, "off", self.rec)
        self.assertEqual(result, {"ok": True, "output": 0})

    async def test_silent_fails_without_accept(self):
        self.a.set_mode("silent")
        result = await project.work("A", self.port_a, "on", self.rec)
        self.assertEqual(result, {"ok": False, "error": "TimeoutError"})
        self.assertEqual(self.rec.of("job_error")[0]["command"], "on")
        self.assertFalse(self.rec.of("accepted"))

    async def test_silent_after_accept_fails_job(self):
        task = asyncio.create_task(project.work("B", self.port_b, "on", self.rec))
        await wait_until(lambda: self.rec.of("accepted"))
        self.b.set_mode("silent")
        result = await task
        self.assertFalse(result["ok"])
        self.assertTrue(self.rec.of("job_error"))
        self.assertFalse(self.rec.of("completed"))

    async def test_closed_port_is_failure(self):
        result = await project.work("A", closed_port(), "on", self.rec)
        self.assertFalse(result["ok"])
        self.assertIn(result["error"], CLOSED_PORT_ERRORS)

    async def test_rejected_request_is_failure(self):
        with mock.patch("project.request_async", side_effect=ValueError("거부")):
            result = await project.work("A", self.port_a, "on", self.rec)
        self.assertEqual(result, {"ok": False, "error": "ValueError"})

    async def test_cancel_not_converted(self):
        task = asyncio.create_task(project.work("B", self.port_b, "on", self.rec))
        await wait_until(lambda: self.rec.of("accepted"))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.rec.of("job_error"))


class StageTests(DeviceCase):
    @property
    def ports(self):
        return (self.port_a, self.port_b)

    def index(self, kind, **fields):
        return [i for i, e in enumerate(self.rec.events) if e["type"] == kind
                and all(e.get(k) == v for k, v in fields.items())]

    async def test_stage_starts_both_before_completion(self):
        result = await project.stage("on", self.ports, self.rec)
        self.assertEqual(result, {"command": "on", "ok": True, "results": {
            "A": {"ok": True, "output": 1}, "B": {"ok": True, "output": 1}}})
        self.assertEqual(len(self.index("command_request")), 2)
        self.assertLess(max(self.index("command_request")), min(self.index("completed")))
        event = self.rec.of("stage_result")[0]
        self.assertEqual((event["command"], event["ok"], event["results"]),
                         ("on", True, result["results"]))

    async def test_stage_keeps_other_result(self):
        self.a.set_mode("silent")
        result = await project.stage("on", self.ports, self.rec)
        self.assertFalse(result["ok"])
        self.assertFalse(result["results"]["A"]["ok"])
        self.assertEqual(result["results"]["B"], {"ok": True, "output": 1})

    async def test_sequence_normal(self):
        stages = await project.sequence(self.ports, self.rec)
        self.assertEqual([s["command"] for s in stages], ["on", "off"])
        self.assertTrue(all(s["ok"] for s in stages))
        self.assertLess(max(self.index("completed", command="on")),
                        min(self.index("command_request", command="off")))
        self.assertFalse(self.rec.of("sequence_stopped"))

    async def test_sequence_stops_after_on_failure(self):
        self.a.set_mode("silent")
        stages = await project.sequence(self.ports, self.rec)
        self.assertEqual([s["command"] for s in stages], ["on"])
        self.assertEqual(self.rec.of("sequence_stopped")[0]["reason"], "on stage failed")
        self.assertFalse(self.index("command_request", command="off"))

    async def test_recovery_adds_no_command(self):
        self.a.set_mode("silent")
        task = asyncio.create_task(project.run(self.ports, seconds=2.5, record=self.rec))
        await wait_until(lambda: self.rec.of("stage_result"))
        recovered_at = len(self.rec.events)
        self.a.set_mode("normal")
        result = await task
        after = self.rec.events[recovered_at:]
        self.assertTrue([e for e in after if e["type"] == "observation" and e["device"] == "A"])
        self.assertFalse(result["stages"][0]["results"]["A"]["ok"])
        self.assertEqual(len(self.rec.of("command_request", "A")), 1)
        self.assertFalse([h for h in self.a.history if h[0] == "command"])
        self.assertEqual(result["observed"]["A"]["last_output"], 0)
        self.assertIsNone(result["observed"]["A"]["error"])


if __name__ == "__main__":
    unittest.main()
