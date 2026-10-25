#!/usr/bin/env python3
"""Haushaltsbuch: Ausgaben aus Kassenzetteln (Foto → Claude liest Laden, Datum, Summe, Posten) oder von Hand.

Speicher: MongoDB-Collection `ausgaben` (über speicher.py) oder Datei HAUSHALT_STATE.
Export (haushalt.json): Monatsübersicht, Kategorien, Läden, Wochen, letzte Belege.
Env: HAUSHALT_BUDGET_EUR (Monatsbudget, Standard 900), ANTHROPIC_API_KEY (Scan), TAFEL_VISION_MODEL.
"""
import os, sys, json, re, uuid, datetime as dt, importlib.util, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
_ll = importlib.util.spec_from_file_location("llm", os.path.join(HERE, "llm.py")); LLM = importlib.util.module_from_spec(_ll); _ll.loader.exec_module(LLM)
_sp = importlib.util.spec_from_file_location("speicher", os.path.join(HERE, "speicher.py")); SPEICHER = importlib.util.module_from_spec(_sp); _sp.loader.exec_module(SPEICHER)
STATE = os.environ.get("HAUSHALT_STATE", os.path.join(os.path.dirname(os.environ.get("EINKAUF_STATE", HERE + "/x")), "haushalt_state.json"))
BUDGET = float(os.environ.get("HAUSHALT_BUDGET_EUR", "900"))
KATEGORIEN = ["Lebensmittel", "Drogerie", "Haushalt", "Kinder", "Mobilität", "Gastro", "Sonstiges"]
LADEN_KAT = {"lidl": "Lebensmittel", "aldi": "Lebensmittel", "rewe": "Lebensmittel", "edeka": "Lebensmittel", "kaufland": "Lebensmittel", "penny": "Lebensmittel", "netto": "Lebensmittel", "scheck": "Lebensmittel",
             "dm": "Drogerie", "rossmann": "Drogerie", "müller": "Drogerie", "apotheke": "Drogerie",
             "ikea": "Haushalt", "obi": "Haushalt", "bauhaus": "Haushalt", "hornbach": "Haushalt", "tedi": "Haushalt", "action": "Haushalt",
             "tankstelle": "Mobilität", "aral": "Mobilität", "shell": "Mobilität", "esso": "Mobilität", "jet": "Mobilität", "rnv": "Mobilität", "vrn": "Mobilität", "db ": "Mobilität", "franklin mobil": "Mobilität",
             "bäcker": "Lebensmittel", "metzger": "Lebensmittel", "markt": "Lebensmittel", "café": "Gastro", "cafe": "Gastro", "restaurant": "Gastro", "pizza": "Gastro", "döner": "Gastro", "eis": "Gastro"}

def kategorie_fuer(laden):
    l = (laden or "").lower()
    for k, v in LADEN_KAT.items():
        if k in l:
            return v
    return "Sonstiges"

# ---------- Speicher ----------
def _col():
    d = SPEICHER.db()
    return d["ausgaben"] if d is not None else None

def load_all():
    c = _col()
    if c is not None:
        try:
            return [dict(x, _id=None) for x in c.find({}, {"_id": 0}).sort("datum", -1).limit(2000)]
        except Exception as e:
            print("ausgaben load:", e, file=sys.stderr)
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return []

def _save_file(rows):
    tmp = STATE + ".tmp"; json.dump(rows, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1); os.replace(tmp, STATE)

def add(entry):
    e = {"id": entry.get("id") or uuid.uuid4().hex[:12], "datum": (entry.get("datum") or dt.date.today().isoformat())[:10], "laden": (entry.get("laden") or "Unbekannt").strip()[:60],
         "summe": round(float(entry.get("summe") or 0), 2), "kategorie": entry.get("kategorie") if entry.get("kategorie") in KATEGORIEN else kategorie_fuer(entry.get("laden")),
         "wer": (entry.get("wer") or "")[:20], "posten": [{"name": str(p.get("name", ""))[:60], "preis": round(float(p.get("preis") or 0), 2), "menge": p.get("menge")} for p in (entry.get("posten") or []) if p.get("name")][:80],
         "quelle": entry.get("quelle") or "manuell", "at": dt.datetime.now().isoformat(timespec="minutes"), "notiz": (entry.get("notiz") or "")[:200]}
    c = _col()
    if c is not None:
        c.update_one({"id": e["id"]}, {"$set": e}, upsert=True)
    else:
        rows = [r for r in load_all() if r.get("id") != e["id"]] + [e]; _save_file(rows)
    return e

def delete(eid):
    c = _col()
    if c is not None:
        return c.delete_one({"id": eid}).deleted_count
    rows = load_all(); n = len(rows); rows = [r for r in rows if r.get("id") != eid]; _save_file(rows); return n - len(rows)

# ---------- Auswertung ----------
def export(outp):
    rows = load_all()
    heute = dt.date.today(); ym = heute.strftime("%Y-%m"); vm = (heute.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")
    monat = [r for r in rows if r["datum"].startswith(ym)]; vormonat = [r for r in rows if r["datum"].startswith(vm)]
    def summe(rs): return round(sum(r["summe"] for r in rs), 2)
    def nach(rs, key, n=8):
        d = {}
        for r in rs:
            d[r.get(key) or "–"] = d.get(r.get(key) or "–", 0) + r["summe"]
        return [{"name": k, "eur": round(v, 2)} for k, v in sorted(d.items(), key=lambda x: -x[1])[:n]]
    # Wochen (letzte 8, Mo–So)
    wochen = []
    mo = heute - dt.timedelta(days=heute.weekday())
    for i in range(7, -1, -1):
        a = mo - dt.timedelta(weeks=i); b = a + dt.timedelta(days=6)
        wochen.append({"von": a.isoformat(), "bis": b.isoformat(), "eur": summe([r for r in rows if a.isoformat() <= r["datum"] <= b.isoformat()])})
    # Monate (letzte 6)
    monate = []
    for i in range(5, -1, -1):
        m = (heute.replace(day=1) - dt.timedelta(days=30 * i)).strftime("%Y-%m")
        monate.append({"ym": m, "eur": summe([r for r in rows if r["datum"].startswith(m)])})
    tage_im_monat = (heute.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    out = {"updated": dt.datetime.now().isoformat(timespec="minutes"), "budget": BUDGET, "kategorien": KATEGORIEN,
           "personen": [x.strip() for x in os.environ.get("EINKAUF_PERSONEN", "Tobi,Julia").split(",") if x.strip()],
           "monat": {"ym": ym, "eur": summe(monat), "belege": len(monat), "tag": heute.day, "tage": tage_im_monat.day,
                     "soll_bis_heute": round(BUDGET * heute.day / tage_im_monat.day, 2), "prognose": round(summe(monat) / heute.day * tage_im_monat.day, 2) if heute.day >= 3 else None,
                     "kategorien": nach(monat, "kategorie"), "laeden": nach(monat, "laden"), "wer": nach(monat, "wer", 4)},
           "vormonat": {"ym": vm, "eur": summe(vormonat), "belege": len(vormonat)},
           "wochen": wochen, "monate": monate,
           "letzte": sorted(rows, key=lambda r: (r["datum"], r.get("at", "")), reverse=True)[:30]}
    tmp = outp + ".tmp"; json.dump(out, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1); os.replace(tmp, outp)
    return out

# ---------- Scan ----------
def scan(b64):
    if not LLM.anbieter():
        return {"error": "Kassenzettel-Scan ist nicht eingerichtet – " + LLM.fehlt() + " Betrag kann von Hand eingetragen werden."}
    if not b64:
        return {"error": "Kein Bild erhalten."}
    prompt = ("Das ist ein Kassenzettel aus Deutschland. Lies ihn sorgfältig und antworte NUR mit einem JSON-Objekt: "
              '{"laden": "Name des Geschäfts kurz (z. B. Lidl, REWE, dm, ALDI)", "datum": "YYYY-MM-DD oder null", "summe": gezahlter Gesamtbetrag als Zahl, '
              '"posten": [{"name": "Artikel kurz", "preis": Zahl, "menge": "z. B. 2x oder 0,5 kg oder null"}], "kategorie": eine von ' + json.dumps(KATEGORIEN, ensure_ascii=False) + '}. '
              "Pfand, Rabatte und Coupons als eigene Posten mit negativem Preis. Dezimalzahlen mit Punkt. Unleserliche Felder null.")
    try:
        text = LLM.frage(prompt, image_b64=b64, max_tokens=1500)
        d = LLM.json_aus(text)
    except Exception as e:
        return {"error": f"Scan fehlgeschlagen: {str(e)[:160]}"}
    if not isinstance(d, dict):
        return {"error": "Beleg nicht lesbar – bitte näher und gerade fotografieren."}
    d["kategorie"] = d.get("kategorie") if d.get("kategorie") in KATEGORIEN else kategorie_fuer(d.get("laden"))
    if not d.get("datum") or not re.match(r"^\d{4}-\d{2}-\d{2}$", str(d["datum"])):
        d["datum"] = dt.date.today().isoformat()
    posten = []
    for p in d.get("posten") or []:
        try:
            posten.append({"name": str(p.get("name", "")).strip()[:60], "preis": round(float(str(p.get("preis", 0)).replace(",", ".")), 2), "menge": p.get("menge")})
        except Exception:
            pass
    d["posten"] = [p for p in posten if p["name"]]
    try:
        d["summe"] = round(float(str(d.get("summe") or sum(p["preis"] for p in d["posten"])).replace(",", ".")), 2)
    except Exception:
        d["summe"] = round(sum(p["preis"] for p in d["posten"]), 2)
    d["quelle"] = "scan"
    return d

if __name__ == "__main__":
    out = export(sys.argv[1] if len(sys.argv) > 1 else "haushalt.json")
    print(f"haushalt: {out['monat']['belege']} Belege, {out['monat']['eur']} € im {out['monat']['ym']}")
