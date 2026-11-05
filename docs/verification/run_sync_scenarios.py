"""과제 2 시나리오 재현. 저장소 루트에서 실행한다.

동기판에는 시간 제한이 없어 끝에 프로세스를 강제 종료한다. 그래서 로그에 run_end가 남지 않는다.
"""
import glob
import json
import subprocess
import sys
import time
import urllib.request


def post(path, body):
    request = urllib.request.Request("http://127.0.0.1:8765" + path, json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
    urllib.request.urlopen(request).read()


def start():
    before = set(glob.glob("logs/*.jsonl"))
    process = subprocess.Popen([sys.executable, "project_sync.py"], stdout=subprocess.DEVNULL)
    while not set(glob.glob("logs/*.jsonl")) - before:
        time.sleep(0.05)
    return process, sorted(set(glob.glob("logs/*.jsonl")) - before)[-1]


def wait_for(log, text, limit=40):
    deadline = time.monotonic() + limit
    while text not in open(log, encoding="utf-8").read():
        if time.monotonic() > deadline:
            raise TimeoutError(text)
        time.sleep(0.05)


demo = subprocess.Popen([sys.executable, "teacher_demo.py", "--no-browser"], stdout=subprocess.DEVNULL)
time.sleep(1.5)
try:
    post("/api/reset", {})
    process, log = start()
    wait_for(log, '"command": "off", "ok"')
    time.sleep(2)
    process.kill()
    process.wait()
    print("NORMAL", log)

    post("/api/reset", {})
    post("/api/mode", {"mode": "silent"})
    process, log = start()
    wait_for(log, '"sequence_stopped"')
    time.sleep(1)
    post("/api/mode", {"mode": "normal"})
    time.sleep(2)
    process.kill()
    process.wait()
    print("FAIL", log)
finally:
    demo.terminate()
