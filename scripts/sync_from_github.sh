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
# An incremental fetch of an existing clone is seconds; one that hangs before any data
# flows (lowSpeed* never trips) used to cost the whole 300 s and delay every repo after
# it (10-21 14:04Z: windy-agent; windy-pro and windy-calendar waited 10+ min). It gets
# FETCH_TIMEOUT and ONE retry on a fresh connection, which is what usually clears it.
FETCH_TIMEOUT="${SYNC_FETCH_TIMEOUT:-90}"
FAILED=0

# Repos Windy Git tracks FROM GitHub. Remove a repo from this list at the moment
# it flips to Windy-Git-first, or the sync will fight its authors and win.
REPOS="${SYNC_REPOS:-windy-calendar windy-search windy-registry Windy-Clone WindyCloud windy-cloud-sites windy-mind eternitas windy-agent windy-git windy-chat windy-mail windy-connect windy-drops windy-code-web windy-code windy-traveler windy-translate windytranslate-site windytraveler-site windy-hand windy-cloud-domains windy-cloud-vps windytalk windy-pro windy-inbox windy-text windy-hand-site windy-calendar-site windy-contracts windy-vault windy-uptime windy-pro-mobile windy-text-site windy-mind-acp windy-admin Windy-Clone-site windy-mind-site windyword-site}"

# Repos whose TAGS must not reach Windy Git. A tag push fires `on: push: tags`
# workflows; windy-pro's build-electron is a matrix over ubuntu/macos/windows-
# latest, labels no runner here has, so every leg would queue forever (and
# queued jobs are invisible in /actions/tasks). Releases are built elsewhere.
NO_TAGS="${SYNC_NO_TAGS:-windy-pro}"

# windy-call and windy-cell left this list 2026-10-21: archived (read-only) on GitHub
# by Windy Call; their Windy Git copies stay as frozen history.

# Branches GitHub deleted (merged PR heads, mostly) used to stay on Windy Git for
# ever: the bare cache below is fetched with --prune, but the push to Windy Git
# was not, so 1,923 had piled up by 10-21 and made lanes ask whether work existed
# only here. With SYNC_PRUNE_GONE=1, after each push, a branch that Windy Git has
# and GitHub no longer has is deleted on Windy Git ONLY if GitHub still holds its
# commit (scripts/github_has_commit.py exits 0). Every doubt keeps the branch.
# At most SYNC_PRUNE_MAX GitHub checks (one API call each) per repo per run, to spare
# the shared GitHub quota. A per-repo cursor in $WORK/prune-cursor.<repo> makes the next
# run start after the last branch checked (wrapping at the end), so a backlog drains
# instead of re-checking the same kept branches every 5 min. The delete carries a lease
# on the checked sha: a branch moved on Windy Git after the check is left alone.
PRUNE_GONE="${SYNC_PRUNE_GONE:-0}"
PRUNE_MAX="${SYNC_PRUNE_MAX:-25}"

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
    timeout -k 10 "${T:-$GIT_TIMEOUT}" git "$@" 9>&-  # a straggler must never keep the push lock
}
timed_out() { [[ $1 -eq 124 || $1 -eq 137 ]]; }
why() { timed_out "$1" && echo " (timed out after ${2:-$GIT_TIMEOUT}s)"; }

prune_gone() {  # prune_gone <repo> <bare>
  local r=$1 bare=$2 dst="${WG_GIT}/${WG_OWNER}/${1}.git" gone heads b sha n=0 kept=0 checks=0 last="" rc
  local cursor="$WORK/prune-cursor.${1}" cur=""
  gone="$(git_authed --git-dir="$bare" push --dry-run --porcelain --prune "$dst" \
            '+refs/heads/*:refs/heads/*' '^refs/heads/archive/*' 2>/dev/null \
          | awk -F'\t' '$1 == "-" { sub(/^:refs\/heads\//, "", $2); print $2 }' \
          | grep -v '^archive/' | LC_ALL=C sort || true)"
  [[ -n "$gone" ]] || { rm -f "$cursor"; return 0; }
  heads="$(git_authed ls-remote --heads "$dst" 2>/dev/null)" || { log "$r: prune skipped (cannot list Windy Git branches)"; return 0; }
  [[ -f "$cursor" ]] && cur="$(cat "$cursor")"
  # Branches after the cursor first, then wrap round to the start.
  # Compare as strings (the "" forces it): awk would compare "10" and "9" as numbers.
  gone="$(LC_ALL=C awk -v c="$cur" '($0 "") > (c "")' <<<"$gone"; LC_ALL=C awk -v c="$cur" '($0 "") <= (c "")' <<<"$gone")"
  while IFS= read -r b; do
    [[ -n "$b" ]] || continue
    (( checks >= PRUNE_MAX )) && break
    sha="$(awk -F'\t' -v ref="refs/heads/$b" '$2 == ref { print $1 }' <<<"$heads")"
    [[ -n "$sha" ]] || continue
    checks=$((checks + 1)); last=$b
    rc=0; python3 "$(dirname "$0")/github_has_commit.py" "$r" "$sha" || rc=$?
    if (( rc == 0 )) && git_authed --git-dir="$bare" push --quiet --force-with-lease="refs/heads/$b:$sha" \
         "$dst" ":refs/heads/$b" 2>/dev/null; then
      n=$((n + 1))
    else
      kept=$((kept + 1))
    fi
  done <<<"$gone"
  [[ -n "$last" ]] && printf '%s\n' "$last" > "$cursor"
  (( n || kept )) && log "$r: pruned $n branch(es) GitHub deleted; kept $kept (commit not confirmed on GitHub, or the branch moved)"
  return 0
}

umask 077
mkdir -p "$WORK" && chmod 0750 "$WORK"
log() { printf '[sync %s] %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }

# rerun_ci.sh rewinds a branch so the NEXT push re-fires CI; it must not do that while this
# loop is pushing. It used to wait for the whole sync to be idle, but passes now take ~5 min
# (the PR bridge), back to back, so it starved (10-21: Chat #451 and autorerun both timed
# out). It now takes this lock instead, which only the push loop holds (~1.5 min).
PUSH_LOCK="$WORK/.push.lock"
exec 9>"$PUSH_LOCK"
LOCK_WAIT="${SYNC_PUSH_LOCK_WAIT:-120}"
flock -w "$LOCK_WAIT" 9 || log "push lock busy for ${LOCK_WAIT} s (a rerun_ci.sh rewind?); pushing anyway"

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
  fetch() { T="$FETCH_TIMEOUT" git_authed --git-dir="$bare" fetch --quiet --prune origin \
              '+refs/heads/*:refs/heads/*' '+refs/tags/*:refs/tags/*' 2>/dev/null; }
  rc=0; fetch || rc=$?
  if timed_out "$rc"; then
    log "$r: fetch timed out after ${FETCH_TIMEOUT}s; retrying once"
    rc=0; fetch || rc=$?
  fi
  (( rc == 0 )) || { log "FAILED fetch $r$(why $rc "$FETCH_TIMEOUT")"; FAILED=1; continue; }

  before="$(git --git-dir="$bare" rev-parse HEAD 2>/dev/null || echo none)"

  if git_authed --git-dir="$bare" push --quiet --force \
       "${WG_GIT}/${WG_OWNER}/${r}.git" \
       '+refs/heads/*:refs/heads/*' '^refs/heads/archive/*' $([[ " $NO_TAGS " == *" $r "* ]] || echo '+refs/tags/*:refs/tags/*') 2>/dev/null; then
    log "$r ok (${before:0:7})"
    [[ "$PRUNE_GONE" == 1 ]] && prune_gone "$r" "$bare"
  else
    rc=$?; log "FAILED push $r -> windy git$(why $rc)"; FAILED=1
  fi
done
flock -u 9  # the push loop is over: rerun_ci.sh may rewind now

# Jobs that name labels no runner has (ubuntu/macos/windows-latest) would wait
# forever and invisibly; cancel them after 30 min. Never fails the sync.
# Both DB steps go through `docker exec`, which hangs outright while the host
# is in an IO stall (09-23: data2 SMR cliff wedged this sync for 10+ min and
# stopped mirroring + the bridge for every lane). They are optional; mirroring
# and the bridge are not. Bound them so a stuck exec costs one step, not the run.
timeout -k 10 120 bash "$(dirname "$0")/cancel_unrunnable.sh" || log "janitor failed or timed out (non-fatal)"

# Idle CI job networks, every run (10-21): dind has ~31 address pools, and a job cut short
# (load cap, runner restart, a spike) leaks its network. The 6-hourly prune (deploy/runner/
# prune.sh) was too slow on a busy day: 30 piled up and new jobs died in 0-1 s with "all
# predefined address pools have been fully subnetted". Only UNUSED networks older than
# 15 min go: a job attaches its network seconds after creating it, and a network in use
# is never pruned. Bounded and non-fatal, like the janitor.
# Containers of jobs that finished 30+ min ago (a leaked RUNNING service container pins
# its network, which the prune below then can't free). Never fails the sync.
if [[ "${SYNC_REAP:-1}" == 1 ]]; then
  timeout -k 5 60 bash "$(dirname "$0")/reap_task_containers.sh" || log "container reaper failed or timed out (non-fatal)"
fi
CI_NET_PRUNE="${SYNC_CI_NET_PRUNE:-1}"
if [[ "$CI_NET_PRUNE" == 1 ]]; then
  timeout -k 5 60 docker exec windy-git-runner-dind-1 docker -H tcp://127.0.0.1:2375 \
    network prune -f --filter until=15m >/dev/null 2>&1 || log "ci network prune failed or timed out (non-fatal)"
fi

# Private repos can't run GitHub Actions; mirror their open PRs here so CI
# fires, and post the verdicts back to GitHub as commit statuses.
if ! python3 "$(dirname "$0")/pr_status_bridge.py"; then
  log "FAILED pr status bridge"; FAILED=1
fi

# Cancel WAITING PR jobs whose commit a newer push replaced (Boss 10-28 08:44Z): never running,
# main, tag or schedule. Never fails the sync.
timeout -k 5 90 python3 "$(dirname "$0")/cancel_superseded.py" || log "cancel-superseded failed or timed out (non-fatal)"

# Runner guard (Boss 10-01): PUBLIC sneakyfree repos have self-hosted GitHub runners on Veron.
# A PR that changes a workflow so a stranger's code could reach one gets a red
# windy-git/runner-guard status. Each status is posted once; never fails the sync.
timeout -k 10 120 python3 "$(dirname "$0")/runner_guard.py" pr --post || log "runner-guard failed or timed out (non-fatal)"

# CI telemetry -> admin.windyword.ai (shapes declared with Windy Telemetry 40).
# Sends nothing until WINDYGIT_TELEMETRY_TOKEN is set; never fails the sync.
timeout -k 10 180 python3 "$(dirname "$0")/telemetry_emit.py" || log "telemetry emit failed or timed out (non-fatal)"

[[ "$FAILED" -ne 0 ]] && { log "COMPLETED WITH FAILURES"; exit 1; }
log "all repos in step with GitHub"
