#!/usr/bin/env python3
"""Offsite runner guard (Hub #121 condition, 11-02): Null 0's CI runners may only ever serve
secret-free repos, and that must stay true AFTER registration, not just at it.

Gitea hands every Actions secret of a repo (and of its owner, and instance-wide ones) to every job
of that repo. register.sh refuses a repo with secrets, but a lane can add one later, and nothing
would notice. Every 10 minutes (windygit-offsite-guard.timer, on Veron, as root), for every live
offsite runner (name null0-*):
  * it must be scoped to exactly ONE repo (repo_id > 0); a global or owner-wide one is a violation;
  * that repo must hold 0 Actions secrets at repo, owner and instance level;
  * Null 0's egress unit must not be in a failed state (its filter or proof broke).
On ANY violation it cuts the offsite runners off at once, fail closed:
  1. ssh Null 0: `docker compose -p windy-git-runner-offsite stop runner-1 runner-2` (reversible);
  2. if that fails, soft-delete the null0-* runner rows in Gitea, so they can't fetch jobs (they must
     then be re-registered through register.sh, which re-checks the secrets).
One BOARD line per new violation set (state file), never a repeat every pass. Output for windy-job
--expect: "offsite guard: ok (...)" or "offsite guard: CUT OFF (...)" (no match -> alert).

  sudo python3 scripts/offsite_secret_guard.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cancel_superseded as cs  # noqa: E402  (psql + the BOARD line)

STATE = Path(os.environ.get("OFFSITE_GUARD_STATE", "/var/lib/windygit/offsite-guard.json"))
NULL0 = os.environ.get("NULL0_SSH", "eth-null0")
LANE_USER = os.environ.get("BOARD_USER", "user1-gpu")
PROJECT = "windy-git-runner-offsite"

RUNNERS_SQL = """
select r.id, r.name, r.owner_id, r.repo_id, coalesce(p.name, ''),
  (select count(*) from secret s where (r.repo_id > 0 and s.repo_id = r.repo_id)
     or (s.repo_id = 0 and s.owner_id = coalesce(p.owner_id, r.owner_id) and s.owner_id > 0)
     or (s.owner_id = 0 and s.repo_id = 0))
from action_runner r left join repository p on p.id = r.repo_id
where coalesce(r.deleted, 0) = 0 and r.name like 'null0-%'
order by r.id;
"""


def violations(rows: list[list[str]]) -> list[str]:
    """Pure: one reason per bad runner row (id, name, owner_id, repo_id, repo, secrets)."""
    out = []
    for rid, name, _owner, repo_id, repo, secrets in (r[:6] for r in rows):
        if not repo_id.isdigit() or int(repo_id) <= 0:
            out.append(f"{name} (id {rid}) is not scoped to one repo")
        elif not secrets.isdigit() or int(secrets) > 0:
            out.append(f"{name} (id {rid}) serves {repo or 'repo ' + repo_id}, which now sees {secrets} Actions secret(s)")
    return out


def ssh(cmd: str, run=subprocess.run) -> subprocess.CompletedProcess:
    return run(["runuser", "-u", LANE_USER, "--", "timeout", "40", "ssh", "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=8", NULL0, cmd], capture_output=True, text=True, timeout=60)


def egress_failed(run=subprocess.run) -> bool | None:
    """True if Null 0's egress unit is in a failed state; None if Null 0 can't be asked."""
    try:
        r = ssh("systemctl is-failed windygit-ci-egress-offsite.service", run)
    except (subprocess.SubprocessError, OSError):
        return None
    if r.returncode == 255:
        return None
    return r.stdout.strip() == "failed"


def stop_runners(run=subprocess.run) -> bool:
    try:
        r = ssh(f"sudo -n docker compose -p {PROJECT} stop runner-1 runner-2", run)
        return r.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def soft_delete(query) -> list[str]:
    rows = query("update action_runner set deleted = extract(epoch from now())::bigint "
                 "where coalesce(deleted, 0) = 0 and name like 'null0-%' returning id, name;")
    return [f"{r[1]} (id {r[0]})" for r in rows]


def load_state() -> dict:
    try:
        s = json.loads(STATE.read_text())
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, sort_keys=True))
    tmp.replace(STATE)


def main(query=cs.psql, run=subprocess.run, post=cs.board) -> int:
    rows = query(RUNNERS_SQL)
    bad = violations(rows)
    if rows and egress_failed(run) is True:
        bad.append("Null 0's egress unit (windygit-ci-egress-offsite) is FAILED")
    if not bad:
        save_state({})
        print(f"offsite guard: ok ({len(rows)} offsite runner(s), each repo-scoped and secret-free)")
        return 0
    how = "stopped on Null 0" if stop_runners(run) else ""
    if not how:
        gone = soft_delete(query)
        how = f"ssh stop FAILED; soft-deleted in Gitea: {', '.join(gone) or 'none left'}"
    key = sorted(bad)
    line = ("[Windy Git] OFFSITE RUNNERS CUT OFF (offsite guard, Hub #121): " + "; ".join(key)
            + f". Action: {how}. Back only after the cause is gone and Hub reads it.")
    if load_state().get("posted") != key and post(line):
        save_state({"posted": key})
    print(f"offsite guard: CUT OFF ({'; '.join(key)}; {how})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
