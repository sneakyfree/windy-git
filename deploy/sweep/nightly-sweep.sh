#!/usr/bin/env bash
# One nightly sweep (Boss simplify rulings E, 10-07), on Veron since 2026-10-21 (Grant: every
# Windy lane off Windy 0). Same steps as the Windy 0 ~/bin/nightly-sweep.sh it replaces; each
# step is its own script. One failing step does not stop the others; the sweep exits 1 if any
# failed. The windy-job heartbeat names are unchanged, so windy-uptime alerts on the same jobs
# (now under /var/lib/windy-heartbeats on Veron). The public secret scan (up to ~2 h) runs on
# Mondays (UTC) only. Pages + BOARD lines still go to Windy 0 ~/windy-orchestra over ssh.
# Units: ~/.config/systemd/user/windygit-nightly-sweep.{service,timer}.
set -uo pipefail
here=$(dirname "$(readlink -f "$0")")
failed=()
step() {  # step <name> <command...>
  echo "== $1"
  "${@:2}" || failed+=("$1")
}
step guards-status        "$here/refresh-guards-status.sh"
step runner-guard-sweep   /usr/local/bin/windy-job windy-runner-guard-sweep 26h \
                            --expect "runner-guard sweep: 0 hit" --owner 13 -- "$here/nightly-runner-guard-sweep.sh"
step contracts-drift      /usr/local/bin/windy-job windy-contracts-drift 26h \
                            --expect "contracts drift sweep: [0-9]+ consumer" --owner 13 -- "$here/nightly-contracts-drift.sh"
# Merge audit (Hub A2, 10-10): repos GitHub can't protect (windy-vault, windy-contracts).
step merge-audit          /usr/local/bin/windy-job windy-merge-audit 26h \
                            --expect "merge audit: [0-9]+ merged, 0 flagged" --owner 13 -- \
                            timeout 300 python3 /srv/windygit/src/scripts/merge_audit.py
if [[ $(date -u +%u) == 1 ]]; then
  step public-secret-scan "$here/weekly-public-secret-scan.sh"
fi
if (( ${#failed[@]} )); then
  echo "nightly sweep: failed: ${failed[*]}"
  exit 1
fi
echo "nightly sweep: ok"
