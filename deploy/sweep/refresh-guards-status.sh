#!/usr/bin/env bash
# Regenerate ~/windy-orchestra/GUARDS_STATUS.md (on Windy 0) from windy-git
# scripts/guards_report.py. Replaces the page only on success. When a guard's
# LANE-owned count DROPS TO 0 (orchestrator, 09-23: "ping me the hour it hits 0"),
# append a BOARD line (Boss reads the BOARD).
# Veron copy of Windy 0 ~/bin/refresh-guards-status.sh (moved 2026-10-21, Grant).
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")
. "$here/common.sh"
state=$STATE/windy-guards-status.json
tmp=$(mktemp); drift=$(mktemp); trap 'rm -f "$tmp" "$drift"' EXIT
if ! (cd /srv/windygit/src && sudo -n timeout 540 python3 scripts/guards_report.py) > "$tmp" 2>/dev/null \
   || ! grep -q "^# Repo guards: live status" "$tmp"; then
  echo "guards status refresh FAILED (page left as is)" >&2; exit 1
fi
# prod vs lock column (Windy Search's daily PROD_LOCK_DRIFT.md); never fatal
{ get_page PROD_LOCK_DRIFT.md "$drift" && python3 "$here/merge-prod-lock-drift.py" "$tmp" "$drift"; } 2>/dev/null \
  || echo "prod-vs-lock merge skipped" >&2

# "| compute-guard (…) | <lane> | <grant> | …" → lane counts now vs last run
transitions=$(python3 - "$tmp" "$state" <<'PY' || true
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
)
put_page "$tmp" GUARDS_STATUS.md
while read -r guard; do
  [ -n "$guard" ] || continue
  board "$(date -u +%Y-%m-%dT%H:%MZ) Windy Git -> Boss: ✅ GUARD READY TO BLOCK: $guard lane-owned findings hit 0 (GUARDS_STATUS.md). Say \"block $guard\"."
done <<<"$transitions"
echo "guards status: ok"
