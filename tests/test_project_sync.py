"""project_sync.py 테스트. run은 끝나지 않으므로 record가 KeyboardInterrupt로 멈춘다."""
import unittest
from unittest import mock

import project_sync
from tests.test_project import CLOSED_PORT_ERRORS, Recorder, closed_port, make_devices


def new_item():
    return {"last_output": None, "last_ok": None, "error": None}


class SyncCase(unittest.TestCase):
    def setUp(self):
        self.servers = make_devices()
        self.addCleanup(self.servers.close)
        self.a, self.b = self.servers.devices
        self.port_a, self.port_b = self.servers.ports
        self.ports = (self.port_a, self.port_b)
        self.rec = Recorder()


class HelperTests(SyncCase):
    def test_observe_success(self):
        item = new_item()
        project_sync.observe("A", self.port_a, item, self.rec)
        self.assertEqual(item["last_output"], 0)
        self.assertEqual(item["last_ok"], self.rec.of("observation")[0]["elapsed"])
        self.assertIsNone(item["error"])

    def test_observe_failure_keeps_last_good(self):
        item = new_item()
        project_sync.observe("A", self.port_a, item, self.rec)
        last_ok = item["last_ok"]
        self.a.set_mode("silent")
        project_sync.observe("A", self.port_a, item, self.rec)
        self.assertEqual((item["last_output"], item["last_ok"]), (0, last_ok))
        self.assertEqual(item["error"], "TimeoutError")
        self.assertEqual(self.rec.of("observation_error", "A")[0]["error"], "TimeoutError")

    def test_observe_rejected_status(self):
        item = new_item()
        with mock.patch("project_sync.request_sync", side_effect=ValueError("거부")):
            project_sync.observe("A", self.port_a, item, self.rec)
        self.assertEqual(item["error"], "ValueError")

    def test_observe_all_order(self):
        observed = {"A": new_item(), "B": new_item()}
        project_sync.observe_all(self.ports, observed, self.rec)
        self.assertEqual([e["device"] for e in self.rec.of("observation")], ["A", "B"])
        self.assertEqual(observed["B"]["last_output"], 0)

    def test_job_records_in_order(self):
        result = project_sync.job("A", self.port_a, "on", self.rec)
        self.assertEqual(result, {"ok": True, "output": 1})
        self.assertEqual([e["type"] for e in self.rec.events],
                         ["command_request", "accepted", "completed"])

    def test_job_silent_fails(self):
        self.a.set_mode("silent")
        result = project_sync.job("A", self.port_a, "on", self.rec)
        self.assertEqual(result, {"ok": False, "error": "TimeoutError"})
        self.assertTrue(self.rec.of("job_error"))
        self.assertFalse(self.rec.of("accepted"))


class StopRecorder(Recorder):
    """지정 조건이 참이면 기록한 뒤 KeyboardInterrupt를 일으킨다."""
    def __init__(self, stop_when=None, on_event=None, extra=4):
        super().__init__()
        self.stop_when = stop_when or self.watched_after_end
        self.on_event = on_event
        self.extra = extra
        self.end_index = None

    def watched_after_end(self, event, _recorder):
        if event["type"] == "sequence_stopped" or (
                event["type"] == "stage_result" and event["command"] == "off"):
            self.end_index = len(self.events)
        if self.end_index is None:
            return False
        after = self.events[self.end_index:]
        return len([e for e in after if e["type"] == "observation"]) >= self.extra

    def __call__(self, kind, device=None, **fields):
        event = super().__call__(kind, device, **fields)
        if self.on_event:
            self.on_event(event)
        if self.stop_when(event, self):
            raise KeyboardInterrupt
        return event


class RunTests(SyncCase):
    def run_until_stopped(self, ports=None, **options):
        self.rec = StopRecorder(**options)
        with self.assertRaises(KeyboardInterrupt):
            project_sync.run(ports or self.ports, self.rec)
        return self.rec

    def index(self, kind, **fields):
        return [i for i, e in enumerate(self.rec.events) if e["type"] == kind
                and all(e.get(k) == v for k, v in fields.items())]

    def test_normal_order(self):
        rec = self.run_until_stopped()
        order = [("A", "on"), ("B", "on"), ("A", "off"), ("B", "off")]
        self.assertEqual([(e["device"], e["command"]) for e in rec.of("command_request")], order)
        self.assertEqual([(e["device"], e["command"]) for e in rec.of("completed")], order)
        requests, completed = self.index("command_request"), self.index("completed")
        for done, following in zip(completed, requests[1:]):
            self.assertLess(done, following)

    def test_observes_between_jobs(self):
        rec = self.run_until_stopped()
        completed = self.index("completed")
        starts = [-1, *completed]
        ends = [self.index("command_request")[0], *self.index("command_request")[1:], len(rec.events)]
        for start, end in zip(starts, ends):
            devices = {e["device"] for e in rec.events[start + 1:end]
                       if e["type"] == "observation"}
            self.assertEqual(devices, {"A", "B"})

    def test_a_failure_still_tries_b_on(self):
        self.a.set_mode("silent")
        rec = self.run_until_stopped(extra=1)
        self.assertTrue(rec.of("completed", "B"))
        self.assertFalse(rec.of("stage_result")[0]["ok"])
        self.assertEqual(rec.of("sequence_stopped")[0]["reason"], "on stage failed")
        self.assertFalse(self.index("command_request", command="off"))

    def test_off_failure_still_tries_b_off(self):
        def cut(event):
            if (event["type"], event["device"], event.get("command")) == (
                    "command_request", "A", "off"):
                self.a.set_mode("silent")
        rec = self.run_until_stopped(on_event=cut, extra=1)
        self.assertTrue(self.index("command_request", device="B", command="off"))
        self.assertFalse(rec.of("stage_result")[-1]["ok"])

    def test_monitors_after_sequence(self):
        rec = self.run_until_stopped()
        last = self.index("stage_result")[-1]
        self.assertGreaterEqual(
            len([e for e in rec.events[last:] if e["type"] == "observation"]), 4)

    def test_silent_mid_run_keeps_flow(self):
        def cut(event):
            if event["type"] == "accepted" and event["device"] == "B":
                self.a.set_mode("silent")
        rec = self.run_until_stopped(on_event=cut, extra=1)
        self.assertTrue(rec.of("observation_error", "A"))
        self.assertTrue(self.index("completed", device="B", command="on"))

    def test_closed_port_keeps_running(self):
        rec = self.run_until_stopped((closed_port(), self.port_b), extra=1)
        self.assertIn(rec.of("job_error", "A")[0]["error"], CLOSED_PORT_ERRORS)
        self.assertTrue(rec.of("completed", "B"))
        self.assertFalse(self.index("command_request", command="off"))

    def test_interrupt_during_job_propagates(self):
        rec = self.run_until_stopped(stop_when=lambda e, _r: e["type"] == "accepted")
        self.assertFalse(rec.of("job_error"))
        self.assertFalse(rec.of("stage_result"))

    def test_recovery_adds_no_command(self):
        self.a.set_mode("silent")

        def heal(event):
            if event["type"] == "sequence_stopped":
                self.a.set_mode("normal")
        rec = self.run_until_stopped(on_event=heal)
        stopped = self.index("sequence_stopped")[0]
        self.assertTrue([e for e in rec.events[stopped:]
                         if e["type"] == "observation" and e["device"] == "A"])
        self.assertEqual(len(rec.of("command_request", "A")), 1)
        self.assertFalse([h for h in self.a.history if h[0] == "command"])


if __name__ == "__main__":
    unittest.main()
