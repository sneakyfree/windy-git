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


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if _strict() and rep.skipped and not hasattr(rep, "wasxfail"):
        reason = rep.longrepr[2] if isinstance(rep.longrepr, tuple) else str(rep.longrepr)
        rep.outcome = "failed"
        rep.longrepr = f"skipped under CI (a skip is a hole in the gate): {reason}"
