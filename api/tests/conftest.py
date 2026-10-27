"""Under CI, a skipped test is a failed test (Boss 10-27: CI runs the WHOLE suite).

A skip guard like `skipif(not shutil.which("age"))` is right on a laptop, but on the
CI gate it turned 3 backup-encryption tests into silent passes for weeks: the job
image had no `age`. With CI set, every skip fails, naming its reason, so a missing
tool shows up red instead of quietly shrinking the gate.
"""

from __future__ import annotations

import os

import pytest


def _strict() -> bool:
    return os.environ.get("CI", "").lower() in {"1", "true", "yes"}


def _fail(rep) -> None:
    reason = rep.longrepr[2] if isinstance(rep.longrepr, tuple) else str(rep.longrepr)
    rep.outcome = "failed"
    rep.longrepr = f"skipped under CI (a skip is a hole in the gate): {reason}"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Skips in setup (skipif marks, fixtures) and in the test body."""
    outcome = yield
    rep = outcome.get_result()
    if _strict() and rep.skipped and not hasattr(rep, "wasxfail"):
        _fail(rep)


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    """Skips while COLLECTING a module (module-level pytest.skip(allow_module_level=True),
    pytest.importorskip): these drop a whole file and never reach runtest_makereport (Hub, #79)."""
    outcome = yield
    rep = outcome.get_result()
    if _strict() and rep.skipped:
        _fail(rep)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """Backstop for any skip the hooks above can't see, e.g. a pytest.skip in a SUBDIRECTORY's
    conftest.py, which drops that whole directory before this file's collect hook runs for it
    (Hub, #79 follow-up). The hooks above give each skip a named failure; this makes sure no
    skip at all leaves a CI run green."""
    tr = session.config.pluginmanager.get_plugin("terminalreporter")
    skipped = (tr.stats.get("skipped") if tr else None) or []
    if _strict() and skipped and session.exitstatus == 0:
        session.exitstatus = 1
        tr.write_line(f"FAILED under CI: {len(skipped)} skip(s) got past the per-test checks "
                      "(a skip is a hole in the gate):", red=True)
        for rep in skipped:
            where = getattr(rep, "nodeid", "") or "?"
            reason = rep.longrepr[2] if isinstance(rep.longrepr, tuple) else str(rep.longrepr)
            tr.write_line(f"  {where}: {reason}", red=True)
