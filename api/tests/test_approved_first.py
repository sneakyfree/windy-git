"""scripts/approved_first.py: fully-approved PRs' jobs go first, oldest first, a slot at a time
(Boss 10-28 09:18Z); cheap on the shared GitHub quota."""

from __future__ import annotations

import importlib.util
import json
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
    assert A not in reads                                         # cached: not re-read within the TTL


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


def test_a_cached_approval_expires_and_a_withdrawn_one_leaves_the_cache():
    """Hub #96 LOW: an approval can be withdrawn (a later failure on the same context)."""
    import pytest

    statuses = {A: _ok("windy-hub/approved")}
    reads = []
    mp = pytest.MonkeyPatch()
    mp.setattr(af.b, "commit_statuses", lambda repo, sha: reads.append(sha) or statuses[sha])
    try:
        cache: dict = {}
        assert af.approved("windy-git", A, cache, now=1000.0) and cache == {A: 1000.0}
        assert af.approved("windy-git", A, cache, now=1000.0 + af.APPROVAL_TTL_S - 1) and reads == [A]
        statuses[A] = [{"context": "windy-hub/approved", "state": "failure"}] + _ok("windy-hub/approved")
        assert not af.approved("windy-git", A, cache, now=1000.0 + af.APPROVAL_TTL_S)    # expired: re-read
        assert reads == [A, A] and A not in cache
    finally:
        mp.undo()


def test_the_old_list_state_reads_as_expired(monkeypatch, tmp_path):
    reads = _world(monkeypatch, tmp_path, {A: _ok("windy-hub/approved", "windy-boss/approved")})
    (tmp_path / "approved.json").write_text(json.dumps([A]))
    af.main(lambda sql: [["windy-pro", A, "1"]] if sql is af.WAITING_HEADS_SQL else [], lambda line: None)
    assert reads == [A]                                           # re-read once, not trusted blindly
    saved = json.loads((tmp_path / "approved.json").read_text())
    assert isinstance(saved, dict) and set(saved) == {A}


def test_a_read_time_in_the_future_is_expired_not_trusted_forever(monkeypatch):
    """Hub #106 LOW: a corrupt file or a clock step back must not pin an approval."""
    reads = []
    monkeypatch.setattr(af.b, "commit_statuses", lambda repo, sha: reads.append(sha) or [])
    cache = {A: 10_000.0}
    assert not af.approved("windy-git", A, cache, now=1000.0) and reads == [A] and A not in cache
