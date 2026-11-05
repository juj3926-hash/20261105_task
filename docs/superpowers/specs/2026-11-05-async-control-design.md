# 과제 1 비동기 제어 설계

- 대상 파일: `project.py`의 학생 구현 영역 (`watch`, `work`, `stage`, `sequence`)
- 범위: 과제 1만 다룬다. 과제 2(`project_sync.py`)와 두 방식의 비교는 이 문서에 포함하지 않는다.

## 1. 목표

가상 장치 A·B를 비동기로 함께 켜고, 두 장치의 실제 완료를 확인한 뒤 함께 끈다. 한쪽 통신이 실패해도 다른 장치의 현재 작업과 상태 감시는 계속된다.

## 2. 자료에 정해진 사실

구현자가 바꿀 수 없는 내용이다. 출처는 `TASKS.md`, `API.md`, 제공 코드다.

### 장치

- A는 포트 9101, 출력 변경 약 2초. B는 포트 9102, 출력 변경 약 4초.
- on/off의 접수 응답과 실제 출력 변경은 별개다.
- 완료 조건은 목표 `output`과 `busy == False`를 모두 확인하는 것이다. on의 목표는 1, off의 목표는 0이다.
- 무응답(`silent`) 모드의 모형은 새 요청을 실행하지 않고 응답하지 않는다. 이미 진행 중인 출력 변경은 계속된다.

### 통신

- `request_async(port, command, timeout)`, `wait_output_async(port, target, limit, interval)`을 사용한다.
- 명령 요청과 감시 조회의 `timeout`은 0.5초, 완료 대기 `limit`은 기본 8초다.
- 예상 예외는 `TimeoutError`, `ConnectionError`, `ValueError`다.

### 함수 계약

| 함수 | 계약 |
|---|---|
| `watch(name, port, item, record)` | status 반복 조회. 조회 사이 `await asyncio.sleep(0.2)` |
| `work(name, port, command, record)` | 성공 `{"ok": True, "output": 값}`, 예상 통신 실패 `{"ok": False, "error": 오류이름}` |
| `stage(command, ports, record)` | `{"command": 명령, "ok": 둘다성공여부, "results": {"A": 결과, "B": 결과}}` |
| `sequence(ports, record)` | 단계 결과 목록 반환 |

### 동작 규칙

- 어느 장치든 실패하면 다른 장치의 현재 작업 결과는 확인하되 off 단계는 시작하지 않는다.
- 감시는 작업 결과가 확정된 뒤에도 이어진다.
- 복구는 새 관측만 갱신한다. 이전 실패를 성공으로 바꾸거나 명령을 다시 보내지 않는다.
- 조회 실패 시 마지막 정상 값과 시각을 지우거나 바꾸지 않는다. 한 번도 읽지 못했다면 None을 유지한다.
- `CancelledError`를 통신 실패와 섞어 삼키지 않는다.
- 함수 이름과 인자를 유지하고, 제공된 실행·기록·종료 틀과 장치·통신·교보재 파일은 수정하지 않는다.

## 3. 구현 선택

자료가 정하지 않아 이 설계에서 결정한 내용이다.

| 항목 | 선택 | 이유 |
|---|---|---|
| 동시 시작 방식 | `asyncio.gather` | `work`가 예상 오류를 결과로 바꾸므로 예외 수집 옵션이 필요 없다 |
| 장치 이름과 포트 대응 | `zip(("A", "B"), ports)` | 제공 틀 `run_project`와 같은 방식이다 |
| 오류 이름 | `type(error).__name__` | `API.md`의 `오류이름`을 예외 클래스 이름으로 해석했다 |
| 예외 처리 범위 | `except (TimeoutError, ConnectionError, ValueError)` | `CancelledError`와 프로그래밍 오류가 그대로 전파된다 |
| 접수 후 완료 확인 실패 | 그 작업을 실패로 확정 | 장치가 뒤늦게 목표에 도달해도 결과를 바꾸지 않는다 |
| `sequence_stopped`의 reason | 실패 사유를 나타내는 문자열 `"on stage failed"` | `API.md`는 필드만 정하고 값은 정하지 않았다 |

## 4. 함수 설계

### watch

무한 반복한다. 매회 `request_async(port, "status", timeout=0.5)`를 호출한다.

- 성공: `record("observation", name, output=..., busy=...)`의 반환 이벤트에서 `elapsed`를 얻어 `last_output`, `last_ok`를 갱신하고 `error`를 None으로 지운다.
- 실패: `error`만 오류 이름으로 바꾸고 `record("observation_error", name, error=...)`를 남긴다.
- 성공·실패와 무관하게 `await asyncio.sleep(0.2)` 후 다시 조회한다.

### work

1. 목표를 정한다. `on`은 1, `off`는 0이다.
2. `command_request`를 기록하고 `request_async(port, command, timeout=0.5)`를 호출한다.
3. 응답을 받으면 `accepted`를 기록한다.
4. `wait_output_async(port, target=목표)`로 실제 완료를 확인한다.
5. `completed`를 기록하고 `{"ok": True, "output": 값}`을 반환한다.

2~4단계의 예상 예외는 `job_error`를 기록하고 `{"ok": False, "error": 오류이름}`을 반환한다.

### stage

`asyncio.gather`로 A·B의 `work`를 함께 시작하고 두 결과를 기다린다. `results`와 `ok`를 만들어 `stage_result`를 기록하고 반환한다.

### sequence

1. on 단계 결과를 목록에 넣는다.
2. `ok`가 거짓이면 `sequence_stopped`를 기록하고 목록을 반환한다.
3. 참이면 off 단계 결과를 목록에 추가해 반환한다.

off 단계가 실패해도 재시도하지 않는다.

## 5. 실패 시 예상 흐름

A가 처음부터 무응답인 경우다.

1. A의 on 요청이 약 0.5초 뒤 `TimeoutError`로 끝나고 `job_error`가 기록된다.
2. B의 on은 계속되어 약 4초 뒤 `completed`가 기록된다.
3. `stage_result`의 `ok`가 거짓이 되고 `sequence_stopped`가 기록되며 off 요청은 없다.
4. A의 감시는 `observation_error`를, B의 감시는 `observation`을 계속 남긴다.
5. A 복구 후 A의 `observation`이 다시 나타난다. 모형에서 on이 실행되지 않았으므로 A의 출력은 0으로 예상한다. 이 값은 실행으로 확인한다.

## 6. 검증

`python teacher_demo.py --no-browser`를 띄우고 `POST /api/reset`, `POST /api/mode`로 버튼과 같은 조작을 한 뒤 JSONL 로그를 대조한다.

| 시나리오 | 로그에서 확인할 내용 |
|---|---|
| 정상 | A·B의 `command_request`가 이어서 나타남. `accepted`와 `completed`가 구분됨. 양쪽 on `completed` 뒤에 off `command_request`가 나타남. 첫 on 요청부터 마지막 off 완료까지 약 8초 |
| 한쪽 실패 | A의 `job_error` 이후에도 B의 `completed`와 `observation`이 이어짐. off의 `command_request`가 없음 |
| 복구 | `stage_result` 이후 복구. A의 새 `observation`이 나타나고, `stages`의 실패가 유지되며, 복구 뒤 `command_request`가 없음 |
| 종료 | 작업 뒤에도 `observation`이 이어지고, 종료 시 `run_end`가 기록됨. 프로그램 종료와 장치 출력 off를 구분함 |

스크립트로 얻은 결과는 AI가 실행한 증거로 표시한다. 학생이 직접 확인할 항목은 체크리스트로 분리한다. 실행 기록은 `docs/verification/`, 로그는 `logs/`에 남긴다.

## 7. 범위 밖

- 재시도, 자동 복구, 명령 재전송
- 제공 파일과 제공 틀의 수정
- 외부 패키지
- 과제 2 구현과 비교
