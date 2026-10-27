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


def test_under_ci_a_subdirectory_conftest_skip_fails_too(tmp_path):
    """Hub #79 follow-up: a skip in a sub-directory's conftest.py drops that directory before
    the root collect hook runs for it; only the sessionfinish backstop catches it."""
    (tmp_path / "sub").mkdir()
    files = {"test_ok.py": "def test_ok():\n    pass\n",
             "sub/conftest.py": 'import pytest\npytest.skip("tool Z not installed", allow_module_level=True)\n',
             "sub/test_z.py": "def test_z():\n    pass\n"}
    r = _run(tmp_path, "true", files)
    assert r.returncode == 1, r.stdout
    assert "FAILED under CI: 1 skip(s)" in r.stdout and "tool Z not installed" in r.stdout, r.stdout
    r = _run(tmp_path, None, files)
    assert r.returncode == 0 and "1 passed, 1 skipped" in r.stdout, r.stdout


def test_check_yml_sets_ci_on_the_tests_step():
    """The hooks above only bite when CI is set; don't rely on act_runner's defaults (Hub, #79)."""
    wf = yaml.safe_load((HERE.parents[1] / ".gitea" / "workflows" / "check.yml").read_text())
    steps = [s for job in wf["jobs"].values() for s in job.get("steps", []) if s.get("name") == "tests"]
    assert steps and all(str((s.get("env") or {}).get("CI")).lower() == "true" for s in steps), steps


LIVE = 'import pytest\n\n@pytest.mark.skipif(True, reason="needs ETERNITAS_URL")\ndef test_live():\n    pass\n'
LIVE_ENTRY = "test_live.py  # owner: Windy Cloud; reason: needs live Eternitas; run: ETERNITAS_URL=... pytest test_live.py\n"


def test_under_ci_only_the_live_only_list_may_skip(tmp_path):
    """Boss 10-27 20:03Z: named live-only tests may skip; every other skip still fails."""
    files = {"test_live.py": LIVE, "test_other.py": 'import pytest\n\ndef test_o():\n    pytest.skip("tool W missing")\n',
             "test_ok.py": "def test_ok():\n    pass\n", "LIVE_ONLY.txt": "# live-only tests\n\n" + LIVE_ENTRY}
    r = _run(tmp_path, "true", files)
    assert r.returncode == 1, r.stdout
    assert "tool W missing" in r.stdout and "1 failed" in r.stdout.splitlines()[-1], r.stdout
    assert "1 live-only skip(s) allowed by LIVE_ONLY.txt" in r.stdout and "test_live.py::test_live" in r.stdout, r.stdout
    (tmp_path / "test_other.py").unlink()
    r = _run(tmp_path, "true", {k: v for k, v in files.items() if k != "test_other.py"})
    assert r.returncode == 0 and "1 passed, 1 skipped" in r.stdout, r.stdout
    assert "1 live-only skip(s) allowed" in r.stdout, r.stdout


def test_a_live_only_entry_must_name_owner_reason_and_run(tmp_path):
    files = {"test_live.py": LIVE, "LIVE_ONLY.txt": "test_live.py  # owner: Windy Cloud; reason: needs live Eternitas\n"}
    r = _run(tmp_path, "true", files)
    assert r.returncode != 0 and "LIVE_ONLY.txt:1: needs" in (r.stdout + r.stderr), r.stdout + r.stderr
    r = _run(tmp_path, None, files)  # locally the list isn't read at all
    assert r.returncode == 0 and "1 skipped" in r.stdout, r.stdout


def test_a_live_only_entry_covers_its_own_file_or_directory_only():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_nsconf", HERE / "conftest.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m._covers("tests/live", "tests/live/test_a.py::test_x")
    assert m._covers("tests/live/", "tests/live/test_a.py")
    assert m._covers("tests/test_e.py", "tests/test_e.py::T::test_y")
    assert m._covers("tests/test_e.py::test_y", "tests/test_e.py::test_y")
    assert not m._covers("tests/live", "tests/live_cache.py::test_z")
    assert not m._covers("tests/test_e.py", "tests/test_e.pyx")
    assert not m._covers("tests/test_e.py::test_y", "tests/test_e.py::test_y2")
