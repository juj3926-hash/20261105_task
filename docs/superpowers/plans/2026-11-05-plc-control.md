# PLC 감시·값 변경 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실제 PLC의 D01000을 감시하고 터미널 명령으로 값을 바꾸는 비동기·동기 프로그램을 만들고, PLC 없이 검증한 뒤 실제 시험 준비를 마친다.

**Architecture:** `plc_common.py`가 통신 없는 공통 로직을 맡고, 두 실행 파일은 같은 규칙을 각자의 흐름으로 돌린다. 클라이언트와 키 입력을 인자로 주입해 가짜 객체로 시험한다.

**Tech Stack:** Python 3.10 이상(현재 3.14.6), PyModbus 3.16.1, `asyncio`, `msvcrt`, `unittest`

**Spec:** `docs/superpowers/specs/2026-11-05-plc-control-design.md`

## Global Constraints

- 읽기는 `read_holding_registers(0, count=1, device_id=unit)`, 쓰기는 `write_register(0, value, device_id=unit)`다. 주소 1000이나 40001을 쓰지 않는다.
- 클라이언트 생성 인자는 `port, baudrate, bytesize, parity, stopbits, timeout, retries`다. `--port`, `--bytesize`, `--parity`, `--stopbits`는 기본값 없는 필수 인자다.
- 기본값은 baudrate 9600, unit 1, timeout 2, retries 0, period 1이다.
- Modbus 요청은 한 번에 하나만 보낸다. 실패한 쓰기를 재전송하지 않는다.
- `plc_project_sync.py`에 `threading`, `multiprocessing`, `subprocess`, `asyncio`를 넣지 않는다.
- 단위 테스트와 구현 단계에서 실제 COM 포트를 열지 않는다. 실제 PLC 시험은 spec 3장 확인 뒤 사용자가 허락한 경우에만 한다.
- 이벤트 type과 필드는 spec 6장을 따른다. `plc/logs/`에 기록한다.

## Review Focus

1. 미관측 상태의 읽기 실패: 표시가 미관측이고 값이 0이 되지 않는다. (Task 1 `test_never_read_shows_unobserved`)
2. 무응답 중 쓴 값의 확인 대기: 쓰기 실패 값은 뒤의 읽기와 비교하지 않는다. (Task 1 `test_failed_write_is_not_confirmed`)
3. 예외 대신 오류 응답(`isError()`)이 오는 경우: 실패로 기록하고 값이 바뀌지 않는다. (Task 2, 3 `test_error_response_is_failure`)
4. 응답 대기 중 `quit`: 비동기판은 대기 끝을 기다리지 않고 종료하고 연결을 닫는다. (Task 2 `test_quit_during_wait_closes`)
5. 연결이 끊긴 상태: 다음 요청 전에 `connect`를 시도하고, 실패해도 프로그램은 계속된다. (Task 2, 3 `test_reconnect_failure_keeps_running`)

---

### Task 1: plc_common

**Files:**
- Create: `plc/plc_common.py`, `tests/test_plc.py`

**Interfaces:**
- Produces:
  - `parse_args(argv=None) -> Namespace`, `client_options(args) -> dict`
  - `parse_command(text) -> tuple`: `("write", int)`, `("unit", int)`, `("status",)`, `("quit",)`, `("reject", reason)`
  - `class State(unit)`: 속성 `unit`, `value`, `observed_at`, `error`, `pending`(deque), `expected`. 메서드 `handle_line(text, record) -> bool`(quit이면 True), `read_ok(value, record)`, `read_failed(error, record)`, `write_done(value, ok, error, record)`, `summary() -> str`
  - `class EventLog(output)`: `__call__(kind, **fields) -> dict`, `wall`, `elapsed`, `type` 포함
  - `class KeyReader(source=None)`: `poll() -> list[str]`. 기본 source는 `msvcrt`이고 가짜는 `kbhit()`, `getwch()`를 가진다. Enter로 줄을 끝내고 Backspace를 처리한다.
  - `open_log(prefix) -> (file, path)`: `plc/logs/` 아래 새 파일
  - `describe(error) -> str`: 예외 클래스 이름

- [ ] **Step 1: 실패하는 테스트 작성**
  - `test_args_require_serial_format`: `--parity` 없으면 `SystemExit`
  - `test_args_defaults`: baudrate 9600, unit 1, timeout 2, retries 0, period 1
  - `test_parse_write_bounds`: `write 0`, `write 65535` 허용, `write -1`, `write 65536`, `write abc` 거절
  - `test_parse_unit_bounds`: `unit 1`, `unit 247` 허용, `unit 0`, `unit 248` 거절
  - `test_never_read_shows_unobserved`: 읽기 실패 뒤 `value is None`, `summary()`에 `미관측`
  - `test_failure_keeps_last_good`: 읽기 성공 뒤 실패. 값·시각 유지, `error` 설정, `summary()`에 오류 표시
  - `test_success_clears_error`
  - `test_write_confirmed_once`: 성공한 쓰기 100 뒤 읽기 100이면 `write_confirmed` 1건, 다음 읽기에는 없음
  - `test_write_mismatch`: 성공한 쓰기 100 뒤 읽기 50이면 `write_mismatch`
  - `test_failed_write_is_not_confirmed`: 실패한 쓰기 뒤 읽기에 두 이벤트 모두 없음
  - `test_handle_line_events`: `write 100`은 `input_received`, `request_accepted`, pending 1건. `unit 2`는 `unit_changed`. 잘못된 입력은 `input_rejected`. `quit`은 True 반환
  - `test_key_reader_lines`: 가짜 키 `w`, `Backspace`, `u`, `\r`이 줄 `u`가 됨

- [ ] **Step 2: 실패 확인**

Run: `python -m unittest tests.test_plc -v`
Expected: `plc_common` import 실패

- [ ] **Step 3: spec 5~6장대로 구현.** `tests/test_plc.py`는 맨 위에서 `plc/`를 `sys.path`에 넣는다.

- [ ] **Step 4: 통과 확인**

Run: `python -m unittest tests.test_plc -v`
Expected: 전체 OK

- [ ] **Step 5: Commit**

```bash
git add plc/plc_common.py tests/test_plc.py
git commit -m "feat: add PLC common logic"
```

### Task 2: 비동기판

**Files:**
- Create: `plc/plc_project.py`
- Test: `tests/test_plc.py`

**Interfaces:**
- Consumes: Task 1 전체
- Produces: `async def run(client, args, record, keys) -> None`. `quit`이나 취소로 끝나고 항상 `client.close()`를 호출한다. `main()`이 `AsyncModbusSerialClient(**client_options(args))`와 `EventLog`, `KeyReader`를 만든다.
- 테스트 도우미 `FakeAsyncClient`: `delay`, `fail` 설정, 동시 호출 수 `max_active`, 요청 목록 `calls`, `connected`, `closed`. `FakeKeys`: 시각별 키를 내주는 `kbhit`, `getwch`

- [ ] **Step 1: 실패하는 테스트 작성** (period 0.1, 지연은 0.3초로 축소)
  - `test_reads_periodically`: 주소 0, count 1, unit 1로 읽고 `observation` 기록
  - `test_write_before_next_read_then_confirm`: `write 100` 뒤 `write_sent`가 다음 `read_sent`보다 앞서고 `write_confirmed`
  - `test_writes_in_order`: `write 100`, `write 200`, `write 300` 순서 유지
  - `test_input_during_wait`: 응답 지연 중 넣은 `status`의 `input_received`가 `observation_error`보다 앞섬, `waiting` 기록
  - `test_one_request_at_a_time`: 지연 중 쓰기 입력 뒤 `max_active == 1`
  - `test_failed_write_not_resent`: 실패한 쓰기의 `calls` 1회
  - `test_unit_change_applies_next_request`: 다음 요청의 `device_id == 2`, 복원 뒤 `observation`으로 오류 해제
  - `test_error_response_is_failure`
  - `test_quit_during_wait_closes`: 지연보다 짧은 시간에 끝나고 `closed`
  - `test_reconnect_failure_keeps_running`: `connect`가 거짓이어도 `observation_error`가 쌓이고 `quit`으로 끝남

- [ ] **Step 2: 실패 확인**

Run: `python -m unittest tests.test_plc -v`
Expected: `plc_project` import 실패

- [ ] **Step 3: spec 7~8장의 세 Task 구현.** `except`에는 `ModbusException`, `OSError`, `asyncio.TimeoutError`만 지정한다. 표시 Task는 요청 진행 중 약 0.5초마다 `waiting`을 기록한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m unittest tests.test_plc -v`
Expected: 전체 OK

- [ ] **Step 5: Commit**

```bash
git add plc/plc_project.py tests/test_plc.py
git commit -m "feat: add async PLC monitor"
```

### Task 3: 동기판

**Files:**
- Create: `plc/plc_project_sync.py`
- Test: `tests/test_plc.py`

**Interfaces:**
- Consumes: Task 1 전체, Task 2의 `FakeKeys`
- Produces: `def run(client, args, record, keys) -> None`. `main()`은 `ModbusSerialClient`를 쓴다.
- 테스트 도우미 `FakeSyncClient`: 호출 안에서 `time.sleep(delay)`로 대기

- [ ] **Step 1: 실패하는 테스트 작성**
  - `test_sync_reads_and_writes`: 정상 쓰기 뒤 `write_confirmed`
  - `test_sync_writes_in_order`
  - `test_sync_input_waits_for_response`: 응답 지연 중 넣은 키의 `input_received`가 해당 `observation_error`보다 뒤
  - `test_sync_failed_write_not_resent`
  - `test_sync_unit_change_and_restore`
  - `test_error_response_is_failure` (동기 클래스)
  - `test_reconnect_failure_keeps_running` (동기 클래스)
  - `test_sync_has_no_concurrency_import`: 소스에 금지 모듈 import 없음

- [ ] **Step 2: 실패 확인**

Run: `python -m unittest tests.test_plc -v`
Expected: `plc_project_sync` import 실패

- [ ] **Step 3: spec 7장의 반복 구현.** 예외는 `ModbusException`, `OSError`만 잡는다.

- [ ] **Step 4: 통과 확인**

Run: `python -m unittest tests.test_plc tests.test_project tests.test_project_sync`
Expected: 전체 OK

- [ ] **Step 5: Commit**

```bash
git add plc/plc_project_sync.py tests/test_plc.py
git commit -m "feat: add sync PLC monitor"
```

### Task 4: 실행 안내와 시험 양식

**Files:**
- Create: `plc/README.md`, `docs/verification/2026-11-05-plc-tests.md`, `docs/verification/2026-11-05-plc-comparison.md`

**Interfaces:**
- Consumes: 두 프로그램의 CLI와 명령

- [ ] **Step 1: 실제 포트 없는 동작 확인.** 존재하지 않는 포트 `COM99`로 두 프로그램을 실행한다. Expected: 원인 안내 뒤 종료, 추적 오류 없음. `--help`에 필수 인자가 표시된다.
- [ ] **Step 2: `plc/README.md` 작성.** 실행 명령, 연결 인자, 명령, 종료 방법, 실행 전 확인 사항을 쓴다.
- [ ] **Step 3: 시험 기록 양식 작성.** `TASKS_2.md`의 표와 시험별 절차를 넣는다. 실제 값은 비워 두고 모두 미확인으로 표시한다. 가짜 클라이언트 결과를 PLC 시험 결과로 적지 않는다.
- [ ] **Step 4: 비교 기록 양식 작성.** 세 질문을 넣고, 실제 로그로 채울 자리를 표시한다.
- [ ] **Step 5: Commit**

```bash
git add plc/README.md docs/verification
git commit -m "docs: add PLC run guide and test templates"
```
