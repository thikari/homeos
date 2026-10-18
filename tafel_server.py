#!/usr/bin/env python3
"""Minimaler Webserver für die Energie-Tafel.
Liefert www/ nur unter dem geheimen Pfad /<TAFEL_TOKEN>/ aus, alles andere 404. Keine Caches, damit data.json immer frisch ist."""
import os, sys, http.server, posixpath, json, urllib.parse, importlib.util, threading

TOKEN = os.environ.get("TAFEL_TOKEN", "").strip("/")
PORT = int(os.environ.get("TAFEL_PORT", "8787"))
ROOT = os.path.abspath(os.environ.get("TAFEL_ROOT", "."))
if not TOKEN:
    sys.exit("TAFEL_TOKEN fehlt")
HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("einkauf", os.path.join(HERE, "einkauf.py")); EINKAUF = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(EINKAUF)
LOCK = threading.Lock()

PHONE_PAGE = r"""<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="default"><title>Einkauf</title>
<style>
:root{--fg:#0f2a4a;--muted:#5f7691;--line:#d9e3ee;--soft:#edf3f9;--good:#16a35a;--bad:#2a6fdb}
body{margin:0;font-family:-apple-system,"Manrope",system-ui,sans-serif;color:var(--fg);background:#fff;padding:env(safe-area-inset-top) 16px 24px}
h1{font-size:1.1rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin:1.2rem 0 .8rem}
form{display:flex;gap:.5rem;margin-bottom:1rem}
input{flex:1;font:inherit;font-size:1.1rem;padding:.75rem .9rem;border:1.5px solid var(--line);border-radius:12px;min-width:0}
ul{list-style:none;margin:0;padding:0}
li{display:flex;align-items:center;gap:.8rem;padding:.8rem 0;border-bottom:1px solid var(--line);font-size:1.15rem;font-weight:600}
li i{width:1.3rem;height:1.3rem;border:2px solid var(--line);border-radius:6px;flex:none}
li small{display:block;font-size:.8rem;font-weight:500;color:var(--muted)}
li small b{color:var(--good)}
li.done{opacity:.35;text-decoration:line-through}
li.kat{font-size:.72rem;letter-spacing:.12em;text-transform:uppercase;color:var(--bad);font-weight:700;border:0;padding:1.1rem 0 .2rem}
.leer{color:var(--muted);font-weight:500}
.hint{color:var(--muted);font-size:.85rem;margin-top:1.2rem;line-height:1.5}
.row{display:flex;justify-content:space-between;align-items:center}
.row a{color:var(--bad);font-size:.9rem;text-decoration:none}
</style></head><body>
<div class="row"><h1>Einkaufsliste</h1><a href="#" id="clear">leeren</a></div>
<div id="ek"></div>
<ul id="l"><li class="leer">Lade …</li></ul>
<p class="hint">Antippen hakt ab. Tippen · Sprechen · Foto · Barcode – alles landet auf der Liste, die auch auf der Tafel steht.</p>
<script src="../einkauf.js"></script>
<script>
const base = location.pathname.replace(/\/einkauf\/?$/, "");
async function load(){ const r = await fetch(base + "/einkauf.json", {cache:"no-store"}); const j = await r.json(); render(j); }
const KAT = [["vorrat","Vorrat · Discounter"],["frisch","Frisch · Markt / Supermarkt"],["drogerie","Drogerie & Haushalt"]];
function render(j){ const ul = document.getElementById("l"); ul.innerHTML = ""; if(!j.items.length){ ul.innerHTML = '<li class="leer">Noch nichts auf der Liste</li>'; return; }
  for(const [k,label] of KAT){ const its = j.items.filter(it => (it.kat||"vorrat") === k); if(!its.length) continue;
    const h = document.createElement("li"); h.className = "kat"; h.textContent = label; ul.appendChild(h);
    for(const it of its){ const best = (it.offers||[]).filter(o=>!o.soon)[0]; const li = document.createElement("li"); li.innerHTML = `<i></i><span>${it.name}${best?`<small><b>${best.store}</b> ${best.price.toLocaleString("de-DE",{minimumFractionDigits:2})} €</small>`:""}</span>`;
      li.onclick = async () => { li.classList.add("done"); await send("x " + it.name); }; ul.appendChild(li); } } }
async function send(text){ const r = await fetch(base + "/einkauf/add", {method:"POST", headers:{"Content-Type":"application/x-www-form-urlencoded"}, body:"text="+encodeURIComponent(text)}); if(r.ok) render(await r.json()); }
initEinkauf({ mount: document.getElementById("ek"), base, onUpdate: render });
document.getElementById("clear").onclick = async e => { e.preventDefault(); if(document.getElementById("clear").dataset.ok){ await send("leer"); delete document.getElementById("clear").dataset.ok; document.getElementById("clear").textContent="leeren"; } else { document.getElementById("clear").dataset.ok="1"; document.getElementById("clear").textContent="wirklich leeren?"; setTimeout(()=>{delete document.getElementById("clear").dataset.ok; document.getElementById("clear").textContent="leeren";},3000);} };
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
    """Foto → Liste von Produktnamen über die Claude-API (Schlüssel ANTHROPIC_API_KEY)."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return {"error": "Foto-Erkennung ist nicht eingerichtet (ANTHROPIC_API_KEY fehlt in Railway)."}
    if not b64:
        return {"error": "Kein Bild erhalten."}
    import urllib.request
    prompt = ("Das ist ein Foto aus einem Haushalt in Deutschland: ein Produkt, eine Verpackung, ein Kühlschrank- oder Vorratsregal oder ein handgeschriebener Zettel. "
              "Nenne die Lebensmittel bzw. Haushaltsartikel, die man auf eine Einkaufsliste setzen würde – bei einer Verpackung das Produkt (kurz, wie man es auf eine Liste schreibt, z. B. 'Haltbare Milch 1,5 %'), "
              "bei einem Zettel die aufgeschriebenen Artikel, bei einem Regal die erkennbaren Produkte. Antworte NUR mit einem JSON-Array aus Strings auf Deutsch, maximal 12 Einträge, keine Erklärung.")
    body = {"model": os.environ.get("TAFEL_VISION_MODEL", "claude-haiku-5-5"), "max_tokens": 300,
            "messages": [{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}}, {"type": "text", "text": prompt}]}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(), method="POST",
                                 headers={"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        j = json.load(r)
    text = "".join(c.get("text", "") for c in j.get("content", []))
    m = text[text.find("["): text.rfind("]") + 1]
    items = json.loads(m) if m else []
    items = [str(x).strip() for x in items if str(x).strip()][:12]
    return {"items": items}

class H(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8"}
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)
    def translate_path(self, path):
        path = path.split("?", 1)[0].split("#", 1)[0]
        prefix = "/" + TOKEN
        if path != prefix and not path.startswith(prefix + "/"):
            return os.path.join(ROOT, "__forbidden__")
        rel = path[len(prefix):] or "/"
        if rel == "/":
            rel = "/index.html"
        rel = posixpath.normpath(rel)
        full = os.path.join(ROOT, rel.lstrip("/"))
        return full if full.startswith(ROOT) else os.path.join(ROOT, "__forbidden__")
    def _einkauf_path(self):
        path = self.path.split("?", 1)[0]
        prefix = "/" + TOKEN + "/einkauf"
        return path[len(prefix):] if path.startswith(prefix) else None
    def do_GET(self):
        sub = self._einkauf_path()
        if sub in ("", "/"):
            body = PHONE_PAGE.encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if sub == "/add" and "text=" in (self.path.split("?", 1) + [""])[1]:
            return self._apply(urllib.parse.parse_qs(self.path.split("?", 1)[1]).get("text", [""])[0])
        if sub and sub.startswith("/ean/"):
            return self._json(ean_lookup(sub[5:]))
        super().do_GET()
    def do_POST(self):
        sub = self._einkauf_path()
        if sub not in ("/add", "/photo"):
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
        text = json.loads(raw).get("text", "") if "json" in ctype else urllib.parse.parse_qs(raw).get("text", [""])[0]
        self._apply(text)
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def _apply(self, text):
        with LOCK:
            state = EINKAUF.load()
            reply = EINKAUF.apply_message(state, text or "", "Handy")
            EINKAUF.save(state)
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
