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
def _budgets():
    """HAUSHALT_BUDGETS="Lebensmittel=450,Drogerie=80,Kinder=120,Gastro=100,Haushalt=60,Mobilität=60" (Rest = Sonstiges)."""
    b = {"Lebensmittel": 450, "Drogerie": 80, "Haushalt": 60, "Kinder": 120, "Mobilität": 60, "Gastro": 100}
    for part in os.environ.get("HAUSHALT_BUDGETS", "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            try:
                b[k.strip()] = float(v.replace(",", "."))
            except ValueError:
                pass
    b["Sonstiges"] = max(0.0, BUDGET - sum(v for k, v in b.items() if k != "Sonstiges"))
    return b
BUDGETS = _budgets()

# Produktarten je Posten (Schlüsselwörter, Wortanfang) – die KI darf auch direkt eine davon vergeben
PRODUKT_KATS = ["Obst & Gemüse", "Milch & Käse", "Fleisch & Fisch", "Brot & Backwaren", "Grundnahrung", "Fertig & TK", "Getränke", "Snacks & Süßes", "Kinder", "Drogerie", "Haushalt", "Pfand & Rabatt", "Sonstiges"]
_PK = {
 "Obst & Gemüse": ["tomat", "gurke", "salat", "paprika", "zwiebel", "knoblauch", "kartoffel", "karott", "möhre", "brokkoli", "blumenkohl", "zucchini", "aubergine", "spinat", "pilz", "champignon", "lauch", "kräuter", "avocado", "apfel", "äpfel", "banane", "birne", "traube", "beere", "zitrone", "limette", "orange", "mandarine", "mango", "melone", "kiwi", "pfirsich", "pflaume", "kirsche", "obst", "gemüse", "ingwer", "salat"],
 "Milch & Käse": ["milch", "käse", "kaese", "joghurt", "jogurt", "quark", "sahne", "butter", "frischkäse", "mozzarella", "feta", "gouda", "emmentaler", "schmand", "creme fraiche", "skyr", "ei ", "eier"],
 "Fleisch & Fisch": ["hähnchen", "haehnchen", "hack", "pute", "rind", "schwein", "lamm", "wurst", "schinken", "salami", "speck", "fisch", "lachs", "forelle", "garnele", "thunfisch", "steak", "schnitzel", "bratwurst", "fleisch"],
 "Brot & Backwaren": ["brot", "brötchen", "broetchen", "baguette", "croissant", "toast", "brezel", "kuchen", "laugen", "semmel", "knäcke"],
 "Grundnahrung": ["nudel", "spaghetti", "penne", "reis", "mehl", "zucker", "salz", "pfeffer", "öl", "oel", "essig", "ketchup", "senf", "mayo", "haferfl", "müsli", "muesli", "cornflakes", "marmelade", "honig", "nutella", "erdnuss", "tomatenmark", "passata", "dosen", "kichererbs", "linsen", "bohnen", "mais", "pesto", "brühe", "gewürz", "kokos", "kaffee", "tee ", "kakao", "soße", "sauce", "konserve"],
 "Fertig & TK": ["pizza", "pommes", "fischstäb", "tiefkühl", "tk ", "fertig", "lasagne", "suppe", "eis "],
 "Getränke": ["wasser", "sprudel", "cola", "limo", "saft", "apfelschorle", "schorle", "bier", "wein", "sekt", "radler", "energy", "eistee", "mineralw"],
 "Snacks & Süßes": ["chips", "schokolade", "schoko", "gummib", "haribo", "kekse", "keks", "bonbon", "riegel", "nüsse", "erdnüsse", "cracker", "süß", "kinderriegel", "milka", "pralin"],
 "Kinder": ["windel", "feuchttüch", "babybrei", "babynahr", "pre-milch", "pre milch", "hipp", "alete", "schnuller", "spielzeug", "kinderwag"],
 "Drogerie": ["zahnpast", "zahnbürst", "shampoo", "duschgel", "seife", "deo", "rasier", "creme", "sonnencr", "wattest", "taschentüch", "tampon", "binden", "pflaster", "vitamin", "medikament", "apotheke"],
 "Haushalt": ["klopapier", "toilettenpap", "küchenrol", "spülmittel", "spuelm", "spültab", "waschmittel", "weichsp", "reiniger", "putz", "müllbeut", "schwamm", "alufolie", "frischhalte", "backpapier", "batterie", "glühbirne", "kerze", "blumen", "lampe", "staubsaug"],
 "Pfand & Rabatt": ["pfand", "rabatt", "coupon", "gutschein", "leergut", "aktion", "payback"],
}
def produkt_kat(name, preis=None):
    n = (name or "").lower()
    if preis is not None and preis < 0:
        return "Pfand & Rabatt"
    for kat in ("Pfand & Rabatt", "Kinder", "Drogerie", "Haushalt", "Snacks & Süßes", "Getränke", "Fertig & TK", "Fleisch & Fisch", "Milch & Käse", "Brot & Backwaren", "Grundnahrung", "Obst & Gemüse"):
        if any(w in n for w in _PK[kat]):
            return kat
    return "Sonstiges"

def produkt_norm(name):
    """Produktname für Preisverlauf vereinheitlichen: klein, Mengen-/Prozentangaben weg, Füllzeichen weg."""
    n = re.sub(r"\d+([.,]\d+)?\s*(kg|g|l|ml|st|stk|x|%|er)\b", " ", (name or "").lower())
    n = re.sub(r"[^a-zäöüß ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()[:40]
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
         "wer": (entry.get("wer") or "")[:20], "posten": [{"name": str(p.get("name", ""))[:60], "preis": round(float(p.get("preis") or 0), 2), "menge": p.get("menge"),
                     "kat": p.get("kat") if p.get("kat") in PRODUKT_KATS else produkt_kat(p.get("name"), float(p.get("preis") or 0))} for p in (entry.get("posten") or []) if p.get("name")][:80],
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
def kat_budgets(monat, tag, tage):
    ist = {}
    for r in monat:
        ist[r.get("kategorie") or "Sonstiges"] = ist.get(r.get("kategorie") or "Sonstiges", 0) + r["summe"]
    out = []
    for k in KATEGORIEN:
        b = BUDGETS.get(k, 0)
        out.append({"name": k, "eur": round(ist.get(k, 0), 2), "budget": b, "pct": round(ist.get(k, 0) / b * 100) if b else None, "soll": round(b * tag / tage, 2)})
    return out

def produkt_summen(monat):
    d = {}
    for r in monat:
        ps = r.get("posten") or []
        if not ps:                                       # Beleg ohne Posten → ganze Summe nach Belegkategorie
            k = {"Drogerie": "Drogerie", "Haushalt": "Haushalt", "Kinder": "Kinder"}.get(r.get("kategorie"), "Sonstiges")
            d[k] = d.get(k, 0) + r["summe"]; continue
        for p in ps:
            k = p.get("kat") or produkt_kat(p.get("name"), p.get("preis"))
            d[k] = d.get(k, 0) + (p.get("preis") or 0)
        rest = r["summe"] - sum(p.get("preis") or 0 for p in ps)
        if abs(rest) >= 0.05:
            d["Nicht aufgeschlüsselt"] = d.get("Nicht aufgeschlüsselt", 0) + rest
    return [{"name": k, "eur": round(v, 2)} for k, v in sorted(d.items(), key=lambda x: -x[1]) if abs(v) >= 0.01]

def preisverlauf(rows, n=20):
    """Produkte, die mehrfach gekauft wurden: letzter Preis, günstigster Laden, Spanne."""
    hist = {}
    for r in sorted(rows, key=lambda r: r["datum"]):
        for p in r.get("posten") or []:
            if (p.get("preis") or 0) <= 0:
                continue
            key = produkt_norm(p["name"])
            if len(key) < 3:
                continue
            h = hist.setdefault(key, {"name": p["name"], "kaeufe": []})
            h["kaeufe"].append({"d": r["datum"], "laden": r.get("laden"), "preis": p["preis"]})
    out = []
    for key, h in hist.items():
        k = h["kaeufe"]
        if len(k) < 2:
            continue
        preise = [x["preis"] for x in k]
        bill = min(k, key=lambda x: x["preis"]); teuer = max(k, key=lambda x: x["preis"])
        out.append({"name": h["name"], "n": len(k), "letzter": k[-1]["preis"], "letzter_laden": k[-1]["laden"], "min": bill["preis"], "min_laden": bill["laden"], "max": teuer["preis"], "max_laden": teuer["laden"],
                    "spanne": round(teuer["preis"] - bill["preis"], 2), "kat": produkt_kat(h["name"])})
    out.sort(key=lambda x: (-x["spanne"], -x["n"]))
    return out[:n]

def export(outp):
    rows = load_all()
    for r in rows:
        for p in r.get("posten") or []:
            if not p.get("kat"):
                p["kat"] = produkt_kat(p.get("name"), p.get("preis"))
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
    out = {"updated": dt.datetime.now().isoformat(timespec="minutes"), "budget": BUDGET, "kategorien": KATEGORIEN, "produkt_kats": PRODUKT_KATS,
           "personen": [x.strip() for x in os.environ.get("EINKAUF_PERSONEN", "Tobi,Julia").split(",") if x.strip()],
           "monat": {"ym": ym, "eur": summe(monat), "belege": len(monat), "tag": heute.day, "tage": tage_im_monat.day,
                     "soll_bis_heute": round(BUDGET * heute.day / tage_im_monat.day, 2), "prognose": round(summe(monat) / heute.day * tage_im_monat.day, 2) if heute.day >= 3 else None,
                     "kategorien": nach(monat, "kategorie"), "laeden": nach(monat, "laden"), "wer": nach(monat, "wer", 4),
                     "budgets": kat_budgets(monat, heute.day, tage_im_monat.day),
                     "produkte": produkt_summen(monat)},
           "preise": preisverlauf(rows),
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
              '"posten": [{"name": "Artikel kurz", "preis": Zahl, "menge": "z. B. 2x oder 0,5 kg oder null", "kat": eine von ' + json.dumps(PRODUKT_KATS, ensure_ascii=False) + '}], "kategorie": eine von ' + json.dumps(KATEGORIEN, ensure_ascii=False) + '}. '
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
            pr = round(float(str(p.get("preis", 0)).replace(",", ".")), 2)
            posten.append({"name": str(p.get("name", "")).strip()[:60], "preis": pr, "menge": p.get("menge"), "kat": p.get("kat") if p.get("kat") in PRODUKT_KATS else produkt_kat(p.get("name"), pr)})
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
