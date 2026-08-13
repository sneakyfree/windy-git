#!/usr/bin/env bash
# Phase 1 sync: GitHub is the source of truth, Windy Git follows.
#
# ── Why this direction, and why the other one was wrong ────────────────────
#
# On 2026-08-13 nine repos were migrated writable with push-mirrors pointed AT
# GitHub. That was premature: a dozen agent sessions on the Mac mini are pushing
# to GitHub continuously, so GitHub — not Windy Git — is where the current work
# actually lives. A push-mirror force-updates refs, so on its 8-hour timer it
# would have pushed Windy Git's stale copy over live work, silently, with no
# conflict to notice. The mirrors were removed before the first timer fired.
#
# This script is the correct Phase 1: pull from GitHub, push into Windy Git.
#
#   Mac mini agents ──push──▶ GitHub ──this script──▶ Windy Git ──▶ CI on Veron
#
# **It requires nothing from anyone.** No remote changes, no coordination, no
# "everybody stop pushing for a minute." Agents keep working exactly as they are
# and CI starts running on 24 cores.
#
# Windy Git is force-updated on purpose. In Phase 1 it holds nothing anyone
# depends on, so GitHub always wins and there is no merge to reconcile — which
# is the entire point of not flipping direction until a repo is quiet.
#
# Phase 2, per repo, only when that repo is idle: point its agents at Windy Git,
# drop it from REPOS here, and add a push-mirror back to GitHub. One repo at a
# time. Never a big-bang cutover across a dozen live sessions.

set -uo pipefail

: "${GITHUB_TOKEN:?GITHUB_TOKEN required}"
: "${GITEA_ADMIN_TOKEN:?GITEA_ADMIN_TOKEN required}"
GH_OWNER="${GITHUB_OWNER:-sneakyfree}"
WG="${WG_HOST:-app.windygit.com}"
WG_OWNER="${WINDYGIT_OWNER:-windyadmin}"
WORK="${SYNC_WORK:-/srv/windygit/sync}"
FAILED=0

# Repos Windy Git tracks FROM GitHub. Remove a repo from this list at the moment
# it flips to Windy-Git-first, or the sync will fight its authors and win.
REPOS="${SYNC_REPOS:-windy-calendar windy-search windy-registry Windy-Clone WindyCloud windy-cloud-sites windy-mind eternitas windy-agent}"

mkdir -p "$WORK"
log() { printf '[sync %s] %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }

for r in $REPOS; do
  bare="$WORK/${r}.git"
  if [[ ! -d "$bare" ]]; then
    git clone --quiet --bare "https://x-access-token:${GITHUB_TOKEN}@github.com/${GH_OWNER}/${r}.git" "$bare" 2>/dev/null \
      || { log "FAILED initial clone of $r"; FAILED=1; continue; }
  fi

  # +refs/heads/*  — branches only, deliberately.
  #
  # `--mirror` would also carry refs/pull/* (GitHub's read-only PR refs, which
  # Gitea rejects) and every remote-tracking ref, turning a working sync into a
  # wall of errors that hides the one that matters.
  if ! git --git-dir="$bare" fetch --quiet --prune origin '+refs/heads/*:refs/heads/*' '+refs/tags/*:refs/tags/*' 2>/dev/null; then
    log "FAILED fetch $r"; FAILED=1; continue
  fi

  before="$(git --git-dir="$bare" rev-parse HEAD 2>/dev/null || echo none)"

  if git --git-dir="$bare" push --quiet --force \
       "https://${WG_OWNER}:${GITEA_ADMIN_TOKEN}@${WG}/${WG_OWNER}/${r}.git" \
       '+refs/heads/*:refs/heads/*' '+refs/tags/*:refs/tags/*' 2>/dev/null; then
    log "$r ok (${before:0:7})"
  else
    log "FAILED push $r -> windy git"; FAILED=1
  fi
done

[[ "$FAILED" -ne 0 ]] && { log "COMPLETED WITH FAILURES"; exit 1; }
log "all repos in step with GitHub"
