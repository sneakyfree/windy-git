#!/usr/bin/env bash
# register.sh <1-6> <repo> : register ONE repo-scoped runner on Windy 0 (name w0-N). Run ON VERON as the lane user (needs sudo).
# Refuses a repo with any Actions secret (repo, owner, instance). Token: Gitea -> ssh stdin -> env of the register command only.
# MISSES 2026-11-12T08:54:34Z: an OLD .runner in the folder made act_runner ask "overwrite? [y/N]", it read the script's
# first input line as "no", and `test -s .runner` then passed on the OLD file. So: (1) an existing .runner is MOVED
# ASIDE (kept, .runner.bak-<UTC>) before register; (2) the proof is the FORGE ROW (a new action_runner row named w0-N,
# scoped to this repo, created since this run started), never the script's own "registered".
set -euo pipefail
n=$1; repo=$2
[[ "$n" =~ ^[1-6]$ ]] || { echo "runner must be 1-6"; exit 2; }
[[ "$repo" =~ ^[A-Za-z0-9._-]{1,100}$ ]] || { echo "bad repo name"; exit 2; }
WGQ="${WGQ:-$HOME/bin/wg-q}"; W0="${WINDY0_SSH:-eth-windy0}"
secrets=$(printf "select count(*) from secret s, repository p where p.owner_id=(select id from \"user\" where lower_name='windyadmin') and p.lower_name=lower('%s') and (s.repo_id=p.id or (s.repo_id=0 and s.owner_id=p.owner_id) or (s.owner_id=0 and s.repo_id=0));\n" "$repo" | "$WGQ")
exists=$(printf "select count(*) from repository where owner_id=(select id from \"user\" where lower_name='windyadmin') and lower_name=lower('%s');\n" "$repo" | "$WGQ")
[ "$exists" = 1 ] || { echo "REFUSED: windyadmin/$repo not found"; exit 1; }
[ "$secrets" = 0 ] || { echo "REFUSED: windyadmin/$repo sees $secrets Actions secret(s): it must stay on Veron"; exit 1; }
tok=$(sudo docker exec -u git windy-git-gitea-1 gitea actions generate-runner-token --scope "windyadmin/$repo" 2>/dev/null | tail -n 1)
[[ "$tok" =~ ^[A-Za-z0-9]{30,80}$ ]] || { echo "REFUSED: no plain token from Gitea"; exit 1; }
# act_runner's interactive mode reads instance, token, name, labels from STDIN: the token never reaches an argv.
t0=$(( $(date +%s) - 5 ))
printf '%s\n' "$tok" | ssh -o BatchMode=yes "$W0" "cd /tmp && sudo -n -u windygit-ci env HOME=/var/lib/windygit-ci bash -c 'read -r T && [ -n \"\$T\" ] && cd /var/lib/windygit-ci/runner-$n && { [ ! -e .runner ] || mv .runner .runner.bak-\$(date -u +%Y%m%dT%H%M%SZ); } && printf \"%s\\n%s\\n%s\\n\\n\" https://app.windygit.com \"\$T\" w0-$n | /usr/local/bin/act_runner register --config /var/lib/windygit-ci/runner-$n/config.yaml 2>&1 | sed -E \"s/[A-Za-z0-9]{30,}/***/g\" | tail -n 4; test -s /var/lib/windygit-ci/runner-$n/.runner'"
# PROOF: the forge row, not the script. A new row named w0-N, scoped to this repo, created since t0, not deleted.
row=$(printf "select r.id || ' ' || p.lower_name from action_runner r join repository p on p.id = r.repo_id where r.name = 'w0-%s' and p.owner_id = (select id from \"user\" where lower_name='windyadmin') and p.lower_name = lower('%s') and r.created >= %s and coalesce(r.deleted, 0) = 0 order by r.id desc limit 1;\n" "$n" "$repo" "$t0" | "$WGQ") || row=""
[[ "$row" =~ ^[0-9]+\ [a-z0-9._-]+$ ]] || { echo "NOT REGISTERED: no new forge row for w0-$n scoped to $repo since $(date -u -d "@$t0" +%H:%M:%SZ) (the old .runner, if any, is kept as .runner.bak-*)"; exit 1; }
echo "registered w0-$n for $repo: forge row id ${row%% *} (repo scope ${row#* }); next: enable the unit, then read it ONLINE in the forge (last_online within 60 s)"
