# RUNBOOK — Windy Git on Veron 1 (rung R0)

Host `Veron-1-5090`, WireGuard `10.10.0.6`, alias `wg-veron` (or `ts-veron`). Passwordless sudo.

**Checkouts (one-repo doctrine):** the ONE standing dev checkout is **OC5
`~/windy-git`** (platform repos live on OC5). `/srv/windygit/src` on Veron is the
*deploy* copy — it holds no local work. Nothing else should exist.

⛔ **Kit 0 is never a host for this service** (D-4). `api/app/main.py` refuses to
boot in production if it finds itself on `72.60.118.54`.

## Layout

| Path | Holds |
|---|---|
| `/srv/windygit/src` | the deploy checkout (clone of `sneakyfree/windy-git`) |
| `/srv/windygit/git` | **git object databases + Gitea data** — local NVMe, truth (I-3) |
| `/srv/windygit/src/data/pg` | Postgres data |
| `/etc/cloudflared/config.yml` | tunnel ingress |
| `/etc/cloudflared/windy-git.json` | tunnel credentials, mode 600 |
| `/srv/windygit/src/.env` | secrets, mode 600, **never committed** |
| `/srv/windygit/git/gitea/conf/app.ini` | Gitea's persisted config — env-to-ini SETS but never UNSETS; edit here when removing a `GITEA__*` var |
| `/srv/windygit/sync/*.git` | bare staging copies the GitHub→Windy Git sync pushes from |
| `/srv/windygit/src/deploy/runner/.env` | `RUNNER_TOKEN` — a **windyadmin user-level** registration token (not instance-level; see CI) |

## Ports — all loopback, on purpose

| Port | Service |
|---|---|
| `127.0.0.1:3080` | Gitea (host 3000 is a resident node dev server; 3300 is nginx — **do not fight them for a port**) |
| `127.0.0.1:8600` | windy-git API |
| `127.0.0.1:2001` | cloudflared metrics (`metrics:` in `/etc/cloudflared/config.yml`) — **not 2000**, see Troubleshooting |

**No inbound port is opened.** cloudflared dials out, so the dynamic residential
IP is irrelevant and there is no firewall hole to maintain.

## Start / stop

```bash
ssh wg-veron
cd /srv/windygit/src
sudo docker compose ps
sudo docker compose logs -f api
sudo systemctl status windygit-tunnel
```

## Deploy

```bash
ssh wg-veron
cd /srv/windygit/src && git fetch origin && git merge --ff-only origin/main   # READ the output
export COMMIT_SHA_BUILD=$(git rev-parse HEAD) BUILT_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
sudo -E docker compose up -d --build --no-deps api      # API only: no forge restart
curl -s https://api.windygit.com/version    # MUST equal git rev-parse HEAD
```

A Gitea config change (compose `GITEA__*`) needs `sudo docker compose up -d --no-deps gitea`
— a ~6 s forge outage; running CI jobs survive it. Check `app.ini` afterwards.

⚠️ **Never `git pull -q` in a deploy script.** `-q` hides *errors*, not just
noise. On 2026-08-14 a divergent branch made `pull -q` fail silently and the
"deploy" ran for 20 minutes against stale code while reporting success. Use
`git fetch && git merge --ff-only` (or `reset --hard origin/main` on THIS
checkout only, which holds no local work) and read the output.

⚠️ **Never force-push a branch a deploy checkout tracks.** An earlier
`git commit --amend` + `--force-with-lease` rewrote history `/srv/windygit/src`
was already sitting on, orphaning it. If you must amend, re-point the deploy
checkout in the same breath.

⚠️ **Never put `COMMIT_SHA` in `.env`.** It does nothing here — the sha is baked
into the image and a runtime override is ignored with a warning (I-12). That env
pin is the documented root cause of nine sibling services misreporting their
commit, and one reporting another repo's commit entirely.

## Verify (the four things that must be true)

```bash
curl -s https://api.windygit.com/version | jq         # source must be "baked"
curl -s https://api.windygit.com/health/full | jq     # degraded is HONEST, not broken
curl -sI https://app.windygit.com/ | head -1          # Gitea, 200
sudo ss -tlnp | grep -E "3080|8600"                   # both must be 127.0.0.1
```

## Timers (host systemd units — the sync timer is NOT in the repo)

| Unit | Cadence | Does |
|---|---|---|
| `windygit-sync.timer` | every 5 min (`OnUnitActiveSec`) | GitHub → Windy Git for `REPOS` in `scripts/sync_from_github.sh`, then `scripts/pr_status_bridge.py` (mirror PRs + GitHub commit statuses). A manual `systemctl start` RESETS the 5-min clock. |
| `windygit-backup.timer` | nightly | `git bundle` + pg_dump → R2, 30-day retention |
| `windygit-ci-prune.timer` | every 6 h | `deploy/runner/prune.sh` — CI dind storage, 60 GB cap |
| `windygit-tunnel.service` | always | the only ingress |

## CI (Gitea Actions) — see `docs/CUTOVER.md` for onboarding a repo

- **Six runners × capacity 1** (`deploy/runner/docker-compose.yml`), one shared
  dind capped at 12 cores / 64 GB. Capacity >1 in one runner shares
  `/root/.cache/act` between jobs and races (`lstat …: no such file`).
- **Runners are scoped to the `windyadmin` user** (`action_runner.owner_id=1`),
  so only first-party repos run. A repo owned by anyone else — a plane-created
  agent or `u-system` repo — gets NO runner. Re-registrations inherit this
  because `RUNNER_TOKEN` is user-level.
- Job ceiling 90 min (`config.yaml` `runner.timeout`); a `config.yaml` change
  needs each runner restarted **while idle** — `compose up -d` won't recreate it.
- `/actions/tasks` lists only PICKED-UP jobs. Queue truth is `action_run_job`
  in the `gitea` DB: `sudo docker exec -i windy-git-db-1 psql -U windygit -d gitea`
  (status 1 ok · 2 fail · 3 cancelled · 4 skipped · 5 waiting · 6 running).
- Job logs are in R2, not on disk. `GET /api/v1/repos/{o}/{r}/actions/jobs/{JOB_ID}/logs`
  takes the `action_run_job` id, not the task id.

## Sign-in posture

- Windy SSO only: password + passkey forms OFF, `ACCOUNT_LINKING=login`,
  **auto-registration OFF** — opening the forge to non-Grant users is a §7
  Grant decision.
- **Break-glass:** `sudo docker exec -u git windy-git-gitea-1 gitea admin user generate-access-token --username windyadmin --token-name <name> --scopes <scopes> --raw`
  (delete it after: `delete from access_token where name='<name>'` in the gitea DB —
  Gitea refuses token management over token auth).

## Troubleshooting

**A hostname returns 530 or won't resolve** — the tunnel is down. `sudo systemctl
restart windygit-tunnel`, then `journalctl -u windygit-tunnel -n 50`.

**`windygit-tunnel` crash-loops with `bind: address already in use` on the metrics
port** — cloudflared exits if it cannot bind `metrics:`, taking ingress with it.
Until 2026-09-23 this unit restarted ~91,000 times because another project's
`cornercall-tunnel` held 127.0.0.1:2000; ingress only survived because a stray
generic `cloudflared.service` ran the same config (now disabled). Windy Git's
metrics port is **2001**. `sudo ss -ltnp | grep :2001` names any squatter.
Keep exactly ONE unit running `/etc/cloudflared/config.yml`: `windygit-tunnel`.

**TLS handshake fails with `curl` exit 35 and no HTTP status at all** — someone
added a **two-level** hostname. Free Universal SSL covers `windygit.com` and
`*.windygit.com` only. The request dies before the tunnel is consulted, so it
presents as "the app is broken" when the app is perfect. Either go back to a
single level or buy Advanced Certificate Manager ($10/mo).

**Port bind fails on `docker compose up`** — a resident project took the port.
Set `GITEA_PORT` / `API_PORT` in `.env` and update `/etc/cloudflared/config.yml`
to match. **Never stop another project's container to free a port.**

**`/health/full` says degraded** — that is the design (I-8). Read `checks`: an
unconfigured provider is honest, not broken. R2, Gitea admin token and Eternitas
are wired in strands G2–G4.

## Promotion to R1 (first external push)

R0's honest limits: no SLA, it is Grant's workstation, and there are no
VPS-style snapshots. All acceptable while Grant is the only user; all
disqualifying the moment a stranger depends on it. **The trigger is not a date —
it is the first external push.** Move the control plane to a dedicated VPS (not
Kit 0), keep Veron 1 as the runner. It is an rsync, a Postgres dump and three
DNS record edits.

## Re-run a PR's CI (Gitea 1.24 has no rerun API)

```bash
ssh wg-veron
cd /srv/windygit/src && bash scripts/rerun_ci.sh <repo> <branch> <github-head-sha-prefix>
```
Moves the Windy Git branch back one commit; the next sync force-pushes the
GitHub head again and Gitea re-fires every workflow for that event on the same
commit. Guarded: refuses unless the branch is at the given sha, waits for a
sync that starts AFTER the rewind, restores the branch itself on timeout.
Don't use the web "Re-run" button: it needs a hub-SSO session as windyadmin,
which is Grant's identity.
