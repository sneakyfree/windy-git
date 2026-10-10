#!/usr/bin/env bash
# Weekly: scan every PUBLIC repo in Grant's 5 GitHub accounts for secret-shaped
# strings (runs on Veron; windy-git scripts/public_secret_scan.py). Writes
# ~/windy-orchestra/PUBLIC_SECRET_SCAN.md (hash + location only, never a value)
# and, when a NOT-excused finding appears that the last run didn't have, appends a
# board line and messages "Windy Boss Terminal" once. Orchestrator ask 09-24.
set -euo pipefail
page=~/windy-orchestra/PUBLIC_SECRET_SCAN.md
state=~/.local/state/public-secret-scan.json
mkdir -p "$(dirname "$state")" ~/scratch-windygit
json=~/scratch-windygit/public-latest.json
timeout 7200 ssh -o BatchMode=yes -o ConnectTimeout=15 ts-veron \
  'cd /srv/windygit/src && timeout 7000 python3 scripts/public_secret_scan.py --out ~/leakscan/public-latest.json' >/dev/null
timeout 120 scp -q -o BatchMode=yes ts-veron:leakscan/public-latest.json "$json"
python3 - "$json" "$page" "$state" <<'PY' > ~/scratch-windygit/public-scan-new.txt
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
new=$(cat ~/scratch-windygit/public-scan-new.txt)
if [ -n "$new" ]; then
  ts=$(date -u +%Y-%m-%dT%H:%MZ)
  list=$(echo "$new" | tr '\n' ' ')
  echo "$ts 13: 🔴 WEEKLY PUBLIC SECRET SCAN: NEW secret-shaped string(s) in PUBLIC repos: $list(hash only; PUBLIC_SECRET_SCAN.md)." >> ~/windy-orchestra/BOARD.md
  msg="Windy Git (automatic, weekly public secret scan, $ts): NEW secret-shaped string(s) in PUBLIC repos (repo#sha256[:8]): $list. Details: ~/windy-orchestra/PUBLIC_SECRET_SCAN.md. Values never printed. Check liveness and rotate/remove."
  FS_MSG="$msg" timeout 180 claude -p 'Load SendMessage (ToolSearch select:SendMessage). Call SendMessage with to = "Windy Boss Terminal" and message = the exact value of env var FS_MSG (run: printenv FS_MSG). Print the result and stop.' --permission-mode bypassPermissions >/dev/null 2>&1 \
    || echo "ping to orchestrator failed; board line written" >&2
fi
