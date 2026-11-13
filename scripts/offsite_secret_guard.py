#!/usr/bin/env python3
"""Offsite runner guard (Hub #121 condition, 11-02): the CI runners on the house machines (Null 0:
null0-*, Windy 0: w0-*) may only ever serve secret-free repos, and that must stay true AFTER
registration, not just at it.

Gitea hands every Actions secret of a repo (and of its owner, and instance-wide ones) to every job
of that repo. register.sh refuses a repo with secrets, but a lane can add one later, and nothing
would notice. Every 10 minutes (windygit-offsite-guard.timer, on Veron, as root), for every live
offsite runner (name null0-* or w0-*):
  * it must be scoped to exactly ONE repo (repo_id > 0); a global or owner-wide one is a violation;
  * that repo must hold 0 Actions secrets at repo, owner and instance level;
  * the egress unit of each host that has runners must not be in a failed state (its filter broke).
On ANY violation it cuts the offsite runners off at once, fail closed:
  1. ssh each host that has runners and stop them (reversible), then READ BACK that none runs;
     a stop that leaves one running, or that matched fewer runners than there are live rows while some ran,
     is a failed stop; a host with NONE running before reads as stopped (Boss 2026-11-12T08:45:27Z (5)). Null 0:
     `docker compose -p windy-git-runner-offsite stop runner-1 runner-2 runner-3`; Windy 0: stop the
     user units act-runner@*.service of the windygit-ci user;
  2. if a host's stop fails, soft-delete THAT host's runner rows in Gitea (null0-* or w0-*, never the other
     host's), so they can't fetch jobs (they must
     then be re-registered through register.sh, which re-checks the secrets).
A host whose egress unit cannot be read prints "offsite guard: UNKNOWN" (the heartbeat alerts) and
becomes a violation after 3 passes in a row. Runner names: null0-N is fixed by the compose file and
register.sh; w0-N is set only by the Windy 0 registration (a follow-up PR adds its script); a row named
anything else is not watched by this guard.
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
WINDY0 = os.environ.get("WINDY0_SSH", "eth-windy0")
LANE_USER = os.environ.get("BOARD_USER", "user1-gpu")
PROJECT = "windy-git-runner-offsite"
# runner-name prefix -> (ssh target, egress unit, stop command, label). Every stop command prints
# "<running before> <running after>" as its last line, so a stop that matched NOTHING (a glob with no
# loaded unit exits 0) cannot pass for a stop (Hub #133 MED-1). Windy 0 stops only the runner units of
# the windygit-ci user: nothing else on that host is touched; the uid is resolved on the host.
N0_COUNT = "sudo -n docker ps --filter 'name=offsite-runner-[0-9]' --format x | wc -l"
W0_USER = "n() { sudo -n -u windygit-ci env XDG_RUNTIME_DIR=/run/user/$(id -u windygit-ci) systemctl --user \"$@\"; }"
W0_COUNT = "n list-units 'act-runner@*' --state=active --no-legend | wc -l"
HOSTS = {
    "null0-": (NULL0, "windygit-ci-egress-offsite.service",
               f"b=$({N0_COUNT}); sudo -n docker compose -p {PROJECT} stop runner-1 runner-2 runner-3 >/dev/null 2>&1; "
               f"a=$({N0_COUNT}); echo \"$b $a\"", "Null 0"),
    "w0-": (WINDY0, "windygit-ci-egress.service",
            f"{W0_USER}; b=$({W0_COUNT}); n stop 'act-runner@*.service' >/dev/null 2>&1; a=$({W0_COUNT}); echo \"$b $a\"",
            "Windy 0"),
}
UNKNOWN_LIMIT = 3  # passes (10 min apart) a host's egress unit may be unreadable before that is a violation

RUNNERS_SQL = """
select r.id, r.name, r.owner_id, r.repo_id, coalesce(p.name, ''),
  (select count(*) from secret s where (r.repo_id > 0 and s.repo_id = r.repo_id)
     or (s.repo_id = 0 and s.owner_id = coalesce(p.owner_id, r.owner_id) and s.owner_id > 0)
     or (s.owner_id = 0 and s.repo_id = 0))
from action_runner r left join repository p on p.id = r.repo_id
where coalesce(r.deleted, 0) = 0 and (r.name like 'null0-%' or r.name like 'w0-%')
order by r.id;
"""


def violations(rows: list[list[str]]) -> list[str]:
    """Pure: one reason per bad runner row (id, name, owner_id, repo_id, repo, secrets)."""
    out = []
    for row in rows:
        if len(row) != 6:  # a '|' in a runner name shifts the columns: never read such a row as clean
            out.append(f"runner row with {len(row)} fields instead of 6 (a '|' in a name?): {'|'.join(row)[:60]!r}")
            continue
        rid, name, _owner, repo_id, repo, secrets = row
        if not repo_id.isdigit() or int(repo_id) <= 0:
            out.append(f"{name} (id {rid}) is not scoped to one repo")
        elif not secrets.isdigit() or int(secrets) > 0:
            out.append(f"{name} (id {rid}) serves {repo or 'repo ' + repo_id}, which now sees {secrets} Actions secret(s)")
    return out


def ssh(cmd: str, run=subprocess.run, host: str = NULL0) -> subprocess.CompletedProcess:
    return run(["runuser", "-u", LANE_USER, "--", "timeout", "40", "ssh", "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=8", host, cmd], capture_output=True, text=True, timeout=60)


def families(rows: list[list[str]]) -> list[str]:
    """The HOSTS prefixes that have at least one live runner row."""
    return [p for p in HOSTS if any(len(r) > 1 and r[1].startswith(p) for r in rows)]


def egress_failed(run=subprocess.run, prefix: str = "null0-") -> bool | None:
    """True if that host's egress unit is missing or failed; False if loaded and healthy; None if the
    host can't be asked (ssh down, timeout, any rc other than 0). An unit that is not installed reads
    LoadState=not-found, which is a violation, not a healthy 'inactive' (Hub #133 MED-2)."""
    host, unit, _stop, _label = HOSTS[prefix]
    try:
        r = ssh(f"systemctl show -p LoadState -p ActiveState -p Result {unit}", run, host)
    except (subprocess.SubprocessError, OSError):
        return None
    if r.returncode != 0:
        return None
    kv = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
    if kv.get("LoadState") != "loaded":
        return True
    return kv.get("ActiveState") not in ("active", "inactive", "activating", "reloading") or kv.get("Result") != "success"


def stopped(r, expected: int) -> bool:
    """A stop counts only if it exited 0 AND the read-back shows none running after, AND either >= `expected`
    runners were running before (Hub #133 MED-1: a stop that matched fewer than the live rows is not a stop) or
    NONE was running before: a host already at 0 reads as STOPPED (Boss RULED 2026-11-12T08:45:27Z (5), after a
    hand stop at 08:32:19Z made the 08:39:52Z pass read '0 0' as a failed stop)."""
    if r.returncode != 0:
        return False
    try:
        before, after = (int(x) for x in r.stdout.split()[-2:])
    except ValueError:
        return False
    return after == 0 and (before >= expected or before == 0)


def failed_stops(run=subprocess.run, prefixes: list[str] | None = None, rows: list[list[str]] | None = None) -> list[str]:
    """Stop the runners on every host in `prefixes` (default: all); return the prefixes whose stop was NOT read
    back as done (each host on its own: one host's failed stop never touches the other's rows, Hub 08:44:09Z)."""
    failed = []
    for prefix in (prefixes if prefixes is not None else list(HOSTS)):
        host, _unit, stop, _label = HOSTS[prefix]
        expected = sum(1 for r in (rows or []) if len(r) > 1 and r[1].startswith(prefix))
        try:
            ok = stopped(ssh(stop, run, host), expected)
        except (subprocess.SubprocessError, OSError):
            ok = False
        if not ok:
            failed.append(prefix)
    return failed


def stop_runners(run=subprocess.run, prefixes: list[str] | None = None, rows: list[list[str]] | None = None) -> bool:
    """True only if EVERY stop was read back as done."""
    return not failed_stops(run, prefixes, rows)


def soft_delete(query, prefixes: list[str] | None = None) -> list[str]:
    """Soft-delete the live runner rows of the hosts in `prefixes` ONLY (default: every offsite host)."""
    names = [p for p in (prefixes if prefixes is not None else list(HOSTS)) if p in HOSTS]   # only known prefixes
    if not names:
        return []
    cond = " or ".join(f"name like '{p}%'" for p in names)
    rows = query("update action_runner set deleted = extract(epoch from now())::bigint "
                 f"where coalesce(deleted, 0) = 0 and ({cond}) returning id, name;")
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
    fams = families(rows)
    state = load_state()
    unk = dict(state.get("unknown", {}))
    for prefix in fams:
        failed = egress_failed(run, prefix)
        if failed is True:
            bad.append(f"{HOSTS[prefix][3]}'s egress unit ({HOSTS[prefix][1].removesuffix('.service')}) is "
                       "missing or FAILED")
        elif failed is None:
            unk[prefix] = unk.get(prefix, 0) + 1
            if unk[prefix] >= UNKNOWN_LIMIT:
                bad.append(f"{HOSTS[prefix][3]}'s egress unit could not be read for {unk[prefix]} passes in a row")
        else:
            unk.pop(prefix, None)
    unknown_now = [HOSTS[p][3] for p in fams if p in unk]
    if not bad:
        save_state({"unknown": unk} if unk else {})
        if unknown_now:  # not "ok": the heartbeat alerts, but nothing is cut on one blip
            print(f"offsite guard: UNKNOWN ({', '.join(unknown_now)} unreadable, {len(rows)} runner(s) otherwise clean)")
            return 0
        print(f"offsite guard: ok ({len(rows)} offsite runner(s), each repo-scoped and secret-free)")
        return 0
    failed = failed_stops(run, fams, rows)
    done = [p for p in fams if p not in failed]
    parts = (["stopped on " + " and ".join(HOSTS[p][3] for p in done)] if done else [])
    if failed:
        gone = soft_delete(query, failed)
        parts.append(f"ssh stop FAILED on {' and '.join(HOSTS[p][3] for p in failed)}; soft-deleted in Gitea: "
                     f"{', '.join(gone) or 'none left'}")
    how = "; ".join(parts)
    key = sorted(bad)
    line = ("[Windy Git] OFFSITE RUNNERS CUT OFF (offsite guard, Hub #121): " + "; ".join(key)
            + f". Action: {how}. Back only after the cause is gone and Hub reads it.")
    if state.get("posted") != key and post(line):
        save_state({"posted": key, "unknown": unk})
    print(f"offsite guard: CUT OFF ({'; '.join(key)}; {how})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
