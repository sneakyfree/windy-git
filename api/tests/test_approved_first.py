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


def test_traveler_repos_take_agents_read_in_place_of_the_hubs(monkeypatch):
    """Boss 2026-11-09T05:57:38Z: windy-boss/approved AND (windy-hub OR windy-agent) on the 2 Traveler repos only."""
    statuses = {A: _ok("windy-boss/approved", "windy-agent/approved"),
                B: _ok("windy-agent/approved"),                                   # no Boss stamp
                C: _ok("windy-boss/approved", "windy-hub/approved")}
    monkeypatch.setattr(af.b, "commit_statuses", lambda repo, sha: statuses[sha])
    for repo in ("windy-traveler", "windytraveler-site"):
        assert af.approved(repo, A, {}, now=1000.0)
        assert not af.approved(repo, B, {}, now=1000.0)
        assert af.approved(repo, C, {}, now=1000.0)
    assert not af.approved("windy-pro", A, {}, now=1000.0)                       # Agent does not count on windy-pro
    assert not af.approved("windy-admin", A, {}, now=1000.0)                     # not fleet-wide
    statuses[A] = [{"context": "windy-agent/approved", "state": "failure"}] + statuses[A]
    assert not af.approved("windy-traveler", A, {}, now=1000.0)                   # a withdrawn read: newest wins


def test_windy_pro_takes_admins_read_in_place_of_the_hubs(monkeypatch):
    """Boss 2026-11-09T06:45:55Z: on windy-pro, windy-boss/approved AND (windy-hub OR windy-admin); no other repo."""
    statuses = {A: _ok("windy-boss/approved", "windy-admin/approved"),
                B: _ok("windy-admin/approved"),                                   # no Boss stamp
                C: _ok("windy-boss/approved", "windy-hub/approved")}
    monkeypatch.setattr(af.b, "commit_statuses", lambda repo, sha: statuses[sha])
    assert af.approved("windy-pro", A, {}, now=1000.0)
    assert not af.approved("windy-pro", B, {}, now=1000.0)
    assert af.approved("windy-pro", C, {}, now=1000.0)
    for repo in ("windy-traveler", "windy-admin", "WindyCloud"):                   # Admin's read counts nowhere else
        assert not af.approved(repo, A, {}, now=1000.0)
    statuses[A] = [{"context": "windy-admin/approved", "state": "failure"}] + statuses[A]
    assert not af.approved("windy-pro", A, {}, now=1000.0)                        # a withdrawn read: newest wins


def _vault(monkeypatch, statuses, files=None, st=200):
    """windy-vault world: statuses per sha; files = the compare answer (None -> the read fails)."""
    compares = []

    def github(method, path, body=None):
        compares.append(path)
        if files is None:
            return 404, {}
        return st, {"files": files}
    monkeypatch.setattr(af.b, "commit_statuses", lambda repo, sha: statuses[sha])
    monkeypatch.setattr(af.b, "github", github)
    return compares


def _f(*names, prev=None):
    out = [{"filename": n} for n in names]
    if prev:
        out[-1]["previous_filename"] = prev
    return out


def test_vault_takes_clouds_read_only_when_every_file_is_docs_or_todo(monkeypatch):
    """Boss 2026-11-09T16:09:00Z (b), NARROW: windy-vault only; docs/** or TODO.md only; anything else needs the Hub."""
    st = {A: _ok("windy-boss/approved", "windy-cloud/approved")}
    calls = _vault(monkeypatch, st, _f("docs/TOKEN-ROLL.md", "TODO.md"))
    assert af.approved("windy-vault", A, {}, now=1000.0)
    assert calls == [f"/repos/{af.b.GH_OWNER}/windy-vault/compare/main...{A}"]          # ONE compare read
    for bad in (_f("docs/TOKEN-ROLL.md", "scripts/roll.py"),                          # code next to docs
                _f(".github/workflows/ci.yml"), _f("ACCESS_LOCKBOX.md"),
                _f("sub/TODO.md"), _f("TODO.md.bak"), _f("docsx/a.md"), _f("docs"),   # look-alikes
                _f("docs/moved.py", prev="scripts/moved.py"),                         # a rename OUT of code
                [], [{"filename": None}]):
        _vault(monkeypatch, st, bad)
        assert not af.approved("windy-vault", A, {}, now=1000.0), bad
    _vault(monkeypatch, st, _f("docs/new.md", prev="docs/old.md"))                     # a rename inside docs/
    assert af.approved("windy-vault", A, {}, now=1000.0)


def test_vault_docs_rule_fails_closed(monkeypatch):
    st = {A: _ok("windy-boss/approved", "windy-cloud/approved")}
    _vault(monkeypatch, st, None)                                                      # compare read failed
    assert not af.approved("windy-vault", A, {}, now=1000.0)
    _vault(monkeypatch, st, _f(*[f"docs/{i}.md" for i in range(af.COMPARE_FILE_CAP)]))  # list may be partial
    assert not af.approved("windy-vault", A, {}, now=1000.0)
    _vault(monkeypatch, st, _f("docs/a.md"), st=500)
    assert not af.approved("windy-vault", A, {}, now=1000.0)
    st[A] = [{"context": "windy-cloud/approved", "state": "failure"}] + st[A]          # a withdrawn Cloud read
    _vault(monkeypatch, st, _f("docs/a.md"))
    assert not af.approved("windy-vault", A, {}, now=1000.0)
    st[A] = _ok("windy-cloud/approved")                                                # Boss's stamp still required
    _vault(monkeypatch, st, _f("docs/a.md"))
    assert not af.approved("windy-vault", A, {}, now=1000.0)


def test_vault_docs_rule_is_vault_only_and_costs_no_read_when_the_hub_stamped(monkeypatch):
    st = {A: _ok("windy-boss/approved", "windy-cloud/approved"),
          B: _ok("windy-boss/approved", "windy-hub/approved")}
    calls = _vault(monkeypatch, st, _f("docs/a.md"))
    for repo in ("windy-uptime", "windycloud-site", "windy-pro", "windy-git"):
        assert not af.approved(repo, A, {}, now=1000.0)                                # not fleet-wide
    assert calls == []                                                                 # and no compare read
    assert af.approved("windy-vault", B, {}, now=1000.0) and calls == []               # Hub + Boss: as before
    _vault(monkeypatch, st, _f("scripts/x.py"))
    assert af.approved("windy-vault", B, {}, now=1000.0)                               # the Hub still covers code
