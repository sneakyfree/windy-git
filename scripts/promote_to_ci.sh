#!/usr/bin/env bash
# promote_to_ci.sh <repo> [workflow-to-disable ...] — pull mirror -> writable CI repo.
# Run ON Veron as root. See docs/CUTOVER.md "Onboarding another private repo".
#
# ⚠️ It DELETES the mirror before importing (Gitea's migrate refuses an existing
# name). If the import then fails, the Windy Git copy is gone until you re-run —
# GitHub and the nightly R2 bundles still hold everything, but check first that
# scripts/import_from_github.py will accept the repo. (2026-09-23: windy-pro was
# deleted this way while the importer still refused it by name.)
set -euo pipefail
set -a; . /srv/windygit/src/.env; set +a
export IMPORT_GITEA_URL=http://localhost:3080
A=http://localhost:3080/api/v1; H="Authorization: token $GITEA_ADMIN_TOKEN"; r=$1; shift
info=$(curl -s -H "$H" $A/repos/windyadmin/$r)
m=$(echo "$info" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("mirror"))')
if [ "$m" = True ]; then
  curl -sf -o /dev/null -X DELETE -H "$H" $A/repos/windyadmin/$r
  (cd /srv/windygit/src && python3 scripts/import_from_github.py "$r" | tail -1)
elif [ "$m" = False ]; then echo "$r already writable"; else echo "$r absent -> importing"; (cd /srv/windygit/src && python3 scripts/import_from_github.py "$r" | tail -1); fi
db=$(curl -s -H "$H" $A/repos/windyadmin/$r | python3 -c 'import json,sys;print(json.load(sys.stdin).get("default_branch","main"))')
for i in $(seq 1 120); do curl -sf -o /dev/null -H "$H" $A/repos/windyadmin/$r/branches/$db && break; sleep 5; done
for w in "$@"; do printf "  disable %s: " "$w"; curl -s -o /dev/null -w '%{http_code}\n' -X PUT -H "$H" $A/repos/windyadmin/$r/actions/workflows/$w/disable; done
curl -s -H "$H" $A/repos/windyadmin/$r/actions/workflows | python3 -c 'import json,sys,os;print("  "+os.environ.get("R",""),[(w["path"].split("/")[-1],w["state"]) for w in json.load(sys.stdin).get("workflows",[])])'
echo "  default=$db"
