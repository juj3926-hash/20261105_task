import json,sys
sys.stdout.reconfigure(encoding="utf-8")
for f in sys.argv[1:]:
    ev=[json.loads(l) for l in open(f,encoding="utf-8")]
    print("==",f,len(ev))
    for e in ev:
        if e["type"] not in("observation","observation_error"):
            print(e["elapsed"],e["type"],e["device"],{k:v for k,v in e.items() if k in("command","error","output","reason","ok")})
    for d in "AB":
        o=[e for e in ev if e["device"]==d and e["type"]=="observation"]
        x=[e for e in ev if e["device"]==d and e["type"]=="observation_error"]
        ts=[e["elapsed"] for e in o]
        print(d,"obs",len(o),"err",len(x),"maxgap",round(max(b-a for a,b in zip(ts,ts[1:])),3) if len(ts)>1 else None,
              "first_obs",ts[:1],"last_obs",o[-1:] and (o[-1]["elapsed"],o[-1]["output"]),"last_err",x[-1:] and (x[-1]["elapsed"],x[-1]["error"]))
