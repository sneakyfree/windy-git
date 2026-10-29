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
        if method == "GET" and "/pulls?state=open&limit=50&page=" in path:
            page = int(path.rsplit("page=", 1)[1])
            return 200, self.wg_prs[(page - 1) * 50 : page * 50]
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
    bridge._STATUSES_CACHE.clear()
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
            stdout = "2||||||run Zq9Xv3TnLm4Bw8KdFh2Yc6RpUe1GsAoJ7iNt\n"

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
        stdout = "0||||||\n"
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
        stdout = f"3|{payload}|||||{name}\n"

    monkeypatch.undo()
    monkeypatch.setattr(bridge.subprocess, "run", lambda *a, **k: R())


def _fake_hint_row(monkeypatch, row):
    class R:
        stdout = row + "\n"

    monkeypatch.undo()
    monkeypatch.setattr(bridge.subprocess, "run", lambda *a, **k: R())


def test_runner_lost_mid_step_says_so_with_the_step_number(monkeypatch):
    """windy-pro run 3326 (10-17): the 18:56Z host restart killed `npm test` at step 6 of 7."""
    _fake_hint_row(monkeypatch, "6||6|7|1||cd account-server && npm test")
    assert bridge.failure_hint(5) == (
        "runner lost, re-run it: step 6/7 '(unnamed step)'")


def test_real_failure_names_the_step_number_not_runner_lost(monkeypatch):
    """Error-code ratchet failed for real; the runner skipped the later steps (status 4)."""
    _fake_hint_row(monkeypatch, "6||6|9|0||Error-code ratchet")
    assert bridge.failure_hint(5) == "at step 6/9 'Error-code ratchet'"


def test_runner_lost_query_keys_on_gitea_stop_marks(monkeypatch):
    seen = {}

    def fake_run(*a, **k):
        seen["sql"] = k["input"]

        class R:
            stdout = "0||0|0|0|0|\n"

        return R()

    monkeypatch.undo()
    monkeypatch.setattr(bridge.subprocess, "run", fake_run)
    assert bridge.failure_hint(5) == "before any step ran"
    assert "s.log_length = 0" in seen["sql"] and "s.stopped = t.stopped" in seen["sql"]
    assert "s.index > (select min(index)" in seen["sql"]


def test_verdict_text_with_runner_lost_fits_a_github_description(monkeypatch):
    _fake_hint_row(monkeypatch, "12||12|12|3||Zq9Xv3TnLm4Bw8KdFh2Yc6RpUe1GsAoJ7iNt")
    text = bridge._verdict_text({"status": "failure", "id": 5})
    assert "runner lost, re-run it: step 12/12 '(unnamed step)'" in text and len(text) <= 140
    assert "Zq9X" not in text


def test_failure_hint_leads_with_the_job_id_for_the_log_fetch(monkeypatch):
    _fake_hint_row(monkeypatch, "6||6|7|1|41574|cd account-server && npm test")
    assert bridge.failure_hint(5) == (
        "(job 41574) runner lost, re-run it: step 6/7 '(unnamed step)'")
    _fake_hint_row(monkeypatch, "0||0|0|0|41922|")
    assert bridge.failure_hint(5) == "(job 41922) before any step ran"


def test_job_id_survives_the_140_char_cut(monkeypatch):
    long_label = "Install dependencies and build every package in the tree"
    _fake_hint_row(monkeypatch, f"6||12|12|1|41574|{long_label}")
    text = bridge._verdict_text({"status": "failure", "id": 5})[:140]
    assert "(job 41574)" in text


def test_a_pipe_in_the_step_name_cannot_shift_fields(monkeypatch):
    """Hub 10-18: 'cat x | grep y' as the FIRST field made a real failure read runner lost."""
    _fake_hint_row(monkeypatch, "6||6|9|0|41579|cat x | grep y | 7 | 1 | 99999")
    assert bridge.failure_hint(5) == "(job 41579) at step 6/9 '(unnamed step)'"
    _fake_hint_row(monkeypatch, "6||6|9|0|41579|Lint | Format")
    hint = bridge.failure_hint(5)
    assert hint.startswith("(job 41579) at step 6/9 ") and "runner lost" not in hint


def test_long_label_keeps_job_and_advice_inside_140(monkeypatch):
    label = "Install Everything Needed For The Account Server X"  # 50 chars, a valid label
    assert len(label) == 50 and bridge._is_step_label(label)
    _fake_hint_row(monkeypatch, f"6||12|12|1|412345|{label}")
    text = bridge._verdict_text({"status": "failure", "id": 5})
    assert len(text) <= 140 and "(job 412345) runner lost, re-run it: step 12/12" in text


def test_hint_sql_pins_status_index_and_stop_marks():
    """Hand-built rows can't catch SQL mutations: pin the clauses that decide the verdict."""
    sql = bridge.hint_sql(7)
    assert sql.count("status = 2 order by index limit 1") == 2           # failed step: number + name
    assert "select index + 1 from action_task_step" in sql               # 0-based index -> "step N"
    assert "s.status = 2 and s.log_length = 0" in sql
    assert "t.stopped > 0 and s.stopped = t.stopped" in sql
    assert "s.index > (select min(index) from action_task_step where task_id = 7 and status = 2)" in sql
    assert "status in (1, 2)" in sql and "task_id = 7" in sql
    assert sql.rstrip(";").rstrip().endswith("order by index limit 1), '')")  # name is the LAST field


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
        stdout = "3|not-base64!!|||||change gate\n"

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


class _CountingFake(Fake):
    def __init__(self, fail_first_get=False, **kw):
        super().__init__(**kw)
        self.status_gets, self.fail_first_get = 0, fail_first_get

    def github(self, method, path, body=None):
        if "/statuses" in path and method == "GET":
            self.status_gets += 1
            if self.fail_first_get and self.status_gets == 1:
                return 502, None
        return super().github(method, path, body)


_STATUSES_NOW = [  # newest first, as GitHub returns them
    {"context": "windy-git/ci/test", "state": "pending", "description": ""},
    {"context": "windy-git/compute-guard", "state": "failure", "description": "BLOCK 1"},
    {"context": "windy-git/secret-guard", "state": "success", "description": "OK: clean"},
    {"context": "windy-git/ci-hygiene", "state": "failure", "description": "BLOCK 2"},
]
_RUNS_NOW = [_run(1, "ci.yml", "test", "success"), _run(2, "ci.yml", "lint", "failure")]


def _one_head(f, monkeypatch, share):
    """What main() does for one head: post_statuses, then the three guards."""
    monkeypatch.setattr(bridge, "gitea", f.gitea)
    monkeypatch.setattr(bridge, "github", f.github)
    monkeypatch.setattr(bridge, "queued_jobs", lambda repo, sha: [])
    monkeypatch.setitem(sys.modules, "guards_report",  # all lane-owned: the guards can block
                        type("GR", (), {"split_grant": staticmethod(lambda r, s, fs: (list(fs), []))}))
    monkeypatch.setitem(sys.modules, "compute_guard", _Guard([_F()]))     # unchanged: BLOCK 1
    monkeypatch.setitem(sys.modules, "secret_guard", _Guard([_F()]))      # changed: was clean
    monkeypatch.setitem(sys.modules, "ci_hygiene", _Guard([_F(), _F()]))  # unchanged: BLOCK 2
    steps = [lambda: bridge.post_statuses("windy-chat", SHA)] + [
        (lambda fn=fn: fn("windy-chat", SHA, "main", False))
        for fn in (bridge.post_compute_guard, bridge.post_ci_hygiene, bridge.post_secret_guard)]
    for step in steps:
        if not share:
            bridge._STATUSES_CACHE.clear()  # the old behaviour: every caller fetched its own
        bridge._RUNS_CACHE.clear()
        step()
    return [(p["context"], p["state"], p.get("description")) for p in f.posted]


def test_shared_statuses_post_exactly_what_separate_gets_did(monkeypatch):
    old = _CountingFake(runs=_RUNS_NOW, statuses=_STATUSES_NOW)
    new = _CountingFake(runs=_RUNS_NOW, statuses=_STATUSES_NOW)
    before = _one_head(old, monkeypatch, share=False)
    bridge._STATUSES_CACHE.clear()
    after = _one_head(new, monkeypatch, share=True)
    assert after == before
    # and the scenario is not vacuous: one CI job and one guard changed, two guards did not
    assert {c for c, _, _ in after} == {"windy-git/ci/test", "windy-git/ci/lint", "windy-git/secret-guard"}
    assert (old.status_gets, new.status_gets) == (4, 1)


def test_failed_statuses_get_is_not_shared(monkeypatch):
    f = _CountingFake(fail_first_get=True, runs=_RUNS_NOW, statuses=_STATUSES_NOW)
    posted = _one_head(f, monkeypatch, share=True)
    # the CI post saw no statuses (as before a failed GET), the guards fetched again and
    # saw the real list, so the unchanged guards are still not reposted
    assert f.status_gets == 2
    assert [c for c, _, _ in posted if "guard" in c or "hygiene" in c] == ["windy-git/secret-guard"]


def test_each_head_and_each_sync_gets_its_own_statuses(fake, monkeypatch):
    f = fake(statuses=_STATUSES_NOW)
    calls = []
    real = f.github

    def counting(method, path, body=None):
        calls.append(path)
        return real(method, path, body)

    monkeypatch.setattr(bridge, "github", counting)
    bridge.commit_statuses("r", SHA)
    bridge.commit_statuses("r", SHA)
    bridge.commit_statuses("r", "b" * 40)
    bridge.commit_statuses("other", SHA)
    assert len(calls) == 3
    bridge._STATUSES_CACHE.clear()  # main() does this at the start of every sync
    bridge.commit_statuses("r", SHA)
    assert len(calls) == 4


def test_every_sync_starts_with_no_shared_statuses(monkeypatch):
    bridge._STATUSES_CACHE[("r", SHA)] = [{"context": "windy-git/ci/test", "state": "success"}]
    monkeypatch.setattr(bridge, "GITEA_TOKEN", "t")
    monkeypatch.setattr(bridge, "GITHUB_TOKEN", "t")
    monkeypatch.setattr(bridge, "REPOS", [])
    assert bridge.main() == 0
    assert bridge._STATUSES_CACHE == {}


def test_failed_statuses_get_returns_an_empty_list_not_the_error_body(monkeypatch):
    # GitHub's error body is a dict; iterating it would hand callers its keys as "statuses"
    monkeypatch.setattr(bridge, "github", lambda method, path, body=None: (403, {"message": "API rate limit exceeded"}))
    bridge._STATUSES_CACHE.clear()
    assert bridge.commit_statuses("r", SHA) == []
    assert ("r", SHA) not in bridge._STATUSES_CACHE  # a failure is never shared with later callers



def test_open_mirror_prs_past_the_first_gitea_page_are_seen(fake, monkeypatch):
    # windy-pro 10-17: 59 open mirror PRs; Gitea returns at most 50 per page
    n = 59
    gh = [{"number": i, "title": f"t{i}", "head": {"sha": f"{i:040d}", "ref": f"b{i}",
           "repo": {"full_name": f"{bridge.GH_OWNER}/r"}}, "base": {"ref": "main"}} for i in range(1, n + 1)]
    wg = [{"number": i, "title": f"{bridge.MIRROR_TAG}{i}] t{i}", "base": {"ref": "main"}} for i in range(1, n + 1)]
    f = fake(gh_prs=gh, wg_prs=wg)
    heads = bridge.sync_prs("r")
    assert len(heads) == n
    assert f.opened == []   # nothing re-opened: every existing mirror PR was found
    assert f.closed == []   # and none closed as stale


def test_gitea_pull_list_stops_on_a_short_page_and_refuses_a_runaway(monkeypatch):
    calls = []

    def g(method, path, body=None):
        calls.append(path)
        page = int(path.rsplit("page=", 1)[1])
        return 200, [{"title": "x"}] * (50 if page < 3 else 7)

    monkeypatch.setattr(bridge, "gitea", g)
    assert len(bridge.gitea_open_pulls("r")) == 107 and len(calls) == 3
    monkeypatch.setattr(bridge, "gitea", lambda m, p, b=None: (200, [{"title": "x"}] * 50))
    with pytest.raises(RuntimeError, match="longer than"):
        bridge.gitea_open_pulls("r")
    monkeypatch.setattr(bridge, "gitea", lambda m, p, b=None: (500, None))
    with pytest.raises(RuntimeError, match="page 1 -> 500"):
        bridge.gitea_open_pulls("r")


def test_autorerun_note_reads_kind_and_job(tmp_path, monkeypatch):
    p = tmp_path / "a.json"
    monkeypatch.setattr(bridge, "AUTORERUN_STATE", str(p))
    assert bridge.autorerun_note("r", "s") is None                 # no file
    p.write_text("garbage")
    assert bridge.autorerun_note("r", "s") is None
    monkeypatch.setattr(bridge, "_repo_runs", lambda repo: [
        {"head_sha": c, "run_number": 11} for c in ("s", "t", "u", "f", "n", "old")])
    p.write_text('{"r@s": {"at": 1, "kind": "runner-lost", "job": "41574", "exit": 0, "runs_before": 10}, '
                 '"r@t": {"at": 1, "exit": 0, "runs_before": 10}, '
                 '"r@u": {"at": 1, "kind": "<b>", "job": "1; x", "exit": 0, "runs_before": 10}, '
                 '"r@f": {"at": 1, "kind": "runner-lost", "job": "9", "exit": 1, "runs_before": 10}, '
                 '"r@n": {"at": 1, "kind": "runner-lost", "job": "9", "runs_before": 10}, '
                 '"r@old": {"at": 1, "kind": "runner-lost", "job": "9", "exit": 0, "runs_before": 11}, '
                 '"r@v1": {"at": 1, "kind": "runner-lost", "job": "9", "exit": 0}}')
    assert bridge.autorerun_note("r", "s") == (
        "Re-queued once automatically: runner lost mid-step (job 41574). A second failure stays red.")
    assert bridge.autorerun_note("r", "t") == (
        "Re-queued once automatically: job died before any step ran. A second failure stays red.")
    assert "<b>" not in bridge.autorerun_note("r", "u") and "1; x" not in bridge.autorerun_note("r", "u")
    assert bridge.autorerun_note("r", "other") is None
    assert bridge.autorerun_note("r", "f") is None      # rerun_ci.sh failed: nothing announced
    assert bridge.autorerun_note("r", "n") is None      # not finished / no exit recorded yet
    assert bridge.autorerun_note("r", "old") is None    # exit 0 but no run newer than before
    assert bridge.autorerun_note("r", "v1") is None     # no runs_before recorded: never announced
    monkeypatch.setattr(bridge, "_repo_runs", lambda repo: (_ for _ in ()).throw(RuntimeError("x")))
    assert bridge.autorerun_note("r", "s") is None      # runs unreadable: say nothing


def test_autorerun_note_is_posted_once(tmp_path, monkeypatch):
    p = tmp_path / "a.json"
    p.write_text('{"r@s": {"at": 1, "kind": "runner-lost", "job": "7", "exit": 0, "runs_before": 1}}')
    monkeypatch.setattr(bridge, "_repo_runs", lambda repo: [{"head_sha": "s", "run_number": 2}])
    monkeypatch.setattr(bridge, "AUTORERUN_STATE", str(p))
    posted = []
    monkeypatch.setattr(bridge, "github", lambda m, path, body=None: (posted.append(body) or (201, {})))
    monkeypatch.setattr(bridge, "commit_statuses", lambda repo, sha: [])
    bridge.post_autorerun_note("r", "s")
    assert posted[0]["context"] == "windy-git/autorerun" and posted[0]["state"] == "success"
    desc = posted[0]["description"]
    monkeypatch.setattr(bridge, "commit_statuses",
                        lambda repo, sha: [{"context": "windy-git/autorerun", "state": "success", "description": desc}])
    bridge.post_autorerun_note("r", "s")
    assert len(posted) == 1


def test_a_pass_is_skipped_below_the_budget_floor(monkeypatch, capsys, tmp_path):
    """10-28: the bridge (about 345 calls a pass) shares the user quota with stamps and lanes."""
    monkeypatch.setattr(bridge, "SKIPS_FILE", tmp_path / "skips")
    calls = []

    def github(method, path, body=None):
        calls.append(path)
        if path == "/rate_limit":
            return 200, {"resources": {"core": {"remaining": 1499}}}
        return 200, []
    monkeypatch.setattr(bridge, "github", github)
    monkeypatch.setattr(bridge, "GITEA_TOKEN", "x")
    monkeypatch.setattr(bridge, "GITHUB_TOKEN", "x")
    assert bridge.main() == 0 and bridge.main() == 0
    assert calls == ["/rate_limit"] * 2 and "1499 < 1500" in capsys.readouterr().out
    assert bridge.main() == 1                                   # 3rd in a row: the pass FAILS -> alert
    assert "WARN: the bridge has skipped 3 passes in a row" in capsys.readouterr().out


def test_a_full_pass_resets_the_skip_count(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "SKIPS_FILE", tmp_path / "skips")
    monkeypatch.setattr(bridge, "STATE_FILE", tmp_path / "state.json")
    (tmp_path / "skips").write_text("2\n")
    monkeypatch.setattr(bridge, "github", lambda m, p, body=None:
                        (200, {"resources": {"core": {"remaining": 4000}}}) if p == "/rate_limit" else (404, {}))
    monkeypatch.setattr(bridge, "REPOS", [])
    monkeypatch.setattr(bridge, "GITEA_TOKEN", "x")
    monkeypatch.setattr(bridge, "GITHUB_TOKEN", "x")
    assert bridge.main() == 0 and (tmp_path / "skips").read_text().strip() == "0"


def test_a_pass_runs_at_the_floor_and_when_the_budget_is_unreadable(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "SKIPS_FILE", tmp_path / "skips")
    monkeypatch.setattr(bridge, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(bridge, "job_signatures", lambda r, shas: {})
    for budget_reply in ((200, {"resources": {"core": {"remaining": 1500}}}), (500, {})):
        calls = []

        def github(method, path, body=None, _r=budget_reply, _calls=calls):
            _calls.append(path)
            return _r if path == "/rate_limit" else (404, {})
        monkeypatch.setattr(bridge, "github", github)
        monkeypatch.setattr(bridge, "REPOS", ["repo-x"])
        monkeypatch.setattr(bridge, "sync_prs", lambda r: [])
        monkeypatch.setattr(bridge, "GITEA_TOKEN", "x")
        monkeypatch.setattr(bridge, "GITHUB_TOKEN", "x")
        bridge.main()
        assert len(calls) > 1, budget_reply                 # it went on to the repos


# ── step 2: the cross-pass state file (Boss 10-28) ──────────────────────────────────────────
SHA_A = "a" * 40


def _cache_world(monkeypatch, tmp_path, sigs, post_ok=True):
    """One repo with one PR head; records which heads were processed this pass."""
    processed = []
    monkeypatch.setattr(bridge, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(bridge, "SKIPS_FILE", tmp_path / "skips")
    monkeypatch.setattr(bridge, "REPOS", ["repo-x"])
    monkeypatch.setattr(bridge, "GITEA_TOKEN", "x")
    monkeypatch.setattr(bridge, "GITHUB_TOKEN", "x")
    monkeypatch.setattr(bridge, "sync_prs", lambda r: [SHA_A])
    monkeypatch.setattr(bridge, "job_signatures", lambda r, shas: dict(sigs))
    monkeypatch.setattr(bridge, "fetched", lambda r, s: True)

    def github(method, path, body=None):
        if path == "/rate_limit":
            return 200, {"resources": {"core": {"remaining": 4000}}}
        if path == "/repos/sneakyfree/repo-x":
            return 200, {"default_branch": "main"}
        if path.endswith("/branches/main"):
            return 200, {"commit": {"sha": SHA_A}}
        return 404, None
    monkeypatch.setattr(bridge, "github", github)

    def post_statuses(repo, sha):
        processed.append(sha)
        bridge._STATUSES_CACHE[(repo, sha)] = []                # the GET worked
        if not post_ok:
            bridge.POST_FAILS[0] += 1
    monkeypatch.setattr(bridge, "post_statuses", post_statuses)
    for f in ("post_autorerun_note", "post_compute_guard", "post_ci_hygiene", "post_birth_terms", "post_secret_guard"):
        monkeypatch.setattr(bridge, f, lambda *a, **k: None)
    return processed


def test_an_unchanged_head_is_read_once_and_then_skipped(monkeypatch, tmp_path):
    sigs = {SHA_A: "1:1:1:100"}
    processed = _cache_world(monkeypatch, tmp_path, sigs)
    bridge.main()
    bridge.main()
    assert processed == [SHA_A]                                  # 2nd pass: cached


def test_a_job_change_or_a_rules_change_forces_a_re_read(monkeypatch, tmp_path):
    sigs = {SHA_A: "1:6:1:100"}
    processed = _cache_world(monkeypatch, tmp_path, sigs)
    bridge.main()
    sigs[SHA_A] = "1:1:1:160"                                    # the job finished
    monkeypatch.setattr(bridge, "job_signatures", lambda r, shas: dict(sigs))
    bridge.main()
    assert processed == [SHA_A, SHA_A]
    monkeypatch.setattr(bridge, "rules_fingerprint", lambda: "deployed-new-rules")
    bridge.main()
    assert processed == [SHA_A] * 3


def test_the_hourly_backstop_re_reads_an_unchanged_head(monkeypatch, tmp_path):
    processed = _cache_world(monkeypatch, tmp_path, {SHA_A: "1:1:1:100"})
    clock = [1_000_000.0]
    monkeypatch.setattr(bridge.time, "time", lambda: clock[0])
    bridge.main()
    clock[0] += 49 * 60
    bridge.main()                                                # inside 50 min: cached
    clock[0] += 12 * 60
    bridge.main()                                                # 61 min: past every key's backstop
    assert processed == [SHA_A, SHA_A]


def test_a_failed_post_or_an_unreadable_signature_is_never_cached(monkeypatch, tmp_path):
    processed = _cache_world(monkeypatch, tmp_path, {SHA_A: "1:1:1:100"}, post_ok=False)
    bridge.main()
    bridge.main()
    assert processed == [SHA_A, SHA_A]                           # retried, not cached
    processed2 = _cache_world(monkeypatch, tmp_path / "b", {SHA_A: "1:1:1:100"})
    (tmp_path / "b").mkdir()
    monkeypatch.setattr(bridge, "job_signatures", lambda r, shas: None)   # the DB was unreadable
    bridge.main()
    bridge.main()
    assert processed2 == [SHA_A, SHA_A]


def test_the_default_branch_name_is_cached_for_a_day(monkeypatch, tmp_path):
    _cache_world(monkeypatch, tmp_path, {SHA_A: "1:1:1:100"})
    calls = []
    inner = bridge.github
    monkeypatch.setattr(bridge, "github", lambda m, p, body=None: calls.append(p) or inner(m, p, body))
    bridge.main()
    bridge.main()
    assert calls.count("/repos/sneakyfree/repo-x") == 1



def test_a_task_cut_at_the_runner_ceiling_says_ceiling_not_runner_lost(monkeypatch):
    """windy-admin #821 (10-28): the bridge said "runner lost, re-run it" for a job the runner's
    90 min ceiling cut. Same marks; the task's run time tells them apart."""
    _fake_hint_row(monkeypatch, "6||6|7|1|56593|cd account-server && npm test")
    monkeypatch.setattr(bridge, "_task_seconds", lambda tid: bridge.RUNNER_CEILING_S + 840)
    assert bridge.failure_hint(5) == "(job 56593) hit the 90 min runner ceiling (too slow or hung): step 6/7 '(unnamed step)'"
    monkeypatch.setattr(bridge, "_task_seconds", lambda tid: 1200)
    assert bridge.failure_hint(5) == "(job 56593) runner lost, re-run it: step 6/7 '(unnamed step)'"
    monkeypatch.setattr(bridge, "_task_seconds", lambda tid: 0)                      # unknown: old words
    assert "runner lost" in bridge.failure_hint(5)


def test_the_ceiling_comes_from_the_runner_config(tmp_path):
    import importlib.util as iu
    spec = iu.spec_from_file_location("runner_ceiling", ROOT / "scripts" / "runner_ceiling.py")
    rc = iu.module_from_spec(spec)
    spec.loader.exec_module(rc)
    assert rc.ceiling_s() == bridge.RUNNER_CEILING_S == 90 * 60
    f = tmp_path / "c.yaml"
    f.write_text("log:\n  level: info\nrunner:\n  capacity: 1\n  timeout: 150m\n")
    assert rc.ceiling_s(f) == 150 * 60
    f.write_text("runner:\n  timeout: soon\n")
    assert rc.ceiling_s(f) == rc.DEFAULT_S                                           # unreadable: 90 min
    assert rc.ceiling_s(tmp_path / "missing.yaml") == rc.DEFAULT_S


def test_a_picked_job_replaces_waiting_on_github(monkeypatch):
    """windy-admin #829 (10-29): waiting -> running is pending -> pending, and the description
    stayed "waiting" for the whole 80 min run. The words are compared for pending states."""
    sha = "c" * 40
    posts = []
    monkeypatch.setattr(bridge, "_repo_runs", lambda repo: [
        {"id": 9, "head_sha": sha, "workflow_id": "ci.yml", "name": "test", "status": "running", "run_number": 108}])
    monkeypatch.setattr(bridge, "queued_jobs", lambda repo, s: [])
    monkeypatch.setattr(bridge, "invalid_workflows", lambda repo, s: {})
    monkeypatch.setattr(bridge, "needs_daemon", lambda *a: False)
    current = [{"context": "windy-git/ci/test", "state": "pending", "description": "Windy Git CI on Veron 1: waiting"}]
    monkeypatch.setattr(bridge, "commit_statuses", lambda repo, s: current)
    monkeypatch.setattr(bridge, "github", lambda m, p, body=None: posts.append(body) or (201, {}))
    bridge.post_statuses("windy-admin", sha)
    assert [p["description"] for p in posts] == ["Windy Git CI on Veron 1: running"]
    posts.clear()
    current[0]["description"] = "Windy Git CI on Veron 1: running"
    bridge.post_statuses("windy-admin", sha)
    assert posts == []                                                               # same words: no POST
