# 과제 2 동기 제어 설계

- 대상 파일: `project_sync.py`의 학생 구현 영역 (`run`과 내부 함수)
- 기준 설계: `docs/superpowers/specs/2026-11-05-async-control-design.md`. 여기서는 달라지는 부분만 적는다.
- 범위: 동기 구현과 과제 1과의 비교

## 1. 목표

같은 장치의 켜기·끄기를 단일 실행 흐름으로 구현하고, 비동기 구현과 작업 순서·전체 실행 시간·감시 실행의 차이를 로그로 비교한다.

## 2. 자료에 정해진 사실

과제 1 spec 2장의 장치와 통신 사실은 같다. 다음이 추가된다.

- 정상 순서는 A on 완료 → B on 완료 → A off 완료 → B off 완료다.
- `request_sync`, `wait_output_sync`를 사용한다. 명령 요청과 조회의 `timeout`은 0.5초, `limit`은 기본 8초다.
- A의 on이 실패해도 B의 on은 시도한다. on이 모두 성공한 경우에만 off로 진행한다.
- 작업 전후와 장치 작업 사이에 상태를 조회해 값·시각·오류를 남긴다. 마지막 정상 값·시각과 현재 오류를 구분한다.
- 작업 순서가 끝난 뒤에도 주기 조회하며 Ctrl+C로 종료한다.
- 제어 프로그램에 스레드·별도 프로세스·asyncio 작업을 추가하지 않는다.
- `wait_output_sync` 내부의 status 조회는 해당 장치의 완료 확인용으로 계속된다. 모든 조회가 멈춘 것으로 설명하지 않는다.
- 통신 실패를 기록하고, 과거 결과를 바꾸거나 명령을 자동 재전송하지 않는다.
- `run_start`, `run_end`는 제공 틀이 기록한다. `--seconds`는 필수가 아니다.

## 3. 구현 선택

| 항목 | 선택 | 이유 |
|---|---|---|
| 구조 | 내부 함수 `observe`, `observe_all`, `job`, `sync_stage`로 분리 | 예외 처리 반복을 없애고 과제 1과 대응시킨다 |
| 이벤트 | 과제 1과 같은 type과 필드 | 두 로그를 같은 기준으로 비교한다 |
| 조회 지점 | 각 장치 작업 전후에 A·B 모두 조회. 작업 사이 조회는 공유한다 | 요구된 지점을 모두 덮는 가장 단순한 규칙이다 |
| off 단계 실패 | A off가 실패해도 B off는 시도 | 자료는 on만 정한다. 비동기판에서 둘을 함께 시작하는 것과 결과를 맞춘다 |
| 작업 후 조회 주기 | `time.sleep(0.2)` | 비동기판의 감시 간격과 맞춘다 |
| 오류 이름, reason | 과제 1과 동일 (`type(error).__name__`, `"on stage failed"`) | 비교 기준 통일 |
| 종료 | `KeyboardInterrupt`를 잡지 않음 | 제공 `main`이 처리한다 |

## 4. 함수 설계

- `observe(name, port, item, record)`: `request_sync(port, "status", timeout=0.5)` 1회. 과제 1 `watch`의 한 회차와 같다. 반복과 대기는 없다.
- `observe_all(ports, observed, record)`: A, B 순서로 `observe`를 호출한다.
- `job(name, port, command, record)`: 과제 1 `work`와 같은 순서와 반환 형식이다.
- `sync_stage(command, ports, observed, record)`: A `job` → `observe_all` → B `job` → `observe_all`. 과제 1 `stage`와 같은 형식으로 `stage_result`를 기록하고 반환한다.
- `run(ports, record)`: `record`가 None이면 `EventLog(io.StringIO())`를 쓴다. `observe_all` → on 단계 → 실패 시 `sequence_stopped`, 성공 시 off 단계 → 무한 반복(`observe_all`, `time.sleep(0.2)`).

## 5. 예상 동작

아래 값은 예상이며 실행으로 확인한다.

- 정상: 첫 on 요청부터 마지막 off 완료까지 약 12초 이상. 과제 1은 8.07초였다.
- 감시 공백: A 작업 중 B의 `observation`이 없고, B 작업 중 A의 `observation`이 없다. 공백은 약 2초와 4초다.
- A 무응답: 조회마다 약 0.5초가 들어, B의 on 시작이 과제 1보다 약 1.5초 늦는다.

## 6. 검증

단위 테스트는 `tests/test_project_sync.py`에 둔다. `run`은 끝나지 않으므로 테스트의 `record`가 지정 조건에서 `KeyboardInterrupt`를 일으켜 멈춘다.

실제 장치 시나리오는 과제 1과 같은 네 가지를 실행해 `docs/verification/`에 기록한다. 동기판에는 `--seconds`가 없어 자동 실행은 프로세스를 강제 종료한다. 이 경우 `run_end`가 남지 않으므로 Ctrl+C 종료는 미확인으로 두고 학생 체크리스트로 넘긴다.

비교 결과는 작업 순서, 첫 on 요청부터 마지막 off 완료까지의 시간, 장치별 관측 최대 간격, A 실패가 B 시작에 준 영향을 표로 남긴다. 단일 실행 흐름의 비교이며, 동기 통신 전체의 한계로 일반화하지 않는다.

## 7. 범위 밖

재시도, 자동 복구, 제공 틀 수정, 외부 패키지, 동기판 `--seconds` 추가
