"""conftest.py: under CI a skip fails the run; locally it stays a skip."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

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


# Skipped while COLLECTING: the whole module vanishes unless conftest catches it (Hub, #79).
MODULE_SKIP = 'import pytest\npytest.skip("tool Y not installed", allow_module_level=True)\ndef test_x():\n    pass\n'
IMPORT_SKIP = 'import pytest\npytest.importorskip("no_such_module_windygit")\ndef test_y():\n    pass\n'


def _run(tmp_path: Path, ci: str | None, files: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    shutil.copy(HERE / "conftest.py", tmp_path / "conftest.py")
    for name, body in (files or {"test_sample.py": SAMPLE}).items():
        (tmp_path / name).write_text(body)
    env = {k: v for k, v in os.environ.items() if k != "CI"}
    if ci is not None:
        env["CI"] = ci
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path)],
                          capture_output=True, text=True, env=env, cwd=tmp_path)


def test_under_ci_every_skip_fails_with_its_reason(tmp_path):
    r = _run(tmp_path, "true")
    assert r.returncode == 1, r.stdout
    # A skipif mark skips in setup, so pytest reports that one as an error; either way the run is red.
    last = r.stdout.splitlines()[-1]
    assert "1 failed" in last and "1 error" in last and "skipped" not in last, r.stdout
    assert "1 passed" in last and "1 xfailed" in last, r.stdout
    assert "tool X not installed" in r.stdout and "no daemon here" in r.stdout


COLLECT = {"test_ok.py": "def test_ok():\n    pass\n", "test_module_skip.py": MODULE_SKIP, "test_import_skip.py": IMPORT_SKIP}


def test_under_ci_a_module_skipped_at_collection_fails_too(tmp_path):
    """Hub #79: without the collect hook this was "1 passed, 2 skipped", rc 0."""
    r = _run(tmp_path, "true", COLLECT)
    assert r.returncode != 0, r.stdout
    assert "2 errors during collection" in r.stdout, r.stdout
    assert "tool Y not installed" in r.stdout and "no_such_module_windygit" in r.stdout
    r = _run(tmp_path, None, COLLECT)
    assert r.returncode == 0 and "1 passed, 2 skipped" in r.stdout, r.stdout


def test_locally_a_skip_stays_a_skip(tmp_path):
    for ci in (None, "", "false"):
        r = _run(tmp_path, ci)
        assert r.returncode == 0, r.stdout
        assert "2 skipped" in r.stdout, r.stdout


def test_check_yml_sets_ci_on_the_tests_step():
    """The hooks above only bite when CI is set; don't rely on act_runner's defaults (Hub, #79)."""
    wf = yaml.safe_load((HERE.parents[1] / ".gitea" / "workflows" / "check.yml").read_text())
    steps = [s for job in wf["jobs"].values() for s in job.get("steps", []) if s.get("name") == "tests"]
    assert steps and all(str((s.get("env") or {}).get("CI")).lower() == "true" for s in steps), steps
