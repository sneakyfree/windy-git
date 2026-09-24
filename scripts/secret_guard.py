#!/usr/bin/env python3
"""Secret guard: no live credential lands in a bridged repo (leak hunt 09-24).

Same walker, cache and GitHub posting as compute_guard / ci_hygiene
(`windy-git/secret-guard`), but over EVERY text file, and a finding carries only
"<kind> #<sha256[:8]>", never the value (house rule 10). Known fakes are allowed
BY HASH in ci/secret-guard-allow.yml (repo + hashes + reason).

  sudo python3 scripts/secret_guard.py report [repo ...]
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compute_guard as cg  # noqa: E402  (shared walker, cache)
import secret_shapes as ss  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ALLOW_FILE = Path(os.environ.get("SECRET_GUARD_ALLOW", ROOT / "ci" / "secret-guard-allow.yml"))
MODE = os.environ.get("SECRET_GUARD_MODE", "warn")
NEVER = re.compile(r"(^|/)(node_modules|vendor|third_party)/")


def path_ok(path: str) -> bool:
    return not NEVER.search(path)


def load_allow(path: Path = ALLOW_FILE) -> dict[str, set[str]]:
    """{repo: {hash8, ...}}; every entry needs a reason."""
    data = yaml.safe_load(path.read_text()) if path.exists() else {}
    out: dict[str, set[str]] = {}
    for e in (data or {}).get("allow") or []:
        if not (e.get("repo") and e.get("hashes") and str(e.get("reason", "")).strip()):
            raise ValueError(f"allow entry needs repo, hashes and a reason: {e}")
        out.setdefault(e["repo"], set()).update(str(h) for h in e["hashes"])
    return out


def scan_line(path: str, text: str) -> list[tuple[str, str]]:
    return [(kind, f"{kind} #{h}") for kind, h in ss.find(text)]


def _drop_allowed(repo: str, findings, allow: dict[str, set[str]]):
    ok = allow.get(repo, set())
    return [f for f in findings if f.match.rsplit("#", 1)[-1] not in ok]


def check(repo: str, sha: str, default_branch: str, is_default_head: bool):
    bare = cg.WORK / f"{repo}.git"
    if not bare.is_dir() or not cg.fetched(bare, sha):  # pushed after the fetch: next cycle
        return None
    allow = load_allow()
    rules = hashlib.sha256(("|".join(rx.pattern for _, rx in ss.PATTERNS) + ss.PREFILTER).encode()).hexdigest()[:8]
    kw = dict(line_fn=scan_line, path_ok=path_ok)
    if is_default_head:
        fs = cg.cached_scan(f"sec-tree:{repo}:{sha}:{rules}",
                            lambda: cg.scan_tree(repo, bare, sha, [], prefilter=ss.PREFILTER, **kw))
    else:
        fs = cg.cached_scan(f"sec-pr:{repo}:{sha}:{rules}",
                            lambda: cg.scan_added(repo, bare, f"refs/heads/{default_branch}", sha, [], **kw))
    return _drop_allowed(repo, fs, allow)


def status_for(findings, whole_tree: bool, grant=()):
    """Same contract as the other guards. `grant` findings never block."""
    scope = "in tree" if whole_tree else "added"
    if not findings and grant:
        g, n = grant[0], len(grant)
        return "success", f"⚠ WARN (Grant-owned, not blocking): {n} secret-shaped string{'s' if n > 1 else ''} {scope}, e.g. {g.path}:{g.line} {g.match}"[:140], g
    if not findings:
        return "success", f"OK: no secret-shaped strings {scope}", None
    f, n = findings[0], len(findings)
    state = "failure" if MODE == "block" else "success"
    lead = "BLOCKED" if MODE == "block" else "⚠ WARN (not blocking)"
    return state, f"{lead}: {n} secret-shaped string{'s' if n > 1 else ''} {scope}, e.g. {f.path}:{f.line} {f.match}"[:140], f


def report(repos: list[str]) -> int:
    allow = load_allow()
    total = 0
    for repo in repos:
        bare = cg.WORK / f"{repo}.git"
        if not bare.is_dir():
            continue
        head = cg._git(bare, "symbolic-ref", "--short", "HEAD").strip()
        sha = cg._git(bare, "rev-parse", head).strip()
        fs = _drop_allowed(repo, cg.scan_tree(repo, bare, sha, [], line_fn=scan_line, path_ok=path_ok,
                                               prefilter=ss.PREFILTER), allow)
        total += len(fs)
        print(f"## {repo} ({head} {sha[:7]}): {len(fs)} finding(s)")
        for f in fs:
            print(f"  {f.path}:{f.line}  {f.match}")
    print(f"TOTAL {total}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "report":
        default = os.environ.get("BRIDGE_REPOS", "").split() or sorted(
            p.name.removesuffix(".git") for p in cg.WORK.glob("*.git"))
        sys.exit(report(sys.argv[2:] or default))
    sys.exit(__doc__)
