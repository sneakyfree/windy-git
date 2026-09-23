#!/usr/bin/env python3
"""Emit Windy Git CI telemetry to admin.windyword.ai (Windy Telemetry 40's ledger).

Runs on Veron after every sync (root; reads the gitea DB via `docker exec`).
Shapes are declared with Telemetry 40 (2026-09-23) — do not add keys or enum
values without re-declaring: a declared family quarantines any row that
doesn't match.

  ci.run          one row per FINISHED job, exactly once (high-water mark on
                  action_run_job.id in STATE)
  service.health  one row per invocation: CI plane counts for the interval

Privacy: ids, names of repos/jobs, codes, counts, durations. No commit
messages, no logs, no author names.

  --dry-run   print the batch instead of posting (and don't advance STATE)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

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
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    dry = "--dry-run" in sys.argv
    state = load_state()
    now = time.time()
    last_job = int(state.get("last_job_id", 0))
    since = float(state.get("last_ts", now - 300))

    if not last_job:
        # First run: start at the current high-water mark rather than replaying
        # a month of history into the ledger as if it happened now.
        last_job = int(sql("select coalesce(max(id),0) as m from action_run_job")[0]["m"])

    jobs = sql(f"""
        select j.id, j.name as job, j.status, j.started, j.stopped,
               p.lower_name as repo, p.default_branch, r.workflow_id, r.event,
               r.ref, r.index as run, left(r.commit_sha, 7) as sha
          from action_run_job j
          join action_run r on r.id = j.run_id
          join repository p on p.id = r.repo_id
         where j.id > {last_job} and j.status in (1, 2, 3, 4) and j.stopped > 0
         order by j.id
         limit 2000""")

    events = []
    for j in jobs:
        ref = j["ref"] or ""
        if ref.startswith("refs/pull/"):
            kind = "pr"
        elif ref == f"refs/heads/{j['default_branch']}":
            kind = "default"
        else:
            kind = "other"
        dur = (j["stopped"] - j["started"]) * 1000 if j["started"] else None
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
        events.append(ev)

    # --- heartbeat: counts since the previous invocation --------------------
    h = sql(f"""
        select
          (select count(*) from action_run_job where stopped >= {int(since)} and status in (1,2,3,4)) as jobs_finished,
          (select count(*) from action_run_job where stopped >= {int(since)} and status = 2) as jobs_failed,
          (select count(*) from action_run_job where stopped >= {int(since)} and status = 3) as jobs_cancelled,
          (select count(*) from action_run_job where status in (5, 7)) as jobs_waiting,
          (select count(*) from action_run_job where status = 6) as jobs_running,
          (select count(*) from action_runner where deleted is null and last_online >= {int(now) - 120}) as runners_online,
          (select coalesce(extract(epoch from now())::bigint - min(created), 0)
             from action_run_job where status in (5, 7)) as oldest_waiting_s""")[0]
    meta = {k: int(v) for k, v in h.items()}
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

    if dry:
        print(json.dumps({"events": events}, indent=1)[:4000])
        print(f"[telemetry] DRY RUN: {len(events)} events ({len(jobs)} ci.run)")
        return 0
    if not TOKEN:
        print("[telemetry] WINDYGIT_TELEMETRY_TOKEN unset — not sending (not a failure)")
        return 0

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
                body = r.read()[:300]
                if r.status >= 300:
                    raise urllib.error.HTTPError(
                        INGEST, r.status, body.decode(errors="replace"), None, None
                    )
        except urllib.error.HTTPError as e:
            print(f"[telemetry] FAILED ingest HTTP {e.code}: {e.read()[:200]!r}")
            return 1  # state NOT advanced: the same rows retry next run
        except urllib.error.URLError as e:
            print(f"[telemetry] FAILED ingest: {e.reason}")
            return 1

    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    new_last = max([j["id"] for j in jobs], default=last_job)
    with open(STATE + ".tmp", "w") as f:
        json.dump({"last_job_id": new_last, "last_ts": now}, f)
    os.replace(STATE + ".tmp", STATE)
    print(f"[telemetry] sent {len(events)} events ({len(jobs)} ci.run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
