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


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    bridge._RUNS_CACHE.clear()
    monkeypatch.setattr(bridge, "failure_hint", lambda task_id: None)


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
    def status_for(findings, whole_tree, grant=()):
        if not findings and grant:
            return "success", f"GRANT-WARN {len(grant)}", grant[0]
        if not findings:
            return "success", "OK: clean", None
        return "failure", f"BLOCK {len(findings)}", findings[0]


class _F:
    path, line = "app/llm.py", 7


def test_guard_posts_warn_with_a_link_to_the_first_finding(fake, monkeypatch):
    f = fake()
    monkeypatch.setitem(sys.modules, "compute_guard", _Guard([_F()]))
    bridge.post_compute_guard("windy-chat", SHA, "main", False)
    assert [(p["context"], p["state"], p["description"]) for p in f.posted] == [
        ("windy-git/compute-guard", "failure", "BLOCK 1")]
    assert f.posted[0]["target_url"].endswith(f"/src/commit/{SHA}/app/llm.py#L7")


def test_guard_same_status_is_not_reposted(fake, monkeypatch):
    f = fake(statuses=[{"context": "windy-git/compute-guard", "state": "failure", "description": "BLOCK 1"}])
    monkeypatch.setitem(sys.modules, "compute_guard", _Guard([_F()]))
    bridge.post_compute_guard("windy-chat", SHA, "main", False)
    assert f.posted == []


def test_guard_that_cannot_run_posts_nothing(fake, monkeypatch):
    f = fake()
    monkeypatch.setitem(sys.modules, "compute_guard", _Guard(None))
    bridge.post_compute_guard("windy-chat", SHA, "main", True)
    assert f.posted == []


def test_ci_hygiene_posts_under_its_own_context(fake, monkeypatch):
    f = fake(statuses=[{"context": "windy-git/compute-guard", "state": "failure", "description": "BLOCK 1"}])
    monkeypatch.setitem(sys.modules, "ci_hygiene", _Guard([_F()]))
    bridge.post_ci_hygiene("windy-chat", SHA, "main", True)
    # the compute-guard status with the same description must not suppress it
    assert [(p["context"], p["description"]) for p in f.posted] == [("windy-git/ci-hygiene", "BLOCK 1")]


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


def test_named_no_daemon_job_is_not_posted_for_that_repo_only(fake, monkeypatch):
    """eternitas ci/build needs Docker but its name doesn't say so (option A, 09-23)."""
    monkeypatch.setattr(bridge, "NO_DAEMON_NAMED", {"eternitas": {"ci/build"}})
    runs = [_run(1, "ci.yml", "build", "failure"), _run(2, "ci.yml", "test", "success")]
    f = fake(runs=runs)
    bridge.post_statuses("eternitas", SHA)
    assert [p["context"] for p in f.posted] == ["windy-git/ci/test"]
    f2 = fake(runs=runs)
    bridge.post_statuses("windy-chat", SHA)
    assert sorted(p["context"] for p in f2.posted) == ["windy-git/ci/build", "windy-git/ci/test"]


def test_default_no_daemon_named_is_empty():
    """eternitas converted its ci/build to a no-Docker ci/smoke (#179); nothing left."""
    assert bridge.NO_DAEMON_NAMED == {}


def test_grant_owned_findings_never_block(fake, monkeypatch):
    """Orchestrator 09-23: compute-guard blocks lane-owned code only."""
    f = fake()
    monkeypatch.setitem(sys.modules, "compute_guard", _Guard([_F()]))
    monkeypatch.setitem(sys.modules, "guards_report",
                        type("GR", (), {"split_grant": staticmethod(lambda r, s, fs: ([], list(fs)))}))
    bridge.post_compute_guard("windy-pro", SHA, "main", True)
    assert [(p["state"], p["description"]) for p in f.posted] == [("success", "GRANT-WARN 1")]


def test_failed_grant_split_warns_instead_of_blocking(fake, monkeypatch):
    def boom(*a):
        raise RuntimeError("no bare clone")

    f = fake()
    monkeypatch.setitem(sys.modules, "compute_guard", _Guard([_F()]))
    monkeypatch.setitem(sys.modules, "guards_report", type("GR", (), {"split_grant": staticmethod(boom)}))
    bridge.post_compute_guard("windy-pro", SHA, "main", True)
    assert [p["state"] for p in f.posted] == ["success"]


@pytest.mark.parametrize("name, hidden", [
    ("Docker Build", True), ("docker-build", True), ("Docker build", True), ("docker", True),
    ("Boot smoke (no Docker)", False), ("smoke (no-docker)", False), ("boot without Docker", False),
    ("smoke", False),
])
def test_no_docker_smoke_jobs_are_posted(name, hidden):
    """windy-search #96: its replacement job says "no Docker" and was hidden."""
    assert bridge.needs_daemon("windy-search", "ci", name) is hidden


def test_failed_status_carries_the_failing_step_not_log_text(fake, monkeypatch):
    f = fake(runs=[_run(7, "ci.yml", "test", "failure")])
    monkeypatch.setattr(bridge, "failure_hint", lambda tid: "at step 'npm ci'" if tid == 7 else None)
    bridge.post_statuses("r", SHA)
    assert f.posted[0]["description"] == "Windy Git CI on Veron 1: failure at step 'npm ci'"


def test_infra_failure_says_no_step_ran(fake, monkeypatch):
    f = fake(runs=[_run(8, "ci.yml", "test", "failure")])
    monkeypatch.setattr(bridge, "failure_hint", lambda tid: "before any step ran")
    bridge.post_statuses("r", SHA)
    assert "before any step ran" in f.posted[0]["description"]


def test_success_description_unchanged_and_hint_not_asked(fake, monkeypatch):
    f = fake(runs=[_run(1, "ci.yml", "test", "success")])
    monkeypatch.setattr(bridge, "failure_hint", lambda tid: (_ for _ in ()).throw(AssertionError("asked")))
    bridge.post_statuses("r", SHA)
    assert f.posted[0]["description"] == "Windy Git CI on Veron 1: success"


def test_repo_task_list_is_fetched_once_per_run(fake):
    f = fake(runs=[_run(1, "ci.yml", "test", "success")])
    calls = []
    orig = f.gitea
    f.gitea = lambda m, p, b=None: (calls.append(p), orig(m, p, b))[1]
    bridge.gitea = f.gitea
    bridge.post_statuses("r", SHA)
    bridge.post_statuses("r", "b" * 40)
    assert len([c for c in calls if "/actions/tasks" in c]) == 1


def test_failure_hint_is_none_for_a_non_integer_id():
    assert bridge.failure_hint(None) is None


def test_failure_hint_sql_and_redaction(monkeypatch):
    seen = {}

    def fake_run(cmd, input=None, **kw):
        seen["sql"] = input

        class R:
            stdout = "run Zq9Xv3TnLm4Bw8KdFh2Yc6RpUe1GsAoJ7iNt|2\n"

        return R()

    monkeypatch.setattr(bridge.subprocess, "run", fake_run)
    monkeypatch.undo()  # keep the autouse stub off for this test only
    monkeypatch.setattr(bridge.subprocess, "run", fake_run)
    assert bridge.failure_hint(5) == "at step '(unnamed step)'"
    assert "status in (1, 2)" in seen["sql"] and "task_id = 5" in seen["sql"]


@pytest.mark.parametrize("name,ok", [
    ("Install dependencies", True), ("actions/checkout@v4", True), ("Main i18n coverage check (P3)", True),
    ("Run pytest", True),
    ("cd src/client/web && npm ci && npm run build", False),   # defaulted from a run: line
    ("npm ci", False), ("set -euo pipefail", False), ("Run set -euo pipefail and more", False),
    ("curl -H \"X: y\" https://x", False), ("export A=b", False), ("", False),
])
def test_only_human_step_labels_are_exposed(name, ok):
    assert bridge._is_step_label(name) is ok


def test_no_failed_step_means_infra_not_unnamed(monkeypatch):
    """A job that died before any step ran has NO failed step: say infra, not "(unnamed step)"."""
    class R:
        stdout = "|0\n"
    monkeypatch.undo()
    monkeypatch.setattr(bridge.subprocess, "run", lambda *a, **k: R())
    assert bridge.failure_hint(9) == "before any step ran"


_GATE_YAML = """name: check
jobs:
    gate:
        runs-on: veron-1
        steps:
            - uses: actions/checkout@v4
            - name: change gate
              run: python3 tools/contracts_manifest.py gate
            - run: npm ci
            - name: Zq9Xv3TnLm4Bw8KdFh2Yc6RpUe1GsAoJ7iNt
              run: true
"""


def _fake_hint_db(monkeypatch, name, payload_yaml):
    import base64 as b64

    payload = b64.b64encode(payload_yaml.encode()).decode() if payload_yaml else ""

    class R:
        stdout = f"{name}|3|{payload}\n"

    monkeypatch.undo()
    monkeypatch.setattr(bridge.subprocess, "run", lambda *a, **k: R())


def test_explicit_lowercase_step_name_is_shown(monkeypatch):
    """contracts 10-10: 'change gate' is the author's `name:`, not a command."""
    _fake_hint_db(monkeypatch, "change gate", _GATE_YAML)
    assert bridge.failure_hint(5) == "at step 'change gate'"


def test_unnamed_run_step_stays_hidden_even_with_payload(monkeypatch):
    _fake_hint_db(monkeypatch, "npm ci", _GATE_YAML)
    assert bridge.failure_hint(5) == "at step '(unnamed step)'"


def test_token_shaped_explicit_name_stays_hidden(monkeypatch):
    _fake_hint_db(monkeypatch, "Zq9Xv3TnLm4Bw8KdFh2Yc6RpUe1GsAoJ7iNt", _GATE_YAML)
    assert bridge.failure_hint(5) == "at step '(unnamed step)'"


def test_bad_payload_falls_back_to_the_label_rule(monkeypatch):
    class R:
        stdout = "change gate|3|not-base64!!\n"

    monkeypatch.undo()
    monkeypatch.setattr(bridge.subprocess, "run", lambda *a, **k: R())
    assert bridge.failure_hint(5) == "at step '(unnamed step)'"


def _pr(ref, n=137):
    return {"number": n, "title": "t", "html_url": "u",
            "head": {"ref": ref, "sha": SHA, "repo": {"full_name": f"{bridge.GH_OWNER}/WindyCloud"}},
            "base": {"ref": "main"}}


def test_archive_branch_pr_gets_an_explaining_error_not_a_mirror(fake):
    # WindyCloud #137, 10-10: archive/* is never synced, so the mirror 404'd silently.
    f = fake(gh_prs=[_pr("archive/a2.2-contract-kit")])
    assert bridge.sync_prs("WindyCloud") == [SHA]
    assert f.opened == []
    assert [(p["context"], p["state"]) for p in f.posted] == [("windy-git/ci", "error")]
    assert "archive/" in f.posted[0]["description"]


def test_archive_explanation_is_not_reposted(fake):
    f = fake(gh_prs=[_pr("archive/x")], statuses=[{"context": "windy-git/ci", "state": "error"}])
    bridge.sync_prs("WindyCloud")
    assert f.posted == []


def test_same_sha_reopened_from_another_branch_clears_the_error(fake):
    f = fake(gh_prs=[_pr("cloud/x")], statuses=[{"context": "windy-git/ci", "state": "error"}])
    bridge.sync_prs("WindyCloud")
    assert [o["head"] for o in f.opened] == ["cloud/x"]
    assert [(p["context"], p["state"]) for p in f.posted] == [("windy-git/ci", "success")]


def test_ordinary_new_mirror_posts_no_extra_status(fake):
    f = fake(gh_prs=[_pr("cloud/x")])
    bridge.sync_prs("WindyCloud")
    assert f.opened and f.posted == []


def test_failed_mirror_open_is_reported_loudly(fake, monkeypatch, capsys):
    f = fake(gh_prs=[_pr("cloud/x")])
    real = f.gitea
    monkeypatch.setattr(bridge, "gitea",
                        lambda m, p, b=None: (404, None) if m == "POST" else real(m, p, b))
    bridge.sync_prs("WindyCloud")
    assert "FAILED to open mirror PR for GH#137" in capsys.readouterr().out
    assert f.posted == []
