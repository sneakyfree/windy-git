"""scripts/cancel_superseded.py, HEAL + RELEASE (11-13): a DB-write cancel left the run's attempt row WAITING (the
one-column HAS_ATTEMPTS answer never got past psql()'s "|" filter), Gitea 28 counted it as a holder of the
concurrency group, and the next main run of that group sat BLOCKED forever (windy-pro 44273, windy-chat 44269)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("cancel_superseded_r", ROOT / "scripts" / "cancel_superseded.py")
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)


def _psql_answer(monkeypatch, stdout):
    class R:
        pass
    r = R()
    r.stdout = stdout
    monkeypatch.setattr(cs.subprocess, "run", lambda *a, **k: r)
    return cs.psql(cs.HAS_ATTEMPTS_SQL)


def test_the_attempt_check_survives_the_psql_parser(monkeypatch):
    # the bug: a one-column answer is dropped by psql()'s "|" filter, so the attempt close never ran
    assert _psql_answer(monkeypatch, "t\n") == []
    # the fix: two columns, read back as true; false and an empty answer stay false
    assert cs._has_attempts(lambda sql: _psql_answer(monkeypatch, "attempts|t\n")) is True
    assert cs._has_attempts(lambda sql: _psql_answer(monkeypatch, "attempts|f\n")) is False
    assert cs._has_attempts(lambda sql: []) is False
    assert "'attempts'" in cs.HAS_ATTEMPTS_SQL


def test_heal_closes_only_attempts_of_cancelled_runs_whose_jobs_are_all_cancelled():
    sql = " ".join(cs.HEAL_ATTEMPTS_SQL.split())
    assert "r.status = 3" in sql                                              # the RUN is cancelled
    assert re.findall(r"a\.status in \(([^)]*)\)", sql) == ["5, 7, 9"]        # never running 6 / cancelling 8
    assert "j.run_attempt_id = a.id and j.status <> 3" in sql                 # every job of THAT attempt cancelled
    assert "returning" in sql


def test_release_sql_mirrors_gitea_and_refuses_what_a_db_write_cannot_judge():
    sql = " ".join(cs.RELEASE_SQL.split())
    assert "a.status = 7 and r.status = 7 and not r.need_approval" in sql     # blocked, never awaiting approval
    assert "r.latest_attempt_id = a.id" in sql                                 # the run's current attempt only
    assert "h.status in (5, 6, 8)" in sql and "hj.status in (5, 6, 8)" in sql  # Gitea's holders
    assert "h.run_id <> a.run_id" in sql and "hj.run_id <> a.run_id" in sql    # its own rows never block it
    assert "raw_concurrency" in sql and "if:" in sql                           # job-level concurrency / if: refused
    assert "order by repo_id, concurrency_group, run_id desc" in sql           # the NEWEST per group only
    assert "then 5 else 9 end" in sql                                          # no needs -> waiting, needs -> pending
    assert "j.status = 7" in sql and "a.status = 7" in sql                     # re-checked in each UPDATE


def _fake(rows_release, has=True):
    seen = []

    def query(sql):
        seen.append(sql)
        if sql is cs.HAS_ATTEMPTS_SQL:
            return [["attempts", "t"]] if has else [["attempts", "f"]]
        if sql is cs.HEAL_ATTEMPTS_SQL:
            return [["healed", "6870", "41489"], ["healed", "5440", "42822"]]
        if sql in (cs.RELEASE_SQL, cs.RELEASE_DRY_SQL):
            return rows_release
        return []
    return query, seen


def test_release_is_off_by_default_but_the_heal_always_runs(monkeypatch):
    monkeypatch.delenv("RELEASE_BLOCKED", raising=False)
    query, seen = _fake([])
    posts = []
    cs.heal_and_release(query, posts.append)
    assert cs.HEAL_ATTEMPTS_SQL in seen and cs.RELEASE_SQL not in seen and cs.RELEASE_DRY_SQL not in seen
    assert posts == []


def test_no_attempt_table_means_no_heal_and_no_release(monkeypatch):
    monkeypatch.setenv("RELEASE_BLOCKED", "on")
    query, seen = _fake([], has=False)
    cs.heal_and_release(query, lambda line: True)
    assert seen == [cs.HAS_ATTEMPTS_SQL]


def test_dry_reads_only(monkeypatch, capsys):
    monkeypatch.setenv("RELEASE_BLOCKED", "dry")
    query, seen = _fake([["release", "44273", "windy-pro", "ci.yml-refs/heads/main"]])
    posts = []
    cs.heal_and_release(query, posts.append)
    assert cs.RELEASE_DRY_SQL in seen and cs.RELEASE_SQL not in seen
    assert not any("action_tasks_version" in s for s in seen) and posts == []
    assert "would wake 1 blocked run(s): windy-pro 44273" in capsys.readouterr().out


def test_on_releases_bumps_the_three_runner_scopes_logs_and_posts_once(tmp_path, monkeypatch):
    monkeypatch.setenv("RELEASE_BLOCKED", "on")
    monkeypatch.setattr(cs, "LOG", tmp_path / "log")
    query, seen = _fake([["release", "44269", "windy-chat", "ci-db", "57", "1", "1"],
                         ["release", "44273", "windy-pro", "ci.yml-refs/heads/main", "12", "1", "13"]])
    posts = []
    cs.heal_and_release(query, posts.append)
    bump = [s for s in seen if "action_tasks_version" in s]
    assert len(bump) == 1 and "owner_id in (1) and repo_id = 0" in bump[0] and "repo_id in (12,57)" in bump[0]
    assert "(owner_id = 0 and repo_id = 0)" in bump[0]
    assert len(posts) == 1 and "2 run(s)" in posts[0] and "windy-chat 44269" in posts[0] and "windy-pro 44273" in posts[0]
    assert (tmp_path / "log").read_text().count("released run") == 2


def test_nothing_to_release_posts_nothing_and_a_db_error_never_fails_the_sync(monkeypatch):
    monkeypatch.setenv("RELEASE_BLOCKED", "on")
    query, seen = _fake([])
    posts = []
    cs.heal_and_release(query, posts.append)
    assert posts == [] and not any("action_tasks_version" in s for s in seen)

    def boom(sql):
        raise OSError("db down")
    cs.heal_and_release(boom, posts.append)
    assert posts == []
    assert cs.main(boom, posts.append) == 0


def test_main_runs_heal_after_the_cancels(monkeypatch):
    monkeypatch.delenv("RELEASE_BLOCKED", raising=False)
    monkeypatch.delenv("MAIN_SUPERSEDE", raising=False)
    query, seen = _fake([])
    assert cs.main(query, lambda line: True) == 0
    assert seen.index(cs.CANCEL_SQL) < seen.index(cs.HEAL_ATTEMPTS_SQL)
