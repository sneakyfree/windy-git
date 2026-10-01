#!/usr/bin/env python3
"""lockbox-names: DISCOVER what the lockbox holds without reading it (Boss rule 10-01).

  lockbox-names [REGEX]        (case-insensitive; matches the section heading or the label)

Prints one row per entry: SECTION HEADING | LABEL | kind | resolvable
  kind        env   = `KEY=value` line            md = `- **`KEY`**: `value`` line
              label = a bold prose label (`**Password (X):** ...`)  file = secrets/**/*.env key
  resolvable  yes   = `lockbox-get LABEL FILE` returns exactly one value
              dup   = defined with 2+ different values (lockbox-get refuses)
              no    = a prose-only label, or not an exact key

NEVER prints a value or any prose after a label. A label or heading that itself looks
like a secret (secret_shapes) is replaced by <secret-shaped>. Reads the COMMITTED lockbox at
origin/main (like lockbox-get; LOCKBOX_REF=<ref> or WORKTREE overrides). Memory only, stdout only.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import secret_shapes as ss  # noqa: E402

REPO = os.environ.get("LOCKBOX_REPO", os.path.expanduser("~/kit-army-config"))
REF = os.environ.get("LOCKBOX_REF", "origin/main")
HEAD = re.compile(r"^#{1,6}\s+(.*\S)\s*$")
ENV = re.compile(r"^([A-Z][A-Z0-9_]{2,})=(.*)$")
MD = re.compile(r"^\s*[-*]?\s*\*\*`([A-Za-z0-9_]+)`\*\*\s*:\s*`([^`]+)`")
LABEL = re.compile(r"\*\*([^*`]{2,70}?)\*\*")


def git(*a: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", REPO, *a], capture_output=True, text=True, errors="ignore")


def read_sources() -> dict[str, str]:
    """{path: text} for ACCESS_LOCKBOX.md and secrets/**/*.env."""
    if REF == "WORKTREE":
        out = {}
        for p in [Path(REPO, "ACCESS_LOCKBOX.md"), *Path(REPO, "secrets").rglob("*.env")]:
            if p.is_file():
                out[str(p.relative_to(REPO))] = p.read_text(errors="ignore")
        return out
    if REF.startswith("origin/"):
        git("fetch", "-q", "origin", REF.split("/", 1)[1])
    names = ["ACCESS_LOCKBOX.md"] + [
        p for p in git("ls-tree", "-r", "--name-only", REF, "--", "secrets").stdout.splitlines() if p.endswith(".env")]
    out = {}
    for n in names:
        r = git("show", f"{REF}:{n}")
        if r.returncode == 0:
            out[n] = r.stdout
    return out


def safe(text: str, limit: int = 70) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return "<secret-shaped>" if ss.find(text) else text[:limit]


def h(v: str) -> str:
    return hashlib.sha256(v.strip().strip('"').strip("'").encode()).hexdigest()[:16]


def collect(src: dict[str, str]):
    """(rows, values) where values[KEY] = {hash,...} for resolvability; nothing printed from it."""
    rows, values = [], {}
    for path, text in src.items():
        section = path
        for line in text.splitlines():
            m = HEAD.match(line) if path.endswith(".md") else None
            if m:
                section = safe(m.group(1), 90)
                continue
            m = ENV.match(line)
            if m:
                values.setdefault(m.group(1), set()).add(h(m.group(2)))
                rows.append((section, m.group(1), "file" if path.startswith("secrets/") else "env"))
                continue
            m = MD.match(line)
            if m:
                values.setdefault(m.group(1), set()).add(h(m.group(2)))
                rows.append((section, m.group(1), "md"))
                continue
            if path.endswith(".md"):
                mm = LABEL.search(line)
                if mm and not mm.group(1).startswith("http"):
                    rows.append((section, safe(mm.group(1)), "label"))
    return rows, values


def resolvable(label: str, kind: str, values) -> str:
    if kind not in ("env", "md", "file"):
        return "no"
    n = len(values.get(label, ()))
    return "yes" if n == 1 else "dup" if n > 1 else "no"


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    rx = re.compile(argv[0], re.I) if argv else None
    src = read_sources()
    if not src:
        print("lockbox-names: cannot read the lockbox")
        return 2
    rows, values = collect(src)
    seen, n = set(), 0
    for section, label, kind in rows:
        if rx and not (rx.search(section) or rx.search(label)):
            continue
        key = (section, label, kind)
        if key in seen:
            continue
        seen.add(key)
        n += 1
        print(f"{section} | {label} | {kind} | {resolvable(label, kind, values)}")
    print(f"# {n} entr{'y' if n == 1 else 'ies'}; names only, values never printed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except re.error:
        print("lockbox-names: bad regex")
        sys.exit(2)
    except Exception as e:  # never a traceback
        print(f"lockbox-names: error: {type(e).__name__}")
        sys.exit(2)
