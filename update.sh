#!/usr/bin/env bash
# Holt neue Commits aus Git und installiert sie, wenn sich etwas geändert hat. Wird stündlich vom tafel-update.timer aufgerufen.
set -euo pipefail
cd "$(dirname "$0")"
git fetch -q origin
LOCAL="$(git rev-parse HEAD)"; REMOTE="$(git rev-parse origin/main)"
[ "$LOCAL" = "$REMOTE" ] && exit 0
echo "Update $LOCAL -> $REMOTE"
git reset -q --hard origin/main
bash ./install.sh --quiet
systemctl start tafel-fetch.service
