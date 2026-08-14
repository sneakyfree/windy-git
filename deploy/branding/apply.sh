#!/usr/bin/env bash
# Apply Windy Git branding to the Gitea custom tree. Idempotent.
set -euo pipefail
CUSTOM="${GITEA_CUSTOM_HOST:-/srv/windygit/git/gitea}"
HERE="$(cd "$(dirname "$0")" && pwd)"

sudo mkdir -p "$CUSTOM"/templates/custom "$CUSTOM"/public/assets/img "$CUSTOM"/public/assets/css
sudo cp -r "$HERE"/templates/. "$CUSTOM"/templates/
sudo cp -r "$HERE"/public/. "$CUSTOM"/public/
sudo chown -R 1000:1000 "$CUSTOM"/templates "$CUSTOM"/public

# APP_NAME must sit at the TOP LEVEL. See README trap #1.
INI="$CUSTOM/conf/app.ini"
sudo cp "$INI" "$INI.bak-brand-$(date +%s)"
sudo python3 - "$INI" <<'PY'
import sys
p = sys.argv[1]
lines = [l for l in open(p).read().splitlines()
         if not l.strip().startswith(("APP_NAME", "APP_SLOGAN"))]
lines.insert(0, "APP_NAME = Windy Git")
open(p, "w").write("\n".join(lines) + "\n")
PY
echo "applied. restart gitea to pick it up."
