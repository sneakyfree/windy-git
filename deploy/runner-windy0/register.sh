#!/usr/bin/env bash
# register-w0.sh <1|2|3|4> <repo> : register ONE repo-scoped runner on Windy 0 (name w0-N). Run ON VERON as the lane user (needs sudo).
# Refuses a repo with any Actions secret (repo, owner, instance). Token: Gitea -> ssh stdin -> env of the register command only.
set -euo pipefail
n=$1; repo=$2
[[ "$n" =~ ^[1-4]$ ]] || { echo "runner must be 1-4"; exit 2; }
[[ "$repo" =~ ^[A-Za-z0-9._-]{1,100}$ ]] || { echo "bad repo name"; exit 2; }
WGQ="${WGQ:-$HOME/bin/wg-q}"; W0="${WINDY0_SSH:-eth-windy0}"
secrets=$(printf "select count(*) from secret s, repository p where p.owner_id=(select id from \"user\" where lower_name='windyadmin') and p.lower_name=lower('%s') and (s.repo_id=p.id or (s.repo_id=0 and s.owner_id=p.owner_id) or (s.owner_id=0 and s.repo_id=0));\n" "$repo" | "$WGQ")
exists=$(printf "select count(*) from repository where owner_id=(select id from \"user\" where lower_name='windyadmin') and lower_name=lower('%s');\n" "$repo" | "$WGQ")
[ "$exists" = 1 ] || { echo "REFUSED: windyadmin/$repo not found"; exit 1; }
[ "$secrets" = 0 ] || { echo "REFUSED: windyadmin/$repo sees $secrets Actions secret(s): it must stay on Veron"; exit 1; }
tok=$(sudo docker exec -u git windy-git-gitea-1 gitea actions generate-runner-token --scope "windyadmin/$repo" 2>/dev/null | tail -n 1)
[[ "$tok" =~ ^[A-Za-z0-9]{30,80}$ ]] || { echo "REFUSED: no plain token from Gitea"; exit 1; }
# act_runner's interactive mode reads instance, token, name, labels from STDIN: the token never reaches an argv.
printf '%s\n' "$tok" | ssh -o BatchMode=yes "$W0" "cd /tmp && sudo -n -u windygit-ci env HOME=/var/lib/windygit-ci bash -c 'read -r T && [ -n \"\$T\" ] && cd /var/lib/windygit-ci/runner-$n && printf \"%s\\n%s\\n%s\\n\\n\" https://app.windygit.com \"\$T\" w0-$n | /usr/local/bin/act_runner register --config /var/lib/windygit-ci/runner-$n/config.yaml 2>&1 | sed -E \"s/[A-Za-z0-9]{30,}/***/g\" | tail -n 4; test -s /var/lib/windygit-ci/runner-$n/.runner'"
echo "registered w0-$n for $repo; next: enable the unit, read back scope + labels"
