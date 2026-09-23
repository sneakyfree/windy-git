#!/usr/bin/env python3
"""CI hygiene guard: installs come from a lockfile, never "latest" (house rule 6).

A floating install lets CI test different versions than prod ships, and a
rebuild silently changes prod. Windy Cloud's OpenAPI test failed on exactly
that (fastapi 0.141.1 in CI vs 0.136.0 on the dev box) and all three Cloud
cells floated in prod. Also flags services that publish a HOST port: every
CI job shares one dind daemon, so two jobs publishing 5432 collide ("port is
already allocated", Windy Mind runs 147/176).

WARN-ONLY (`windy-git/ci-hygiene`, green + "⚠ WARN"); CI_HYGIENE_MODE=block
turns it red once the lanes report clean. Scans CI workflow files and
Dockerfiles only. PR heads: lines the PR adds. Default branch: every line.

OK (not flagged):
  pip / uv pip install  -r FILE (with or without --require-hashes), --no-deps,
                        exact pins (tool==1.2.3), pip/setuptools/wheel upgrades
  uv sync --locked | --frozen          npm ci
  npm install pkg@1.2.3 (every package exact-pinned)
  yarn install --frozen-lockfile / --immutable   pnpm install --frozen-lockfile
Also flagged: `:latest` images (FROM / COPY --from / image: / docker://) and
`COPY uv.lock* ...`-style globs that build without the lock (Windy Mail #147).
Exceptions: ci/ci-hygiene-allow.yml, one reason per entry.

  python3 scripts/ci_hygiene.py report [repo ...]
"""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compute_guard as cg  # noqa: E402  (shared walker, cache and allow-list loader)

ROOT = Path(__file__).resolve().parents[1]
ALLOW_FILE = Path(os.environ.get("CI_HYGIENE_ALLOW", ROOT / "ci" / "ci-hygiene-allow.yml"))
MODE = os.environ.get("CI_HYGIENE_MODE", "warn")

# CI workflow files and Dockerfiles; never vendored copies.
INCLUDE = re.compile(r"(^|/)\.(github|gitea)/workflows/[^/]+\.ya?ml$|(^|/)(Dockerfile[^/]*|[^/]+\.Dockerfile)$")
NEVER = re.compile(r"(^|/)(node_modules|vendor|third_party)/")
PREFILTER = (r"pip3? install|pip install|uv sync|npm (install|i )|yarn install|pnpm install"
             r"|^\s*-\s*['\"]?[0-9]+:[0-9]+|:latest|lock[^ ]*\*"
             r"|docker[ -]compose|docker (build|buildx|run)|docker/build-push-action")

TOOLING = {"pip", "setuptools", "wheel"}
NO_DOCKER_FIX = "use job services: + a no-Docker smoke test; the image builds at deploy"
DOCKER_FILE = re.compile(r"(^|/)(Dockerfile[^/]*|[^/]+\.Dockerfile)$")
LATEST = re.compile(r"(?:^\s*FROM\s+(?:--platform=\S+\s+)?|--from=|image:\s*['\"]?|docker://)([\w./-]+):latest\b", re.I)
LOCKNAME = re.compile(r"(uv\.lock|poetry\.lock|package-lock\.json|pnpm-lock\.yaml|yarn\.lock|requirements[^ ]*\.(txt|lock))", re.I)
EXACT_PY = re.compile(r"^[A-Za-z0-9._-]+(\[[^\]]*\])?==[A-Za-z0-9.+!-]+$")
EXACT_NPM = re.compile(r"^(@[^/@]+/)?[^/@]+@\d+\.\d+\.\d+([-+][0-9A-Za-z.-]+)?$")
HOST_PORT = re.compile(r"^\s*-\s*['\"]?(\d{2,5}):(\d{2,5})['\"]?\s*(#.*)?$")
PIP_VALUE_FLAGS = {"-c", "--constraint", "-i", "--index-url", "--extra-index-url", "-f",
                   "--find-links", "--target", "-t", "--python", "--prefix", "--root", "--platform",
                   "--python-version", "--implementation", "--abi", "--only-binary", "--no-binary"}


def path_ok(path: str) -> bool:
    return bool(INCLUDE.search(path)) and not NEVER.search(path)


def _commands(text: str) -> list[list[str]]:
    """Split a shell line into simple commands (&&, ||, ;, |), tokenized."""
    out = []
    for part in re.split(r"&&|\|\||;|\|", text):
        try:
            toks = shlex.split(part, comments=True)
        except ValueError:
            toks = part.split()
        # Dockerfile RUN prefix / sudo / env-prefixed assignments
        while toks and (toks[0] in ("RUN", "sudo", "exec", "-", "run:", "command:")
                        or re.match(r"^[A-Z_][A-Z0-9_]*=", toks[0])):
            toks = toks[1:]
        if toks:
            out.append(toks)
    return out


def _pip_problem(args: list[str]) -> str | None:
    if "-r" in args or "--requirement" in args or any(a.startswith("--requirement=") for a in args):
        return None
    if "--no-deps" in args:
        return None
    pkgs, skip = [], False
    for a in args:
        if skip:
            skip = False
            continue
        if a in PIP_VALUE_FLAGS:
            skip = True
            continue
        if a.startswith("-") and a not in ("-e", "--editable"):
            continue
        if a in ("-e", "--editable"):
            continue
        pkgs.append(a)
    loose = [p for p in pkgs if not EXACT_PY.match(p) and p.split("[")[0].lower() not in TOOLING]
    if loose:
        return f"floating pip install: {' '.join(loose)[:40]}"
    return None


def scan_line(path: str, text: str) -> list[tuple[str, str]]:
    if cg.COMMENT.match(text):
        return []
    hits = []
    if "/workflows/" in path and HOST_PORT.match(text):
        hits.append(("host port", f"service publishes host port {HOST_PORT.match(text).group(1)} (shared dind)"))
        return hits
    # Windy Mail #147: a `:latest` build/tool image floats exactly like an
    # unpinned package, and `COPY uv.lock* ./` builds WITHOUT the lock when it
    # is missing instead of failing.
    m = LATEST.search(text)
    if m:
        hits.append(("floating image", f"{m.group(1)}:latest"))
    if DOCKER_FILE.search(path) and re.match(r"^\s*COPY\b", text, re.I):
        globbed = [t for t in text.split() if "*" in t and LOCKNAME.search(t)]
        if globbed:
            hits.append(("optional lock", f"COPY {globbed[0]} (must fail if the lock is missing)"))
    # Windy Git jobs get NO Docker daemon (I-5), so a docker build/compose/run
    # step in CI can never pass here (orchestrator 09-23, option A). The real
    # image build is the deploy step on the target host.
    if "/workflows/" in path and re.search(r"uses:\s*['\"]?docker/build-push-action", text):
        hits.append(("needs docker", "docker/build-push-action in CI (no Docker daemon on Windy Git; " + NO_DOCKER_FIX + ")"))
    for toks in _commands(text):
        low = [t.lower() for t in toks]
        if "/workflows/" in path and (
            low[:2] in (["docker", "build"], ["docker", "buildx"], ["docker", "run"], ["docker", "compose"])
            or low[:1] == ["docker-compose"]
        ):
            hits.append(("needs docker", f"{' '.join(low[:2])} in CI (no Docker daemon on Windy Git; " + NO_DOCKER_FIX + ")"))
            continue
        # pip install / python -m pip install / uv pip install
        for i in range(len(low) - 1):
            if os.path.basename(low[i]) in ("pip", "pip3") and low[i + 1] == "install":
                prob = _pip_problem(toks[i + 2:])
                if prob:
                    hits.append(("floating install", prob))
                break
        if low[:2] == ["uv", "sync"] and not ({"--locked", "--frozen"} & set(low)):
            hits.append(("floating install", "uv sync without --locked/--frozen"))
        if low[:1] == ["npm"] and len(low) > 1 and low[1] in ("install", "i", "add"):
            pkgs = [t for t in toks[2:] if not t.startswith("-")]
            if not pkgs or not all(EXACT_NPM.match(p) for p in pkgs):
                hits.append(("floating install", f"npm {low[1]} {' '.join(pkgs)[:30]}".strip() + " (use npm ci)"))
        if low[:2] == ["yarn", "install"] and not ({"--frozen-lockfile", "--immutable"} & set(low)):
            hits.append(("floating install", "yarn install without --frozen-lockfile"))
        if low[:2] == ["pnpm", "install"] and "--frozen-lockfile" not in low:
            hits.append(("floating install", "pnpm install without --frozen-lockfile"))
    return hits


def check(repo: str, sha: str, default_branch: str, is_default_head: bool):
    bare = cg.WORK / f"{repo}.git"
    if not bare.is_dir() or not cg.fetched(bare, sha):  # pushed after the fetch: next cycle
        return None
    allow = cg.load_allow(ALLOW_FILE)
    rules = hashlib.sha256((PREFILTER + INCLUDE.pattern + EXACT_PY.pattern + EXACT_NPM.pattern).encode()).hexdigest()[:8]
    fp = cg._fingerprint(allow) + ":" + rules  # hashlib, not hash(): hash() is per-process random
    kw = dict(line_fn=scan_line, path_ok=path_ok)
    if is_default_head:
        return cg.cached_scan(f"hyg-tree:{repo}:{sha}:{fp}",
                              lambda: cg.scan_tree(repo, bare, sha, allow, prefilter=PREFILTER, **kw))
    return cg.cached_scan(f"hyg-pr:{repo}:{sha}:{fp}",
                          lambda: cg.scan_added(repo, bare, f"refs/heads/{default_branch}", sha, allow, **kw))


def status_for(findings, whole_tree: bool):
    scope = "in CI/Dockerfiles" if whole_tree else "added"
    if not findings:
        return "success", f"OK: no floating install or host-port service {scope}", None
    f = findings[0]
    n = len(findings)
    state = "failure" if MODE == "block" else "success"
    lead = "BLOCKED" if MODE == "block" else "⚠ WARN (not blocking)"
    return state, f"{lead}: {n} CI hygiene issue{'s' if n > 1 else ''} {scope}, e.g. {f.path}:{f.line} {f.match}"[:140], f


def report(repos: list[str]) -> int:
    allow = cg.load_allow(ALLOW_FILE)
    total = 0
    for repo in repos:
        bare = cg.WORK / f"{repo}.git"
        if not bare.is_dir():
            print(f"## {repo}: no sync clone, skipped")
            continue
        head = cg._git(bare, "symbolic-ref", "--short", "HEAD").strip()
        sha = cg._git(bare, "rev-parse", head).strip()
        fs = cg.scan_tree(repo, bare, sha, allow, line_fn=scan_line, path_ok=path_ok, prefilter=PREFILTER)
        total += len(fs)
        print(f"## {repo} ({head} {sha[:7]}): {len(fs)} issue(s)")
        for f in fs:
            print(f"  {f.path}:{f.line}  [{f.kind}]  {f.match}")
    print(f"TOTAL {total}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "report":
        default = os.environ.get("BRIDGE_REPOS", "").split() or sorted(
            p.name.removesuffix(".git") for p in cg.WORK.glob("*.git"))
        sys.exit(report(sys.argv[2:] or default))
    sys.exit(__doc__)
