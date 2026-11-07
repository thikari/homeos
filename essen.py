#!/usr/bin/env python3
"""Essensplan für homeOS: sieben Tage (Mo–So), Rezepte mit Zutaten, ein Tipp → Zutaten auf die Einkaufsliste.

Speicher: MongoDB (Collections `essensplan` je ISO-Woche, `rezepte`) oder Datei neben EINKAUF_STATE.
Aufruf als Skript: `python3 essen.py <ausgabe.json>` schreibt den Export (diese + nächste Woche, Rezeptnamen).
Vorschlag für leere Tage: KI (llm.py) mit der eigenen Rezeptliste, sonst Rotation der am längsten nicht gekochten Rezepte.
"""
import os, sys, json, re, datetime as dt, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
def _mod(name):
    sp = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py")); m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m); return m
SPEICHER = _mod("speicher"); LLM = _mod("llm")

STATE = os.environ.get("ESSEN_STATE", os.path.join(os.path.dirname(os.environ.get("EINKAUF_STATE", HERE + "/x")), "essen_state.json"))
MONGO = bool(os.environ.get("MONGODB_URI", "").strip())
WT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

# Familientaugliche Startrezepte (werden durch eigene gleichen Namens überschrieben)
STANDARD = [
    ("Spaghetti Bolognese", ["Spaghetti", "Hackfleisch", "Passierte Tomaten", "Zwiebeln", "Karotten", "Parmesan"], "schnell"),
    ("Nudeln mit Tomatensoße", ["Nudeln", "Passierte Tomaten", "Zwiebeln", "Knoblauch", "Parmesan", "Basilikum"], "schnell,vegetarisch"),
    ("Pfannkuchen", ["Mehl", "Eier", "Milch", "Apfelmus", "Zucker"], "schnell,vegetarisch,süß"),
    ("Kartoffelsuppe", ["Kartoffeln", "Karotten", "Lauch", "Sellerie", "Gemüsebrühe", "Sahne", "Würstchen"], "suppe"),
    ("Hähnchen-Curry mit Reis", ["Hähnchenbrust", "Reis", "Kokosmilch", "Currypaste", "Paprika", "Zwiebeln"], ""),
    ("Gemüse-Reispfanne", ["Reis", "Paprika", "Zucchini", "Mais", "Erbsen", "Eier", "Sojasoße"], "vegetarisch,reste"),
    ("Ofengemüse mit Feta", ["Kartoffeln", "Süßkartoffeln", "Paprika", "Zucchini", "Feta", "Olivenöl"], "vegetarisch"),
    ("Lachs mit Kartoffeln und Brokkoli", ["Lachsfilet", "Kartoffeln", "Brokkoli", "Zitrone", "Butter"], "fisch"),
    ("Pizza selbstgemacht", ["Mehl", "Hefe", "Passierte Tomaten", "Mozzarella", "Salami", "Paprika"], "freitag"),
    ("Flammkuchen", ["Flammkuchenteig", "Schmand", "Speck", "Zwiebeln", "Lauch"], "schnell"),
    ("Linsensuppe", ["Rote Linsen", "Karotten", "Kartoffeln", "Zwiebeln", "Gemüsebrühe", "Essig", "Würstchen"], "suppe"),
    ("Chili sin Carne", ["Kidneybohnen", "Mais", "Gehackte Tomaten", "Zwiebeln", "Paprika", "Reis", "Schmand"], "vegetarisch"),
    ("Käsespätzle", ["Spätzle", "Bergkäse", "Zwiebeln", "Butter", "Salat"], "vegetarisch"),
    ("Fischstäbchen mit Kartoffelpüree", ["Fischstäbchen", "Kartoffeln", "Milch", "Butter", "Erbsen"], "schnell,kinder"),
    ("Wraps mit Hähnchen", ["Tortilla-Wraps", "Hähnchenbrust", "Salat", "Tomaten", "Mais", "Sauerrahm", "Käse"], "schnell"),
    ("Gnocchi-Pfanne", ["Gnocchi", "Kirschtomaten", "Zucchini", "Mozzarella", "Pesto"], "schnell,vegetarisch"),
    ("Kartoffelgratin mit Salat", ["Kartoffeln", "Sahne", "Milch", "Käse", "Knoblauch", "Salat", "Gurke"], "vegetarisch"),
    ("Couscous-Salat", ["Couscous", "Gurke", "Tomaten", "Paprika", "Feta", "Zitrone", "Minze"], "schnell,vegetarisch,kalt"),
    ("Hackbällchen mit Reis", ["Hackfleisch", "Reis", "Eier", "Semmelbrösel", "Passierte Tomaten", "Zwiebeln"], ""),
    ("Tomatensuppe mit Brot", ["Gehackte Tomaten", "Zwiebeln", "Sahne", "Gemüsebrühe", "Baguette", "Käse"], "suppe,schnell,vegetarisch"),
    ("Asia-Nudeln", ["Mie-Nudeln", "Paprika", "Karotten", "Zuckerschoten", "Sojasoße", "Eier", "Sesamöl"], "schnell,vegetarisch"),
    ("Schnitzel mit Pommes", ["Schnitzel", "Pommes", "Eier", "Semmelbrösel", "Zitrone", "Gurke"], "kinder"),
    ("Milchreis mit Kirschen", ["Milchreis", "Milch", "Zucker", "Sauerkirschen", "Zimt"], "schnell,vegetarisch,süß"),
    ("Quiche mit Lauch", ["Blätterteig", "Lauch", "Eier", "Sahne", "Käse", "Speck"], "vegetarisch-option"),
    ("Reste-Tag", [], "reste"),
    ("Brotzeit", ["Brot", "Käse", "Wurst", "Gurke", "Tomaten", "Paprika"], "schnell,kalt"),
]

def slug(name):
    s = re.sub(r"[^a-z0-9äöüß]+", "-", name.strip().lower()).strip("-")
    return s[:60] or "x"

# ---------------- Speicher ----------------
def _db():
    return SPEICHER.db() if MONGO else None

def _file():
    try: return json.load(open(STATE, encoding="utf-8"))
    except Exception: return {"wochen": {}, "rezepte": {}}

def _file_save(d):
    os.makedirs(os.path.dirname(STATE) or ".", exist_ok=True)
    tmp = STATE + ".tmp"; json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1); os.replace(tmp, STATE)

def woche_key(d):
    y, w, _ = d.isocalendar(); return f"{y}-W{w:02d}"

def tage(d):
    mo = d - dt.timedelta(days=d.weekday()); return [mo + dt.timedelta(days=i) for i in range(7)]

def plan_laden(wk):
    if MONGO:
        try:
            doc = _db()["essensplan"].find_one({"_id": wk}) or {}
            return doc.get("tage") or {}
        except Exception as e: print("essensplan laden:", e, file=sys.stderr)
    return _file().get("wochen", {}).get(wk, {})

def plan_speichern(wk, tage_):
    if MONGO:
        try:
            _db()["essensplan"].replace_one({"_id": wk}, {"_id": wk, "tage": tage_, "updated": dt.datetime.now().isoformat(timespec="minutes")}, upsert=True); return
        except Exception as e: print("essensplan speichern:", e, file=sys.stderr)
    d = _file(); d.setdefault("wochen", {})[wk] = tage_; _file_save(d)

def eigene_rezepte():
    if MONGO:
        try:
            return {r["_id"]: {k: v for k, v in r.items() if k != "_id"} for r in _db()["rezepte"].find()}
        except Exception as e: print("rezepte laden:", e, file=sys.stderr)
    return _file().get("rezepte", {})

def rezepte():
    """Alle Rezepte als Liste {id, name, zutaten, tags, eigen, zuletzt, anzahl}; eigene überschreiben Standard gleichen Namens."""
    out = {slug(n): {"id": slug(n), "name": n, "zutaten": z, "tags": [t for t in tg.split(",") if t], "eigen": False} for n, z, tg in STANDARD}
    for rid, r in eigene_rezepte().items():
        out[rid] = {"id": rid, "name": r.get("name", rid), "zutaten": r.get("zutaten") or [], "tags": r.get("tags") or [], "eigen": not r.get("standard", False),
                    "zuletzt": r.get("zuletzt"), "anzahl": r.get("anzahl", 0), "versteckt": r.get("versteckt", False)}
    return sorted([r for r in out.values() if not r.get("versteckt")], key=lambda r: r["name"].lower())

def rezept_speichern(name, zutaten, tags=None):
    name = name.strip()[:80]
    if not name: raise ValueError("Name fehlt")
    rid = slug(name)
    zut = [z.strip() for z in (zutaten if isinstance(zutaten, list) else re.split(r"[,\n;]+", zutaten or "")) if z.strip()][:40]
    doc = {"name": name, "zutaten": zut, "tags": tags or [], "geaendert": dt.datetime.now().isoformat(timespec="minutes")}
    alt = eigene_rezepte().get(rid) or {}
    doc["zuletzt"], doc["anzahl"] = alt.get("zuletzt"), alt.get("anzahl", 0)
    if MONGO:
        try: _db()["rezepte"].replace_one({"_id": rid}, {"_id": rid, **doc}, upsert=True); return rid
        except Exception as e: print("rezept speichern:", e, file=sys.stderr)
    d = _file(); d.setdefault("rezepte", {})[rid] = doc; _file_save(d); return rid

def rezept_entfernen(rid):
    """Eigenes Rezept löschen; Standardrezept nur ausblenden."""
    ist_standard = rid in {slug(n) for n, _, _ in STANDARD}
    if MONGO:
        try:
            if ist_standard: _db()["rezepte"].update_one({"_id": rid}, {"$set": {"versteckt": True, "standard": True}, "$setOnInsert": {"name": rid}}, upsert=True)
            else: _db()["rezepte"].delete_one({"_id": rid})
            return
        except Exception as e: print("rezept löschen:", e, file=sys.stderr)
    d = _file()
    if ist_standard: d.setdefault("rezepte", {})[rid] = {"name": rid, "versteckt": True, "standard": True}
    else: d.get("rezepte", {}).pop(rid, None)
    _file_save(d)

def _gekocht(rid, datum):
    """Merkt sich, wann ein Rezept zuletzt geplant wurde (für die Rotation)."""
    r = eigene_rezepte().get(rid)
    std = {slug(n): (n, z, tg) for n, z, tg in STANDARD}
    if r is None and rid in std:
        n, z, tg = std[rid]; r = {"name": n, "zutaten": z, "tags": [t for t in tg.split(",") if t], "standard": True}
    if r is None: return
    r["zuletzt"] = max(r.get("zuletzt") or "", datum); r["anzahl"] = int(r.get("anzahl", 0)) + 1
    if MONGO:
        try: _db()["rezepte"].replace_one({"_id": rid}, {"_id": rid, **r}, upsert=True); return
        except Exception as e: print("rezept merken:", e, file=sys.stderr)
    d = _file(); d.setdefault("rezepte", {})[rid] = r; _file_save(d)

# ---------------- Plan ----------------
def setze(datum, gericht, wer=None):
    """Gericht für einen Tag setzen (leer = löschen). Passt der Name zu einem Rezept, wird es verknüpft."""
    d = dt.date.fromisoformat(datum); wk = woche_key(d); t = plan_laden(wk)
    gericht = (gericht or "").strip()[:80]
    if not gericht:
        t.pop(datum, None); plan_speichern(wk, t); return None
    rez = {r["name"].lower(): r for r in rezepte()}
    r = rez.get(gericht.lower())
    eintrag = {"gericht": r["name"] if r else gericht, "rezept": r["id"] if r else None, "wer": wer, "at": dt.datetime.now().isoformat(timespec="minutes")}
    if t.get(datum, {}).get("rezept") != eintrag["rezept"] and r:
        _gekocht(r["id"], datum)
    t[datum] = eintrag; plan_speichern(wk, t); return eintrag

def plan(d=None):
    d = d or dt.date.today(); wk = woche_key(d); t = plan_laden(wk); rz = {r["id"]: r for r in rezepte()}
    out = []
    for x in tage(d):
        e = t.get(x.isoformat()) or {}
        r = rz.get(e.get("rezept")) if e.get("rezept") else None
        out.append({"datum": x.isoformat(), "wt": WT[x.weekday()], "tag": x.day, "gericht": e.get("gericht"), "rezept": e.get("rezept"),
                    "zutaten": (r or {}).get("zutaten", []), "heute": x == dt.date.today(), "vorbei": x < dt.date.today()})
    return {"woche": wk, "von": out[0]["datum"], "bis": out[-1]["datum"], "tage": out}

def zutaten(datum=None, woche=None, ab_heute=True):
    """Zutaten eines Tages oder einer Woche (ohne Doppelte)."""
    out, seen = [], set()
    if datum:
        tg = [t for t in plan(dt.date.fromisoformat(datum))["tage"] if t["datum"] == datum]
    else:
        d = dt.date.fromisoformat(woche) if woche else dt.date.today()
        tg = [t for t in plan(d)["tage"] if not (ab_heute and t["vorbei"])]
    for t in tg:
        for z in t["zutaten"]:
            if z.lower() not in seen:
                seen.add(z.lower()); out.append(z)
    return out

def vorschlag(d=None):
    """Leere Tage der Woche füllen: KI mit eigener Rezeptliste, sonst Rotation (am längsten nicht geplant zuerst)."""
    d = d or dt.date.today(); p = plan(d); rz = rezepte()
    leer = [t for t in p["tage"] if not t["gericht"] and not t["vorbei"]]
    if not leer: return []
    belegt = {t["rezept"] for t in p["tage"] if t.get("rezept")}
    kandidaten = [r for r in rz if r["id"] not in belegt and "reste" not in r["tags"]]
    kandidaten.sort(key=lambda r: (r.get("zuletzt") or "", r.get("anzahl", 0)))
    gewaehlt = None
    if LLM.anbieter() and kandidaten:
        try:
            prompt = ("Du planst Abendessen für eine Familie mit drei Kindern (7, 5 Jahre, Baby). Wähle für die freien Tage je ein Gericht aus dieser Liste, "
                      "abwechslungsreich (nicht zweimal Nudeln hintereinander, höchstens einmal Fisch, Freitag gern Pizza/Flammkuchen, Sonntag etwas Aufwendigeres, "
                      "unter der Woche schnelle Gerichte). Antworte nur als JSON {\"<datum>\": \"<Gerichtname exakt aus der Liste>\"}.\n"
                      f"Freie Tage: {', '.join(t['datum'] + ' (' + t['wt'] + ')' for t in leer)}\n"
                      f"Schon geplant: {', '.join(t['gericht'] for t in p['tage'] if t['gericht']) or '–'}\n"
                      "Liste (zuletzt gekocht): " + "; ".join(f"{r['name']} ({r.get('zuletzt') or 'nie'})" for r in kandidaten[:40]))
            j = LLM.json_aus(LLM.frage(prompt, max_tokens=400))
            if isinstance(j, dict):
                namen = {r["name"].lower(): r["name"] for r in kandidaten}
                gewaehlt = {k: namen[v.strip().lower()] for k, v in j.items() if isinstance(v, str) and v.strip().lower() in namen}
        except Exception as e:
            print("essen vorschlag KI:", e, file=sys.stderr)
    if not gewaehlt and kandidaten:
        import random
        rnd = random.Random(p["woche"]); gewaehlt = {}; rest = list(kandidaten); rnd.shuffle(rest)
        rest.sort(key=lambda r: (r.get("zuletzt") or ""))                  # am längsten nicht geplant zuerst, dazwischen zufällig
        def passt(r, t):
            tg = set(r["tags"])
            if t["wt"] == "Fr": return "freitag" in tg
            if t["wt"] in ("Sa", "So"): return "schnell" not in tg
            return "schnell" in tg or "suppe" in tg
        for t in leer:
            r = next((r for r in rest if passt(r, t)), None) or (rest[0] if rest else None)
            if r: rest.remove(r); gewaehlt[t["datum"]] = r["name"]
    out = []
    for t in leer:
        if t["datum"] in gewaehlt:
            setze(t["datum"], gewaehlt[t["datum"]], wer="Vorschlag"); out.append({"datum": t["datum"], "gericht": gewaehlt[t["datum"]]})
    return out

def export(outp):
    heute = dt.date.today()
    out = {"heute": heute.isoformat(), "diese": plan(heute), "naechste": plan(heute + dt.timedelta(days=7)),
           "rezepte": [{"id": r["id"], "name": r["name"], "zutaten": r["zutaten"], "tags": r["tags"], "eigen": r["eigen"], "zuletzt": r.get("zuletzt")} for r in rezepte()],
           "ki": bool(LLM.anbieter()), "updated": dt.datetime.now().isoformat(timespec="minutes")}
    tmp = outp + ".tmp"; json.dump(out, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1); os.replace(tmp, outp)
    return out

if __name__ == "__main__":
    export(sys.argv[1] if len(sys.argv) > 1 else "essen.json"); print("ok")
