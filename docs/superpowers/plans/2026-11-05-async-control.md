# 과제 1 비동기 제어 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `project.py`의 `watch`, `work`, `stage`, `sequence`를 완성해 A·B를 동시 제어하고, 한쪽 실패에도 다른 장치의 작업과 감시를 유지한다.

**Architecture:** 제공 틀 `run_project`가 감시 Task 둘과 `sequence` Task를 함께 실행한다. `work`가 예상 통신 오류를 결과값으로 바꾸므로 `stage`의 `gather`는 한쪽 실패로 끊기지 않는다.

**Tech Stack:** Python 3.10 이상(현재 3.14.6), 표준 라이브러리 `asyncio`, `unittest`

**Spec:** `docs/superpowers/specs/2026-11-05-async-control-design.md`

## Global Constraints

- 표준 라이브러리만 사용한다. 테스트도 pytest가 아닌 `unittest`를 쓴다.
- 함수 이름과 인자를 유지한다. `project.py`의 제공 틀(`# 제공된 실행·로그·종료 틀` 아래)과 `device_*.py`, `teacher_demo.py`는 수정하지 않는다.
- 명령 요청과 감시 조회는 `timeout=0.5`, 완료 대기는 `limit` 기본 8초, 감시 간격은 `asyncio.sleep(0.2)`다.
- 예상 예외는 `(TimeoutError, ConnectionError, ValueError)`만 잡는다. 오류 이름은 `type(error).__name__`이다.
- 재시도와 명령 재전송을 넣지 않는다.

## Review Focus

1. 접수 뒤 완료 대기 중 통신 끊김: 그 작업만 실패하고 다른 장치는 완료된다. (Task 2 `test_silent_after_accept_fails_job`)
2. 장치 서버가 아예 없는 포트: `ConnectionError`가 실패 결과와 현재 오류로 남고 프로그램은 계속된다. (Task 1, 2 `test_closed_port_*`)
3. 장치의 요청 거부(`ValueError`): 통신 실패와 같은 경로로 결과에 남는다. (Task 2 `test_rejected_request_is_failure`)
4. 감시·작업 중 취소: `CancelledError`가 삼켜지지 않는다. (Task 1 `test_cancel_propagates`, Task 2 `test_cancel_not_converted`)
5. 복구 뒤: 새 관측만 갱신되고 과거 실패와 명령 횟수는 그대로다. (Task 3 `test_recovery_adds_no_command`)

---

### Task 1: watch

**Files:**
- Modify: `project.py:7-12`
- Create: `tests/test_project.py`

**Interfaces:**
- Produces: `async def watch(name, port, item, record)`. 반환하지 않고 취소될 때까지 반복한다. `item` 키는 `last_output`, `last_ok`, `error`다.
- Produces: 테스트 도우미 `make_devices()`는 `DeviceServers(ports=(0, 0), delays=(0.2, 0.4))`를 반환하고, `Recorder`는 `record` 호출을 `events` 목록에 쌓고 `elapsed`가 든 딕셔너리를 반환한다. 포트 0을 써서 실행 중인 교보재와 충돌하지 않는다.

- [ ] **Step 1: 실패하는 테스트 작성** (`unittest.IsolatedAsyncioTestCase`, 각 테스트는 `watch`를 Task로 띄우고 약 0.5초 뒤 취소)
  - `test_success_updates_item`: `last_output == 0`, `last_ok`가 마지막 `observation`의 `elapsed`, `error is None`
  - `test_failure_keeps_last_good`: 정상 조회 뒤 `set_mode("silent")`. `last_output`, `last_ok`가 유지되고 `error == "TimeoutError"`
  - `test_recovery_clears_error`: `set_mode("normal")` 뒤 `error is None`, `last_ok` 증가
  - `test_closed_port_keeps_none`: 닫힌 포트. `last_output is None`, `last_ok is None`, `error == "ConnectionError"`
  - `test_cancel_propagates`: `await task`가 `asyncio.CancelledError`를 발생시킴

- [ ] **Step 2: 실패 확인**

Run: `python -m unittest tests.test_project -v`
Expected: `NotImplementedError`로 FAIL

- [ ] **Step 3: spec 4장의 watch 구현**

- [ ] **Step 4: 통과 확인**

Run: `python -m unittest tests.test_project -v`
Expected: 전체 OK

- [ ] **Step 5: Commit**

```bash
git add project.py tests/test_project.py
git commit -m "feat: implement device status watch"
```

### Task 2: work

**Files:**
- Modify: `project.py:15-19`
- Test: `tests/test_project.py`

**Interfaces:**
- Consumes: Task 1의 `make_devices`, `Recorder`
- Produces: `async def work(name, port, command, record) -> dict`. 성공 `{"ok": True, "output": int}`, 실패 `{"ok": False, "error": str}`

- [ ] **Step 1: 실패하는 테스트 작성**
  - `test_on_records_in_order`: 이벤트 순서가 `command_request`, `accepted`, `completed`이고 반환이 `{"ok": True, "output": 1}`
  - `test_off_targets_zero`: on 뒤 off. 반환이 `{"ok": True, "output": 0}`
  - `test_silent_fails_without_accept`: 시작 전 silent. `{"ok": False, "error": "TimeoutError"}`, `job_error` 있음, `accepted` 없음
  - `test_silent_after_accept_fails_job`: `accepted` 뒤 silent 전환. `ok`가 거짓이고 `job_error` 있음, `completed` 없음
  - `test_closed_port_is_failure`: `error == "ConnectionError"`
  - `test_rejected_request_is_failure`: `unittest.mock.patch("project.request_async", side_effect=ValueError("거부"))`. `error == "ValueError"`
  - `test_cancel_not_converted`: 완료 대기 중 취소하면 `CancelledError`가 발생하고 `job_error`는 없음

- [ ] **Step 2: 실패 확인**

Run: `python -m unittest tests.test_project -v`
Expected: 새 테스트가 `NotImplementedError`로 FAIL

- [ ] **Step 3: spec 4장의 work 구현.** 이벤트 필드는 `API.md` 기록 함수 표를 따른다. `completed`의 `output`은 `wait_output_async` 응답의 값이다.

- [ ] **Step 4: 통과 확인**

Run: `python -m unittest tests.test_project -v`
Expected: 전체 OK

- [ ] **Step 5: Commit**

```bash
git add project.py tests/test_project.py
git commit -m "feat: implement device command work"
```

### Task 3: stage와 sequence

**Files:**
- Modify: `project.py:22-32`
- Test: `tests/test_project.py`

**Interfaces:**
- Consumes: Task 2의 `work`
- Produces: `async def stage(command, ports, record) -> dict`, `async def sequence(ports, record) -> list[dict]`

- [ ] **Step 1: 실패하는 테스트 작성**
  - `test_stage_starts_both_before_completion`: 두 `command_request`가 첫 `completed`보다 앞섬. 반환 형식이 spec 계약과 같고 `stage_result` 기록
  - `test_stage_keeps_other_result`: A silent. `ok`가 거짓, `results["A"]["ok"]`가 거짓, `results["B"] == {"ok": True, "output": 1}`
  - `test_sequence_normal`: 단계 2개. 모든 on `completed`가 첫 off `command_request`보다 앞섬
  - `test_sequence_stops_after_on_failure`: 단계 1개, `sequence_stopped`의 `reason == "on stage failed"`, off `command_request` 없음
  - `test_recovery_adds_no_command`: `run(ports, seconds=2, record=rec)` 실행 중 `stage_result` 뒤 A를 normal로 복구. 복구 뒤 A `observation` 있음, 결과 `stages[0]["results"]["A"]["ok"]`가 거짓, A `command_request` 1회, `devices[0].history`에 command 없음

- [ ] **Step 2: 실패 확인**

Run: `python -m unittest tests.test_project -v`
Expected: 새 테스트가 `NotImplementedError`로 FAIL

- [ ] **Step 3: spec 4장의 stage, sequence 구현.** 학생 영역의 TODO 주석과 `NotImplementedError`가 남지 않게 한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m unittest tests.test_project -v`
Expected: 전체 OK

- [ ] **Step 5: Commit**

```bash
git add project.py tests/test_project.py
git commit -m "feat: implement stage and sequence control"
```

### Task 4: 실제 장치 시나리오 검증

**Files:**
- Create: `docs/verification/2026-11-05-async-control.md`
- 로그: `logs/`

**Interfaces:**
- Consumes: 완성된 `python project.py`, 교보재 `POST /api/reset`, `POST /api/mode` (`Content-Type: application/json`, 본문 `{"mode":"silent"}` 또는 `{"mode":"normal"}`, reset은 `{}`)

- [ ] **Step 1: 교보재 시작.** `python teacher_demo.py --no-browser`를 백그라운드로 실행한다.
- [ ] **Step 2: 정상.** reset 후 `python project.py --seconds 12`. spec 6장 정상 항목을 로그와 대조하고, 첫 on 요청부터 마지막 off 완료까지의 시간을 적는다.
- [ ] **Step 3: 한쪽 실패와 복구.** reset, silent 후 `python project.py --seconds 10`. `stage_result` 확인 뒤 normal로 복구한다. spec 6장 해당 항목과 복구 뒤 A의 출력을 적는다.
- [ ] **Step 4: 종료.** reset 후 `python project.py`를 실행하고 작업 뒤 감시를 확인한 다음 Ctrl+C를 보낸다. 자동으로 보낼 수 없으면 미확인으로 적고 학생 체크리스트로 넘긴다.
- [ ] **Step 5: 기록 작성.** 시나리오별 로그 경로, 증거 행, 판정을 적는다. AI 실행 증거, 학생 직접 확인 체크리스트, 미확인 항목을 구분한다.
- [ ] **Step 6: Commit**

```bash
git add docs/verification logs
git commit -m "docs: record async control verification"
```
