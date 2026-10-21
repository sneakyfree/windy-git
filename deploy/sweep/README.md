# Nightly sweep (Veron)

One user timer runs five checks at 09:40 UTC. They change nothing in any repo; guards-status runs `guards_report.py` with `sudo -n`, because it reads repo trees inside the Gitea container (Boss simplify rulings E, 10-07). It moved from Windy 0 to Veron on 2026-10-21, when every Windy lane left Windy 0.

| step | what it does | heartbeat (windy-job) |
|---|---|---|
| guards-status | `scripts/guards_report.py` → `GUARDS_STATUS.md`, plus the prod-vs-lock column from Windy Search's `PROD_LOCK_DRIFT.md` | none |
| runner-guard-sweep | `scripts/runner_guard.py report` over every public repo → `RUNNER_GUARD.md` | `windy-runner-guard-sweep` |
| contracts-drift | `scripts/contracts_drift.py` → `CONTRACTS_DRIFT.md` | `windy-contracts-drift` |
| merge-audit | `scripts/merge_audit.py` (windy-vault, windy-contracts) | `windy-merge-audit` |
| public-secret-scan | Mondays only, `scripts/public_secret_scan.py` → `PUBLIC_SECRET_SCAN.md` | none |

The checks run next to `/srv/windygit/src`. The pages and the BOARD still live on Windy 0 (`~/windy-orchestra`), so `common.sh` writes them over `ssh eth-windy0`, and a failed write fails the step. Heartbeats land in Veron's `/var/lib/windy-heartbeats`, which the windy-uptime check `heartbeats-veron` reads.

When something new turns up (a guard's lane count reaches 0, a new runner-guard hit, a new contract drift, a new public secret), the sweep writes one BOARD line. The old `claude -p` message to "Windy Boss Terminal" was dropped in the move, because that session no longer exists and Boss reads the BOARD.

## Install (user1-gpu on Veron)

```
mkdir -p ~/.local/share/windygit-sweep/bin
cp deploy/sweep/*.sh deploy/sweep/merge-prod-lock-drift.py ~/.local/share/windygit-sweep/bin/
cp deploy/sweep/windygit-nightly-sweep.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now windygit-nightly-sweep.timer
```

State (the "what was new last time" lists) lives in `~/.local/state/windygit-sweep/`. In a tmux shell, `systemctl --user` needs `XDG_RUNTIME_DIR=/run/user/1005 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1005/bus`.

To roll back, disable the Veron timer. The Windy 0 copy was deleted on 2026-10-21, so to run it there again, reinstall these scripts on Windy 0 with ssh to Veron.
