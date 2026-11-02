#!/usr/bin/env python3
"""Red-main alarm (Boss 11-02): a default-branch status that stays red for more than a day gets said.

windy-pro-mobile's main failed windy-git/secret-guard on every commit from at least 10-20 and nobody
saw it for 13 days. Now, every RUN_EVERY (systemd timer), for each repo the bridge serves: read the
default-branch head and its statuses (the newest per context). A context in failure/error starts a
clock (persisted per repo + context, across new head commits). Past THRESHOLD_S, ONE BOARD line names
the repo, context, owner lane and how long; then once a day while it stays red. Success clears it;
pending keeps the clock (a re-run that fails again is the same red). On FIRST sight the clock starts
at the current head's failing status (GitHub keeps no per-context history across commits), so a red
that already spans older commits is undercounted once, by at most a day. Reads only; budget floor like the
bridge. Output for windy-job --expect: "red main: none" or "red main: N red > 24 h (BOARD)".

  sudo python3 scripts/red_main.py      (env: /etc/windygit/sync.env, as the bridge)
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cancel_superseded as cs  # noqa: E402  (the BOARD line: Windy 0, else the fallback board)
import guards_report as gr  # noqa: E402  (owner lanes)
import pr_status_bridge as b  # noqa: E402  (same token, helpers and repo list)

STATE = Path(os.environ.get("RED_MAIN_STATE", "/var/lib/windygit/red-main.json"))
MIN_BUDGET = int(os.environ.get("RED_MAIN_MIN_BUDGET", "1500"))
THRESHOLD_S = 24 * 3600
REPEAT_S = 24 * 3600 - 15 * 60      # "once a day" with room for timer jitter
BRANCH_TTL_S = 86400
RED = ("failure", "error")

# guards_report.OWNERS routes guard findings; it doesn't cover every bridged repo, so the alarm adds
# the rest (lane session names). An owner not known for sure says so instead of guessing.
OWNERS = {**gr.OWNERS,
          "windy-text": "Windy Text", "windy-text-site": "Windy Text", "windy-hand-site": "Windy Hand",
          "windy-calendar-site": "Windy Calender", "windy-vault": "Windy Vault", "windy-uptime": "Windy Git",
          "windy-pro-mobile": "Windy Mobile (mini)", "windy-mind-acp": "Windy Mind", "windy-mind-site": "Windy Mind",
          "windy-admin": "Windy Admin Panel", "Windy-Clone-site": "Windy Clone", "windyword-site": "Windy Word",
          "windy-mobile": "Windy Mobile (Cell Phone)", "windycloud-site": "Windy Cloud",
          "eternitas-site": "Eternitas", "eternitas-authenticator": "Eternitas"}


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def newest_by_context(statuses: list[dict]) -> dict[str, dict]:
    """GitHub lists statuses newest first: the first one per context is its state now."""
    out: dict[str, dict] = {}
    for s in statuses or []:
        out.setdefault(s.get("context", ""), s)
    return out


def step(state: dict, repo: str, sha: str, statuses: list[dict], now: float) -> list[str]:
    """Update the clocks for one repo's default head; return the BOARD lines due now."""
    reds = state.setdefault("reds", {})
    lines = []
    for ctx, s in sorted(newest_by_context(statuses).items()):
        key = f"{repo}|{ctx}"
        st = s.get("state")
        if st == "success":
            reds.pop(key, None)
            continue
        if st not in RED:
            continue                     # pending: keep any clock as it is
        r = reds.get(key)
        if r is None:
            try:
                since = min(_ts(s.get("created_at") or ""), now)
            except ValueError:
                since = now
            r = reds[key] = {"since": since, "last_post": 0.0}
        r["sha"] = sha
        age = now - r["since"]
        if age > THRESHOLD_S and now - r.get("last_post", 0.0) >= REPEAT_S:
            r["last_post"] = now
            day = time.strftime("%Y-%m-%d %H:%MZ", time.gmtime(r["since"]))
            lines.append(f"[Windy Git] RED MAIN: {repo} default branch, {ctx} = {st} since {day} "
                         f"({age / 3600:.0f} h), head {sha[:8]}. Owner: {OWNERS.get(repo, 'unknown (Boss routes)')}. "
                         "Daily until green (Boss 11-02).")
    return lines


def load() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def main(post=cs.board) -> int:
    st, body = b.github("GET", "/rate_limit")
    try:
        budget = int(body["resources"]["core"]["remaining"]) if st == 200 else 0
    except (KeyError, TypeError, ValueError):
        budget = 0
    if budget < MIN_BUDGET:
        print(f"red main: skipped (GitHub API budget {budget} < {MIN_BUDGET})")
        return 0
    now = time.time()
    state = load()
    branches = state.setdefault("branches", {})
    lines, red_now, failed = [], 0, []
    for repo in b.REPOS:
        try:
            c = branches.get(repo)
            if not c or now - c.get("read", 0) > BRANCH_TTL_S:
                code, rp = b.github("GET", f"/repos/{b.GH_OWNER}/{repo}")
                if code != 200:
                    failed.append(repo)
                    continue
                c = branches[repo] = {"name": rp["default_branch"], "read": now}
            code, br = b.github("GET", f"/repos/{b.GH_OWNER}/{repo}/branches/{c['name']}")
            if code != 200:
                failed.append(repo)
                continue
            sha = br["commit"]["sha"]
            code, comb = b.github("GET", f"/repos/{b.GH_OWNER}/{repo}/commits/{sha}/status?per_page=100")
            if code != 200:
                failed.append(repo)
                continue
            lines += step(state, repo, sha, comb.get("statuses") or [], now)
        except Exception as e:  # noqa: BLE001 - one repo's failure must not hide the others
            failed.append(f"{repo} ({type(e).__name__})")
    red_now = sum(1 for r in state.get("reds", {}).values() if now - r["since"] > THRESHOLD_S)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True))
    tmp.replace(STATE)
    for line in lines:
        print("  " + line)
        post(line)
    if failed:
        print(f"  unreadable this run (checked again next run): {', '.join(failed)}")
    print("red main: none" if not red_now else f"red main: {red_now} red > 24 h (BOARD)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
