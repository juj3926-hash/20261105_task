# 구현에 사용할 API

## 실행 환경과 장치

Python 3.10 이상, 표준 라이브러리만 사용한다. `python teacher_demo.py`가 브라우저 교보재(8765)와 가상 장치 A(9101)·B(9102)를 함께 시작한다. 모든 연결은 자기 PC의 `127.0.0.1`이다.

- A의 출력 변경 시간은 약 2초, B는 약 4초다. 이미 목표 출력이면 바로 완료될 수 있다.
- 명령은 `on`, `off`, `status`다. on/off의 접수 응답과 실제 출력 변경은 별개다.
- 완료 조건은 목표 `output`과 `busy == False`를 모두 확인하는 것이다.
- 상태값은 모형의 출력이다. 실제 실린더 위치나 그리퍼가 물체를 잡았다는 뜻이 아니다.
- 이 모형은 TCP로 UTF-8 JSON 한 줄을 주고받는다. 실제 PLC Modbus 프로토콜과 다르다.

```python
from device_client import (
    PORT_A, PORT_B,
    request_async, wait_output_async,
    request_sync, wait_output_sync,
)
```

## 제공 통신 함수

| 함수 | 역할 |
|---|---|
| `await request_async(port, command, timeout=1.0)` | 요청 하나의 응답 대기. 대기 중 다른 준비된 Task에 실행 기회 제공 |
| `await wait_output_async(port, target=1, limit=8.0, interval=0.1)` | 상태를 반복 조회하며 목표 출력과 busy false 확인 |
| `request_sync(port, command, timeout=1.0)` | 같은 요청을 동기 방식으로 수행. 응답까지 호출한 실행 흐름 대기 |
| `wait_output_sync(port, target=1, limit=8.0, interval=0.1)` | 동기 status 조회와 대기를 반복해 실제 완료 확인 |

네 함수 모두 정상 시 응답 딕셔너리를 반환한다. on의 목표는 1, off의 목표는 0이다. on/off 요청의 정상 응답은 다음과 같다.

```python
{"ok": True, "accepted": True}
```

status 및 완료 확인 함수의 정상 응답:

```python
{"ok": True, "output": 0, "busy": False, "target": 0}
```

- `timeout`: 요청 한 번의 응답 제한. 과제의 명령 요청과 감시 조회에는 0.5초를 사용한다.
- `limit`: 목표 출력을 확인하는 전체 대기 제한. 기본 8초를 사용한다. 내부 개별 status 요청의 제한을 넘겨도 더 일찍 실패할 수 있다.
- `interval`: 완료 확인을 위한 반복 조회 사이 대기. 실제 관측 간격은 응답 처리 시간의 영향도 받는다.
- 예상 예외: `TimeoutError`(응답 또는 완료 제한), `ConnectionError`(연결 실패·종료), `ValueError`(요청 거부·잘못된 응답).

일반 동기 함수 앞에 await만 붙여 비동기 호출로 바꾸지 않는다. 각 방식에 맞는 함수를 사용한다. `wait_output_sync`도 완료를 확인하기 위해 status를 반복 요청한다. 단일 흐름의 다른 감시 작업에 실행 기회를 주는 함수는 아니다.

## project.py 학생 구현 함수

| 함수 | 역할과 반환 계약 |
|---|---|
| `async def watch(name, port, item, record)` | status 반복 조회. 성공 시 마지막 값·시각과 오류 해제, 실패 시 마지막 정상 값·시각 보존 및 현재 오류 갱신. 조회 사이 `await asyncio.sleep(0.2)` |
| `async def work(name, port, command, record)` | 요청 → 접수 → 목표 출력·busy 확인. 성공은 `{"ok": True, "output": 값}`, 예상 통신 실패는 `{"ok": False, "error": 오류이름}` |
| `async def stage(command, ports, record)` | A·B work를 함께 시작하고 두 결과 수집. `{"command": 명령, "ok": 둘다성공여부, "results": {"A": 결과, "B": 결과}}` |
| `async def sequence(ports, record)` | on 단계 결과를 보존하고 모두 성공한 때만 off 단계 실행. 단계 결과 목록 반환 |

`item`의 초기 형태:

```python
{"last_output": None, "last_ok": None, "error": None}
```

정상 조회에서 `record("observation", ...)`가 반환한 이벤트의 `elapsed`를 `last_ok`에 저장한다. 실패하면 값과 정상 시각을 지우거나 0·현재 시각으로 바꾸지 않는다. 한 번도 읽지 못했다면 None을 유지한다. 복구되면 현재 관측만 갱신한다.

예상 통신 오류는 해당 장치의 실패 결과로 남긴다. `CancelledError`를 통신 실패와 섞어 삼키지 않는다. 취소는 제공된 실행 틀이 Task를 정리하기 위한 요청이다.

제공 `async run(ports=(9101, 9102), seconds=None, record=None)`은 감시 두 개와 sequence를 함께 실행한다. 작업 순서가 끝나도 감시하며, Ctrl+C 또는 지정 시간이 되면 Task를 정리한다. 반환은 `stages`, `observed`, `sequence_finished`다. `python project.py --seconds 15`도 가능하다. 이 실행·로그 틀은 project.py 안에 포함되어 있다.

## project_sync.py 학생 구현 함수

`def run(ports=(PORT_A, PORT_B), record=None)` 안에 단일 실행 흐름의 동기 제어와 관측을 구현한다. 내부 함수를 나누는 방법은 spec·plan에서 정한다. 동기판에 비동기 함수 계약을 그대로 붙이지 않는다.

정상 작업 순서는 A on 완료 → B on 완료 → A off 완료 → B off 완료다. on 단계의 A 결과가 실패여도 B의 on을 시도해 결과를 수집하며, on 중 하나라도 실패하면 off 단계는 시작하지 않는다. 작업 전후·작업 사이에는 상태를 조회하고, 작업 순서가 끝난 뒤에도 조회를 이어가며 Ctrl+C로 종료한다. 마지막 정상 값·시각과 현재 오류는 구분한다.

제공 실행 틀은 `record`를 전달하고 터미널·JSONL 기록을 보존한다. `project.py`의 EventLog만 재사용하므로 두 파일을 같은 폴더에 둔다. 학생의 동기 제어가 project.py의 비동기 run을 호출하는 것은 아니다. 별도 `--seconds` 종료 기능은 동기판 필수 요구가 아니다.

## 기록 함수

```python
record(type, device=None, **fields) -> dict
```

터미널과 JSONL에 사건을 기록하고 해당 딕셔너리를 반환한다. 공통 필드는 `elapsed`(그 실행 시작부터 경과한 초), `type`, `device`다. 기존 파일을 덮어쓰지 않는 새 로그 경로는 제공 틀이 만든다.

| type | 추가 필드와 기록 시점 |
|---|---|
| `command_request` | command. 장치 명령 요청 직전 |
| `accepted` | command. 접수 응답 수신 |
| `completed` | command, output. 목표 출력과 busy false 확인 |
| `job_error` | command, error. 해당 장치 명령 작업 실패 |
| `observation` | output, busy. 정상 상태 조회 |
| `observation_error` | error. 현재 상태 조회 실패 |
| `stage_result` | command, ok, results. 한 단계의 두 결과 |
| `sequence_stopped` | reason. 실패로 다음 단계 시작하지 않음 |

비동기판의 run_start·run_end는 제공 틀이 기록한다. 동기판도 제공 틀의 시작·종료 기록과 학생의 장치 작업 완료 기록을 구분한다. 프로그램 종료 기록 자체를 장치 작업 성공으로 해석하지 않는다.

## 장애 조작과 화면

- 학생 프로그램을 종료하고 `초기화`를 누르면 장치 출력·통신 모드·교보재 기록이 초기화된다.
- `A 통신 끊기`, `A 통신 복구`는 통신 모드만 바꾼다. 출력 초기화나 새 작업 시작을 하지 않으며, 학생 제어 프로그램 실행 중 장애·복구 시험에 사용한다.
- `단일 장치`, `블로킹 순차`, `비동기 순차`, `Task 동시`, `A 무응답`은 교보재의 완성 시연을 시작한다. 학생 프로그램과 동시에 실행하지 않는다.
- 이 모형의 무응답 모드는 새 요청을 실행하지 않고 응답하지 않는다. 이미 진행 중인 출력 변경은 계속된다. 실제 장치의 timeout이 항상 명령 미실행을 뜻하는 것은 아니다.
- 브라우저의 장치 그림은 모형 내부 상태다. PC 마지막 관측·감시 시간축은 교보재 시연 코드의 기록이며 학생 프로그램의 관측은 학생 터미널·JSONL에 있다.
