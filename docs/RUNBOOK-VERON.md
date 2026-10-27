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
| `127.0.0.1:2021` | cloudflared metrics (`metrics:` in `/etc/cloudflared/config.yml`, which lives ON THE HOST ONLY, not in this repo) — **not 2000/2001**, see Troubleshooting |

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
| `windygit-mirror-lag.timer` | hourly | `scripts/mirror_lag.py`: every pull mirror vs GitHub (stale refresh, head behind, source unreadable); reads only. Heartbeat `windygit-mirror-lag` (windy-uptime heartbeats-veron) goes red while any mirror lags. |
| `windygit-tunnel.service` | always | the only ingress |

## CI (Gitea Actions) — see `docs/CUTOVER.md` for onboarding a repo

- **Two runners × capacity 1 by default** (Boss 10-27: Veron ran at load 37-56; CI runs at most 2
  jobs at once). Runners 3-6 stay defined behind the compose profile `extra-runners`; start one
  only on a Boss GO, with a BOARD line. One shared dind capped at 12 cores / 64 GB. Capacity >1 in
  one runner shares `/root/.cache/act` between jobs and races (`lstat …: no such file`).
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
metrics port is **2021**. `sudo ss -ltnp | grep :2021` names any squatter.
**It recurred on 10-17:** after a desktop Software Updater reboot at 18:56Z,
`cornercall-tunnel` started first and took **2001** (its port floats to the first
free one in the 2000s), so `windygit-tunnel` crash-looped, `app.`/`api.` returned
530, and every runner crash-looped too (they reach Gitea via `app.windygit.com`).
Fixed by moving ours to 2021, outside that range and outside cloudflared's own
default (20241-20245). Take a `predeploy-snapshot` of `/etc/cloudflared/config.yml`
before editing it. Never edit `cornercall-tunnel`: it is not ours.
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

## Sync token hygiene (by count)

Since #18 the sync's tokens ride only as auth headers in git's env-only config: never in a URL, argv or
any config file. `scripts/sync_token_hygiene.sh` checks that by count, printing counts only and
never a value. It runs nightly from Windy 0's sweep (heartbeat `windy-sync-token-hygiene`, 26h). By hand:

    sudo bash /srv/windygit/src/scripts/sync_token_hygiene.sh
    # sync token hygiene: files=0 remote-creds=0 argv=0 dir=root:root/750 loose-configs=0

Anything but zeros, or a dir other than `root:root/750`, means a regression. Fix it before anything
else, and never print a token to find it: compare sha256[:10] only.

## Stop a runner without killing its job (the safe drain)

Under a deep queue a runner claims its next job within `fetch_interval` (2 s) of finishing one, so
"wait until idle, then `docker stop`" loses the race. A `docker stop` on a runner that just claimed a
job drains for `shutdown_timeout` (3m) and then KILLS a longer job. Per runner:
1. the DB says idle (`action_task` status 6 count = 0 for its name);
2. `docker pause <c>` (frozen, so it can't claim);
3. after 1 s, re-check: if it's now busy, `docker unpause` and try later;
4. still idle: `docker update --restart=no <c>` and `docker kill <c>` (no job, so nothing is lost).
To apply a config change, start it again (`docker start`). After interrupting a drain loop, check
`docker ps -a --filter status=paused` and unpause any leftovers. Every wait loop needs a deadline.

## Move one job to the front of the queue (GO'd prod deploys only)

Boss rule (10-27): only a PR with a **GO'd same-day prod deploy** jumps the queue; ask Boss for any
other. BOARD line before and after.

```bash
ssh wg-veron
cd /srv/windygit/src && bash scripts/queue_jump.sh <action_run_job id>
```
Gitea 1.24 has no priority knob: a runner gets the waiting job with the lowest `updated`, then
`id`. The script refuses unless the job is waiting and unclaimed. It sets that one row's `updated`
one second below the oldest waiting job, then watches: OK when it is the next job picked; if any
other job is picked first (or none within `QUEUE_JUMP_WAIT`, default 30 min) it restores the old
value and exits 1. First use: 10-27, windy-admin run 74 went next, ahead of about 140.
Don't cancel a duplicate run to post a "same tree" status by hand: the status bridge maps
cancelled to `error` and re-posts that every cycle over any manual status.

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


## Reading a CI job log (lanes)

A failed `windy-git/...` status on GitHub starts with `(job N)`. Any lane can read that job's
step log with the read-only token `WINDYGIT_CI_READ_TOKEN` (lockbox). It belongs to the restricted Gitea
user `windy-ci-reader`: read collaborator on the private CI repos, scope `read:repository`,
no write, no admin. One line for bash or zsh with curl 7.55+ (`-H @file`), on Linux or macOS;
the token never reaches argv or the screen, and the temp file is shredded (`rm -P` is the macOS fallback):

```bash
t=$(mktemp) && lockbox-get WINDYGIT_CI_READ_TOKEN "$t" && curl -s -H @<(printf 'Authorization: token %s\n' "$(cat "$t")") https://app.windygit.com/api/v1/repos/windyadmin/<repo>/actions/jobs/<job>/logs | tail -40; { shred -u "$t" 2>/dev/null || rm -P "$t"; }
```

`runner lost, re-run it: step N/M` means Gitea stopped the task because its runner went away
(host restart, runner crash). That is not a test failure: re-run it at the same head
(see "Re-run a PR's CI" above, `scripts/rerun_ci.sh`).
Quote only error lines from the log on the BOARD, never env or token-shaped strings.
A new repo that is promoted to CI needs `windy-ci-reader` added as a read collaborator
(`PUT /repos/windyadmin/<repo>/collaborators/windy-ci-reader` with `{"permission":"read"}`).
