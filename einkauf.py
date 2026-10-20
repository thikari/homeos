#!/usr/bin/env python3
"""Einkaufsliste + Sonderangebote (marktguru) für die Energie-Tafel.

Die Liste wird über die Handy-Seite /<token>/einkauf/ gepflegt (tafel_server.py ruft apply_message auf):
    "Milch, Eier, Windeln"   → hinzufügen (Komma oder Zeilenumbruch trennt)
    "x Milch" / "- Milch"    → abhaken (Teilstring reicht)
    "leer"                   → Liste leeren
Angebote: marktguru-Web-API (Schlüssel von marktguru.de, kein Account). PLZ über ANGEBOTE_PLZ, Standard 68309.
"""
import os, sys, json, re, time, urllib.request, urllib.parse, datetime as dt, importlib.util
_sp = importlib.util.spec_from_file_location("speicher", os.path.join(os.path.dirname(os.path.abspath(__file__)), "speicher.py")); SPEICHER = importlib.util.module_from_spec(_sp); _sp.loader.exec_module(SPEICHER)

STATE = os.environ.get("EINKAUF_STATE", "einkauf_state.json")
PLZ = os.environ.get("ANGEBOTE_PLZ", "68309")
PERSONEN = [x.strip() for x in os.environ.get("EINKAUF_PERSONEN", "Tobi,Julia").split(",") if x.strip()]
MG_HEADERS = {"x-apikey": "8Kk+pmbf7TgJ9nVj2cXeA7P5zBGv8iuutVVMRfOfvNE=", "x-clientkey": "WU/RH+PMGDi+gkZer3WbMelt6zcYHSTytNB7VpTia90=",
              "User-Agent": "Mozilla/5.0", "Accept": "application/json"}
LAEDEN = {"Lidl", "ALDI SÜD", "REWE", "EDEKA", "Kaufland", "Netto Marken-Discount", "PENNY", "dm", "ROSSMANN", "Scheck-in Center"}

MONGO = os.environ.get("MONGODB_URI", "").strip()           # gesetzt → Liste in MongoDB (DB aus der URI oder "homeos", Collection "einkauf")
_col = None
def _mongo():
    global _col
    if _col is None:
        _col = SPEICHER.db()["einkauf"]
    return _col

LEER = {"items": [], "offset": 0, "offers": {}, "offers_at": None, "uebernahme": {}}

def load():
    if MONGO:
        try:
            doc = _mongo().find_one({"_id": "liste"}) or {}
            doc.pop("_id", None)
            return {**LEER, **doc} if doc else dict(LEER)
        except Exception as e:
            print("MongoDB load:", e, file=sys.stderr)
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return dict(LEER)

def save(s):
    if MONGO:
        try:
            _mongo().replace_one({"_id": "liste"}, {"_id": "liste", **s}, upsert=True)
            return
        except Exception as e:
            print("MongoDB save:", e, file=sys.stderr)
    tmp = STATE + ".tmp"; json.dump(s, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1); os.replace(tmp, STATE)

# Kategorien: Vorrat (Discounter), Frisch (Markt/Supermarkt), Drogerie & Haushalt. Treffer über Wortanfänge.
KATEGORIEN = {
    "frisch": ["tomate", "gurke", "salat", "paprika", "zwiebel", "knoblauch", "kartoffel", "karotte", "möhre", "brokkoli", "blumenkohl", "zucchini", "aubergine", "spinat", "pilz", "champignon", "lauch", "kräuter", "petersilie", "basilikum", "avocado",
               "apfel", "äpfel", "banane", "birne", "traube", "beere", "erdbeere", "himbeere", "blaubeere", "heidelbeere", "zitrone", "limette", "orange", "mandarine", "mango", "melone", "kiwi", "pfirsich", "pflaume", "kirsche", "obst", "gemüse",
               "brot", "brötchen", "baguette", "croissant", "kuchen", "brezel",
               "fleisch", "hack", "hähnchen", "huhn", "pute", "rind", "schwein", "lamm", "wurst", "schinken", "salami", "speck", "fisch", "lachs", "forelle", "garnele",
               "käse", "frischkäse", "mozzarella", "feta", "parmesan", "quark", "joghurt", "sahne", "butter", "ei", "eier", "tofu", "sushi", "salat"],
    "drogerie": ["windel", "feuchttücher", "zahnpasta", "zahnbürste", "shampoo", "duschgel", "seife", "deo", "rasier", "creme", "sonnencreme", "wattestäbchen", "taschentücher", "klopapier", "toilettenpapier", "küchenrolle",
                 "spülmittel", "waschmittel", "weichspüler", "spültab", "putz", "reiniger", "müllbeutel", "schwamm", "alufolie", "frischhaltefolie", "backpapier", "batterie", "glühbirne", "kerze", "blumen"],
}

# Englisch → Deutsch für Suche und Einordnung (Julia schreibt auch auf Englisch). Längere Begriffe zuerst.
EN_DE = {
 "whole milk": "Vollmilch", "oat milk": "Hafermilch", "almond milk": "Mandelmilch", "milk": "Milch", "eggs": "Eier", "egg": "Eier", "butter": "Butter", "cheese": "Käse", "cream cheese": "Frischkäse",
 "yogurt": "Joghurt", "yoghurt": "Joghurt", "cream": "Sahne", "sour cream": "Schmand", "quark": "Quark", "bread": "Brot", "rolls": "Brötchen", "bread rolls": "Brötchen", "toast": "Toast", "flour": "Mehl", "sugar": "Zucker",
 "salt": "Salz", "pepper": "Pfeffer", "rice": "Reis", "pasta": "Nudeln", "noodles": "Nudeln", "spaghetti": "Spaghetti", "oats": "Haferflocken", "oatmeal": "Haferflocken", "cereal": "Müsli", "muesli": "Müsli",
 "coffee": "Kaffee", "tea": "Tee", "cocoa": "Kakao", "juice": "Saft", "apple juice": "Apfelsaft", "orange juice": "Orangensaft", "water": "Wasser", "sparkling water": "Sprudel", "beer": "Bier", "wine": "Wein",
 "apples": "Äpfel", "apple": "Apfel", "bananas": "Bananen", "banana": "Banane", "pears": "Birnen", "grapes": "Trauben", "strawberries": "Erdbeeren", "raspberries": "Himbeeren", "blueberries": "Blaubeeren",
 "lemons": "Zitronen", "lemon": "Zitrone", "limes": "Limetten", "oranges": "Orangen", "mandarins": "Mandarinen", "mango": "Mango", "melon": "Melone", "kiwi": "Kiwi", "peaches": "Pfirsiche", "plums": "Pflaumen", "cherries": "Kirschen", "fruit": "Obst",
 "tomatoes": "Tomaten", "tomato": "Tomaten", "cucumber": "Gurke", "lettuce": "Salat", "salad": "Salat", "peppers": "Paprika", "bell pepper": "Paprika", "onions": "Zwiebeln", "onion": "Zwiebel", "garlic": "Knoblauch",
 "potatoes": "Kartoffeln", "potato": "Kartoffeln", "carrots": "Karotten", "carrot": "Karotten", "broccoli": "Brokkoli", "cauliflower": "Blumenkohl", "zucchini": "Zucchini", "courgette": "Zucchini", "eggplant": "Aubergine", "aubergine": "Aubergine",
 "spinach": "Spinat", "mushrooms": "Champignons", "leek": "Lauch", "herbs": "Kräuter", "parsley": "Petersilie", "basil": "Basilikum", "avocado": "Avocado", "vegetables": "Gemüse", "veggies": "Gemüse", "sweet potato": "Süßkartoffel", "corn": "Mais", "peas": "Erbsen", "beans": "Bohnen",
 "chicken": "Hähnchen", "chicken breast": "Hähnchenbrust", "turkey": "Pute", "beef": "Rindfleisch", "pork": "Schweinefleisch", "minced meat": "Hackfleisch", "ground beef": "Hackfleisch", "mince": "Hackfleisch", "meat": "Fleisch", "sausage": "Wurst", "sausages": "Würstchen", "ham": "Schinken", "bacon": "Speck", "salami": "Salami",
 "fish": "Fisch", "salmon": "Lachs", "tuna": "Thunfisch", "shrimp": "Garnelen", "prawns": "Garnelen", "tofu": "Tofu",
 "ketchup": "Ketchup", "mustard": "Senf", "mayo": "Mayonnaise", "mayonnaise": "Mayonnaise", "olive oil": "Olivenöl", "oil": "Öl", "vinegar": "Essig", "honey": "Honig", "jam": "Marmelade", "peanut butter": "Erdnussbutter", "chocolate spread": "Nussnougatcreme", "nutella": "Nutella",
 "chocolate": "Schokolade", "cookies": "Kekse", "biscuits": "Kekse", "crisps": "Chips", "chips": "Chips", "gummy bears": "Gummibärchen", "sweets": "Süßigkeiten", "candy": "Süßigkeiten", "ice cream": "Eis", "pizza": "Pizza", "fries": "Pommes", "fish fingers": "Fischstäbchen", "fish sticks": "Fischstäbchen",
 "canned tomatoes": "Dosentomaten", "chopped tomatoes": "Dosentomaten", "tomato paste": "Tomatenmark", "chickpeas": "Kichererbsen", "lentils": "Linsen", "coconut milk": "Kokosmilch", "stock": "Brühe", "broth": "Brühe", "pesto": "Pesto", "soy sauce": "Sojasoße",
 "diapers": "Windeln", "nappies": "Windeln", "wipes": "Feuchttücher", "baby wipes": "Feuchttücher", "baby food": "Babynahrung", "formula": "Babymilch", "toothpaste": "Zahnpasta", "toothbrush": "Zahnbürste", "shampoo": "Shampoo", "shower gel": "Duschgel", "soap": "Seife", "deodorant": "Deo", "deo": "Deo",
 "razor": "Rasierer", "razor blades": "Rasierklingen", "lotion": "Creme", "sunscreen": "Sonnencreme", "cotton buds": "Wattestäbchen", "tissues": "Taschentücher", "toilet paper": "Toilettenpapier", "loo roll": "Toilettenpapier", "kitchen roll": "Küchenrolle", "paper towels": "Küchenrolle",
 "dish soap": "Spülmittel", "washing up liquid": "Spülmittel", "dishwasher tabs": "Spültabs", "laundry detergent": "Waschmittel", "detergent": "Waschmittel", "fabric softener": "Weichspüler", "cleaner": "Reiniger", "bin bags": "Müllbeutel", "trash bags": "Müllbeutel", "sponges": "Schwämme", "sponge": "Schwamm",
 "foil": "Alufolie", "aluminium foil": "Alufolie", "cling film": "Frischhaltefolie", "baking paper": "Backpapier", "batteries": "Batterien", "light bulb": "Glühbirne", "candles": "Kerzen", "flowers": "Blumen", "cat food": "Katzenfutter", "dog food": "Hundefutter",
}
_EN_KEYS = sorted(EN_DE, key=len, reverse=True)
_EN_FUELL = re.compile(r"^(some|a|an|the|pack of|bag of|bottle of|box of|two|three|\d+)\s+", re.I)

def deutsch(name):
    """Englischen Artikelnamen ins Deutsche übersetzen (für Angebotssuche/Kategorie). Unbekanntes bleibt wie es ist."""
    low = name.lower().strip()
    core = _EN_FUELL.sub("", low)
    for k in _EN_KEYS:
        if re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", core):
            return EN_DE[k]
    return name

def suchbegriff(item):
    return item.get("q") or deutsch(item["name"])

def kategorie(name):
    n = deutsch(name).lower()
    if any(re.search(r"(?<![a-zäöüß])" + re.escape(w), n) for w in VORRAT_WOERTER if w not in ("spinat", "windeln", "feuchttücher", "klopapier", "toilettenpapier")):
        return "vorrat"
    for kat, woerter in KATEGORIEN.items():
        if any(n.startswith(w) or (" " + w) in (" " + n) for w in woerter):
            return kat
    return "vorrat"

# Bekannte Artikel (für die Zerlegung diktierter Sätze ohne Kommas). Längere zuerst, damit "Haltbare Milch" vor "Milch" greift.
VORRAT_WOERTER = ["haltbare milch", "hafermilch", "mandelmilch", "milch", "nudeln", "spaghetti", "penne", "reis", "mehl", "zucker", "salz", "pfeffer", "öl", "olivenöl", "essig", "ketchup", "senf", "mayo", "mayonnaise",
                  "kaffee", "tee", "kakao", "müsli", "haferflocken", "cornflakes", "marmelade", "honig", "nutella", "nussnougatcreme", "erdnussbutter", "toast", "knäckebrot", "zwieback", "kekse", "chips", "schokolade", "gummibärchen",
                  "wasser", "sprudel", "cola", "saft", "apfelsaft", "orangensaft", "bier", "wein", "sekt", "dosentomaten", "passierte tomaten", "tomatenmark", "kichererbsen", "linsen", "bohnen", "mais", "thunfisch", "pesto", "brühe",
                  "kokosmilch", "soja", "tiefkühlpizza", "pizza", "pommes", "fischstäbchen", "eis", "erbsen", "spinat", "katzenfutter", "hundefutter", "babybrei", "babynahrung", "windeln", "feuchttücher", "klopapier", "toilettenpapier"]
ALLE_WOERTER = sorted(set(VORRAT_WOERTER + KATEGORIEN["frisch"] + KATEGORIEN["drogerie"] + ["eier", "butter", "joghurt", "quark", "sahne", "käse", "brot", "brötchen", "wurst", "schinken", "hähnchen", "hackfleisch", "lachs"]), key=len, reverse=True)
FUELL = re.compile(r"^(bitte|noch|auch|wir brauchen|ich brauche|brauchen wir|kaufen|einkaufen|und|dann|außerdem|ein|eine|einen|etwas|ein paar|bisschen|päckchen|packung)\s+", re.I)
MENGE = r"(?:\d+|ein|eine|einen|zwei|drei|vier|fünf|sechs|zehn)?\s*(?:liter|kilo|kg|gramm|g|flaschen?|packungen?|päckchen|dosen?|stück|becher|tüten?|kisten?|bund|netz)?\s*"

def zerlege_gesprochen(t):
    """'Milch Eier und zwei Liter Apfelsaft Windeln' → 'Milch\nEier\n2 Liter Apfelsaft\nWindeln'. Erst an Kommas/und trennen, dann Reste an bekannten Artikelnamen."""
    teile = []
    for part in re.split(r"\s*(?:,|;|\bund\b|\bsowie\b|\bdann\b|\bplus\b|\boder\b)\s*", t, flags=re.I):
        part = part.strip()
        if not part:
            continue
        rest = part
        while rest:
            rest = FUELL.sub("", rest).strip()
            if not rest:
                break
            low = rest.lower()
            # nächstes bekanntes Wort finden; alles davor gehört (als Menge/Adjektiv) dazu, wenn kurz
            best = None
            for w in ALLE_WOERTER:
                m = re.search(r"(?<![a-zäöüß])" + re.escape(w) + r"[a-zäöüß]*", low)
                if m and (best is None or m.start() < best.start()):
                    best = m
            if best is None:
                teile.append(rest); break
            vor = rest[:best.start()].strip()
            name = rest[best.start():best.end()]
            if vor and len(vor.split()) <= 3 and re.fullmatch(MENGE + r"[a-zäöüß-]*", vor.lower()):
                name = (vor + " " + name).strip()
            elif vor:
                teile.append(vor)
            teile.append(name)
            rest = rest[best.end():].strip()
    teile = [re.sub(r"\s+(bitte|danke|noch|auch)$", "", x.strip(), flags=re.I) for x in teile]
    teile = [x for x in teile if x and not re.fullmatch(r"(bitte|danke|noch|auch|das|war|wars|das wars|fertig|ende)", x, re.I)]
    zahl = {"ein": "1", "eine": "1", "einen": "1", "zwei": "2", "drei": "3", "vier": "4", "fünf": "5", "sechs": "6", "zehn": "10"}
    out = []
    for x in teile:
        x = re.sub(r"^(ein|eine|einen|zwei|drei|vier|fünf|sechs|zehn)\b", lambda m: zahl[m[1].lower()], x.strip(), flags=re.I)
        x = re.sub(r"^1\s+(?!liter|kilo|kg|flasche|packung|dose|stück|becher|tüte|kiste)", "", x, flags=re.I)
        if x: out.append(x)
    return "\n".join(out)

def norm(s):
    s = s.strip().strip(".;,")
    return s[:1].upper() + s[1:] if s else s

def apply_message(state, text, who):
    t = text.strip()
    low = t.lower()
    items = state["items"]
    if low in ("leer", "clear", "/leer", "/clear"):
        state["items"] = []; state["uebernahme"] = {}; SPEICHER.log_einkauf("geleert", who); return "Liste geleert."
    if low in ("liste", "/liste", "/list", "/start"):
        return "Einkaufsliste:\n" + ("\n".join("• " + i["name"] for i in items) if items else "(leer)")
    m = re.match(r"^(x|-|✓|✔|done|weg|erledigt)\s+(.+)$", t, re.I)
    if m:
        q = m[2].strip().lower(); before = len(items)
        for i in items:
            if q in i["name"].lower():
                SPEICHER.log_einkauf("abgehakt", who, i["name"], i.get("kat"), i.get("q"))
        state["items"] = [i for i in items if q not in i["name"].lower()]
        n = before - len(state["items"])
        return f"Abgehakt: {m[2].strip()}" if n else f"„{m[2].strip()}“ steht nicht auf der Liste."
    added = []
    forced = None
    mk = re.match(r"^(frisch|vorrat|discounter|drogerie|haushalt)\s*:\s*(.+)$", t, re.I | re.S)
    if mk:
        forced = {"discounter": "vorrat", "haushalt": "drogerie"}.get(mk[1].lower(), mk[1].lower()); t = mk[2]
    for part in re.split(r"[,\n;]+", t):
        kat = forced
        pm = re.match(r"^\s*(frisch|vorrat|discounter|drogerie|haushalt)\s*:?\s+(.+)$", part, re.I)
        if pm:
            kat = {"discounter": "vorrat", "haushalt": "drogerie"}.get(pm[1].lower(), pm[1].lower()); part = pm[2]
        name = norm(part)
        if not name or len(name) > 60:
            continue
        if not any(i["name"].lower() == name.lower() for i in items):
            it = {"name": name, "kat": kat or kategorie(name), "by": who, "at": dt.datetime.now().isoformat(timespec="minutes")}
            d = deutsch(name)
            if d.lower() != name.lower():
                it["q"] = d                               # deutscher Suchbegriff für Angebote, z. B. "milk" → "Milch"
            items.append(it); added.append(name); SPEICHER.log_einkauf("dazu", who, name, it["kat"], it.get("q"))
    return ("Dazu: " + ", ".join(added)) if added else "Steht schon drauf."

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
            offers[i["name"]] = search_offers(suchbegriff(i))
        except Exception as e:
            print("Angebote:", i["name"], e, file=sys.stderr)
    state["offers"] = offers; state["offers_at"] = time.time()

def nehmen(state, name, who):
    """Einzelnen Artikel übernehmen (gleiche Person nochmal = freigeben)."""
    for i in state["items"]:
        if i["name"].lower() == (name or "").lower():
            if i.get("wer_kauft") == who:
                i.pop("wer_kauft", None); SPEICHER.log_einkauf("freigegeben", who, i["name"], i.get("kat")); return f"{i['name']} freigegeben."
            i["wer_kauft"] = who; SPEICHER.log_einkauf("uebernommen", who, i["name"], i.get("kat")); return f"{who} kauft {i['name']}."
    return "Nicht gefunden."

def claim(state, kat, who):
    """Gruppe (oder 'alle') übernehmen = alle Artikel darin auf who setzen; sind schon alle bei who → freigeben."""
    kats = ["vorrat", "frisch", "drogerie"] if kat == "alle" else [kat]
    its = [i for i in state["items"] if (i.get("kat") or "vorrat") in kats]
    release = bool(its) and all(i.get("wer_kauft") == who for i in its)
    for i in its:
        if release:
            i.pop("wer_kauft", None)
        else:
            i["wer_kauft"] = who
    state["uebernahme"] = uebernahme(state)
    SPEICHER.log_einkauf("freigegeben" if release else "uebernommen", who, kat=kat)
    return "Freigegeben." if release else f"{who} übernimmt {'alles' if kat == 'alle' else kat}."

def uebernahme(state):
    """Abgeleitet: Gruppe gilt als übernommen, wenn alle Artikel darin dieselbe Person haben."""
    out = {}
    for k in ("vorrat", "frisch", "drogerie"):
        its = [i for i in state["items"] if (i.get("kat") or "vorrat") == k]
        wer = {i.get("wer_kauft") for i in its}
        if its and len(wer) == 1 and None not in wer:
            out[k] = {"wer": wer.pop()}
    return out

STANDARD = ["Milch", "Eier", "Butter", "Brot", "Käse", "Joghurt", "Bananen", "Äpfel", "Tomaten", "Gurke", "Paprika", "Kartoffeln", "Zwiebeln", "Nudeln", "Reis",
            "Haferflocken", "Müsli", "Toast", "Hähnchen", "Hackfleisch", "Wurst", "Frischkäse", "Quark", "Sahne", "Apfelsaft", "Wasser", "Kaffee", "Windeln", "Feuchttücher",
            "Toilettenpapier", "Küchenrolle", "Spülmittel", "Spültabs", "Waschmittel", "Zahnpasta", "Müllbeutel"]

def vorschlaege(state, n=24):
    """Schnell-dazu-Chips: häufig hinzugefügte Artikel (Log, 120 Tage) vor der Standardliste; was schon auf der Liste steht, fällt raus."""
    drauf = {i["name"].lower() for i in state["items"]}
    out, seen = [], set()
    try:
        d = SPEICHER.db()
        if d is not None:
            seit = (dt.datetime.now() - dt.timedelta(days=120)).isoformat()
            pipe = [{"$match": {"aktion": "dazu", "at": {"$gte": seit}, "name": {"$ne": None}}}, {"$group": {"_id": {"$toLower": "$name"}, "n": {"$sum": 1}, "name": {"$first": "$name"}}}, {"$sort": {"n": -1}}, {"$limit": 60}]
            for r in d["einkauf_log"].aggregate(pipe):
                if r["_id"] not in drauf and r["_id"] not in seen and r["n"] >= 2:
                    out.append(r["name"]); seen.add(r["_id"])
    except Exception as e:
        print("vorschlaege:", e, file=sys.stderr)
    for x in STANDARD:
        if len(out) >= n:
            break
        if x.lower() not in drauf and x.lower() not in seen:
            out.append(x); seen.add(x.lower())
    return out[:n]

def export(state, outp):
    out = {"items": [{**i, "kat": i.get("kat") or kategorie(i["name"]), "offers": state["offers"].get(i["name"], [])} for i in state["items"]],
           "uebernahme": uebernahme(state), "personen": PERSONEN, "vorschlaege": vorschlaege(state),
           "updated": dt.datetime.now().isoformat(timespec="minutes"), "errors": {}}
    tmp = outp + ".tmp"; json.dump(out, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1); os.replace(tmp, outp)

def main():
    state = load()
    errors = {}
    try:
        refresh_offers(state)
    except Exception as e:
        errors["angebote"] = f"{type(e).__name__}: {e}"[:200]
    save(state)
    out = {"items": [{**i, "kat": i.get("kat") or kategorie(i["name"]), "offers": state["offers"].get(i["name"], [])} for i in state["items"]],
           "updated": dt.datetime.now().isoformat(timespec="minutes"), "errors": errors}
    outp = sys.argv[1] if len(sys.argv) > 1 else "einkauf.json"
    json.dump(out, open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{outp}: {len(out['items'])} Artikel, Fehler: {errors or 'keine'}")

if __name__ == "__main__":
    main()
