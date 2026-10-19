#!/usr/bin/env python3
"""Langzeitspeicher in MongoDB (MONGODB_URI). Alles optional: ohne URI sind alle Funktionen No-ops.

Collections (Datenbank aus der URI, sonst "homeos"):
  einkauf          Dokument "liste": aktuelle Einkaufsliste (items, uebernahme, offers)
  einkauf_log      Ereignisse: {at, wer, aktion: dazu|abgehakt|geleert|uebernommen, name, kat, q}   → Einkaufs-Historie
  energie_15min    {t: "YYYY-MM-DDTHH:MM", ct, kwh, solar_pct?}  Strompreis und Verbrauch je Viertelstunde (eindeutig je t)
  energie_tage     {d: "YYYY-MM-DD", strom_kwh, kaltwasser_m3, warmwasser_m3, pv_kwh, grundlast_w}   Tageswerte (eindeutig je d)
  energie_monate   {ym: "YYYY-MM", strom_kwh, kaltwasser_m3, warmwasser_m3, waerme_kwh, kosten_eur, solar_eur, at}   Monatsstand (eindeutig je ym)
  energie_live     {at, power_w, price_ct, ampel, pv_kw, siedlung_kw, autarkie_pct}   ein Punkt je Abruf (5 min)
  mobil_buchungen  {id, start, ende, fahrzeug, kennung, typ, ort, eur, status}   FRANKLIN-Mobil-Buchungen (eindeutig je id)
  mobil_fahrzeuge  {at, id, name, frei, akku}   Verfügbarkeit je Abruf (für „wann ist was frei"-Statistik)
  wetter_tage      {d, tmin, tmax, code, regen_mm}   (eindeutig je d)
"""
import os, sys, datetime as dt

URI = os.environ.get("MONGODB_URI", "").strip()
_db = None

def db():
    global _db
    if not URI:
        return None
    if _db is None:
        from pymongo import MongoClient
        _db = MongoClient(URI, serverSelectionTimeoutMS=8000).get_default_database(default="homeos")
        _indexe()
    return _db

def _indexe():
    from pymongo import ASCENDING
    for col, key in [("energie_15min", "t"), ("energie_tage", "d"), ("energie_monate", "ym"), ("mobil_buchungen", "id"), ("wetter_tage", "d")]:
        _db[col].create_index([(key, ASCENDING)], unique=True)
    _db["einkauf_log"].create_index([("at", ASCENDING)])
    _db["energie_live"].create_index([("at", ASCENDING)])
    _db["mobil_fahrzeuge"].create_index([("at", ASCENDING)])

def aktiv():
    return bool(URI)

def upsert(col, key, docs):
    """docs mit eindeutigem Feld key einfügen/aktualisieren. Liefert Anzahl."""
    d = db()
    if d is None or not docs:
        return 0
    n = 0
    for x in docs:
        if x.get(key) is None:
            continue
        r = d[col].update_one({key: x[key]}, {"$set": x}, upsert=True)
        n += 1 if (r.upserted_id is not None or r.modified_count) else 0
    return n

def insert(col, doc):
    d = db()
    if d is None:
        return
    d[col].insert_one(dict(doc))

def log_einkauf(aktion, wer, name=None, kat=None, q=None):
    try:
        insert("einkauf_log", {"at": dt.datetime.now().isoformat(timespec="seconds"), "wer": wer, "aktion": aktion, "name": name, "kat": kat, "q": q})
    except Exception as e:
        print("einkauf_log:", e, file=sys.stderr)

def archiviere_energie(data):
    """data.json des Fetchers → 15-min-, Tages-, Monats- und Live-Collections."""
    if db() is None or not data:
        return {}
    n = {}
    try:
        n["15min"] = upsert("energie_15min", "t", [{"t": p["t"], "ct": p.get("ct"), "kwh": p.get("kwh")} for p in data.get("price_24h") or [] if p.get("t")])
    except Exception as e:
        print("energie_15min:", e, file=sys.stderr)
    try:
        tage = {}
        for feld, key in [("strom_kwh", "strom_kwh"), ("kaltwasser_m3", "kaltwasser_m3"), ("warmwasser_m3", "warmwasser_m3")]:
            for x in (data.get("daily") or {}).get(key) or []:
                if x.get("d"):
                    tage.setdefault(x["d"], {"d": x["d"]})[feld] = x.get("v")
        heute = data.get("data_until", "")[:10] or dt.date.today().isoformat()
        if heute in tage:
            tage[heute]["pv_kwh"] = data.get("pv_today_kwh"); tage[heute]["grundlast_w"] = data.get("grundlast_w")
        n["tage"] = upsert("energie_tage", "d", list(tage.values()))
    except Exception as e:
        print("energie_tage:", e, file=sys.stderr)
    try:
        m = data.get("month") or {}
        if m.get("year") and m.get("month"):
            c = ((data.get("cost") or {}).get("month")) or {}
            n["monat"] = upsert("energie_monate", "ym", [{"ym": f"{m['year']}-{int(m['month']):02d}", "strom_kwh": m.get("strom_kwh"), "kaltwasser_m3": m.get("kaltwasser_m3"),
                                                          "warmwasser_m3": m.get("warmwasser_m3"), "waerme_kwh": m.get("waerme_kwh"), "tage": m.get("days_counted"),
                                                          "kosten_eur": c.get("eur"), "solar_eur": c.get("saved_eur"), "at": data.get("updated")}])
    except Exception as e:
        print("energie_monate:", e, file=sys.stderr)
    try:
        l = data.get("live") or {}
        if l.get("power_w") is not None:
            insert("energie_live", {"at": data.get("updated"), **{k: l.get(k) for k in ("power_w", "price_ct", "ampel", "pv_kw", "siedlung_kw", "autarkie_pct")}})
    except Exception as e:
        print("energie_live:", e, file=sys.stderr)
    try:
        w = data.get("weather") or {}
        tage = []
        for i, d in enumerate((w.get("daily") or {}).get("time") or []):
            tage.append({"d": d, "tmin": (w["daily"].get("temperature_2m_min") or [None]*9)[i], "tmax": (w["daily"].get("temperature_2m_max") or [None]*9)[i],
                         "code": (w["daily"].get("weather_code") or [None]*9)[i], "regen_mm": (w["daily"].get("precipitation_sum") or [None]*9)[i]})
        n["wetter"] = upsert("wetter_tage", "d", tage)
    except Exception as e:
        print("wetter_tage:", e, file=sys.stderr)
    return n

def archiviere_mobil(mobil, buchungen_roh=None):
    if db() is None or not mobil:
        return {}
    n = {}
    try:
        at = mobil.get("updated")
        for f in (mobil.get("mobil") or {}).get("fahrzeuge") or []:
            insert("mobil_fahrzeuge", {"at": at, "id": f["id"], "name": f.get("name"), "kennung": f.get("kennung"), "frei": f.get("frei"), "akku": f.get("akku")})
        n["fahrzeuge"] = len((mobil.get("mobil") or {}).get("fahrzeuge") or [])
    except Exception as e:
        print("mobil_fahrzeuge:", e, file=sys.stderr)
    try:
        if buchungen_roh:
            n["buchungen"] = upsert("mobil_buchungen", "id", buchungen_roh)
    except Exception as e:
        print("mobil_buchungen:", e, file=sys.stderr)
    return n

if __name__ == "__main__":
    import json
    print("MongoDB:", "aktiv" if aktiv() else "nicht konfiguriert")
    for f in sys.argv[1:]:
        j = json.load(open(f, encoding="utf-8"))
        print(f, archiviere_mobil(j) if "mobil" in j else archiviere_energie(j))
