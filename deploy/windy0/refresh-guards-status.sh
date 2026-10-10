#!/usr/bin/env bash
# Hourly: regenerate ~/windy-orchestra/GUARDS_STATUS.md from Veron (windy-git
# scripts/guards_report.py). Replaces the page only on success. When a guard's
# LANE-owned count DROPS TO 0 (orchestrator, 09-23: "ping me the hour it hits 0"),
# append a board line and message "Windy Boss Terminal" once.
set -euo pipefail
out=~/windy-orchestra/GUARDS_STATUS.md
state=~/.local/state/windy-guards-status.json
mkdir -p "$(dirname "$state")"
tmp=$(mktemp)
if ! timeout 600 ssh -o BatchMode=yes -o ConnectTimeout=15 ts-veron \
     'cd /srv/windygit/src && sudo -n timeout 540 python3 scripts/guards_report.py' > "$tmp" 2>/dev/null \
   || ! grep -q "^# Repo guards: live status" "$tmp"; then
  rm -f "$tmp"; echo "guards status refresh FAILED (page left as is)" >&2; exit 1
fi
mv "$tmp" "$out"
# prod vs lock column (Windy Search's daily PROD_LOCK_DRIFT.md); never fatal
python3 ~/bin/merge-prod-lock-drift.py "$out" ~/windy-orchestra/PROD_LOCK_DRIFT.md 2>/dev/null \
  || echo "prod-vs-lock merge skipped" >&2

# "| compute-guard (…) | <lane> | <grant> | …" → lane counts now vs last run
python3 - "$out" "$state" <<'PY' > /tmp/guards-transitions.$$ || true
import json, re, sys
page, state = sys.argv[1], sys.argv[2]
now = {}
for line in open(page):
    m = re.match(r"^\| (compute-guard|ci-hygiene) [^|]*\| (\d+) \| (\d+) \|", line)
    if m:
        now[m.group(1)] = int(m.group(2))
try:
    prev = json.load(open(state))
except (OSError, ValueError):
    prev = {}
for g, n in now.items():
    if n == 0 and prev.get(g, 1) > 0:
        print(g)
json.dump(now, open(state, "w"))
PY
while read -r guard; do
  [ -n "$guard" ] || continue
  ts=$(date -u +%Y-%m-%dT%H:%MZ)
  echo "$ts 13: ✅ GUARD READY TO BLOCK: $guard lane-owned findings hit 0 (GUARDS_STATUS.md). Orchestrator: say \"block $guard\"." >> ~/windy-orchestra/BOARD.md
  msg="Windy Git (automatic, hourly guards check): the $guard lane-owned count just hit 0 on every bridged default branch (GUARDS_STATUS.md, $ts). Grant-owned items are listed separately and don't count. Say \"block $guard\" and Windy Git flips it to blocking."
  FS_MSG="$msg" timeout 180 claude -p 'Load SendMessage (ToolSearch select:SendMessage). Call SendMessage with to = "Windy Boss Terminal" and message = the exact value of env var FS_MSG (run: printenv FS_MSG). Print the result and stop.' --permission-mode bypassPermissions >/dev/null 2>&1 \
    || echo "ping to orchestrator failed; board line written" >&2
done < /tmp/guards-transitions.$$
rm -f /tmp/guards-transitions.$$
