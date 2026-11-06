#!/usr/bin/env python3
"""Red-main alarm (Boss 11-02): a default-branch status that stays red for more than a day gets said.

windy-pro-mobile's main failed windy-git/secret-guard on every commit from at least 10-20 and nobody
saw it for 13 days. Now, every 2 h (systemd timer), for each repo the bridge serves: read the
default-branch head and its statuses (the newest per context). A context in failure/error starts a
clock, persisted per repo + context as first_red_at and kept across new head commits. Past
THRESHOLD_S, ONE BOARD line names the repo, context, owner lane and how long; then once a day while
it stays red. Success clears it; pending keeps the clock (a re-run that fails again is the same red).

First sight of a red: the clock is backfilled along main's FIRST-PARENT history (up to HISTORY_MAX,
newest first): first_red_at = the oldest consecutive red status for that context, stopping at the
first commit where it was success or absent; if a limit ends the walk first, the line says "since at
least". A merged PR's own commits are never read: their
PR-mode scans can be green while main is red (Boss 11-02). So a red that started 13 commits ago counts from there.

No silent loss (Hub #112): a line's last_post is stored only after the BOARD write is confirmed. A
failed write prints "BOARD post FAILED", is retried next run, and the run ends on a line windy-job's
--expect does not accept. Only contexts seen THIS run count; a stored clock not seen for
GHOST_S (renamed, removed, repo unbridged) is dropped and printed. Reads only; budget floor like the
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
GHOST_S = 7 * 86400
BRANCH_TTL_S = 86400
HISTORY_MAX = 30
RED = ("failure", "error")

# guards_report.OWNERS routes guard findings; it doesn't cover every bridged repo, so the alarm adds
# the rest (lane session names). An owner not known for sure says so instead of guessing.
OWNERS = {**gr.OWNERS,
          "windy-mind": "Windy Mind",   # gr.OWNERS spells it "WIndy Mind"; lanes grep BOARD for their name
          "windy-text": "Windy Text", "windy-text-site": "Windy Text", "windy-hand-site": "Windy Hand",
          "windy-calendar-site": "Windy Calender", "windy-vault": "Windy Vault", "windy-uptime": "Windy Git",
          "windy-pro-mobile": "Windy Mobile (mini)", "windy-mind-acp": "Windy Mind", "windy-mind-site": "Windy Mind",
          "windy-admin": "Windy Admin Panel", "Windy-Clone-site": "Windy Clone", "windyword-site": "Windy Word",
          "windy-mobile": "Windy Mobile (Cell Phone)", "windycloud-site": "Windy Cloud",
          "eternitas-site": "Eternitas", "eternitas-authenticator": "Eternitas",
          "windy-legal": "Windy Legal", "windy-cfo": "Windy CFO", "windy-board": "Windy Git"}

# A known reading of a red, appended to its line (Boss's read, dated). Never hides the line.
NOTES = {("windytalk", "windy-git/secret-guard"):
         "Boss 11-02: likely header-only (publish-release.sh echoes the BEGIN/END lines around a key "
         "fetched at run time); fix = a secret-guard allow entry for that file (path + kind, with a reason)."}

# A context that is KNOWN red by design is exempt, by exact repo + context name, until a date (Boss 11-04).
# windy-pro's account-server-on-Postgres suite (.github/workflows/account-server-pg.yml) has 148 Postgres-only
# failures that follow-up PRs fix one by one; Hub posts its fail count in its daily BOARD line instead. The
# value is the LAST exempt day (UTC, inclusive); from the next day the alarm fires as for any other red. The
# exemption ends sooner by removing this entry in the PR that makes the job required. Nothing else is exempt:
# every other context in the same repo still alarms.
EXEMPT = {("windy-pro", "windy-git/account-server-pg/test-account-server-pg"): "2026-11-30"}


def exempt(repo: str, ctx: str, now: float) -> bool:
    last = EXEMPT.get((repo, ctx))
    return last is not None and now < _ts(last + "T00:00:00Z") + 86400


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def newest_by_context(statuses: list[dict]) -> dict[str, dict]:
    """GitHub lists statuses newest first: the first one per context is its state now."""
    out: dict[str, dict] = {}
    for s in statuses or []:
        out.setdefault(s.get("context", ""), s)
    return out


def step(state: dict, repo: str, sha: str, statuses: list[dict], now: float,
         history=lambda repo, ctx: None) -> list[tuple[str, str]]:
    """Update the clocks for one repo's default head; return (key, BOARD line) pairs due now.
    `history(repo, ctx)` gives the backfilled first_red_at (or None) on first sight."""
    reds = state.setdefault("reds", {})
    due = []
    for ctx, s in sorted(newest_by_context(statuses).items()):
        key = f"{repo}|{ctx}"
        st = s.get("state")
        if exempt(repo, ctx, now):
            reds.pop(key, None)             # no clock while exempt: the first day after it starts one
            continue
        if st == "success":
            reds.pop(key, None)
            continue
        r = reds.get(key)
        if st not in RED:
            if r is not None:
                r["seen"], r["red_now"] = now, False      # pending: keep the clock, not red right now
            continue
        if r is None:
            try:
                since = min(_ts(s.get("created_at") or ""), now)
            except ValueError:
                since = now
            back = history(repo, ctx)
            exact = True
            if back is not None:
                when, exact = back if isinstance(back, tuple) else (back, True)
                if when is not None:            # (None, False): the walk read nothing; since stays, marked inexact
                    since = min(since, when)
            r = reds[key] = {"since": since, "last_post": 0.0, "exact": exact}
        r["sha"], r["seen"], r["red_now"] = sha, now, True
        age = now - r["since"]
        if age > THRESHOLD_S and now - r.get("last_post", 0.0) >= REPEAT_S:
            day = time.strftime("%Y-%m-%d %H:%MZ", time.gmtime(r["since"]))
            note = NOTES.get((repo, ctx))
            at_least = "" if r.get("exact", True) else "at least "
            due.append((key, f"[Windy Git] RED MAIN: {repo} default branch, {ctx} = {st} since {at_least}{day} "
                             f"({age / 3600:.0f} h), head {sha[:8]}. Owner: {OWNERS.get(repo, 'unknown (Boss routes)')}. "
                             + (f"{note} " if note else "") + "Daily until green (Boss 11-02)."))
    return due


def red_count(state: dict, now: float) -> int:
    """Reds over the threshold that were SEEN red this run: a stored clock alone is not a red."""
    return sum(1 for r in state.get("reds", {}).values()
               if r.get("seen") == now and r.get("red_now") and now - r["since"] > THRESHOLD_S)


def prune(state: dict, now: float) -> list[str]:
    gone = [k for k, r in state.get("reds", {}).items() if now - r.get("seen", r["since"]) > GHOST_S]
    for k in gone:
        del state["reds"][k]
    return gone


def load() -> dict:
    if not STATE.exists():
        return {}
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        print("  state unreadable: clocks reset (reds wait another 24 h)")
        return {}


def first_parent_chain(commits: list[dict], head: str, limit: int) -> list[str]:
    """main's own line of commits, newest first: the parents[0] chain from `head`, within the
    listed commits. GitHub's commit list also holds the commits a merge brought in from a PR branch;
    their PR-mode statuses say nothing about main (Boss 11-02: windy-pro-mobile's merge a1aeb83a)."""
    by_sha = {c.get("sha"): c for c in commits if isinstance(c, dict)}
    chain, sha = [], head
    while sha in by_sha and len(chain) < limit:
        chain.append(sha)
        parents = by_sha[sha].get("parents") or []
        sha = parents[0].get("sha") if parents else None
    return chain


HISTORY_PAGES = 3


def history_from_github(repo: str, branch: str):
    """first_red(repo, ctx) -> (first_red_at, exact), or (None, False) when nothing could be read (Hub
    #112: an unreadable walk must not read as exact). Walks main's first-parent chain, fetching more
    pages when the chain leaves the listed commits (a busy PR branch can fill a page). exact=False
    when the walk ended on a limit or an unreadable page, not on a non-red commit: the time is then a
    lower bound and the line says "since at least"."""
    def first_red(_repo: str, ctx: str):
        oldest, walked, pages, start = None, 0, 0, branch
        while pages < HISTORY_PAGES and walked < HISTORY_MAX:
            code, commits = b.github("GET", f"/repos/{b.GH_OWNER}/{repo}/commits?sha={start}&per_page=100")
            pages += 1
            if code != 200 or not isinstance(commits, list) or not commits:
                return (oldest, False)
            chain = first_parent_chain(commits, commits[0].get("sha"), HISTORY_MAX - walked)
            for sha in chain:                               # newest first
                code, comb = b.github("GET", f"/repos/{b.GH_OWNER}/{repo}/commits/{sha}/status?per_page=100")
                if code != 200:
                    return (oldest, False)
                s = newest_by_context(comb.get("statuses") or []).get(ctx)
                if not s or s.get("state") not in RED:
                    return (oldest, True) if oldest is not None else None   # the red began after this one
                try:
                    oldest = _ts(s["created_at"])
                except (KeyError, ValueError):
                    return (oldest, False)
                walked += 1
            by_sha = {c.get("sha"): c for c in commits if isinstance(c, dict)}
            parents = (by_sha.get(chain[-1]) or {}).get("parents") or [] if chain else []
            if not parents:
                return (oldest, True) if oldest is not None else None       # the first commit: exact
            start = parents[0].get("sha")
        return (oldest, False)              # a limit: a lower bound
    return first_red


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
    due, failed = [], []
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
            due += step(state, repo, sha, comb.get("statuses") or [], now, history_from_github(repo, c["name"]))
        except Exception as e:  # noqa: BLE001 - one repo's failure must not hide the others
            failed.append(f"{repo} ({type(e).__name__})")
    lost = 0
    for key, line in due:
        print("  " + line)
        if post(line):
            state["reds"][key]["last_post"] = now
        else:
            lost += 1
            print(f"  BOARD post FAILED for {key}: retried next run")
    for k in prune(state, now):
        print(f"  dropped a clock not seen for {GHOST_S // 86400} d: {k}")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True))
    tmp.replace(STATE)
    if failed:
        print(f"  unreadable this run (checked again next run): {', '.join(failed)}")
    n = red_count(state, now)
    if lost:
        print(f"red main: {n} red > 24 h, BOARD post failed ({lost})")   # does NOT match --expect: an alert
    else:
        print("red main: none" if not n else f"red main: {n} red > 24 h (BOARD)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
