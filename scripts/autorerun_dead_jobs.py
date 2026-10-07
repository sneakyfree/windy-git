#!/usr/bin/env python3
"""Re-run ONLY the CI that died before any step ran (Boss ruling E, 10-07).

A job whose container never started (runc/overlay race, docker address pools, DNS at job
start) failed with NO step run: that is infrastructure, it says nothing about the code, and
a human re-run is pure toil (~0.7% of jobs). A job that ran a step and failed is NEVER
touched here: a real red stays red.

Runs ON Veron 1 as root every 10 minutes (windygit-autorerun.timer). For each commit with
such a dead job in the last 45 minutes it calls scripts/rerun_ci.sh (rewind the Windy Git
branch one commit; the next sync pushes it back and Gitea fires a fresh run).

Guard rails, in code: at most ONE automatic re-run per (repo, sha) ever (a second failure
stays red for a human), at most 3 per pass, nothing if a newer run already exists for that
sha, and rerun_ci.sh itself refuses unless the branch is still at that sha.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

STATE = Path(os.environ.get("AUTORERUN_STATE", "/var/lib/windygit/autorerun.json"))
HERE = Path(__file__).resolve().parent
WINDOW_S = 45 * 60
MAX_PER_PASS = 3
KEEP_S = 7 * 86400

CANDIDATES = f"""
select p.id, p.name, r.commit_sha, r.ref, r.index
from action_run r
join repository p on p.id = r.repo_id
join action_run_job j on j.run_id = r.id
where j.status = 2 and j.task_id > 0
  and j.stopped > extract(epoch from now()) - {WINDOW_S}
  and not exists (select 1 from action_task_step s where s.task_id = j.task_id and s.status in (1, 2))
  and not exists (select 1 from action_run r2 where r2.repo_id = r.repo_id
                  and r2.commit_sha = r.commit_sha and r2.index > r.index)
group by p.id, p.name, r.commit_sha, r.ref, r.index
order by r.index;
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
    if len(parts) == 4 and parts[1] == "pull" and parts[2].isdigit() and repo_id.isdigit():
        rows = query(
            "select pr.head_branch from pull_request pr join issue i on i.id = pr.issue_id "
            f"where i.repo_id = {int(repo_id)} and i.index = {int(parts[2])} and pr.head_repo_id = i.repo_id;")
        return rows[0][0] if rows else None
    return None


def pick(rows: list[list[str]], state: dict, now: float, query=psql) -> list[dict]:
    """Candidates still eligible: not retried before, branch resolvable, capped per pass."""
    out, seen = [], set()
    for repo_id, repo, sha, ref, _idx in rows:
        key = f"{repo}@{sha}"
        if key in state or key in seen:
            continue
        branch = branch_for(repo_id, ref, query)
        if not branch:
            continue
        seen.add(key)
        out.append({"repo": repo, "sha": sha, "branch": branch, "key": key})
        if len(out) >= MAX_PER_PASS:
            break
    return out


def load_state() -> dict:
    try:
        s = json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}
    cut = time.time() - KEEP_S
    return {k: v for k, v in s.items() if v.get("at", 0) > cut}


def save_state(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s))


def main() -> int:
    state = load_state()
    todo = pick(psql(CANDIDATES), state, time.time())
    print(f"autorerun: {len(todo)} dead-job commit(s) to re-run")
    for t in todo:
        state[t["key"]] = {"at": time.time(), "branch": t["branch"]}
        save_state(state)  # record BEFORE acting: a crash must never cause a second attempt
        env = {**os.environ, "WGQ": str(HERE / "wg_sql.sh")}
        r = subprocess.run(["bash", str(HERE / "rerun_ci.sh"), t["repo"], t["branch"], t["sha"][:8]],
                           env=env, capture_output=True, text=True, timeout=1000)
        print(f"  {t['repo']}@{t['sha'][:7]} ({t['branch']}): rerun exit {r.returncode}: "
              f"{(r.stdout.strip().splitlines() or [''])[0][:100]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
