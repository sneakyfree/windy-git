#!/usr/bin/env bash
# Nightly (Boss 10-01): runner-guard over the default branch of EVERY public repo in Grant's
# 5 GitHub accounts (windy-git scripts/runner_guard.py report). Writes
# ~/windy-orchestra/RUNNER_GUARD.md on Windy 0 (repo, file:line, rule; no file content), appends
# ONE BOARD line per NEW hit vs the last run, and prints "runner-guard sweep: N hit(s)" last, so
# the windy-job heartbeat (--expect "runner-guard sweep: 0 hit") goes red while any hit exists.
# Veron copy of Windy 0 ~/bin/nightly-runner-guard-sweep.sh (moved 2026-10-21, Grant).
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")
. "$here/common.sh"
state=$STATE/runner-guard-sweep.txt
page=$(mktemp); trap 'rm -f "$page"' EXIT
out=$(cd /srv/windygit/src && timeout 850 python3 scripts/runner_guard.py report || true)
summary=$(grep '^# runner-guard sweep:' <<<"$out" || echo "# runner-guard sweep: ERROR (no summary)")
hits=$(grep -v '^#' <<<"$out" | grep . || true)
{
  echo "# Runner guard: stranger-code paths to self-hosted runners ($(date -u '+%Y-%m-%d %H:%MZ'))"
  echo "_Nightly; windy-git scripts/runner_guard.py. R1 pull_request_target · R2 fork PR on self-hosted without a same-repo/environment gate · R3 outsider events (issue_comment, workflow_run, ...) on self-hosted · R0 unparseable._"
  echo; echo "${summary#\# }"; echo
  echo "| repo | file:line | rule | fix |"; echo "|---|---|---|---|"
  while IFS=$'\t' read -r repo loc rule msg; do [[ -n $repo ]] && echo "| $repo | $loc | $rule | $msg |"; done <<<"$hits"
} > "$page"
put_page "$page" RUNNER_GUARD.md
new=$(comm -13 <(sort -u "$state" 2>/dev/null || true) <(cut -f1-3 <<<"$hits" | sort -u))
cut -f1-3 <<<"$hits" | sort -u > "$state"
if [[ -n "$new" ]]; then
  n=$(grep -c . <<<"$new")
  board "$(date -u +%Y-%m-%dT%H:%MZ) Windy Git: 🚨 runner-guard: $n NEW stranger-code path(s) to a self-hosted runner in public repos; see ~/windy-orchestra/RUNNER_GUARD.md"
fi
echo "${summary#\# }"
