#!/usr/bin/env python3
"""Is every Windy Git pull mirror still in step with GitHub? (gap report G11.2)

A Gitea pull mirror that stops refreshing fails silently: no CI depends on it, so
nothing turns red, and its copy just ages. On 10-21 a fleet-wide check found 7
mirrors empty. They were correct (their GitHub repos are empty too), but nothing
would have said so if they had been broken. This check makes that loud.

Runs on Veron hourly as root (windygit-mirror-lag.timer) under windy-job, whose
heartbeat (--expect "... 0 behind") turns windy-uptime's heartbeats-veron red while
any mirror lags. Reads only: the Gitea API (GITEA_SYNC_TOKEN) and GitHub GraphQL
(GITHUB_TOKEN), one query per 40 mirrors. It changes nothing.

A mirror is BEHIND when either
  - its last refresh (mirror_updated) is older than twice its own refresh interval,
    and at least STALE_S (most mirrors refresh every 10 min, so an hour means the
    refresh itself is failing; astral-sh/setup-uv refreshes daily on purpose); or
  - its default-branch head differs from GitHub's, and GitHub's last push is older
    than GRACE_S, or twice the interval if longer (a recent push is a mirror that
    hasn't refreshed yet).
A mirror whose GitHub repo can't be read is reported as UNREADABLE and counts as
behind: say only what's true, never call an unchecked mirror fine.
Prints one line per problem, then `mirror lag: <n> mirrors checked, <m> behind`.
Exit 1 when m > 0, when no mirror is found, or on an API error.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request

GITEA = os.environ.get("BRIDGE_GITEA_URL", "http://localhost:3080").rstrip("/")
GITEA_TOKEN = os.environ.get("GITEA_SYNC_TOKEN") or os.environ.get("GITEA_ADMIN_TOKEN", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
STALE_S = 3600
GRACE_S = 1800
BATCH = 40
MAX_PAGES = 40  # 2,000 mirrors; a Gitea that never returns an empty page is a fault, not a list
_DUR = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)(?:\.\d+)?s)?")
_GH = re.compile(r"^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$")


def _call(url: str, auth: str, body: dict | None = None):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": auth,
            "Content-Type": "application/json",
            "Accept": "application/json",
            # urllib's default UA is 403'd as a bot by GitHub's edge.
            "User-Agent": "windy-git-mirror-lag/1",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"null")


def gitea(path: str):
    return _call(GITEA + "/api/v1" + path, f"token {GITEA_TOKEN}")


def github_graphql(query: str):
    return _call("https://api.github.com/graphql", f"Bearer {GITHUB_TOKEN}", {"query": query})


def _ts(s: str | None) -> float | None:
    if not s:
        return None
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def interval_s(go_duration: str | None) -> int:
    """Gitea's mirror_interval is a Go duration ("10m0s", "24h0m0s"). Unknown -> 10 min."""
    m = _DUR.fullmatch(go_duration or "")
    if not m or not any(m.groups()):
        return 600
    h, mi, se = (int(g or 0) for g in m.groups())
    return h * 3600 + mi * 60 + se


def gitea_mirrors() -> list[dict]:
    """Every pull mirror: name, source, last refresh and default-branch head (None if empty)."""
    out = []
    for page in range(1, MAX_PAGES + 1):
        d = gitea(f"/repos/search?mode=mirror&limit=50&page={page}")
        rows = (d or {}).get("data") or []
        for r in rows:
            head = None
            if not r.get("empty"):
                b = gitea(f"/repos/{r['full_name']}/branches/{urllib.request.quote(r['default_branch'], safe='')}")
                head = ((b or {}).get("commit") or {}).get("id")
            out.append({
                "name": r["full_name"],
                "source": r.get("original_url") or "",
                "updated": _ts(r.get("mirror_updated")),
                "interval": interval_s(r.get("mirror_interval")),
                "head": head,
            })
        if not rows:  # page until an empty page: never trust the page size to be 50
            return out
    # Never a silently truncated list: fail loud, so the heartbeat goes red.
    raise ValueError(f"mirror list longer than {MAX_PAGES} pages")


def github_heads(sources: list[str]) -> dict[str, dict | None]:
    """source url -> {"head": oid or None, "pushed": ts} or None when GitHub can't be read."""
    keyed = [(s, _GH.match(s)) for s in sources]
    found: dict[str, dict | None] = {s: None for s, m in keyed}
    todo = [(s, m.group(1), m.group(2)) for s, m in keyed if m]
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        q = "query{" + " ".join(
            f'a{j}: repository(owner:{json.dumps(o)}, name:{json.dumps(n)})'
            "{pushedAt defaultBranchRef{target{oid}}}"
            for j, (_, o, n) in enumerate(chunk)
        ) + "}"
        data = (github_graphql(q) or {}).get("data") or {}
        for j, (s, _, _) in enumerate(chunk):
            r = data.get(f"a{j}")
            if r is not None:
                found[s] = {
                    "head": ((r.get("defaultBranchRef") or {}).get("target") or {}).get("oid"),
                    "pushed": _ts(r.get("pushedAt")),
                }
    return found


def judge(mirrors: list[dict], gh: dict[str, dict | None], now: float) -> list[str]:
    """Pure: the problem lines (empty = every mirror in step)."""
    problems = []
    for m in mirrors:
        g = gh.get(m["source"])
        if m["updated"] is None or now - m["updated"] > max(STALE_S, 2 * m.get("interval", 600)):
            age = "never" if m["updated"] is None else f"{int((now - m['updated']) // 60)} min ago"
            problems.append(f"STALE {m['name']}: last refresh {age}")
        elif g is None:
            problems.append(f"UNREADABLE {m['name']}: GitHub source {m['source'] or '(none)'} not readable")
        elif g["head"] != m["head"] and (
            g["pushed"] is None or now - g["pushed"] > max(GRACE_S, 2 * m.get("interval", 600))
        ):
            problems.append(
                f"BEHIND {m['name']}: Windy Git {(m['head'] or 'empty')[:8]}, GitHub {(g['head'] or 'empty')[:8]}"
            )
    return problems


def main() -> int:
    try:
        mirrors = gitea_mirrors()
        gh = github_heads([m["source"] for m in mirrors])
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError) as e:
        print(f"mirror lag: ERROR ({type(e).__name__})")
        return 1
    if not mirrors:
        # Zero mirrors is never "all in step": Gitea answering an empty list is a fault.
        print("mirror lag: ERROR (no mirrors found)")
        return 1
    problems = judge(mirrors, gh, dt.datetime.now(dt.UTC).timestamp())
    for p in problems:
        print(f"  {p}")
    print(f"mirror lag: {len(mirrors)} mirrors checked, {len(problems)} behind")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
