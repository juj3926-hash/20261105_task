# 과제 1 검증 기록

- 일시: 2026-11-05, Python 3.14.6, Windows 11
- 방법: `teacher_demo.py --no-browser`를 띄우고 `/api/reset`, `/api/mode`로 버튼과 같은 조작을 한 뒤 `python project.py`를 실행했다. 정상은 `--seconds 12`, 실패·복구는 `--seconds 10`, 종료는 옵션 없이 실행했다.
- 재현: 저장소 루트에서 `python docs/verification/run_async_scenarios.py`, 로그 요약은 `python docs/verification/summarize_log.py <로그 경로>`
- 아래 "AI 실행 증거"는 AI가 스크립트로 실행하고 로그를 대조한 결과다. 학생이 직접 확인한 결과가 아니다.
- 단위 테스트: `python -m unittest tests.test_project` 19개 통과

## AI 실행 증거

### 정상: 통과

로그: `logs/project-20261105-144541-1c59d6c2.jsonl`

| 경과(초) | 사건 |
|---|---|
| 0.0012 / 0.0014 | A·B on `command_request` |
| 0.0034 / 0.0031 | A·B on `accepted` |
| 2.0701 / 4.0362 | A·B on `completed` |
| 4.0364 / 4.0366 | A·B off `command_request` (양쪽 on 완료 뒤) |
| 6.1131 / 8.0723 | A·B off `completed` |

- 첫 on 요청부터 마지막 off 완료까지 8.0711초
- 8.07초 이후 약 11.81초까지의 관측은 작업 뒤 추가 감시 시간이며 위 시간에 넣지 않는다.
- 감시 최대 간격: A 0.222초, B 0.221초

### 한쪽 실패: 통과

로그: `logs/project-20261105-144553-d018c246.jsonl`

- A on `job_error`(TimeoutError) 0.5086초
- 그 뒤에도 B on `completed` 4.0351초
- B 감시 최대 간격 0.22초, 오류 0건
- `stage_result` ok=false, `sequence_stopped` 4.0352초, off `command_request` 없음

### 복구: 통과

같은 로그. `stage_result` 약 1초 뒤 복구했다. 복구 시점은 로그에 기록되지 않으며, 재현 스크립트의 대기 시간이 출처다.

- A `observation_error` 8건, 마지막 5.5282초
- A 첫 `observation` 5.7334초, 출력 0 (spec의 예상과 일치)
- 복구 뒤 `command_request` 없음. 과거 실패 유지는 이 로그의 `run_end.stages`와 단위 테스트 `test_recovery_adds_no_command`로 확인했다.
- 이 로그의 `run_end`까지 A 조회가 이어졌다.

### 종료: 일부 확인

- `--seconds` 종료: 위 두 로그에 `run_end`가 있고, 작업 뒤에도 `observation`이 이어졌다.
- 프로그램 종료와 장치 출력 off는 별개다. 실패 시나리오에서 종료 직전 B의 출력은 1이었다.
- 무기한 실행의 작업 뒤 감시: `logs/project-20261105-144603-506bb0d6.jsonl`에서 8.09초 뒤 9.70초까지 이어졌다.
- 이 실행은 Ctrl+C가 아닌 Ctrl+Break로 끝내 프로세스가 강제 종료되었고 `run_end`가 없다. Ctrl+C 검증으로 인정하지 않는다.

## 미확인

- 실제 터미널의 Ctrl+C 종료와 그때의 `run_end` 기록

## 학생 직접 확인 체크리스트

- [ ] 브라우저 버튼으로 정상 실행과 로그 확인
- [ ] A 통신 끊기 후 실행, B 작업과 감시 지속 확인
- [ ] `stage_result` 뒤 A 통신 복구, 새 관측과 과거 실패 유지 확인
- [ ] 터미널에서 Ctrl+C로 종료, `run_end` 확인

## 참고

이 Windows 환경은 닫힌 포트의 연결 거부에 2.06초가 걸렸다(별도 측정, 로그에는 없음). 0.5초 제한의 요청에서는 `ConnectionError`보다 `TimeoutError`가 먼저 나온다.
