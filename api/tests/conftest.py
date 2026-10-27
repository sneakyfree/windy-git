"""Under CI, a skipped test is a failed test (Boss 10-27: CI runs the WHOLE suite).

A skip guard like `skipif(not shutil.which("age"))` is right on a laptop, but on the
CI gate it turned 3 backup-encryption tests into silent passes for weeks: the job
image had no `age`. With CI set, every skip fails, naming its reason, so a missing
tool shows up red instead of quietly shrinking the gate.

The ONE exception (Boss 10-27 20:03Z): tests that need a live outside service, listed
BY NAME in LIVE_ONLY.txt at the pytest rootdir. One entry per line: a nodeid prefix,
then `# owner: ...; reason: ...; run: <command that runs them>`. All three fields are
required (a malformed entry stops a CI run). A listed test may skip; every other skip
fails. Allowed skips are still named at the end of the run. No file = no exceptions.

This file is the fleet drop-in: copy it as-is into a repo's root conftest.py and set
CI: "true" on the pytest step. The sessionfinish backstop reads pytest's terminal
reporter, so don't run CI with `-p no:terminal` (Hub, #82).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

LIVE_ONLY_FILE = "LIVE_ONLY.txt"
_ENTRY = re.compile(r"^(?P<prefix>\S+)\s+#\s*(?P<meta>.*)$")
_live_only: list[str] = []


def _strict() -> bool:
    return os.environ.get("CI", "").lower() in {"1", "true", "yes"}


def load_live_only(path: Path) -> list[str]:
    """Nodeid prefixes from LIVE_ONLY.txt. Every entry must name owner, reason and run."""
    if not path.is_file():
        return []
    out = []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _ENTRY.match(line)
        meta = m.group("meta").lower() if m else ""
        if not (m and all(f"{k}:" in meta for k in ("owner", "reason", "run"))):
            raise pytest.UsageError(f"{path.name}:{n}: needs '<nodeid prefix>  # owner: ...; reason: ...; run: ...'")
        out.append(m.group("prefix"))
    return out


def _covers(prefix: str, nodeid: str) -> bool:
    """A file or test entry covers itself and what's inside it (`::`); a directory entry
    covers what's under it (`/`). Never a bare string prefix: tests/live must not cover
    tests/live_cache.py."""
    return nodeid == prefix or nodeid.startswith(prefix + "::") or nodeid.startswith(prefix.rstrip("/") + "/")


def _allowed(nodeid: str) -> bool:
    return any(_covers(p, nodeid) for p in _live_only)


def pytest_configure(config):
    _live_only[:] = load_live_only(Path(config.rootpath) / LIVE_ONLY_FILE) if _strict() else []


def _reason(rep) -> str:
    return rep.longrepr[2] if isinstance(rep.longrepr, tuple) else str(rep.longrepr)


def _fail(rep) -> None:
    rep.outcome = "failed"
    rep.longrepr = f"skipped under CI (a skip is a hole in the gate): {_reason(rep)}"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Skips in setup (skipif marks, fixtures) and in the test body."""
    outcome = yield
    rep = outcome.get_result()
    if _strict() and rep.skipped and not hasattr(rep, "wasxfail") and not _allowed(rep.nodeid):
        _fail(rep)


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    """Skips while COLLECTING a module (module-level pytest.skip(allow_module_level=True),
    pytest.importorskip): these drop a whole file and never reach runtest_makereport (Hub, #79)."""
    outcome = yield
    rep = outcome.get_result()
    if _strict() and rep.skipped and not _allowed(rep.nodeid):
        _fail(rep)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """Backstop for any skip the hooks above can't see, e.g. a pytest.skip in a SUBDIRECTORY's
    conftest.py, which drops that whole directory before this file's collect hook runs for it
    (Hub, #79 follow-up). The hooks above give each skip a named failure; this makes sure no
    skip outside LIVE_ONLY.txt leaves a CI run green, and names the allowed ones too."""
    if not _strict():
        return
    tr = session.config.pluginmanager.get_plugin("terminalreporter")
    skipped = (tr.stats.get("skipped") if tr else None) or []
    allowed = [r for r in skipped if _allowed(getattr(r, "nodeid", "") or "")]
    holes = [r for r in skipped if r not in allowed]
    if allowed:
        tr.write_line(f"{len(allowed)} live-only skip(s) allowed by {LIVE_ONLY_FILE} (run them before any change they guard):")
        for rep in allowed:
            tr.write_line(f"  {rep.nodeid}: {_reason(rep)}")
    if holes and session.exitstatus == 0:
        session.exitstatus = 1
        tr.write_line(f"FAILED under CI: {len(holes)} skip(s) got past the per-test checks "
                      "(a skip is a hole in the gate):", red=True)
        for rep in holes:
            tr.write_line(f"  {getattr(rep, 'nodeid', '') or '?'}: {_reason(rep)}", red=True)
