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
MAIN PASS (Boss YES 2026-11-12T02:56:14Z; 174 of 463 waiting jobs stood on older main commits): with
MAIN_SUPERSEDE=dry or on, a WAITING/BLOCKED unclaimed job on an OLDER default-branch push commit is cancelled
when a newer default-branch push run of the same repo exists. Never a running job, never the newest main commit,
never a tag, schedule or dispatch (release) run, never a re-run asked for by name (attempt > 1), never a sha on
the KEEP list (KEEP_FILE: one line per sha, '<40-hex sha> <lane> <BOARD time>'; a lane with a booked deploy at
an older sha adds it, or uses Boss's identical-tree rule). dry: the same selection, nothing changed, ONE BOARD
line with the count per repo (once: DRY_MARK). on: cancelled like the PR pass, every job id logged, one BOARD
line. Off by default; an unreadable KEEP file skips the main pass (it cancels nothing).
ONE SQL statement selects and cancels together and RETURNS what it cancelled, so a job a runner
claims in between is never touched. A run whose jobs are now all cancelled is closed. Each
cancel is printed (the sync's journal) and appended to LOG; one BOARD line per pass when
the count is above 0. Never fails the sync.
HEAL + RELEASE (11-13): every pass closes attempt rows a DB cancel left WAITING on cancelled runs (Gitea 28
counts them as concurrency holders, so the next run of the group sat BLOCKED forever); RELEASE_BLOCKED=dry|on
(off by default) then wakes the newest run per (repo, group) that nothing else holds. See heal_and_release().
"""

from __future__ import annotations

import os
import pwd
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

LOG = Path(os.environ.get("CANCEL_SUPERSEDED_LOG", "/var/log/windygit/superseded-cancels.log"))
BOARD_USER = os.environ.get("BOARD_USER", "user1-gpu")
FALLBACK_DIR = os.environ.get("BOARD_FALLBACK_DIR", f"/home/{BOARD_USER}/windy-orchestra-fallback")
KEEP_FILE = Path(os.environ.get("MAIN_SUPERSEDE_KEEP", "/var/lib/windygit/keep-main.txt"))
DRY_MARK = Path(os.environ.get("MAIN_SUPERSEDE_DRY_MARK", "/var/lib/windygit/main-supersede-dry.posted"))
KEEP_LINE = re.compile(r"^([0-9a-f]{40})\s+(\S.*?)\s+(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ)\s*$")

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

MAIN_VICTIMS = """
with newest as (
  select distinct on (r.repo_id) r.repo_id, r.commit_sha
  from action_run r join repository p on p.id = r.repo_id
  where r.event = 'push' and r.ref = 'refs/heads/' || p.default_branch
  order by r.repo_id, r.id desc
), victims as (
  select j.id from action_run_job j
  join action_run r on r.id = j.run_id
  join repository p on p.id = r.repo_id
  join newest n on n.repo_id = r.repo_id
  where j.status in (5, 7, 9) and j.task_id = 0 and j.attempt <= 1
    and r.event = 'push' and r.ref = 'refs/heads/' || p.default_branch
    and r.commit_sha <> n.commit_sha
    and r.commit_sha <> all({keep}::text[])
  {lock}
)"""


def _keep_array(keep: set[str]) -> str:
    shas = sorted(k for k in keep if re.fullmatch(r"[0-9a-f]{40}", k))   # only hex ever reaches the SQL
    return "array[" + ", ".join(f"'{k}'" for k in shas) + "]"


def main_cancel_sql(keep: set[str]) -> str:
    return MAIN_VICTIMS.format(keep=_keep_array(keep), lock="for update of j skip locked") + """, done as (
  update action_run_job j set status = 3, stopped = extract(epoch from now())::bigint,
         updated = extract(epoch from now())::bigint
  from victims v where j.id = v.id and j.status in (5, 7, 9) and j.task_id = 0
  returning j.id, j.run_id, j.repo_id, j.commit_sha, j.name
)
select d.id, p.name, r.ref, substr(d.commit_sha, 1, 8), d.name, d.run_id
from done d join action_run r on r.id = d.run_id join repository p on p.id = d.repo_id order by p.name, d.id;
"""


def main_dry_sql(keep: set[str]) -> str:
    return MAIN_VICTIMS.format(keep=_keep_array(keep), lock="") + """
select j.id, p.name, r.ref, substr(j.commit_sha, 1, 8), j.name, j.run_id
from victims v join action_run_job j on j.id = v.id join action_run r on r.id = j.run_id
join repository p on p.id = j.repo_id order by p.name, j.id;
"""


def keep_shas() -> tuple[set[str], int]:
    """(shas, bad line count). Missing file = empty list. Any other read error raises: the caller skips the
    main pass (fail safe). Never follows a symlink; reads at most 1 MB; prints nothing from the file."""
    try:
        fd = os.open(KEEP_FILE, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return set(), 0
    with os.fdopen(fd, "rb") as f:
        text = f.read(1 << 20).decode("utf-8", "replace")
    shas, bad = set(), 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = KEEP_LINE.match(line)
        if m and not re.match(r"^\d{4}-\d\d-\d\dT", m.group(2)):
            shas.add(m.group(1))
        else:
            bad += 1
    return shas, bad


# Gitea 28.x (windy-git #149): 9 = pending (waiting on `needs:`; 1.24 used 7 for that), 8 = cancelling
# (a RUNNING job asked to stop; never touched here). A run also has attempt rows with their own status
# (action_run_attempt; run.status mirrors it), so they are closed too. On 1.24 neither 9 nor that table
# exists, so this is the same SQL as before there. Source: models/actions/status.go, services/actions/run.go
# (insertRunJob: Waiting + needs -> Pending), models/actions/run_attempt.go at v28.3.0.
# TWO columns on purpose: psql() keeps only lines with a "|" in them (it drops psql's command tags), so a
# one-column answer ("t") came back as [] and the attempt rows were NEVER closed (11-13: 1360 attempts of
# cancelled runs still read waiting, and Gitea counted them as holders of their concurrency group).
HAS_ATTEMPTS_SQL = "select 'attempts', to_regclass('public.action_run_attempt') is not null;"

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


BOARD_SAY = '~/windy-orchestra/bin/board-say "Windy Git"'
LANE_PREFIX = "[Windy Git] "


def board(line: str) -> bool:
    """One BOARD line: Windy 0 over ssh as the lane user; while Windy 0 is down, the fallback board.
    True only when the line was written somewhere (board-say said OK, or a fallback file); callers that
    must not lose a line check it (red_main, Hub #112).
    BOARD STANDARD (Windy Boss 2026-11-10T18:29:46Z, Grant's GO): every line goes through board-say, which
    adds "- [time Windy Git]" with Windy 0's clock; so the "[Windy Git] " prefix the callers write is
    dropped here and no time is sent (board-say refuses a line that starts with one). A refusal or any
    answer other than "OK ..." is a failed post and the line goes to the fallback board, never lost."""
    stamped = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {line}\n"
    text = line[len(LANE_PREFIX):] if line.startswith(LANE_PREFIX) else line
    try:
        r = subprocess.run(["runuser", "-u", BOARD_USER, "--", "timeout", "25", "ssh", "-o", "BatchMode=yes",
                            "-o", "ConnectTimeout=8", "eth-windy0", BOARD_SAY],
                           input=text + "\n", text=True, capture_output=True, timeout=40)
        if r.returncode == 0 and (getattr(r, "stdout", "") or "").startswith("OK "):
            return True
        if r.returncode == 2:   # board-say REFUSED the text: say why in the journal; the fallback keeps the line
            print(f"  board-say refused: {(getattr(r, 'stderr', '') or '').strip()[:200]}")
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


def _log_and_post(rows: list[list[str]], post, label: str, headline: str) -> None:
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    lines = [f"{stamp} cancelled job {r[0]} {r[1]} {r[2]} {r[3]} {r[4]}{label}" for r in rows]
    print("\n".join("  " + x for x in lines))
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass
    post(headline.format(n=len(rows), repos=_per_repo(rows)) + f" Log: {LOG}")


def _per_repo(rows: list[list[str]]) -> str:
    per_repo: dict[str, int] = {}
    for r in rows:
        per_repo[r[1]] = per_repo.get(r[1], 0) + 1
    return ", ".join(f"{k} {v}" for k, v in sorted(per_repo.items()))


def _close_runs(query, rows: list[list[str]]) -> None:
    runs = sorted({r[5] for r in rows if r[5].isdigit()})
    if runs:
        query(CLOSE_RUNS_SQL.format(ids=",".join(runs)))
        if _has_attempts(query):
            query(CLOSE_ATTEMPTS_SQL.format(ids=",".join(runs)))


def _has_attempts(query) -> bool:
    return query(HAS_ATTEMPTS_SQL) == [["attempts", "t"]]


# HEAL (11-13): an attempt row still WAITING/BLOCKED/PENDING whose run is CANCELLED and whose own jobs are all
# cancelled is left over from a DB-write cancel (the parse bug above). Gitea 28 counts a waiting attempt as a
# HOLDER of its concurrency group (models/actions/run.go GetConcurrencyHolders: waiting, running, cancelling),
# so every later run in that group is BLOCKED (status 7) and never runs: windy-pro main 44273 and windy-chat
# main 44269 on 11-13, behind cancelled runs 41489 and 42822. Only cancelled runs; never a running or
# cancelling attempt; RETURNING says exactly what changed.
HEAL_ATTEMPTS_SQL = """
update action_run_attempt a set status = 3, stopped = extract(epoch from now())::bigint,
       updated = extract(epoch from now())::bigint
from action_run r
where r.id = a.run_id and r.status = 3 and a.status in (5, 7, 9)
  and not exists (select 1 from action_run_job j where j.run_attempt_id = a.id and j.status <> 3)
returning 'healed', a.id, a.run_id;
"""

# RELEASE (RELEASE_BLOCKED=dry|on, off by default): what Gitea's checkRunConcurrency would have done had the
# holder finished through Gitea. A run BLOCKED by run-level concurrency is woken when NO other run holds its
# group (no attempt and no job of another run waiting, running or cancelling, the same test as Gitea's
# shouldBlockRunByConcurrency). The newest blocked run per (repo, group) only. Never a run awaiting approval.
# Refused (left for Gitea or a person) when any job of it has job-level concurrency (raw_concurrency) or a
# no-needs job carries a job-level `if:` (4-space key in its payload): Gitea evaluates those, a DB write
# cannot. Jobs with no needs -> 5 (waiting); jobs with needs -> 9 (pending: Gitea's resolver moves them on as
# their needs finish). Then +1 on action_tasks_version for the global, owner and repo runner scopes, so idle
# runners fetch again (FetchTask only queries when the version moved).
RELEASE_VICTIMS = r"""
with blocked as (
  select a.id as att, a.run_id, a.repo_id, a.concurrency_group, r.owner_id
  from action_run_attempt a join action_run r on r.id = a.run_id and r.latest_attempt_id = a.id
  where a.status = 7 and r.status = 7 and not r.need_approval and coalesce(a.concurrency_group, '') <> ''
    and not exists (select 1 from action_run_attempt h where h.repo_id = a.repo_id
                    and h.concurrency_group = a.concurrency_group and h.status in (5, 6, 8) and h.run_id <> a.run_id)
    and not exists (select 1 from action_run_job hj where hj.repo_id = a.repo_id
                    and hj.concurrency_group = a.concurrency_group and hj.status in (5, 6, 8) and hj.run_id <> a.run_id)
    and not exists (select 1 from action_run_job x where x.run_attempt_id = a.id and x.status = 7
                    and (coalesce(x.raw_concurrency, '') <> ''
                         or (coalesce(x.needs, '') in ('', 'null', '[]')
                             and convert_from(x.workflow_payload, 'UTF8') ~ E'\n    if:')))
), victims as (
  select distinct on (repo_id, concurrency_group) * from blocked order by repo_id, concurrency_group, run_id desc
)"""

RELEASE_DRY_SQL = RELEASE_VICTIMS + """
select 'release', v.run_id, p.name, v.concurrency_group from victims v join repository p on p.id = v.repo_id
order by p.name, v.run_id;
"""

RELEASE_SQL = RELEASE_VICTIMS + """, att as (
  update action_run_attempt a set status = 5, updated = extract(epoch from now())::bigint
  from victims v where a.id = v.att and a.status = 7
  returning a.id, a.run_id
), run as (
  update action_run r set status = 5, updated = extract(epoch from now())::bigint
  from att where r.id = att.run_id and r.status = 7
  returning r.id, r.repo_id, r.owner_id
), jobs as (
  update action_run_job j set status = case when coalesce(j.needs, '') in ('', 'null', '[]') then 5 else 9 end,
         updated = extract(epoch from now())::bigint
  from att where j.run_attempt_id = att.id and j.status = 7
  returning j.id, j.run_id
)
select 'release', run.id, p.name, v.concurrency_group, run.repo_id, run.owner_id,
       (select count(*) from jobs where jobs.run_id = run.id)
from run join victims v on v.run_id = run.id join repository p on p.id = run.repo_id order by p.name, run.id;
"""

# Gitea 28's action_tasks_version names its time column updated_unix (not "updated" as the run tables do):
# 11-13 18:36:40Z the first live RELEASE woke windy-chat 44269 and then this bump failed on "updated".
BUMP_SQL = """
update action_tasks_version set version = version + 1, updated_unix = extract(epoch from now())::bigint
where (owner_id = 0 and repo_id = 0) or (owner_id in ({owners}) and repo_id = 0) or (owner_id = 0 and repo_id in ({repos}));
"""


def _why(e: Exception) -> str:
    """The error class plus psql's first stderr line (a Postgres message: SQL and names, never a value)."""
    err = (getattr(e, "stderr", "") or "").strip().splitlines()
    return f"{type(e).__name__}: {err[0][:160]}" if err else type(e).__name__


def heal_and_release(query, post) -> None:
    """Never fails the sync. HEAL always (it is the close that should have happened); RELEASE per RELEASE_BLOCKED."""
    try:
        if not _has_attempts(query):
            return
        healed = query(HEAL_ATTEMPTS_SQL)
    except Exception as e:  # noqa: BLE001
        print(f"  cancel-superseded (heal): skipped ({type(e).__name__})")
        return
    if healed:
        print(f"  cancel-superseded (heal): {len(healed)} attempt row(s) of cancelled runs closed "
              f"(runs {', '.join(sorted({r[2] for r in healed}, key=int)[:20])}{' ...' if len(healed) > 20 else ''})")
    mode = os.environ.get("RELEASE_BLOCKED", "off").strip().lower()
    if mode not in ("dry", "on"):
        return
    try:
        if mode == "dry":
            rows = query(RELEASE_DRY_SQL)
            if rows:
                print(f"  cancel-superseded (release) DRY RUN: would wake {len(rows)} blocked run(s): "
                      + ", ".join(f"{r[2]} {r[1]}" for r in rows))
            return
        rows = query(RELEASE_SQL)
    except Exception as e:  # noqa: BLE001
        print(f"  cancel-superseded (release): skipped ({_why(e)})")
        return
    # The release is COMMITTED by now: whatever the bump does, the woken runs are logged and posted (11-13: a
    # failed bump used to skip both, so the first live release reached neither the log nor the BOARD).
    bump = ""
    if rows:
        repos = sorted({r[4] for r in rows if r[4].isdigit()}, key=int)
        owners = sorted({r[5] for r in rows if r[5].isdigit()}, key=int)
        if repos and owners:
            try:
                query(BUMP_SQL.format(owners=",".join(owners), repos=",".join(repos)))
            except Exception as e:  # noqa: BLE001
                bump = f"; runner-scope bump FAILED ({_why(e)}): idle runners see them at the next version change"
                print(f"  cancel-superseded (release): bump failed ({_why(e)})")
    if rows:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        lines = [f"{stamp} released run {r[1]} {r[2]} group {r[3]} jobs {r[6]}{bump}" for r in rows]
        print("\n".join("  " + x for x in lines))
        try:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG, "a") as f:
                f.write("\n".join(lines) + "\n")
        except OSError:
            pass
        post(f"[Windy Git] cancel-superseded (release): {len(rows)} run(s) blocked behind a cancelled run woken "
             f"({', '.join(f'{r[2]} {r[1]}' for r in rows)}); nothing else held their group{bump}. Log: {LOG}")


def main_pass(query, post) -> None:
    mode = os.environ.get("MAIN_SUPERSEDE", "off").strip().lower()
    if mode not in ("dry", "on"):
        return
    try:
        keep, bad = keep_shas()
    except OSError as e:
        print(f"  cancel-superseded (main): skipped, keep list unreadable ({type(e).__name__})")
        return
    if bad:
        print(f"  cancel-superseded (main): {bad} keep line(s) ignored (need '<40-hex sha> <lane> <BOARD time>')")
    try:
        if mode == "dry":
            rows = query(main_dry_sql(keep))
        else:
            rows = query(main_cancel_sql(keep))
            if rows:
                _close_runs(query, rows)
    except Exception as e:  # noqa: BLE001 - never fails the sync
        print(f"  cancel-superseded (main): skipped ({type(e).__name__})")
        return
    if mode == "dry":
        print(f"  cancel-superseded (main) DRY RUN: would cancel {len(rows)} job(s): {_per_repo(rows) or 'none'}")
        if DRY_MARK.exists():
            return
        if post(f"[Windy Git] cancel-superseded (main) DRY RUN: {len(rows)} waiting/blocked jobs on older main "
                f"commits would be cancelled ({_per_repo(rows) or 'none'}); keep list {len(keep)} sha(s); "
                f"cancelled nothing.") is not False:
            try:
                DRY_MARK.parent.mkdir(parents=True, exist_ok=True)
                DRY_MARK.write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\n")
            except OSError:
                pass
        return
    if rows:
        _log_and_post(rows, post, " (main)",
                      "[Windy Git] cancel-superseded (main): {n} waiting/blocked jobs on older main commits "
                      "cancelled ({repos}); the newest main of each repo and the keep list untouched.")


def main(query=psql, post=board) -> int:
    try:
        rows = query(CANCEL_SQL)
        if rows:
            _close_runs(query, rows)
    except Exception as e:  # noqa: BLE001 - never fails the sync
        print(f"  cancel-superseded: skipped ({type(e).__name__})")
        rows = []
    if rows:
        _log_and_post(rows, post, "",
                      "[Windy Git] cancel-superseded: {n} waiting/blocked PR jobs on replaced commits cancelled "
                      "({repos}).")
    main_pass(query, post)
    heal_and_release(query, post)
    return 0


if __name__ == "__main__":
    sys.exit(main())
