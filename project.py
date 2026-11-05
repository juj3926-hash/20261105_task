"""기본 통합 과제: 두 장치 켜기 → 모두 완료되면 끄기. 감시는 계속."""
import asyncio
from device_client import PORT_A, PORT_B, request_async, wait_output_async


# 학생 구현: 아래 watch, work, stage, sequence 네 함수
async def watch(name, port, item, record):
    """반복 조회. 성공 시 마지막 값·시각 갱신, 오류 시 마지막 정상 값 보존."""
    while True:
        try:
            reply = await request_async(port, "status", timeout=0.5)
        except (TimeoutError, ConnectionError, ValueError) as error:
            item["error"] = type(error).__name__
            record("observation_error", name, error=item["error"])
        else:
            event = record("observation", name, output=reply["output"], busy=reply["busy"])
            item.update(last_output=reply["output"], last_ok=event["elapsed"], error=None)
        await asyncio.sleep(0.2)


async def work(name, port, command, record):
    """명령 하나의 요청·접수·완료 확인. 오류도 {ok: False, error: ...}로 반환."""
    target = 1 if command == "on" else 0
    record("command_request", name, command=command)
    try:
        await request_async(port, command, timeout=0.5)
        record("accepted", name, command=command)
        reply = await wait_output_async(port, target=target)
    except (TimeoutError, ConnectionError, ValueError) as error:
        failure = type(error).__name__
        record("job_error", name, command=command, error=failure)
        return {"ok": False, "error": failure}
    record("completed", name, command=command, output=reply["output"])
    return {"ok": True, "output": reply["output"]}


async def stage(command, ports, record):
    """A/B work를 함께 시작하고 둘 다 결과를 낼 때까지 기다린다."""
    # TODO: create_task 또는 gather로 동시 시작.
    # {command, ok, results:{A:결과, B:결과}}를 stage_result에 기록하고 반환.
    raise NotImplementedError("stage: 두 장치의 현재 작업 결과를 모으세요.")


async def sequence(ports, record):
    """on 단계 모두 성공한 경우에만 off 단계. 실패한 작업은 다시 실행하지 않는다."""
    # TODO: on stage 결과를 목록에 보존. 성공할 때만 off stage 결과 추가.
    raise NotImplementedError("sequence: 두 단계 사이의 진행 조건을 작성하세요.")


async def run(ports=(PORT_A, PORT_B), seconds=None, record=None):
    return await run_project(watch, sequence, ports, seconds, record)


# 제공된 실행·로그·종료 틀: 아래 부분은 수정할 필요가 없습니다.
import argparse
from datetime import datetime
import io
import json
from pathlib import Path
import time
from uuid import uuid4


class EventLog:
    def __init__(self, output, echo=True):
        self.output, self.echo = output, echo
        self.started = time.monotonic()

    def __call__(self, kind, device=None, **fields):
        event = {"elapsed": round(time.monotonic()-self.started, 4), "type": kind,
                 "device": device, **fields}
        line = json.dumps(event, ensure_ascii=False, allow_nan=False)
        self.output.write(line + "\n")
        self.output.flush()
        if self.echo:
            print(line)
        return event


async def run_project(watch, sequence, ports, seconds=None, record=None):
    if seconds is not None and (seconds <= 0 or seconds == float("inf") or seconds != seconds):
        raise ValueError("seconds는 양의 유한한 초여야 합니다.")
    if record is None:
        record = EventLog(io.StringIO())
    observed = {name: {"last_output": None, "last_ok": None, "error": None} for name in ("A", "B")}
    record("run_start", ports=list(ports), seconds=seconds)
    monitors = [asyncio.create_task(watch(name, port, observed[name], record))
                for name, port in zip(("A", "B"), ports)]
    job = asyncio.create_task(sequence(ports, record))
    tasks = [job, *monitors]
    try:
        done, _ = await asyncio.wait(tasks, timeout=seconds, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            if not task.cancelled() and task.exception() is not None:
                raise task.exception()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        finished = job.done() and not job.cancelled() and job.exception() is None
        result = {"stages": job.result() if finished else [],
                  "observed": observed, "sequence_finished": finished}
        record("run_end", **result)
    return result


def main(run):
    parser = argparse.ArgumentParser(description="두 장치의 단계 작업과 독립 감시")
    parser.add_argument("--seconds", type=float, help="지정한 초 뒤 종료. 생략하면 Ctrl+C까지 감시")
    args = parser.parse_args()
    folder = Path("logs")
    folder.mkdir(exist_ok=True)
    path = folder / ("project-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8] + ".jsonl")
    print("로그 파일:", path)
    try:
        with path.open("x", encoding="utf-8") as output:
            asyncio.run(run(seconds=args.seconds, record=EventLog(output)))
    except KeyboardInterrupt:
        print("감시를 종료했습니다.")
    except (NotImplementedError, ValueError) as error:
        print("확인할 내용:", error)
        raise SystemExit(1)
    finally:
        print("기록 보존:", path)


if __name__ == "__main__":
    main(run)
