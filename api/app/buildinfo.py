"""Deployment identity (I-12).

Nine of twelve live services in this ecosystem cannot name the commit they are
running. One reports *another repo's* commit. The root cause found on 2026-08-10
was hardcoded `COMMIT_SHA` pins in `/opt/*/.env` that OVERRIDE the build arg, so a
redeploy keeps reporting the old sha until a human hand-edits the file.

The fix here is structural, not procedural:

  * the sha is baked into the image at build time (Docker ARG -> this module);
  * a runtime `COMMIT_SHA` environment variable is **IGNORED**, loudly;
  * in a dev worktree with nothing baked, we read git directly and SAY SO in
    `source`, rather than reporting a value we cannot stand behind (I-8).

`make check` fails if /version disagrees with `git rev-parse HEAD` in CI.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

# Rewritten at image build time by the Dockerfile. Do not edit by hand, and do
# not "helpfully" default it to something plausible.
BAKED_COMMIT_SHA: str = ""
BAKED_BUILT_AT: str = ""

VERSION = "0.1.0"


@dataclass(frozen=True)
class BuildInfo:
    version: str
    commit_sha: str | None
    built_at: str | None
    source: str  # "baked" | "git-worktree" | "unknown"


def _git_head() -> str | None:
    try:
        root = Path(__file__).resolve().parents[2]
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:  # pragma: no cover - defensive
        return None


@lru_cache
def get_build_info() -> BuildInfo:
    override = os.environ.get("COMMIT_SHA")

    if BAKED_COMMIT_SHA:
        if override and override != BAKED_COMMIT_SHA:
            log.warning(
                "IGNORING COMMIT_SHA environment override (%s). This service "
                "reports the sha baked into its own artifact (%s). See I-12 — an "
                "env pin overriding the build arg is exactly why nine sibling "
                "services misreport their commit.",
                override[:12],
                BAKED_COMMIT_SHA[:12],
            )
        return BuildInfo(VERSION, BAKED_COMMIT_SHA, BAKED_BUILT_AT or None, "baked")

    head = _git_head()
    if head:
        if override:
            log.warning(
                "IGNORING COMMIT_SHA environment override (%s); reading the "
                "worktree instead.",
                override[:12],
            )
        return BuildInfo(VERSION, head, None, "git-worktree")

    # Nothing baked, no git. Say so. Do not invent a sha (I-8).
    return BuildInfo(VERSION, None, None, "unknown")
