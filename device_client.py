"""UTF-8 JSON 한 줄을 보내고 한 줄을 받는다. 요청 하나마다 연결 하나."""
import asyncio
import contextlib
import json
import socket
import time

HOST = "127.0.0.1"
PORT_A, PORT_B = 9101, 9102


def _encode(command):
    if not isinstance(command, str):
        raise ValueError("command는 문자열")
    return (json.dumps({"command": command}) + "\n").encode("utf-8")


def _decode(line):
    if not line or not line.endswith(b"\n"):
        raise ConnectionError("응답 한 줄을 받기 전에 연결 종료")
    try:
        reply = json.loads(line.decode("utf-8"))
    except (ValueError, UnicodeError) as error:
        raise ValueError("JSON 응답 형식 오류") from error
    if not isinstance(reply, dict) or not isinstance(reply.get("ok"), bool):
        raise ValueError("응답에 ok 불리언 필요")
    if not reply["ok"]:
        raise ValueError(reply.get("error", "장치가 요청 거부"))
    return reply


def request_sync(port, command, timeout=1.0):
    """답이 올 때까지 호출한 흐름을 멈춘다."""
    try:
        with socket.create_connection((HOST, port), timeout=timeout) as conn:
            conn.settimeout(timeout)
            conn.sendall(_encode(command))
            with conn.makefile("rb") as reader:
                line = reader.readline(4097)
            if len(line) > 4096:
                raise ValueError("응답 길이 초과")
            return _decode(line)
    except socket.timeout as error:
        raise TimeoutError(f"{port}: {timeout:g}초 안에 응답 없음") from error
    except OSError as error:
        raise ConnectionError(f"{port}: 연결 실패 또는 종료") from error


async def request_async(port, command, timeout=1.0):
    """답을 기다리는 동안 event loop에 실행 기회를 돌려준다."""
    async def exchange():
        reader, writer = await asyncio.open_connection(HOST, port, limit=4096)
        try:
            writer.write(_encode(command))
            await writer.drain()
            return _decode(await reader.readline())
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
    try:
        return await asyncio.wait_for(exchange(), timeout=timeout)
    except asyncio.TimeoutError as error:
        raise TimeoutError(f"{port}: {timeout:g}초 안에 응답 없음") from error
    except OSError as error:
        raise ConnectionError(f"{port}: 연결 실패 또는 종료") from error


def wait_output_sync(port, target=1, limit=8.0, interval=0.1):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        reply = request_sync(port, "status", timeout=min(1.0, max(0.01, deadline-time.monotonic())))
        if reply["output"] == target and not reply["busy"]:
            return reply
        time.sleep(interval)
    raise TimeoutError(f"{port}: {limit:g}초 안에 목표 출력 미확인")


async def wait_output_async(port, target=1, limit=8.0, interval=0.1):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        reply = await request_async(port, "status", timeout=min(1.0, max(0.01, deadline-time.monotonic())))
        if reply["output"] == target and not reply["busy"]:
            return reply
        await asyncio.sleep(interval)
    raise TimeoutError(f"{port}: {limit:g}초 안에 목표 출력 미확인")
