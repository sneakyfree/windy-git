#!/usr/bin/env python3
"""Nightly merge audit for repos GitHub cannot protect (Hub decision A2, 2026-10-10).

windy-vault and windy-contracts are private on a plan without branch protection, and every
lane shares one GitHub login, so GitHub can neither require a check nor a review. Instead:
Hub/Boss post `windy-hub/approved` on the exact HEAD sha they reviewed, Windy Git posts
`windy-git/check/*`, and this audit flags every PR merged to main whose head lacked either,
plus any commit on main that arrived without a PR. It detects; it cannot prevent.

Runs on Windy 0 from the nightly sweep (gh CLI). Prints one line per finding, then
`merge audit: <n> merged, <m> flagged`. Exit 1 on any finding or API error.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys

OWNER = "sneakyfree"
REPOS = ("windy-vault", "windy-contracts")
APPROVAL = "windy-hub/approved"
CHECK_PREFIX = "windy-git/check/"
# Merges before the rule existed are not judged by it.
RULE_START = "2026-10-10T23:30:00Z"
WINDOW_H = 26


def gh(path: str):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(out.stdout or "null")


def latest_states(statuses: list[dict]) -> dict[str, str]:
    """GitHub lists statuses newest first: the first per context is the current one."""
    cur: dict[str, str] = {}
    for s in statuses or []:
        cur.setdefault(s["context"], s["state"])
    return cur


def problems(states: dict[str, str]) -> list[str]:
    out = []
    if states.get(APPROVAL) != "success":
        out.append(f"no {APPROVAL}=success")
    checks = {k: v for k, v in states.items() if k.startswith(CHECK_PREFIX)}
    if not checks:
        out.append("no windy-git/check status")
    elif any(v != "success" for v in checks.values()):
        out.append("windy-git/check not green: " + ", ".join(sorted(k for k, v in checks.items() if v != "success")))
    return out


def audit(repo: str, since: str, api=gh) -> tuple[int, list[str]]:
    commits = api(f"repos/{OWNER}/{repo}/commits?sha=main&since={since}&per_page=100") or []
    seen: set[int] = set()
    merged, flags = 0, []
    for c in commits:
        prs = [p for p in (api(f"repos/{OWNER}/{repo}/commits/{c['sha']}/pulls") or []) if p.get("merged_at")]
        if not prs:
            flags.append(f"{repo}@{c['sha'][:7]}: on main without a merged PR (direct push)")
            continue
        for p in prs:
            if p["number"] in seen or p["merged_at"] < since:
                continue
            seen.add(p["number"])
            merged += 1
            head = p["head"]["sha"]
            states = latest_states(api(f"repos/{OWNER}/{repo}/commits/{head}/statuses?per_page=100"))
            why = problems(states)
            if why:
                flags.append(f"{repo}#{p['number']} (head {head[:7]}): {'; '.join(why)}")
    return merged, flags


def main() -> int:
    now = dt.datetime.now(dt.UTC)
    since = max((now - dt.timedelta(hours=WINDOW_H)).strftime("%Y-%m-%dT%H:%M:%SZ"), RULE_START)
    merged, flags = 0, []
    try:
        for repo in REPOS:
            m, f = audit(repo, since)
            merged += m
            flags += f
    except (subprocess.SubprocessError, OSError, ValueError, KeyError) as e:
        print(f"merge audit: ERROR ({type(e).__name__})")
        return 1
    for line in flags:
        print(f"  FLAG {line}")
    print(f"merge audit: {merged} merged, {len(flags)} flagged (since {since})")
    return 1 if flags else 0


if __name__ == "__main__":
    sys.exit(main())
