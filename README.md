# homeos – Energie-Tafel für den Bilderrahmen

Eine HTML-Seite, die ein gerooteter Bilderrahmen (WebView, wie im wesbos-Setup) oder jedes alte Tablet im Vollbild anzeigt.
Die Daten kommen live aus dem enocoo-Portal der Siedlung.

## Dateien
- `index.html` – die Tafel. Lädt alle 5 Minuten `data.json` neu.
- `enocoo_fetch.py` – loggt sich ins Portal ein, holt Ampel, Preis, aktuelle Leistung, PV, Monats- und Jahreswerte, schreibt `data.json`. Keine Abhängigkeiten außer Python 3.
- `termine.json` – manuelle Termine `[{"date":"2026-10-17","time":"06:00","title":"…"}]`.
- `build_data.py` – Fallback: `data.json` aus dem CSV-Export bauen (ohne Portal).
- `raw_test.json` – Beispiel-Rohdaten zum Testen: `python3 enocoo_fetch.py --raw raw_test.json --events termine.json`

## Einrichtung auf dem Server (ein Befehl)
    ssh mogli
    sudo git clone https://github.com/thikari/homeos.git /opt/homeos && cd /opt/homeos && sudo bash install.sh

Bei einem Git-Checkout richtet `install.sh` zusätzlich `tafel-update.timer` ein: stündlich `git fetch`, neue Commits werden
automatisch installiert (`update.sh`). Änderungen am Dashboard laufen damit nur noch über einen Push ins Repo –
spätestens eine Stunde später sind sie auf dem Rahmen. Sofort: `sudo bash /opt/homeos/update.sh`.

`install.sh` fragt einmal nach Portal-Benutzer, Passwort und der Kalender-Privatadresse, legt `/etc/tafel.env` (nur root lesbar) an,
richtet zwei systemd-Einheiten ein – `tafel-fetch.timer` (alle 5 Minuten) und `tafel-web.service` (Port 8787) – und gibt am Ende die
Adresse für den Rahmen aus: `http://<server-ip>:8787/<geheimer-pfad>/`. Ohne den Pfad liefert der Server nur 404; Port 8787 in der
Firewall freigeben (`ufw allow 8787/tcp`). Wer HTTPS will: nginx/Caddy als Reverse-Proxy davor, oder Tailscale und die Tailscale-IP im Rahmen.

Prüfen:  `systemctl list-timers tafel-fetch.timer` · `journalctl -u tafel-fetch -n 20` · `curl -s http://127.0.0.1:8787/<pfad>/data.json | head`
Update:  neue Dateien in den Ordner, `sudo bash install.sh` erneut (Env-Datei bleibt).
Die Tafel zeigt oben einen gelben Balken, sobald `data.json` älter als 20 Minuten ist.

## Alternative: Railway (HTTPS, Deploy bei jedem Push)
1. Railway → New Project → Deploy from GitHub repo → `thikari/homeos`. Der Dockerfile wird erkannt.
2. Variables setzen: `ENOCOO_USER`, `ENOCOO_PASS`, `TAFEL_TOKEN` (langer Zufallsstring, z. B. `openssl rand -hex 16`), optional `ICS_URL`.
3. Settings → Networking → Generate Domain. Adresse für den Rahmen: `https://<domain>/<TAFEL_TOKEN>/`
Ein Prozess (`railway_main.py`) liefert die Seite aus und holt alle 5 Minuten Daten. Logs zeigen jede Abfrage.
Jeder Push auf `main` deployt neu – `install.sh`/`update.sh` sind dann nicht nötig.

## Auf dem Rahmen
Chrome/WebView im Kiosk-Modus auf `https://dein-server/tafel/` öffnen. Die Seite skaliert von 400 px bis 1600 px Breite; dunkles Design ist Standard.

## Wetter und Zeitfenster
`enocoo_fetch.py` holt zusätzlich die Vorhersage von Open-Meteo (kostenlos, kein Key) für Mannheim: Temperatur, Wettercode, Regenwahrscheinlichkeit und stündliche Sonneneinstrahlung (W/m²). Die Tafel zeigt daraus 3 Tage Wetter und einen 24-Stunden-Streifen: grün = voraussichtlich Solarüberschuss (≥ 240 W/m²), gelb = brauchbar (≥ 100 W/m²), grau = Netzstrom. Darüber steht in Worten, wann das nächste Fenster kommt („in 4 Stunden, heute 12 bis 16 Uhr"). Die Schwellen `RAD_GOOD`/`RAD_OK` in `index.html` sind an den Portalpreisen vom 16.10.2026 kalibriert; nach ein paar Wochen Portaldaten lohnt ein Nachjustieren.

## Strompreis live + Prognose
Links der aktuelle Portalpreis (alle 5 Minuten neu), rechts die Kurve: letzte 6 Stunden echte Viertelstundenpreise (durchgezogen), nächste 18 Stunden Prognose (gestrichelt). Die Prognose rechnet die stündliche Sonneneinstrahlung (Open-Meteo) in ct/kWh um; die Umrechnungstabelle wird bei jedem Rendern an den echten Preisen der letzten 24 h neu kalibriert (`kalibrieren()` in `index.html`), bei zu wenig Daten gilt `CAL_DEFAULT`. Grünes Band < 8 ct, gelbes Band 8–18 ct. Die Prognose kennt nur die Sonne, nicht den Quartiersverbrauch – an Wochenenden mit wenig Verbrauch ist der echte Preis eher niedriger als geschätzt.

## Abfahrten (VRN)
`enocoo_fetch.py` fragt die VRN-Fahrplanauskunft (EFA, kein Key) für Franklin Mitte (6003053), Franklinschule (6003057) und Pl. der Freundschaft (6002367, Linie 5 + Bus 41) ab, mit Echtzeit. Andere Haltestellen: ID über `https://www.vrn.de/mngvrn/XML_STOPFINDER_REQUEST?outputFormat=JSON&type_sf=any&name_sf=<Name>` suchen und in `VRN_STOPS` eintragen. Die Tafel zeigt die nächsten drei Abfahrten innerhalb einer Stunde; der Countdown läuft zwischen zwei Cron-Läufen weiter (daher Cron alle 5 Minuten, nicht seltener).

## Kosten in Euro
Von der Portal-Startseite (Tabelle „Haushaltsstrom"): Monat bisher in €, Ersparnis durch Solar, Jahr. Das Portal rechnet innerhalb des Monats mit kalkulierten Preisen, die im Folgemonat durch die echten ersetzt werden.

## Startfenster je Gerät
Unter jedem Gerät steht der beste Startzeitpunkt in den nächsten 24 Stunden und was ein Durchgang dann kostet, verglichen mit „jetzt". Gerechnet wird mit Laufzeit und Verbrauch aus `GERAETE` in `index.html` (Spülmaschine Eco 3 h / 0,9 kWh, Waschmaschine 2 h / 0,8 kWh, Trockner 1,5 h / 2,4 kWh) – an die eigenen Geräte anpassen. Das Fenster umfasst alle Startzeiten, die höchstens 2 ct über dem Optimum liegen.

## Einkaufsliste per Telegram + Angebote
Zweiter Tab „Einkauf" (Knopf unten rechts, bleibt auf dem Gerät gespeichert; Direktlink `…/#einkauf`).
1. In Telegram @BotFather anschreiben → `/newbot` → Name vergeben → Token kopieren.
2. Railway → Variables → `TELEGRAM_TOKEN` = Token. Optional `TELEGRAM_CHAT_IDS` = eure Chat-IDs (kommagetrennt), dann darf nur ihr schreiben – der Bot nennt jedem Unbekannten seine Chat-ID.
3. Dem Bot schreiben: `Milch, Eier` fügt hinzu · `x Milch` hakt ab · `leer` leert · `liste` zeigt die Liste. Der Bot antwortet jeweils. Abgleich jede Minute.
Angebote: `einkauf.py` fragt für jeden Artikel die marktguru-Web-API für PLZ 68309 (`ANGEBOTE_PLZ`) ab, alle 6 Stunden; bestes aktuelles Angebot steht unter dem Artikel, rechts alle Treffer (Lidl, Aldi Süd, REWE, EDEKA, Kaufland, Netto, Penny, dm, Rossmann).
Liste liegt in `einkauf_state.json` im Container – bei einem Redeploy geht sie verloren (Railway-Volume unter `/app` mounten, wenn das stört).

## Grundlast, Wasser, Geräteläufe
„Heute"-Spalte: Grundlast = kleinste volle Stunde der letzten 24 h (nachts), Warm-/Kaltwasser der letzten 24 h in Litern.
Unter jedem Gerät: letzter erkannter Lauf (Block ≥ 600 W über Grundlast, 45 min – 3,5 h, ≥ 0,4 kWh) mit Durchschnittspreis und dem günstigsten Preis des Tages. Zuordnung heuristisch: ≥ 1,6 kWh in ≤ 2,5 h = Trockner, ≥ 2,25 h = Spülmaschine, sonst Waschmaschine.

## Logik der Empfehlung
Portal-Preis < 8 ct → "Ja, jetzt." · 8–18 ct → "Geht so." · darüber: "Warten." wenn innerhalb 5 h günstige Stunden folgen, sonst "Netzstrom."
Günstig = Stunden mit Durchschnittspreis < 10 ct im Preisprofil der letzten 24 h.

## Ziele anpassen
In `index.html` oben im Script: `ZIEL` (Jahresziele) und `SAISON` (Monatsanteile).

## Hinweis Portal
Die Seite `downloadConsumption.php` gibt im Quelltext Sitzungsdaten inkl. Passwort-Hash aus (PHP-Debug-Ausgabe). Das ist ein Fehler auf enocoo-Seite – lohnt eine kurze Meldung an enocoo.

## Einkaufsliste: Tippen · Sprechen · Foto · Barcode

Die Eingabe-Leiste (`einkauf.js`) gibt es auf der Handy-Seite `/<token>/einkauf/` und im Tab **Einkauf** auf der Tafel (iPad = Touch):

- **Tippen** – Textfeld; `Milch, Eier` fügt hinzu, `x Milch` hakt ab, `frisch: Käse` / `vorrat …` / `drogerie …` legt die Gruppe fest (auch pro Artikel in einer Zeile).
- **Sprechen** – Spracherkennung des Browsers (Safari/Chrome, de-DE), „und" wird zum Komma. Kein Server nötig.
- **Foto** – Kamera/Fotoauswahl, das Bild wird auf 1024 px verkleinert und an `POST /<token>/einkauf/photo` geschickt; der Server fragt die Claude-API (`ANTHROPIC_API_KEY` in Railway setzen, Modell über `TAFEL_VISION_MODEL`, Standard `claude-haiku-5-5`). Ergebnis: Vorschläge zum Antippen. Ohne Schlüssel meldet der Button das.
- **Barcode** – Kamera-Scanner (ZXing von jsDelivr), EAN → `GET /<token>/einkauf/ean/<code>` → Open Food Facts / Open Beauty Facts / Open Products Facts → Produktname als Vorschlag.
- Antippen eines Artikels hakt ihn ab – auf dem Handy und auf der Tafel.

Kamera und Mikrofon verlangen HTTPS (Railway hat das) und einmalig die Freigabe im Browser.

## Tab „Mobil"

`mobil.py` läuft alle 2 Minuten (`MOBIL_INTERVAL`) und schreibt `mobil.json`:

- **Bahn & Bus** – alle Abfahrten der drei Haltestellen (Franklin Mitte, Franklinschule, Platz der Freundschaft) mit Echtzeit, Verspätung und Richtung.
- **FRANKLIN Mobil** – Fahrzeuge im Quartier (E-Autos, Lastenräder) mit Standort, Akku und ob sie in den nächsten 2 h frei sind. Quelle: Cantamen-CASIREST-API hinter buchung.franklin-mobil.de (öffentlicher Web-App-Key, kein Login nötig).
- **Unsere Buchungen** – eigene Buchungen der nächsten 60 Tage. Dafür in Railway `FRANKLIN_LOGIN` und `FRANKLIN_PASS` setzen (die Zugangsdaten der FRANKLIN-Mobil-App). Das Login-Token wird neben `einkauf_state.json` gecacht.

## Zugang mit PIN

Mit `TAFEL_PIN` (Railway-Variable) zeigt die Startseite `https://<domain>/` eine PIN-Abfrage. Nach richtiger Eingabe setzt der Server ein Cookie für ein Jahr; danach funktionieren `/`, `/einkauf/` und alle Daten ohne Token im Pfad. `/logout` löscht das Cookie. Der geheime Pfad `/<TAFEL_TOKEN>/…` funktioniert parallel weiter (für den Rahmen im Kiosk-Modus). Ohne `TAFEL_PIN` gibt es nur den Token-Pfad. Falsche PINs werden mit 1,5 s Verzögerung beantwortet; Token oder PIN ändern macht alle Cookies ungültig.

## Dauerhafter Speicher (wichtig)

Einkaufsliste: entweder `MONGODB_URI` setzen (Railway-MongoDB oder Atlas; Collection `einkauf`, Dokument `liste`) – oder Datei in `DATA_DIR`. Auf Railway: im Service **Volume** anlegen mit Mount-Pfad `/app/data` – wird automatisch erkannt (Log: „Datenordner: /app/data (persistent)"). Ohne Volume ist die Liste nach jedem Deploy leer.

## MongoDB-Schema (mit `MONGODB_URI`)

| Collection | Schlüssel | Inhalt | Woher |
|---|---|---|---|
| `einkauf` | `_id: "liste"` | aktuelle Einkaufsliste (items, uebernahme, offers) | Handy/Tafel |
| `einkauf_log` | `at` | jede Aktion: dazu · abgehakt · geleert · uebernommen · freigegeben, mit `wer`, `name`, `kat` | Handy/Tafel |
| `energie_15min` | `t` (eindeutig) | Strompreis ct/kWh und Verbrauch kWh je Viertelstunde – wächst über die 24 h des Portals hinaus | enocoo, alle 5 min |
| `energie_tage` | `d` | Strom kWh, Kalt-/Warmwasser m³, PV kWh, Grundlast W je Tag | enocoo |
| `energie_monate` | `ym` | Monatsstand Strom/Wasser/Wärme, Kosten €, Solar-Ersparnis € | enocoo |
| `energie_live` | `at` | Leistung W, Preis, Ampel, PV kW, Siedlung kW, Autarkie je Abruf | enocoo |
| `wetter_tage` | `d` | Tmin/Tmax, Wettercode, Regen | Open-Meteo |
| `mobil_buchungen` | `id` | jede FRANKLIN-Mobil-Buchung mit Fahrzeug, Zeit, Preis und Posten (Fahrzeit, Km, Gebühr) | Cantamen, alle 2 min |
| `mobil_fahrzeuge` | `at` | Verfügbarkeit/Akku aller Fahrzeuge je Abruf (für Auslastungs-Statistik) | Cantamen |

Alles wird nur ergänzt bzw. per Schlüssel aktualisiert – nichts wird gelöscht. Indizes werden beim ersten Start angelegt.

## Push-Benachrichtigungen

Glocke neben „Teilen" auf der Handy-Seite: einmal antippen → Berechtigung → das Gerät bekommt bei Änderungen der *anderen* Person eine Nachricht („Julia: + Milch, Eier · ✓ Windeln"), gebündelt über 20 s. Eigene Änderungen werden nicht gemeldet. Web Push (RFC 8291/8292) ohne Fremddienst: `webpush.py`, VAPID-Schlüssel werden beim ersten Mal erzeugt und in MongoDB (`config`/`push`) bzw. `push.json` gespeichert, Abos in `push_abos`. iPhone: die Seite muss auf dem Home-Bildschirm liegen und von dort geöffnet werden (iOS ≥ 16.4). Optional `VAPID_SUBJECT=mailto:…`.

## Haushaltsbuch (Tab „Haushalt" · Handy-Seite `/haushalt/`)

Kassenzettel fotografieren → KI liest Laden, Datum, Summe und Posten (`MISTRAL_API_KEY`, Modell `MISTRAL_MODEL` Standard mistral-small-latest; alternativ `ANTHROPIC_API_KEY`) → prüfen → speichern. Oder von Hand (Laden, Betrag, Kategorie, Wer). Posten vom Beleg, die auf der Einkaufsliste stehen, werden automatisch abgehakt. Übersicht: Monat vs. Budget (`HAUSHALT_BUDGET_EUR`, Standard 900) mit Soll-Marke und Prognose, nach Kategorie, Laden und Person, letzte 8 Wochen, 6 Monate, letzte Belege. Speicher: MongoDB-Collection `ausgaben` (sonst Datei `haushalt_state.json`).

Posten werden einer Produktart zugeordnet (Obst & Gemüse, Milch & Käse, Fleisch & Fisch, Brot, Grundnahrung, Fertig & TK, Getränke, Snacks & Süßes, Kinder, Drogerie, Haushalt, Pfand & Rabatt) – von der KI beim Scan oder per Wortliste; daraus „Nach Produktart" und ein Preisvergleich je Produkt über die Läden. Budget je Belegkategorie über `HAUSHALT_BUDGETS="Lebensmittel=450,Drogerie=80,Kinder=120,Gastro=100,Haushalt=60,Mobilität=60"` (Rest des Gesamtbudgets = Sonstiges); bei 80 % und 100 % gibt es eine Push-Nachricht, je Monat einmal.
