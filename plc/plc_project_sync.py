"""PLC D01000 동기 감시와 값 변경. 통신 함수가 반환한 뒤 다음 처리를 진행한다."""
import sys
import time

from pymodbus.client import ModbusSerialClient
from pymodbus.exceptions import ConnectionException, ModbusException, ModbusIOException

from plc_common import (ADDRESS, HELP, EventLog, KeyReader, State, client_options, describe,
                        open_log, parse_args)

FAILURES = (ModbusException, OSError)
LOOP_WAIT = 0.05


def exchange(client, request):
    if not client.connected and not client.connect():
        raise ConnectionException("연결 실패")
    reply = request()
    if reply.isError():
        raise ModbusIOException("오류 응답")
    return reply


def write_once(client, state, value, record):
    unit = state.unit
    record("write_sent", value=value, unit=unit)
    try:
        exchange(client, lambda: client.write_register(ADDRESS, value, device_id=unit))
    except FAILURES as error:
        state.write_done(value, False, describe(error), record)
    else:
        state.write_done(value, True, None, record)


def read_once(client, state, record):
    unit = state.unit
    record("read_sent", unit=unit)
    try:
        reply = exchange(
            client, lambda: client.read_holding_registers(ADDRESS, count=1, device_id=unit))
    except FAILURES as error:
        state.read_failed(describe(error), record)
    else:
        state.read_ok(reply.registers[0], record)


def run(client, args, record, keys):
    """입력 처리 → 쓰기 → 주기 읽기를 한 흐름에서 차례로 수행한다."""
    state = State(args.unit)
    next_read = 0.0
    try:
        while True:
            for line in keys.poll():
                if state.handle_line(line, record):
                    return
            if state.pending:
                write_once(client, state, state.pending.popleft(), record)
            if time.monotonic() >= next_read:
                next_read = time.monotonic() + args.period
                read_once(client, state, record)
            time.sleep(LOOP_WAIT)
    finally:
        client.close()


def main():
    args = parse_args()
    output, path = open_log("plc-sync")
    print("로그 파일:", path)
    print(HELP)
    code = 0
    with output:
        record = EventLog(output)
        record("run_start", mode="sync", **vars(args))
        reason = "quit"
        try:
            client = ModbusSerialClient(**client_options(args))
            if client.connect():
                run(client, args, record, KeyReader())
            else:
                print(f"{args.port}를 열 수 없습니다. COM 번호와 다른 프로그램의 사용 여부를 확인하세요.")
                reason, code = "open_failed", 1
        except KeyboardInterrupt:
            reason = "interrupted"
        finally:
            record("run_end", reason=reason)
    sys.exit(code)


if __name__ == "__main__":
    main()
