#!/usr/bin/env python3
"""Queue order: fully-approved PRs first (Boss 10-28 09:18Z).

Stamped windy-pro PRs waited up to 2 h behind PRs nobody had reviewed. Now, after each sync
pass: jobs of a PR whose head already carries all its required approvals go to the front,
oldest first; everything else stays FIFO behind them; main pushes and schedules are never
moved. "At most one at a time per runner slot": each pass keeps up to SLOTS approved jobs at the
front, so approvals jump the line without starving everything else.
Cheap on the GitHub quota (shared with stamps): it looks only at heads that have WAITING PR jobs,
a head once seen fully approved is cached (approvals don't un-post), and it skips when fewer
than MIN_BUDGET calls are left. Logged; one BOARD line per pass when it moves anything.
Required approvals per repo: APPROVALS below (windy-git needs only Hub's: it is Boss-exempt).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cancel_superseded as cs  # noqa: E402  (same DB helper and BOARD line)
import pr_status_bridge as b  # noqa: E402  (same GitHub helper and token)

SLOTS = int(os.environ.get("APPROVED_FIRST_SLOTS", "2"))
MIN_BUDGET = int(os.environ.get("APPROVED_FIRST_MIN_BUDGET", "1500"))
STATE = Path(os.environ.get("APPROVED_FIRST_STATE", "/var/lib/windygit/approved-heads.json"))
LOG = Path(os.environ.get("APPROVED_FIRST_LOG", "/var/log/windygit/approved-first.log"))
DEFAULT_APPROVALS = ("windy-hub/approved", "windy-boss/approved")
APPROVALS = {"windy-git": ("windy-hub/approved",)}

WAITING_HEADS_SQL = """
select p.name, j.commit_sha, min(j.created)
from action_run_job j join action_run r on r.id = j.run_id join repository p on p.id = j.repo_id
where j.status = 5 and j.task_id = 0 and r.ref like 'refs/pull/%/head'
  and r.event in ('pull_request', 'pull_request_sync')
group by p.name, j.commit_sha order by 3;
"""


def approved(repo: str, sha: str, cache: set[str]) -> bool:
    if sha in cache:
        return True
    need = APPROVALS.get(repo, DEFAULT_APPROVALS)
    newest: dict[str, str] = {}                 # statuses come newest first: a later failure wins
    for s in b.commit_statuses(repo, sha):
        newest.setdefault(s["context"], s.get("state", ""))
    if all(newest.get(c) == "success" for c in need):
        cache.add(sha)
        return True
    return False


def move_sql(shas: list[str], slots: int) -> str:
    good = [s for s in shas if b.SAFE_SHA.match(s)]
    ids = ",".join(repr(s) for s in good) or "''"
    return f"""
with others as (select coalesce(min(updated), extract(epoch from now())::bigint) mn from action_run_job
                where status = 5 and task_id = 0 and commit_sha not in ({ids})),
pick as (select j.id, row_number() over (order by j.created, j.id) rn from action_run_job j
         join action_run r on r.id = j.run_id
         where j.status = 5 and j.task_id = 0 and j.commit_sha in ({ids})
           and r.ref like 'refs/pull/%/head' and r.event in ('pull_request', 'pull_request_sync')
         order by j.created, j.id limit {int(slots)})
update action_run_job j set updated = (select mn from others) - 1000 + pick.rn
from pick where j.id = pick.id and j.status = 5 and j.task_id = 0
  and j.updated >= (select mn from others)
returning j.id, j.commit_sha;
"""


def main(query=cs.psql, post=cs.board) -> int:
    try:
        st, body = b.github("GET", "/rate_limit")
        budget = int(body["resources"]["core"]["remaining"]) if st == 200 else None
    except Exception:  # noqa: BLE001
        budget = None
    if budget is not None and budget < MIN_BUDGET:
        print(f"  approved-first: skipped (GitHub API budget {budget} < {MIN_BUDGET})")
        return 0
    try:
        cache = set(json.loads(STATE.read_text()))
    except (OSError, ValueError):
        cache = set()
    try:
        heads = query(WAITING_HEADS_SQL)
        eligible = [(repo, sha) for repo, sha, _ in heads if b.SAFE_SHA.match(sha) and approved(repo, sha, cache)]
        moved = query(move_sql([sha for _, sha in eligible], SLOTS)) if eligible else []
    except Exception as e:  # noqa: BLE001 - never fails the sync
        print(f"  approved-first: skipped ({type(e).__name__})")
        return 0
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(sorted(cache & {sha for _, sha, _ in heads})))
    except OSError:
        pass
    if moved:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        repo_of = dict((sha, repo) for repo, sha in eligible)
        lines = [f"{stamp} to the front: job {r[0]} {repo_of.get(r[1], '?')} {r[1][:8]}" for r in moved]
        print("\n".join("  " + x for x in lines))
        try:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG, "a") as f:
                f.write("\n".join(lines) + "\n")
        except OSError:
            pass
        post(f"[Windy Git] approved-first: {len(moved)} job(s) of fully-approved PRs moved to the front "
             f"({len(eligible)} approved heads waiting). Log: {LOG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
