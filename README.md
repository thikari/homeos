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

## Logik der Empfehlung
Portal-Preis < 8 ct → "Ja, jetzt." · 8–18 ct → "Geht so." · darüber: "Warten." wenn innerhalb 5 h günstige Stunden folgen, sonst "Netzstrom."
Günstig = Stunden mit Durchschnittspreis < 10 ct im Preisprofil der letzten 24 h.

## Ziele anpassen
In `index.html` oben im Script: `ZIEL` (Jahresziele) und `SAISON` (Monatsanteile).

## Hinweis Portal
Die Seite `downloadConsumption.php` gibt im Quelltext Sitzungsdaten inkl. Passwort-Hash aus (PHP-Debug-Ausgabe). Das ist ein Fehler auf enocoo-Seite – lohnt eine kurze Meldung an enocoo.
