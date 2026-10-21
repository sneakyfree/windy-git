#!/usr/bin/env python3
"""Birth-terms guard: the retired agent-birth words don't come back (Grant, 2026-10-21).

The fleet glossary kit-army-config doctrine/03-GLOSSARY-AGENT-BIRTH-TERMS.md retired
"the Hub" for Windy's account software (now Windy Accounts; "the Hub lane" is only the
Claude session named Windy Hub) and the "hallway" words (now Windy's Birth Canal, and
the Eternitas Registry for Eternitas's step). This guard flags those words in prose a
PR ADDS, so existing history is never flagged.

  scope    *.md files only (code identifiers such as HUB_PLATFORM_IDS are never prose)
  flags    "hatch hallway", "agent hallway", "one hallway", "the hallway",
           "the hub" unless the next word is "lane" (all case-insensitive)
  exempt   the glossary file itself; anything under a history/ folder (verbatim
           archive copies, e.g. docs/history/ from the Windy 0 salvage); any line
           inside a <!-- glossary --> ... <!-- /glossary --> block (judged on the
           whole file at the PR head, so markers outside the changed hunk still
           count); any line containing "(historical)"

WARN-ONLY (`windy-git/birth-terms`, green + "⚠ WARN"); BIRTH_TERMS_MODE=block turns
it red (its own Boss GO, after a dry run). Default-branch heads are not judged: only
what a PR adds. Private repos run through the PR bridge (check/status_for, like
ci_hygiene); public repos through runner_guard's PR pass (scan_patch), which already
holds each PR's file list, so this costs no extra GitHub call there.

  python3 scripts/birth_terms.py lint FILE...     # every line, glossary rules applied
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compute_guard as cg  # noqa: E402  (shared walker, cache and Finding)

MODE = os.environ.get("BIRTH_TERMS_MODE", "warn")
GLOSSARY = "doctrine/03-GLOSSARY-AGENT-BIRTH-TERMS.md"
NEVER = re.compile(r"(^|/)(node_modules|vendor|third_party|history)/", re.I)
ESCAPE = "(historical)"
OPEN, CLOSE = "<!-- glossary -->", "<!-- /glossary -->"
RULES = [
    (re.compile(r"\b(?:hatch|agent|one)\s+hallway\b", re.I), "Birth Canal"),
    (re.compile(r"\bthe\s+hallway\b", re.I), "the Birth Canal / the Registry"),
    (re.compile(r"\bthe\s+hub\b(?!\s+lane\b)", re.I), "Windy Accounts / the Hub lane"),
]
FINGERPRINT = hashlib.sha256("|".join(p.pattern for p, _ in RULES).encode()).hexdigest()[:8]


def path_ok(path: str) -> bool:
    return path.lower().endswith(".md") and not NEVER.search(path) and not path.endswith(GLOSSARY)


def scan_line(path: str, text: str) -> list[tuple[str, str]]:
    """(kind, match) per retired word on one line; kind names the replacement."""
    if ESCAPE in text.lower():
        return []
    out = []
    for pat, use in RULES:
        for m in pat.finditer(text):
            out.append((f"use {use}", m.group(0)))
    return out


def glossary_lines(text: str) -> set[int]:
    """1-based line numbers inside CLOSED <!-- glossary --> blocks (markers included).
    An unclosed block exempts nothing: a stray opener must not silence a whole file."""
    out, start = set(), None
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if s == OPEN and start is None:
            start = n
        elif s == CLOSE and start is not None:
            out.update(range(start, n + 1))
            start = None
    return out


def drop_glossary(findings: list, read) -> list:
    """Remove findings inside glossary blocks. read(path) -> file text at the head, or None."""
    blocks: dict[str, set[int]] = {}
    keep = []
    for f in findings:
        if f.path not in blocks:
            text = read(f.path)
            blocks[f.path] = glossary_lines(text) if text else set()
        if f.line not in blocks[f.path]:
            keep.append(f)
    return keep


def check(repo: str, sha: str, default_branch: str, is_default_head: bool):
    if is_default_head:
        return None  # only what a PR adds is judged; history stays as written
    bare = cg.WORK / f"{repo}.git"
    if not bare.is_dir() or not cg.fetched(bare, sha):  # pushed after the fetch: next cycle
        return None

    def scan():
        found = cg.scan_added(repo, bare, f"refs/heads/{default_branch}", sha, [],
                              line_fn=scan_line, path_ok=path_ok)
        return drop_glossary(found, lambda p: _show(bare, sha, p))

    found = cg.cached_scan(f"birth-pr:{repo}:{sha}:{FINGERPRINT}", scan)
    # Post only when there is something to say: an OK on every PR head is ~130 status
    # creates in one cycle against GitHub's secondary limit (Hub, #53), and WARN never blocks.
    return found or None


def _show(bare: Path, sha: str, path: str) -> str | None:
    try:
        return cg._git(bare, "show", f"{sha}:{path}")
    except Exception:  # noqa: BLE001 — unreadable file: no exemption, the finding stays
        return None


def scan_patch(path: str, patch: str | None, read) -> list:
    """Public-repo PRs: findings from a GitHub PR-files `patch` (unified diff of one file).
    read(path) -> the file text at the head, for glossary blocks; called only if needed."""
    if not patch or not path_ok(path):
        return []
    found, line = [], 0
    for raw in patch.splitlines():
        m = cg.HUNK.match(raw)
        if m:
            line = int(m.group(1))
            continue
        if raw.startswith("\\"):  # "\ No newline at end of file": not a line
            continue
        if raw.startswith("+"):
            for kind, match in scan_line(path, raw[1:]):
                found.append(cg.Finding(path, line, kind, match))
            line += 1
        elif not raw.startswith("-"):
            line += 1
    return drop_glossary(found, read) if found else []


def status_for(findings, whole_tree: bool = False, grant=()):
    """Same contract as compute_guard.status_for: `grant` findings never block."""
    if not findings and grant:
        g, n = grant[0], len(grant)
        return "success", f"⚠ WARN (Grant-owned, not blocking): {n} retired birth term(s) added, e.g. {g.path}:{g.line}"[:140], g
    if not findings:
        return "success", "OK: no retired agent-birth words added", None
    f, n = findings[0], len(findings)
    state = "failure" if MODE == "block" else "success"
    lead = "BLOCKED" if MODE == "block" else "⚠ WARN"
    return state, fit(f"{lead}: {n} retired term(s) added, e.g. {f.path}:{f.line} '{f.match}' -> {f.kind[4:]}"), f


def fit(head: str, limit: int = 140) -> str:
    """GitHub cuts a status description at 140 chars: shorten the head, never the glossary path."""
    tail = f"; see {GLOSSARY}"
    room = limit - len(tail)
    return (head if len(head) <= room else head[:room - 1] + "…") + tail


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] != "lint":
        print(__doc__.strip().splitlines()[-1].strip())
        return 2
    hits = 0
    for p in argv[1:]:
        text = Path(p).read_text(errors="replace")
        inside = glossary_lines(text)
        for n, line in enumerate(text.splitlines(), 1):
            if n in inside or not path_ok(p):
                continue
            for kind, match in scan_line(p, line):
                hits += 1
                print(f"{p}:{n}: '{match}' -> {kind[4:]}")
    print(f"birth-terms: {hits} finding(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
