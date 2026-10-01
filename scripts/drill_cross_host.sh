#!/usr/bin/env bash
# Cross-host restore drill on Windy 0: ONLY lockbox + R2, nothing from Veron. Values never printed.
# Usage: bash drill_cross_host.sh   (needs lockbox keys RESTIC_WINDYGIT_PASSWORD, WINDYGIT_R2_ACCESS_KEY_ID, WINDYGIT_R2_SECRET_ACCESS_KEY, WINDYGIT_R2_ENDPOINT)
set -euo pipefail
umask 077; W=$(mktemp -d ~/.cache/wg-xdrill.XXXXXX)
trap 'docker rm -f wg-xdrill-pg >/dev/null 2>&1 || true; rm -rf "$W"' EXIT
lockbox-get RESTIC_WINDYGIT_PASSWORD "$W/pw" >/dev/null
lockbox-get WINDYGIT_R2_ACCESS_KEY_ID "$W/ak" >/dev/null; lockbox-get WINDYGIT_R2_SECRET_ACCESS_KEY "$W/sk" >/dev/null; lockbox-get WINDYGIT_R2_ENDPOINT "$W/ep" >/dev/null
export RESTIC_PASSWORD_FILE="$W/pw" AWS_ACCESS_KEY_ID="$(cat "$W/ak")" AWS_SECRET_ACCESS_KEY="$(cat "$W/sk")"
export RESTIC_REPOSITORY="s3:$(cat "$W/ep")/windy-git-backups/restic"
restic snapshots --tag windygit-state --compact | tail -3
restic restore latest --tag windygit-state --target "$W/r" --include /var/backups/windygit-state --include /srv/windygit/git/gitea/conf --quiet
ls -l "$W/r/var/backups/windygit-state" | awk 'NR>1{print $5, $NF}'
docker run -d --name wg-xdrill-pg -e POSTGRES_PASSWORD="$(python3 -c 'import secrets;print(secrets.token_hex(12))')" -e POSTGRES_USER=drill postgres:16-alpine >/dev/null
for i in $(seq 1 30); do docker exec wg-xdrill-pg pg_isready -U drill >/dev/null 2>&1 && break; sleep 2; done
for db in gitea windygit; do
  docker exec wg-xdrill-pg psql -U drill -d postgres -qc "create database $db"
  docker exec -i wg-xdrill-pg pg_restore -U drill -d $db --no-owner --no-privileges < "$W/r/var/backups/windygit-state/$db.dump" 2>&1 | grep -v "already exists" | head -2 || true
done
for t in repository issue pull_request '"user"' external_login_user action_run action_run_job; do
  echo "$t restored=$(docker exec wg-xdrill-pg psql -U drill -d gitea -Atc "select count(*) from $t")"
done
echo "cross-host drill OK (cleaned up)"
