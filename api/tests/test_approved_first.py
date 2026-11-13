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

import pytest  # noqa: E402

PATHS: dict = {}


@pytest.fixture(autouse=True)
def _code_heads(monkeypatch):
    """Every head is a code head (app.py) unless a test puts its diff in PATHS."""
    PATHS.clear()
    monkeypatch.setattr(af, "head_paths", lambda repo, sha: PATHS.get(sha, ["app.py"]))


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
                B: _ok("windy-boss/approved"),                                   # no reader stamp
                C: [{"context": "windy-hub/approved", "state": "failure"}] + _ok("windy-hub/approved")}
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


def test_windy_git_needs_hub_and_boss_on_code_and_boss_on_docs(monkeypatch):
    """Boss 2026-11-13T05:07:40Z: windy-git keeps his context (it holds the guards); 13:48:46Z: he stamps its TODO PRs."""
    statuses = {A: _ok("windy-hub/approved"), B: _ok("windy-hub/approved", "windy-boss/approved"),
                C: _ok("windy-boss/approved")}
    monkeypatch.setattr(af.b, "commit_statuses", lambda repo, sha: statuses[sha])
    assert not af.approved("windy-git", A, {}, now=1000.0)                       # Hub alone: not on windy-git
    assert af.approved("windy-git", B, {}, now=1000.0)
    PATHS[C] = ["TODO.md"]
    assert af.approved("windy-git", C, {}, now=1000.0)                           # docs head: Boss's stamp, no guards here


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
        assert af.approved("windy-mail", A, cache, now=1000.0) and cache == {A: 1000.0}
        assert af.approved("windy-mail", A, cache, now=1000.0 + af.APPROVAL_TTL_S - 1) and reads == [A]
        statuses[A] = [{"context": "windy-hub/approved", "state": "failure"}] + _ok("windy-hub/approved")
        assert not af.approved("windy-mail", A, cache, now=1000.0 + af.APPROVAL_TTL_S)    # expired: re-read
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
    """Boss 2026-11-09T05:57:38Z: (windy-hub OR windy-agent) on the 2 Traveler repos only; since 2026-11-13T01:44:24Z (2)
    that ONE reader stamp is the whole approval for code (no Boss stamp)."""
    statuses = {A: _ok("windy-agent/approved"),
                B: _ok("windy-boss/approved"),                                    # Boss alone: no reader
                C: _ok("windy-hub/approved")}
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
    """Boss 2026-11-09T06:45:55Z: on windy-pro, windy-hub OR windy-admin; no other repo. No Boss stamp since 01:44:24Z (2)."""
    statuses = {A: _ok("windy-admin/approved"),
                B: _ok("windy-boss/approved"),                                    # Boss alone: no reader
                C: _ok("windy-hub/approved")}
    monkeypatch.setattr(af.b, "commit_statuses", lambda repo, sha: statuses[sha])
    assert af.approved("windy-pro", A, {}, now=1000.0)
    assert not af.approved("windy-pro", B, {}, now=1000.0)
    assert af.approved("windy-pro", C, {}, now=1000.0)
    for repo in ("windy-traveler", "windy-admin", "WindyCloud"):                   # Admin's read counts nowhere else
        assert not af.approved(repo, A, {}, now=1000.0)
    statuses[A] = [{"context": "windy-admin/approved", "state": "failure"}] + statuses[A]
    assert not af.approved("windy-pro", A, {}, now=1000.0)                        # a withdrawn read: newest wins


def test_a_code_head_needs_only_the_hub_stamp_unless_boss_ask(monkeypatch):
    """Boss 2026-11-13T01:44:24Z (2): code = ONE stamp, the Hub's; windy-boss/approved only on BOSS ASK titles
    (and windy-git / kit-army-config). Windy Log 04:30:05Z: windy-contracts #358 was Hub-only and not counted."""
    statuses = {A: _ok("windy-hub/approved"), B: _ok("windy-boss/approved"),
                C: _ok("windy-hub/approved", "windy-boss/approved")}
    monkeypatch.setattr(af.b, "commit_statuses", lambda repo, sha: statuses[sha])
    assert af.approved("windy-contracts", A, {}, now=1000.0)
    assert not af.approved("windy-contracts", B, {}, now=1000.0)                 # Boss is not the reader
    assert not af.approved("windy-contracts", A, {}, now=1000.0, boss_ask=True)  # BOSS ASK: his stamp too
    assert af.approved("windy-contracts", C, {}, now=1000.0, boss_ask=True)
    assert not af.approved("kit-army-config", A, {}, now=1000.0)                 # the lockbox keeps Boss


def test_a_docs_only_head_counts_on_the_three_guards_by_name_and_nothing_less(monkeypatch):
    """Boss 2026-11-13T01:44:24Z (1): TODO/docs-only heads merge (and so go first) on the three guards by name."""
    three = ("windy-git/secret-guard", "windy-git/compute-guard", "windy-git/ci-hygiene")
    statuses = {A: _ok(*three), B: _ok(*three[:2]), C: _ok("windy-hub/approved")}
    monkeypatch.setattr(af.b, "commit_statuses", lambda repo, sha: statuses[sha])
    for sha in (A, B, C):
        PATHS[sha] = ["TODO.md", "docs/plan.md", "README.md"]
    assert af.approved("windy-mail", A, {}, now=1000.0)
    assert not af.approved("windy-mail", B, {}, now=1000.0)                      # one guard missing: not yet
    assert not af.approved("windy-mail", C, {}, now=1000.0)                      # a stamp is not a guard
    statuses[A] = [{"context": "windy-git/ci-hygiene", "state": "failure"}] + statuses[A]
    assert not af.approved("windy-mail", A, {}, now=1000.0)                      # newest wins


def test_a_head_with_one_code_file_or_an_unreadable_diff_is_code(monkeypatch):
    three = ("windy-git/secret-guard", "windy-git/compute-guard", "windy-git/ci-hygiene")
    statuses = {A: _ok(*three), B: _ok(*three)}
    monkeypatch.setattr(af.b, "commit_statuses", lambda repo, sha: statuses[sha])
    PATHS[A] = ["TODO.md", "api/app.py"]
    PATHS[B] = None
    assert not af.approved("windy-mail", A, {}, now=1000.0)                      # guards alone never move code
    assert not af.approved("windy-mail", B, {}, now=1000.0)


def test_the_boss_ask_flag_comes_from_the_run_title_in_sql(monkeypatch, tmp_path):
    reads = _world(monkeypatch, tmp_path, {A: _ok("windy-hub/approved")})
    seen = []
    def query(sql):
        seen.append(sql)
        if "group by p.name" in sql:
            return [["windy-contracts", A, "1", "t"]]
        return []
    af.main(query, lambda line: None)
    assert "like '%BOSS ASK%'" in seen[0] and reads == [A]
    assert len(seen) == 1                                                        # BOSS ASK + Hub only: not moved
