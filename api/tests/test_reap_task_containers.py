"""scripts/reap_task_containers.sh against a fake `docker` (dind ps/rm + the Gitea DB)."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "reap_task_containers.sh"

PS = """aaa111aaa111 GITEA-ACTIONS-TASK-100-WORKFLOW-CI-JOB-test-abc
bbb222bbb222 GITEA-ACTIONS-TASK-100-WORKFLOW-CI-JOB-test-abc-postgres-16
ccc333ccc333 GITEA-ACTIONS-TASK-200-WORKFLOW-CI-JOB-build-def
ddd444ddd444 GITEA-ACTIONS-TASK-300_WORKFLOW-CI-JOB-x
eee555eee555 windy-something-else
fff666fff666 GITEA-ACTIONS-TASK-;drop-table
"""


def _world(tmp_path: Path, finished: str, rm_fails: str = "") -> tuple[dict, Path]:
    log = tmp_path / "log"
    fake = tmp_path / "bin" / "docker"
    fake.parent.mkdir()
    (tmp_path / "ps").write_text(PS)
    fake.write_text(f"""#!/usr/bin/env bash
echo "$*" >> {log}
case "$*" in
  *" ps -a "*) cat {tmp_path / 'ps'} ;;
  *"windy-git-db-1"*) cat > {tmp_path / 'sql'}; printf '{finished}' ;;
  *" rm -f {rm_fails}"*) [ -n "{rm_fails}" ] && exit 1 ;;
esac
exit 0
""")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return {"PATH": f"{fake.parent}:{os.environ['PATH']}"}, log


def _run(env, **extra):
    return subprocess.run(["bash", str(SCRIPT)], env={**env, **extra}, capture_output=True, text=True)


def test_removes_only_containers_of_tasks_the_db_says_finished(tmp_path):
    env, log = _world(tmp_path, "100\n300\n")
    r = _run(env)
    assert r.returncode == 0, r.stderr
    removed = [line.split()[-1] for line in log.read_text().splitlines() if " rm -f " in line]
    assert removed == ["aaa111aaa111", "bbb222bbb222", "ddd444ddd444"]     # task 200 still running
    assert "[reaper] removed 3 container(s) of finished jobs" in r.stdout
    sql = (tmp_path / "sql").read_text()
    assert "id in (100,200,300)" in sql and "- 30 * 60" in sql               # only parsed digit ids
    assert "drop" not in sql


def test_nothing_finished_means_nothing_removed(tmp_path):
    env, log = _world(tmp_path, "")
    r = _run(env)
    assert r.returncode == 0 and "removed 0 container(s)" in r.stdout
    assert " rm -f " not in log.read_text()


def test_a_stuck_removal_is_counted_not_fatal(tmp_path):
    env, _ = _world(tmp_path, "100\n", rm_fails="aaa111aaa111")
    r = _run(env)
    assert r.returncode == 0
    assert "[reaper] removed 1 container(s) of finished jobs, 1 could not be removed" in r.stdout


def test_age_must_be_a_whole_number(tmp_path):
    env, log = _world(tmp_path, "100\n")
    r = _run(env, REAP_AFTER_MIN="30; drop table x")
    assert r.returncode == 2 and not log.exists()
    r = _run(env, REAP_AFTER_MIN="45")
    assert r.returncode == 0 and "- 45 * 60" in (tmp_path / "sql").read_text()


def test_dry_run_names_but_never_removes(tmp_path):
    env, log = _world(tmp_path, "100\n")
    r = _run(env, REAP_DRY_RUN="1")
    assert r.returncode == 0 and " rm -f " not in log.read_text()
    assert "[reaper] would remove container aaa111aaa111 of finished task 100" in r.stdout
    assert "[reaper] DRY RUN: would remove 2 container(s) of finished jobs" in r.stdout
