#!/usr/bin/env bash
# Energie-Tafel auf dem Server einrichten (Debian/Ubuntu, systemd).
# Aufruf als root im Projektordner:   sudo bash install.sh
# Danach läuft alle 5 Minuten enocoo_fetch.py, ein kleiner Webserver liefert die Tafel aus,
# und bei einem Git-Checkout holt sich der Server stündlich selbst Updates.
set -euo pipefail
QUIET=0; [ "${1:-}" = "--quiet" ] && QUIET=1

DIR=/opt/tafel
PORT="${PORT:-8787}"
SRC="$(cd "$(dirname "$0")" && pwd)"

echo "== Dateien nach $DIR"
mkdir -p "$DIR/www"
install -m 644 "$SRC/index.html" "$DIR/www/index.html"
install -m 755 "$SRC/enocoo_fetch.py" "$DIR/enocoo_fetch.py"
install -m 755 "$SRC/tafel_server.py" "$DIR/tafel_server.py"
[ -f "$DIR/termine.json" ] || install -m 644 "$SRC/termine.json" "$DIR/termine.json"

echo "== Python-Abhängigkeiten (Serientermine)"
if ! python3 -c "import icalendar, recurring_ical_events" 2>/dev/null; then
  pip3 install -q icalendar recurring-ical-events --break-system-packages 2>/dev/null || pip3 install -q icalendar recurring-ical-events
fi

echo "== Zugangsdaten"
if [ ! -f /etc/tafel.env ]; then
  read -rp "enocoo Benutzername [H12W01_01]: " U; U="${U:-H12W01_01}"
  read -rsp "enocoo Passwort: " P; echo
  read -rp "Google-Kalender Privatadresse (iCal, leer = ohne): " ICS
  TOKEN="$(tr -dc a-z0-9 </dev/urandom | head -c 24)"
  umask 077
  cat >/etc/tafel.env <<EOF
ENOCOO_USER=$U
ENOCOO_PASS=$P
ICS_URL=$ICS
TAFEL_TOKEN=$TOKEN
TAFEL_PORT=$PORT
EOF
  umask 022
  echo "   /etc/tafel.env geschrieben (nur root lesbar)"
else
  echo "   /etc/tafel.env existiert, wird beibehalten"
fi
# shellcheck disable=SC1091
set -a; . /etc/tafel.env; set +a

echo "== systemd: Fetcher alle 5 Minuten"
cat >/etc/systemd/system/tafel-fetch.service <<EOF
[Unit]
Description=Energie-Tafel: Daten aus enocoo, Wetter, VRN, Kalender holen
After=network-online.target

[Service]
Type=oneshot
EnvironmentFile=/etc/tafel.env
WorkingDirectory=$DIR
ExecStart=/usr/bin/python3 $DIR/enocoo_fetch.py --ics "\${ICS_URL}" --events $DIR/termine.json --out $DIR/www/data.json.tmp
ExecStartPost=/bin/mv $DIR/www/data.json.tmp $DIR/www/data.json
EOF
cat >/etc/systemd/system/tafel-fetch.timer <<EOF
[Unit]
Description=Energie-Tafel alle 5 Minuten aktualisieren

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
AccuracySec=30s

[Install]
WantedBy=timers.target
EOF

echo "== systemd: Webserver auf Port $PORT"
cat >/etc/systemd/system/tafel-web.service <<EOF
[Unit]
Description=Energie-Tafel Webserver
After=network-online.target

[Service]
EnvironmentFile=/etc/tafel.env
WorkingDirectory=$DIR/www
ExecStart=/usr/bin/python3 $DIR/tafel_server.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

if [ -d "$SRC/.git" ]; then
  echo "== systemd: stündlich Updates aus Git holen"
  cat >/etc/systemd/system/tafel-update.service <<EOF
[Unit]
Description=Energie-Tafel: Code aus Git aktualisieren

[Service]
Type=oneshot
WorkingDirectory=$SRC
ExecStart=/bin/bash $SRC/update.sh
EOF
  cat >/etc/systemd/system/tafel-update.timer <<EOF
[Unit]
Description=Energie-Tafel stündlich auf Updates prüfen

[Timer]
OnBootSec=5min
OnUnitActiveSec=1h

[Install]
WantedBy=timers.target
EOF
fi

systemctl daemon-reload
systemctl enable --now tafel-fetch.timer tafel-web.service
[ -d "$SRC/.git" ] && systemctl enable --now tafel-update.timer
systemctl restart tafel-web.service

[ "$QUIET" = 1 ] && exit 0

echo "== Erster Abruf"
systemctl start tafel-fetch.service && echo "   ok" || { echo "   FEHLER – siehe: journalctl -u tafel-fetch -n 30"; exit 1; }

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "Fertig. Tafel-Adresse für den Rahmen:"
echo "   http://$IP:$PORT/$TAFEL_TOKEN/"
echo
echo "Firewall: Port $PORT freigeben (ufw allow $PORT/tcp). Der Pfad ist das Geheimnis – ohne ihn gibt es nur 404."
echo "Log:    journalctl -u tafel-fetch -f      Status: systemctl list-timers 'tafel-*'"
