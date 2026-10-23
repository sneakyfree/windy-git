#!/usr/bin/env bash
# Phase 1 of the site batch (Hub approved 10-23; Boss GO in principle after #64's AFTER, then a
# Boss GO naming the batch PR's head). Run on Veron as root AFTER the batch PR is merged, BEFORE
# its deploy (promote first, then deploy: deploying first makes every sync pass fail on pull
# mirrors). Per repo: promote (pull mirror -> writable CI copy, GitHub untouched), disable the
# GitHub-only workflows on Windy Git, add windy-ci-reader, prove 0 Actions secrets.
#   bash site_batch_promote.sh [--dry]      (--dry prints the plan, changes nothing)
set -euo pipefail
DRY=${1:-}
# repo : workflows to disable on Windy Git (they're ubuntu-latest only, or deploys)
PLAN=(
  "eternitas-site:canonical-domains-lint.yml deploy.yml"
  "windy-call-site:"
  "windy-chat-site:canonical-domains-lint.yml deploy.yml"
  "windy-code-site:canonical-domains-lint.yml deploy.yml"
  "windy-connect-site:"
  "windy-drops-site:deploy.yml"
  "windy-fly-site:canonical-domains-lint.yml deploy.yml"
  "windy-git-site:"
  "windy-mail-site:canonical-domains-lint.yml deploy.yml"
  "windy-mobile-site:"
  "windy-search-site:"
  "windy-vault-site:"
  "windycloud-site:deploy.yml"
  "windytalk-site:"
  "windyword-site:deploy.yml"
)
A=http://localhost:3080/api/v1
umask 077; W=$(mktemp -d /dev/shm/sitebatch.XXXX); trap 'shred -u "$W/h" 2>/dev/null; rm -rf "$W"' EXIT INT TERM
ENVF="${SITE_BATCH_ENV:-/srv/windygit/src/.env}"   # override only to test the refusal
sed -n 's/^GITEA_ADMIN_TOKEN=/Authorization: token /p' "$ENVF" > "$W/h"
# Fail closed everywhere: this script's output IS the proof (Hub, #67).
[ -s "$W/h" ] || { echo "no GITEA_ADMIN_TOKEN in $ENVF: refusing" >&2; exit 1; }
api() { curl -s -H @"$W/h" "$@"; }
mirror_of() {  # prints True/False, or exits on anything else (API error, 404, auth failure)
  local m
  m=$(api "$A/repos/windyadmin/$1" | python3 -c 'import json,sys
try: v=json.load(sys.stdin).get("mirror")
except Exception: v=None
print(v)')
  [[ "$m" == True || "$m" == False ]] || { echo "$1: mirror state unreadable ($m): STOP" >&2; exit 1; }
  echo "$m"
}
if [ -n "${SITE_BATCH_ONLY:-}" ]; then   # e.g. SITE_BATCH_ONLY=windy-git-site to run one repo
  PLAN=($(printf '%s\n' "${PLAN[@]}" | grep -E "^(${SITE_BATCH_ONLY//,/|}):" || true))
  [ ${#PLAN[@]} -gt 0 ] || PLAN=("${SITE_BATCH_ONLY%%,*}:")   # unknown name: let mirror_of refuse it
fi
ok=0
for row in "${PLAN[@]}"; do
  r=${row%%:*}; wfs=${row#*:}
  mirror=$(mirror_of "$r")
  if [ "$DRY" = --dry ]; then echo "$r: mirror=$mirror; would disable: ${wfs:-none}"; continue; fi
  if [ "$mirror" = True ]; then
    (cd /srv/windygit/src && R=$r bash scripts/promote_to_ci.sh "$r" | tail -2)
    [ "$(mirror_of "$r")" = False ] || { echo "$r: still a mirror after promote: STOP" >&2; exit 1; }
  else
    echo "$r: already writable"
  fi
  for w in $wfs; do
    code=$(api -o /dev/null -w '%{http_code}' -X PUT "$A/repos/windyadmin/$r/actions/workflows/$w/disable")
    [ "$code" = 204 ] || { echo "$r: disable $w returned HTTP $code: STOP" >&2; exit 1; }
  done
  c=$(api -o /dev/null -w '%{http_code}' -X PUT -H 'Content-Type: application/json' -d '{"permission":"read"}' "$A/repos/windyadmin/$r/collaborators/windy-ci-reader")
  [[ "$c" == 204 || "$c" == 201 ]] || { echo "$r: windy-ci-reader grant returned HTTP $c: STOP" >&2; exit 1; }
  n=$(api "$A/repos/windyadmin/$r/actions/secrets" | python3 -c 'import json,sys
try: d=json.load(sys.stdin)
except Exception: d=None
print(len(d) if isinstance(d,list) else "?")')
  [ "$n" = 0 ] || { echo "$r: actions secrets = $n (must be exactly 0): STOP" >&2; exit 1; }
  echo "$r: disabled=[${wfs:-none}] ci-reader=$c actions_secrets=0"
  ok=$((ok+1))
done
[ "$DRY" = --dry ] || echo "DONE: $ok/${#PLAN[@]} promoted, workflows disabled, ci-reader granted, secrets=0"
