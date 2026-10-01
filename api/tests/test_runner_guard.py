"""runner-guard: workflow shapes that hand a self-hosted runner to strangers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("runner_guard", ROOT / "scripts" / "runner_guard.py")
rg = importlib.util.module_from_spec(_spec)
sys.modules["runner_guard"] = rg
_spec.loader.exec_module(rg)


def rules(text):
    return [(r, ln) for _p, ln, r, _m in rg.lint_text("w.yml", text)]


def test_pull_request_target_always_fails():
    assert rules("on: pull_request_target\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps: []\n")[0][0] == "R1"


def test_fork_pr_on_self_hosted_fails_and_points_at_runs_on():
    wf = "on:\n  pull_request:\njobs:\n  t:\n    runs-on: [self-hosted, linux, x64]\n    steps: []\n"
    assert rules(wf) == [("R2", 5)]


def test_same_repo_gate_or_environment_passes():
    gated = ("on: [pull_request]\njobs:\n  t:\n    if: github.event.pull_request.head.repo.full_name == github.repository\n"
             "    runs-on: [self-hosted]\n    steps: []\n")
    env = "on: [pull_request]\njobs:\n  t:\n    environment: ci\n    runs-on: self-hosted\n    steps: []\n"
    assert rules(gated) == [] and rules(env) == []


def test_outsider_events_on_self_hosted_fail_but_writer_events_pass():
    wf = "on:\n  issue_comment:\n  workflow_run:\n    workflows: [x]\njobs:\n  t:\n    runs-on: self-hosted\n    steps: []\n"
    assert sorted(r for r, _ in rules(wf)) == ["R3", "R3"]
    ok = "on:\n  push:\n    tags: ['v*']\n  workflow_dispatch:\n  schedule:\n    - cron: '0 3 * * *'\njobs:\n  t:\n    runs-on: self-hosted\n    steps: []\n"
    assert rules(ok) == []


def test_expression_runs_on_is_treated_as_self_hosted_and_hosted_runner_is_fine():
    expr = "on: pull_request\njobs:\n  t:\n    runs-on: ${{ matrix.os }}\n    steps: []\n"
    hosted = "on: pull_request\njobs:\n  t:\n    runs-on: ubuntu-latest\n    steps: []\n"
    assert rules(expr) == [("R2", 4)] and rules(hosted) == []


def test_broken_yaml_is_a_finding_and_non_workflows_are_ignored():
    assert rules("on: [push\njobs: {")[0][0] == "R0"
    assert rules("name: just a file\n") == []


def test_pr_mode_posts_each_status_once(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(rg, "STATE", str(tmp_path / "s.json"))
    monkeypatch.setattr(rg, "public_repos", lambda owners: [("o/r", "main")])
    monkeypatch.setattr(rg, "file_at", lambda *a: "on: push\\njobs:\\n  t:\\n    runs-on: self-hosted\\n    steps: []\\n")

    def fake_gh(*args, check=True):
        if args[0].startswith("repos/o/r/pulls?"):
            return "7 abc123 o/r\\n"
        if args[0].endswith("/files?per_page=100"):
            return ".github/workflows/ci.yml\\n"
        calls.append(args[0])
        return ""
    monkeypatch.setattr(rg, "gh", fake_gh)
    rg.cmd_pr(["o"], post=True)
    rg.cmd_pr(["o"], post=True)
    assert calls == ["repos/o/r/statuses/abc123"]
