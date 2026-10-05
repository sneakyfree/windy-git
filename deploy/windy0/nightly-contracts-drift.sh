#!/usr/bin/env bash
# Nightly (Mind plan v2.1 S0.4): which consumers of windy-contracts are behind MANIFEST.json?
# Runs scripts/contracts_drift.py on Veron, writes ~/windy-orchestra/CONTRACTS_DRIFT.md (repo,
# contract, status, versions; no file content), appends ONE BOARD line per consumer repo whose
# set of problems is NEW since the last run (so a lagging consumer is named the night after a
# bump, then again only if it changes), and prints the sweep's summary line last for windy-job.
# FLOOD CAP (Hub 10-05): on the first run, or when more than 8 repos are new, ONE summary
# BOARD line is written instead; the full list is in CONTRACTS_DRIFT.md. BOARD lines say only
# repo, what is behind, and what to do. Never file content.
# Install: cp to ~/bin/nightly-contracts-drift.sh (Windy 0); units: windy-contracts-drift.{service,timer}.
set -euo pipefail
page=~/windy-orchestra/CONTRACTS_DRIFT.md
state=~/.local/state/contracts-drift.txt
mkdir -p "$(dirname "$state")"
first=0; [[ -e "$state" ]] || first=1
out=$(timeout 600 ssh -o BatchMode=yes -o ConnectTimeout=15 ts-veron \
  'cd /srv/windygit/src && timeout 550 python3 scripts/contracts_drift.py' || true)
summary=$(grep '^# contracts drift sweep:' <<<"$out" || echo "# contracts drift sweep: ERROR (no summary)")
rows=$(grep -v '^#' <<<"$out" | grep . || true)
{
  echo "# Contract drift: consumers behind windy-contracts MANIFEST.json ($(date -u '+%Y-%m-%d %H:%MZ'))"
  echo "_Nightly; windy-git scripts/contracts_drift.py. BEHIND = locked sha256 != MANIFEST; LOCAL_EDIT = vendored bytes != own lock; UNKNOWN = path not in MANIFEST; MISSING_VENDORED._"
  echo; echo "${summary#\# }"; echo
  echo "| consumer repo | lock | contract | status | locked | MANIFEST |"; echo "|---|---|---|---|---|---|"
  while IFS=$'\t' read -r repo lock path st lv mv; do [[ -n $repo ]] && echo "| $repo | $lock | $path | $st | $lv | $mv |"; done <<<"$rows"
} > "$page"
cur=$(cut -f1,3,4,6 <<<"$rows" | sort -u)
new=$(comm -13 <(sort -u "$state" 2>/dev/null || true) <(echo "$cur" | grep . || true))
if grep -q . <<<"$cur"; then echo "$cur" > "$state"; else : > "$state"; fi
if [[ -n "$new" ]]; then
  nrepos=$(cut -f1 <<<"$new" | sort -u | grep -c . || true)
  now=$(date -u +%Y-%m-%dT%H:%MZ)
  if (( nrepos > 8 || (first == 1 && nrepos > 0) )); then
    echo "$now Windy Git: 📐 contract drift: $nrepos consumer repo(s) behind/missing/local-edit vs windy-contracts. Each: re-vendor + re-lock (tools/contracts_lock.py). Full list: ~/windy-orchestra/CONTRACTS_DRIFT.md" >> ~/windy-orchestra/BOARD.md
  else
    while read -r repo; do
      [[ -z $repo ]] && continue
      what=$(awk -F'\t' -v r="$repo" '$1==r {printf "%s%s %s (MANIFEST %s)", sep, $2, $3, $4; sep="; "}' <<<"$new")
      echo "$now Windy Git: 📐 contract drift: $repo: $what. Re-vendor + re-lock (tools/contracts_lock.py). See ~/windy-orchestra/CONTRACTS_DRIFT.md" >> ~/windy-orchestra/BOARD.md
    done < <(cut -f1 <<<"$new" | sort -u)
  fi
fi
echo "${summary#\# }"
