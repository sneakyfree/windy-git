#!/usr/bin/env bash
# One nightly sweep on Windy 0 (Boss simplify rulings E, 10-07): replaces the four
# separate Windy Git timers (windy-guards-status hourly, windy-runner-guard-sweep,
# windy-contracts-drift, windy-public-secret-scan weekly). Each step is its own script,
# unchanged. One failing step does not stop the others; the sweep exits 1 if any failed.
# The two steps that already had windy-job heartbeats keep their names, so windy-uptime
# alerts on exactly what it alerted on before. The public secret scan (up to ~2 h of
# Veron time) still runs once a week: Mondays (UTC) only.
# Install: cp to ~/bin/ (Windy 0); units: windy-nightly-sweep.{service,timer}.
set -uo pipefail
failed=()
step() {  # step <name> <command...>
  echo "== $1"
  "${@:2}" || failed+=("$1")
}
step guards-status        "$HOME/bin/refresh-guards-status.sh"
step runner-guard-sweep   /usr/local/bin/windy-job windy-runner-guard-sweep 26h \
                            --expect "runner-guard sweep: 0 hit" --owner 13 -- "$HOME/bin/nightly-runner-guard-sweep.sh"
step contracts-drift      /usr/local/bin/windy-job windy-contracts-drift 26h \
                            --expect "contracts drift sweep: [0-9]+ consumer" --owner 13 -- "$HOME/bin/nightly-contracts-drift.sh"
# Token hygiene by count (10-10, after #18): no sync token in any file, remote URL or argv on Veron.
step sync-token-hygiene   /usr/local/bin/windy-job windy-sync-token-hygiene 26h \
                            --expect "sync token hygiene: files=0 remote-creds=0 argv=0" --owner 13 -- \
                            timeout 300 ssh -o BatchMode=yes -o ConnectTimeout=15 ts-veron \
                            'sudo -n timeout 240 bash /srv/windygit/src/scripts/sync_token_hygiene.sh'
# Merge audit (Hub A2, 10-10): repos GitHub can't protect (windy-vault, windy-contracts).
step merge-audit          /usr/local/bin/windy-job windy-merge-audit 26h \
                            --expect "merge audit: [0-9]+ merged, 0 flagged" --owner 13 -- \
                            timeout 300 python3 "$HOME/bin/merge_audit.py"
if [[ $(date -u +%u) == 1 ]]; then
  step public-secret-scan "$HOME/bin/weekly-public-secret-scan.sh"
fi
if (( ${#failed[@]} )); then
  echo "nightly sweep: failed: ${failed[*]}"
  exit 1
fi
echo "nightly sweep: ok"
