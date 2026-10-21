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
           inside a <!-- glossary --> ... <!-- /glossary --> block or a fenced
           ``` / ~~~ code block (both judged on the whole file at the PR head, so
           markers outside the changed hunk still count; an UNCLOSED block exempts
           nothing); text inside `inline code`; any line containing "(historical)"

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
# Bump SCAN_VERSION whenever what is exempt changes, so cached scans are redone.
SCAN_VERSION = "2"  # 2: fenced code blocks + inline code exempt
FINGERPRINT = hashlib.sha256(("|".join(p.pattern for p, _ in RULES) + "|v" + SCAN_VERSION).encode()).hexdigest()[:8]
INLINE_CODE = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def path_ok(path: str) -> bool:
    return path.lower().endswith(".md") and not NEVER.search(path) and not path.endswith(GLOSSARY)


def scan_line(path: str, text: str) -> list[tuple[str, str]]:
    """(kind, match) per retired word on one line; kind names the replacement."""
    if ESCAPE in text.lower():
        return []
    text = INLINE_CODE.sub(" ", text)  # `the hub` in code is an identifier or a quote, not prose
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


def fenced_lines(text: str) -> set[int]:
    """1-based line numbers inside CLOSED fenced code blocks (fences included). The closing
    fence uses the same character, at least as many, and nothing after it (CommonMark).
    Unclosed: exempts nothing, like an unclosed glossary block."""
    out, start, fence = set(), None, ""
    for n, line in enumerate(text.splitlines(), 1):
        m = FENCE.match(line)
        if start is None:
            if m:
                start, fence = n, m.group(1)
        elif m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) \
                and not line[m.end():].strip():
            out.update(range(start, n + 1))
            start = None
    return out


def exempt_lines(text: str) -> set[int]:
    return glossary_lines(text) | fenced_lines(text)


class Unread(Exception):
    """A head file could not be read, so its blocks are unknown: the findings stand
    (never a silent exemption) but the result must not be cached as final."""

    def __init__(self, found: list):
        super().__init__("head file unreadable")
        self.found = found


def drop_glossary(findings: list, read, strict: bool = False) -> list:
    """Remove findings inside glossary or fenced code blocks. read(path) -> file text at
    the head, or None. strict: raise Unread(kept findings) if any read failed."""
    blocks: dict[str, set[int]] = {}
    keep, failed = [], False
    for f in findings:
        if f.path not in blocks:
            text = read(f.path)
            failed |= text is None
            blocks[f.path] = exempt_lines(text) if text else set()
        if f.line not in blocks[f.path]:
            keep.append(f)
    if strict and failed:
        raise Unread(keep)
    return keep


def cached(key: str, scan) -> list:
    """cg.cached_scan, except a scan that could not read a head file is used once and
    not cached (it may hold findings a readable file would exempt)."""
    try:
        return cg.cached_scan(key, scan)
    except Unread as e:
        return e.found


def check(repo: str, sha: str, default_branch: str, is_default_head: bool):
    if is_default_head:
        return None  # only what a PR adds is judged; history stays as written
    bare = cg.WORK / f"{repo}.git"
    if not bare.is_dir() or not cg.fetched(bare, sha):  # pushed after the fetch: next cycle
        return None

    def scan():
        found = cg.scan_added(repo, bare, f"refs/heads/{default_branch}", sha, [],
                              line_fn=scan_line, path_ok=path_ok)
        return drop_glossary(found, lambda p: _show(bare, sha, p), strict=True)

    found = cached(f"birth-pr:{repo}:{sha}:{FINGERPRINT}", scan)
    # Post only when there is something to say: an OK on every PR head is ~130 status
    # creates in one cycle against GitHub's secondary limit (Hub, #53), and WARN never blocks.
    return found or None


def _show(bare: Path, sha: str, path: str) -> str | None:
    try:
        return cg._git(bare, "show", f"{sha}:{path}")
    except Exception:  # noqa: BLE001 — unreadable file: no exemption, the finding stays
        return None


def scan_patch(path: str, patch: str | None, read, strict: bool = False) -> list:
    """Public-repo PRs: findings from a GitHub PR-files `patch` (unified diff of one file).
    read(path) -> the file text at the head, for glossary/fenced blocks; called only if
    needed. strict: see drop_glossary."""
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
    return drop_glossary(found, read, strict) if found else []


def unchecked(pr_files: list[dict]) -> int:
    """*.md files in a PR whose diff GitHub left out (too large, or binary-looking): their
    added lines were never read. A pure rename (0 changes) has no added lines."""
    return sum(1 for x in pr_files
               if path_ok(x["f"]) and not x.get("p") and x.get("c") != 0)


def scan_pr(full: str, sha: str, pr_files: list[dict], read) -> list:
    """Findings for one public-repo PR head, cached per head (one PR-files call feeds it;
    head-file reads for blocks happen once per head, not every 5-min cycle)."""
    def scan():
        out, failed = [], False
        for x in pr_files:
            try:
                out += scan_patch(x["f"], x.get("p"), read, strict=True)
            except Unread as e:
                out += e.found
                failed = True
        if failed:
            raise Unread(out)
        return out
    return cached(f"birth-pub:{full}:{sha}:{FINGERPRINT}", scan)


def status_for(findings, whole_tree: bool = False, grant=(), unchecked: int = 0):
    """Same contract as compute_guard.status_for: `grant` findings never block.
    unchecked: *.md files whose diff GitHub omitted (public path); named, never blocking."""
    note = f" (+{unchecked} .md not checked: no diff)" if unchecked else ""
    if not findings and grant:
        g, n = grant[0], len(grant)
        return "success", fit(f"⚠ WARN (Grant-owned, not blocking): {n} retired term(s) added{note}, e.g. {g.path}:{g.line}"), g
    if not findings:
        if unchecked:
            return "success", f"OK in checked lines; {unchecked} .md file(s) not checked (GitHub omitted the diff)", None
        return "success", "OK: no retired agent-birth words added", None
    f, n = findings[0], len(findings)
    state = "failure" if MODE == "block" else "success"
    lead = "BLOCKED" if MODE == "block" else "⚠ WARN"
    return state, fit(f"{lead}: {n} retired term(s) added{note}, e.g. {f.path}:{f.line} '{f.match}' -> {f.kind[4:]}"), f


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
        inside = exempt_lines(text)
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
