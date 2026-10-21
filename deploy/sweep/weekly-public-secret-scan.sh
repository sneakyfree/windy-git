#!/usr/bin/env bash
# Weekly: scan every PUBLIC repo in Grant's 5 GitHub accounts for secret-shaped strings
# (windy-git scripts/public_secret_scan.py). Writes ~/windy-orchestra/PUBLIC_SECRET_SCAN.md on
# Windy 0 (hash + location only, never a value) and, when a NOT-excused finding appears that
# the last run didn't have, appends a BOARD line (Boss reads the BOARD). Orchestrator ask 09-24.
# Veron copy of Windy 0 ~/bin/weekly-public-secret-scan.sh (moved 2026-10-21, Grant).
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")
. "$here/common.sh"
state=$STATE/public-secret-scan.json
json=~/leakscan/public-latest.json
mkdir -p ~/leakscan
page=$(mktemp); trap 'rm -f "$page"' EXIT
(cd /srv/windygit/src && timeout 7000 python3 scripts/public_secret_scan.py --out "$json") >/dev/null
new=$(python3 - "$json" "$page" "$state" <<'PY'
import json, sys, time
src, page, state = sys.argv[1:4]
d = json.load(open(src))
rows = d["rows"]; bad = [r for r in rows if not r["excused"]]
now = time.strftime("%Y-%m-%d %H:%MZ", time.gmtime())
L = [f"# Public repos: secret-shaped strings (generated {now}; windy-git scripts/public_secret_scan.py, weekly)",
     "_Every PUBLIC repo in sneakyfree, VERONTECH, Windstorm-Institute, Windstorm-Labs, Public-Streamer; full history "
     "incl. unreachable objects. Hash (sha256[:8]) + location only. Known fakes excused by ci/secret-guard-allow.yml._", "",
     f"Scanned **{len(d['scanned'])}** public repos · clone errors: {', '.join(d['errors']) or 'none'} · "
     f"secret-shaped: {len(rows)} · **NOT excused: {len(bad)}**", "",
     "| hash8 | kind | repo | paths | first seen | in HEAD? |", "|---|---|---|---|---|---|"]
for r in sorted(bad, key=lambda r: (r["repo"], r["hash8"], r["first_date"])):
    L.append(f"| {r['hash8']} | {r['kind']} | {r['repo']} | {'; '.join(r['paths'])[:80]} | {r['first_date'][:10]} | {'YES' if r['in_head'] else 'history'} |")
open(page, "w").write("\n".join(L) + "\n")
keys = sorted({f"{r['repo']}#{r['hash8']}" for r in bad})
try:
    prev = set(json.load(open(state)))
except (OSError, ValueError):
    prev = None
json.dump(keys, open(state, "w"))
if prev is not None:
    for k in keys:
        if k not in prev:
            print(k)
PY
)
put_page "$page" PUBLIC_SECRET_SCAN.md
if [ -n "$new" ]; then
  list=$(echo "$new" | tr '\n' ' ')
  board "$(date -u +%Y-%m-%dT%H:%MZ) Windy Git -> Boss: 🔴 WEEKLY PUBLIC SECRET SCAN: NEW secret-shaped string(s) in PUBLIC repos: $list(repo#sha256[:8], values never printed; PUBLIC_SECRET_SCAN.md). Check liveness and rotate/remove."
fi
echo "public secret scan: ok"
