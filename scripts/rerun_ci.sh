#!/usr/bin/env bash
# Re-run a PR's (or branch's) CI on Windy Git. Runs ON Veron 1.
#
#   bash scripts/rerun_ci.sh <repo> <branch> <sha-prefix>
#
# Gitea 1.24 has NO rerun API; the web button needs a hub-SSO session as
# windyadmin, which is Grant's identity, so we don't use it. Instead: move the
# Windy Git branch back one commit, let the next sync force-push the GitHub head
# again, and Gitea fires an ordinary push / pull_request_sync event on the SAME
# commit. Every workflow on that event re-runs, not only the failed one.
#
# Safety: refuses unless the branch is exactly at <sha-prefix> (GitHub's head),
# never rewinds while a sync is running (a run already past this repo would
# not push it back), waits for a sync that STARTS after the rewind, and if the
# branch is not verifiably back at <sha-prefix> by the deadline, restores it
# itself, so Windy Git is never left behind GitHub.
set -euo pipefail
repo="${1:?repo}"; branch="${2:?branch}"; want="${3:?sha prefix}"
G="sudo docker exec -u git windy-git-gitea-1 git -C /data/git/repositories/windyadmin/${repo}.git"

head=$($G rev-parse "refs/heads/${branch}")
[[ "$head" == "$want"* ]] || { echo "refusing: ${branch} is at ${head:0:7}, not ${want}"; exit 1; }
parent=$($G rev-parse "${head}^")

# NOT `systemctl is-active`: the sync is Type=oneshot, which reads "activating"
# (exit 3) for its whole run, so is-active says "idle" mid-run.
busy() { case "$(systemctl show windygit-sync -p ActiveState --value)" in
  activating|active|deactivating|reloading) return 0;; esac; return 1; }
while busy; do sleep 5; done
$G update-ref "refs/heads/${branch}" "$parent" "$head"
mark=$(awk '{print int($1*1000000)}' /proc/uptime)
echo "rewound ${repo}:${branch} ${head:0:7} -> ${parent:0:7}"

deadline=$(( $(date +%s) + 900 ))
until [ "$(systemctl show windygit-sync -p ExecMainStartTimestampMonotonic --value)" -gt "$mark" ] \
      && [ "$($G rev-parse "refs/heads/${branch}")" = "$head" ]; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    $G update-ref "refs/heads/${branch}" "$head" "$($G rev-parse "refs/heads/${branch}")" || true
    echo "TIMEOUT: restored ${branch} to ${head:0:7} by hand; NO new run fired"; exit 1
  fi
  sleep 10
done
echo "restored by sync: ${branch} = ${head:0:7}"
sleep 5
~/bin/wg-q <<SQL
select ar.index, ar.workflow_id, ar.event, ar.status, to_char(to_timestamp(ar.created),'HH24:MI:SS')
  from action_run ar join repository r on r.id = ar.repo_id
 where r.name = '${repo}' and ar.commit_sha = '${head}' order by ar.id desc limit 6;
SQL
