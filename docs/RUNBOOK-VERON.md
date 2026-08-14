# RUNBOOK — Windy Git on Veron 1 (rung R0)

Host `Veron-1-5090`, WireGuard `10.10.0.6`, alias `wg-veron`. Passwordless sudo.

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

## Ports — all loopback, on purpose

| Port | Service |
|---|---|
| `127.0.0.1:3080` | Gitea (host 3000 is a resident node dev server; 3300 is nginx — **do not fight them for a port**) |
| `127.0.0.1:8600` | windy-git API |
| `127.0.0.1:2000` | cloudflared metrics |

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
cd /srv/windygit/src && git pull
export COMMIT_SHA_BUILD=$(git rev-parse HEAD) BUILT_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
sudo -E docker compose up -d --build
curl -s https://api.windygit.com/version    # MUST equal git rev-parse HEAD
```

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

## Troubleshooting

**A hostname returns 530 or won't resolve** — the tunnel is down. `sudo systemctl
restart windygit-tunnel`, then `journalctl -u windygit-tunnel -n 50`.

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
