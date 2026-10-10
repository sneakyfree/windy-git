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
# The narrow token (scope write:repository only, Gitea token "windygit-sync" on
# windyadmin; /etc/windygit/sync.env). The admin token is for humans: the
# fallback exists only so a rollback to the old unit keeps working.
GITEA_TOKEN="${GITEA_SYNC_TOKEN:-${GITEA_ADMIN_TOKEN:-}}"
: "${GITEA_TOKEN:?GITEA_SYNC_TOKEN required}"
GH_OWNER="${GITHUB_OWNER:-sneakyfree}"
WG="${WG_HOST:-app.windygit.com}"
WG_OWNER="${WINDYGIT_OWNER:-windyadmin}"
WORK="${SYNC_WORK:-/srv/windygit/sync}"
GH_GIT="${GITHUB_GIT_BASE:-https://github.com}"
WG_GIT="${WG_GIT_BASE:-https://${WG}}"
# One hung transfer must not stall every repo behind it (10-10: a windy-call
# fetch hung 5 min, holding the bridge and every lane's CI statuses).
GIT_TIMEOUT="${SYNC_GIT_TIMEOUT:-300}"
FAILED=0

# Repos Windy Git tracks FROM GitHub. Remove a repo from this list at the moment
# it flips to Windy-Git-first, or the sync will fight its authors and win.
REPOS="${SYNC_REPOS:-windy-calendar windy-search windy-registry Windy-Clone WindyCloud windy-cloud-sites windy-mind eternitas windy-agent windy-git windy-chat windy-mail windy-connect windy-drops windy-code-web windy-code windy-traveler windy-translate windytranslate-site windytraveler-site windy-hand windy-cloud-domains windy-cloud-vps windytalk windy-pro windy-inbox windy-text windy-call windy-cell windy-hand-site windy-calendar-site windy-contracts windy-vault}"

# Repos whose TAGS must not reach Windy Git. A tag push fires `on: push: tags`
# workflows; windy-pro's build-electron is a matrix over ubuntu/macos/windows-
# latest, labels no runner here has, so every leg would queue forever (and
# queued jobs are invisible in /actions/tasks). Releases are built elsewhere.
NO_TAGS="${SYNC_NO_TAGS:-windy-pro}"

# `archive/*` branches never reach Windy Git (negative refspec, git >= 2.29).
# They are off-machine safety copies of unpushed work (one-repo doctrine), not
# work in progress: GitHub holds them, and CI time on them is waste.

# Tokens never go in a URL or on a command line (10-10: GITHUB_TOKEN sat in
# every bare repo's config and in `ps` for any local user on Veron). They ride
# as per-host auth headers in git's env-only config (GIT_CONFIG_COUNT, git >=
# 2.31); a root process's environ is readable by root only. printf is a
# builtin, so the token never reaches argv here either.
gh_auth="Authorization: Basic $(printf 'x-access-token:%s' "$GITHUB_TOKEN" | base64 | tr -d '\n')"
wg_auth="Authorization: Basic $(printf '%s:%s' "$WG_OWNER" "$GITEA_TOKEN" | base64 | tr -d '\n')"
git_authed() {
  GIT_TERMINAL_PROMPT=0 GIT_CONFIG_COUNT=5 \
    GIT_CONFIG_KEY_0="http.${GH_GIT}/.extraheader" GIT_CONFIG_VALUE_0="$gh_auth" \
    GIT_CONFIG_KEY_1="http.${WG_GIT}/.extraheader" GIT_CONFIG_VALUE_1="$wg_auth" \
    GIT_CONFIG_KEY_2=credential.helper GIT_CONFIG_VALUE_2= \
    GIT_CONFIG_KEY_3=http.lowSpeedLimit GIT_CONFIG_VALUE_3=1000 \
    GIT_CONFIG_KEY_4=http.lowSpeedTime GIT_CONFIG_VALUE_4=60 \
    timeout -k 10 "$GIT_TIMEOUT" git "$@"
}
why() { [[ $1 -eq 124 || $1 -eq 137 ]] && echo " (timed out after ${GIT_TIMEOUT}s)"; }

umask 077
mkdir -p "$WORK" && chmod 0750 "$WORK"
log() { printf '[sync %s] %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }

for r in $REPOS; do
  bare="$WORK/${r}.git"
  src="${GH_GIT}/${GH_OWNER}/${r}.git"
  if [[ ! -d "$bare" ]]; then
    git_authed clone --quiet --bare "$src" "$bare" 2>/dev/null \
      || { rc=$?; log "FAILED initial clone of $r$(why $rc)"; FAILED=1; continue; }
  fi
  # Older clones stored the token in their remote URL: replace it with the plain one.
  [[ "$(git --git-dir="$bare" remote get-url origin 2>/dev/null)" == "$src" ]] \
    || git --git-dir="$bare" remote set-url origin "$src"

  # +refs/heads/*  — branches only, deliberately.
  #
  # `--mirror` would also carry refs/pull/* (GitHub's read-only PR refs, which
  # Gitea rejects) and every remote-tracking ref, turning a working sync into a
  # wall of errors that hides the one that matters.
  git_authed --git-dir="$bare" fetch --quiet --prune origin '+refs/heads/*:refs/heads/*' '+refs/tags/*:refs/tags/*' 2>/dev/null \
    || { rc=$?; log "FAILED fetch $r$(why $rc)"; FAILED=1; continue; }

  before="$(git --git-dir="$bare" rev-parse HEAD 2>/dev/null || echo none)"

  if git_authed --git-dir="$bare" push --quiet --force \
       "${WG_GIT}/${WG_OWNER}/${r}.git" \
       '+refs/heads/*:refs/heads/*' '^refs/heads/archive/*' $([[ " $NO_TAGS " == *" $r "* ]] || echo '+refs/tags/*:refs/tags/*') 2>/dev/null; then
    log "$r ok (${before:0:7})"
  else
    rc=$?; log "FAILED push $r -> windy git$(why $rc)"; FAILED=1
  fi
done

# Jobs that name labels no runner has (ubuntu/macos/windows-latest) would wait
# forever and invisibly; cancel them after 30 min. Never fails the sync.
# Both DB steps go through `docker exec`, which hangs outright while the host
# is in an IO stall (09-23: data2 SMR cliff wedged this sync for 10+ min and
# stopped mirroring + the bridge for every lane). They are optional; mirroring
# and the bridge are not. Bound them so a stuck exec costs one step, not the run.
timeout -k 10 120 bash "$(dirname "$0")/cancel_unrunnable.sh" || log "janitor failed or timed out (non-fatal)"

# Private repos can't run GitHub Actions; mirror their open PRs here so CI
# fires, and post the verdicts back to GitHub as commit statuses.
if ! python3 "$(dirname "$0")/pr_status_bridge.py"; then
  log "FAILED pr status bridge"; FAILED=1
fi

# Runner guard (Boss 10-01): PUBLIC sneakyfree repos have self-hosted GitHub runners on Veron.
# A PR that changes a workflow so a stranger's code could reach one gets a red
# windy-git/runner-guard status. Each status is posted once; never fails the sync.
timeout -k 10 120 python3 "$(dirname "$0")/runner_guard.py" pr --post || log "runner-guard failed or timed out (non-fatal)"

# CI telemetry -> admin.windyword.ai (shapes declared with Windy Telemetry 40).
# Sends nothing until WINDYGIT_TELEMETRY_TOKEN is set; never fails the sync.
timeout -k 10 180 python3 "$(dirname "$0")/telemetry_emit.py" || log "telemetry emit failed or timed out (non-fatal)"

[[ "$FAILED" -ne 0 ]] && { log "COMPLETED WITH FAILURES"; exit 1; }
log "all repos in step with GitHub"
