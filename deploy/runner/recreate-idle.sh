#!/usr/bin/env bash
# Recreate the WHOLE CI stack (dind + all runners) without killing a job. Use after a change
# that needs dind itself recreated (e.g. cgroup_parent): restart-idle.sh only bounces runners.
# Run on Veron as root, from deploy/runner/.
#   1. Every POLL seconds, stop ANY runner that has no running task (a runner stopped mid-job
#      loses it). Stopped runners claim nothing, so new jobs WAIT in the queue; none die.
#      Any order, not one at a time: under a queue a runner refills within fetch_interval (2s),
#      so waiting on one named runner while the others cycle could take hours (10-27).
#   2. Once all are stopped, dind has no jobs: `compose up -d` recreates dind and the runners.
# The compose project holds ONLY dind + the runners, so --remove-orphans touches nothing else
# (Hub, #72 LOW 2: check `docker ps --filter label=com.docker.compose.project=windy-git-runner`).
# Known gap (Hub, #72 LOW 1): a runner can claim a job in the instant between its idle read and
# `docker stop`; act_runner then drains it for shutdown_timeout (3m), so only a job that both
# lands in that instant AND runs longer than 3m is lost.
#   WGQ=<path to wg-q>   (default: the invoking user's ~/bin/wg-q)
#   RECREATE_WAIT_MAX    total seconds to get every runner stopped (default 5400); on timeout the
#                        ones already stopped are started again and nothing is recreated
#   RECREATE_POLL        seconds between passes (default 2, = config.yaml fetch_interval)
#   RECREATE_DRY=1       read-only: report what each pass would stop; stop and recreate nothing
set -euo pipefail
cd "$(dirname "$0")"
WGQ="${WGQ:-$(getent passwd "${SUDO_USER:-$USER}" | cut -d: -f6)/bin/wg-q}"
[ -x "$WGQ" ] || { echo "no DB helper at $WGQ: refusing (nothing stopped)"; exit 1; }
WAIT_MAX="${RECREATE_WAIT_MAX:-5400}"
POLL="${RECREATE_POLL:-2}"
DRY="${RECREATE_DRY:-0}"
STOP_T="${RESTART_STOP_TIMEOUT:-200}"   # > config.yaml's shutdown_timeout (3m): a just-claimed task drains
stopped=()
undo() { [ ${#stopped[@]} -gt 0 ] && docker start "${stopped[@]}" >/dev/null && echo "restarted: ${stopped[*]}"; return 0; }
trap 'echo "interrupted"; undo; exit 130' INT TERM

declare -A name_of
mapfile -t pending < <(docker ps --format '{{.Names}}' | grep -E '^windy-git-runner-runner(-[0-9]+)?-1$' | sort -u)
[ ${#pending[@]} -gt 0 ] || { echo "no running runner containers: nothing to do"; exit 1; }
for c in "${pending[@]}"; do
  n=$(docker exec "$c" sh -c 'grep -o "\"name\": *\"[^\"]*\"" /data/.runner' | sed -E 's/.*"([^"]*)"$/\1/' || true)
  [[ "$n" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "$c: cannot read its runner name; nothing stopped"; exit 1; }
  name_of[$c]=$n
done
busy() { [ "$("$WGQ" <<<"select count(*) from action_task t join action_runner r on r.id=t.runner_id where r.name='$1' and t.status=6;")" != 0 ]; }

t0=$(date +%s)
while [ ${#pending[@]} -gt 0 ]; do
  if (( $(date +%s) - t0 > WAIT_MAX )); then
    echo "still busy after ${WAIT_MAX}s: ${pending[*]}; recreating nothing"; undo; exit 1
  fi
  left=()
  for c in "${pending[@]}"; do
    if busy "${name_of[$c]}"; then left+=("$c"); continue; fi
    if [ "$DRY" = 1 ]; then echo "$c (${name_of[$c]}): idle -> WOULD stop (dry run)"; continue; fi
    docker stop -t "$STOP_T" "$c" >/dev/null && stopped+=("$c") && echo "$c (${name_of[$c]}): idle, stopped $(date -u +%TZ)"
  done
  [ "$DRY" = 1 ] && { echo "dry run: ${#left[@]} busy now (${left[*]:-none}); nothing stopped"; exit 0; }
  pending=("${left[@]}")
  [ ${#pending[@]} -gt 0 ] && sleep "$POLL"
done
trap - INT TERM
docker compose up -d --remove-orphans 2>&1 | tail -n 20
echo "recreated $(date -u +%TZ)"
docker ps --format '{{.Names}}' | grep -E '^windy-git-runner-' | while read -r c; do
  echo "  $c -> $(cut -d: -f3 /proc/"$(docker inspect -f '{{.State.Pid}}' "$c")"/cgroup | cut -d/ -f2)"
done
