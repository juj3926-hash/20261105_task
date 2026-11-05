# PLC D01000 감시와 값 변경

`plc_project.py`는 비동기판, `plc_project_sync.py`는 동기판이다. 요구사항은 `TASKS_2.md`에 있다.

## 실행 전 확인

- [ ] 강사가 D01000을 사용하지 않는 테스트 워드로 확인했다.
- [ ] 시험 둘 전에 강사가 독립 실습선에 국번 2 장치가 없음을 확인했다.
- [ ] COM 번호, 데이터 비트, 패리티, 정지 비트를 실제 값으로 확인했다.
- [ ] QModMaster 연결을 해제했다.
- [ ] 두 프로그램을 동시에 실행하지 않는다.

## 실행

이 폴더의 터미널에서 실행한다. 아래의 꺾쇠 값은 확인한 실제 값으로 바꾼다.

```text
python plc_project.py --port <COM> --bytesize <7|8> --parity <N|E|O> --stopbits <1|2>
python plc_project_sync.py --port <COM> --bytesize <7|8> --parity <N|E|O> --stopbits <1|2>
```

기본값은 통신 속도 9600, 국번 1, timeout 2초, retries 0, 감시 주기 1초다. 비교할 때는 두 프로그램에 같은 값을 쓴다.

## 명령

입력한 글자는 화면에 보이지 않는다. 명령을 입력하고 Enter를 누르면 프로그램이 처리한 시점에 `input_received`가 표시된다.

| 명령 | 동작 |
|---|---|
| `write <값>` | 값 변경 요청 (0~65535) |
| `unit <국번>` | 요청 대상 국번 변경 (1~247). 실행 중 적용 |
| `status` | 마지막 정상 값·시각, 현재 오류, 국번, 대기 요청 수 표시 |
| `quit` | 프로그램 종료, COM 포트 해제 |

Ctrl+C로도 종료할 수 있다. 프로그램 종료는 PLC 값을 바꾸지 않는다.

## 기록

터미널과 `logs/`의 JSONL에 사건을 남긴다. `request_accepted`는 접수, `write_result`는 쓰기 응답, `observation`은 실제 읽은 값, `write_confirmed`는 쓰기 뒤 재조회 일치다.
