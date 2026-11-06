"""PLC D01000 비동기 감시와 값 변경. 응답 대기 중에도 입력과 표시를 처리한다."""
import asyncio
import sys
import time

from pymodbus.client import AsyncModbusSerialClient
from pymodbus.exceptions import ConnectionException, ModbusException

from plc_common import (ADDRESS, HELP, EventLog, KeyReader, State, check_reply, client_options, describe,
                        open_log, parse_args)

FAILURES = (ModbusException, OSError, asyncio.TimeoutError)
KEY_INTERVAL = 0.05
WAIT_NOTICE = 0.5


def poll_stopped(client):
    """pymodbus 3.16.1 내부 확인. Windows에서 포트가 끊기면 poll Task만 끝나고 connected는 True로 남는다."""
    transport = getattr(getattr(client, "ctx", None), "transport", None)
    task = getattr(transport, "poll_task", None)
    return task is not None and task.done()


async def exchange(client, request, busy):
    """요청 하나를 수행한다. 이 함수를 부르는 곳은 통신 Task 하나뿐이다."""
    if poll_stopped(client):
        client.close()
    if not client.connected and not await client.connect():
        raise ConnectionException("연결 실패")
    busy["since"] = time.monotonic()
    try:
        reply = await request()
    finally:
        busy["since"] = None
    return check_reply(reply)


async def write_once(client, state, value, record, busy):
    unit = state.unit
    record("write_sent", value=value, unit=unit)
    try:
        await exchange(client, lambda: client.write_register(ADDRESS, value, device_id=unit), busy)
    except FAILURES as error:
        state.write_done(value, unit, False, describe(error), record)
    else:
        state.write_done(value, unit, True, None, record)


async def read_once(client, state, record, busy):
    unit = state.unit
    record("read_sent", unit=unit)
    try:
        reply = await exchange(
            client, lambda: client.read_holding_registers(ADDRESS, count=1, device_id=unit), busy)
    except FAILURES as error:
        state.read_failed(describe(error), unit, record)
    else:
        state.read_ok(reply.registers[0], unit, record)


async def communicate(client, state, period, record, busy):
    next_read = 0.0
    while True:
        if state.pending:
            await write_once(client, state, state.pending.popleft(), record, busy)
        elif time.monotonic() >= next_read:
            next_read = time.monotonic() + period
            await read_once(client, state, record, busy)
        else:
            await asyncio.sleep(0.02)


async def read_keys(keys, state, record):
    while True:
        for line in keys.poll():
            if state.handle_line(line, record):
                return
        await asyncio.sleep(KEY_INTERVAL)


async def show_waiting(busy, record):
    while True:
        await asyncio.sleep(WAIT_NOTICE)
        if busy["since"] is not None:
            record("waiting", seconds=round(time.monotonic() - busy["since"], 1))


async def run(client, args, record, keys):
    state = State(args.unit)
    busy = {"since": None}
    workers = [asyncio.create_task(communicate(client, state, args.period, record, busy)),
               asyncio.create_task(show_waiting(busy, record))]
    inputs = asyncio.create_task(read_keys(keys, state, record))
    tasks = [inputs, *workers]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        client.close()


async def start(args, record):
    client = AsyncModbusSerialClient(**client_options(args))
    if not await client.connect():
        print(f"{args.port}를 열 수 없습니다. COM 번호와 다른 프로그램의 사용 여부를 확인하세요.")
        return 1
    await run(client, args, record, KeyReader())
    return 0


def main():
    args = parse_args()
    output, path = open_log("plc-async")
    print("로그 파일:", path)
    print(HELP)
    code = 0
    with output:
        record = EventLog(output)
        record("run_start", mode="async", **vars(args))
        reason = "quit"
        try:
            code = asyncio.run(start(args, record))
            reason = "quit" if code == 0 else "open_failed"
        except KeyboardInterrupt:
            reason = "interrupted"
        finally:
            record("run_end", reason=reason)
    sys.exit(code)


if __name__ == "__main__":
    main()
