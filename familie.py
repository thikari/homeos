#!/usr/bin/env python3
"""Familie für homeOS: Wer holt welches Kind wann ab, Termine mit Zuständigkeit, Schließtage, Mitnehmen-Liste, Erinnerungen.

Daten
- Konfiguration (Mongo `config/familie` oder Datei): kinder[{name, einrichtung, plan{Mo..Fr: {bis, wer}}}], personen, kuerzel {T: Tobi, J: Julia},
  stundenplan {Person: {Mo..So: "von–bis"}}, mitnehmen {Mo..So: ["Noam: Sportbeutel"]}, schliesstage [{von, bis, kind|"", text}], betreuung [{name, tel}]
- Ausnahmen (Mongo `familie_ausnahmen` / Datei): {datum, kind, wer ("Tobi"/"Julia"/"zuhause"/"andere"), bis, text, von, at}
- Terminzuständigkeit (Mongo `familie_termine` / Datei): key "YYYY-MM-DD|Titel" → {wer: "T"|"J"|"TJ"|"offen", betreuung: bool, notiz}
Termine kommen aus dem Familienkalender (ICS_URL, wie die Tafel) – ein Präfix "T:", "J:" oder "TJ:" im Titel setzt die Zuständigkeit automatisch.

Export familie.json: tage (14 Tage aufgelöst: Abholen je Kind), termine (21 Tage mit Zuständigkeit), offen (Hinweise), mitnehmen (morgen), erinnerungen (nächste 24 h).
"""
import os, sys, json, re, datetime as dt, importlib.util, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
def _mod(name):
    sp = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py")); m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m); return m
SPEICHER = _mod("speicher")
STATE = os.environ.get("FAMILIE_STATE", os.path.join(os.path.dirname(os.environ.get("EINKAUF_STATE", HERE + "/x")), "familie_state.json"))
ICS_CACHE = os.path.join(os.path.dirname(STATE) or ".", "familie_ics.json")
MONGO = bool(os.environ.get("MONGODB_URI", "").strip())
WT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

STANDARD = {
    "personen": ["Tobi", "Julia"],
    "kuerzel": {"T": "Tobi", "J": "Julia"},
    "kinder": [
        {"name": "Noam", "einrichtung": "Schule/Hort", "plan": {"Mo": {"bis": "15:00", "wer": "Julia"}, "Di": {"bis": "15:00", "wer": "Julia"}, "Mi": {"bis": "15:00", "wer": "Julia"}, "Do": {"bis": "15:00", "wer": "Julia"}, "Fr": {"bis": "13:00", "wer": "Tobi"}}},
        {"name": "Ella", "einrichtung": "Kita", "plan": {"Mo": {"bis": "14:30", "wer": "Tobi"}, "Di": {"bis": "14:30", "wer": "Tobi"}, "Mi": {"bis": "14:30", "wer": "Tobi"}, "Do": {"bis": "14:30", "wer": "Tobi"}, "Fr": {"bis": "14:30", "wer": "Julia"}}},
    ],
    "stundenplan": {"Tobi": {"Mo": "7:30–13:10", "Di": "7:30–13:10", "Mi": "7:30–13:10", "Do": "7:30–13:10"}, "Julia": {}},
    "mitnehmen": {"Mo": [], "Di": ["Noam: Sportbeutel"], "Mi": [], "Do": ["Ella: Turnbeutel"], "Fr": [], "Sa": [], "So": []},
    "schliesstage": [],
    "betreuung": [],
    "hinweis": "Standardwerte – bitte auf der Handy-Seite unter Einstellungen anpassen.",
}

# ---------------- Speicher ----------------
def _db(): return SPEICHER.db() if MONGO else None
def _file():
    try: return json.load(open(STATE, encoding="utf-8"))
    except Exception: return {}
def _file_save(d):
    os.makedirs(os.path.dirname(STATE) or ".", exist_ok=True); tmp = STATE + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1); os.replace(tmp, STATE)

def config():
    c = None
    if MONGO:
        try:
            doc = _db()["config"].find_one({"_id": "familie"}); c = (doc or {}).get("wert")
        except Exception as e: print("familie config:", e, file=sys.stderr)
    if c is None: c = _file().get("config")
    if not c: return json.loads(json.dumps(STANDARD))
    out = json.loads(json.dumps(STANDARD)); out.update(c); out.pop("hinweis", None) if c.get("kinder") else None
    return out

def config_speichern(c):
    c = {k: v for k, v in c.items() if k != "hinweis"}
    if MONGO:
        try: _db()["config"].replace_one({"_id": "familie"}, {"_id": "familie", "wert": c}, upsert=True); return
        except Exception as e: print("familie config speichern:", e, file=sys.stderr)
    d = _file(); d["config"] = c; _file_save(d)

def ausnahmen():
    if MONGO:
        try: return [{k: v for k, v in a.items() if k != "_id"} for a in _db()["familie_ausnahmen"].find()]
        except Exception as e: print("ausnahmen:", e, file=sys.stderr)
    return _file().get("ausnahmen", [])

def ausnahme_setzen(datum, kind, wer, bis=None, text=None, von=None):
    """wer: Personenname, "zuhause" (krank/frei) oder "" = Ausnahme löschen."""
    dt.date.fromisoformat(datum)
    a = {"datum": datum, "kind": kind, "wer": wer or "", "bis": bis or None, "text": (text or "")[:80], "von": von, "at": dt.datetime.now().isoformat(timespec="minutes")}
    if MONGO:
        try:
            if wer: _db()["familie_ausnahmen"].replace_one({"datum": datum, "kind": kind}, a, upsert=True)
            else: _db()["familie_ausnahmen"].delete_one({"datum": datum, "kind": kind})
            return a
        except Exception as e: print("ausnahme speichern:", e, file=sys.stderr)
    d = _file(); lst = [x for x in d.get("ausnahmen", []) if not (x["datum"] == datum and x["kind"] == kind)]
    if wer: lst.append(a)
    d["ausnahmen"] = lst; _file_save(d); return a

def zuordnungen():
    if MONGO:
        try: return {z["_id"]: {k: v for k, v in z.items() if k != "_id"} for z in _db()["familie_termine"].find()}
        except Exception as e: print("zuordnungen:", e, file=sys.stderr)
    return _file().get("termine", {})

def zuordnung_setzen(key, wer=None, betreuung=None, notiz=None, von=None):
    z = zuordnungen().get(key, {})
    if wer is not None: z["wer"] = wer
    if betreuung is not None: z["betreuung"] = bool(betreuung)
    if notiz is not None: z["notiz"] = notiz[:120]
    z["von"] = von; z["at"] = dt.datetime.now().isoformat(timespec="minutes")
    if MONGO:
        try: _db()["familie_termine"].replace_one({"_id": key}, {"_id": key, **z}, upsert=True); return z
        except Exception as e: print("zuordnung speichern:", e, file=sys.stderr)
    d = _file(); d.setdefault("termine", {})[key] = z; _file_save(d); return z

# ---------------- Kalender ----------------
def kalender(days=28):
    """Termine aus ICS_URL (10 min Cache in familie_ics.json)."""
    try:
        c = json.load(open(ICS_CACHE, encoding="utf-8"))
        if dt.datetime.now().timestamp() - c.get("at", 0) < 600: return c["events"]
    except Exception: c = None
    url = os.environ.get("ICS_URL")
    ev = []
    if url:
        try:
            EF = _mod("enocoo_fetch"); ev = EF.read_ics(url, days_ahead=days)
        except Exception as e:
            print("familie ics:", e, file=sys.stderr)
            if c: return c["events"]
    try:
        tf = os.path.join(HERE, "termine.json")
        ev += [e for e in json.load(open(tf, encoding="utf-8")) if e.get("date")]
    except Exception: pass
    try:
        os.makedirs(os.path.dirname(ICS_CACHE) or ".", exist_ok=True); json.dump({"at": dt.datetime.now().timestamp(), "events": ev}, open(ICS_CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception: pass
    return ev

PRAEFIX = re.compile(r"^\s*(TJ|JT|T|J)\s*[:\-–]\s*", re.I)

def termine(cfg, days=21):
    heute = dt.date.today(); bis = heute + dt.timedelta(days=days); zu = zuordnungen(); out = []
    kurz = {k.upper(): v for k, v in cfg.get("kuerzel", {}).items()}
    for e in kalender():
        if not (heute.isoformat() <= e["date"] <= bis.isoformat()): continue
        titel = e.get("title") or ""; m = PRAEFIX.match(titel)
        key = f"{e['date']}|{titel.strip()}"
        z = zu.get(key, {})
        wer = z.get("wer")
        if not wer and m:
            p = m.group(1).upper(); wer = "TJ" if p in ("TJ", "JT") else p
        kind = next((k["name"] for k in cfg.get("kinder", []) if k["name"].lower() in titel.lower()), None)
        relevant = bool(m) or bool(kind) or any(w in titel.lower() for w in ("eltern", "kita", "schule", "hort", "arzt", "u-unter", "fest", "feier", "geburtstag", "schließ", "ferien"))
        out.append({"key": key, "datum": e["date"], "wt": WT[dt.date.fromisoformat(e["date"]).weekday()], "zeit": e.get("time"), "titel": PRAEFIX.sub("", titel).strip(),
                    "wer": wer or "offen", "wer_name": " + ".join(kurz.get(c, c) for c in (wer or "")) if wer and wer != "offen" else None,
                    "betreuung": bool(z.get("betreuung")), "notiz": z.get("notiz"), "kind": kind, "relevant": relevant, "auto": bool(m) and not z.get("wer")})
    out.sort(key=lambda t: (t["datum"], t["zeit"] or ""))
    return out

# ---------------- Auflösung ----------------
def _schliesst(cfg, datum, kind):
    for s in cfg.get("schliesstage", []):
        if s.get("von", "") <= datum <= (s.get("bis") or s.get("von", "")) and (not s.get("kind") or s["kind"] == kind):
            return s.get("text") or "geschlossen"
    return None

def tag(cfg, d, ausn):
    """Abholen je Kind an einem Tag: Plan + Ausnahme + Schließtag."""
    wt = WT[d.weekday()]; out = []
    for k in cfg.get("kinder", []):
        plan = (k.get("plan") or {}).get(wt)
        a = ausn.get((d.isoformat(), k["name"]))
        zu = _schliesst(cfg, d.isoformat(), k["name"])
        e = {"kind": k["name"], "einrichtung": k.get("einrichtung"), "plan_wer": plan.get("wer") if plan else None, "bis": (a or {}).get("bis") or (plan or {}).get("bis"),
             "wer": None, "status": "frei", "text": None, "ausnahme": bool(a)}
        if a:
            if a["wer"] == "zuhause": e.update(status="zuhause", text=a.get("text") or "zu Hause")
            else: e.update(status="abholen", wer=a["wer"], text=a.get("text") or None)
        elif zu:
            e.update(status="zu", text=zu)
        elif plan:
            e.update(status="abholen", wer=plan.get("wer") or None)
            if not e["wer"]: e["status"] = "offen"
        out.append(e)
    return out

def _hhmm(t):
    try: h, m = t.split(":"); return int(h) * 60 + int(m)
    except Exception: return None

def _konflikt(cfg, person, d, bis):
    """Person hat laut Stundenplan zu dieser Zeit Unterricht/Termin?"""
    sp = (cfg.get("stundenplan") or {}).get(person, {}).get(WT[d.weekday()])
    if not sp or not bis: return None
    m = re.match(r"\s*(\d{1,2}:\d{2})\s*[–-]\s*(\d{1,2}:\d{2})", sp)
    if not m: return None
    von, bis2 = _hhmm(m.group(1)), _hhmm(m.group(2)); t = _hhmm(bis)
    if von is not None and bis2 is not None and t is not None and von <= t < bis2 + 30:
        return f"{person} hat {sp}"
    return None

def export(outp=None, days=14):
    cfg = config(); heute = dt.date.today(); now = dt.datetime.now()
    ausn = {(a["datum"], a["kind"]): a for a in ausnahmen() if a.get("datum", "") >= (heute - dt.timedelta(days=1)).isoformat()}
    tage = []
    for i in range(days):
        d = heute + dt.timedelta(days=i); eintr = tag(cfg, d, ausn)
        for e in eintr:
            if e["status"] == "abholen" and e["wer"]:
                e["konflikt"] = _konflikt(cfg, e["wer"], d, e["bis"])
        tage.append({"datum": d.isoformat(), "wt": WT[d.weekday()], "tag": d.day, "heute": i == 0, "kinder": eintr,
                     "mitnehmen": (cfg.get("mitnehmen") or {}).get(WT[d.weekday()], [])})
    term = termine(cfg)
    offen = []
    for t in tage[:10]:
        for e in t["kinder"]:
            if e["status"] == "offen": offen.append({"datum": t["datum"], "text": f"{e['kind']}: niemand zum Abholen eingetragen", "art": "abholen"})
            if e["status"] == "zu": offen.append({"datum": t["datum"], "text": f"{e['kind']}: {e['text']} – wer hat {e['kind']}?", "art": "zu"})
            if e.get("konflikt"): offen.append({"datum": t["datum"], "text": f"{e['kind']} {e['bis']}: {e['konflikt']}", "art": "konflikt"})
    for t in term:
        if t["relevant"] and t["wer"] == "offen": offen.append({"datum": t["datum"], "text": f"{t['titel']}: Zuständigkeit offen", "art": "termin", "key": t["key"]})
        if t["betreuung"] and t["wer"] == "TJ": offen.append({"datum": t["datum"], "text": f"{t['titel']}: beide dabei – Betreuung fehlt", "art": "betreuung", "key": t["key"]})
    offen.sort(key=lambda o: o["datum"])
    # Erinnerungen der nächsten 24 h (werden vom Server verschickt): 07:00 Tagesübersicht je Person, 30 min vor Abholen
    erinn = []
    for t in tage[:2]:
        d = dt.date.fromisoformat(t["datum"])
        for p in cfg.get("personen", []):
            meine = [f"{e['kind']} {e['bis'] or ''} ({e['einrichtung']})" for e in t["kinder"] if e["status"] == "abholen" and e["wer"] == p]
            tt = [f"{x['zeit'] or ''} {x['titel']}".strip() for x in term if x["datum"] == t["datum"] and x["wer"] in ("TJ", {v: k for k, v in cfg.get('kuerzel', {}).items()}.get(p))]
            if meine or tt:
                erinn.append({"key": f"tag|{t['datum']}|{p}", "at": f"{t['datum']}T07:00", "an": p, "titel": "Heute" if t["heute"] else "Morgen",
                              "text": " · ".join((["Abholen: " + ", ".join(meine)] if meine else []) + (["Termine: " + ", ".join(tt)] if tt else []))})
        for e in t["kinder"]:
            if e["status"] == "abholen" and e["wer"] and e["bis"]:
                hh = _hhmm(e["bis"])
                if hh is not None:
                    at = dt.datetime.combine(d, dt.time(0)) + dt.timedelta(minutes=hh - 30)
                    erinn.append({"key": f"abh|{t['datum']}|{e['kind']}", "at": at.isoformat(timespec="minutes"), "an": e["wer"], "titel": f"{e['kind']} abholen",
                                  "text": f"{e['bis']} {e['einrichtung']}" + (f" – {e['text']}" if e.get("text") else "")})
    out = {"updated": now.isoformat(timespec="minutes"), "kinder": [k["name"] for k in cfg.get("kinder", [])], "personen": cfg.get("personen", []), "kuerzel": cfg.get("kuerzel", {}),
           "hinweis": cfg.get("hinweis"), "tage": tage, "termine": term, "offen": offen, "erinnerungen": erinn, "betreuung": cfg.get("betreuung", []),
           "schliesstage": [s for s in cfg.get("schliesstage", []) if (s.get("bis") or s.get("von", "")) >= heute.isoformat()]}
    if outp:
        tmp = outp + ".tmp"; json.dump(out, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1); os.replace(tmp, outp)
    return out

if __name__ == "__main__":
    export(sys.argv[1] if len(sys.argv) > 1 else "familie.json"); print("ok")
