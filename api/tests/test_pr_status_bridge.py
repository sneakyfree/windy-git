"""Behavioral tests for scripts/pr_status_bridge.py.

The bridge is the ONLY CI signal the private platform repos get on GitHub, so
these drive its real functions against fake Gitea/GitHub APIs rather than
grepping its source: a status painted green that nobody tested is worse than
no status at all.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("pr_status_bridge", ROOT / "scripts" / "pr_status_bridge.py")
bridge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bridge)

SHA = "a" * 40


def _run(i, wf, job, status, sha=SHA, n=1):
    return {"id": i, "workflow_id": wf, "name": job, "status": status, "head_sha": sha, "run_number": n}


class Fake:
    def __init__(self, runs=(), statuses=(), gh_prs=(), wg_prs=()):
        self.runs, self.statuses = list(runs), list(statuses)
        self.gh_prs, self.wg_prs = list(gh_prs), list(wg_prs)
        self.posted, self.opened, self.closed = [], [], []

    def gitea(self, method, path, body=None):
        if "/actions/tasks" in path:
            page = int(path.rsplit("page=", 1)[1])
            return 200, {"workflow_runs": self.runs[(page - 1) * 50: page * 50]}
        if method == "GET" and path.endswith("/pulls?state=open&limit=50"):
            return 200, self.wg_prs
        if method == "POST" and path.endswith("/pulls"):
            self.opened.append(body)
            return 201, {}
        if method == "PATCH":
            self.closed.append(path)
            return 201, {}
        raise AssertionError(path)

    def github(self, method, path, body=None):
        if "/statuses" in path and method == "GET":
            return 200, self.statuses
        if "/statuses/" in path and method == "POST":
            self.posted.append(body)
            return 201, {}
        if "/pulls?" in path:
            return 200, self.gh_prs
        raise AssertionError(path)


@pytest.fixture
def fake(monkeypatch):
    def make(**kw):
        f = Fake(**kw)
        monkeypatch.setattr(bridge, "gitea", f.gitea)
        monkeypatch.setattr(bridge, "github", f.github)
        return f
    return make


def test_posts_latest_verdict_per_job(fake):
    f = fake(runs=[_run(1, "ci.yml", "test", "failure"), _run(2, "ci.yml", "test", "success", n=2)])
    bridge.post_statuses("r", SHA)
    assert [(p["context"], p["state"]) for p in f.posted] == [("windy-git/ci/test", "success")]
    assert f.posted[0]["target_url"].endswith("/actions/runs/2")


def test_unchanged_state_is_not_reposted(fake):
    f = fake(runs=[_run(1, "ci.yml", "test", "success")],
             statuses=[{"context": "windy-git/ci/test", "state": "success"}])
    bridge.post_statuses("r", SHA)
    assert f.posted == []


def test_skipped_job_is_never_painted_green(fake):
    f = fake(runs=[_run(1, "substrate-drift.yml", "check", "skipped")])
    bridge.post_statuses("r", SHA)
    assert f.posted == []


def test_other_commits_runs_are_ignored(fake):
    f = fake(runs=[_run(1, "ci.yml", "test", "failure", sha="b" * 40)])
    bridge.post_statuses("r", SHA)
    assert f.posted == []


def test_runs_past_the_first_page_are_seen(fake):
    noise = [_run(100 + i, "drift.yml", "x", "skipped", sha="c" * 40) for i in range(50)]
    f = fake(runs=noise + [_run(1, "ci.yml", "test", "success")])
    bridge.post_statuses("r", SHA)
    assert [p["state"] for p in f.posted] == ["success"]


def _gh_pr(n, repo="sneakyfree/r"):
    return {"number": n, "title": "t", "html_url": "u",
            "head": {"ref": f"b{n}", "sha": SHA, "repo": {"full_name": repo} if repo else None},
            "base": {"ref": "main"}}


def test_fork_prs_are_never_mirrored(fake, monkeypatch):
    monkeypatch.setattr(bridge, "GH_OWNER", "sneakyfree")
    f = fake(gh_prs=[_gh_pr(1, repo="stranger/r"), _gh_pr(2, repo=None)])
    assert bridge.sync_prs("r") == []
    assert f.opened == []


def test_pr_mirror_opened_once_and_closed_when_github_closes(fake, monkeypatch):
    monkeypatch.setattr(bridge, "GH_OWNER", "sneakyfree")
    f = fake(gh_prs=[_gh_pr(7)], wg_prs=[{"number": 3, "title": "[GH#5] gone"}])
    assert bridge.sync_prs("r") == [SHA]
    assert [o["head"] for o in f.opened] == ["b7"]
    assert f.closed == ["/repos/windyadmin/r/pulls/3"]

    f2 = fake(gh_prs=[_gh_pr(7)], wg_prs=[{"number": 4, "title": "[GH#7] t"}])
    bridge.sync_prs("r")
    assert f2.opened == [] and f2.closed == []
