"""Behavioral tests for scripts/pr_status_bridge.py.

The bridge is the ONLY CI signal the private platform repos get on GitHub, so
these drive its real functions against fake Gitea/GitHub APIs rather than
grepping its source: a status painted green that nobody tested is worse than
no status at all.
"""

from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "pr_status_bridge", ROOT / "scripts" / "pr_status_bridge.py"
)
bridge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bridge)

SHA = "a" * 40


def _run(i, wf, job, status, sha=SHA, n=1):
    return {
        "id": i,
        "workflow_id": wf,
        "name": job,
        "status": status,
        "head_sha": sha,
        "run_number": n,
    }


class Fake:
    def __init__(self, runs=(), statuses=(), gh_prs=(), wg_prs=(), workflows=None):
        self.runs, self.statuses = list(runs), list(statuses)
        self.workflows = workflows or {}  # {path: yaml text} at every commit
        self.gh_prs, self.wg_prs = list(gh_prs), list(wg_prs)
        self.posted, self.opened, self.closed = [], [], []

    def gitea(self, method, path, body=None):
        if "/contents/" in path:
            want = path.split("/contents/", 1)[1].split("?", 1)[0]
            if want in self.workflows:
                return 200, {"content": base64.b64encode(self.workflows[want].encode()).decode()}
            files = [
                {"type": "file", "name": k.rsplit("/", 1)[1], "path": k}
                for k in self.workflows
                if k.rsplit("/", 1)[0] == want
            ]
            return (200, files) if files else (404, None)
        if "/actions/tasks" in path:
            page = int(path.rsplit("page=", 1)[1])
            return 200, {"workflow_runs": self.runs[(page - 1) * 50 : page * 50]}
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
    def make(queued=(), **kw):
        f = Fake(**kw)
        monkeypatch.setattr(bridge, "gitea", f.gitea)
        monkeypatch.setattr(bridge, "github", f.github)
        monkeypatch.setattr(bridge, "queued_jobs", lambda repo, sha: list(queued))
        return f

    return make


def test_posts_latest_verdict_per_job(fake):
    f = fake(runs=[_run(1, "ci.yml", "test", "failure"), _run(2, "ci.yml", "test", "success", n=2)])
    bridge.post_statuses("r", SHA)
    assert [(p["context"], p["state"]) for p in f.posted] == [("windy-git/ci/test", "success")]
    assert f.posted[0]["target_url"].endswith("/actions/runs/2")


def test_unchanged_state_is_not_reposted(fake):
    f = fake(
        runs=[_run(1, "ci.yml", "test", "success")],
        statuses=[{"context": "windy-git/ci/test", "state": "success"}],
    )
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
    return {
        "number": n,
        "title": "t",
        "html_url": "u",
        "head": {"ref": f"b{n}", "sha": SHA, "repo": {"full_name": repo} if repo else None},
        "base": {"ref": "main"},
    }


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


def test_image_build_jobs_are_not_posted(fake):
    """No Docker daemon in job containers (I-5): a build job's red is structural."""
    f = fake(
        runs=[_run(1, "ci.yml", "Docker Build", "failure"), _run(2, "ci.yml", "docker", "failure")]
    )
    bridge.post_statuses("r", SHA)
    assert f.posted == []


def test_non_blocking_jobs_are_not_posted_for_that_repo_only(fake, monkeypatch):
    """Grant ruled windy-pro's desktop/installer jobs non-blocking: they must not
    reach GitHub for windy-pro, and the rule must not leak to other repos."""
    monkeypatch.setattr(bridge, "NON_BLOCKING", {"windy-pro": {"ci/build-desktop"}})
    runs = [_run(1, "ci.yml", "build-desktop", "failure"), _run(2, "ci.yml", "test", "success")]
    f = fake(runs=runs)
    bridge.post_statuses("windy-pro", SHA)
    assert [p["context"] for p in f.posted] == ["windy-git/ci/test"]
    f2 = fake(runs=runs)
    bridge.post_statuses("windy-chat", SHA)
    assert sorted(p["context"] for p in f2.posted) == [
        "windy-git/ci/build-desktop",
        "windy-git/ci/test",
    ]


def test_default_non_blocking_is_grants_ruling():
    assert bridge.NON_BLOCKING.get("windy-pro") == {
        "ci/build-desktop",
        "ci/test-installer",
        "ci/reality-check",
    }


def test_transport_blips_are_retried_but_http_errors_are_not(monkeypatch):
    import urllib.error

    calls = {"n": 0}

    class _R:
        status = 200

        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def flaky(req, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.URLError("_ssl.c:983: The handshake operation timed out")
        return _R()

    monkeypatch.setattr(bridge.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(bridge.time, "sleep", lambda s: None)
    assert bridge._call("http://x", "t", "GET", "/p") == (200, {})
    assert calls["n"] == 3

    def forbidden(req, timeout):
        calls["n"] += 1
        raise urllib.error.HTTPError("http://x/p", 403, "no", {}, None)

    calls["n"] = 0
    monkeypatch.setattr(bridge.urllib.request, "urlopen", forbidden)
    assert bridge._call("http://x", "t", "GET", "/p") == (403, None)
    assert calls["n"] == 1


GOOD = "on: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps: []\n"
BROKEN = "on: push\njobs:\n  test:\n    runs-on: x\n   steps: [\n"


def test_invalid_workflow_gets_an_error_status_even_with_no_runs(fake):
    # Gitea fires NO run for an invalid file: without this the PR shows nothing.
    f = fake(workflows={".github/workflows/ci.yml": BROKEN})
    bridge.post_statuses("windy-chat", SHA)
    assert [(p["context"], p["state"]) for p in f.posted] == [("windy-git/ci/workflow", "error")]
    assert "invalid YAML at line 5" in f.posted[0]["description"]
    assert f.posted[0]["target_url"].endswith(f"/src/commit/{SHA}/.github/workflows/ci.yml")


def test_valid_workflows_post_nothing_extra(fake):
    f = fake(runs=[_run(1, "ci.yml", "test", "success")], workflows={".github/workflows/ci.yml": GOOD})
    bridge.post_statuses("windy-chat", SHA)
    assert [p["context"] for p in f.posted] == ["windy-git/ci/test"]


def test_workflow_error_is_not_reposted(fake):
    f = fake(
        workflows={".github/workflows/ci.yml": BROKEN},
        statuses=[{"context": "windy-git/ci/workflow", "state": "error"}],
    )
    bridge.post_statuses("windy-chat", SHA)
    assert f.posted == []


def test_gitea_dir_wins_over_github_dir(fake):
    # Gitea runs .gitea/workflows when it has files and ignores .github/workflows.
    f = fake(workflows={".gitea/workflows/ci.yml": GOOD, ".github/workflows/old.yml": BROKEN})
    bridge.post_statuses("windy-chat", SHA)
    assert f.posted == []


@pytest.mark.parametrize(
    "text, problem",
    [
        (GOOD, None),
        ("on: push\njobs:\n  a:\n    uses: ./x.yml\n", None),
        (BROKEN, "invalid YAML at line 5"),
        ("jobs:\n  a:\n    runs-on: x\n", "no `on:` trigger"),
        ("on: push\n", "no `jobs:`"),
        ("on: push\njobs:\n  a:\n    steps: []\n", "job `a` has no `runs-on:`"),
        ("- a\n", "not a YAML mapping"),
    ],
)
def test_workflow_problem(text, problem):
    assert bridge.workflow_problem(text) == problem


def _q(n, wf, job):
    return {"run_number": n, "workflow_id": wf, "name": job}


def test_queued_job_shows_pending_instead_of_nothing(fake):
    f = fake(queued=[_q(5, "ci.yml", "test")])
    bridge.post_statuses("windy-chat", SHA)
    assert [(p["context"], p["state"]) for p in f.posted] == [("windy-git/ci/test", "pending")]
    assert f.posted[0]["target_url"].endswith("/actions/runs/5")


def test_queued_rerun_supersedes_the_stale_failure(fake):
    f = fake(runs=[_run(1, "ci.yml", "test", "failure", n=4)], queued=[_q(7, "ci.yml", "test")])
    bridge.post_statuses("windy-chat", SHA)
    assert [(p["context"], p["state"]) for p in f.posted] == [("windy-git/ci/test", "pending")]


def test_older_queued_job_never_overrides_a_newer_verdict(fake):
    f = fake(runs=[_run(1, "ci.yml", "test", "success", n=9)], queued=[_q(3, "ci.yml", "test")])
    bridge.post_statuses("windy-chat", SHA)
    assert [(p["context"], p["state"]) for p in f.posted] == [("windy-git/ci/test", "success")]


def test_queued_docker_and_non_blocking_jobs_stay_unposted(fake):
    f = fake(queued=[_q(2, "ci.yml", "docker-build"), _q(2, "ci.yml", "build-desktop")])
    bridge.post_statuses("windy-pro", SHA)
    assert f.posted == []


def test_queued_lookup_refuses_unsafe_input():
    assert bridge.queued_jobs("x'; drop table t;--", SHA) == []
    assert bridge.queued_jobs("windy-chat", "not-a-sha") == []


def _db(monkeypatch, jobs, labels):
    import json as _json
    import subprocess as _sp

    payload = _json.dumps({"jobs": jobs, "labels": [_json.dumps(x) for x in labels]})
    monkeypatch.setattr(
        bridge.subprocess, "run",
        lambda *a, **k: _sp.CompletedProcess(a, 0, stdout=payload, stderr=""),
    )


RUNNER = ["veron-1", "linux-x64", "self-hosted", "linux", "x64"]


def test_only_jobs_a_runner_can_take_are_pending(monkeypatch):
    # macos-latest is cancelled unpicked by the janitor: pending would never resolve.
    _db(monkeypatch, [
        {"run_number": 3, "workflow_id": "ci.yml", "name": "test", "runs_on": '["self-hosted","linux","x64"]'},
        {"run_number": 3, "workflow_id": "ci.yml", "name": "mac", "runs_on": '["macos-latest"]'},
    ], [RUNNER])
    assert [j["name"] for j in bridge.queued_jobs("windy-chat", SHA)] == ["test"]


def test_lookup_failure_is_non_fatal(monkeypatch):
    import subprocess as _sp

    def boom(*a, **k):
        raise _sp.TimeoutExpired("docker", 30)

    monkeypatch.setattr(bridge.subprocess, "run", boom)
    assert bridge.queued_jobs("windy-chat", SHA) == []


class _Guard:
    def __init__(self, findings):
        self.findings = findings

    def check(self, repo, sha, default_branch, is_default_head):
        return self.findings

    @staticmethod
    def status_for(findings, whole_tree):
        if not findings:
            return "success", "OK: clean", None
        return "success", f"WARN {len(findings)}", findings[0]


class _F:
    path, line = "app/llm.py", 7


def test_guard_posts_warn_with_a_link_to_the_first_finding(fake, monkeypatch):
    f = fake()
    monkeypatch.setitem(sys.modules, "compute_guard", _Guard([_F()]))
    bridge.post_compute_guard("windy-chat", SHA, "main", False)
    assert [(p["context"], p["state"], p["description"]) for p in f.posted] == [
        ("windy-git/compute-guard", "success", "WARN 1")]
    assert f.posted[0]["target_url"].endswith(f"/src/commit/{SHA}/app/llm.py#L7")


def test_guard_same_status_is_not_reposted(fake, monkeypatch):
    f = fake(statuses=[{"context": "windy-git/compute-guard", "state": "success", "description": "WARN 1"}])
    monkeypatch.setitem(sys.modules, "compute_guard", _Guard([_F()]))
    bridge.post_compute_guard("windy-chat", SHA, "main", False)
    assert f.posted == []


def test_guard_that_cannot_run_posts_nothing(fake, monkeypatch):
    f = fake()
    monkeypatch.setitem(sys.modules, "compute_guard", _Guard(None))
    bridge.post_compute_guard("windy-chat", SHA, "main", True)
    assert f.posted == []


def test_ci_hygiene_posts_under_its_own_context(fake, monkeypatch):
    f = fake(statuses=[{"context": "windy-git/compute-guard", "state": "success", "description": "WARN 1"}])
    monkeypatch.setitem(sys.modules, "ci_hygiene", _Guard([_F()]))
    bridge.post_ci_hygiene("windy-chat", SHA, "main", True)
    # the compute-guard status with the same description must not suppress it
    assert [(p["context"], p["description"]) for p in f.posted] == [("windy-git/ci-hygiene", "WARN 1")]


def test_retargeted_pr_gets_a_fresh_mirror_on_the_new_base(fake):
    # eternitas #167: stacked on fix/one-hallway, retargeted to main on GitHub.
    gh = [{"number": 167, "title": "feat", "html_url": "u",
           "head": {"ref": "feat/x", "sha": SHA, "repo": {"full_name": f"{bridge.GH_OWNER}/eternitas"}},
           "base": {"ref": "main"}}]
    wg = [{"number": 9, "title": "[GH#167] feat", "base": {"ref": "fix/one-hallway"}}]
    f = fake(gh_prs=gh, wg_prs=wg)
    assert bridge.sync_prs("eternitas") == [SHA]
    assert f.closed == [f"/repos/{bridge.WG_OWNER}/eternitas/pulls/9"]
    assert [(o["base"], o["head"]) for o in f.opened] == [("main", "feat/x")]


def test_unchanged_base_leaves_the_mirror_alone(fake):
    gh = [{"number": 5, "title": "t", "html_url": "u",
           "head": {"ref": "b", "sha": SHA, "repo": {"full_name": f"{bridge.GH_OWNER}/windy-chat"}},
           "base": {"ref": "main"}}]
    f = fake(gh_prs=gh, wg_prs=[{"number": 3, "title": "[GH#5] t", "base": {"ref": "main"}}])
    bridge.sync_prs("windy-chat")
    assert f.closed == [] and f.opened == []
