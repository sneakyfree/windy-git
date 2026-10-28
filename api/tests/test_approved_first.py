"""scripts/approved_first.py: fully-approved PRs' jobs go first, oldest first, a slot at a time
(Boss 10-28 09:18Z); cheap on the shared GitHub quota."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("GITEA_SYNC_TOKEN", "x")
os.environ.setdefault("GITHUB_TOKEN", "x")
_spec = importlib.util.spec_from_file_location("approved_first", ROOT / "scripts" / "approved_first.py")
af = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(af)

A, B, C = "a" * 40, "b" * 40, "c" * 40


def _world(monkeypatch, tmp_path, statuses, budget=4000):
    monkeypatch.setattr(af, "STATE", tmp_path / "approved.json")
    monkeypatch.setattr(af, "LOG", tmp_path / "log")
    reads = []
    monkeypatch.setattr(af.b, "github", lambda m, p, body=None:
                        (200, {"resources": {"core": {"remaining": budget}}}))
    monkeypatch.setattr(af.b, "commit_statuses", lambda repo, sha: reads.append(sha) or statuses.get(sha, []))
    return reads


def _ok(*ctxs):
    return [{"context": c, "state": "success"} for c in ctxs]


def test_only_fully_approved_heads_are_moved_and_approvals_are_cached(monkeypatch, tmp_path):
    statuses = {A: _ok("windy-hub/approved", "windy-boss/approved"),
                B: _ok("windy-hub/approved"),                                    # Boss missing
                C: [{"context": "windy-boss/approved", "state": "failure"}] + _ok("windy-hub/approved", "windy-boss/approved")}
    reads = _world(monkeypatch, tmp_path, statuses)
    sqls, posts = [], []

    def query(sql):
        sqls.append(sql)
        if sql is af.WAITING_HEADS_SQL:
            return [["windy-pro", A, "1"], ["windy-pro", B, "2"], ["windy-pro", C, "3"]]
        return [["101", A], ["102", A]]
    af.main(query, posts.append)
    move = [s for s in sqls if "update action_run_job" in s]
    assert len(move) == 1 and repr(A) in move[0] and repr(B) not in move[0] and repr(C) not in move[0]
    assert "limit 2" in move[0]                                   # one per runner slot
    assert len(posts) == 1 and "2 job(s)" in posts[0]
    reads.clear()
    af.main(query, posts.append)
    assert A not in reads                                         # cached: never re-read


def test_windy_git_needs_only_hubs_approval():
    assert af.APPROVALS["windy-git"] == ("windy-hub/approved",)


def test_the_move_never_touches_main_schedules_or_running_jobs():
    sql = " ".join(af.move_sql([A], 2).split())
    assert "j.status = 5 and j.task_id = 0" in sql and sql.count("j.status = 5 and j.task_id = 0") == 2
    assert "r.ref like 'refs/pull/%/head'" in sql and "r.event in ('pull_request', 'pull_request_sync')" in sql
    assert "j.updated >= (select mn from others)" in sql          # already at the front: left alone
    assert "order by j.created, j.id limit 2" in sql


def test_below_the_budget_floor_it_reads_nothing(monkeypatch, tmp_path):
    reads = _world(monkeypatch, tmp_path, {}, budget=1499)
    called = []
    af.main(lambda sql: called.append(sql) or [], lambda line: None)
    assert called == [] and reads == []
