"""conftest.py: under CI a skip fails the run; locally it stays a skip."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

SAMPLE = '''
import pytest

@pytest.mark.skipif(True, reason="tool X not installed")
def test_marked():
    pass

def test_imperative():
    pytest.skip("no daemon here")

@pytest.mark.xfail(reason="known bug", strict=False)
def test_xfail():
    assert False

def test_ok():
    pass
'''


def _run(tmp_path: Path, ci: str | None) -> subprocess.CompletedProcess:
    shutil.copy(HERE / "conftest.py", tmp_path / "conftest.py")
    (tmp_path / "test_sample.py").write_text(SAMPLE)
    env = {k: v for k, v in os.environ.items() if k != "CI"}
    if ci is not None:
        env["CI"] = ci
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path)],
                          capture_output=True, text=True, env=env, cwd=tmp_path)


def test_under_ci_every_skip_fails_with_its_reason(tmp_path):
    r = _run(tmp_path, "true")
    assert r.returncode == 1, r.stdout
    # A skipif mark skips in setup, so pytest reports that one as an error; either way the run is red.
    assert "1 failed" in r.stdout and "1 error" in r.stdout, r.stdout
    assert "1 passed" in r.stdout and "1 xfailed" in r.stdout and "skipped" not in r.stdout.splitlines()[-1], r.stdout
    assert "tool X not installed" in r.stdout and "no daemon here" in r.stdout


def test_locally_a_skip_stays_a_skip(tmp_path):
    for ci in (None, "", "false"):
        r = _run(tmp_path, ci)
        assert r.returncode == 0, r.stdout
        assert "2 skipped" in r.stdout, r.stdout
