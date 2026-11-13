#!/usr/bin/env python3
"""Queue order: fully-approved PRs first (Boss 10-28 09:18Z).

Stamped windy-pro PRs waited up to 2 h behind PRs nobody had reviewed. Now, after each sync
pass: jobs of a PR whose head already carries all its required approvals go to the front,
oldest first; everything else stays FIFO behind them; main pushes and schedules are never
moved. "At most one at a time per runner slot": each pass keeps up to SLOTS approved jobs at the
front, so approvals jump the line without starving everything else.
Cheap on the GitHub quota (shared with stamps): it looks only at heads that have WAITING PR jobs,
a head seen fully approved is cached for APPROVAL_TTL_S (an approval CAN be withdrawn: a later
failure or pending status on the same context wins, so the head is re-read after the TTL, Hub
#96 LOW), and it skips when fewer than MIN_BUDGET calls are left. Logged; one BOARD line per pass when it moves anything.
Required approvals per head: needs() below (the LESS CEREMONY rules at the end of this note). An entry that is a
tuple is ANY ONE of its contexts: the 2 Traveler repos take Agent's read in place of the Hub's (Boss 11-09 05:57:38Z,
per his REVIEW CAPACITY ruling 11-04 22:00:57Z; not fleet-wide), and windy-pro takes Admin's read in place of the
Hub's (Boss 11-09 06:45:55Z: the Hub never stamps its own PRs). This only orders the queue: it merges nothing.
LESS CEREMONY (Boss ALL LANES 2026-11-13T01:44:24Z (1)(2); 05:07:40Z; 13:48:46Z): "approved for queue order" is
  (a) a head whose WHOLE PR diff is docs only (TODO.md, README*, docs/: docs_only's strict list, read from git, never a
      title or label) with secret-guard, compute-guard and ci-hygiene success BY NAME at that head;
  (b) any other head with its ONE reader stamp (Hub; windy-pro: Hub or Admin; the 2 Traveler repos: Hub or Agent).
  windy-boss/approved is required ONLY on BOSS_REPOS (windy-git, which holds the guards, and kit-army-config, the
  lockbox) and on a PR whose title carries BOSS ASK; there a docs-only head needs Boss's stamp (windy-git has no guards).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cancel_superseded as cs  # noqa: E402  (same DB helper and BOARD line)
import docs_only as do  # noqa: E402  (the strict docs list and the head diff)
import pr_status_bridge as b  # noqa: E402  (same GitHub helper and token)

SLOTS = int(os.environ.get("APPROVED_FIRST_SLOTS", "2"))
MIN_BUDGET = int(os.environ.get("APPROVED_FIRST_MIN_BUDGET", "1500"))
APPROVAL_TTL_S = int(os.environ.get("APPROVED_FIRST_TTL_S", "1800"))
STATE = Path(os.environ.get("APPROVED_FIRST_STATE", "/var/lib/windygit/approved-heads.json"))
LOG = Path(os.environ.get("APPROVED_FIRST_LOG", "/var/log/windygit/approved-first.log"))
HUB = "windy-hub/approved"
BOSS = "windy-boss/approved"
HUB_OR_AGENT = (HUB, "windy-agent/approved")   # any one: the non-author reader
HUB_OR_ADMIN = (HUB, "windy-admin/approved")
READER = {"windy-traveler": HUB_OR_AGENT, "windytraveler-site": HUB_OR_AGENT, "windy-pro": HUB_OR_ADMIN}
GUARDS = ("windy-git/secret-guard", "windy-git/compute-guard", "windy-git/ci-hygiene")
BOSS_REPOS = frozenset({"windy-git", "kit-army-config"})


def head_paths(repo: str, sha: str) -> list[str] | None:
    """The PR head's whole diff against main (None = unreadable: then it is treated as code)."""
    return do.changed_paths(repo, sha, "pull_request")


def needs(repo: str, sha: str, boss_ask: bool = False) -> tuple:
    """The contexts that make this head approved for queue order. Each entry: a context, or a tuple = any one."""
    boss = repo in BOSS_REPOS or boss_ask
    paths = head_paths(repo, sha)
    docs = bool(paths) and all(do.is_docs_path(p) for p in paths)
    if docs:
        return (BOSS,) if boss else GUARDS
    return (READER.get(repo, HUB),) + ((BOSS,) if boss else ())

WAITING_HEADS_SQL = """
select p.name, j.commit_sha, min(j.created), bool_or(upper(coalesce(r.title, '')) like '%BOSS ASK%')
from action_run_job j join action_run r on r.id = j.run_id join repository p on p.id = j.repo_id
where j.status = 5 and j.task_id = 0 and r.ref like 'refs/pull/%/head'
  and r.event in ('pull_request', 'pull_request_sync')
group by p.name, j.commit_sha order by 3;
"""


def approved(repo: str, sha: str, cache: dict[str, float], now: float | None = None, boss_ask: bool = False) -> bool:
    """cache: sha -> when it was last READ fully approved. Fresh entries are trusted; older ones
    are re-read, and a head no longer fully approved leaves the cache."""
    now = time.time() if now is None else now
    t = cache.get(sha, float("-inf"))
    if t <= now and now - t < APPROVAL_TTL_S:   # a FUTURE read time (corrupt file, clock step back) is expired
        return True
    cache.pop(sha, None)
    need = needs(repo, sha, boss_ask)
    newest: dict[str, str] = {}                 # statuses come newest first: a later failure wins
    for s in b.commit_statuses(repo, sha):
        newest.setdefault(s["context"], s.get("state", ""))
    if all(any(newest.get(x) == "success" for x in ((c,) if isinstance(c, str) else c)) for c in need):
        cache[sha] = now
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
        raw = json.loads(STATE.read_text())
        # the old format (a list of shas, no read times) reads as expired: every head is re-read once
        cache = {k: float(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
    except (OSError, ValueError, TypeError, AttributeError):
        cache = {}
    try:
        heads = query(WAITING_HEADS_SQL)
        eligible = [(h[0], h[1]) for h in heads
                    if b.SAFE_SHA.match(h[1]) and approved(h[0], h[1], cache, boss_ask=len(h) > 3 and h[3] == "t")]
        moved = query(move_sql([sha for _, sha in eligible], SLOTS)) if eligible else []
    except Exception as e:  # noqa: BLE001 - never fails the sync
        print(f"  approved-first: skipped ({type(e).__name__})")
        return 0
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        live = {h[1] for h in heads}
        STATE.write_text(json.dumps({k: v for k, v in cache.items() if k in live}, sort_keys=True))
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
