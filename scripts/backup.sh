#!/usr/bin/env bash
# Nightly backup (G0.9) — the prerequisite for Windy Git becoming the daily driver.
#
# Today GitHub is authoritative, so losing Veron 1 costs nothing. The moment
# people push HERE first, that inverts: Veron 1 holds the only current copy of
# the company's source between mirror syncs, and Veron 1 is Grant's workstation
# — no SLA, no snapshots, a residential line, and he reboots it.
#
# `git bundle` is used deliberately over tarring the repo directory: a bundle is
# a single file that `git clone` reads directly, so a restore is one command and
# needs no knowledge of Gitea's on-disk layout. Tarring a live repo directory
# also races with a concurrent push; bundling asks git for a consistent view.
#
# The whole archive measured 1.58 GB across 141 repos, so this costs about two
# cents a month on R2 and takes minutes. There is no reason for it not to exist.

set -uo pipefail

STAMP="$(date -u +%Y-%m-%d)"
WORK="$(mktemp -d /tmp/windygit-backup-XXXXXX)"
GIT_ROOT="${GIT_DATA_ROOT:-/srv/windygit/git}/git/repositories"
BUCKET="${R2_BUCKET_BACKUPS:-windy-git-backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-30}"
FAILED=0

cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

log() { printf '[backup %s] %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }

if [[ -z "${R2_ACCESS_KEY_ID:-}" || -z "${R2_SECRET_ACCESS_KEY:-}" ]]; then
  log "FATAL: R2 credentials unset — refusing to report a backup that did not happen"
  exit 1
fi

export AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID"
export AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
export AWS_DEFAULT_REGION=auto
S3="aws s3 --endpoint-url https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

# ---- 1. every repo, as a restorable bundle -------------------------------
shopt -s nullglob
count=0
for repo in "$GIT_ROOT"/*/*.git; do
  owner="$(basename "$(dirname "$repo")")"
  name="$(basename "$repo" .git)"
  out="$WORK/${owner}__${name}.bundle"

  # --all captures every ref, not just the default branch. A bundle of one
  # branch silently loses every other branch and every tag, and you find out
  # during the restore.
  if git --git-dir="$repo" bundle create "$out" --all >/dev/null 2>&1; then
    # Verify before trusting. An unverified bundle is a belief, not a backup.
    if git bundle verify "$out" >/dev/null 2>&1; then
      count=$((count + 1))
    else
      log "CORRUPT bundle for ${owner}/${name} — not uploading"
      rm -f "$out"; FAILED=1
    fi
  else
    # An empty repo has no refs and cannot be bundled. That is normal, not a
    # failure — say so rather than counting it as an error.
    if [[ -z "$(git --git-dir="$repo" for-each-ref 2>/dev/null)" ]]; then
      log "skip ${owner}/${name} (empty repo, no refs)"
    else
      log "FAILED to bundle ${owner}/${name}"; FAILED=1
    fi
    rm -f "$out"
  fi
done
log "bundled $count repos"

# ---- 2. the plane's own database ------------------------------------------
# Postgres is truth for repos, grants, versions, tokens and mirror state. The
# bundles restore the code; this restores who may touch it.
if docker exec windy-git-db-1 pg_dump -U windygit -d windygit --schema=windgit \
     > "$WORK/windgit.sql" 2>/dev/null && [[ -s "$WORK/windgit.sql" ]]; then
  log "dumped windgit schema ($(wc -c < "$WORK/windgit.sql") bytes)"
else
  log "FAILED to dump the database"; FAILED=1
fi

# ---- 3. upload ------------------------------------------------------------
if $S3 cp "$WORK" "s3://${BUCKET}/${STAMP}/" --recursive --only-show-errors; then
  log "uploaded to s3://${BUCKET}/${STAMP}/"
else
  log "FATAL: upload failed"; exit 1
fi

# ---- 4. retention ---------------------------------------------------------
cutoff="$(date -u -d "${KEEP_DAYS} days ago" +%Y-%m-%d 2>/dev/null || true)"
if [[ -n "$cutoff" ]]; then
  $S3 ls "s3://${BUCKET}/" | awk '{print $2}' | tr -d '/' | while read -r d; do
    [[ "$d" < "$cutoff" ]] && { log "pruning $d"; $S3 rm "s3://${BUCKET}/${d}/" --recursive --only-show-errors; }
  done
fi

# Non-zero on ANY failure so the systemd unit goes red and the failure is
# visible. A backup script that swallows errors is worse than none — it
# manufactures confidence.
if [[ "$FAILED" -ne 0 ]]; then
  log "COMPLETED WITH FAILURES"
  exit 1
fi
log "ok — $count repos + database"
