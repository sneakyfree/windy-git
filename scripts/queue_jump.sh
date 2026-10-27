#!/usr/bin/env bash
# Move ONE waiting CI job to the front of Windy Git's queue. Runs ON Veron 1.
#
#   bash scripts/queue_jump.sh <action_run_job id>
#
# Boss rule (10-27): only a PR with a GO'd same-day prod deploy jumps the queue; ask Boss for
# any other. Post a BOARD line before and after (this script prints the facts for them).
#
# Gitea 1.24 has no priority knob: a runner gets the waiting job with the lowest `updated`,
# then `id`. This sets that one job's `updated` to one second below the oldest waiting job,
# then watches. If ANY other job is picked first, it puts the old value back (exit 1).
# Refuses unless the job is waiting (status 5) and unclaimed (task_id 0).
#   WGQ=<path to wg-q>        (default: the invoking user's ~/bin/wg-q)
#   QUEUE_JUMP_WAIT=<seconds> how long to wait for the pick (default 1800)
#   QUEUE_JUMP_POLL=<seconds> poll interval (default 3)
set -euo pipefail
job="${1:?action_run_job id}"
[[ "$job" =~ ^[0-9]+$ ]] || { echo "refusing: job id must be a number"; exit 2; }
WGQ="${WGQ:-$(getent passwd "${SUDO_USER:-$USER}" | cut -d: -f6)/bin/wg-q}"
[ -x "$WGQ" ] || { echo "no DB helper at $WGQ: refusing (nothing changed)"; exit 2; }
WAIT="${QUEUE_JUMP_WAIT:-1800}"
POLL="${QUEUE_JUMP_POLL:-3}"
q() { "$WGQ" <<<"$1"; }

row=$(q "select status, task_id, updated from action_run_job where id=$job;")
IFS='|' read -r status task old <<<"$row"
[ "$status" = 5 ] && [ "$task" = 0 ] || { echo "refusing: job $job is not waiting+unclaimed (status=${status:-?} task=${task:-?})"; exit 2; }
min=$(q "select min(updated) from action_run_job where status=5 and task_id=0;")
new=$((min - 1))
last_task=$(q "select coalesce(max(id),0) from action_task;")
q "update action_run_job set updated=$new where id=$job and status=5 and task_id=0;" >/dev/null
echo "job $job: updated $old -> $new (oldest waiting was $min); watching for the next pick"

end=$(( $(date +%s) + WAIT ))
while [ "$(date +%s)" -lt "$end" ]; do
  first=$(q "select job_id from action_task where id > $last_task order by id limit 1;")
  if [ -n "$first" ]; then
    if [ "$first" = "$job" ]; then
      echo "OK: job $job was the next job picked ($(date -u +%TZ))"; exit 0
    fi
    q "update action_run_job set updated=$old where id=$job and status=5;" >/dev/null
    echo "REVERTED: job $first was picked first; job $job back to updated=$old"; exit 1
  fi
  sleep "$POLL"
done
q "update action_run_job set updated=$old where id=$job and status=5;" >/dev/null
echo "REVERTED: nothing was picked within ${WAIT}s; job $job back to updated=$old"; exit 1
