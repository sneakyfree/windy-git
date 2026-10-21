#!/usr/bin/env bash
# Remove CI containers whose job finished a while ago. Run on Veron as root (the sync).
#
# act_runner names every container of a job GITEA-ACTIONS-TASK-<task id>-...: the job
# container and its service containers (postgres:16, redis, ...). When a job dies the
# wrong way, a service container can keep RUNNING with its network attached, so neither
# `container prune` (stopped only) nor `network prune` can free it; enough of them and
# dind runs out of address pools and every new job fails at start (10-21 12:2xZ: a
# windy-mind postgres:16 of task 34259 and a windy-git one of task 38428, by hand).
#
# Only names that parse to a task id, only tasks Gitea says FINISHED (ok, fail, cancel,
# skip) more than REAP_AFTER_MIN minutes ago; a task the DB doesn't know is left alone.
set -euo pipefail
AGE_MIN="${REAP_AFTER_MIN:-30}"
DRY="${REAP_DRY_RUN:-0}"  # 1: name what would go, remove nothing
[[ "$AGE_MIN" =~ ^[0-9]+$ ]] || { echo "[reaper] REAP_AFTER_MIN must be a whole number"; exit 2; }
D=(docker exec windy-git-runner-dind-1 docker -H tcp://127.0.0.1:2375)  # dind listens on TCP only

# "<container id> <task id>" per CI container; the sed only passes digits as the task id.
pairs="$("${D[@]}" ps -a --format '{{.ID}} {{.Names}}' \
         | sed -nE 's/^([0-9a-f]+) GITEA-ACTIONS-TASK-([0-9]+)[-_].*/\1 \2/p')"
[[ -n "$pairs" ]] || { echo "[reaper] removed 0 container(s) of finished jobs"; exit 0; }
ids="$(awk '{print $2}' <<<"$pairs" | sort -un | paste -sd, -)"
finished="$(docker exec -i windy-git-db-1 sh -c 'psql -U "$POSTGRES_USER" -d gitea -At -v ON_ERROR_STOP=1' <<SQL
select id from action_task
 where id in (${ids}) and status in (1, 2, 3, 4) and stopped > 0
   and stopped < extract(epoch from now())::bigint - ${AGE_MIN} * 60;
SQL
)"
n=0 failed=0
while read -r cid tid; do
  grep -qxF "$tid" <<<"$finished" || continue
  if [[ "$DRY" == 1 ]]; then
    n=$((n + 1)); echo "[reaper] would remove container ${cid:0:12} of finished task ${tid}"
  elif "${D[@]}" rm -f "$cid" </dev/null >/dev/null 2>&1; then
    n=$((n + 1)); echo "[reaper] removed container ${cid:0:12} of finished task ${tid}"
  else
    failed=$((failed + 1))  # e.g. "Removal In Progress" held by the kernel: retried next pass
  fi
done <<<"$pairs"
msg="[reaper] removed ${n} container(s) of finished jobs"
[[ "$DRY" == 1 ]] && msg="[reaper] DRY RUN: would remove ${n} container(s) of finished jobs"
(( failed == 0 )) || msg+=", ${failed} could not be removed"
echo "$msg"
