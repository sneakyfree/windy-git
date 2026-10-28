#!/usr/bin/env python3
"""The login canary must never go quiet unseen (Boss 10-28 (D)).

07:10-08:42Z on 10-28, 8 canary schedules in a row were cancelled unpicked behind the CI queue,
and nothing said so. This reads the Gitea DB: when did a canary job last actually RUN (success or
failure, not cancelled), and how many schedules in a row since then never ran?
  canary: ok (last ran N min ago)
  canary: WARN silent N min, K schedules in a row missed (WARN to Boss and Admin)
WARN after SILENT_MIN (20: two 10-min schedules). windy-job --expect "^canary: ok" turns it into
a windy-uptime alert. HQ's monitor_silent (Admin) is the independent second check.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

SILENT_MIN = int(os.environ.get("CANARY_SILENT_MIN", "20"))
# Gitea stores a scheduled run as event "push" with trigger_event "schedule" (checked 10-28).
SQL = """
select coalesce(max(j.stopped) filter (where j.status in (1, 2)), 0),
       count(*) filter (where j.status in (3, 4) and j.created > coalesce(
           (select max(j2.stopped) from action_run_job j2 join action_run r2 on r2.id = j2.run_id
            where r2.repo_id = r.repo_id and r2.workflow_id = 'canary.yml' and j2.status in (1, 2)), 0))
from action_run_job j join action_run r on r.id = j.run_id join repository p on p.id = r.repo_id
where p.lower_name = 'windy-git' and r.workflow_id = 'canary.yml' and r.trigger_event = 'schedule'
group by r.repo_id;
"""


def psql(sql: str) -> list[list[str]]:
    out = subprocess.run(
        ["docker", "exec", "-i", "windy-git-db-1", "sh", "-c",
         'psql -U "$POSTGRES_USER" -d gitea -At -F "|" -v ON_ERROR_STOP=1'],
        input=sql, capture_output=True, text=True, check=True, timeout=30,
    ).stdout.strip()
    return [line.split("|") for line in out.splitlines() if line]


def verdict(last_run: int, missed: int, now: float) -> str:
    if not last_run:
        return "canary: WARN it has never run (WARN to Boss and Admin)"
    mins = (now - last_run) / 60
    if mins > SILENT_MIN:
        return (f"canary: WARN silent {mins:.0f} min, {missed} schedules in a row missed "
                "(WARN to Boss and Admin)")
    return f"canary: ok (last ran {mins:.0f} min ago)"


def main(query=psql) -> int:
    try:
        rows = query(SQL)
    except Exception as e:  # noqa: BLE001 - an unreadable DB is itself a WARN, never a silent ok
        print(f"canary: WARN cannot read the CI database ({type(e).__name__}) (WARN to Boss and Admin)")
        return 0
    last, missed = (int(rows[0][0] or 0), int(rows[0][1] or 0)) if rows else (0, 0)
    print(verdict(last, missed, time.time()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
