#!/usr/bin/env python3
"""Minimaler Webserver für die Energie-Tafel.
Liefert www/ nur unter dem geheimen Pfad /<TAFEL_TOKEN>/ aus, alles andere 404. Keine Caches, damit data.json immer frisch ist."""
import os, sys, re, http.server, posixpath, json, urllib.parse, importlib.util, threading, hmac, hashlib, time

TOKEN = os.environ.get("TAFEL_TOKEN", "").strip("/")
PORT = int(os.environ.get("TAFEL_PORT", "8787"))
ROOT = os.path.abspath(os.environ.get("TAFEL_ROOT", "."))
if not TOKEN:
    sys.exit("TAFEL_TOKEN fehlt")
PIN = os.environ.get("TAFEL_PIN", "").strip()                 # Passwort für die Anmeldeseite; leer = nur der geheime Pfad
COOKIE_SECRET = hashlib.sha256((TOKEN + "|" + PIN).encode()).hexdigest()   # Cookie-Wert; ändert sich mit PIN oder Token
COOKIE_AGE = 365 * 24 * 3600
HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("einkauf", os.path.join(HERE, "einkauf.py")); EINKAUF = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(EINKAUF)
_ll = importlib.util.spec_from_file_location("llm", os.path.join(HERE, "llm.py")); LLM = importlib.util.module_from_spec(_ll); _ll.loader.exec_module(LLM)
_hh = importlib.util.spec_from_file_location("haushalt", os.path.join(HERE, "haushalt.py")); HAUSHALT = importlib.util.module_from_spec(_hh); _hh.loader.exec_module(HAUSHALT)
_wp = importlib.util.spec_from_file_location("webpush", os.path.join(HERE, "webpush.py")); WEBPUSH = importlib.util.module_from_spec(_wp); _wp.loader.exec_module(WEBPUSH)
LOCK = threading.Lock()

PHONE_PAGE = r"""<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="default"><meta name="apple-mobile-web-app-title" content="Einkauf"><title>homeOS · Einkauf</title>
<link rel="icon" type="image/svg+xml" href="../icon.svg"><link rel="apple-touch-icon" href="../icon-180.png"><link rel="manifest" href="../manifest.webmanifest">
<style>
:root{--fg:#0f2a4a;--muted:#5f7691;--line:#d9e3ee;--soft:#edf3f9;--good:#16a35a;--bad:#2a6fdb}
body{margin:0;font-family:-apple-system,"Manrope",system-ui,sans-serif;color:var(--fg);background:#fff;padding:env(safe-area-inset-top) 16px 24px}
h1{font-size:1.1rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin:1.2rem 0 .8rem}
form{display:flex;gap:.5rem;margin-bottom:1rem}
input{flex:1;font:inherit;font-size:1.1rem;padding:.75rem .9rem;border:1.5px solid var(--line);border-radius:12px;min-width:0}
ul{list-style:none;margin:0;padding:0}
li{position:relative;overflow:hidden;padding:0;border-bottom:1px solid var(--line);font-size:1.15rem;font-weight:600}
li .row2{display:flex;align-items:center;gap:.8rem;padding:.8rem 0;background:#fff;position:relative}
li .sw{position:absolute;inset:0;display:flex;justify-content:space-between;align-items:center;font-size:.8rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#fff;padding:0 .9rem}
li .sw .sl{background:var(--muted)} li .sw .sr{background:var(--good)} li .sw span{padding:.4rem .7rem;border-radius:999px;opacity:0;transition:opacity .15s}
li.swl .sl, li.swr .sr{opacity:1}
li .kauft{font-size:.72rem;font-weight:700;letter-spacing:.04em;padding:.2rem .55rem;border-radius:999px;background:var(--good);color:#fff;margin-left:auto}
li .kauft + .von{margin-left:.4rem}
li.mine:not(.me) .row2{opacity:.55}
.filter{display:flex;gap:.4rem;margin:0 0 .4rem}.filter button{font:inherit;font-weight:700;font-size:.85rem;padding:.4rem .9rem;border-radius:999px;border:1.5px solid var(--line);background:#fff;color:var(--muted)}.filter button.on{background:var(--fg);border-color:var(--fg);color:#fff}
li i{width:1.3rem;height:1.3rem;border:2px solid var(--line);border-radius:6px;flex:none;position:relative}
li i::after{content:"";position:absolute;inset:-.6rem}
li small{display:block;font-size:.8rem;font-weight:500;color:var(--muted)}
li small b{color:var(--good)}
li.done .row2{opacity:.35;text-decoration:line-through}
li.kat{display:flex;align-items:center;font-size:.72rem;letter-spacing:.12em;text-transform:uppercase;color:var(--bad);font-weight:700;border:0;padding:1.1rem 0 .2rem;justify-content:space-between;overflow:visible}
li.kat .claim{font:inherit;font-size:.7rem;letter-spacing:.06em;padding:.3rem .7rem;border-radius:999px;border:1.5px solid var(--line);background:#fff;color:var(--muted)}
li.kat .claim.on{background:var(--good);border-color:var(--good);color:#fff}
li .von{margin-left:auto;font-size:.75rem;width:1.5rem;height:1.5rem;border-radius:50%;background:var(--soft);color:var(--muted);display:grid;place-items:center;flex:none}
.leer{color:var(--muted);font-weight:500}
.hint{color:var(--muted);font-size:.85rem;margin-top:1.2rem;line-height:1.5}
.row{display:flex;justify-content:space-between;align-items:center}
.row a{color:var(--bad);font-size:.9rem;text-decoration:none}
</style></head><body>
<div class="row"><h1>Einkaufsliste</h1><a href="#" id="clear">leeren</a></div>
<div id="ek"></div>
<div id="filter" class="filter" hidden><button data-f="alle" class="on">Alle</button><button data-f="meine">Meine</button></div>
<ul id="l"><li class="leer">Lade …</li></ul>
<p class="hint">Nach rechts wischen = ich kaufe das · nach links oder Kästchen = erledigt. Tippen · Sprechen · Foto · Barcode – alles landet auf der Liste, die auch auf der Tafel steht.</p>
<script src="../einkauf.js"></script>
<script>
const base = location.pathname.replace(/\/einkauf\/?$/, "");
async function load(){ const r = await fetch(base + "/einkauf.json", {cache:"no-store"}); const j = await r.json(); render(j); }
const KAT = [["vorrat","Vorrat · Discounter"],["frisch","Frisch · Markt / Supermarkt"],["drogerie","Drogerie & Haushalt"]];
let FILTER = "alle";
function render(j){ LAST = j; if (j.personen) window.EINKAUF_PERSONEN = j.personen; if (window.einkaufClaimState) einkaufClaimState(j); if (window.einkaufVorschlaege) einkaufVorschlaege(j); const ul = document.getElementById("l"); ul.innerHTML = "";
  const me = wer(); const f = document.getElementById("filter"); f.hidden = !me; f.querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.f === FILTER)); f.querySelector('[data-f="meine"]').textContent = (me||"Meine") + " (" + j.items.filter(i => i.wer_kauft === me).length + ")";
  const items = FILTER === "meine" && me ? j.items.filter(i => i.wer_kauft === me) : j.items;
  if(!items.length){ ul.innerHTML = '<li class="leer">' + (FILTER === "meine" ? "Nichts übernommen – nach rechts wischen, um Artikel zu nehmen." : "Noch nichts auf der Liste") + '</li>'; return; }
  for(const [k,label] of KAT){ const its = items.filter(it => (it.kat||"vorrat") === k); if(!its.length) continue;
    const ue = (j.uebernahme||{})[k]; const h = document.createElement("li"); h.className = "kat"; h.innerHTML = `<span>${label}</span><button class="claim ${ue?"on":""}">${ue ? ue.wer + " kauft" : "alle nehmen"}</button>`; h.querySelector("button").onclick = (e) => { e.stopPropagation(); claim(k); }; ul.appendChild(h);
    for(const it of its){ const best = (it.offers||[]).filter(o=>!o.soon)[0]; const li = document.createElement("li"); li.className = it.wer_kauft ? "mine" + (it.wer_kauft === me ? " me" : "") : "";
      li.innerHTML = `<div class="sw"><span class="sl">✓ erledigt</span><span class="sr">${me ? me + " kauft" : "nehmen"}</span></div><div class="row2"><i></i><span>${it.name}${it.q?` <small style="display:inline;opacity:.7">${it.q}</small>`:""}${best?`<small><b>${best.store}</b> ${best.price.toLocaleString("de-DE",{minimumFractionDigits:2})} €</small>`:""}</span>${it.wer_kauft ? `<b class="kauft">${it.wer_kauft}</b>` : ""}${it.by && it.by !== "Handy" && it.by !== "Tafel" ? `<b class="von">${it.by[0]}</b>` : ""}</div>`;
      li.querySelector("i").onclick = async () => { li.classList.add("done"); await send("x " + it.name); };
      swipe(li, async () => { li.classList.add("done"); await send("x " + it.name); }, async () => { if(!me){ alert("Erst oben auf deinen Namen tippen."); return; } await nehmen(it.name); });
      ul.appendChild(li); } } }
function swipe(li, left, right){ let x0=null, dx=0; const row = li.querySelector(".row2");
  li.addEventListener("touchstart", e => { x0 = e.touches[0].clientX; dx = 0; row.style.transition = "none"; }, {passive:true});
  li.addEventListener("touchmove", e => { if(x0===null) return; dx = e.touches[0].clientX - x0; if (Math.abs(dx) > 8) row.style.transform = `translateX(${Math.max(-110, Math.min(110, dx))}px)`; li.classList.toggle("swl", dx < -30); li.classList.toggle("swr", dx > 30); }, {passive:true});
  li.addEventListener("touchend", () => { row.style.transition = "transform .18s"; row.style.transform = ""; const d = dx; x0 = null; li.classList.remove("swl","swr"); if (d < -70) left(); else if (d > 70) right(); });
}
async function nehmen(name){ const r = await fetch(base + "/einkauf/nehmen", {method:"POST", headers:{"Content-Type":"application/x-www-form-urlencoded"}, body:"name="+encodeURIComponent(name)+"&wer="+encodeURIComponent(wer())}); if(r.ok) render(await r.json()); }
function wer(){ try { return localStorage.getItem("ek-wer") || ""; } catch(e){ return ""; } }
async function send(text){ const r = await fetch(base + "/einkauf/add", {method:"POST", headers:{"Content-Type":"application/x-www-form-urlencoded"}, body:"text="+encodeURIComponent(text)+"&wer="+encodeURIComponent(wer())}); if(r.ok) render(await r.json()); }
async function claim(kat){ const r = await fetch(base + "/einkauf/claim", {method:"POST", headers:{"Content-Type":"application/x-www-form-urlencoded"}, body:"kat="+encodeURIComponent(kat)+"&wer="+encodeURIComponent(wer()||"Handy")}); if(r.ok) render(await r.json()); }
let LAST=null; initEinkauf({ mount: document.getElementById("ek"), base, onUpdate: render, getData: () => LAST });
document.getElementById("clear").onclick = async e => { e.preventDefault(); if(document.getElementById("clear").dataset.ok){ await send("leer"); delete document.getElementById("clear").dataset.ok; document.getElementById("clear").textContent="leeren"; } else { document.getElementById("clear").dataset.ok="1"; document.getElementById("clear").textContent="wirklich leeren?"; setTimeout(()=>{delete document.getElementById("clear").dataset.ok; document.getElementById("clear").textContent="leeren";},3000);} };
document.querySelectorAll("#filter button").forEach(b => b.onclick = () => { FILTER = b.dataset.f; if (LAST) render(LAST); });
load(); setInterval(load, 30000);
</script></body></html>"""

def ean_lookup(code):
    """Barcode → Produktname über Open Food Facts (Lebensmittel) und Open Beauty/Products Facts (Drogerie)."""
    code = "".join(ch for ch in code if ch.isdigit())[:14]
    if not code:
        return {"name": None}
    import urllib.request
    for host in ("world.openfoodfacts.org", "world.openbeautyfacts.org", "world.openproductsfacts.org"):
        try:
            req = urllib.request.Request(f"https://{host}/api/v2/product/{code}.json?fields=product_name,product_name_de,brands,quantity", headers={"User-Agent": "FranklinTafel/1.0 (einkaufsliste)"})
            with urllib.request.urlopen(req, timeout=8) as r:
                j = json.load(r)
        except Exception:
            continue
        p = j.get("product") or {}
        name = (p.get("product_name_de") or p.get("product_name") or "").strip()
        if not name:
            continue
        brand = (p.get("brands") or "").split(",")[0].strip()
        qty = (p.get("quantity") or "").strip()
        full = " ".join(x for x in (brand if brand and brand.lower() not in name.lower() else "", name, qty if qty and qty.lower() not in name.lower() else "") if x)
        return {"name": full, "ean": code}
    return {"name": None, "ean": code}

def photo_items(b64):
    """Foto → Liste von Produktnamen (Mistral oder Claude)."""
    if not LLM.anbieter():
        return {"error": "Foto-Erkennung ist nicht eingerichtet – " + LLM.fehlt()}
    if not b64:
        return {"error": "Kein Bild erhalten."}
    prompt = ("Das ist ein Foto aus einem Haushalt in Deutschland: ein Produkt, eine Verpackung, ein Kühlschrank- oder Vorratsregal oder ein handgeschriebener Zettel. "
              "Nenne die Lebensmittel bzw. Haushaltsartikel, die man auf eine Einkaufsliste setzen würde – bei einer Verpackung das Produkt (kurz, z. B. 'Haltbare Milch 1,5 %'), "
              "bei einem Zettel die aufgeschriebenen Artikel, bei einem Regal die erkennbaren Produkte. Antworte NUR mit JSON: {\"items\": [\"…\", …]} auf Deutsch, maximal 12 Einträge.")
    text = LLM.frage(prompt, image_b64=b64, max_tokens=300)
    d = LLM.json_aus(text) or {}
    items = d.get("items") if isinstance(d, dict) else (d if isinstance(d, list) else [])
    return {"items": [str(x).strip() for x in (items or []) if str(x).strip()][:12]}

def gesprochen_zerlegen(text):
    """Diktierter Satz → kommagetrennte Artikel. Mit KI-Schlüssel über das Modell, sonst Wortlisten-Heuristik."""
    t = re.sub(r"\s+", " ", text or "").strip().rstrip(".!?")
    if not t:
        return ""
    if LLM.anbieter():
        try:
            prompt = ("Das ist ein diktierter Satz für eine Einkaufsliste (Deutsch oder Englisch, evtl. mit Erkennungsfehlern): \"" + t + "\"\n"
                      "Zerlege ihn in einzelne Artikel, so wie man sie auf eine Liste schreibt (Mengen behalten, z. B. '2 Liter Milch'; Füllwörter wie 'bitte', 'noch', 'wir brauchen' weglassen; "
                      "sagt jemand 'Milch ist erledigt/streichen/haben wir', dann 'x Milch'). Antworte NUR mit JSON: {\"items\": [\"…\"]}.")
            d = LLM.json_aus(LLM.frage(prompt, max_tokens=200)) or {}
            items = [str(x).strip() for x in (d.get("items") or []) if str(x).strip()]
            if items:
                return "\n".join(items)
        except Exception as e:
            print("sprache/ki:", e, flush=True)
    return EINKAUF.zerlege_gesprochen(t)

def _push_store_load():
    if EINKAUF.SPEICHER.aktiv():
        try:
            d = EINKAUF.SPEICHER.db()
            cfg = d["config"].find_one({"_id": "push"}) or {}
            abos = list(d["push_abos"].find({}, {"_id": 0}))
            return {"keys": cfg.get("keys"), "abos": abos}
        except Exception as e:
            print("push load:", e, flush=True)
    try:
        return json.load(open(PUSH_FILE, encoding="utf-8"))
    except Exception:
        return {"keys": None, "abos": []}

def _push_keys():
    st = _push_store_load()
    if st.get("keys"):
        return st["keys"]
    keys = WEBPUSH.vapid_keys()
    if EINKAUF.SPEICHER.aktiv():
        try:
            EINKAUF.SPEICHER.db()["config"].update_one({"_id": "push"}, {"$set": {"keys": keys}}, upsert=True); return keys
        except Exception as e:
            print("push keys:", e, flush=True)
    st["keys"] = keys; json.dump(st, open(PUSH_FILE, "w"))
    return keys

def _push_abo_set(sub, wer, geraet):
    doc = {"endpoint": sub["endpoint"], "sub": sub, "wer": wer, "geraet": geraet, "at": time.strftime("%Y-%m-%dT%H:%M")}
    if EINKAUF.SPEICHER.aktiv():
        try:
            EINKAUF.SPEICHER.db()["push_abos"].update_one({"endpoint": sub["endpoint"]}, {"$set": doc}, upsert=True); return
        except Exception as e:
            print("push abo:", e, flush=True)
    st = _push_store_load(); st["abos"] = [a for a in st["abos"] if a["endpoint"] != sub["endpoint"]] + [doc]; json.dump(st, open(PUSH_FILE, "w"))

def _push_abo_del(endpoint):
    if EINKAUF.SPEICHER.aktiv():
        try:
            EINKAUF.SPEICHER.db()["push_abos"].delete_one({"endpoint": endpoint}); return
        except Exception as e:
            print("push del:", e, flush=True)
    st = _push_store_load(); st["abos"] = [a for a in st["abos"] if a["endpoint"] != endpoint]; json.dump(st, open(PUSH_FILE, "w"))

PUSH_QUEUE = []           # (wer, aktion, text)
PUSH_TIMER = None
def push_event(wer, aktion, text):
    """Ereignis sammeln; nach 20 s eine gebündelte Nachricht an alle anderen Geräte."""
    global PUSH_TIMER
    PUSH_QUEUE.append((wer, aktion, text))
    if PUSH_TIMER is None:
        PUSH_TIMER = threading.Timer(20, _push_flush); PUSH_TIMER.daemon = True; PUSH_TIMER.start()

def push_sofort(wer, titel, text):
    """Sofort (ohne Bündelung) an alle anderen Geräte – z. B. wenn jemand den Einkauf übernimmt."""
    def run():
        try:
            st = _push_store_load(); keys = _push_keys()
            for a in st.get("abos", []):
                if wer and a.get("wer") and a["wer"] == wer:
                    continue
                code, txt = WEBPUSH.send(a["sub"], {"title": titel, "body": text, "url": "haushalt/" if "udget" in titel else "einkauf/"}, keys, sub=os.environ.get("VAPID_SUBJECT", "mailto:homeos@example.org"), urgency="high")
                if code in (404, 410):
                    _push_abo_del(a["endpoint"])
                elif code >= 300:
                    print("push", code, txt, flush=True)
        except Exception as e:
            print("push sofort:", e, flush=True)
    threading.Thread(target=run, daemon=True).start()

MELD_FILE = os.path.join(os.path.dirname(os.environ.get("EINKAUF_STATE", os.path.join(HERE, "x"))), "haushalt_meldungen.json")
def budget_meldungen(out):
    """Push an alle, wenn eine Kategorie 80 % bzw. 100 % ihres Monatsbudgets überschreitet (je Monat und Stufe nur einmal)."""
    ym = out["monat"]["ym"]
    db = EINKAUF.SPEICHER.db() if EINKAUF.SPEICHER.aktiv() else None
    if db is not None:
        st = (db["config"].find_one({"_id": "haushalt_meldungen"}) or {}).get("stufen", {})
    else:
        try:
            st = json.load(open(MELD_FILE))
        except Exception:
            st = {}
    monat = st.setdefault(ym, {})
    geaendert = False
    for b in out["monat"].get("budgets") or []:
        if not b.get("budget"):
            continue
        stufe = 100 if b["eur"] >= b["budget"] else (80 if b["eur"] >= b["budget"] * 0.8 else 0)
        if stufe > monat.get(b["name"], 0):
            monat[b["name"]] = stufe; geaendert = True
            eur = lambda v: f"{v:.2f}".replace(".", ",") + " €"
            txt = f"{b['name']}: {eur(b['eur'])} von {eur(b['budget'])}" + (" – Budget aufgebraucht" if stufe == 100 else f" ({b['pct']} %)")
            push_sofort(None, "Haushaltsbudget" if stufe == 80 else "Budget überschritten", txt)
    if geaendert:
        if db is not None:
            db["config"].update_one({"_id": "haushalt_meldungen"}, {"$set": {"stufen": {ym: monat}}}, upsert=True)
        else:
            json.dump(st, open(MELD_FILE, "w"))

def _push_flush():
    global PUSH_TIMER
    PUSH_TIMER = None
    ev, PUSH_QUEUE[:] = list(PUSH_QUEUE), []
    if not ev:
        return
    try:
        st = _push_store_load(); keys = _push_keys()
        by = {}
        for wer, aktion, text in ev:
            by.setdefault(wer or "Jemand", {}).setdefault(aktion, []).append(text)
        lines = []
        for wer, akt in by.items():
            parts = []
            if akt.get("dazu"): parts.append("+ " + ", ".join(akt["dazu"]))
            if akt.get("abgehakt"): parts.append("✓ " + ", ".join(akt["abgehakt"]))
            if akt.get("nimmt"): parts.append("kauft " + ", ".join(akt["nimmt"]))
            if akt.get("geleert"): parts.append("Liste geleert")
            lines.append(f"{wer}: " + " · ".join(parts))
        body = "\n".join(lines)[:300]
        akteure = {wer for wer, _, _ in ev if wer}
        for a in st.get("abos", []):
            if a.get("wer") and a["wer"] in akteure and akteure == {a["wer"]}:
                continue                                     # eigene Änderungen nicht melden
            code, txt = WEBPUSH.send(a["sub"], {"title": "Einkaufsliste", "body": body, "url": "einkauf/"}, keys, sub=os.environ.get("VAPID_SUBJECT", "mailto:homeos@example.org"))
            if code in (404, 410):
                _push_abo_del(a["endpoint"])
            elif code >= 300:
                print("push", code, txt, flush=True)
    except Exception as e:
        print("push flush:", e, flush=True)

HAUSHALT_PAGE = r"""<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="default"><meta name="apple-mobile-web-app-title" content="Haushalt"><title>homeOS · Haushalt</title>
<link rel="icon" type="image/svg+xml" href="../icon.svg"><link rel="apple-touch-icon" href="../icon-180.png"><link rel="manifest" href="../manifest.webmanifest">
<style>
:root{--fg:#0f2a4a;--muted:#5f7691;--line:#d9e3ee;--soft:#edf3f9;--good:#16a35a;--warn:#e3b000;--bad:#2a6fdb;--mono:ui-monospace,Menlo,monospace}
body{margin:0;font-family:-apple-system,"Manrope",system-ui,sans-serif;color:var(--fg);background:#fff;padding:env(safe-area-inset-top) 16px 40px}
h1{font-size:1.1rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin:1.2rem 0 .8rem}
h2{font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;color:var(--bad);margin:1.4rem 0 .5rem}
.row{display:flex;justify-content:space-between;align-items:center;gap:.6rem}
.big{font-size:2rem;font-weight:800;letter-spacing:-.02em;line-height:1}.big small{font-size:.5em;font-weight:500;color:var(--muted)}
.bar{height:.6rem;background:var(--soft);border-radius:999px;overflow:hidden;position:relative;margin:.5rem 0 .3rem}.bar i{display:block;height:100%;background:var(--good);border-radius:999px}.bar i[data-s=ok]{background:var(--warn)}.bar i[data-s=bad]{background:var(--bad)}
.bar::after{content:"";position:absolute;top:-2px;bottom:-2px;left:var(--soll,100%);border-left:1.5px dashed var(--fg);opacity:.6}
.hint{color:var(--muted);font-size:.85rem;line-height:1.5}
.btns{display:flex;gap:.5rem;margin:.8rem 0}.btns button{flex:1;font:inherit;font-weight:700;font-size:1rem;padding:.9rem;border:1.5px solid var(--line);border-radius:14px;background:#fff;color:var(--fg)}.btns button.p{background:var(--fg);color:#fff;border-color:var(--fg)}
form{display:grid;gap:.5rem;margin:.6rem 0 1rem;padding:1rem;border:1.5px solid var(--line);border-radius:16px;background:var(--soft)}form[hidden]{display:none}
input,select{font:inherit;font-size:1.05rem;padding:.65rem .8rem;border:1.5px solid var(--line);border-radius:12px;background:#fff;min-width:0}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:.5rem}
.ok{font:inherit;font-weight:700;padding:.8rem;border:0;border-radius:12px;background:var(--good);color:#fff}.x{font:inherit;padding:.6rem;border:1.5px solid var(--line);border-radius:12px;background:#fff;color:var(--muted)}
.posten{font-size:.85rem;color:var(--muted);max-height:9rem;overflow:auto;background:#fff;border-radius:10px;padding:.5rem .7rem}.posten div{display:flex;justify-content:space-between}
ul{list-style:none;margin:0;padding:0}li{display:grid;grid-template-columns:auto 1fr auto;gap:.8rem;align-items:center;padding:.6rem 0;border-bottom:1px solid var(--line)}
li .d{font-family:var(--mono);font-size:.8rem;color:var(--muted);white-space:nowrap}li .l{font-weight:600}li .l small{display:block;font-weight:500;color:var(--muted);font-size:.8rem}li .e{font-family:var(--mono);font-weight:700;white-space:nowrap}
li .e button{margin-left:.5rem;border:0;background:none;color:var(--muted);font-size:1rem}
.kat{display:grid;gap:.3rem}.kat div{display:grid;grid-template-columns:7rem 1fr 4.5rem;gap:.5rem;align-items:center;font-size:.9rem}.kat i{display:block;height:.5rem;background:var(--bad);border-radius:999px}.kat b{font-family:var(--mono);text-align:right}.kb div{grid-template-columns:6.5rem 1fr 6rem}.kb b small{font-weight:500;color:var(--muted)}.kat .bar i{background:var(--good)}
.st{color:var(--muted);font-size:.9rem;min-height:1.2rem}
.wk{display:grid;grid-template-columns:repeat(8,1fr);gap:4px;align-items:end;height:48px}.wk i{display:block;background:var(--bad);border-radius:3px 3px 0 0;height:var(--h)}.wk i.now{background:var(--good)}
</style></head><body>
<div class="row"><h1>Haushaltsbuch</h1><a href="../einkauf/" style="color:var(--bad);font-size:.9rem;text-decoration:none">Einkaufsliste →</a></div>
<div class="big" id="m-eur">– €<small> im Monat</small></div><div class="bar" id="m-bar"><i style="width:0"></i></div><div class="hint" id="m-hint"></div>
<div class="btns"><button class="p" id="b-scan">📷 Kassenzettel scannen</button><button id="b-hand">Von Hand</button></div>
<input type="file" accept="image/*" capture="environment" id="file" hidden>
<div class="st" id="st"></div>
<form id="f" hidden>
  <div class="g2"><input name="laden" placeholder="Laden (Lidl, dm …)" required><input name="summe" type="number" step="0.01" inputmode="decimal" placeholder="Betrag €" required></div>
  <div class="g2"><input name="datum" type="date"><select name="kategorie"></select></div>
  <div class="g2"><select name="wer"><option value="">Wer?</option></select><input name="notiz" placeholder="Notiz (optional)"></div>
  <div class="posten" id="posten" hidden></div>
  <div class="g2"><button type="button" class="x" id="abbr">Abbrechen</button><button class="ok">Speichern</button></div>
</form>
<h2>Budget nach Kategorie</h2><div class="kat kb" id="kat"></div>
<h2>Nach Produktart</h2><div class="kat" id="prod"></div>
<h2>Preise</h2><ul id="preise"><li class="hint">Noch zu wenig Belege mit Posten.</li></ul>
<h2>Letzte 8 Wochen</h2><div class="wk" id="wk"></div>
<h2>Letzte Belege</h2><ul id="l"><li class="hint">Lade …</li></ul>
<script>
const base = location.pathname.replace(/\/haushalt\/?$/, "");
let D = null, POSTEN = [];
const eur = v => (v==null?"–":v.toLocaleString("de-DE",{minimumFractionDigits:2,maximumFractionDigits:2})+" €");
function wer(){ try { return localStorage.getItem("ek-wer") || ""; } catch(e){ return ""; } }
async function load(){ const r = await fetch(base + "/haushalt.json", {cache:"no-store"}); if(r.ok){ D = await r.json(); render(); } }
function render(){ const m = D.monat; document.getElementById("m-eur").innerHTML = eur(m.eur) + `<small> von ${eur(D.budget)} · ${m.belege} Belege</small>`;
  const pct = Math.min(100, m.eur / D.budget * 100), soll = m.soll_bis_heute, s = m.eur <= soll ? "good" : m.eur <= D.budget ? "ok" : "bad";
  document.getElementById("m-bar").innerHTML = `<i data-s="${s}" style="width:${pct}%"></i>`; document.getElementById("m-bar").style.setProperty("--soll", (m.tag/m.tage*100)+"%");
  document.getElementById("m-hint").textContent = (m.eur <= soll ? `${eur(soll - m.eur)} unter Plan` : `${eur(m.eur - soll)} über Plan`) + ` · Soll bis heute ${eur(soll)}` + (m.prognose ? ` · Prognose ${eur(m.prognose)}` : "") + ` · Vormonat ${eur(D.vormonat.eur)}`;
  const k = document.getElementById("kat"); const bud = (m.budgets||[]).filter(b=>b.budget||b.eur);
  k.innerHTML = bud.map(b=>{ const pct = b.budget ? Math.min(100, b.eur/b.budget*100) : 0; const st = !b.budget ? "" : b.eur > b.budget ? "bad" : b.eur > b.soll ? "ok" : "good"; return `<div><span>${b.name}</span><span class="bar" style="--soll:${b.budget?Math.min(100,b.soll/b.budget*100):100}%;margin:0;height:.5rem"><i data-s="${st}" style="width:${pct}%"></i></span><b>${eur(b.eur)}<small> /${Math.round(b.budget)}</small></b></div>`; }).join("");
  const pd = document.getElementById("prod"); const pm = Math.max(1, ...(m.produkte||[]).map(x=>Math.abs(x.eur))); pd.innerHTML = (m.produkte||[]).slice(0,8).map(x=>`<div><span>${x.name}</span><i style="width:${Math.abs(x.eur)/pm*100}%"></i><b>${eur(x.eur)}</b></div>`).join("") || '<div class="hint">Noch keine Posten erfasst – Kassenzettel scannen.</div>';
  const pl = document.getElementById("preise"); const pr = (D.preise||[]).filter(p=>p.spanne>0).slice(0,6); if(pr.length) pl.innerHTML = pr.map(p=>`<li><span class="d"></span><span class="l">${p.name}<small>${p.n}× · ${p.min_laden} ${eur(p.min)} … ${p.max_laden} ${eur(p.max)}</small></span><span class="e">${eur(p.letzter)}</span></li>`).join("");
  const w = document.getElementById("wk"); const wm = Math.max(1, ...D.wochen.map(x=>x.eur)); w.innerHTML = D.wochen.map((x,i)=>`<i class="${i===D.wochen.length-1?"now":""}" style="--h:${Math.max(4,x.eur/wm*100)}%" title="${x.von}: ${eur(x.eur)}"></i>`).join("");
  const sel = document.querySelector('select[name=kategorie]'); if(!sel.options.length) sel.innerHTML = D.kategorien.map(x=>`<option>${x}</option>`).join("");
  const ws = document.querySelector('select[name=wer]'); if(ws.options.length<=1 && D.personen) ws.innerHTML = '<option value="">Wer?</option>' + D.personen.map(x=>`<option ${x===wer()?"selected":""}>${x}</option>`).join("");
  const ul = document.getElementById("l"); ul.innerHTML = D.letzte.length ? "" : '<li class="hint">Noch keine Belege.</li>';
  for(const r of D.letzte){ const li = document.createElement("li"); const d = new Date(r.datum+"T00:00"); li.innerHTML = `<span class="d">${d.toLocaleDateString("de-DE",{day:"2-digit",month:"2-digit"})}</span><span class="l">${r.laden}<small>${r.kategorie}${r.wer?" · "+r.wer:""}${r.posten&&r.posten.length?" · "+r.posten.length+" Posten":""}${r.quelle==="scan"?" · 📷":""}</small></span><span class="e">${eur(r.summe)}<button title="löschen" data-id="${r.id}">✕</button></span>`;
    li.querySelector("button").onclick = async (e) => { if(!confirm(`${r.laden} ${eur(r.summe)} löschen?`)) return; await fetch(base+"/haushalt/del",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:r.id})}); load(); }; ul.appendChild(li); } }
const f = document.getElementById("f"), st = document.getElementById("st");
function openForm(v){ f.hidden = false; f.laden.value = v.laden||""; f.summe.value = v.summe!=null?v.summe:""; f.datum.value = v.datum||new Date().toISOString().slice(0,10); if(v.kategorie) f.kategorie.value = v.kategorie; POSTEN = v.posten||[]; const p = document.getElementById("posten"); p.hidden = !POSTEN.length; p.innerHTML = POSTEN.map(x=>`<div><span>${x.menge?x.menge+" ":""}${x.name}</span><span>${eur(x.preis)}</span></div>`).join(""); f.dataset.quelle = v.quelle||"manuell"; f.scrollIntoView({behavior:"smooth"}); }
document.getElementById("b-hand").onclick = () => openForm({});
document.getElementById("abbr").onclick = () => { f.hidden = true; st.textContent = ""; };
document.getElementById("b-scan").onclick = () => document.getElementById("file").click();
document.getElementById("file").onchange = async () => { const file = document.getElementById("file").files[0]; if(!file) return; st.textContent = "Kassenzettel wird gelesen …";
  const b64 = await new Promise(res => { const img = new Image(); img.onload = () => { const c = document.createElement("canvas"); const s = Math.min(1, 1600/Math.max(img.width,img.height)); c.width = img.width*s; c.height = img.height*s; c.getContext("2d").drawImage(img,0,0,c.width,c.height); res(c.toDataURL("image/jpeg",.85).split(",")[1]); }; img.src = URL.createObjectURL(file); });
  try { const r = await fetch(base+"/haushalt/scan",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({image:b64})}); const j = await r.json(); if(j.error){ st.textContent = j.error; return; } st.textContent = `Gelesen: ${j.laden||"?"} · ${eur(j.summe)} · ${(j.posten||[]).length} Posten – bitte prüfen und speichern.`; openForm(j); } catch(e){ st.textContent = "Fehler: " + e.message; } document.getElementById("file").value = ""; };
f.onsubmit = async (e) => { e.preventDefault(); const fd = new FormData(f); const body = Object.fromEntries(fd.entries()); body.summe = parseFloat(String(body.summe).replace(",", ".")); body.posten = POSTEN; body.quelle = f.dataset.quelle; if(!body.wer) body.wer = wer();
  const r = await fetch(base+"/haushalt/add",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}); const j = await r.json(); st.textContent = j.reply || "Gespeichert."; f.hidden = true; load(); };
load(); setInterval(load, 60000);
</script></body></html>"""

class H(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8", ".webmanifest": "application/manifest+json", ".svg": "image/svg+xml", ".png": "image/png"}
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)
    # --- Zugang: geheimer Pfad /<TOKEN>/... ODER Cookie nach PIN-Eingabe auf der Startseite ---
    def _cookie_ok(self):
        c = self.headers.get("Cookie", "")
        m = re.search(r"(?:^|;\s*)tafel=([0-9a-f]+)", c)
        return bool(m) and hmac.compare_digest(m[1], COOKIE_SECRET)
    def _rel(self):
        """Pfad ohne Token-Präfix, oder None wenn kein Zugang."""
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        prefix = "/" + TOKEN
        if path == prefix or path.startswith(prefix + "/"):
            return path[len(prefix):] or "/"
        if self._cookie_ok():
            return path
        return None
    def translate_path(self, path):
        rel = self._rel()
        if rel is None:
            return os.path.join(ROOT, "__forbidden__")
        if rel == "/":
            rel = "/index.html"
        rel = posixpath.normpath(rel)
        full = os.path.join(ROOT, rel.lstrip("/"))
        return full if full.startswith(ROOT) else os.path.join(ROOT, "__forbidden__")
    def _einkauf_path(self):
        rel = self._rel()
        return rel[len("/einkauf"):] if rel and rel.startswith("/einkauf") else None
    def _html(self, body, code=200, extra=()):
        b = body.encode("utf-8")
        self.send_response(code)
        for k, v in extra:
            self.send_header(k, v)
        self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        rel = self._rel()
        if rel is None:
            path = self.path.split("?", 1)[0]
            if PIN and path in ("/", "/index.html", "/einkauf", "/einkauf/", "/haushalt", "/haushalt/", "/login"):
                return self._html(LOGIN_PAGE.replace("__MSG__", ""))
            self.send_response(404); self.end_headers(); return
        if rel == "/status":
            st = {"speicher": "datei", "pfad": os.environ.get("EINKAUF_STATE"), "mongodb_uri_gesetzt": bool(os.environ.get("MONGODB_URI")), "mongodb": None,
                  "pin": bool(PIN), "franklin_login": bool(os.environ.get("FRANKLIN_LOGIN")), "ki": LLM.anbieter()}
            if os.environ.get("MONGODB_URI"):
                try:
                    d = EINKAUF.SPEICHER.db(); d.command("ping")
                    st["speicher"] = "mongodb"; st["mongodb"] = {"db": d.name, "collections": {c: d[c].estimated_document_count() for c in sorted(d.list_collection_names())}}
                except Exception as e:
                    st["mongodb"] = f"FEHLER: {type(e).__name__}: {str(e)[:200]}"
            return self._json(st)
        if rel == "/logout":
            return self._html("<meta http-equiv=refresh content='0;url=/'>Abgemeldet.", extra=[("Set-Cookie", "tafel=; Max-Age=0; Path=/")])
        if rel in ("/haushalt", "/haushalt/"):
            return self._html(HAUSHALT_PAGE)
        sub = self._einkauf_path()
        if sub in ("", "/"):
            body = PHONE_PAGE.encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if sub == "/add" and "text=" in (self.path.split("?", 1) + [""])[1]:
            q = urllib.parse.parse_qs(self.path.split("?", 1)[1])
            return self._apply(q.get("text", [""])[0], who=(q.get("wer", [""])[0].strip()[:20] or "Handy"))
        if sub and sub.startswith("/ean/"):
            return self._json(ean_lookup(sub[5:]))
        if sub == "/push/key":
            return self._json({"key": _push_keys()["public"]})
        super().do_GET()
    def _haushalt(self, rel):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 8_000_000:
            self.send_response(413); self.end_headers(); return
        try:
            form = json.loads(self.rfile.read(n).decode("utf-8", "ignore") or "{}")
        except Exception:
            form = {}
        if rel == "/haushalt/scan":
            try:
                return self._json(HAUSHALT.scan(form.get("image", "")))
            except Exception as e:
                return self._json({"error": f"Scan fehlgeschlagen: {e}"})
        with LOCK:
            if rel == "/haushalt/add":
                e = HAUSHALT.add(form)
                # Posten vom Beleg mit der Einkaufsliste abgleichen und abhaken
                abgehakt = []
                try:
                    st = EINKAUF.load(); namen = {i["name"].lower(): i["name"] for i in st["items"]}
                    for p in e.get("posten") or []:
                        pn = p["name"].lower()
                        for low, name in list(namen.items()):
                            if low in pn or (len(low) > 3 and pn.startswith(low[:4])):
                                EINKAUF.apply_message(st, "x " + name, e.get("wer") or "Beleg"); abgehakt.append(name); namen.pop(low, None)
                    if abgehakt:
                        EINKAUF.save(st); EINKAUF.export(st, os.path.join(ROOT, "einkauf.json"))
                except Exception as ex:
                    print("beleg→liste:", ex, flush=True)
                out = HAUSHALT.export(os.path.join(ROOT, "haushalt.json"))
                try:
                    budget_meldungen(out)
                except Exception as ex:
                    print("budget push:", ex, flush=True)
                return self._json({"ok": True, "eintrag": e, "reply": f"Gespeichert: {e['laden']} {e['summe']:.2f} €".replace(".", ",") + (f" · abgehakt: {', '.join(abgehakt)}" if abgehakt else "")})
            if rel == "/haushalt/del":
                n = HAUSHALT.delete(form.get("id", "")); HAUSHALT.export(os.path.join(ROOT, "haushalt.json"))
                return self._json({"ok": bool(n)})
        self.send_response(404); self.end_headers()
    def do_POST(self):
        rel0 = self._rel()
        if rel0 and rel0.startswith("/haushalt/"):
            return self._haushalt(rel0)
        if self.path.split("?", 1)[0] == "/login":
            n = int(self.headers.get("Content-Length") or 0)
            pin = urllib.parse.parse_qs(self.rfile.read(min(n, 4096)).decode("utf-8", "ignore")).get("pin", [""])[0]
            if PIN and hmac.compare_digest(pin.encode(), PIN.encode()):
                secure = "; Secure" if self.headers.get("X-Forwarded-Proto", "https") == "https" else ""
                return self._html("<meta http-equiv=refresh content='0;url=/'>Willkommen.", extra=[("Set-Cookie", f"tafel={COOKIE_SECRET}; Max-Age={COOKIE_AGE}; Path=/; HttpOnly; SameSite=Lax{secure}")])
            time.sleep(1.5)                               # bremst Durchprobieren
            return self._html(LOGIN_PAGE.replace("__MSG__", "Falsche PIN."), code=401)
        sub = self._einkauf_path()
        if sub not in ("/add", "/photo", "/claim", "/nehmen", "/push/subscribe", "/push/unsubscribe"):
            self.send_response(404); self.end_headers(); return
        n = int(self.headers.get("Content-Length") or 0)
        if n > 6_000_000:
            self.send_response(413); self.end_headers(); return
        raw = self.rfile.read(n).decode("utf-8", "ignore")
        ctype = self.headers.get("Content-Type", "")
        if sub == "/photo":
            try:
                return self._json(photo_items(json.loads(raw).get("image", "")))
            except Exception as e:
                return self._json({"error": f"Foto-Erkennung fehlgeschlagen: {e}"})
        form = json.loads(raw) if "json" in ctype else {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}
        who = (form.get("wer") or "").strip()[:20] or "Tafel"
        if sub == "/push/subscribe":
            if not (isinstance(form.get("subscription"), dict) and form["subscription"].get("endpoint")):
                return self._json({"error": "subscription fehlt"}, 400)
            _push_abo_set(form["subscription"], who if who != "Tafel" else "", (form.get("geraet") or "")[:60]); return self._json({"ok": True})
        if sub == "/push/unsubscribe":
            _push_abo_del((form.get("endpoint") or "")); return self._json({"ok": True})
        if sub == "/claim":
            return self._apply(None, who=who, claim=(form.get("kat") or "alle"))
        if sub == "/nehmen":
            return self._apply(None, who=who, nehmen=(form.get("name") or ""))
        text = form.get("text", "")
        if form.get("sprache"):
            text = gesprochen_zerlegen(text)
        self._apply(text, who=who)
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def _apply(self, text, who="Handy", claim=None, nehmen=None):
        with LOCK:
            state = EINKAUF.load()
            reply = EINKAUF.claim(state, claim, who) if claim else (EINKAUF.nehmen(state, nehmen, who) if nehmen else EINKAUF.apply_message(state, text or "", who))
            EINKAUF.save(state)
            try:
                if reply.startswith("Dazu: "): push_event(who, "dazu", reply[6:])
                elif reply.startswith("Abgehakt: "): push_event(who, "abgehakt", reply[10:])
                elif reply.startswith("Liste geleert"): push_event(who, "geleert", "")
                elif " kauft " in reply and nehmen: push_event(who, "nimmt", reply.split(" kauft ", 1)[1].rstrip("."))
                elif " übernimmt " in reply:
                    n_items = len([i for i in state["items"] if i.get("wer_kauft") == who])
                    was = {"alle": "den ganzen Einkauf", "vorrat": "Vorrat / Discounter", "frisch": "Frisch / Markt", "drogerie": "Drogerie & Haushalt"}.get(claim, claim)
                    push_sofort(who, "Einkauf übernommen", f"{who} übernimmt {was} – {n_items} Artikel")
                elif reply.startswith("Freigegeben") and claim == "alle": push_sofort(who, "Einkauf freigegeben", f"{who} gibt den Einkauf wieder frei")
            except Exception as e:
                print("push event:", e, flush=True)
            EINKAUF.export(state, os.path.join(ROOT, "einkauf.json"))
            out = json.load(open(os.path.join(ROOT, "einkauf.json"), encoding="utf-8")); out["reply"] = reply
        body = json.dumps(out, ensure_ascii=False).encode("utf-8")
        self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Robots-Tag", "noindex")
        super().end_headers()
    def log_message(self, fmt, *args):
        if "404" in str(args) or "data.json" in str(args) or "einkauf.json" in str(args):
            return
        super().log_message(fmt, *args)

http.server.ThreadingHTTPServer.allow_reuse_address = True
with http.server.ThreadingHTTPServer(("0.0.0.0", PORT), H) as s:
    print(f"Tafel auf Port {PORT}, Pfad /{TOKEN}/", flush=True)
    s.serve_forever()
