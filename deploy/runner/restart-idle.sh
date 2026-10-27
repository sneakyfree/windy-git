#!/usr/bin/env bash
# Restart Windy Git's CI runner containers ONE AT A TIME, each only when it has no running
# task (a `docker restart` kills the job it is running: "runner lost", 10-21 CI cap lesson).
# Use after a runner config.yaml change (labels, container options). A job-image RETAG needs no
# restart: the daemon resolves the tag per job. Only RUNNING runners are touched (stopped ones,
# e.g. behind the extra-runners profile, stay stopped). Run on Veron as root.
#   WGQ=<path to wg-q>   (default: the invoking user's ~/bin/wg-q)
set -euo pipefail
WGQ="${WGQ:-$(getent passwd "${SUDO_USER:-$USER}" | cut -d: -f6)/bin/wg-q}"
[ -x "$WGQ" ] || { echo "no DB helper at $WGQ: refusing (nothing restarted)"; exit 1; }
WAIT_MAX="${RESTART_WAIT_MAX:-3600}"   # per runner; give up (leave it running) after this
# Longer than config.yaml's shutdown_timeout (3m): a task claimed between the idle check and
# the restart is drained, not killed (Hub, #62 S1).
STOP_T="${RESTART_STOP_TIMEOUT:-200}"
for c in $(docker ps --format '{{.Names}}' | grep -E '^windy-git-runner-runner(-[0-9]+)?-1$|^windy-git-runner-runner-1$' | sort -u); do
  name=$(docker exec "$c" sh -c 'grep -o "\"name\": *\"[^\"]*\"" /data/.runner' | sed -E 's/.*"([^"]*)"$/\1/' || true)
  [[ "$name" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "$c: cannot read its runner name; skipped"; continue; }
  t0=$(date +%s)
  until [ "$("$WGQ" <<<"select count(*) from action_task t join action_runner r on r.id=t.runner_id where r.name='$name' and t.status=6;")" = 0 ]; do
    (( $(date +%s) - t0 > WAIT_MAX )) && { echo "$c ($name): still busy after ${WAIT_MAX}s; NOT restarted"; continue 2; }
    sleep 15
  done
  docker restart -t "$STOP_T" "$c" >/dev/null && echo "$c ($name): idle, restarted $(date -u +%TZ)"
done
