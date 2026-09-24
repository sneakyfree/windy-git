#!/usr/bin/env python3
"""Live status of the repo guards (compute-guard + ci-hygiene + secret-guard) as one markdown page.

Scans every bridged repo's DEFAULT branch with both guards and renders what is
left, per repo and owner lane. Findings in code Grant owns (ci/grant-owned.yml:
windy-pro's desktop app and its build jobs) are listed in their OWN section and
do not count against "ready to block": those are proposals for Grant, not a
lane's fix (orchestrator, 09-23).

  sudo python3 scripts/guards_report.py > GUARDS_STATUS.md
"""

from __future__ import annotations

import fnmatch
import os
import re
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ci_hygiene as hy  # noqa: E402
import compute_guard as cg  # noqa: E402
import secret_guard as sgd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OWNED = Path(os.environ.get("GRANT_OWNED", ROOT / "ci" / "grant-owned.yml"))
REPOS = os.environ.get("BRIDGE_REPOS", "").split() or [
    "windy-chat", "windy-mail", "windy-calendar", "Windy-Clone", "WindyCloud", "windy-search",
    "windy-connect", "windy-drops", "windy-code-web", "windy-code", "windy-traveler",
    "windy-registry", "eternitas", "windy-translate", "windytranslate-site", "windytraveler-site",
    "windy-hand", "windy-cloud-sites", "windy-cloud-domains", "windy-cloud-vps", "windytalk",
    "windy-pro", "windy-mind", "windy-git", "windy-inbox"]
# Owner lane per repo = the session name to message (orchestrator routing, 09-23 ~22:45Z:
# hub/account-server/dashboard/site -> "Windy Hub"; windy-calendar only -> "Windy Calender";
# windy-admin/telemetry -> "Windy Admin"). windy-pro here = its server/web side; the desktop
# app is Grant-owned and listed in its own section below.
OWNERS = {
    "windy-chat": "Windy Chat", "windy-mail": "Windy Mail", "windy-calendar": "Windy Calender",
    "Windy-Clone": "Windy Clone", "WindyCloud": "Windy Cloud", "windy-cloud-sites": "Windy Cloud",
    "windy-cloud-domains": "Windy Cloud", "windy-cloud-vps": "Windy Cloud", "windy-search": "Windy Search",
    "windy-connect": "Windy Connect", "windy-drops": "Windy Drops", "windy-registry": "Windy Drops",
    "windy-code-web": "Windy Code", "windy-code": "Windy Code", "windy-traveler": "Windy Traveler",
    "windytraveler-site": "Windy Traveler", "eternitas": "Eternitas", "windy-translate": "Windy Translate",
    "windytranslate-site": "Windy Translate", "windy-hand": "Windy Hand", "windytalk": "Windy Talk",
    "windy-pro": "Windy Hub", "windy-mind": "WIndy Mind", "windy-git": "Windy Git",
    "windy-inbox": "Windy Drops"}  # Windy Inbox build lead (09-24)
JOB = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")


def job_of(text: str, line: int) -> str | None:
    """The workflow job a line belongs to (2-space keys under `jobs:`)."""
    in_jobs, job = False, None
    for i, raw in enumerate(text.splitlines(), 1):
        if raw.startswith("jobs:"):
            in_jobs = True
        elif in_jobs and JOB.match(raw):
            job = JOB.match(raw).group(1)
        elif raw and not raw[0].isspace() and not raw.startswith("jobs:"):
            in_jobs = False
        if i == line:
            return job if in_jobs else None
    return None


def grant_owned(repo: str, path: str, job: str | None, owned: list[dict]) -> bool:
    for e in owned:
        if e["repo"] != repo:
            continue
        if any(fnmatch.fnmatch(path, g) for g in e.get("paths") or []):
            return True
        if job and job in (e.get("jobs") or {}).get(path, []):
            return True
    return False


def split_grant(repo: str, sha: str, findings: list) -> tuple[list, list]:
    """(lane-owned, Grant-owned) findings at `sha`, by ci/grant-owned.yml, with
    workflow lines attributed to their job exactly as the status page does."""
    owned = (yaml.safe_load(OWNED.read_text()) or {}).get("grant_owned") or []
    if not any(e["repo"] == repo for e in owned):
        return list(findings), []
    bare = cg.WORK / f"{repo}.git"
    texts: dict[str, str] = {}
    lane, grant = [], []
    for f in findings:
        job = None
        if "/workflows/" in f.path:
            if f.path not in texts:
                texts[f.path] = cg._git(bare, "show", f"{sha}:{f.path}")
            job = job_of(texts[f.path], f.line)
        (grant if grant_owned(repo, f.path, job, owned) else lane).append(f)
    return lane, grant


def scan(repo: str, owned: list[dict]):
    bare = cg.WORK / f"{repo}.git"
    if not bare.is_dir():
        return None
    head = cg._git(bare, "symbolic-ref", "--short", "HEAD").strip()
    sha = cg._git(bare, "rev-parse", head).strip()
    out = {"sha": sha, "compute": [], "hygiene": [], "secrets": []}
    texts: dict[str, str] = {}
    for key, fs in (("compute", cg.check(repo, sha, head, True) or []),
                    ("hygiene", hy.check(repo, sha, head, True) or []),
                    ("secrets", sgd.check(repo, sha, head, True) or [])):
        for f in fs:
            job = None
            if "/workflows/" in f.path:
                if f.path not in texts:
                    texts[f.path] = cg._git(bare, "show", f"{sha}:{f.path}")
                job = job_of(texts[f.path], f.line)
            out[key].append((f, job, grant_owned(repo, f.path, job, owned)))
    return out


def render(results: dict) -> str:
    now = time.strftime("%Y-%m-%d %H:%MZ", time.gmtime())
    lane = {k: 0 for k in ("compute", "hygiene", "secrets")}
    grant = {k: 0 for k in ("compute", "hygiene", "secrets")}
    for r in results.values():
        for k in lane:
            lane[k] += sum(1 for _, _, g in r.get(k, []) if not g)
            grant[k] += sum(1 for _, _, g in r.get(k, []) if g)
    L = [f"# Repo guards: live status (generated {now}; windy-git scripts/guards_report.py)",
         "_Default branches only. WARN-only today; the orchestrator says \"block\" per guard when its LANE column is 0. "
         "Grant-owned code (ci/grant-owned.yml) is listed separately and never holds up a block._", "",
         "| Guard | Lane-owned findings | Grant-owned (proposals) | Ready to block? |", "|---|---|---|---|",
         f"| compute-guard (Mind is the only door) | {lane['compute']} | {grant['compute']} | {'✅ YES' if lane['compute'] == 0 else '❌ not yet'} |",
         f"| ci-hygiene (house rule 6) | {lane['hygiene']} | {grant['hygiene']} | {'✅ YES' if lane['hygiene'] == 0 else '❌ not yet'} |",
         f"| secret-guard (no credentials in repos; hash only) | {lane['secrets']} | {grant['secrets']} | {'✅ YES' if lane['secrets'] == 0 else '❌ not yet'} |",
         "", "## By repo (lane-owned)", "| Repo | owner | head | compute | hygiene | secrets | first items |", "|---|---|---|---|---|---|---|"]
    for repo, r in sorted(results.items()):
        c = [x for x in r["compute"] if not x[2]]
        h = [x for x in r["hygiene"] if not x[2]]
        s = [x for x in r.get("secrets", []) if not x[2]]
        items = "; ".join(f"`{f.path}:{f.line}` {f.match}" for f, _, _ in (s + c + h)[:3]) or "clean ✅"
        L.append(f"| {repo} | {OWNERS.get(repo, '?')} | {r['sha'][:7]} | {len(c)} | {len(h)} | {len(s)} | {items} |")
    L += ["", "## Grant-owned (windy-pro desktop app + its build jobs): proposals only, not blocking"]
    g = [(repo, f, job) for repo, r in sorted(results.items()) for k in ("compute", "hygiene", "secrets")
         for f, job, own in r.get(k, []) if own]
    L += [f"- {repo} `{f.path}:{f.line}`{f' (job {job})' if job else ''}: {f.match}" for repo, f, job in g] or ["- none"]
    return "\n".join(L) + "\n"


def main() -> int:
    owned = (yaml.safe_load(OWNED.read_text()) or {}).get("grant_owned") or []
    results = {}
    for repo in REPOS:
        r = scan(repo, owned)
        if r is not None:
            results[repo] = r
    sys.stdout.write(render(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
