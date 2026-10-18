#!/usr/bin/env python3
"""Einkaufsliste per Telegram + Sonderangebote (marktguru) für die Energie-Tafel.

Telegram: Bot bei @BotFather anlegen, Token als TELEGRAM_TOKEN setzen. Jeder, der dem Bot schreibt, pflegt die Liste:
    "Milch, Eier, Windeln"   → hinzufügen (Komma oder Zeilenumbruch trennt)
    "x Milch" / "- Milch"    → abhaken (Teilstring reicht)
    "leer"                   → Liste leeren
    "liste"                  → Bot antwortet mit der Liste
Optional TELEGRAM_CHAT_IDS="123,456": nur diese Chats dürfen schreiben (sonst jeder, der den Bot findet).

Angebote: marktguru-Web-API (Schlüssel von marktguru.de, kein Account). PLZ über ANGEBOTE_PLZ, Standard 68309.
"""
import os, sys, json, re, time, urllib.request, urllib.parse, datetime as dt

STATE = os.environ.get("EINKAUF_STATE", "einkauf_state.json")
PLZ = os.environ.get("ANGEBOTE_PLZ", "68309")
MG_HEADERS = {"x-apikey": "8Kk+pmbf7TgJ9nVj2cXeA7P5zBGv8iuutVVMRfOfvNE=", "x-clientkey": "WU/RH+PMGDi+gkZer3WbMelt6zcYHSTytNB7VpTia90=",
              "User-Agent": "Mozilla/5.0", "Accept": "application/json"}
LAEDEN = {"Lidl", "ALDI SÜD", "REWE", "EDEKA", "Kaufland", "Netto Marken-Discount", "PENNY", "dm", "ROSSMANN", "Scheck-in Center"}

def load():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {"items": [], "offset": 0, "offers": {}, "offers_at": None}

def save(s):
    tmp = STATE + ".tmp"; json.dump(s, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1); os.replace(tmp, STATE)

def tg(method, **params):
    tok = os.environ.get("TELEGRAM_TOKEN")
    if not tok:
        return None
    data = urllib.parse.urlencode(params).encode()
    return json.loads(urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/{method}", data=data, timeout=25).read().decode())

def norm(s):
    return s.strip().strip(".;,").capitalize()

def apply_message(state, text, who):
    t = text.strip()
    low = t.lower()
    items = state["items"]
    if low in ("leer", "clear", "/leer", "/clear"):
        state["items"] = []; return "Liste geleert."
    if low in ("liste", "/liste", "/list", "/start"):
        return "Einkaufsliste:\n" + ("\n".join("• " + i["name"] for i in items) if items else "(leer)")
    m = re.match(r"^(x|-|✓|✔|done|weg|erledigt)\s+(.+)$", t, re.I)
    if m:
        q = m[2].strip().lower(); before = len(items)
        state["items"] = [i for i in items if q not in i["name"].lower()]
        n = before - len(state["items"])
        return f"Abgehakt: {m[2].strip()}" if n else f"„{m[2].strip()}“ steht nicht auf der Liste."
    added = []
    for part in re.split(r"[,\n;]+", t):
        name = norm(part)
        if not name or len(name) > 60:
            continue
        if not any(i["name"].lower() == name.lower() for i in items):
            items.append({"name": name, "by": who, "at": dt.datetime.now().isoformat(timespec="minutes")}); added.append(name)
    return ("Dazu: " + ", ".join(added)) if added else "Steht schon drauf."

def poll_telegram(state):
    allowed = {c.strip() for c in os.environ.get("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()}
    r = tg("getUpdates", offset=state.get("offset", 0), timeout=0)
    if not r or not r.get("ok"):
        return
    for u in r.get("result", []):
        state["offset"] = u["update_id"] + 1
        msg = u.get("message") or u.get("edited_message")
        if not msg or "text" not in msg:
            continue
        chat = str(msg["chat"]["id"])
        if allowed and chat not in allowed:
            tg("sendMessage", chat_id=chat, text=f"Nicht freigeschaltet. Chat-ID: {chat}"); continue
        who = (msg.get("from") or {}).get("first_name", "?")
        reply = apply_message(state, msg["text"], who)
        tg("sendMessage", chat_id=chat, text=reply)

def search_offers(q, limit=6):
    url = f"https://api.marktguru.de/api/v1/offers/search?as=web&q={urllib.parse.quote(q)}&zipCode={PLZ}&limit={limit}&offset=0"
    req = urllib.request.Request(url, headers=MG_HEADERS)
    j = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore"))
    out = []
    today = dt.date.today()
    for o in j.get("results", []):
        adv = (o.get("advertisers") or [{}])[0].get("name", "")
        vd = (o.get("validityDates") or [{}])[0]
        frm, to = (vd.get("from") or "")[:10], (vd.get("to") or "")[:10]
        if to and to < today.isoformat():
            continue
        if frm and frm > (today + dt.timedelta(days=7)).isoformat():
            continue
        out.append({"product": (o.get("product") or {}).get("name", ""), "brand": (o.get("brand") or {}).get("name", ""),
                    "price": o.get("price"), "old": o.get("oldPrice"), "unit": (o.get("unit") or {}).get("shortName", ""),
                    "desc": (o.get("description") or "")[:60], "store": adv, "from": frm, "to": to,
                    "soon": bool(frm and frm > today.isoformat())})
    out.sort(key=lambda x: (x["soon"], x["price"] if x["price"] is not None else 99))
    return out[:4]

def refresh_offers(state, max_age_h=6):
    at = state.get("offers_at")
    if at and (time.time() - at) < max_age_h * 3600 and set(state.get("offers", {})) >= {i["name"] for i in state["items"]}:
        return
    offers = {}
    for i in state["items"]:
        try:
            offers[i["name"]] = search_offers(i["name"])
        except Exception as e:
            print("Angebote:", i["name"], e, file=sys.stderr)
    state["offers"] = offers; state["offers_at"] = time.time()

def main():
    state = load()
    errors = {}
    try:
        poll_telegram(state)
    except Exception as e:
        errors["telegram"] = f"{type(e).__name__}: {e}"[:200]
    try:
        refresh_offers(state)
    except Exception as e:
        errors["angebote"] = f"{type(e).__name__}: {e}"[:200]
    save(state)
    out = {"items": [{**i, "offers": state["offers"].get(i["name"], [])} for i in state["items"]],
           "updated": dt.datetime.now().isoformat(timespec="minutes"), "telegram": bool(os.environ.get("TELEGRAM_TOKEN")), "errors": errors}
    outp = sys.argv[1] if len(sys.argv) > 1 else "einkauf.json"
    json.dump(out, open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{outp}: {len(out['items'])} Artikel, Fehler: {errors or 'keine'}")

if __name__ == "__main__":
    main()
