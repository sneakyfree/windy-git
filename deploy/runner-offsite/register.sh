#!/usr/bin/env bash
# Register ONE offsite runner on Null 0, scoped to ONE secret-free repo. Run ON VERON as root:
#   sudo bash deploy/runner-offsite/register.sh <runner 1|2> <repo>      e.g. 1 eternitas
# Refuses unless the repo holds 0 Actions secrets (repo, owner and instance level): Gitea hands a
# repo's secrets to every job of that repo, and only secret-free repos may run off Veron. The
# repo-scoped registration token goes from Gitea straight into Null 0's 0600 .env over ssh stdin:
# never in argv, never printed, never on Veron's disk. It is single-use; the runner's own credential
# then lives in its runner-data volume, and the token line is blanked by the next step. On Null 0 the
# directory and .env belong to the windygit-ci system user (no login shell, no docker group); docker
# compose runs via sudo. Nothing is mounted from any home directory (Boss 11-02: Null 0 holds a Claude login).
set -euo pipefail
n=$1; repo=$2
[[ "$n" =~ ^[12]$ ]] || { echo "runner must be 1 or 2"; exit 2; }
[[ "$repo" =~ ^[A-Za-z0-9._-]{1,100}$ ]] || { echo "bad repo name"; exit 2; }
NULL0="${NULL0_SSH:-eth-null0}"; DIR="${OFFSITE_DIR:-/opt/windygit-runner-offsite}"
WGQ="${WGQ:-/home/user1-gpu/bin/wg-q}"
secrets=$(printf "select count(*) from secret s, repository p where p.owner_id = (select id from \"user\" where lower_name = 'windyadmin') and p.lower_name = lower('%s') and (s.repo_id = p.id or (s.owner_id = p.owner_id and s.repo_id = 0) or (s.owner_id = 0 and s.repo_id = 0));\n" "$repo" | "$WGQ")
exists=$(printf "select count(*) from repository where owner_id = (select id from \"user\" where lower_name = 'windyadmin') and lower_name = lower('%s');\n" "$repo" | "$WGQ")
[ "$exists" = 1 ] || { echo "REFUSED: repo windyadmin/$repo not found"; exit 1; }
[ "$secrets" = 0 ] || { echo "REFUSED: windyadmin/$repo holds $secrets Actions secret(s) (repo/owner/instance): it must stay on Veron"; exit 1; }
# Gitea 1.24.7 prints a log line on STDOUT before the token (the DEFAULT_ACTIONS_URL warning), so
# only the LAST line is the token; store-token.sh still refuses anything that isn't one plain token.
docker exec -u git windy-git-gitea-1 gitea actions generate-runner-token --scope "windyadmin/$repo" 2>/dev/null \
  | tail -n 1 \
  | runuser -u user1-gpu -- ssh -o BatchMode=yes "$NULL0" "sudo -n $DIR/store-token.sh $n"
echo "next on Null 0: sudo docker compose -p windy-git-runner-offsite up -d runner-$n; then blank RUNNER_${n}_TOKEN in .env; then read back scope + labels in Gitea (action_runner.repo_id, agent_labels)"
