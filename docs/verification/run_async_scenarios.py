import json,subprocess,sys,time,urllib.request,glob,os,signal
def post(p,b):
    r=urllib.request.Request("http://127.0.0.1:8765"+p,json.dumps(b).encode(),{"Content-Type":"application/json"})
    return urllib.request.urlopen(r).read()
def latest(before): return sorted(set(glob.glob("logs/project-*.jsonl"))-before)[-1]
demo=subprocess.Popen([sys.executable,"teacher_demo.py","--no-browser"],stdout=subprocess.DEVNULL)
time.sleep(1.5)
try:
    b=set(glob.glob("logs/*.jsonl")); post("/api/reset",{})
    subprocess.run([sys.executable,"project.py","--seconds","12"],stdout=subprocess.DEVNULL,check=True)
    print("NORMAL",latest(b))
    b=set(glob.glob("logs/*.jsonl")); post("/api/reset",{}); post("/api/mode",{"mode":"silent"})
    p=subprocess.Popen([sys.executable,"project.py","--seconds","10"],stdout=subprocess.DEVNULL)
    time.sleep(1); log=latest(b)
    while '"stage_result"' not in open(log,encoding="utf-8").read(): time.sleep(.05)
    time.sleep(1); post("/api/mode",{"mode":"normal"}); print("RECOVERED_AT_WALL_AFTER_STAGE+1s")
    p.wait(); print("FAIL",log)
    b=set(glob.glob("logs/*.jsonl")); post("/api/reset",{})
    p=subprocess.Popen([sys.executable,"project.py"],stdout=subprocess.DEVNULL,creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    time.sleep(10); p.send_signal(signal.CTRL_BREAK_EVENT)
    try: print("BREAK rc",p.wait(5))
    except subprocess.TimeoutExpired: p.kill(); print("BREAK killed")
    print("END",latest(b))
finally:
    demo.terminate()
