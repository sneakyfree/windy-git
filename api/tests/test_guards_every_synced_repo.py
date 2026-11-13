"""GUARDS ON EVERY SYNCED REPO (Boss 2026-11-12T17:56:52Z (b)): every repo the sync carries gets secret-guard,
compute-guard, ci-hygiene and birth-terms; repos outside the bridge's CI set get them GUARD-ONLY (no mirror PR,
no CI verdict); anything else is OUT by name with a reason."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(monkeypatch, **env):
    for k in ("SYNC_REPOS", "BRIDGE_GUARD_ONLY_REPOS", "BRIDGE_REPOS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location("bridge_g", ROOT / "scripts" / "pr_status_bridge.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_every_synced_repo_is_guarded_or_out_by_name(monkeypatch):
    b = _load(monkeypatch)
    synced = b.synced_repos()
    assert len(synced) > 50                                                  # read from sync_from_github.sh
    for r in synced:
        assert r in b.REPOS or r in b.GUARD_ONLY or r in b.GUARD_OUT, f"{r} is synced but has no guards"
    assert not set(b.GUARD_ONLY) & set(b.REPOS)
    assert all(isinstance(v, str) and len(v) > 10 for v in b.GUARD_OUT.values())   # each OUT has its reason
    for r in list(b.REPOS) + list(b.GUARD_ONLY):
        assert r != "kit-army-config" and not r.endswith("-soul")             # never mirrored, never guarded here
    assert {"windy-git", "windy-git-site", "windy-marketing", "windy-agent"} <= set(b.GUARD_ONLY)


def test_sync_repos_env_wins_and_the_guard_only_env_overrides(monkeypatch):
    b = _load(monkeypatch, SYNC_REPOS="windy-chat x-one windy-ads")
    assert b.GUARD_ONLY == ["x-one"]                                         # windy-chat bridged, windy-ads OUT
    b = _load(monkeypatch, BRIDGE_GUARD_ONLY_REPOS="only-this")
    assert b.GUARD_ONLY == ["only-this"]


@pytest.fixture
def b(monkeypatch):
    m = _load(monkeypatch)
    m.REPOS, m.GUARD_ONLY = [], ["g1"]
    posted = []
    for name in ("post_compute_guard", "post_ci_hygiene", "post_birth_terms", "post_secret_guard"):
        monkeypatch.setattr(m, name, lambda repo, sha, br, d, _n=name: posted.append((_n, repo, sha, d)))
    for name in ("post_statuses", "sync_prs", "post_autorerun_note"):
        monkeypatch.setattr(m, name, lambda *a, _n=name, **k: pytest.fail(f"{_n} called for a guard-only repo"))
    monkeypatch.setattr(m, "fetched", lambda repo, sha: True)
    monkeypatch.setattr(m, "default_ref", lambda repo, pre, st, now: ("main", "d" * 40))
    monkeypatch.setattr(m, "github_open_pulls", lambda repo: [
        {"head": {"sha": "a" * 40, "repo": {"full_name": f"{m.GH_OWNER}/g1"}}},
        {"head": {"sha": "f" * 40, "repo": {"full_name": "someone/g1"}}},                  # a fork
        {"head": {"sha": "e" * 40, "repo": None}}])                                         # a deleted fork
    m._posted = posted
    return m


def test_guard_only_posts_the_four_guards_on_pr_heads_and_the_default_head_never_a_fork(b):
    st = {"heads": {}, "branches": {}}
    seen = set()
    assert b.guard_only_pass("g1", None, st, 1000.0, seen) == (2, 0)
    shas = {(r, s, d) for _, r, s, d in b._posted}
    assert shas == {("g1", "a" * 40, False), ("g1", "d" * 40, True)}
    assert len(b._posted) == 8                                               # 4 guards x 2 heads
    assert seen == {f"guard|g1|{'a' * 40}", f"guard|g1|{'d' * 40}"}


def test_an_unchanged_head_is_read_once_per_backstop(b):
    st = {"heads": {}, "branches": {}}
    for sha in ("a" * 40, "d" * 40):
        b._STATUSES_CACHE[("g1", sha)] = []                                 # statuses were read: cacheable
    b.guard_only_pass("g1", None, st, 1000.0, set())
    n = len(b._posted)
    assert b.guard_only_pass("g1", None, st, 1060.0, set()) == (0, 2) and len(b._posted) == n
    assert b.guard_only_pass("g1", None, st, 1000.0 + b.BACKSTOP_S + 1, set())[0] == 2


def test_the_prefetch_covers_guard_only_repos_and_a_failing_one_does_not_stop_the_pass(b, monkeypatch):
    asked, done = [], []
    monkeypatch.setattr(b, "api_budget", lambda: None)
    monkeypatch.setattr(b, "prefetch", lambda repos: asked.append(list(repos)))
    monkeypatch.setattr(b, "load_state", lambda fp: {"heads": {}, "branches": {}})
    monkeypatch.setattr(b, "save_state", lambda st: None)
    monkeypatch.setattr(b, "_write_skips", lambda n: None)
    b.GUARD_ONLY = ["boom", "g1"]

    def gp(repo, pre, st, now, seen):
        if repo == "boom":
            raise RuntimeError("x")
        done.append(repo)
        return 1, 0
    monkeypatch.setattr(b, "guard_only_pass", gp)
    monkeypatch.setattr(b, "GITEA_TOKEN", "t")
    monkeypatch.setattr(b, "GITHUB_TOKEN", "t")
    assert b.main() == 1 and done == ["g1"] and asked == [["boom", "g1"]]
