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
sed -n 's/^GITEA_ADMIN_TOKEN=/Authorization: token /p' /srv/windygit/src/.env > "$W/h"
api() { curl -s -H @"$W/h" "$@"; }
for row in "${PLAN[@]}"; do
  r=${row%%:*}; wfs=${row#*:}
  mirror=$(api "$A/repos/windyadmin/$r" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("mirror"))')
  if [ "$DRY" = --dry ]; then echo "$r: mirror=$mirror; would disable: ${wfs:-none}"; continue; fi
  if [ "$mirror" = True ]; then
    (cd /srv/windygit/src && R=$r bash scripts/promote_to_ci.sh "$r" $wfs | tail -2)
  else
    echo "$r: already writable (mirror=$mirror), only disabling: ${wfs:-none}"
    for w in $wfs; do api -o /dev/null -X PUT "$A/repos/windyadmin/$r/actions/workflows/$w/disable"; done
  fi
  c=$(api -o /dev/null -w '%{http_code}' -X PUT -H 'Content-Type: application/json' -d '{"permission":"read"}' "$A/repos/windyadmin/$r/collaborators/windy-ci-reader")
  n=$(api "$A/repos/windyadmin/$r/actions/secrets" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(len(d) if isinstance(d,list) else "?")')
  echo "$r: ci-reader=$c actions_secrets=$n"
done
