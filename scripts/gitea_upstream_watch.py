#!/usr/bin/env python3
"""Daily: is the Gitea under Windy Git current, and does any published advisory cover what we run?

Why (Russ, 11-07): Windy Git sat on 1.24.7 for a year while Gitea published 175 advisories. Staying current
must be mechanical, not memory. Once a day this reads
  - the version we RUN (live /api/v1/version, never a file),
  - Gitea's releases on GitHub (go-gitea/gitea, no pre-releases),
  - every security advisory Gitea publishes on its own repo (go-gitea/gitea security advisories; the
    global GitHub database lists only the reviewed half of them: 82 vs 168 covering 1.24.7 on 11-07),
and prints ONE line. ALARM (the line starts with "ALARM") when
  (a) a newer PATCH of our own minor has been out for more than 30 days, or
  (b) an advisory rated critical or high that covers our version has been public for more than 72 hours.
Otherwise the line says how far behind the newest release we are and how many advisories cover us.

  python3 scripts/gitea_upstream_watch.py            # print only (dark)
  python3 scripts/gitea_upstream_watch.py --post     # also the one BOARD line (after the go-ahead)
Reads only. Never prints a token.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

GITEA = os.environ.get("BRIDGE_GITEA_URL", "http://localhost:3080").rstrip("/")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
PKG = "code.gitea.io/gitea"
PATCH_LAG_S = 30 * 86400
SEVERE_LAG_S = 72 * 3600
SEVERE = {"critical", "high"}
MAX_PAGES = 20

Version = tuple[int, int, int]


def parse(v: str) -> Version | None:
    m = re.match(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$", v.strip())
    return (int(m[1]), int(m[2]), int(m[3] or 0)) if m else None


def covers(rng: str, v: Version) -> bool:
    """GitHub's vulnerable_version_range, e.g. '>= 1.5.0, < 1.26.3', '< 1.27.0', '<= 1.24.6', '= 1.24.0'.
    An unparseable range counts as covering us: a missed advisory is worse than a false alarm."""
    ops = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b,
           "<": lambda a, b: a < b, "=": lambda a, b: a == b}
    for part in [p.strip() for p in rng.split(",") if p.strip()]:
        m = re.match(r"^(>=|<=|>|<|=)?\s*(\S+)$", part)   # a bare "1.26.2" means "= 1.26.2"
        bound = parse(m[2]) if m else None
        if bound is None:
            return True
        if not ops[m[1] or "="](v, bound):
            return False
    return True


def _get(url: str, headers: dict | None = None):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "windy-git-upstream-watch", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r), r.headers.get("Link", "")


def gh(path: str) -> list:
    """Every page of a GitHub list (Link: rel=next)."""
    auth = {"Authorization": f"Bearer {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
    url, out = f"https://api.github.com{path}", []
    for _ in range(MAX_PAGES):
        body, link = _get(url, auth)
        out += body
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        if not m:
            return out
        url = m[1]
    raise RuntimeError(f"{path}: more than {MAX_PAGES} pages")


def running_version() -> str:
    body, _ = _get(f"{GITEA}/api/v1/version")
    return body["version"]


def ts(iso: str) -> float:
    return time.mktime(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone


def check(ours: str, releases: list, advisories: list, now: float) -> tuple[bool, str]:
    v = parse(ours)
    if v is None:
        return True, f"ALARM Windy Git Gitea watch: cannot read our version ({ours!r})"
    rel = sorted(((parse(r["tag_name"]), r) for r in releases
                  if not r.get("prerelease") and not r.get("draft") and parse(r["tag_name"])),
                 key=lambda x: x[0])
    newest = rel[-1] if rel else None
    patch = [x for x in rel if x[0][:2] == v[:2] and x[0] > v]
    alarms, notes = [], []
    if patch:
        first = min(patch, key=lambda x: ts(x[1]["published_at"]))
        age = now - ts(first[1]["published_at"])
        top = ".".join(map(str, patch[-1][0]))
        (alarms if age > PATCH_LAG_S else notes).append(
            f"patch {top} out (first newer patch {int(age // 86400)} d ago)")
    cov = []
    for a in advisories:
        if a.get("withdrawn_at"):
            continue
        hit = False
        vulns = a.get("vulnerabilities") or []
        for x in vulns:                               # Gitea's own advisories: the package is Gitea
            patched = [p for p in (parse(t) for t in re.split(r"[,\s]+", x.get("patched_versions") or "") if t) if p]
            if covers(x.get("vulnerable_version_range") or "", v) and not any(v >= p for p in patched):
                hit = True
        if hit or not vulns:                          # no vulnerability listed = assume it covers us
            cov.append(a)
    sev = {s: sum(1 for a in cov if (a.get("severity") or "").lower() == s) for s in ("critical", "high", "medium", "low")}
    late = [a for a in cov if (a.get("severity") or "").lower() in SEVERE
            and now - ts(a.get("published_at") or "1970-01-01T00:00:00") > SEVERE_LAG_S]
    if late:
        alarms.append(f"{len(late)} critical/high advisories cover {ours} for 72 h+ (e.g. {late[0].get('ghsa_id')})")
    behind = f"newest {'.'.join(map(str, newest[0]))}" if newest else "no releases read"
    if newest and newest[0] <= v:
        behind = "on the newest release"
    counts = ", ".join(f"{k} {n}" for k, n in sev.items())
    head = "ALARM " if alarms else ""
    detail = "; ".join(alarms + notes)
    return bool(alarms), (f"{head}[Windy Git] Gitea watch: we run {ours}; {behind}; advisories covering us: "
                          f"{len(cov)} ({counts}){'; ' + detail if detail else ''}")


def main(argv: list[str]) -> int:
    try:
        ours = running_version()
        releases = gh("/repos/go-gitea/gitea/releases?per_page=100")
        advisories = gh("/repos/go-gitea/gitea/security-advisories?state=published&per_page=100")
    except (urllib.error.URLError, OSError, ValueError, KeyError, RuntimeError) as e:
        line = f"ALARM [Windy Git] Gitea watch could not read its sources ({type(e).__name__})"
        alarm = True
    else:
        alarm, line = check(ours, releases, advisories, time.time())
    print(line)
    if "--post" in argv:
        import cancel_superseded as cs  # the BOARD line (Windy 0, else the fallback board)
        cs.board(line)
    return 1 if alarm else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
