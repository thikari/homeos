#!/usr/bin/env python3
"""Holt Live- und Tagesdaten aus dem enocoo-Portal und schreibt data.json für die Energie-Tafel.

Zugangsdaten per Umgebungsvariablen (nie ins Skript schreiben):
    ENOCOO_USER=H12W01_01  ENOCOO_PASS=...  python3 enocoo_fetch.py [--events termine.json] [--ics URL] [--out data.json]

Endpunkte (alle brauchen die PHPSESSID aus dem Login):
    POST /SigninForm.php?mode=ok            user, passwort, idProject=1, idLanguage=1
    GET  /php/getTrafficLightStatus.php     {"color":"rot|gelb|gruen","currentEnergyprice":32.08,...}
    GET  /php/getMeterDataWithParam.php     ?from=YYYY-MM-DD&intVal=Letzte24h|Tag|Monat|Jahr&mClass=Stromverbrauch|Kaltwasser|Warmwasser|Waerme&AreaId=168
    GET  /php/getPVDataDetails.php          ?from=..&to=..&intVal=Letzte24h&diagType=GesamtverbrauchUndErzeugung
                                            → [Siedlungsverbrauch kW, PV kW, Autarkie %, Eigennutzung %, Stunde] je 15 min
"""
import os, sys, json, re, argparse, datetime as dt, urllib.request, urllib.parse, http.cookiejar, ssl

BASE = "https://ems003.enocoo.com:48889"
WX_URL = ("https://api.open-meteo.com/v1/forecast?latitude=49.49&longitude=8.47"
          "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset"
          "&hourly=temperature_2m,weather_code,shortwave_radiation,precipitation_probability"
          "&current=temperature_2m,weather_code&timezone=Europe%2FBerlin&forecast_days=3")

def fetch_weather():
    """Open-Meteo, kein API-Key. Kompaktes Format für die Tafel."""
    try:
        w = json.loads(urllib.request.urlopen(WX_URL, timeout=20).read().decode())
        return {"current": {"time": w["current"]["time"], "temperature_2m": w["current"]["temperature_2m"], "weather_code": w["current"]["weather_code"]},
                "daily": w["daily"],
                "hourly": {"time": w["hourly"]["time"], "t": w["hourly"]["temperature_2m"], "c": w["hourly"]["weather_code"],
                           "r": w["hourly"]["shortwave_radiation"], "p": w["hourly"]["precipitation_probability"]}}
    except Exception as e:
        print("Wetter nicht abrufbar:", e, file=sys.stderr)
        return None
AREA = 168  # H12W01

VRN_STOPS = [("6003053", "Franklin Mitte"), ("6003057", "Franklinschule")]  # VRN-EFA Haltestellen-IDs (Linie 16, Bus 67)

def fetch_departures(stops=VRN_STOPS, limit=8):
    """VRN-EFA (kein Key). Liefert die nächsten Abfahrten mit Echtzeit."""
    out = []
    for sid, label in stops:
        try:
            url = ("https://www.vrn.de/mngvrn/XML_DM_REQUEST?outputFormat=JSON&language=de&stateless=1&type_dm=stop"
                   f"&name_dm={sid}&useRealtime=1&mode=direct&limit=10")
            j = json.loads(urllib.request.urlopen(url, timeout=20).read().decode("utf-8", "ignore"))
            for d in j.get("departureList") or []:
                sl = d.get("servingLine", {})
                t = d.get("realDateTime") or d.get("dateTime") or {}
                plan = d.get("dateTime") or {}
                out.append({"stop": label, "line": str(sl.get("number", "")).replace("RNV ", ""),
                            "dir": str(sl.get("direction", "")).replace("Käfertal, ", "").replace("Mannheim, ", ""),
                            "type": "Tram" if "bahn" in str(sl.get("name", "")).lower() else "Bus",
                            "time": f"{int(t.get('hour', 0)):02d}:{int(t.get('minute', 0)):02d}",
                            "plan": f"{int(plan.get('hour', 0)):02d}:{int(plan.get('minute', 0)):02d}",
                            "countdown": int(d.get("countdown", 0))})
        except Exception as e:
            print("Abfahrten nicht abrufbar:", label, e, file=sys.stderr)
    out.sort(key=lambda x: x["countdown"])
    return out[:limit]

def parse_costs(html):
    """Kostentabelle 'Haushaltsstrom' der Portal-Startseite: Periode | kWh | Kosten € | Ersparnis € | Vergleich %.
    Nur die Stromtabelle hat drei Zahlen vor dem Prozentwert, deshalb reicht das Muster ohne Segmentierung."""
    txt = re.sub(r"<[^>]+>", " ", html).replace("&nbsp;", " ").replace("\xa0", " ")
    txt = re.sub(r"\s+", " ", txt)
    num = lambda v: float(v.replace(".", "").replace(",", "."))
    pat = r"(Heute|Jan|Feb|Mär|Apr|Mai|Jun|Jul|Aug|Sep|Okt|Nov|Dez|20\d\d)\.?\s*:\s*([\d.]+,\d+)\s+([\d.]+,\d+)\s+([\d.]+,\d+)\s+(\d+)\s*%"
    rows = {}
    for m in re.finditer(pat, txt):
        key = "today" if m[1] == "Heute" else ("year" if m[1].startswith("20") else "month")
        rows.setdefault(key, {"kwh": num(m[2]), "eur": num(m[3]), "saved_eur": num(m[4]), "vs_avg_pct": int(m[5])})
    out = {"today": rows.get("today"), "month": rows.get("month"), "year": rows.get("year")}
    if not rows:
        i = txt.find("Heute")
        out["debug"] = txt[max(0, i - 80): i + 220] if i >= 0 else txt[:300]
    return out

def session():
    cj = http.cookiejar.CookieJar()
    ctx = ssl.create_default_context()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj), urllib.request.HTTPSHandler(context=ctx))
    op.addheaders = [("User-Agent", "EnergieTafel/1.0")]
    return op

def login(op):
    user, pw = os.environ.get("ENOCOO_USER"), os.environ.get("ENOCOO_PASS")
    if not user or not pw:
        sys.exit("ENOCOO_USER / ENOCOO_PASS fehlen")
    op.open(BASE + "/", timeout=30)  # Session-Cookie holen
    data = urllib.parse.urlencode({"user": user, "passwort": pw, "idProject": "1", "idLanguage": "1"}).encode()
    r = op.open(BASE + "/SigninForm.php?mode=ok", data=data, timeout=30)
    html = r.read().decode("utf-8", "ignore")
    if "Abgemeldet" in html or ("Anmeldung" in html and "Benutzername" in html):
        sys.exit("Login fehlgeschlagen (Portal zeigt wieder die Anmeldeseite) – Benutzername/Passwort prüfen")

def get_json(op, path, **params):
    params["cache"] = int(dt.datetime.now().timestamp() * 1000)
    r = op.open(BASE + path + "?" + urllib.parse.urlencode(params), timeout=30)
    txt = r.read().decode("utf-8-sig", "ignore").strip().lstrip("\ufeff")
    if "Abgemeldet" in txt or txt.startswith("<"):
        raise RuntimeError("Session abgelaufen bei " + path)
    return json.loads(txt)

def meter(op, mclass, interval, frm):
    data = get_json(op, "/php/getMeterDataWithParam.php", **{"from": frm, "intVal": interval, "mClass": mclass, "AreaId": AREA})
    return data

def read_ics(src, days_ahead=60):
    """Liest einen iCal-Feed (URL oder Datei) inkl. Serienterminen. Nutzt icalendar + recurring_ical_events,
    wenn installiert (pip install icalendar recurring-ical-events), sonst einfacher Parser ohne Serien."""
    if not src:
        return []
    text = urllib.request.urlopen(src).read().decode("utf-8", "ignore") if src.startswith("http") else open(src, encoding="utf-8").read()
    start = dt.date.today(); end = start + dt.timedelta(days=days_ahead)
    try:
        import icalendar, recurring_ical_events
        cal = icalendar.Calendar.from_ical(text)
        ev = []
        for e in recurring_ical_events.of(cal).between(start, end):
            d = e["DTSTART"].dt
            if isinstance(d, dt.datetime):
                if d.tzinfo:
                    d = d.astimezone()  # lokale Zeit
                ev.append({"date": d.date().isoformat(), "time": d.strftime("%H:%M"), "title": str(e.get("SUMMARY", ""))})
            else:
                ev.append({"date": d.isoformat(), "time": None, "title": str(e.get("SUMMARY", ""))})
        return ev
    except ImportError:
        pass
    ev = []
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        s_ = re.search(r"DTSTART[^:]*:(\d{8})(?:T(\d{4}))?", block); t_ = re.search(r"SUMMARY[^:]*:(.*)", block)
        if s_ and t_:
            ev.append({"date": f"{s_[1][:4]}-{s_[1][4:6]}-{s_[1][6:]}", "time": f"{s_[2][:2]}:{s_[2][2:]}" if s_[2] else None, "title": t_[1].strip().replace("\\,", ",")})
    return ev

def fetch_raw(op, today):
    first = today.replace(day=1)
    prev = (first - dt.timedelta(days=1)).replace(day=1)
    raw = {"ampel": get_json(op, "/php/getTrafficLightStatus.php"),
           "l24": meter(op, "Stromverbrauch", "Letzte24h", today.isoformat()),
           "pv": get_json(op, "/php/getPVDataDetails.php", **{"from": today.isoformat(), "to": (today + dt.timedelta(days=1)).isoformat(), "intVal": "Letzte24h", "diagType": "GesamtverbrauchUndErzeugung"}),
           "m_strom": meter(op, "Stromverbrauch", "Monat", first.isoformat()),
           "m_kalt": meter(op, "Kaltwasser", "Monat", first.isoformat()),
           "m_warm": meter(op, "Warmwasser", "Monat", first.isoformat()),
           "m_waerme": meter(op, "Waerme", "Monat", first.isoformat()),
           "m_prev": meter(op, "Stromverbrauch", "Monat", prev.isoformat()),
           "jahr": meter(op, "Stromverbrauch", "Jahr", today.replace(month=1, day=1).isoformat())}
    raw["main_html"] = op.open(BASE + "/php/mainPage.php").read().decode("utf-8", "ignore")
    return raw

def build(raw, now, events, weather=None, departures=None):
    today = now.date()
    kwh15, hours, prices = raw["l24"]
    power_w = round(kwh15[-1] * 4 * 1000) if kwh15 else None
    price_now = prices[-1] if prices else None
    profil = {}
    for h, p in zip(hours, prices):
        profil.setdefault(h, []).append(p)
    price_profile = {str(h): round(sum(v) / len(v) * 100, 1) for h, v in profil.items()}
    # Viertelstundenpreise mit Zeitstempel (letzter Wert = jetzt, 15-min-Raster rückwärts)
    n = len(prices); end = now.replace(second=0, microsecond=0); end = end - dt.timedelta(minutes=end.minute % 15)
    price_24h = [{"t": (end - dt.timedelta(minutes=15 * (n - 1 - i))).isoformat(timespec="minutes"), "ct": round(p * 100, 2), "kwh": kwh15[i]} for i, p in enumerate(prices)]
    pv = raw["pv"]
    month = {"year": today.year, "month": today.month}
    daily = {}
    for key, rk in (("strom_kwh", "m_strom"), ("kaltwasser_m3", "m_kalt"), ("warmwasser_m3", "m_warm"), ("waerme_kwh", "m_waerme")):
        vals = raw[rk][0]
        daily[key] = vals
        month[key] = round(sum(vals), 2)
    month["days_counted"] = len(daily["strom_kwh"])
    strom_days = daily["strom_kwh"]
    allstrom = raw["m_prev"][0] + strom_days
    week = allstrom[-8:-1]
    ampel = raw["ampel"]
    return {
        "updated": now.isoformat(timespec="minutes"),
        "data_until": today.isoformat(),
        "live": {
            "power_w": power_w, "price_ct": round(price_now * 100, 1) if price_now is not None else None,
            "ampel": ampel.get("color"), "ampel_price_ct": ampel.get("currentEnergyprice"),
            "pv_kw": pv[1][-1], "siedlung_kw": pv[0][-1], "autarkie_pct": pv[2][-1],
        },
        "price_profile_ct": price_profile,
        "price_24h": price_24h,
        "month": month,
        "today": {"strom_kwh": round(strom_days[-1], 2) if strom_days else None, "kaltwasser_m3": round(daily["kaltwasser_m3"][-1], 3) if daily["kaltwasser_m3"] else None},
        "yesterday": {"strom_kwh": round(allstrom[-2], 2) if len(allstrom) >= 2 else None, "kaltwasser_m3": round(daily["kaltwasser_m3"][-2], 3) if len(daily["kaltwasser_m3"]) >= 2 else None},
        "week_avg_strom_kwh": round(sum(week) / len(week), 2) if week else None,
        "pv_today_kwh": round(sum(pv[1]) / 4),
        "year_strom_kwh": round(sum(raw["jahr"][0]), 1),
        "events": events,
        "weather": weather,
        "cost": parse_costs(raw["main_html"]) if raw.get("main_html") else None,
        "departures": departures or [],
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data.json"); ap.add_argument("--events"); ap.add_argument("--ics")
    ap.add_argument("--raw", help="Rohdaten-JSON statt Portal-Abruf (zum Testen)")
    ap.add_argument("--weather", help="Wetter-JSON statt Open-Meteo-Abruf (zum Testen)")
    ap.add_argument("--departures", help="Abfahrten-JSON statt VRN-Abruf (zum Testen)")
    ap.add_argument("--now", help="Zeitpunkt der Rohdaten, z. B. 2026-10-16T20:00 (zum Testen)")
    a = ap.parse_args()
    now = dt.datetime.fromisoformat(a.now) if a.now else dt.datetime.now(); today = now.date()
    errors = {}

    raw = None
    try:
        if a.raw:
            raw = json.load(open(a.raw, encoding="utf-8"))
        else:
            op = session(); login(op); raw = fetch_raw(op, today)
    except SystemExit as e:
        errors["portal"] = str(e)
    except Exception as e:
        errors["portal"] = f"{type(e).__name__}: {e}"[:300]

    events = []
    try:
        events = read_ics(a.ics)
    except Exception as e:
        errors["kalender"] = f"{type(e).__name__}: {e}"[:300]
    if a.events:
        try:
            events += json.load(open(a.events, encoding="utf-8"))
        except Exception as e:
            errors["termine"] = f"{type(e).__name__}: {e}"[:300]
    events = sorted([e for e in events if e["date"] >= today.isoformat()], key=lambda e: (e["date"], e.get("time") or ""))[:12]

    try:
        weather = json.load(open(a.weather, encoding="utf-8")) if a.weather else fetch_weather()
        if weather is None:
            errors["wetter"] = "Open-Meteo nicht erreichbar"
    except Exception as e:
        weather = None; errors["wetter"] = f"{type(e).__name__}: {e}"[:300]

    try:
        departures = json.load(open(a.departures, encoding="utf-8")) if a.departures else fetch_departures()
    except Exception as e:
        departures = []; errors["vrn"] = f"{type(e).__name__}: {e}"[:300]

    if raw:
        out = build(raw, now, events, weather, departures)
    else:
        out = {"updated": now.isoformat(timespec="minutes"), "data_until": None, "live": {}, "price_profile_ct": {}, "price_24h": [],
               "month": None, "today": {}, "yesterday": {}, "week_avg_strom_kwh": None, "pv_today_kwh": None, "year_strom_kwh": None,
               "events": events, "weather": weather, "cost": None, "departures": departures}
    out["errors"] = errors
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    l = out.get("live") or {}
    print(f"{a.out}: {l.get('power_w')} W, {l.get('price_ct')} ct, Ampel {l.get('ampel')}, Fehler: {errors or 'keine'}")

if __name__ == "__main__":
    main()
