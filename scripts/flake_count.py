#!/usr/bin/env python3
"""Count LOGGED CI flake retries over the last 7 days; flag a LOW to Boss when one goes over its limit.

Boss's rule (10-28, FLAKE-1): a test may retry a known flake ONCE, only if the retry is logged
by name and counted, and more than 2 retries in a week raises a LOW to Boss. A silent retry is
not OK. The retry prints exactly one line per retry, which this job counts:

  [WINDY-FLAKE-RETRY] <FLAKE-ID> <what>      e.g. "[WINDY-FLAKE-RETRY] FLAKE-1 chromium-launch"

It reads the logs of the WATCHed finished jobs (Gitea API, admin token from the env, never argv;
each finished job ATTEMPT's count is cached, so each log is read once). Output, read by windy-job --expect:
  flake count: <N> retries in 7 days (<per id>)
  over limit: none                     <- the healthy line
  over limit: FLAKE-1 x3 (LOW to Boss) <- windy-uptime's heartbeat check alerts on it

  sudo python3 scripts/flake_count.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

WATCH = [("windy-pro", "gates")]          # (repo, job name) whose logs carry retries
MARK = re.compile(r"^\S*\s*\[WINDY-FLAKE-RETRY\] (\S+)", re.M)  # log lines may carry a timestamp prefix
LIMIT = 2                                 # more than this in the window = LOW to Boss
WINDOW_S = 7 * 86400
STATE = Path(os.environ.get("FLAKE_STATE", "/var/lib/windygit/flake-count.json"))
GITEA = os.environ.get("GITEA_URL", "http://localhost:3080")


def psql(sql: str) -> list[list[str]]:
    out = subprocess.run(
        ["docker", "exec", "-i", "windy-git-db-1", "sh", "-c",
         'psql -U "$POSTGRES_USER" -d gitea -At -F "|" -v ON_ERROR_STOP=1'],
        input=sql, capture_output=True, text=True, check=True, timeout=60,
    ).stdout.strip()
    return [line.split("|") for line in out.splitlines() if line]


def finished_jobs(now: int, query=psql) -> list[tuple[int, int, str, int]]:
    """[(job id, attempt, repo, stopped)] for WATCHed jobs that finished (ok or failed) inside the
    window. A Gitea re-run reuses the job id and bumps `attempt`, and its log REPLACES the old one,
    so each attempt is its own entry (Hub, #88)."""
    out = []
    for repo, name in WATCH:
        rows = query(
            "select j.id, j.attempt, j.stopped from action_run_job j join repository p on p.id = j.repo_id "
            f"where p.lower_name = '{repo.lower()}' and j.name = '{name}' and j.status in (1, 2) "
            f"and j.stopped > {now - WINDOW_S};")
        out += [(int(r[0]), int(r[1]), repo, int(r[2])) for r in rows]
    return out


def fetch_log(repo: str, job: int) -> str:
    req = urllib.request.Request(f"{GITEA}/api/v1/repos/windyadmin/{repo}/actions/jobs/{job}/logs",
                                 headers={"Authorization": f"token {os.environ['GITEA_ADMIN_TOKEN']}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode(errors="replace")


def count(log: str) -> dict[str, int]:
    return dict(Counter(MARK.findall(log)))


def run(now: int, query=psql, fetch=fetch_log, state_path: Path = STATE) -> tuple[list[str], bool]:
    """(output lines, all logs read). Cache: {"<job id>:<attempt>": {"stopped": t, "counts": {flake id: n}}}.
    Pruned by AGE, not by this run's job list: a job waiting on (or running) a re-run drops out of
    the query, but its earlier attempt still counts (Hub, #88)."""
    try:
        cache = json.loads(state_path.read_text())
    except (OSError, ValueError):
        cache = {}
    cache = {k: v for k, v in cache.items() if isinstance(v, dict) and "stopped" in v}  # pre-r2 format
    jobs = finished_jobs(now, query)
    ok = True
    for job, attempt, repo, stopped in jobs:
        key = f"{job}:{attempt}"
        if key not in cache:
            try:
                cache[key] = {"stopped": stopped, "counts": count(fetch(repo, job))}
            except Exception as e:  # noqa: BLE001 - one unreadable log must not hide the rest
                print(f"  {repo} job {job} attempt {attempt}: log unreadable ({type(e).__name__})", file=sys.stderr)
                ok = False
    cache = {k: v for k, v in cache.items() if v["stopped"] > now - WINDOW_S}
    total: Counter = Counter()
    for v in cache.values():
        total.update(v["counts"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(cache, sort_keys=True))
    per = ", ".join(f"{k}: {v}" for k, v in sorted(total.items())) or "none"
    over = [f"{k} x{v}" for k, v in sorted(total.items()) if v > LIMIT]
    lines = [f"flake count: {sum(total.values())} retries in 7 days across {len(cache)} job attempts ({per})",
             "over limit: " + (", ".join(over) + f" (more than {LIMIT} in 7 days: LOW to Boss)" if over else "none")]
    return lines, ok


def main() -> int:
    if "GITEA_ADMIN_TOKEN" not in os.environ:
        print("GITEA_ADMIN_TOKEN not set: refusing (nothing counted)")
        return 2
    lines, ok = run(int(time.time()))
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
