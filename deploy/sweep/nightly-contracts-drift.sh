#!/usr/bin/env bash
# Nightly (Mind plan v2.1 S0.4): which consumers of windy-contracts are behind MANIFEST.json?
# Runs scripts/contracts_drift.py here, writes ~/windy-orchestra/CONTRACTS_DRIFT.md on Windy 0
# (repo, contract, status, versions; no file content), appends ONE BOARD line per consumer repo
# whose set of problems is NEW since the last run, and prints the sweep's summary line last for
# windy-job. FLOOD CAP (Hub 10-05): on the first run, or when more than 8 repos are new, ONE
# summary BOARD line is written instead. BOARD lines say only repo, what is behind, and what to do.
# Veron copy of Windy 0 ~/bin/nightly-contracts-drift.sh (moved 2026-10-21, Grant).
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")
. "$here/common.sh"
state=$STATE/contracts-drift.txt
first=0; [[ -e "$state" ]] || first=1
page=$(mktemp); trap 'rm -f "$page"' EXIT
out=$(cd /srv/windygit/src && timeout 550 python3 scripts/contracts_drift.py || true)
summary=$(grep '^# contracts drift sweep:' <<<"$out" || echo "# contracts drift sweep: ERROR (no summary)")
rows=$(grep -v '^#' <<<"$out" | grep . || true)
{
  echo "# Contract drift: consumers behind windy-contracts MANIFEST.json ($(date -u '+%Y-%m-%d %H:%MZ'))"
  echo "_Nightly; windy-git scripts/contracts_drift.py. BEHIND = locked sha256 != MANIFEST; LOCAL_EDIT = vendored bytes != own lock; UNKNOWN = path not in MANIFEST; MISSING_VENDORED._"
  echo; echo "${summary#\# }"; echo
  echo "| consumer repo | lock | contract | status | locked | MANIFEST |"; echo "|---|---|---|---|---|---|"
  while IFS=$'\t' read -r repo lock path st lv mv; do [[ -n $repo ]] && echo "| $repo | $lock | $path | $st | $lv | $mv |"; done <<<"$rows"
} > "$page"
put_page "$page" CONTRACTS_DRIFT.md
cur=$(cut -f1,3,4,6 <<<"$rows" | sort -u)
new=$(comm -13 <(sort -u "$state" 2>/dev/null || true) <(echo "$cur" | grep . || true))
if grep -q . <<<"$cur"; then echo "$cur" > "$state"; else : > "$state"; fi
if [[ -n "$new" ]]; then
  nrepos=$(cut -f1 <<<"$new" | sort -u | grep -c . || true)
  now=$(date -u +%Y-%m-%dT%H:%MZ)
  if (( nrepos > 8 || (first == 1 && nrepos > 0) )); then
    board "$now Windy Git: 📐 contract drift: $nrepos consumer repo(s) differ from windy-contracts MANIFEST. List: ~/windy-orchestra/CONTRACTS_DRIFT.md"
  else
    while read -r repo; do
      [[ -z $repo ]] && continue
      what=$(awk -F'\t' -v r="$repo" '$1==r {printf "%s%s %s (MANIFEST %s)", sep, $2, $3, $4; sep="; "}' <<<"$new")
      board "$now Windy Git: 📐 contract drift: $repo: $what. See ~/windy-orchestra/CONTRACTS_DRIFT.md"
    done < <(cut -f1 <<<"$new" | sort -u)
  fi
fi
echo "${summary#\# }"
