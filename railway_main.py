#!/usr/bin/env python3
"""Ein Prozess für Railway (oder jeden Container): Webserver + Fetcher-Schleife alle 5 Minuten.
Env: ENOCOO_USER, ENOCOO_PASS, ICS_URL (optional), TAFEL_TOKEN, PORT (von Railway gesetzt)."""
import os, sys, time, threading, subprocess, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
WWW = os.path.join(HERE, "www")
os.makedirs(WWW, exist_ok=True)
shutil.copy(os.path.join(HERE, "index.html"), os.path.join(WWW, "index.html"))
shutil.copy(os.path.join(HERE, "einkauf.js"), os.path.join(WWW, "einkauf.js"))
for f in os.listdir(os.path.join(HERE, "static")):
    shutil.copy(os.path.join(HERE, "static", f), os.path.join(WWW, f))
INTERVAL = int(os.environ.get("FETCH_INTERVAL", "300"))

def fetch_loop():
    while True:
        cmd = [sys.executable, os.path.join(HERE, "enocoo_fetch.py"), "--events", os.path.join(HERE, "termine.json"), "--out", os.path.join(WWW, "data.json.tmp")]
        if os.environ.get("ICS_URL"):
            cmd += ["--ics", os.environ["ICS_URL"]]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                os.replace(os.path.join(WWW, "data.json.tmp"), os.path.join(WWW, "data.json"))
                print(r.stdout.strip(), flush=True)
            else:
                print("fetch failed:", r.stderr.strip()[-500:], flush=True)
        except Exception as e:
            print("fetch error:", e, flush=True)
        time.sleep(INTERVAL)

def einkauf_loop():
    while True:
        try:
            r = subprocess.run([sys.executable, os.path.join(HERE, "einkauf.py"), os.path.join(WWW, "einkauf.json.tmp")], capture_output=True, text=True, timeout=90,
                               env={**os.environ, "EINKAUF_STATE": os.path.join(HERE, "einkauf_state.json")})
            if r.returncode == 0:
                os.replace(os.path.join(WWW, "einkauf.json.tmp"), os.path.join(WWW, "einkauf.json"))
            else:
                print("einkauf failed:", r.stderr.strip()[-300:], flush=True)
        except Exception as e:
            print("einkauf error:", e, flush=True)
        time.sleep(int(os.environ.get("EINKAUF_INTERVAL", "900")))

def mobil_loop():
    state_dir = os.path.dirname(os.environ.get("EINKAUF_STATE", os.path.join(HERE, "einkauf_state.json")))
    while True:
        try:
            r = subprocess.run([sys.executable, os.path.join(HERE, "mobil.py"), os.path.join(WWW, "mobil.json")], capture_output=True, text=True, timeout=120,
                               env={**os.environ, "MOBIL_TOKEN_FILE": os.path.join(state_dir, "mobil_token.json")})
            print((r.stdout or r.stderr).strip()[-300:], flush=True)
        except Exception as e:
            print("mobil error:", e, flush=True)
        time.sleep(int(os.environ.get("MOBIL_INTERVAL", "120")))

threading.Thread(target=fetch_loop, daemon=True).start()
threading.Thread(target=einkauf_loop, daemon=True).start()
threading.Thread(target=mobil_loop, daemon=True).start()
os.environ.setdefault("TAFEL_PORT", os.environ.get("PORT", "8787"))
os.environ["TAFEL_ROOT"] = WWW
os.environ.setdefault("EINKAUF_STATE", os.path.join(HERE, "einkauf_state.json"))
exec(open(os.path.join(HERE, "tafel_server.py")).read())
