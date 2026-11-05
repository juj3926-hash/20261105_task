"""과제 2: 단일 실행 흐름의 동기 제어와 비동기 결과 비교."""
from datetime import datetime
from pathlib import Path
import time
from uuid import uuid4

from device_client import PORT_A, PORT_B, request_sync, wait_output_sync
from project import EventLog


# 학생 구현: 필요한 동기 함수는 자유롭게 추가합니다.
def observe(name, port, item, record):
    """상태를 한 번 조회한다. 실패해도 마지막 정상 값과 시각은 보존한다."""
    try:
        reply = request_sync(port, "status", timeout=0.5)
    except (TimeoutError, ConnectionError, ValueError) as error:
        item["error"] = type(error).__name__
        record("observation_error", name, error=item["error"])
    else:
        event = record("observation", name, output=reply["output"], busy=reply["busy"])
        item.update(last_output=reply["output"], last_ok=event["elapsed"], error=None)


def observe_all(ports, observed, record):
    for name, port in zip(("A", "B"), ports):
        observe(name, port, observed[name], record)


def job(name, port, command, record):
    """명령 하나의 요청·접수·완료 확인. 오류도 {ok: False, error: ...}로 반환."""
    target = 1 if command == "on" else 0
    record("command_request", name, command=command)
    try:
        request_sync(port, command, timeout=0.5)
        record("accepted", name, command=command)
        reply = wait_output_sync(port, target=target)
    except (TimeoutError, ConnectionError, ValueError) as error:
        failure = type(error).__name__
        record("job_error", name, command=command, error=failure)
        return {"ok": False, "error": failure}
    record("completed", name, command=command, output=reply["output"])
    return {"ok": True, "output": reply["output"]}


def run(ports=(PORT_A, PORT_B), record=None):
    """TASKS.md의 동기 과제를 구현하고 실제 요청·관측·완료 시각을 기록하세요."""
    # TODO: 동기 요청과 완료 대기로 A on → B on → A off → B off를 구성.
    # on 단계 실패 시 off로 진행하지 않음. 통신 실패를 장치별 결과로 구분.
    # 제어 작업 사이의 상태 조회와 작업 종료 후 감시를 구현.
    # 조회할 때만 관측 기록을 남기고, 기다리는 동안의 감시 공백을 비교.
    # asyncio·추가 스레드·프로세스로 제어 작업을 나누지 않습니다.
    raise NotImplementedError("run: 동기 제어와 관측을 구현하세요.")


# 제공된 로그·실행 틀. EventLog는 project.py에서 재사용하며 비동기 제어를 실행하지 않습니다.
def main():
    folder = Path("logs")
    folder.mkdir(exist_ok=True)
    path = folder / ("project-sync-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8] + ".jsonl")
    print("로그 파일:", path)
    try:
        with path.open("x", encoding="utf-8") as output:
            record = EventLog(output)
            record("run_start", ports=[PORT_A, PORT_B], mode="sync")
            reason = "error"
            try:
                run(record=record)
                reason = "returned"
            except KeyboardInterrupt:
                reason = "interrupted"
                print("제어 프로그램을 종료했습니다.")
            except (NotImplementedError, ValueError, TimeoutError, ConnectionError) as error:
                record("run_error", error=type(error).__name__, message=str(error))
                print("확인할 내용:", error)
                raise SystemExit(1)
            finally:
                # 함수 반환·프로그램 종료는 장치 작업의 성공 판정이 아닙니다.
                record("run_end", reason=reason)
    finally:
        print("기록 보존:", path)


if __name__ == "__main__":
    main()
