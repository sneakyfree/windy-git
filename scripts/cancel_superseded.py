#!/usr/bin/env python3
"""Cancel WAITING CI jobs whose commit a newer push replaced on the same PR (Boss 10-28 08:44Z).

The queue was 150 deep and 23 of them (15%) were for PR commits nobody would ever read: the
bridge posts only on a PR's CURRENT head. This is GitHub's "cancel-in-progress", for pending only:
  - PR refs only (refs/pull/N/head), events pull_request / pull_request_sync;
  - the job is WAITING (status 5) or BLOCKED on its `needs:` (status 7), and unclaimed
    (task_id 0). NEVER a running job. Blocked jobs too (Hub #94 LOW): this cancel writes the DB
    directly, so Gitea never re-resolves a cancelled job's dependents, and they would sit
    blocked forever;
  - its run's commit is not the commit of the NEWEST run on that same repo + PR ref;
  - never a default-branch push, a tag, a schedule (the canary) or a dispatch.
ONE SQL statement selects and cancels together and RETURNS what it cancelled, so a job a runner
claims in between is never touched. A run whose jobs are now all cancelled is closed. Each
cancel is printed (the sync's journal) and appended to LOG; one BOARD line per pass when
the count is above 0. Never fails the sync.
"""

from __future__ import annotations

import os
import pwd
import stat
import subprocess
import sys
import time
from pathlib import Path

LOG = Path(os.environ.get("CANCEL_SUPERSEDED_LOG", "/var/log/windygit/superseded-cancels.log"))
BOARD_USER = os.environ.get("BOARD_USER", "user1-gpu")
FALLBACK_DIR = os.environ.get("BOARD_FALLBACK_DIR", f"/home/{BOARD_USER}/windy-orchestra-fallback")

CANCEL_SQL = """
with newest as (
  select distinct on (r.repo_id, r.ref) r.repo_id, r.ref, r.commit_sha
  from action_run r where r.ref like 'refs/pull/%/head' order by r.repo_id, r.ref, r.id desc
), victims as (
  select j.id from action_run_job j
  join action_run r on r.id = j.run_id
  join newest n on n.repo_id = r.repo_id and n.ref = r.ref
  where j.status in (5, 7, 9) and j.task_id = 0
    and r.ref like 'refs/pull/%/head' and r.event in ('pull_request', 'pull_request_sync')
    and r.commit_sha <> n.commit_sha
  for update of j skip locked
), done as (
  update action_run_job j set status = 3, stopped = extract(epoch from now())::bigint,
         updated = extract(epoch from now())::bigint
  from victims v where j.id = v.id and j.status in (5, 7, 9) and j.task_id = 0
  returning j.id, j.run_id, j.repo_id, j.commit_sha, j.name
)
select d.id, p.name, r.ref, substr(d.commit_sha, 1, 8), d.name, d.run_id
from done d join action_run r on r.id = d.run_id join repository p on p.id = d.repo_id order by p.name, d.id;
"""

CLOSE_RUNS_SQL = """
update action_run r set status = 3, stopped = extract(epoch from now())::bigint,
       updated = extract(epoch from now())::bigint
where r.id in ({ids}) and r.status in (5, 7, 9)
  and not exists (select 1 from action_run_job j where j.run_id = r.id and j.status <> 3);
"""


# Gitea 28.x (windy-git #149): 9 = pending (waiting on `needs:`; 1.24 used 7 for that), 8 = cancelling
# (a RUNNING job asked to stop; never touched here). A run also has attempt rows with their own status
# (action_run_attempt; run.status mirrors it), so they are closed too. On 1.24 neither 9 nor that table
# exists, so this is the same SQL as before there. Source: models/actions/status.go, services/actions/run.go
# (insertRunJob: Waiting + needs -> Pending), models/actions/run_attempt.go at v28.3.0.
HAS_ATTEMPTS_SQL = "select to_regclass('public.action_run_attempt') is not null;"

CLOSE_ATTEMPTS_SQL = """
update action_run_attempt a set status = 3, stopped = extract(epoch from now())::bigint,
       updated = extract(epoch from now())::bigint
where a.run_id in ({ids}) and a.status in (5, 7, 9)
  and not exists (select 1 from action_run_job j where j.run_attempt_id = a.id and j.status <> 3);
"""


def psql(sql: str) -> list[list[str]]:
    out = subprocess.run(
        ["docker", "exec", "-i", "windy-git-db-1", "sh", "-c",
         'psql -U "$POSTGRES_USER" -d gitea -At -F "|" -v ON_ERROR_STOP=1'],
        input=sql, capture_output=True, text=True, check=True, timeout=60,
    ).stdout.strip()
    return [line.split("|") for line in out.splitlines() if line and "|" in line]


def board(line: str) -> bool:
    """One BOARD line: Windy 0 over ssh as the lane user; while Windy 0 is down, the fallback board.
    True only when the line was written somewhere (ssh rc 0, or a fallback file); callers that must
    not lose a line check it (red_main, Hub #112)."""
    stamped = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {line}\n"
    try:
        r = subprocess.run(["runuser", "-u", BOARD_USER, "--", "timeout", "25", "ssh", "-o", "BatchMode=yes",
                            "-o", "ConnectTimeout=8", "eth-windy0", "cat >> ~/windy-orchestra/BOARD.md"],
                           input=stamped, text=True, capture_output=True, timeout=40)
        if r.returncode == 0:
            return True
    except (subprocess.SubprocessError, OSError):
        pass
    # TODAY's fallback file (Boss 11-02), not the newest existing one: an old file (BOARD-FALLBACK-
    # 20261027.md) is where nobody looks for today's lines. Created owned by the lane user, 0644, so
    # lanes appending as user1-gpu still can (these jobs run as root).
    path = os.path.join(FALLBACK_DIR, f"BOARD-FALLBACK-{time.strftime('%Y%m%d', time.gmtime())}.md")
    try:
        # Who will own a new file: resolved BEFORE writing, so a failure can't follow a written line
        # (the caller would retry and write it twice).
        owner = pwd.getpwnam(BOARD_USER) if os.geteuid() == 0 else None
        # As root: never follow a symlink, and set mode/owner on the OPEN FILE, not the path (Hub #119).
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o644)
    except (OSError, KeyError):
        return False
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            return False
        os.write(fd, stamped.encode())
        if st.st_size == 0:                     # we just created it (or it was empty): fix mode + owner
            os.fchmod(fd, 0o644)
            if owner is not None:
                os.fchown(fd, owner.pw_uid, owner.pw_gid)
        print(f"  BOARD: Windy 0 unreachable, line written to the FALLBACK board {os.path.basename(path)}")
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def main(query=psql, post=board) -> int:
    try:
        rows = query(CANCEL_SQL)
        if rows:
            runs = sorted({r[5] for r in rows if r[5].isdigit()})
            if runs:
                query(CLOSE_RUNS_SQL.format(ids=",".join(runs)))
                if query(HAS_ATTEMPTS_SQL) == [["t"]]:
                    query(CLOSE_ATTEMPTS_SQL.format(ids=",".join(runs)))
    except Exception as e:  # noqa: BLE001 - never fails the sync
        print(f"  cancel-superseded: skipped ({type(e).__name__})")
        return 0
    if not rows:
        return 0
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    lines = [f"{stamp} cancelled job {r[0]} {r[1]} {r[2]} {r[3]} {r[4]}" for r in rows]
    print("\n".join("  " + x for x in lines))
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass
    per_repo: dict[str, int] = {}
    for r in rows:
        per_repo[r[1]] = per_repo.get(r[1], 0) + 1
    post(f"[Windy Git] cancel-superseded: {len(rows)} waiting/blocked PR jobs on replaced commits cancelled ("
         + ", ".join(f"{k} {v}" for k, v in sorted(per_repo.items())) + f"). Log: {LOG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
