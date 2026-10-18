#!/usr/bin/env python3
"""Re-run ONLY CI that died of infrastructure, once per commit, never a real red.

Two kinds of infrastructure death (both say nothing about the code):
  dead-before-step  the job container never started: no step ran (Boss ruling E, 10-07).
  runner-lost       the runner vanished MID-step (the 10-17 18:56Z Veron restart killed
                    windy-pro run 3326 in `npm test`): Gitea stopped the task itself and marked
                    every unfinished later step failed with no log at the task's stop time; a
                    runner reporting a real failure marks those steps skipped instead.

Runs ON Veron 1 as root every 10 minutes (windygit-autorerun.timer). A re-run is
scripts/rerun_ci.sh: rewind the Windy Git branch one commit, the next sync pushes it back, and
Gitea re-fires EVERY enabled workflow on that push / pull_request_sync event at the commit. So
the decision is about the whole COMMIT, not one job (Hub, 10-18). A commit is re-run only if,
over the latest run of each (workflow, event) on a CI event (push / pull_request /
pull_request_sync; scheduled runs never count):
  - every workflow is on the per-repo allowlist ci/autorerun-allow.yml (CI tests only: nothing
    that deploys, releases, publishes, mirrors or probes production), and the repo holds no
    Actions secret (a step without one cannot authenticate anywhere);
  - every job is finished (a still-running workflow could finish real-red after the pick and
    then be re-run into green);
  - no job is a real red (a failure that is neither kind above);
  - at least one job is dead-before-step or runner-lost.
The commit is judged again from fresh rows right before rerun_ci.sh.

Guard rails, in code: ONE automatic re-run per (repo, sha) EVER across both kinds (the
ledger is never pruned; a second failure stays red for a human), ONE per pass, an flock so a
manual run beside the timer cannot double-run, and rerun_ci.sh itself refuses unless the
branch is still at that sha. The ledger is written atomically BEFORE acting, with the kind,
job id and, after, rerun_ci.sh's exit code: the bridge posts windy-git/autorerun ("re-queued
once") only for exit 0. A corrupt ledger or allowlist = re-run nothing and exit 1.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

STATE = Path(os.environ.get("AUTORERUN_STATE", "/var/lib/windygit/autorerun.json"))
COUNTS = Path(os.environ.get("AUTORERUN_COUNTS", "/var/lib/windygit/autorerun_counts.json"))
LOCK = Path(os.environ.get("AUTORERUN_LOCK", "/run/windygit-autorerun.lock"))
HERE = Path(__file__).resolve().parent
ALLOW_FILE = Path(os.environ.get("AUTORERUN_ALLOW", HERE.parent / "ci" / "autorerun-allow.yml"))
WINDOW_S = 45 * 60
MAX_PER_PASS = 1
EVENTS = ("push", "pull_request", "pull_request_sync")
TERMINAL = {1, 2, 3, 4}  # success, failure, cancelled, skipped
KINDS = ("dead-before-step", "runner-lost")
_SHA = re.compile(r"^[0-9a-f]{40}$")


def candidates_sql(since: int) -> str:
    """Facts only: failed, assigned jobs on a CI event since `since` (epoch seconds)."""
    return f"""
select r.repo_id, p.name, r.commit_sha, r.ref
from action_run_job j
join action_run r on r.id = j.run_id
join repository p on p.id = r.repo_id
where j.status = 2 and j.task_id > 0 and j.stopped > {int(since)}
  and r.event in ('push', 'pull_request', 'pull_request_sync')
group by r.repo_id, p.name, r.commit_sha, r.ref
order by max(j.stopped);
"""


def commit_sql(repo_id: int, sha: str) -> str:
    """Facts only: every job of every run at the commit, with its step marks.
    Columns: run index, workflow, event, job id, job status, task id, steps that ran,
    runner-lost marks, Actions secrets the repo (or its owner) holds."""
    return f"""
select r."index", r.workflow_id, r.event, j.id, j.status, j.task_id,
  (select count(*) from action_task_step s where s.task_id = j.task_id and s.status in (1, 2)),
  (select count(*) from action_task_step s join action_task t on t.id = s.task_id
     where s.task_id = j.task_id and s.status = 2 and s.log_length = 0
       and t.stopped > 0 and s.stopped = t.stopped
       and s."index" > (select min(s2."index") from action_task_step s2
                        where s2.task_id = j.task_id and s2.status = 2)),
  (select count(*) from secret sec where sec.repo_id = r.repo_id
     or sec.owner_id = (select p.owner_id from repository p where p.id = r.repo_id))
from action_run r
join action_run_job j on j.run_id = r.id
where r.repo_id = {int(repo_id)} and r.commit_sha = '{sha}'
order by r."index", j.id;
"""


def psql(sql: str) -> list[list[str]]:
    out = subprocess.run(
        ["docker", "exec", "-i", "windy-git-db-1", "sh", "-c",
         'psql -U "$POSTGRES_USER" -d gitea -At -F "|" -v ON_ERROR_STOP=1'],
        input=sql, capture_output=True, text=True, check=True, timeout=30,
    ).stdout.strip()
    return [line.split("|") for line in out.splitlines() if line]


def branch_for(repo_id: str, ref: str, query=psql) -> str | None:
    """refs/heads/x -> x. refs/pull/N/head -> the PR's head branch (same-repo PRs only)."""
    if ref.startswith("refs/heads/"):
        return ref[len("refs/heads/"):]
    parts = ref.split("/")
    if len(parts) == 4 and parts[1] == "pull" and parts[2].isdigit() and str(repo_id).isdigit():
        rows = query(
            "select pr.head_branch from pull_request pr join issue i on i.id = pr.issue_id "
            f"where i.repo_id = {int(repo_id)} and i.\"index\" = {int(parts[2])} and pr.head_repo_id = i.repo_id;")
        return rows[0][0] if rows else None
    return None


def judge(repo: str, rows: list[list[str]], allow: dict) -> tuple[str | None, str, str]:
    """(kind or None, job id, reason). Pure: decides from commit_sql rows only."""
    jobs = []
    for row in rows:
        idx, wf, ev, job, st, task, ran, lost, secrets = row[:9]
        jobs.append({"idx": int(idx), "wf": wf, "ev": ev, "job": job, "st": int(st), "task": int(task),
                     "ran": int(ran), "lost": int(lost), "secrets": int(secrets)})
    if any(j["secrets"] > 0 for j in jobs):
        return None, "", "repo holds Actions secrets"
    ci = [j for j in jobs if j["ev"] in EVENTS]
    if not ci:
        return None, "", "no CI-event run"
    latest: dict[tuple[str, str], int] = {}
    for j in ci:
        k = (j["wf"], j["ev"])
        latest[k] = max(latest.get(k, j["idx"]), j["idx"])
    cur = [j for j in ci if j["idx"] == latest[(j["wf"], j["ev"])]]
    allowed = allow.get(repo, set())
    if any(j["wf"] not in allowed for j in cur):
        return None, "", "workflow not on the allowlist"
    if any(j["st"] not in TERMINAL for j in cur):
        return None, "", "a run is not finished"
    dead, lost, real = [], [], []
    for j in cur:
        if j["st"] != 2:
            continue
        if j["task"] > 0 and j["lost"] > 0:
            lost.append(j)
        elif j["task"] > 0 and j["ran"] == 0:
            dead.append(j)
        else:
            real.append(j)
    if real:
        return None, "", "a real red at the commit"
    if lost:
        return "runner-lost", min(lost, key=lambda j: int(j["job"]))["job"], "ok"
    if dead:
        return "dead-before-step", min(dead, key=lambda j: int(j["job"]))["job"], "ok"
    return None, "", "nothing infra-dead in the latest runs"


def load_allow() -> dict | None:
    """repo -> set of workflow files. None = missing or malformed: re-run nothing."""
    try:
        d = yaml.safe_load(ALLOW_FILE.read_text())
        repos = d["repos"]
        return {str(r): {str(w) for w in wfs} for r, wfs in repos.items() if isinstance(wfs, list)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError):
        return None


def load_state() -> dict | None:
    """The once-per-commit ledger, never pruned. Missing = empty (first run). Unreadable or
    malformed = None: re-run nothing (a lost ledger could re-run a commit twice)."""
    try:
        text = STATE.read_text()
    except FileNotFoundError:
        return {}
    except OSError:
        return None
    try:
        s = json.loads(text)
    except ValueError:
        return None
    if not isinstance(s, dict) or not all(isinstance(v, dict) for v in s.values()):
        return None
    return s


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def save_state(s: dict) -> None:
    """Atomic: temp file in the same directory, fsync'd, os.replace. Old or new, never torn."""
    _atomic_write(STATE, json.dumps(s))


def bump_count(kind: str) -> dict:
    """Running totals per kind."""
    try:
        c = json.loads(COUNTS.read_text())
        c = c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        c = {}
    c[kind] = int(c.get(kind, 0)) + 1 if str(c.get(kind, 0)).isdigit() else 1
    _atomic_write(COUNTS, json.dumps(c))
    return c


def plan(state: dict, allow: dict, now: float, query=psql) -> tuple[list[dict], dict]:
    """Eligible commits (at most MAX_PER_PASS) and a count of refusal reasons."""
    out, why = [], {}
    for repo_id, repo, sha, ref in (r[:4] for r in query(candidates_sql(int(now) - WINDOW_S))):
        key = f"{repo}@{sha}"
        if key in state or not _SHA.match(sha) or not str(repo_id).isdigit():
            continue
        kind, job, reason = judge(repo, query(commit_sql(int(repo_id), sha)), allow)
        if not kind:
            why[reason] = why.get(reason, 0) + 1
            continue
        branch = branch_for(repo_id, ref, query)
        if not branch:
            why["branch not resolvable"] = why.get("branch not resolvable", 0) + 1
            continue
        out.append({"repo": repo, "repo_id": int(repo_id), "sha": sha, "branch": branch,
                    "key": key, "kind": kind, "job": job})
        if len(out) >= MAX_PER_PASS:
            break
    return out, why


def main() -> int:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lock:  # held for the whole pass; released when the file closes
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("autorerun: another pass holds the lock; nothing done")
            return 0
        return _pass()


def _pass() -> int:
    state, allow = load_state(), load_allow()
    if state is None or allow is None:
        print(f"autorerun: REFUSING, {'ledger ' + str(STATE) if state is None else 'allowlist ' + str(ALLOW_FILE)}"
              " unreadable or malformed; nothing re-run")
        return 1
    todo, why = plan(state, allow, time.time(), query=psql)
    by = {k: sum(t["kind"] == k for t in todo) for k in KINDS}
    print(f"autorerun: {len(todo)} commit(s) to re-run (dead-before-step {by['dead-before-step']}, "
          f"runner-lost {by['runner-lost']}); refused: {json.dumps(why, sort_keys=True)}")
    for t in todo:
        kind, _job, reason = judge(t["repo"], psql(commit_sql(t["repo_id"], t["sha"])), allow)
        if kind != t["kind"]:  # fresh rows right before acting: the commit moved on
            print(f"  {t['repo']}@{t['sha'][:7]}: re-check refused ({reason}); not re-run")
            continue
        state[t["key"]] = {"at": time.time(), "branch": t["branch"], "kind": t["kind"], "job": t["job"]}
        save_state(state)  # record BEFORE acting: a crash must never cause a second attempt
        bump_count(t["kind"])
        env = {**os.environ, "WGQ": str(HERE / "wg_sql.sh")}
        try:
            r = subprocess.run(["bash", str(HERE / "rerun_ci.sh"), t["repo"], t["branch"], t["sha"][:8]],
                               env=env, capture_output=True, text=True, timeout=1000)
            rc, first = r.returncode, (r.stdout.strip().splitlines() or [""])[0][:100]
        except subprocess.TimeoutExpired:
            rc, first = 124, "timed out (rerun_ci.sh restores the branch itself at its deadline)"
        state[t["key"]]["exit"] = rc
        save_state(state)
        print(f"  {t['repo']}@{t['sha'][:7]} ({t['branch']}, {t['kind']}): rerun exit {rc}: {first}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
