# 과제 2 검증 기록

- 일시: 2026-11-05, Python 3.14.6, Windows 11
- 방법: `teacher_demo.py --no-browser`를 띄우고 `/api/reset`, `/api/mode`로 버튼과 같은 조작을 한 뒤 `python project_sync.py`를 실행했다.
- 재현: 저장소 루트에서 `python docs/verification/run_sync_scenarios.py`, 로그 요약은 `python docs/verification/summarize_log.py <로그 경로>`
- 아래 "AI 실행 증거"는 AI가 스크립트로 실행하고 로그를 대조한 결과다. 학생이 직접 확인한 결과가 아니다.
- 단위 테스트: `python -m unittest tests.test_project tests.test_project_sync` 34개 통과 (과제 2는 15개)

## AI 실행 증거

### 정상: 통과

로그: `logs/project-sync-20261105-150026-301775ea.jsonl`

| 경과(초) | 사건 |
|---|---|
| 0.0333 → 2.1377 | A on 요청 → 완료 |
| 2.1692 → 6.1849 | B on 요청 → 완료 |
| 6.1875 → 8.2515 | A off 요청 → 완료 |
| 8.2643 → 12.2851 | B off 요청 → 완료 |

- 첫 on 요청부터 마지막 off 완료까지 12.2518초
- 12.29초 이후 14.26초까지의 관측은 작업 뒤 추가 감시이며 위 시간에 넣지 않는다.
- `observation` 최대 간격: A 4.047초, B 4.036초
- A의 4.047초는 B off 동안 A 조회가 전혀 없던 공백이다. B의 4.036초는 B 자신의 완료 확인 status 조회만 있고, 그 조회가 `observation`으로 기록되지 않은 공백이다.

### 한쪽 실패: 통과

로그: `logs/project-sync-20261105-150040-f326086a.jsonl`

- 시작 조회에서 A 조회 대기로 A on 요청이 0.5082초에 시작
- A on `job_error`(TimeoutError) 1.0211초
- 뒤이은 조회의 A 대기 뒤 B on 요청 1.5508초, 완료 5.6347초
- `stage_result` ok=false, `sequence_stopped` 6.1437초, off `command_request` 없음
- B `observation` 최대 간격 4.593초

### 복구: 통과

같은 로그. `sequence_stopped` 약 1초 뒤 복구했다. 복구 시점은 로그에 기록되지 않으며, 재현 스크립트의 대기 시간이 출처다.

- A `observation_error` 5건, 마지막 7.3886초
- A 첫 `observation` 7.5934초, 출력 0
- 복구 뒤 `command_request` 없음. `stage_result`의 실패는 그대로이며, 명령 미추가는 단위 테스트 `test_recovery_adds_no_command`로도 확인했다.

### 종료: 일부 확인

- 작업 뒤 조회 지속: 두 로그에서 확인했다.
- 자동 실행은 프로세스를 강제 종료했으므로 두 로그에 `run_end`가 없다. 장치 작업 성공 여부와 무관하다.
- 프로그램 종료와 장치 출력 off는 별개다. 실패 시나리오에서 마지막 관측의 B 출력은 1이었다.
- `KeyboardInterrupt`가 `run` 밖으로 나가는 것은 단위 테스트로만 확인했다.

## 미확인

- 실제 터미널의 Ctrl+C 종료와 그때의 `run_end` 기록

## 학생 직접 확인 체크리스트

- [ ] 브라우저 버튼으로 정상 실행과 로그 확인
- [ ] A 통신 끊기 후 실행, A의 제한 대기가 B 시작과 조회에 주는 영향 확인
- [ ] `sequence_stopped` 뒤 A 통신 복구, 새 관측과 과거 실패 유지 확인
- [ ] 터미널에서 Ctrl+C로 종료, `run_end` 확인
