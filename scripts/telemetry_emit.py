#!/usr/bin/env python3
"""Emit Windy Git CI telemetry to admin.windyword.ai (Windy Telemetry 40's ledger).

Runs on Veron after every sync (root; reads the gitea DB via `docker exec`).
Shapes are declared with Telemetry 40 (2026-09-23) — do not add keys or enum
values without re-declaring: a declared family quarantines any row that
doesn't match.

  ci.run          one row per FINISHED job, exactly once — cursor on
                  (finish time, job id) in STATE; jobs finish out of id order
  service.health  one row per invocation: CI plane counts for the interval

Privacy: ids, names of repos/jobs, codes, counts, durations. No commit
messages, no logs, no author names.

  --dry-run   print the batch instead of posting (and don't advance STATE)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

INGEST = os.environ.get("TELEMETRY_INGEST_URL", "https://admin.windyword.ai/v1/events")
TOKEN = os.environ.get("WINDYGIT_TELEMETRY_TOKEN", "")
STATE = os.environ.get("TELEMETRY_STATE", "/var/lib/windy-git/telemetry-state.json")
PLATFORM, SERVICE = "windy-git", "ci"
OUTCOME = {1: "success", 2: "failure", 3: "cancelled", 4: "skipped"}
EVENTS = {"push", "pull_request", "pull_request_sync", "schedule", "workflow_dispatch"}
RUNNERS_EXPECTED = 6


def sql(query: str) -> list[dict]:
    """Rows as dicts, via psql's json_agg — no driver needed on the host."""
    wrapped = f"select coalesce(json_agg(t), '[]'::json) from ({query}) t;"
    out = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "windy-git-db-1",
            "sh",
            "-c",
            'psql -U "$POSTGRES_USER" -d gitea -At -v ON_ERROR_STOP=1',
        ],
        input=wrapped,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return json.loads(out or "[]")


def load_state() -> dict:
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat().replace("+00:00", "Z")


# ---- push velocity: DETECT + ALERT ONLY (G3.4, 2026-09-23) -----------------
# `git push` goes straight to Gitea and never touches our API, so throttle.py
# cannot see it (NOT_ENFORCED_HERE). Gitea's own `action` table does record
# every push, so we read it here, emit `forge.push_velocity` when an account
# crosses a threshold, and let Telemetry Boss's detector page. Nothing here sits
# in the push path; nothing is ever refused (orchestrator, 09-23).
#
# Thresholds = the STANDARD-band bases from config.py (500 pushes/day; the
# force-push base of 10/day is used for ref deletes, the closest thing we can
# see). EI band multipliers are NOT applied: a platinum agent over 500/day is
# still flagged, for a human to look at, not blocked. Gitea records no
# "forced" flag, so force pushes cannot be told apart from pushes: named, not
# guessed.
PV_RULES = (  # (rule, row key, window_s, threshold)
    ("pushes_1h", "p1h", 3600, 60),
    ("pushes_24h", "p24h", 86400, 500),
    ("ref_deletes_24h", "d24h", 86400, 10),
)
# The GitHub -> Windy Git sync pushes as windyadmin every 5 min, by design.
PV_EXEMPT = {"windyadmin"}
# Gitea op_type: 5 commit push, 9 tag push, 16 tag delete, 17 branch delete.
# One action row per WATCHER is written for each push; user_id = act_user_id
# keeps exactly the actor's own copy.
PV_QUERY = """
    select a.act_user_id as uid, u.lower_name as login,
           count(*) filter (where a.op_type in (5, 9) and a.created_unix > {h1}) as p1h,
           count(*) filter (where a.op_type in (5, 9)) as p24h,
           count(*) filter (where a.op_type in (16, 17)) as d24h,
           count(distinct a.repo_id) as repos
      from action a join "user" u on u.id = a.act_user_id
     where a.created_unix > {h24} and a.user_id = a.act_user_id
       and a.op_type in (5, 9, 16, 17)
     group by 1, 2"""


def passport_from_login(login: str) -> str | None:
    """agent-et26abcd1234 -> ET26-ABCD-1234 (repos.py _owner_login, reversed)."""
    m = re.fullmatch(r"agent-([a-z0-9]{4})([a-z0-9]{4})([a-z0-9]{4})", login)
    return "-".join(g.upper() for g in m.groups()) if m else None


def push_velocity_events(rows: list[dict], now: float, alerted: dict) -> tuple[list[dict], dict]:
    """(events, alerted') — one row per account per rule per window while over.

    `alerted` maps "<uid>:<rule>" -> epoch of the last row. An account still over
    the line is re-reported once per window, not every 5 minutes; one that drops
    back under is forgotten, so a later burst reports again.
    """
    events, keep = [], {}
    for r in rows:
        login = str(r["login"])
        if login in PV_EXEMPT:
            continue
        agent = login.startswith("agent-")
        for rule, key, window, limit in PV_RULES:
            n = int(r[key])
            if n <= limit:
                continue
            k = f"{r['uid']}:{rule}"
            last = alerted.get(k)
            if last is not None and now - float(last) < window:
                keep[k] = last
                continue
            keep[k] = now
            ev = {
                "ts": iso(now),
                "platform": PLATFORM,
                "service": "forge",
                "event_type": "forge.push_velocity",
                "actor_type": "agent" if agent else "human",
                "metadata": {
                    "rule": rule,
                    "window_s": window,
                    "count": n,
                    "threshold": limit,
                    "repos": int(r["repos"]),
                    "gitea_user_id": int(r["uid"]),
                },
            }
            passport = passport_from_login(login) if agent else None
            if passport:  # unknown is absent, never invented (I-12)
                ev["actor_id"] = passport
            events.append(ev)
    return events, keep


def main() -> int:
    dry = "--dry-run" in sys.argv
    state = load_state()
    now = time.time()
    since = float(state.get("last_ts", now - 300))
    # Cursor = (finish time, job id), NOT job id alone: jobs finish out of id
    # order, so an id high-water mark silently drops every long job that started
    # before the mark and finished after it (Telemetry Boss caught this: 43
    # finished vs 8 ci.run rows). Finish time = stopped, or updated for jobs
    # Gitea/the janitor skipped without a stop time.
    if "last_fin" in state:
        last_fin, last_id = int(state["last_fin"]), int(state["last_id"])
    else:  # first run or pre-cursor state: start now, never replay history
        last_fin, last_id = int(state.get("last_ts", now)), 0
    cutoff = int(now) - 5  # leave the current second alone; late writers land next run
    FIN = "coalesce(nullif(j.stopped, 0), j.updated)"

    jobs = sql(f"""
        select j.id, j.name as job, j.status, j.started, j.stopped, {FIN} as fin,
               p.lower_name as repo, p.default_branch, r.workflow_id, r.event,
               r.ref, r.index as run, left(r.commit_sha, 7) as sha
          from action_run_job j
          join action_run r on r.id = j.run_id
          join repository p on p.id = r.repo_id
         where j.status in (1, 2, 3, 4)
           and ({FIN}, j.id) > ({last_fin}, {last_id})
           and {FIN} <= {cutoff}
         order by {FIN}, j.id
         limit 2000""")

    try:  # posted_to_github: the bridge's own rules, from the same checkout
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import pr_status_bridge as bridge
    except Exception:  # noqa: BLE001
        bridge = None

    events = []
    for j in jobs:
        ref = j["ref"] or ""
        if ref.startswith("refs/pull/"):
            kind = "pr"
        elif ref == f"refs/heads/{j['default_branch']}":
            kind = "default"
        else:
            kind = "other"
        # Gitea stores whole seconds; duration_ms is seconds*1000 (so 10000 = 10 s).
        dur = (j["stopped"] - j["started"]) * 1000 if j["started"] and j["stopped"] else None
        ev = {
            "ts": iso(j["stopped"]),
            "platform": PLATFORM,
            "service": SERVICE,
            "event_type": "ci.run",
            "actor_type": "system",
            "metadata": {
                "repo": j["repo"],
                "workflow": (j["workflow_id"] or "").removesuffix(".yml").removesuffix(".yaml"),
                "job": j["job"],
                "outcome": OUTCOME[j["status"]],
                "event": j["event"] if j["event"] in EVENTS else "other",
                "branch_kind": kind,
                "run": j["run"],
                "sha": j["sha"],
            },
        }
        if dur is not None and dur >= 0:
            ev["duration_ms"] = int(dur)
        if bridge is not None:
            wf = ev["metadata"]["workflow"]
            ev["metadata"]["posted_to_github"] = bool(
                j["repo"] in {r.lower() for r in bridge.REPOS}
                and kind in ("default", "pr")
                and j["status"] != 4
                and not bridge.NO_DAEMON_JOB.search(j["job"])
                and f"{wf}/{j['job']}" not in bridge.NON_BLOCKING.get(j["repo"], set())
            )
        events.append(ev)

    # --- heartbeat: counts since the previous invocation --------------------
    # Interval counts come from EXACTLY the rows emitted above, so
    # sum(jobs_finished) over any window == count(ci.run) in it, by construction.
    h = sql(f"""
        select
          (select count(*) from action_run_job where status in (5, 7)) as jobs_waiting,
          (select count(*) from action_run_job where status = 6) as jobs_running,
          (select count(*) from action_runner where deleted is null and last_online >= {int(now) - 120}) as runners_online,
          (select coalesce(extract(epoch from now())::bigint - min(created), 0)
             from action_run_job where status in (5, 7)) as oldest_waiting_s""")[0]
    h["jobs_finished"] = len(jobs)
    h["jobs_failed"] = sum(1 for j in jobs if j["status"] == 2)
    h["jobs_cancelled"] = sum(1 for j in jobs if j["status"] == 3)
    meta = {k: int(v) for k, v in h.items()}
    meta["interval_s"] = int(now - since)  # ecosystem-standard key
    # UPDATE 7. Quarantines seen on earlier sends (the ledger answers 202 anyway)
    # are carried in the state file until a heartbeat reports them. Dropped is 0
    # by construction: a failed send keeps the cursor and the spool, so every row
    # is re-sent next run (a partial failure can duplicate, never lose).
    meta["telemetry_quarantined"] = int(state.get("quarantined_unreported", 0))
    meta["telemetry_dropped"] = 0
    for k in ("repos_synced", "repos_sync_failed", "statuses_posted", "bridge_errors"):
        v = os.environ.get(f"TELEMETRY_{k.upper()}")
        if v is not None and v.isdigit():  # absent = couldn't count; never invent 0
            meta[k] = int(v)
    events.append(
        {
            "ts": iso(now),
            "platform": PLATFORM,
            "service": SERVICE,
            "event_type": "service.health",
            "actor_type": "system",
            "metadata": meta,
        }
    )

    pv_rows = sql(PV_QUERY.format(h1=int(now) - 3600, h24=int(now) - 86400))
    pv_events, pv_alerted = push_velocity_events(pv_rows, now, state.get("pv_alerted", {}))
    for e in pv_events:
        m = e["metadata"]
        print(f"[telemetry] WARNING push velocity: gitea user {m['gitea_user_id']} "
              f"{m['rule']} = {m['count']} > {m['threshold']}")
    events += pv_events

    # ci.job_cancelled: spooled by the janitor (cancel_unrunnable.sh), one JSON per job.
    spool = os.environ.get("JANITOR_SPOOL", "/var/lib/windy-git/janitor-cancelled.jsonl")
    spooled = 0
    try:
        with open(spool) as f:
            for line in f:
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                events.append(
                    {
                        "ts": iso(now),
                        "platform": PLATFORM,
                        "service": SERVICE,
                        "event_type": "ci.job_cancelled",
                        "actor_type": "system",
                        "metadata": {
                            k: m[k]
                            for k in ("repo", "workflow", "job", "reason", "runs_on", "waited_s")
                        },
                    }
                )
                spooled += 1
    except OSError:
        pass

    if dry:
        out = os.environ.get("TELEMETRY_DRY_OUT")
        if out:
            with open(out, "w") as f:
                json.dump({"events": events}, f)
        else:
            print(json.dumps({"events": events}, indent=1)[:4000])
        print(f"[telemetry] DRY RUN: {len(events)} events ({len(jobs)} ci.run)")
        return 0
    if not TOKEN:
        print("[telemetry] WINDYGIT_TELEMETRY_TOKEN unset — not sending (not a failure)")
        return 0

    quarantined = 0
    for i in range(0, len(events), 500):
        req = urllib.request.Request(
            INGEST,
            data=json.dumps({"events": events[i : i + 500]}).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Content-Type": "application/json",
                "User-Agent": "windy-git-telemetry/1",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
                if r.status >= 300:
                    raise urllib.error.HTTPError(
                        INGEST, r.status, body[:300].decode(errors="replace"), None, None
                    )
            try:
                resp = json.loads(body or b"{}")
            except ValueError:
                resp = {}
            q = resp.get("quarantined") if isinstance(resp, dict) else None
            if isinstance(q, int) and q > 0:
                quarantined += q
                reasons = "; ".join(map(str, resp.get("rejections") or [])) or "no reason given"
                print(f"[telemetry] WARNING {q} row(s) QUARANTINED by the ledger: {reasons}")
        except urllib.error.HTTPError as e:
            print(f"[telemetry] FAILED ingest HTTP {e.code}: {e.read()[:200]!r}")
            return 1  # state NOT advanced: the same rows retry next run
        except urllib.error.URLError as e:
            print(f"[telemetry] FAILED ingest: {e.reason}")
            return 1

    if spooled:
        open(spool, "w").close()  # only after every batch was accepted
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    new_fin, new_id = (jobs[-1]["fin"], jobs[-1]["id"]) if jobs else (last_fin, last_id)
    with open(STATE + ".tmp", "w") as f:
        json.dump(
            {"last_fin": new_fin, "last_id": new_id, "last_ts": now,
             "quarantined_unreported": quarantined, "pv_alerted": pv_alerted},
            f,
        )
    os.replace(STATE + ".tmp", STATE)
    print(f"[telemetry] sent {len(events)} events ({len(jobs)} ci.run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
