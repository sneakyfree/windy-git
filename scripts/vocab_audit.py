#!/usr/bin/env python3
"""D-9 vocabulary audit (codon G12.6).

"Git" is never a countable noun. There is no such thing as "a Git". Git is the
program; a moment in time is a *commit*; user-facing it is a *version* or a
*save point*; the container is a *repo*.

This is not pedantry. It is the tell that separates people who use git from
people who have read about it, and it will cost credibility with exactly the
developer audience this product is built for. There is a second edge: *git* is
British slang for a contemptible person -- which is why Torvalds chose it, self
-deprecatingly -- so "tracking your Gits" reads badly to a Commonwealth ear.

Doctrine files are exempt because they QUOTE the forbidden forms in order to
forbid them. Any other file may exempt a single line with a `vocab-ok` marker.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# These files define the law and must quote what they prohibit.
EXEMPT_FILES = {
    "DNA_STRAND_MASTER_PLAN.md",
    "README.md",
    "AGENTS.md",
    "scripts/vocab_audit.py",
    "api/tests/test_d09_vocabulary.py",
}

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".ruff_cache", ".mypy_cache",
             ".pytest_cache", "node_modules", "LICENSES", "patches"}

SCAN_SUFFIXES = {".py", ".md", ".html", ".js", ".ts", ".jsx", ".tsx", ".json",
                 ".yaml", ".yml", ".toml", ".txt", ".ini"}

# "a Git" / "an Git" / "the Git" as a countable thing, plus the plural.
# Negative lookahead keeps GitHub, Gitea, GitLab, Gitpod and "Git " as a proper
# noun in phrases like "Windy Git is".
PATTERNS = [
    (re.compile(r"\b(?:a|an|one|each|every|another)\s+Git\b(?!Hub|ea|Lab|pod|Kraken)"),
     'countable "a Git"'),
    (re.compile(r"\bGits\b(?!Hub|ea)"), 'plural "Gits"'),
    (re.compile(r"\b(?:my|your|their|his|her|its)\s+Git\b(?!Hub|ea|Lab|pod)"),
     'possessive "your Git"'),
    (re.compile(r"\bgits\b"), 'lowercase plural "gits"'),
]


def violations() -> list[tuple[str, int, str, str]]:
    found: list[tuple[str, int, str, str]] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel in EXEMPT_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if "vocab-ok" in line:
                continue
            for pattern, label in PATTERNS:
                if pattern.search(line):
                    found.append((rel, lineno, label, line.strip()[:100]))
    return found


def main() -> int:
    found = violations()
    if not found:
        print("vocab audit: clean (D-9)")
        return 0
    print("D-9 VOCABULARY LAW VIOLATION -- 'Git' is not a countable noun.\n")
    for rel, lineno, label, line in found:
        print(f"  {rel}:{lineno}  {label}\n      {line}")
    print("\nSay 'a commit' (developers) or 'a version' / 'a save point' (everyone else).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
