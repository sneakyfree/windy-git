#!/usr/bin/env bash
# Nightly STATE backup: everything git bundles do NOT hold (SOTU 10-01: 625 issues/PRs, users,
# SSO links, CI history, settings lived on one unbacked-up host). Encrypted restic repo in R2.
#   - Postgres: every database (custom-format dump, restore-listable) + globals
#   - Gitea config/data (app.ini, jwt, attachments, avatars, templates) + the bare repositories
#   - the deploy .env files, systemd drop-ins and the cloudflared tunnel config (needed to rebuild)
# The restic password lives in /etc/windygit/restic.pass (root 600) AND the lockbox
# (RESTIC_WINDYGIT_PASSWORD): a lost Veron must not lose the backups. NEVER echo env/values here.
# Restore: docs/RESTORE-DRILL.md. Bounded: every docker exec runs under `timeout` (a hung
# runc exec in the IO stall wedged the sync on 09-23).
set -euo pipefail
log() { echo "[backup_state $(date -u +%FT%TZ)] $*"; }
: "${R2_ACCOUNT_ID:?}" "${R2_ACCESS_KEY_ID:?}" "${R2_SECRET_ACCESS_KEY:?}"
PASSFILE="${RESTIC_PASSWORD_FILE:-/etc/windygit/restic.pass}"
[[ -s "$PASSFILE" ]] || { log "FATAL: $PASSFILE missing/empty: refusing to report a backup that did not happen"; exit 1; }
export RESTIC_PASSWORD_FILE="$PASSFILE"
export AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
export RESTIC_REPOSITORY="${RESTIC_REPOSITORY:-s3:https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com/${R2_BUCKET_BACKUPS:-windy-git-backups}/restic}"
DB="${WG_DB_CONTAINER:-windy-git-db-1}"
STAGE="${WG_STAGE:-/var/backups/windygit-state}"
GIT_ROOT="${GIT_DATA_ROOT:-/srv/windygit/git}"
umask 077
mkdir -p "$STAGE"; chmod 700 "$STAGE"; rm -f "$STAGE"/*.dump "$STAGE"/globals.sql

# systemd gives units no $HOME, and restic wants a cache dir: pin one.
export RESTIC_CACHE_DIR="${RESTIC_CACHE_DIR:-/var/cache/windygit-restic}"; mkdir -p "$RESTIC_CACHE_DIR"
if ! err=$(restic cat config 2>&1 >/dev/null); then
  # only a MISSING repo may be initialised; any other error (auth, network, wrong password) must stop here
  if grep -qiE "does not exist|is there a repository|unable to open config file" <<<"$err"; then
    log "initialising restic repo"; restic init >/dev/null
  else
    log "FATAL: restic cannot open the repository: $(head -c 300 <<<"$err" | tr '\n' ' ')"; exit 1
  fi
fi

PGU=$(timeout 30 docker exec "$DB" printenv POSTGRES_USER)
[[ -n "$PGU" ]] || { log "FATAL: no POSTGRES_USER in $DB"; exit 1; }
dbs=$(timeout 60 docker exec "$DB" psql -U "$PGU" -Atc "select datname from pg_database where not datistemplate and datname<>'postgres' order by 1")
n=0
for d in $dbs; do
  timeout 600 docker exec "$DB" pg_dump -U "$PGU" -Fc "$d" > "$STAGE/$d.dump"
  # a dump that cannot be listed is not a backup
  timeout 120 docker exec -i "$DB" pg_restore -l < "$STAGE/$d.dump" >/dev/null
  [[ $(stat -c%s "$STAGE/$d.dump") -gt 1000 ]] || { log "FATAL: $d dump suspiciously small"; exit 1; }
  n=$((n+1)); log "dumped $d ($(stat -c%s "$STAGE/$d.dump") bytes)"
done
[[ $n -ge 1 ]] || { log "FATAL: no databases dumped"; exit 1; }
timeout 120 docker exec "$DB" pg_dumpall -U "$PGU" --globals-only > "$STAGE/globals.sql"

paths=("$STAGE" "$GIT_ROOT" /srv/windygit/src/.env /srv/windygit/src/deploy/runner/.env /etc/cloudflared)
for p in /etc/systemd/system/windygit-*.service.d /etc/windygit; do [[ -e $p ]] && paths+=("$p"); done
# restic.pass itself is excluded: the password never rides in its own backup
snap=$(restic backup --tag windygit-state --host windygit-veron --quiet --json \
  --exclude "$GIT_ROOT/gitea/log" --exclude "$GIT_ROOT/gitea/queues" --exclude "$GIT_ROOT/gitea/tmp" \
  --exclude "$GIT_ROOT/gitea/indexers" --exclude "$GIT_ROOT/gitea/actions_log" --exclude /etc/windygit/restic.pass \
  "${paths[@]}" | python3 -c 'import sys,json
for l in sys.stdin:
    d=json.loads(l)
    if d.get("message_type")=="summary": print(d["snapshot_id"][:8])')
[[ -n "$snap" ]] || { log "FATAL: restic produced no snapshot"; exit 1; }
rm -f "$STAGE"/*.dump "$STAGE"/globals.sql
restic check --read-data-subset=2% --quiet >/dev/null || { log "FATAL: restic check failed"; exit 1; }
if [[ $(date +%u) == 7 ]]; then
  restic forget --tag windygit-state --keep-daily 14 --keep-weekly 8 --keep-monthly 6 --prune --quiet >/dev/null
fi
echo "ok — state backed up ($n dbs, snapshot $snap)"
