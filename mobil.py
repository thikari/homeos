#!/usr/bin/env python3
"""Mobil-Tab: VRN-Abfahrten (alle drei Haltestellen) + FRANKLIN Mobil (Carsharing, Cantamen CASIREST).

FRANKLIN Mobil:
  - Fahrzeuge und Verfügbarkeit sind öffentlich (nur X-API-Key der Web-App).
  - Eigene Buchungen brauchen Login: FRANKLIN_LOGIN + FRANKLIN_PASS (Railway-Variablen). Token wird in MOBIL_TOKEN_FILE gecacht.
Aufruf: mobil.py OUT.json   → {updated, departures, mobil:{fahrzeuge, buchungen, login}, errors}
"""
import os, sys, json, base64, datetime as dt, urllib.request, urllib.parse, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://de1.cantamen.de/casirest/v3/"
API_KEY = os.environ.get("FRANKLIN_API_KEY", "f04347c1-f2ad-0b05-fd65-49d5d4d3552b")   # öffentlicher Key der Web-App buchung.franklin-mobil.de
PROV = "117"                                                                              # FRANKLIN Mobil GmbH
LAT, LNG = 49.520325, 8.533892                                                            # Franklin Mitte
STOP_LINKS = {"Franklin Mitte": "https://www.vrn.de/mng/#/XSLT_DM_REQUEST?language=de&type_dm=stop&useRealtime=1&mode=direct&dm=6003053",
              "Franklinschule": "https://www.vrn.de/mng/#/XSLT_DM_REQUEST?language=de&type_dm=stop&useRealtime=1&mode=direct&dm=6003057",
              "Pl. der Freundschaft": "https://www.vrn.de/mng/#/XSLT_DM_REQUEST?language=de&type_dm=stop&useRealtime=1&mode=direct&dm=6002367"}
TOKEN_FILE = os.environ.get("MOBIL_TOKEN_FILE", os.path.join(os.path.dirname(os.environ.get("EINKAUF_STATE", HERE + "/x")), "mobil_token.json"))

def _req(path, token=None, method="GET", body=None):
    h = {"X-API-Key": API_KEY, "Accept": "application/json", "User-Agent": "Mozilla/5.0 (FranklinTafel)"}
    if token:
        h["Authorization"] = "Basic " + base64.b64encode((token + ":").encode()).decode()
    data = None
    if body is not None:
        data = json.dumps(body).encode(); h["Content-Type"] = "application/json"
    r = urllib.request.Request(API + path, data=data, method=method, headers=h)
    with urllib.request.urlopen(r, timeout=25) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8") or "null")

def iso(t): return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")

def fahrzeuge():
    _, bk = _req(f"bookees?expand=bookeeType&expand=bookeeProduct&expand=place&provId={PROV}")
    now = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
    _, props = _req(f"bookingproposals?expand=bookeeId&lat={LAT}&lng={LNG}&range=2500&start={iso(now)}&end={iso(now + dt.timedelta(hours=2))}")
    frei = {p["bookeeId"]: p["timeRange"] for p in props}
    out = []
    for b in bk:
        place = (b.get("place") or {}).get("name", "")
        if "FRANKLIN" not in place.upper() and "George-Washington" not in place:
            continue                                    # Spinelli, Schriesheim, Rheinau ausblenden
        cat = (b.get("bookeeProduct") or {}).get("bookeeCategory", "")
        # Belegte Zeitfenster der nächsten 48 h (öffentlich, ohne Login)
        bloecke = []
        try:
            _, un = _req(f"unavailabilities?bookeeId={b['id']}&start={iso(now)}&end={iso(now + dt.timedelta(hours=48))}")
            for u in (un[0].get("unavailabilityTimeRanges") if un else []) or []:
                tr = u.get("timeRange") or {}
                a, e = _ts(tr.get("start")), _ts(tr.get("end"))
                if a and e and e > now:
                    bloecke.append((max(a, now), e))
        except Exception as ex:
            print("unavailabilities", b["id"], ex, file=sys.stderr)
        bloecke.sort()
        merged = []
        for a, e in bloecke:                            # überlappende Blöcke zusammenfassen
            if merged and a <= merged[-1][1] + dt.timedelta(minutes=1):
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((a, e))
        jetzt_belegt = bool(merged) and merged[0][0] <= now + dt.timedelta(minutes=1)
        out.append({"id": b["id"], "name": b.get("displayName") or b.get("name"), "kennung": b.get("licenseNumber", ""),
                    "typ": "Lastenrad" if cat == "CARGO_BIKE" else "E-Auto", "ort": place.replace(" (FRANKLIN)", ""),
                    "akku": b.get("fuelLevel"), "frei": (b["id"] in frei) and not jetzt_belegt,
                    "belegt": [{"start": a.isoformat(), "ende": e.isoformat()} for a, e in merged[:4]],
                    "link": f"https://buchung.franklin-mobil.de/#/49.5203-8.5339-15-0/bookee/{b['id']}"})
    out.sort(key=lambda x: (x["typ"] != "E-Auto", not x["frei"], x["ort"], x["name"]))
    return out

def _ts(v):
    if not v:
        return None
    v = v.replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(v).astimezone(dt.timezone.utc)
    except ValueError:
        return None

def _load_token():
    try:
        return json.load(open(TOKEN_FILE)).get("id")
    except Exception:
        return None

def login():
    user, pw = os.environ.get("FRANKLIN_LOGIN", "").strip(), os.environ.get("FRANKLIN_PASS", "")
    if not user or not pw:
        return None, "kein Login hinterlegt"
    st, tok = _req("tokens?expand=customerId", method="POST", body={"login": user, "credential": pw, "provId": PROV, "storeLogin": True})
    if st != 201 or not tok.get("id"):
        return None, "Login abgelehnt"
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    json.dump(tok, open(TOKEN_FILE, "w"))
    return tok["id"], None

def buchungen(fz):
    tok = _load_token()
    err = None
    if not tok:
        tok, err = login()
        if not tok:
            return [], err
    now = dt.datetime.now(dt.timezone.utc)
    q = f"bookings?expand=bookee.placeId&expand=bookee&expand=price&start={iso(now - dt.timedelta(days=400))}&end={iso(now + dt.timedelta(days=60))}"
    try:
        _, bs = _req(q, token=tok)
    except urllib.error.HTTPError as e:
        if e.code != 401:
            raise
        tok, err = login()                               # Token abgelaufen → neu anmelden
        if not tok:
            return [], err
        _, bs = _req(q, token=tok)
    byid = {f["id"]: f for f in fz}
    out = []
    kosten = {}                                          # "YYYY-MM" → {"eur": float, "fahrten": n}
    for b in bs or []:
        if (b.get("bookingState") or b.get("state") or "").upper() in ("CANCELLED", "STORNIERT", "CANCELED"):
            continue
        tr0 = b.get("timeRange") or {}
        a0 = _ts(tr0.get("start"))
        if a0 and a0 < now - dt.timedelta(hours=12):      # vergangene Fahrt → nur Kosten zählen
            items = ((b.get("price") or {}).get("priceItems")) or []
            cents = sum(int((it.get("priceIncl") or {}).get("amount") or 0) for it in items)
            k = a0.astimezone().strftime("%Y-%m")
            kosten.setdefault(k, {"eur": 0.0, "fahrten": 0})
            kosten[k]["eur"] += cents / 100; kosten[k]["fahrten"] += 1
            continue
        bk = b.get("bookee") or {}
        f = byid.get(str(b.get("bookeeId") or bk.get("id")), {})
        tr = b.get("timeRange") or {}
        out.append({"start": tr.get("start"), "ende": tr.get("end"),
                    "fahrzeug": f.get("name") or bk.get("displayName") or bk.get("name") or "Fahrzeug",
                    "kennung": f.get("kennung") or bk.get("licenseNumber", ""),
                    "typ": f.get("typ") or ("Lastenrad" if "rad" in (bk.get("licenseNumber", "") + bk.get("name", "")).lower() else "E-Auto"),
                    "ort": f.get("ort") or (bk.get("place") or {}).get("name", ""), "status": b.get("bookingState") or b.get("state")})
    out.sort(key=lambda x: x["start"] or "")
    global KOSTEN
    KOSTEN = [{"monat": k, "eur": round(v["eur"], 2), "fahrten": v["fahrten"]} for k, v in sorted(kosten.items(), reverse=True)][:12]
    return out, None
KOSTEN = []

def main():
    outp = sys.argv[1] if len(sys.argv) > 1 else "mobil.json"
    errors = []
    res = {"updated": dt.datetime.now().isoformat(timespec="minutes"), "departures": [], "stops": STOP_LINKS,
           "mobil": {"fahrzeuge": [], "buchungen": [], "login": bool(os.environ.get("FRANKLIN_LOGIN")), "link": "https://buchung.franklin-mobil.de/#/49.5203-8.5339-15-0/account/bookings"}}
    try:
        spec = importlib.util.spec_from_file_location("enocoo_fetch", os.path.join(HERE, "enocoo_fetch.py")); E = importlib.util.module_from_spec(spec); spec.loader.exec_module(E)
        res["departures"] = E.fetch_departures(limit=60)
    except Exception as e:
        errors.append(f"Abfahrten: {e}")
    fz = []
    try:
        fz = fahrzeuge(); res["mobil"]["fahrzeuge"] = fz
    except Exception as e:
        errors.append(f"FRANKLIN Mobil Fahrzeuge: {e}")
    try:
        bs, err = buchungen(fz); res["mobil"]["buchungen"] = bs; res["mobil"]["kosten"] = KOSTEN
        if err:
            res["mobil"]["login_fehler"] = err
    except Exception as e:
        errors.append(f"FRANKLIN Mobil Buchungen: {e}")
    res["errors"] = errors
    tmp = outp + ".tmp"
    json.dump(res, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1); os.replace(tmp, outp)
    print(f"mobil: {len(res['departures'])} Abfahrten, {len(fz)} Fahrzeuge ({sum(f['frei'] for f in fz)} frei), {len(res['mobil']['buchungen'])} Buchungen" + (f", Fehler: {errors}" if errors else ""))

if __name__ == "__main__":
    main()
