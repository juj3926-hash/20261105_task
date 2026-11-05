# 과제 2 동기 제어 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `project_sync.py`의 `run`을 단일 실행 흐름으로 완성하고, 과제 1과 작업 순서·전체 시간·감시 차이를 로그로 비교한다.

**Architecture:** `run`이 순서만 표현하고, `observe`, `observe_all`, `job`, `sync_stage`가 조회·작업·단계를 맡는다. 모든 호출은 한 흐름에서 차례로 실행되므로 조회는 작업 사이에서만 일어난다.

**Tech Stack:** Python 3.10 이상(현재 3.14.6), 표준 라이브러리, `unittest`

**Spec:** `docs/superpowers/specs/2026-11-05-sync-control-design.md`

## Global Constraints

- 표준 라이브러리만 사용한다. `threading`, `multiprocessing`, `subprocess`, `asyncio`를 `project_sync.py`에 넣지 않는다.
- `run(ports=(PORT_A, PORT_B), record=None)` 인자를 유지한다. `project_sync.py`의 제공 틀(`main`)과 `device_*.py`, `teacher_demo.py`는 수정하지 않는다.
- 명령 요청과 조회는 `timeout=0.5`, 완료 대기는 `limit` 기본 8초, 작업 후 조회 간격은 `time.sleep(0.2)`다.
- 예상 예외는 `(TimeoutError, ConnectionError, ValueError)`만 잡는다. 오류 이름은 `type(error).__name__`, 정지 사유는 `"on stage failed"`다.
- 재시도와 명령 재전송을 넣지 않는다. 이벤트 type과 필드는 과제 1과 같다.

## Review Focus

1. B 작업 중 A 통신 끊김: 다음 조회가 `observation_error`로 남고 흐름은 계속된다. (Task 2 `test_silent_mid_run_keeps_flow`)
2. 장치 서버가 없는 포트: `run`이 예외로 끝나지 않고 다른 장치를 시도한다. (Task 2 `test_closed_port_keeps_running`)
3. 조회 거부(`ValueError`): 조회 오류로 남고 흐름은 계속된다. (Task 1 `test_observe_rejected_status`)
4. 작업 중 Ctrl+C: `KeyboardInterrupt`가 실패 결과로 바뀌지 않고 `run` 밖으로 나간다. (Task 2 `test_interrupt_during_job_propagates`)
5. 복구 뒤: 새 관측만 갱신되고 명령이 추가되지 않는다. (Task 2 `test_recovery_adds_no_command`)

---

### Task 1: observe, observe_all, job

**Files:**
- Modify: `project_sync.py:11-19` (학생 구현 영역)
- Create: `tests/test_project_sync.py`

**Interfaces:**
- Consumes: `tests/test_project.py`의 `make_devices`, `closed_port`, `Recorder`, `CLOSED_PORT_ERRORS`
- Produces: `observe(name, port, item, record) -> None`, `observe_all(ports, observed, record) -> None`, `job(name, port, command, record) -> dict`. `observed`는 `{"A": item, "B": item}`, `item`은 과제 1과 같은 형식이고 `job`의 반환은 과제 1 `work`와 같다.

- [ ] **Step 1: 실패하는 테스트 작성** (`unittest.TestCase`, 지연 0.2·0.4초 장치)
  - `test_observe_success`: `last_output == 0`, `last_ok`가 `observation`의 `elapsed`, `error is None`
  - `test_observe_failure_keeps_last_good`: 정상 조회 뒤 silent. 값·시각 유지, `error == "TimeoutError"`, `observation_error` 기록
  - `test_observe_rejected_status`: `mock.patch("project_sync.request_sync", side_effect=ValueError("거부"))`. 예외 없이 `error == "ValueError"`
  - `test_observe_all_order`: `observation` 장치 순서가 `["A", "B"]`
  - `test_job_records_in_order`: 이벤트가 `command_request`, `accepted`, `completed`이고 반환 `{"ok": True, "output": 1}`
  - `test_job_silent_fails`: `{"ok": False, "error": "TimeoutError"}`, `job_error` 있음, `accepted` 없음

- [ ] **Step 2: 실패 확인**

Run: `python -m unittest tests.test_project_sync -v`
Expected: `observe`, `job` 속성이 없어 ERROR

- [ ] **Step 3: spec 4장의 세 함수를 `run` 위에 구현**

- [ ] **Step 4: 통과 확인**

Run: `python -m unittest tests.test_project_sync -v`
Expected: 전체 OK

- [ ] **Step 5: Commit**

```bash
git add project_sync.py tests/test_project_sync.py
git commit -m "feat: add sync observe and job helpers"
```

### Task 2: sync_stage와 run

**Files:**
- Modify: `project_sync.py` (학생 구현 영역, `import io` 추가)
- Test: `tests/test_project_sync.py`

**Interfaces:**
- Consumes: Task 1의 세 함수
- Produces: `sync_stage(command, ports, observed, record) -> dict` (과제 1 `stage`와 같은 형식), `run(ports, record)`는 반환하지 않고 `KeyboardInterrupt`로만 끝난다.
- 테스트 도우미 `StopRecorder(Recorder)`: `stop_when(event, recorder)`가 참이 되면 기록 뒤 `KeyboardInterrupt`를 일으킨다. 기본 조건은 마지막 단계가 끝난 뒤 `observation` 4건이다.

- [ ] **Step 1: 실패하는 테스트 작성**
  - `test_normal_order`: `command_request`와 `completed`의 (장치, 명령) 순서가 A on, B on, A off, B off이고 각 `completed`가 다음 `command_request`보다 앞섬
  - `test_observes_between_jobs`: 첫 `command_request` 앞, 각 `completed` 뒤에 A·B `observation`이 모두 있음
  - `test_a_failure_still_tries_b_on`: A silent. B on `completed` 있음, `stage_result` ok 거짓, `sequence_stopped`의 `reason == "on stage failed"`, off `command_request` 없음
  - `test_off_failure_still_tries_b_off`: A off `command_request` 직전 silent. B off `command_request` 있음, off `stage_result` ok 거짓
  - `test_monitors_after_sequence`: 마지막 `stage_result` 뒤 `observation` 있음, `KeyboardInterrupt`로 종료
  - `test_silent_mid_run_keeps_flow`: B on `accepted` 뒤 A silent. A `observation_error` 있고 B on `completed` 있음
  - `test_closed_port_keeps_running`: `(closed_port(), port_b)`. A `job_error`, B on `completed`, off 없음
  - `test_interrupt_during_job_propagates`: `accepted`에서 `KeyboardInterrupt`. `run` 밖으로 나오고 `job_error` 없음
  - `test_recovery_adds_no_command`: A silent로 시작, `sequence_stopped`에서 normal로 복구. 복구 뒤 A `observation` 있음, A `command_request` 1회, `a.history`에 command 없음

- [ ] **Step 2: 실패 확인**

Run: `python -m unittest tests.test_project_sync -v`
Expected: `NotImplementedError` 또는 `sync_stage` 부재로 실패

- [ ] **Step 3: spec 4장의 `sync_stage`, `run` 구현.** 학생 영역의 TODO 주석과 `NotImplementedError`가 남지 않게 한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m unittest discover -s tests -t .`
Expected: 과제 1 테스트를 포함해 전체 OK

- [ ] **Step 5: Commit**

```bash
git add project_sync.py tests/test_project_sync.py
git commit -m "feat: implement sync control run"
```

### Task 3: 실제 장치 시나리오와 비교

**Files:**
- Create: `docs/verification/run_sync_scenarios.py`, `docs/verification/2026-11-05-sync-control.md`, `docs/verification/2026-11-05-comparison.md`
- 로그: `logs/`

**Interfaces:**
- Consumes: `python project_sync.py`, `POST /api/reset`, `POST /api/mode`, `docs/verification/summarize_log.py`, 과제 1 로그

- [ ] **Step 1: 시나리오 스크립트 작성.** `run_async_scenarios.py`와 같은 방식이다. 동기판은 시간 제한이 없으므로 로그에서 완료 조건을 본 뒤 약 2초 더 감시하고 프로세스를 종료한다. 복구는 `sequence_stopped` 약 1초 뒤에 한다.
- [ ] **Step 2: 정상, 한쪽 실패·복구 실행.** 저장소 루트에서 `python docs/verification/run_sync_scenarios.py`. 로그 경로가 출력되어야 한다.
- [ ] **Step 3: 로그 대조.** `python docs/verification/summarize_log.py <로그>`로 spec 5장의 예상값을 실제값과 비교한다. 예상과 다르면 실제값을 기록한다.
- [ ] **Step 4: 검증 기록 작성.** 과제 1 기록과 같은 구분으로 쓴다. 강제 종료로 `run_end`가 없는 점과 Ctrl+C 미확인을 적는다.
- [ ] **Step 5: 비교 결과 작성.** 작업 순서, 첫 on 요청부터 마지막 off 완료까지의 시간, 장치별 관측 최대 간격, A 실패가 B 시작에 준 영향을 표로 쓴다. 이 공백은 독립 감시 흐름의 공백이며 `wait_output_sync` 내부 status 조회는 계속된다는 점과, 단일 실행 흐름의 비교 조건임을 함께 적는다.
- [ ] **Step 6: Commit**

```bash
git add docs/verification logs
git commit -m "docs: record sync verification and comparison"
```
