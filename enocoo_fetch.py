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

VRN_STOPS = [("6003053", "Franklin Mitte"), ("6003057", "Franklinschule"), ("6002367", "Pl. der Freundschaft")]  # VRN-EFA Haltestellen-IDs (Linie 16/5, Bus 67/41)

def fetch_departures(stops=VRN_STOPS, limit=14):
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
                            "dir": str(sl.get("direction", "")).replace("Käfertal, ", "").replace("Mannheim, ", "").replace("Ma Hbf - Heidelberg", "Hbf · Heidelberg"),
                            "type": "Tram" if "bahn" in str(sl.get("name", "")).lower() else "Bus",
                            "time": f"{int(t.get('hour', 0)):02d}:{int(t.get('minute', 0)):02d}",
                            "plan": f"{int(plan.get('hour', 0)):02d}:{int(plan.get('minute', 0)):02d}",
                            "countdown": int(d.get("countdown", 0))})
        except Exception as e:
            print("Abfahrten nicht abrufbar:", label, e, file=sys.stderr)
    out.sort(key=lambda x: x["countdown"])
    return out[:limit]

def parse_start(html):
    """Alle vier Tabellen der Startseite des neuen Portals (Haushaltsstrom, Heizung, Warmwasser, Kaltwasser) →
    {"strom": {"today": {...}, "month": {...}, "year": {...}}, "heizung": …, "warmwasser": …, "kaltwasser": …}
    Strom: kwh, eur, saved_eur, vs_avg_pct; Heizung: kwh, vs_avg_pct; Wasser: m3, vs_avg_pct."""
    txt = re.sub(r"<[^>]+>", " ", html).replace("&nbsp;", " ").replace("\xa0", " ").replace("&sup1;", "").replace("&sup2;", "").replace("&sup3;", "")
    txt = re.sub(r"\s+", " ", txt)
    num = lambda v: float(v.replace(".", "").replace(",", "."))
    out = {}
    abschnitte = [("strom", "Haushaltsstrom", "Heizung"), ("heizung", "Heizung", "Warmwasser"), ("warmwasser", "Warmwasser", "Kaltwasser"), ("kaltwasser", "Kaltwasser", None)]
    for key, start, ende in abschnitte:
        i = txt.find(start + " Periode")
        if i < 0: continue
        j = txt.find(ende + " Periode", i + 1) if ende else -1
        seg = txt[i: j if j > 0 else i + 1500]
        rows = {}
        for m in re.finditer(r"(Heute|Jan|Feb|Mär|Apr|Mai|Jun|Jul|Aug|Sep|Okt|Nov|Dez|20\d\d)\.?\s*:\s*((?:-?[\d.]+,\d+\s+)+)(-?\d+)\s*%", seg):
            zahlen = [num(z) for z in m[2].split()]
            per = "today" if m[1] == "Heute" else ("year" if m[1].startswith("20") else "month")
            if key == "strom" and len(zahlen) >= 3:
                rows[per] = {"kwh": zahlen[0], "eur": zahlen[1], "saved_eur": zahlen[2], "vs_avg_pct": int(m[3])}
            elif key == "heizung":
                rows[per] = {"kwh": zahlen[0], "vs_avg_pct": int(m[3])}
            else:
                rows[per] = {"m3": zahlen[0], "vs_avg_pct": int(m[3])}
        if rows: out[key] = rows
    return out

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
    op.addheaders = [("User-Agent", os.environ.get("ENOCOO_UA", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")), ("Accept-Language", "de-DE,de;q=0.9")]
    return op

def login(op):
    """Anmeldung: neues Portal (/anmelden mit CSRF-Token, seit Nov. 2026); fällt auf das alte SigninForm.php zurück."""
    user, pw = os.environ.get("ENOCOO_USER"), os.environ.get("ENOCOO_PASS")
    if not user or not pw:
        sys.exit("ENOCOO_USER / ENOCOO_PASS fehlen")
    try:
        url, html = login_neu(op)
        if "/anmelden" in url and 'name="passwort"' in html:
            sys.exit("Login fehlgeschlagen (Portal zeigt wieder die Anmeldeseite) – Benutzername/Passwort prüfen")
        op.open(BASE + "/start", timeout=30).read()   # Session initialisieren (Meta-Refresh der Anmeldeantwort)
        return "neu"
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    op.open(BASE + "/", timeout=30)  # Session-Cookie holen
    data = urllib.parse.urlencode({"user": user, "passwort": pw, "idProject": "1", "idLanguage": "1"}).encode()
    r = op.open(BASE + "/SigninForm.php?mode=ok", data=data, timeout=30)
    html = r.read().decode("utf-8", "ignore")
    if "Abgemeldet" in html or ("Anmeldung" in html and "Benutzername" in html):
        sys.exit("Login fehlgeschlagen (Portal zeigt wieder die Anmeldeseite) – Benutzername/Passwort prüfen")
    return "alt"

PFADE = {"neu": {"ampel": "/api/ampel", "zaehler": "/api/zaehlerdaten", "pv": "/api/pv-details", "start": "/start"},
         "alt": {"ampel": "/php/getTrafficLightStatus.php", "zaehler": "/php/getMeterDataWithParam.php", "pv": "/php/getPVDataDetails.php", "start": "/php/mainPage.php"}}
PORTAL = "neu"

def get_json(op, path, **params):
    params = {"cache": int(dt.datetime.now().timestamp() * 1000), **params}
    req = urllib.request.Request(BASE + path + "?" + urllib.parse.urlencode(params), headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/javascript, */*; q=0.01"})
    r = op.open(req, timeout=30)
    txt = r.read().decode("utf-8-sig", "ignore").strip().lstrip("\ufeff")
    if "Abgemeldet" in txt or txt.startswith("<"):
        raise RuntimeError("Session abgelaufen bei " + path)
    return json.loads(txt)

def meter(op, mclass, interval, frm):
    data = get_json(op, PFADE[PORTAL]["zaehler"], **{"from": frm, "intVal": interval, "mClass": mclass, "AreaId": AREA})
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
    raw = {"ampel": get_json(op, PFADE[PORTAL]["ampel"]),
           "l24": meter(op, "Stromverbrauch", "Letzte24h", today.isoformat()),
           "pv": get_json(op, PFADE[PORTAL]["pv"], **{"from": today.isoformat(), "to": (today + dt.timedelta(days=1)).isoformat(), "intVal": "Letzte24h", "diagType": "GesamtverbrauchUndErzeugung"}),
           "m_strom": meter(op, "Stromverbrauch", "Monat", first.isoformat()),
           "m_kalt": meter(op, "Kaltwasser", "Monat", first.isoformat()),
           "m_warm": meter(op, "Warmwasser", "Monat", first.isoformat()),
           "m_waerme": meter(op, "Waerme", "Monat", first.isoformat()),
           "m_prev": meter(op, "Stromverbrauch", "Monat", prev.isoformat()),
           "w24_kalt": meter(op, "Kaltwasser", "Letzte24h", today.isoformat()),
           "w24_warm": meter(op, "Warmwasser", "Letzte24h", today.isoformat()),
           "jahr": meter(op, "Stromverbrauch", "Jahr", today.replace(month=1, day=1).isoformat())}
    raw["main_html"] = op.open(BASE + PFADE[PORTAL]["start"]).read().decode("utf-8", "ignore")
    return raw

def build(raw, now, events, weather=None, departures=None):
    today = now.date()
    kwh15, hours, prices = raw["l24"]
    # Das Portal liefert null, wenn ein Wert noch nicht feststeht (z. B. Zeitumstellung) – solche Werte überall überspringen
    num = lambda v: v if isinstance(v, (int, float)) else None
    kwh15 = [num(v) for v in kwh15]; prices = [num(v) for v in prices]
    letzte_kwh = next((v for v in reversed(kwh15) if v is not None), None)
    power_w = round(letzte_kwh * 4 * 1000) if letzte_kwh is not None else None
    price_now = next((p for p in reversed(prices) if p is not None), None)
    profil = {}
    for h, p in zip(hours, prices):
        if p is not None:
            profil.setdefault(h, []).append(p)
    price_profile = {str(h): round(sum(v) / len(v) * 100, 1) for h, v in profil.items() if v}
    # Viertelstundenpreise mit Zeitstempel (letzter Wert = jetzt, 15-min-Raster rückwärts)
    n = len(prices); end = now.replace(second=0, microsecond=0); end = end - dt.timedelta(minutes=end.minute % 15)
    gefuellt, letzter = [], None                       # fehlende Preise mit dem letzten bekannten fortschreiben, damit Chart und Kalibrierung sauber bleiben
    for p in prices:
        letzter = p if p is not None else letzter
        gefuellt.append(letzter)
    price_24h = [{"t": (end - dt.timedelta(minutes=15 * (n - 1 - i))).isoformat(timespec="minutes"), "ct": round(p * 100, 2) if p is not None else None, "kwh": kwh15[i] or 0} for i, p in enumerate(gefuellt)]
    kwh15 = [v or 0 for v in kwh15]
    pv = raw.get("pv") or [[], [], []]
    last = lambda a: (a[-1] if a else None)
    month = {"year": today.year, "month": today.month}
    daily = {}
    for key, rk in (("strom_kwh", "m_strom"), ("kaltwasser_m3", "m_kalt"), ("warmwasser_m3", "m_warm"), ("waerme_kwh", "m_waerme")):
        vals = [v if isinstance(v, (int, float)) else 0 for v in (raw.get(rk) or [[]])[0]]
        daily[key] = vals
        month[key] = round(sum(vals), 2)
    month["days_counted"] = len(daily["strom_kwh"])
    strom_days = daily["strom_kwh"]
    allstrom = raw["m_prev"][0] + strom_days
    week = allstrom[-8:-1]
    first = today.replace(day=1); prev_first = (first - dt.timedelta(days=1)).replace(day=1)
    def dated(prev_vals, cur_vals):
        out = [{"d": (prev_first + dt.timedelta(days=i)).isoformat(), "v": v} for i, v in enumerate(prev_vals)]
        out += [{"d": (first + dt.timedelta(days=i)).isoformat(), "v": v} for i, v in enumerate(cur_vals)]
        return out[-14:]
    daily_out = {"strom_kwh": dated(raw["m_prev"][0], strom_days), "kaltwasser_m3": dated([], daily["kaltwasser_m3"]), "warmwasser_m3": dated([], daily["warmwasser_m3"])}
    # Wasser letzte 24 h in Litern (Viertelstundenwerte m³ → l)
    def l24(key):
        v = raw.get(key)
        return round(sum(x for x in v[0] if isinstance(x, (int, float))) * 1000) if v and v[0] else None
    wasser24 = {"kalt_l": l24("w24_kalt"), "warm_l": l24("w24_warm")}
    # Grundlast: kleinste Stundensumme der letzten 24 h (typisch nachts), in Watt
    hour_sums = {}
    for i, k in enumerate(kwh15):
        hour_sums.setdefault(i // 4, 0); hour_sums[i // 4] += k
    full_hours = [v for i, v in hour_sums.items() if i < len(kwh15) // 4]
    grundlast_w = round(min(full_hours) * 1000) if full_hours else None
    ampel = raw["ampel"]
    cost = parse_costs(raw["main_html"]) if raw.get("main_html") else None
    start = parse_start(raw["main_html"]) if raw.get("main_html") else {}
    if not strom_days and cost and cost.get("today"):      # neues Portal: Zählerdaten (noch) leer → Tageswerte von der Startseite
        strom_days = [cost["today"]["kwh"]]
        if cost.get("month"): month["strom_kwh"] = cost["month"]["kwh"]
    if month["days_counted"] == 0 and start:
        for key, mk in (("warmwasser", "warmwasser_m3"), ("kaltwasser", "kaltwasser_m3")):
            if start.get(key, {}).get("month"): month[mk] = start[key]["month"]["m3"]
            if start.get(key, {}).get("today"): daily[mk] = [start[key]["today"]["m3"]]
        if start.get("heizung", {}).get("month"): month["waerme_kwh"] = start["heizung"]["month"]["kwh"]
    if price_now is None and isinstance(ampel.get("currentEnergyprice"), (int, float)):
        price_now = ampel["currentEnergyprice"] / 100
    hinweise = []
    if not kwh15: hinweise.append("Viertelstundenwerte fehlen (Portal liefert leere Zählerdaten)")
    return {
        "hinweise": hinweise,
        "updated": now.isoformat(timespec="minutes"),
        "data_until": today.isoformat(),
        "live": {
            "power_w": power_w, "price_ct": round(price_now * 100, 1) if price_now is not None else None,
            "ampel": ampel.get("color"), "ampel_price_ct": ampel.get("currentEnergyprice"),
            "pv_kw": last(pv[1]) if len(pv) > 1 else None, "siedlung_kw": last(pv[0]) if pv else None, "autarkie_pct": last(pv[2]) if len(pv) > 2 else None,
        },
        "price_profile_ct": price_profile,
        "price_24h": price_24h,
        "month": month,
        "daily": daily_out,
        "today": {"strom_kwh": round(strom_days[-1], 2) if strom_days else None, "kaltwasser_m3": round(daily["kaltwasser_m3"][-1], 3) if daily["kaltwasser_m3"] else None,
                  "warmwasser_m3": round(daily["warmwasser_m3"][-1], 3) if daily["warmwasser_m3"] else None},
        "wasser24": wasser24,
        "grundlast_w": grundlast_w,
        "yesterday": {"strom_kwh": round(allstrom[-2], 2) if len(allstrom) >= 2 else None, "kaltwasser_m3": round(daily["kaltwasser_m3"][-2], 3) if len(daily["kaltwasser_m3"]) >= 2 else None},
        "week_avg_strom_kwh": round(sum(week) / len(week), 2) if week else None,
        "pv_today_kwh": round(sum(x for x in (pv[1] if len(pv) > 1 else []) if isinstance(x, (int, float))) / 4),
        "year_strom_kwh": round(sum(raw["jahr"][0]), 1) if raw["jahr"][0] else (cost.get("year", {}).get("kwh") if cost else None),
        "events": events,
        "weather": weather,
        "cost": cost,
        "start": start or None,
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
    global PORTAL

    raw = None
    try:
        if a.raw:
            raw = json.load(open(a.raw, encoding="utf-8"))
        else:
            op = session(); PORTAL = login(op); raw = fetch_raw(op, today)
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

    out = None
    if raw:
        try:
            out = build(raw, now, events, weather, departures)
        except Exception as e:
            import traceback
            tb = traceback.extract_tb(e.__traceback__)[-1]
            errors["aufbereitung"] = f"{type(e).__name__}: {e} (Zeile {tb.lineno})"[:300]
            print("build fehlgeschlagen:", traceback.format_exc(), file=sys.stderr)
    if out is None:
        out = {"updated": now.isoformat(timespec="minutes"), "data_until": None, "live": {}, "price_profile_ct": {}, "price_24h": [],
               "month": None, "today": {}, "yesterday": {}, "week_avg_strom_kwh": None, "pv_today_kwh": None, "year_strom_kwh": None,
               "events": events, "weather": weather, "cost": None, "departures": departures}
    out["errors"] = errors
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    l = out.get("live") or {}
    print(f"{a.out}: {l.get('power_w')} W, {l.get('price_ct')} ct, Ampel {l.get('ampel')}, Fehler: {errors or 'keine'}")


# ---------------- Neues Portal (seit Nov. 2026: /anmelden mit CSRF-Token) – Erkundung ----------------
def login_neu(op):
    """Anmeldung am umgebauten Portal: GET /anmelden (csrf_token) → POST /anmelden?mode=ok. Gibt die Antwort-HTML zurück."""
    user, pw = os.environ.get("ENOCOO_USER"), os.environ.get("ENOCOO_PASS")
    if not user or not pw:
        raise RuntimeError("ENOCOO_USER / ENOCOO_PASS fehlen")
    html = op.open(BASE + "/anmelden", timeout=30).read().decode("utf-8", "ignore")
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html) or re.search(r'value="([^"]+)"[^>]*name="csrf_token"', html)
    data = {"user": user, "passwort": pw}
    if m: data["csrf_token"] = m.group(1)
    r = op.open(BASE + "/anmelden?mode=ok", data=urllib.parse.urlencode(data).encode(), timeout=30)
    return r.geturl(), r.read().decode("utf-8", "ignore")

def erkunden(pfad=None, roh=False, vorher=None, ajax=False):
    """Diagnose: meldet sich am neuen Portal an und liefert Links, Skripte und URL-artige Strings der Startseite
    (oder der Seite `pfad`), damit die neuen Daten-Endpunkte gefunden werden können."""
    op = session()
    url, html = login_neu(op)
    out = {"nach_login": url, "titel": (re.search(r"<title>(.*?)</title>", html, re.S) or [None, None])[1]}
    if vorher:
        try: op.open(BASE + vorher, timeout=30).read()
        except Exception as e: out["vorher_fehler"] = str(e)[:200]
    if pfad:
        try:
            req = urllib.request.Request(BASE + pfad, headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/javascript, */*; q=0.01", "Referer": BASE + "/verbrauch"} if ajax else {})
            r = op.open(req, timeout=30); html = r.read().decode("utf-8-sig", "ignore"); out["pfad"] = pfad; out["pfad_url"] = r.geturl(); out["status"] = r.status
        except urllib.error.HTTPError as e:
            out["pfad"] = pfad; out["status"] = e.code; html = e.read().decode("utf-8", "ignore")
    if roh:
        out["html"] = html[:20000]; return out
    out["links"] = sorted(set(re.findall(r'href="([^"#]+)"', html)))[:80]
    out["skripte"] = sorted(set(re.findall(r'<script[^>]+src="([^"]+)"', html)))
    out["formulare"] = re.findall(r'<form[^>]*action="([^"]*)"', html)
    urls = set(re.findall(r'["\'](/[A-Za-z0-9_\-/\.]+(?:\?[^"\']*)?)["\']', html))
    for src in out["skripte"]:
        if any(k in src for k in ("jquery", "bootstrap", "chart", "moment")): continue
        try:
            js = op.open(src if src.startswith("http") else BASE + src, timeout=30).read().decode("utf-8", "ignore")
            urls |= set(re.findall(r'["\'](/[A-Za-z0-9_\-/\.]+(?:\?[^"\']*)?)["\']', js))
            urls |= set(u for u in re.findall(r'(?:url|href|action)\s*[:=]\s*["\']([^"\']+)["\']', js))
        except Exception as e:
            out.setdefault("skript_fehler", []).append(f"{src}: {e}")
    out["urls"] = sorted(u for u in urls if not u.endswith((".css", ".png", ".svg", ".woff", ".woff2", ".ico", ".jpg")))[:150]
    out["text"] = re.sub(r"\s+", " ", re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", html, flags=re.S))[:1500]
    return out

if __name__ == "__main__":
    main()
