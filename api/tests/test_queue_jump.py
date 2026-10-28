"""scripts/queue_jump.sh: one waiting job to the front, and an automatic revert if anything else
is picked first (Boss 10-27: only GO'd same-day prod deploys jump the queue)."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "queue_jump.sh"
FAKE_WGQ = """#!{py}
import os, sqlite3, sys
db = sqlite3.connect(os.environ["FAKE_DB"])
cur = db.execute(sys.stdin.read())
rows = cur.fetchall() if cur.description else []
db.commit()
for r in rows:
    print("|".join("" if v is None else str(v) for v in r))
"""


def _setup(tmp_path: Path) -> tuple[Path, dict]:
    db = tmp_path / "q.db"
    c = sqlite3.connect(db)
    c.execute("create table action_run_job (id integer primary key, status int, task_id int, updated int)")
    c.execute("create table action_task (id integer primary key, job_id int)")
    c.executemany("insert into action_run_job values (?,?,?,?)",
                  [(1, 5, 0, 100), (2, 5, 0, 110), (3, 6, 77, 90), (4, 5, 78, 95), (9, 5, 0, 500)])
    c.execute("insert into action_task values (77, 3)")
    c.commit()
    wgq = tmp_path / "wg-q"
    wgq.write_text(FAKE_WGQ.format(py=sys.executable))
    wgq.chmod(0o755)
    env = {**os.environ, "WGQ": str(wgq), "FAKE_DB": str(db), "QUEUE_JUMP_POLL": "0.1", "QUEUE_JUMP_WAIT": "20"}
    return db, env


def _updated(db: Path, job: int) -> int:
    return sqlite3.connect(db).execute("select updated from action_run_job where id=?", (job,)).fetchone()[0]


def _runner_picks(db: Path, job: int) -> None:
    """Wait until the script has moved job 9, then let a 'runner' pick `job`."""
    for _ in range(200):
        if _updated(db, 9) != 500:
            break
        time.sleep(0.05)
    c = sqlite3.connect(db)
    cur = c.execute("insert into action_task (job_id) values (?)", (job,))
    c.execute("update action_run_job set status=6, task_id=? where id=?", (cur.lastrowid, job))  # one tx, like Gitea
    c.commit()


def test_the_job_jumps_and_is_kept_when_it_is_picked_next(tmp_path):
    db, env = _setup(tmp_path)
    p = subprocess.Popen(["bash", str(SCRIPT), "9"], env=env, stdout=subprocess.PIPE, text=True)
    _runner_picks(db, 9)
    out, _ = p.communicate(timeout=30)
    assert p.returncode == 0 and "OK: job 9 was picked: task" in out, out
    assert _updated(db, 9) == 99  # one below the oldest waiting (100)


def test_it_reverts_when_another_job_is_picked_first(tmp_path):
    db, env = _setup(tmp_path)
    p = subprocess.Popen(["bash", str(SCRIPT), "9"], env=env, stdout=subprocess.PIPE, text=True)
    _runner_picks(db, 1)
    out, _ = p.communicate(timeout=30)
    assert p.returncode == 1 and "REVERTED: job 1 was picked first" in out, out
    assert _updated(db, 9) == 500


def test_it_reverts_when_nothing_is_picked_in_time(tmp_path):
    db, env = _setup(tmp_path)
    r = subprocess.run(["bash", str(SCRIPT), "9"], env={**env, "QUEUE_JUMP_WAIT": "1"},
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 1 and "nothing was picked" in r.stdout, r.stdout
    assert _updated(db, 9) == 500


def test_it_refuses_a_job_that_is_not_waiting_and_unclaimed(tmp_path):
    db, env = _setup(tmp_path)
    # 3 = running; 4 = still "waiting" but already claimed by a task; 404 = no such job
    for bad in ("3", "4", "404", "9; drop table action_task"):
        r = subprocess.run(["bash", str(SCRIPT), bad], env=env, capture_output=True, text=True, timeout=30)
        assert r.returncode == 2 and "refusing" in r.stdout, (bad, r.stdout)
    assert _updated(db, 3) == 90 and _updated(db, 4) == 95 and _updated(db, 9) == 500


def test_killed_mid_watch_it_still_reverts(tmp_path):
    """Hub #87: Ctrl-C or kill during the watch must not leave the job jumped."""
    import signal
    db, env = _setup(tmp_path)
    p = subprocess.Popen(["bash", str(SCRIPT), "9"], env=env, stdout=subprocess.PIPE, text=True)
    first = p.stdout.readline()                     # "...watching for the next pick": the loop is running
    assert "watching" in first and _updated(db, 9) == 99, first
    p.send_signal(signal.SIGTERM)
    out, _ = p.communicate(timeout=30)
    assert p.returncode == 130 and "REVERTED on exit" in first + out, first + out
    assert _updated(db, 9) == 500


def test_a_job_cancelled_while_waiting_is_a_failure_not_an_ok(tmp_path):
    """10-28: Gitea cancelled a waiting canary job and the script reported "picked second"."""
    db, env = _setup(tmp_path)
    p = subprocess.Popen(["bash", str(SCRIPT), "9"], env=env, stdout=subprocess.PIPE, text=True)
    for _ in range(200):
        if _updated(db, 9) != 500:
            break
        time.sleep(0.05)
    c = sqlite3.connect(db)
    c.execute("insert into action_task (job_id) values (1)")              # another job picked
    c.execute("update action_run_job set status=3 where id=9")            # ours CANCELLED, no task
    c.commit()
    out, _ = p.communicate(timeout=30)
    assert p.returncode == 1 and "cancelled, not picked" in out, out


def test_picked_second_in_the_same_instant_is_reported_as_ok(tmp_path):
    db, env = _setup(tmp_path)
    p = subprocess.Popen(["bash", str(SCRIPT), "9"], env=env, stdout=subprocess.PIPE, text=True)
    for _ in range(200):
        if _updated(db, 9) != 500:
            break
        time.sleep(0.05)
    c = sqlite3.connect(db)
    t1 = c.execute("insert into action_task (job_id) values (1)").lastrowid
    t9 = c.execute("insert into action_task (job_id) values (9)").lastrowid
    c.execute("update action_run_job set status=6, task_id=? where id=1", (t1,))
    c.execute("update action_run_job set status=6, task_id=? where id=9", (t9,))
    c.commit()
    out, _ = p.communicate(timeout=30)
    assert p.returncode == 0 and "OK: job 9 was picked" in out, out          # "picked" or "picked second": it ran
