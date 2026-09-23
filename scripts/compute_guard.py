#!/usr/bin/env python3
"""Compute guard: Windy Mind is the ONLY door to AI compute (Grant, 2026-09-23).

Flags code that talks to an AI provider directly instead of through Windy Mind:
a provider API host, a provider SDK import or dependency, or a raw provider key
name. Direct calls skip Mind's metering, caps and live-model routing, and they
spend whichever key happens to be lying around (the audit found Grant's personal
Max OAuth token inside a platform container).

WARN-ONLY for now: the bridge posts `windy-git/compute-guard` as success with a
"⚠ WARN" description, so nothing turns red. `COMPUTE_GUARD_MODE=block` flips
findings to failure once the repos are clean (orchestrator's call).

- PR heads: only lines the PR ADDS (vs its merge-base with the default branch).
- Default-branch head: the whole tree (the baseline, and what `report` prints).

Exceptions live in ONE file, ci/compute-guard-allow.yml, each with a reason.
Tests, docs, lockfiles, vendored code and CI config are never scanned.
Reads the sync's bare GitHub clones on Veron (no docker exec: IO-stall lesson).

  python3 scripts/compute_guard.py report [repo ...]   # whole-tree findings on each default branch
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ALLOW_FILE = Path(os.environ.get("COMPUTE_GUARD_ALLOW", ROOT / "ci" / "compute-guard-allow.yml"))
WORK = Path(os.environ.get("SYNC_WORK", "/srv/windygit/sync"))
CACHE = Path(os.environ.get("COMPUTE_GUARD_CACHE", "/var/lib/windy-git/compute-guard-cache.json"))
MODE = os.environ.get("COMPUTE_GUARD_MODE", "warn")  # warn | block

HOSTS = [
    "api.anthropic.com", "api.openai.com", "api.groq.com",
    "generativelanguage.googleapis.com", "api.mistral.ai", "api.perplexity.ai",
    "openrouter.ai", "api.together.xyz", "api.together.ai", "api.cerebras.ai",
    "api.sambanova.ai", "api.deepseek.com", "api.x.ai", "api.cohere.ai",
    "api.cohere.com", "api.fireworks.ai", "api.replicate.com",
    "api-inference.huggingface.co",
]
KEYS = [
    "ANTHROPIC_API_KEY", "ANTHROPIC_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN",
    "OPENAI_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY",
    "GOOGLE_AI_API_KEY", "MISTRAL_API_KEY", "PERPLEXITY_API_KEY", "PPLX_API_KEY",
    "OPENROUTER_API_KEY", "TOGETHER_API_KEY", "CEREBRAS_API_KEY", "SAMBANOVA_API_KEY",
    "DEEPSEEK_API_KEY", "XAI_API_KEY", "COHERE_API_KEY", "FIREWORKS_API_KEY",
    "REPLICATE_API_TOKEN",
]
PY_SDKS = r"anthropic|openai|groq|mistralai|cohere|google\.generativeai|google\.genai|together|cerebras|litellm"
JS_SDKS = (r"@anthropic-ai/sdk|openai|groq-sdk|@google/generative-ai|@google/genai|@mistralai/mistralai"
           r"|cohere-ai|together-ai|@ai-sdk/(?:anthropic|openai|groq|google|mistral)")

RULES: list[tuple[str, re.Pattern]] = [
    ("provider host", re.compile("|".join(re.escape(h) for h in HOSTS))),
    ("provider key", re.compile(r"\b(?:" + "|".join(KEYS) + r")\b")),
    ("provider SDK", re.compile(rf"^\s*(?:from|import)\s+(?:{PY_SDKS})(?:\s|\.|$|,)")),
    ("provider SDK", re.compile(rf"""(?:from\s+|require\(\s*|import\(\s*)['"](?:{JS_SDKS})(?:/[^'"]*)?['"]""")),
    # dependency manifests: package.json keys, requirements / pyproject lines
    ("provider SDK dep", re.compile(rf'''^\s*"(?:{JS_SDKS})"\s*:''')),
    ("provider SDK dep", re.compile(rf'''^\s*["']?(?:{PY_SDKS.replace(chr(92) + ".", "-")})(?:\[[^\]]*\])?\s*(?:[<>=~!]=?|["',]|$)''')),
]
DEP_FILES = re.compile(r"(^|/)(package\.json|requirements[^/]*\.txt|pyproject\.toml|setup\.cfg|Pipfile)$")

# Never scanned: tests, docs, lockfiles, vendored/built code, CI config.
SKIP = re.compile(
    r"(^|/)(tests?|__tests__|spec|docs?|node_modules|vendor|dist|build|\.github|\.gitea)/"
    r"|(^|/)(test_[^/]*|[^/]*_test\.py|conftest\.py|[^/]*\.(test|spec)\.[cm]?[jt]sx?)$"
    r"|\.(md|mdx|rst|txt|lock|snap|svg|png|jpg|pdf)$"
    r"|(^|/)(package-lock\.json|pnpm-lock\.yaml|yarn\.lock|uv\.lock|poetry\.lock|Cargo\.lock)$"
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    match: str


def load_allow(path: Path = ALLOW_FILE) -> list[dict]:
    data = yaml.safe_load(path.read_text()) or {}
    entries = data.get("allow") or []
    for e in entries:  # a reason per entry is the whole point of the file
        if not (e.get("repo") and e.get("paths") and str(e.get("reason", "")).strip()):
            raise ValueError(f"allow entry needs repo, paths and a reason: {e}")
    return entries


def allowed(repo: str, path: str, allow: list[dict]) -> bool:
    for e in allow:
        if e["repo"] == repo and any(fnmatch.fnmatch(path, g) for g in e["paths"]):
            return True
    return False


COMMENT = re.compile(r"^\s*(?:#|//|/\*|\*|<!--)")


def scan_line(path: str, text: str) -> list[tuple[str, str]]:
    # A comment is not a call: "the ANTHROPIC_OAUTH_TOKEN setting was removed"
    # (windy-search) must not count, nor a commented-out `# OPENAI_API_KEY=`.
    if COMMENT.match(text):
        return []
    hits = []
    for kind, rx in RULES:
        if kind == "provider SDK dep" and not DEP_FILES.search(path):
            continue
        m = rx.search(text)
        if m:
            hits.append((kind, m.group(0).strip()[:60]))
    return hits


def _git(bare: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "--git-dir", str(bare), *args],
        capture_output=True, text=True, check=True, timeout=120,
    ).stdout


def _default_path_ok(path: str) -> bool:
    return not SKIP.search(path)


def scan_tree(repo: str, bare: Path, sha: str, allow: list[dict], *, line_fn=None,
              path_ok=None, prefilter: str | None = None) -> list[Finding]:
    """Every line in the tree at `sha` (default branch: the baseline)."""
    # A cheap prefilter by git, then the real rules in Python.
    # Other guards (ci_hygiene) reuse this walker with their own line rules.
    line_fn = line_fn or scan_line
    path_ok = path_ok or _default_path_ok
    pre = prefilter or "|".join([re.escape(h) for h in HOSTS] + KEYS + [
        "anthropic", "openai", "groq", "mistral", "generativeai", "genai", "cohere",
        "together", "cerebras", "litellm"])
    try:
        out = _git(bare, "grep", "-nIE", "-e", pre, sha, "--", ".")
    except subprocess.CalledProcessError as e:
        if e.returncode == 1:  # no matches
            return []
        raise
    found = []
    for raw in out.splitlines():
        # <sha>:<path>:<line>:<text>
        try:
            _, path, line, text = raw.split(":", 3)
        except ValueError:
            continue
        if not path_ok(path) or allowed(repo, path, allow):
            continue
        for kind, match in line_fn(path, text):
            found.append(Finding(path, int(line), kind, match))
    return found


def scan_added(repo: str, bare: Path, base_ref: str, sha: str, allow: list[dict], **kw) -> list[Finding]:
    """Only the lines a PR adds, vs its merge-base with the default branch."""
    mb = _git(bare, "merge-base", base_ref, sha).strip()
    diff = _git(bare, "diff", "-U0", "--no-color", "--no-ext-diff", mb, sha)
    return parse_added(repo, diff, allow, **kw)


HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parse_added(repo: str, diff: str, allow: list[dict], *, line_fn=None, path_ok=None) -> list[Finding]:
    line_fn = line_fn or scan_line
    path_ok = path_ok or _default_path_ok
    found, path, line = [], None, 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            p = raw[4:]
            path = None if p == "/dev/null" else p[2:] if p.startswith("b/") else p
            continue
        m = HUNK.match(raw)
        if m:
            line = int(m.group(1))
            continue
        if path is None or raw.startswith("--- "):
            continue
        if raw.startswith("+"):
            if path_ok(path) and not allowed(repo, path, allow):
                for kind, match in line_fn(path, raw[1:]):
                    found.append(Finding(path, line, kind, match))
            line += 1
    return found


# ---- cache: a tree scan runs once per (repo, sha, rules+allow) --------------
def _fingerprint(allow: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps([HOSTS, KEYS, PY_SDKS, JS_SDKS, SKIP.pattern, allow], sort_keys=True).encode()
    ).hexdigest()[:16]


def cached_scan(key: str, fn) -> list[Finding]:
    try:
        cache = json.loads(CACHE.read_text())
    except (OSError, ValueError):
        cache = {}
    if key in cache:
        return [Finding(**f) for f in cache[key]]
    result = fn()
    cache[key] = [f.__dict__ for f in result]
    if len(cache) > 2000:  # keep it small: newest entries win
        cache = dict(list(cache.items())[-1000:])
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache))
        tmp.replace(CACHE)
    except OSError:
        pass
    return result


def fetched(bare: Path, sha: str) -> bool:
    """Is `sha` in the sync clone yet? The bridge learns PR / default heads from
    GitHub's API AFTER the sync fetched, so a push in between is simply not here
    until the next 5-min cycle. That is a race, not an error: skip quietly."""
    try:
        _git(bare, "cat-file", "-e", f"{sha}^{{commit}}")
        return True
    except subprocess.CalledProcessError:
        return False


def check(repo: str, sha: str, default_branch: str, is_default_head: bool) -> list[Finding] | None:
    """Findings for one commit, or None when the guard can't run (never a fake OK)."""
    bare = WORK / f"{repo}.git"
    if not bare.is_dir() or not fetched(bare, sha):
        return None
    allow = load_allow()
    fp = _fingerprint(allow)
    if is_default_head:
        return cached_scan(f"tree:{repo}:{sha}:{fp}", lambda: scan_tree(repo, bare, sha, allow))
    return cached_scan(
        f"pr:{repo}:{sha}:{fp}",
        lambda: scan_added(repo, bare, f"refs/heads/{default_branch}", sha, allow),
    )


def status_for(findings: list[Finding], whole_tree: bool) -> tuple[str, str, Finding | None]:
    """(state, description, first finding) for the GitHub commit status."""
    scope = "in tree" if whole_tree else "added"
    if not findings:
        what = "no direct AI-provider use in tree" if whole_tree else "no direct AI-provider use added"
        return "success", f"OK: {what} (Windy Mind is the only door)", None
    f = findings[0]
    n = len(findings)
    state = "failure" if MODE == "block" else "success"
    lead = "BLOCKED" if MODE == "block" else "⚠ WARN (not blocking)"
    desc = f"{lead}: {n} direct AI-provider use{'s' if n > 1 else ''} {scope}, e.g. {f.path}:{f.line} {f.match}"
    return state, desc[:140], f


def report(repos: list[str]) -> int:
    allow = load_allow()
    total = 0
    for repo in repos:
        bare = WORK / f"{repo}.git"
        if not bare.is_dir():
            print(f"## {repo}: no sync clone, skipped")
            continue
        head = _git(bare, "symbolic-ref", "--short", "HEAD").strip()
        sha = _git(bare, "rev-parse", head).strip()
        fs = scan_tree(repo, bare, sha, allow)
        total += len(fs)
        print(f"## {repo} ({head} {sha[:7]}): {len(fs)} finding(s)")
        for f in fs:
            print(f"  {f.path}:{f.line}  [{f.kind}]  {f.match}")
    print(f"TOTAL {total}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "report":
        default = os.environ.get("BRIDGE_REPOS", "").split() or sorted(
            p.name.removesuffix(".git") for p in WORK.glob("*.git"))
        sys.exit(report(sys.argv[2:] or default))
    sys.exit(__doc__)
