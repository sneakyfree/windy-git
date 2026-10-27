#!/usr/bin/env bash
# Recreate the WHOLE CI stack (dind + all runners) without killing a job. Use after a change
# that needs dind itself recreated (e.g. cgroup_parent): restart-idle.sh only bounces runners.
# Run on Veron as root, from deploy/runner/.
#   1. Stop each runner only when it has no running task (a runner stopped mid-job loses it).
#      Stopped runners claim nothing, so new jobs WAIT in the queue; none die.
#   2. Once all are stopped, dind has no jobs: `compose up -d` recreates dind and the runners.
#   WGQ=<path to wg-q>   (default: the invoking user's ~/bin/wg-q)
set -euo pipefail
cd "$(dirname "$0")"
WGQ="${WGQ:-$(getent passwd "${SUDO_USER:-$USER}" | cut -d: -f6)/bin/wg-q}"
[ -x "$WGQ" ] || { echo "no DB helper at $WGQ: refusing (nothing stopped)"; exit 1; }
WAIT_MAX="${RECREATE_WAIT_MAX:-3600}"   # per runner; on timeout, restart the ones already stopped and quit
STOP_T="${RESTART_STOP_TIMEOUT:-200}"   # > config.yaml's shutdown_timeout (3m): a just-claimed task drains
stopped=()
undo() { [ ${#stopped[@]} -gt 0 ] && docker start "${stopped[@]}" >/dev/null && echo "restarted: ${stopped[*]}"; }
for c in $(docker ps --format '{{.Names}}' | grep -E '^windy-git-runner-runner(-[0-9]+)?-1$' | sort -u); do
  name=$(docker exec "$c" sh -c 'grep -o "\"name\": *\"[^\"]*\"" /data/.runner' | sed -E 's/.*"([^"]*)"$/\1/' || true)
  [[ "$name" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "$c: cannot read its runner name; aborting"; undo; exit 1; }
  t0=$(date +%s)
  until [ "$("$WGQ" <<<"select count(*) from action_task t join action_runner r on r.id=t.runner_id where r.name='$name' and t.status=6;")" = 0 ]; do
    (( $(date +%s) - t0 > WAIT_MAX )) && { echo "$c ($name): still busy after ${WAIT_MAX}s; aborting"; undo; exit 1; }
    sleep 15
  done
  docker stop -t "$STOP_T" "$c" >/dev/null && stopped+=("$c") && echo "$c ($name): idle, stopped $(date -u +%TZ)"
done
docker compose up -d --remove-orphans 2>&1 | tail -n 20
echo "recreated $(date -u +%TZ)"
docker ps --format '{{.Names}}' | grep -E '^windy-git-runner-' | while read -r c; do
  echo "  $c -> $(cut -d: -f3 /proc/"$(docker inspect -f '{{.State.Pid}}' "$c")"/cgroup | cut -d/ -f2)"
done
