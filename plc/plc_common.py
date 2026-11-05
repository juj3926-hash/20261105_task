"""두 PLC 프로그램의 공통 로직. 통신과 대기를 하지 않는다."""
import argparse
from collections import deque
from datetime import datetime
import json
from pathlib import Path
import time
from uuid import uuid4

LOG_FOLDER = Path(__file__).resolve().parent / "logs"
ADDRESS = 0  # D01000 기준 요청 주소. 1000이나 40001이 아니다.
HELP = "명령: write <0~65535>, unit <1~247>, status, quit"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="PLC D01000 감시와 값 변경")
    parser.add_argument("--port", required=True, help="COM 번호. 예: COM3")
    parser.add_argument("--bytesize", required=True, type=int, choices=(7, 8))
    parser.add_argument("--parity", required=True, choices=("N", "E", "O"))
    parser.add_argument("--stopbits", required=True, type=int, choices=(1, 2))
    parser.add_argument("--baudrate", type=int, default=9600)
    parser.add_argument("--unit", type=int, default=1, help="요청 대상 국번")
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--period", type=float, default=1.0, help="감시 주기(초)")
    return parser.parse_args(argv)


def client_options(args):
    return {"port": args.port, "baudrate": args.baudrate, "bytesize": args.bytesize,
            "parity": args.parity, "stopbits": args.stopbits,
            "timeout": args.timeout, "retries": args.retries}


def _integer(text, low, high):
    try:
        value = int(text)
    except ValueError:
        return None
    return value if low <= value <= high else None


def parse_command(text):
    words = text.split()
    if words == ["status"]:
        return ("status",)
    if words == ["quit"]:
        return ("quit",)
    if len(words) == 2 and words[0] == "write":
        value = _integer(words[1], 0, 65535)
        return ("write", value) if value is not None else ("reject", "값은 0~65535 정수")
    if len(words) == 2 and words[0] == "unit":
        unit = _integer(words[1], 1, 247)
        return ("unit", unit) if unit is not None else ("reject", "국번은 1~247 정수")
    return ("reject", HELP)


def describe(error):
    return type(error).__name__


class State:
    """마지막 정상 관측과 현재 오류를 구분해 보관한다."""
    def __init__(self, unit):
        self.unit = unit
        self.value = None
        self.observed_at = None
        self.error = None
        self.pending = deque()
        self.expected = None

    def handle_line(self, text, record):
        """명령 한 줄을 처리한다. quit이면 True를 반환한다."""
        record("input_received", text=text)
        command = parse_command(text)
        if command[0] == "write":
            self.pending.append(command[1])
            record("request_accepted", value=command[1], pending=len(self.pending))
        elif command[0] == "unit":
            self.unit = command[1]
            record("unit_changed", unit=self.unit)
        elif command[0] == "status":
            record("status", summary=self.summary())
        elif command[0] == "reject":
            record("input_rejected", text=text, reason=command[1])
        return command[0] == "quit"

    def read_ok(self, value, record):
        event = record("observation", value=value, unit=self.unit)
        self.value, self.observed_at, self.error = value, event["elapsed"], None
        if self.expected is not None:
            if value == self.expected:
                record("write_confirmed", value=value)
            else:
                record("write_mismatch", value=self.expected, observed=value)
            self.expected = None

    def read_failed(self, error, record):
        self.error = error
        record("observation_error", unit=self.unit, error=error)

    def write_done(self, value, ok, error, record):
        record("write_result", value=value, unit=self.unit, ok=ok, error=error)
        if ok:
            self.expected = value

    def summary(self):
        seen = "미관측" if self.value is None else f"값 {self.value} (관측 {self.observed_at}초)"
        return f"{seen}, 현재 오류 {self.error or '없음'}, 국번 {self.unit}, 대기 요청 {len(self.pending)}"


class EventLog:
    def __init__(self, output, echo=True):
        self.output, self.echo = output, echo
        self.started = time.monotonic()

    def __call__(self, kind, **fields):
        event = {"wall": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                 "elapsed": round(time.monotonic() - self.started, 3), "type": kind, **fields}
        line = json.dumps(event, ensure_ascii=False)
        self.output.write(line + "\n")
        self.output.flush()
        if self.echo:
            print(line, flush=True)
        return event


class KeyReader:
    """키를 모아 Enter로 끝난 줄을 돌려준다. 키를 기다리지 않는다."""
    def __init__(self, source=None):
        if source is None:
            import msvcrt as source
        self.source = source
        self.buffer = ""

    def poll(self):
        lines = []
        while self.source.kbhit():
            key = self.source.getwch()
            if key in ("\r", "\n"):
                lines.append(self.buffer)
                self.buffer = ""
            elif key == "\b":
                self.buffer = self.buffer[:-1]
            elif key in ("\x00", "\xe0"):
                self.source.getwch()  # 방향키 같은 특수 키의 두 번째 값을 버린다.
            elif key == "\x03":
                raise KeyboardInterrupt
            else:
                self.buffer += key
        return lines


def open_log(prefix):
    LOG_FOLDER.mkdir(exist_ok=True)
    name = prefix + "-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8] + ".jsonl"
    path = LOG_FOLDER / name
    return path.open("x", encoding="utf-8"), path
