"""PLC 프로그램 테스트. 실제 COM 포트를 열지 않고 가짜 클라이언트와 가짜 키를 쓴다."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
import sys
import time
import unittest

from pymodbus.exceptions import ModbusIOException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "plc"))

import plc_common
import plc_project
import plc_project_sync
from plc_common import KeyReader, State, parse_args, parse_command

SERIAL = ["--port", "COM9", "--bytesize", "8", "--parity", "N", "--stopbits", "1"]


class Rec:
    def __init__(self):
        self.events = []

    def __call__(self, kind, **fields):
        event = {"elapsed": len(self.events), "type": kind, **fields}
        self.events.append(event)
        return event

    def of(self, kind):
        return [e for e in self.events if e["type"] == kind]

    def kinds(self):
        return [e["type"] for e in self.events]


class ArgsTests(unittest.TestCase):
    def test_args_require_serial_format(self):
        with self.assertRaises(SystemExit):
            parse_args(["--port", "COM9", "--bytesize", "8", "--stopbits", "1"])

    def test_args_defaults(self):
        args = parse_args(SERIAL)
        self.assertEqual((args.baudrate, args.unit, args.timeout, args.retries, args.period),
                         (9600, 1, 2.0, 0, 1.0))
        self.assertEqual(plc_common.client_options(args), {
            "port": "COM9", "baudrate": 9600, "bytesize": 8, "parity": "N",
            "stopbits": 1, "timeout": 2.0, "retries": 0})


class CommandTests(unittest.TestCase):
    def test_parse_write_bounds(self):
        self.assertEqual(parse_command("write 0"), ("write", 0))
        self.assertEqual(parse_command("write 65535"), ("write", 65535))
        for text in ("write -1", "write 65536", "write abc", "write"):
            self.assertEqual(parse_command(text)[0], "reject", text)

    def test_parse_unit_bounds(self):
        self.assertEqual(parse_command("unit 1"), ("unit", 1))
        self.assertEqual(parse_command("unit 247"), ("unit", 247))
        for text in ("unit 0", "unit 248"):
            self.assertEqual(parse_command(text)[0], "reject", text)

    def test_parse_simple_commands(self):
        self.assertEqual(parse_command(" status "), ("status",))
        self.assertEqual(parse_command("quit"), ("quit",))
        self.assertEqual(parse_command("hello")[0], "reject")


class StateTests(unittest.TestCase):
    def setUp(self):
        self.state = State(1)
        self.rec = Rec()

    def test_never_read_shows_unobserved(self):
        self.state.read_failed("ModbusIOException", 1, self.rec)
        self.assertIsNone(self.state.value)
        self.assertIn("미관측", self.state.summary())

    def test_failure_keeps_last_good(self):
        self.state.read_ok(100, 1, self.rec)
        seen = self.state.observed_at
        self.state.read_failed("ModbusIOException", 1, self.rec)
        self.assertEqual((self.state.value, self.state.observed_at), (100, seen))
        self.assertEqual(self.state.error, "ModbusIOException")
        self.assertIn("ModbusIOException", self.state.summary())
        self.assertIn("100", self.state.summary())

    def test_success_clears_error(self):
        self.state.read_failed("ModbusIOException", 1, self.rec)
        self.state.read_ok(5, 1, self.rec)
        self.assertIsNone(self.state.error)

    def test_write_confirmed_once(self):
        self.state.write_done(100, 1, True, None, self.rec)
        self.state.read_ok(100, 1, self.rec)
        self.state.read_ok(100, 1, self.rec)
        self.assertEqual(len(self.rec.of("write_confirmed")), 1)

    def test_write_mismatch(self):
        self.state.write_done(100, 1, True, None, self.rec)
        self.state.read_ok(50, 1, self.rec)
        self.assertEqual(self.rec.of("write_mismatch")[0]["observed"], 50)
        self.assertFalse(self.rec.of("write_confirmed"))

    def test_failed_write_is_not_confirmed(self):
        self.state.write_done(100, 1, False, "ModbusIOException", self.rec)
        self.state.read_ok(100, 1, self.rec)
        self.assertFalse(self.rec.of("write_confirmed"))
        self.assertFalse(self.rec.of("write_mismatch"))
        self.assertFalse(self.rec.of("write_result")[0]["ok"])

    def test_handle_line_events(self):
        self.assertFalse(self.state.handle_line("write 100", self.rec))
        self.assertEqual(self.rec.kinds(), ["input_received", "request_accepted"])
        self.assertEqual(list(self.state.pending), [100])
        self.state.handle_line("unit 2", self.rec)
        self.assertEqual(self.state.unit, 2)
        self.assertTrue(self.rec.of("unit_changed"))
        self.state.handle_line("write x", self.rec)
        self.assertTrue(self.rec.of("input_rejected"))
        self.assertTrue(self.state.handle_line("quit", self.rec))


class FakeKeys:
    def __init__(self, keys=""):
        self.keys = list(keys)

    def kbhit(self):
        return bool(self.keys)

    def getwch(self):
        return self.keys.pop(0)


class KeyReaderTests(unittest.TestCase):
    def test_key_reader_lines(self):
        reader = KeyReader(FakeKeys("w\bu\r"))
        self.assertEqual(reader.poll(), ["u"])

    def test_partial_line_waits(self):
        source = FakeKeys("wr")
        reader = KeyReader(source)
        self.assertEqual(reader.poll(), [])
        source.keys.extend("ite 1\r")
        self.assertEqual(reader.poll(), ["write 1"])


class Reply:
    def __init__(self, registers=None, error=False, exception_code=None):
        self.registers, self.error, self.exception_code = registers, error, exception_code

    def isError(self):
        return self.error


class FakeBase:
    """연결된 국번만 응답하는 가짜 PLC. 실패 방식은 예외 또는 오류 응답이다."""
    def __init__(self, delay=0.0, alive=(1,), error_reply=False, can_connect=True):
        self.delay, self.alive, self.error_reply = delay, set(alive), error_reply
        self.can_connect = can_connect
        self.connected = can_connect
        self.closed = False
        self.word = 0
        self.calls = []
        self.active = self.max_active = 0

    def enter(self, call):
        self.calls.append(call)
        self.active += 1
        self.max_active = max(self.max_active, self.active)

    def answer(self, call):
        self.active -= 1
        unit = call[-1]
        if unit not in self.alive:
            if self.error_reply:
                return Reply(error=True, exception_code=2)
            raise ModbusIOException("응답 없음")
        if call[0] == "write":
            self.word = call[2]
            return Reply()
        return Reply([self.word])

    def close(self):
        self.closed = True


class FakeAsyncClient(FakeBase):
    async def connect(self):
        self.connected = self.can_connect
        return self.can_connect

    async def read_holding_registers(self, address, *, count, device_id):
        call = ("read", address, count, device_id)
        self.enter(call)
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.active -= 1
            raise
        return self.answer(call)

    async def write_register(self, address, value, *, device_id):
        call = ("write", address, value, device_id)
        self.enter(call)
        await asyncio.sleep(self.delay)
        return self.answer(call)


class ScriptKeys:
    """(시작 후 초, 명령) 목록을 시간에 맞춰 내준다. KeyReader의 poll과 같은 형태다."""
    def __init__(self, script):
        self.script = list(script)
        self.started = time.monotonic()

    def poll(self):
        now = time.monotonic() - self.started
        lines = [text for at, text in self.script if at <= now]
        self.script = [item for item in self.script if item[0] > now]
        return lines


def test_args():
    return parse_args(SERIAL + ["--period", "0.1"])


test_args.__test__ = False


def sent(client, kind):
    return [call for call in client.calls if call[0] == kind]


class AsyncMonitorTests(unittest.IsolatedAsyncioTestCase):
    async def drive(self, client, script):
        rec = Rec()
        await asyncio.wait_for(
            plc_project.run(client, test_args(), rec, ScriptKeys(script)), 8)
        return rec

    async def test_reads_periodically(self):
        client = FakeAsyncClient()
        rec = await self.drive(client, [(0.35, "quit")])
        self.assertEqual(sent(client, "read")[0], ("read", 0, 1, 1))
        self.assertGreaterEqual(len(rec.of("observation")), 3)
        self.assertEqual(rec.of("observation")[0]["value"], 0)

    async def test_write_before_next_read_then_confirm(self):
        client = FakeAsyncClient()
        rec = await self.drive(client, [(0.05, "write 100"), (0.35, "quit")])
        self.assertEqual(sent(client, "write"), [("write", 0, 100, 1)])
        kinds = rec.kinds()
        self.assertLess(kinds.index("write_sent"), kinds.index("write_result"))
        self.assertEqual(kinds[kinds.index("write_result") + 1], "read_sent")
        self.assertEqual(rec.of("write_confirmed")[0]["value"], 100)

    async def test_writes_in_order(self):
        client = FakeAsyncClient(delay=0.02)
        await self.drive(client, [(0.05, "write 100"), (0.05, "write 200"),
                                  (0.05, "write 300"), (0.4, "quit")])
        self.assertEqual([c[2] for c in sent(client, "write")], [100, 200, 300])

    async def test_input_during_wait(self):
        client = FakeAsyncClient(delay=0.7, alive=())
        rec = await self.drive(client, [(0.1, "status"), (1.0, "quit")])
        kinds = rec.kinds()
        self.assertLess(kinds.index("input_received"), kinds.index("observation_error"))
        self.assertLess(kinds.index("waiting"), kinds.index("observation_error"))

    async def test_one_request_at_a_time(self):
        client = FakeAsyncClient(delay=0.2)
        await self.drive(client, [(0.05, "write 1"), (0.06, "write 2"), (0.8, "quit")])
        self.assertEqual(client.max_active, 1)

    async def test_failed_write_not_resent(self):
        client = FakeAsyncClient(alive=())
        rec = await self.drive(client, [(0.05, "write 100"), (0.4, "quit")])
        self.assertEqual(len(sent(client, "write")), 1)
        self.assertFalse(rec.of("write_result")[0]["ok"])

    async def test_unit_change_applies_next_request(self):
        client = FakeAsyncClient()
        rec = await self.drive(client, [(0.15, "unit 2"), (0.4, "unit 1"), (0.7, "quit")])
        self.assertIn(("read", 0, 1, 2), client.calls)
        self.assertTrue(rec.of("observation_error"))
        self.assertGreater(rec.kinds()[::-1].index("observation_error"),
                           rec.kinds()[::-1].index("observation"))

    async def test_error_response_is_failure(self):
        client = FakeAsyncClient(alive=(), error_reply=True)
        rec = await self.drive(client, [(0.05, "write 1"), (0.3, "quit")])
        self.assertTrue(rec.of("observation_error"))
        self.assertFalse(rec.of("observation"))
        self.assertFalse(rec.of("write_result")[0]["ok"])

    async def test_quit_during_wait_closes(self):
        client = FakeAsyncClient(delay=5)
        started = time.monotonic()
        await self.drive(client, [(0.1, "quit")])
        self.assertLess(time.monotonic() - started, 1)
        self.assertTrue(client.closed)

    async def test_reconnect_failure_keeps_running(self):
        client = FakeAsyncClient(can_connect=False)
        rec = await self.drive(client, [(0.35, "quit")])
        self.assertEqual(rec.of("observation_error")[0]["error"], "ConnectionException")
        self.assertGreaterEqual(len(rec.of("observation_error")), 2)
        self.assertFalse(client.calls)


class FakeSyncClient(FakeBase):
    def connect(self):
        self.connected = self.can_connect
        return self.can_connect

    def read_holding_registers(self, address, *, count, device_id):
        call = ("read", address, count, device_id)
        self.enter(call)
        time.sleep(self.delay)
        return self.answer(call)

    def write_register(self, address, value, *, device_id):
        call = ("write", address, value, device_id)
        self.enter(call)
        time.sleep(self.delay)
        return self.answer(call)


class FixTests(unittest.IsolatedAsyncioTestCase):
    """최종 리뷰에서 나온 결함의 재현 테스트."""
    def test_args_reject_bad_unit(self):
        for unit in ("0", "248"):
            with self.assertRaises(SystemExit):
                parse_args(SERIAL + ["--unit", unit])

    async def test_result_keeps_request_unit(self):
        client = FakeAsyncClient(delay=0.3, alive=())
        rec = Rec()
        await plc_project.run(client, test_args(), rec,
                              ScriptKeys([(0.1, "unit 2"), (0.35, "quit")]))
        self.assertEqual(rec.of("observation_error")[0]["unit"], 1)

    async def test_timeout_and_error_reply_differ(self):
        rec = Rec()
        await plc_project.run(FakeAsyncClient(alive=()), test_args(), rec,
                              ScriptKeys([(0.05, "quit")]))
        self.assertEqual(rec.of("observation_error")[0]["error"], "NoResponse")
        rec = Rec()
        await plc_project.run(FakeAsyncClient(alive=(), error_reply=True), test_args(), rec,
                              ScriptKeys([(0.05, "quit")]))
        self.assertEqual(rec.of("observation_error")[0]["error"], "ErrorReply(2)")

    async def test_dead_poll_task_reconnects(self):
        class Dead(FakeAsyncClient):
            opens = 0

            async def connect(self):
                self.opens += 1
                self.ctx.transport.poll_task = SimpleNamespace(done=lambda: False)
                return await super().connect()

            def close(self):
                self.connected = False

        client = Dead()
        client.ctx = SimpleNamespace(transport=SimpleNamespace(
            poll_task=SimpleNamespace(done=lambda: True)))
        rec = Rec()
        await plc_project.run(client, test_args(), rec, ScriptKeys([(0.25, "quit")]))
        self.assertEqual(client.opens, 1)
        self.assertTrue(rec.of("observation"))


class SyncMonitorTests(unittest.TestCase):
    def drive(self, client, script):
        rec = Rec()
        plc_project_sync.run(client, test_args(), rec, ScriptKeys(script))
        return rec

    def test_sync_reads_and_writes(self):
        client = FakeSyncClient()
        rec = self.drive(client, [(0.15, "write 100"), (0.5, "quit")])
        self.assertEqual(sent(client, "read")[0], ("read", 0, 1, 1))
        self.assertEqual(sent(client, "write"), [("write", 0, 100, 1)])
        self.assertEqual(rec.of("write_confirmed")[0]["value"], 100)
        self.assertTrue(client.closed)

    def test_sync_writes_in_order(self):
        client = FakeSyncClient()
        self.drive(client, [(0.05, "write 100"), (0.05, "write 200"),
                            (0.05, "write 300"), (0.5, "quit")])
        self.assertEqual([c[2] for c in sent(client, "write")], [100, 200, 300])

    def test_sync_input_waits_for_response(self):
        client = FakeSyncClient(delay=0.3, alive=())
        rec = self.drive(client, [(0.1, "status"), (0.8, "quit")])
        kinds = rec.kinds()
        self.assertLess(kinds.index("observation_error"), kinds.index("input_received"))
        self.assertFalse(rec.of("waiting"))

    def test_sync_failed_write_not_resent(self):
        client = FakeSyncClient(alive=())
        rec = self.drive(client, [(0.05, "write 100"), (0.4, "quit")])
        self.assertEqual(len(sent(client, "write")), 1)
        self.assertFalse(rec.of("write_result")[0]["ok"])

    def test_sync_unit_change_and_restore(self):
        client = FakeSyncClient()
        rec = self.drive(client, [(0.15, "unit 2"), (0.4, "unit 1"), (0.7, "quit")])
        self.assertIn(("read", 0, 1, 2), client.calls)
        self.assertGreater(rec.kinds()[::-1].index("observation_error"),
                           rec.kinds()[::-1].index("observation"))

    def test_error_response_is_failure(self):
        client = FakeSyncClient(alive=(), error_reply=True)
        rec = self.drive(client, [(0.05, "write 1"), (0.3, "quit")])
        self.assertTrue(rec.of("observation_error"))
        self.assertFalse(rec.of("observation"))
        self.assertFalse(rec.of("write_result")[0]["ok"])

    def test_reconnect_failure_keeps_running(self):
        client = FakeSyncClient(can_connect=False)
        rec = self.drive(client, [(0.35, "quit")])
        self.assertEqual(rec.of("observation_error")[0]["error"], "ConnectionException")
        self.assertFalse(client.calls)

    def test_sync_has_no_concurrency_import(self):
        source = Path(plc_project_sync.__file__).read_text(encoding="utf-8")
        for name in ("threading", "multiprocessing", "subprocess", "asyncio"):
            self.assertNotIn(name, source)


if __name__ == "__main__":
    unittest.main()
