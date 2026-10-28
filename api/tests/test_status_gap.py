"""scripts/status_gap.py: every head older than 30 min gets Windy Git CI statuses for each workflow
that should run, or an explained INFO, or a WARN (Boss 10-28: #1582 and windy-admin 70a3c27)."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("GITEA_SYNC_TOKEN", "x")
os.environ.setdefault("GITHUB_TOKEN", "x")
_spec = importlib.util.spec_from_file_location("status_gap", ROOT / "scripts" / "status_gap.py")
sg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sg)

WINDY_PRO_CI = {"push": {"branches": ["main"]},
                "pull_request": {"branches": ["main"], "paths-ignore": ["**/*.md", "docs/**", "site/**"]}}


def test_paths_ignore_skips_a_docs_only_pr_exactly_like_1582():
    assert sg.triggers(WINDY_PRO_CI, "pull_request", ["docs/handtest/grant-notes.json"], "main") is False
    assert sg.triggers(WINDY_PRO_CI, "pull_request", ["docs/a.md", "src/x.js"], "main") is True
    assert sg.triggers(WINDY_PRO_CI, "pull_request", ["README.md"], "main") is False      # **/*.md at the root too
    assert sg.triggers(WINDY_PRO_CI, "push", ["docs/x"], "main") is True                  # push has no filter
    assert sg.triggers(WINDY_PRO_CI, "workflow_dispatch", [], "main") is None


def test_paths_last_match_wins_and_star_stays_in_one_directory():
    on = {"pull_request": {"paths": ["src/**", "!src/gen/**", "src/gen/keep.js", "*.json"]}}
    assert sg.triggers(on, "pull_request", ["src/a/b.js"], "main") is True
    assert sg.triggers(on, "pull_request", ["src/gen/x.js"], "main") is False
    assert sg.triggers(on, "pull_request", ["src/gen/keep.js"], "main") is True
    assert sg.triggers(on, "pull_request", ["sub/package.json"], "main") is False         # * doesn't cross /
    assert sg.triggers(on, "pull_request", ["package.json"], "main") is True


def test_branch_filters_and_the_short_on_forms():
    assert sg.triggers({"push": {"branches": ["release/*"]}}, "push", [], "main") is False
    assert sg.triggers({"push": {"branches-ignore": ["main"]}}, "push", [], "main") is False
    assert sg.triggers("push", "push", [], "main") is True
    assert sg.triggers(["push", "pull_request"], "pull_request", ["x"], "main") is True
    assert sg.triggers({"push": None}, "push", ["x"], "main") is True


def _jobs(table):
    return lambda wf: table.get(wf)


def test_evaluate_names_every_reason():
    dec = {"ci.yml": True, "lint.yml": False, "deploy.yml": True, "build.yml": True,
           "img.yml": True, "manual.yml": None}
    ctx = ["windy-git/compute-guard", "windy-git/build/test"]
    warns, infos = sg.evaluate("repo-x", ctx, dec, _jobs({"img.yml": ["Docker build"], "ci.yml": None}),
                               frozenset({"deploy.yml"}))
    assert warns == ["no Gitea run was created although ci.yml should run"], warns
    assert "lint.yml skipped by its branches/paths filter" in infos
    assert "deploy.yml is disabled on Windy Git by design (repo Actions settings)" in infos
    assert any(i.startswith("img.yml ran, but only jobs the bridge hides") for i in infos)
    assert not any("build.yml" in x for x in warns + infos)        # covered by windy-git/build/test
    assert not any("manual.yml" in x for x in warns + infos)       # doesn't listen to the event


def test_a_workflow_that_ran_but_posted_nothing_is_a_bridge_warn_and_lint_does_not_cover_ci():
    ctx = ["windy-git/canonical-domains-lint/lint"]                   # #1582 had this, but no ci/*
    warns, _ = sg.evaluate("repo-x", ctx, {"ci.yml": True, "canonical-domains-lint.yml": True},
                           _jobs({"ci.yml": ["gates", "test"]}))
    assert warns == ["ci.yml ran on Windy Git but no windy-git/ci/* status was posted (bridge)"], warns


def test_nothing_listening_is_info_only():
    warns, infos = sg.evaluate("repo-x", [], {"a.yml": None}, _jobs({}))
    assert warns == [] and infos == ["no workflow listens to this event"]


def test_disabled_workflows_reads_the_actions_unit_config():
    q = lambda sql: [['{"DisabledWorkflows":["deploy.yml","release.yml"]}']]  # noqa: E731
    assert sg.disabled_workflows("windy-pro", q) == {"deploy.yml", "release.yml"}
    assert sg.disabled_workflows("windy-pro", lambda sql: []) == set()
    assert sg.disabled_workflows("bad name;", q) == set()


def _fake_bridge(monkeypatch, calls, budget=5000):
    """A one-repo world: one PR head 2 h old, covered by windy-git/ci/test."""
    monkeypatch.setattr(sg.b, "REPOS", ["repo-x"])
    sha = "a" * 40

    def github(method, path, body=None):
        calls.append(path)
        if path == "/rate_limit":
            return 200, {"resources": {"core": {"remaining": budget}}}
        if path.endswith("/pulls?state=open&per_page=100"):
            return 200, [{"number": 7, "head": {"sha": sha, "repo": {"full_name": "sneakyfree/repo-x"}},
                          "base": {"ref": "main"}, "updated_at": "2000-01-01T00:00:00Z"}]
        if path == "/repos/sneakyfree/repo-x":
            return 200, {"default_branch": "main"}
        return 404, {}
    monkeypatch.setattr(sg.b, "github", github)
    monkeypatch.setattr(sg.b, "gitea", lambda m, p, body=None: (200, {}))
    monkeypatch.setattr(sg.b, "commit_statuses", lambda r, s: calls.append("statuses") or [{"context": "windy-git/ci/test"}])
    monkeypatch.setattr(sg, "workflow_ons", lambda r, s: {"ci.yml": {"pull_request": None}})
    monkeypatch.setattr(sg, "disabled_workflows", lambda r: set())


def test_a_covered_head_is_cached_and_never_read_again(monkeypatch, tmp_path, capsys):
    calls: list[str] = []
    _fake_bridge(monkeypatch, calls)
    monkeypatch.setattr(sg, "STATE", tmp_path / "s.json")
    sg.main()
    assert calls.count("statuses") == 1 and "status gaps: none" in capsys.readouterr().out
    calls.clear()
    sg.main()
    assert "statuses" not in calls                                   # cached: no second read
    assert not any(c.startswith("/repos/sneakyfree/repo-x") and c.count("/") == 3 for c in calls)  # default branch cached


def test_it_refuses_under_the_budget_floor_and_reads_nothing(monkeypatch, tmp_path, capsys):
    calls: list[str] = []
    _fake_bridge(monkeypatch, calls, budget=1499)
    monkeypatch.setattr(sg, "STATE", tmp_path / "s.json")
    sg.main()
    assert calls == ["/rate_limit"]
    assert "status gaps: skipped (GitHub API budget 1499 < 1500" in capsys.readouterr().out
