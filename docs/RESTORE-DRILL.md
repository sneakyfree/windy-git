# Restoring Windy Git from the encrypted state backup

What is backed up (`scripts/backup_state.sh`, restic repo `s3:…/windy-git-backups/restic`, tag `windygit-state`):
both Postgres databases (`gitea`, `windygit`, custom-format dumps + globals), the whole Gitea data root
(`/srv/windygit/git`: config, jwt, attachments, avatars, templates AND the bare repositories),
`/srv/windygit/src/.env`, `deploy/runner/.env`, `/etc/cloudflared`, the windygit systemd drop-ins.
NOT in it: the restic password itself (lockbox `RESTIC_WINDYGIT_PASSWORD`) and the R2 access key
(scoped token `windy-git-r2-scoped`, lockbox). Never print either: use `lockbox-get KEY FILE`.

## Drill (any machine with restic + docker; proven on Veron 2026-10-01, counts identical)
    export RESTIC_PASSWORD_FILE=<0600 file from lockbox-get RESTIC_WINDYGIT_PASSWORD>
    export AWS_ACCESS_KEY_ID=… AWS_SECRET_ACCESS_KEY=…            # from lockbox-get, into env, not echoed
    export RESTIC_REPOSITORY=s3:https://<R2 account>.r2.cloudflarestorage.com/windy-git-backups/restic
    restic snapshots --tag windygit-state
    restic restore latest --tag windygit-state --target /var/tmp/wg-drill
    docker run -d --name wg-drill-pg -e POSTGRES_PASSWORD=<random> -e POSTGRES_USER=drill postgres:16-alpine
    for db in gitea windygit; do
      docker exec wg-drill-pg psql -U drill -d postgres -c "create database $db"
      docker exec -i wg-drill-pg pg_restore -U drill -d $db --no-owner --no-privileges \
        < /var/tmp/wg-drill/var/backups/windygit-state/$db.dump
    done
    # compare row counts with live (or with the last known): repository, issue, pull_request, "user",
    # external_login_user, access_token, action_run, action_run_job
    docker rm -f wg-drill-pg; rm -rf /var/tmp/wg-drill

## Real disaster (Veron lost)
1. New Linux host with Docker, a Cloudflare tunnel connector, the repo (`git clone` from GitHub: windy-git).
2. `restic restore latest --tag windygit-state --target /` (puts /srv/windygit/git, the .env files, /etc/cloudflared back).
3. `docker compose -p windy-git up -d db`, then pg_restore both dumps into it (as above, into the real db names/owner from `.env`).
4. `docker compose -p windy-git up -d` + `deploy/runner` runners; re-register runners if the token changed.
5. Verify: `/api/healthz`, Windy SSO login, `git ls-remote`, one CI run. GitHub is still the source of truth for code,
   so repo content can also be re-synced from there; the database is what only this backup holds.
Retention: 14 daily / 8 weekly / 6 monthly (prune on Sundays). Integrity: every run does `restic check --read-data-subset=2%`.
