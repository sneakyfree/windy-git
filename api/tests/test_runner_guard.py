"""runner-guard: workflow shapes that hand a self-hosted runner to strangers."""

from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("runner_guard", ROOT / "scripts" / "runner_guard.py")
rg = importlib.util.module_from_spec(_spec)
sys.modules["runner_guard"] = rg
_spec.loader.exec_module(rg)


@pytest.fixture(autouse=True)
def _private_cache(tmp_path, monkeypatch):
    # birth-terms caches public scans per head: never read or write the live cache in tests
    monkeypatch.setattr(rg.birth_terms.cg, "CACHE", tmp_path / "bt-cache.json")


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
            return '{"f": ".github/workflows/ci.yml", "p": null}\n'
        calls.append((args[0], [a for a in args if a.startswith("context=")]))
        return ""
    monkeypatch.setattr(rg, "gh", fake_gh)
    rg.cmd_pr(["o"], post=True)
    rg.cmd_pr(["o"], post=True)
    # posted ONCE across both passes; no birth-terms status when there is nothing to say
    assert calls == [("repos/o/r/statuses/abc123", ["context=windy-git/runner-guard"])]



def test_pr_files_error_skips_that_pr_and_the_pass_goes_on(monkeypatch, tmp_path):
    # Hub #53: a rate-limit 403 (or 404/5xx, or an HTML body) on one PR's files call must not
    # crash the pass: that PR gets no status this run, later PRs still do, state is saved.
    calls = []
    state = tmp_path / "s.json"
    monkeypatch.setattr(rg, "STATE", str(state))
    monkeypatch.setattr(rg, "public_repos", lambda owners: [("o/r", "main")])
    monkeypatch.setattr(rg, "file_at", lambda *a: "")

    def fake_gh(*args, check=True):
        if args[0].startswith("repos/o/r/pulls?"):
            return "7 aaa111 o/r\n8 bbb222 o/r\n9 ccc333 o/r\n"
        if args[0] == "repos/o/r/pulls/7/files?per_page=100":
            raise RuntimeError("gh api 403")                       # gh exits non-zero
        if args[0] == "repos/o/r/pulls/8/files?per_page=100":
            return '{"message": "API rate limit exceeded", "documentation_url": "x"}\n'
        if args[0] == "repos/o/r/pulls/9/files?per_page=100":
            return '{"f": "docs/a.md", "p": "@@ -0,0 +1 @@\\n+see the hub"}\n'
        calls.append((args[0], [a for a in args if a.startswith("context=")]))
        return ""
    monkeypatch.setattr(rg, "gh", fake_gh)
    assert rg.cmd_pr(["o"], post=True) == 0
    assert calls == [("repos/o/r/statuses/ccc333", ["context=windy-git/birth-terms"]),
                     ("repos/o/r/statuses/ccc333", ["context=windy-git/runner-guard"])]
    assert state.exists()


def test_pr_files_rejects_non_file_rows(monkeypatch):
    monkeypatch.setattr(rg, "gh", lambda *a, check=True: "<html>502 Bad Gateway</html>\n")
    assert rg.pr_files("o/r", "1") is None
    monkeypatch.setattr(rg, "gh", lambda *a, check=True: '["not", "a", "dict"]\n')
    assert rg.pr_files("o/r", "1") is None
    monkeypatch.setattr(rg, "gh", lambda *a, check=True: '{"f": "a.md", "p": null, "c": 2}\n')
    assert rg.pr_files("o/r", "1") == [{"f": "a.md", "p": None, "c": 2}]


BAD_WF = "on: issue_comment\njobs:\n  t:\n    runs-on: self-hosted\n    steps: []\n"


def _pr_world(monkeypatch, tmp_path, files_rows, contents):
    calls, state = [], tmp_path / "s.json"
    monkeypatch.setattr(rg, "STATE", str(state))
    monkeypatch.setattr(rg, "public_repos", lambda owners: [("o/r", "main")])

    def fake_gh(*args, check=True):
        if args[0].startswith("repos/o/r/pulls?"):
            return "7 aaa111 o/r\n"
        if args[0] == "repos/o/r/pulls/7/files?per_page=100":
            assert "--paginate" in args          # B2: every page, not just the first 100 files
            return files_rows
        if args[0].startswith("repos/o/r/contents/"):
            return contents(args[0])
        calls.append((args[0], [a for a in args if a.startswith(("context=", "state="))]))
        return ""
    monkeypatch.setattr(rg, "gh", fake_gh)
    return calls, state


def test_unreadable_workflow_contents_post_no_ok(monkeypatch, tmp_path):
    # Hub #53 B1: a 403 on the contents call used to read as "" and post a false OK.
    def contents(path):
        raise RuntimeError("gh api 403")
    calls, state = _pr_world(monkeypatch, tmp_path, '{"f": ".github/workflows/x.yml", "p": null}\n', contents)
    state.write_text('["o/r@aaa111:failure:BLOCKED: R3 earlier"]')
    rg.cmd_pr(["o"], post=True)
    assert calls == []                                            # no status at all for that PR
    assert "o/r@aaa111:failure:BLOCKED: R3 earlier" in state.read_text()   # N1: kept, not pruned


def test_empty_contents_is_unreadable_too(monkeypatch):
    monkeypatch.setattr(rg, "gh", lambda *a, check=True: "\n")
    with pytest.raises(rg.Unreadable):
        rg.file_at("o/r", ".github/workflows/x.yml", "abc")


def test_a_workflow_on_page_two_is_seen(monkeypatch, tmp_path):
    # Hub #53 B2: gh --paginate concatenates the pages; the workflow is the 101st file.
    rows = "".join(f'{{"f": "src/f{i}.py", "p": null}}\n' for i in range(100))
    rows += '{"f": ".github/workflows/x.yml", "p": null}\n'
    b64 = base64.b64encode(BAD_WF.encode()).decode()
    calls, _ = _pr_world(monkeypatch, tmp_path, rows, lambda path: b64)
    rg.cmd_pr(["o"], post=True)
    assert [c for c in calls if "context=windy-git/runner-guard" in c[1]][0][1][0] == "state=failure"


def test_files_at_githubs_3000_cap_are_unreadable(monkeypatch):
    rows = "".join(f'{{"f": "f{i}.md", "p": null, "s": "modified"}}\n' for i in range(rg.FILES_CAP))
    monkeypatch.setattr(rg, "gh", lambda *a, check=True: rows)
    assert rg.pr_files("o/r", "1") is None
    monkeypatch.setattr(rg, "gh", lambda *a, check=True: '{"f": "gone.yml", "p": null, "s": "removed"}\n')
    assert rg.pr_files("o/r", "1") == []                         # removed files are not judged
    monkeypatch.setattr(rg, "gh", lambda *a, check=True: '{"f": "a.md", "p": null, "s": "added", "c": 4}\n')
    assert rg.pr_files("o/r", "1") == [{"f": "a.md", "p": None, "c": 4}]


def test_report_is_an_error_when_a_repo_is_unreadable(monkeypatch, capsys):
    monkeypatch.setattr(rg, "public_repos", lambda owners: [("o/a", "main"), ("o/b", "main")])

    def wf(full, branch):
        if full == "o/b":
            raise rg.Unreadable("x.yml")
        return []
    monkeypatch.setattr(rg, "workflows_at", wf)
    assert rg.cmd_report(["o"]) == 1
    out = capsys.readouterr().out
    assert "runner-guard sweep: ERROR (1 repo(s) unreadable: o/b)" in out and "0 hit" not in out


def _gh_fail(not_found):
    def f(*a, check=True):
        raise rg.GhError("gh api x failed", not_found=not_found)
    return f


def test_workflows_listing_404_is_none_but_other_errors_are_unreadable(monkeypatch):
    # Hub #53 sweep nit a: check=False read a 403 on the listing as "no workflows" (a clean repo).
    monkeypatch.setattr(rg, "gh", _gh_fail(not_found=True))
    assert rg.workflows_at("o/r", "main") == []
    monkeypatch.setattr(rg, "gh", _gh_fail(not_found=False))
    with pytest.raises(rg.Unreadable):
        rg.workflows_at("o/r", "main")


def test_gh_marks_only_a_real_404_as_not_found(monkeypatch):
    class R:
        def __init__(self, err):
            self.returncode, self.stdout, self.stderr = 1, "", err
    monkeypatch.setattr(rg.subprocess, "run", lambda *a, **k: R("gh: Not Found (HTTP 404)"))
    with pytest.raises(rg.GhError) as e:
        rg.gh("repos/o/r/contents/x")
    assert e.value.not_found
    monkeypatch.setattr(rg.subprocess, "run", lambda *a, **k: R("gh: API rate limit exceeded (HTTP 403)"))
    with pytest.raises(rg.GhError) as e:
        rg.gh("repos/o/r/contents/x")
    assert not e.value.not_found


def test_repo_list_failure_or_zero_repos_is_an_error(monkeypatch, capsys, tmp_path):
    # Hub #53 sweep nit b: a failed or empty repo list read as "0 hit(s) in 0 public repos".
    monkeypatch.setattr(rg, "gh", _gh_fail(not_found=False))
    assert rg.cmd_report(["o"]) == 1
    assert "runner-guard sweep: ERROR (repo list of o unreadable)" in capsys.readouterr().out
    monkeypatch.setattr(rg, "gh", lambda *a, check=True: "\n")
    assert rg.cmd_report(["o"]) == 1
    assert "ERROR (repo lists (0 public repos) unreadable)" in capsys.readouterr().out
    # the PR pass leaves the posted state untouched instead of pruning every key
    state = tmp_path / "s.json"
    state.write_text('["o/r@aaa111:success:OK: no workflow changes"]')
    monkeypatch.setattr(rg, "STATE", str(state))
    assert rg.cmd_pr(["o"], post=True) == 1
    assert "o/r@aaa111" in state.read_text()


def test_open_pr_list_is_paginated_and_a_failed_list_keeps_that_repos_keys(monkeypatch, tmp_path):
    # Hub #53 sweep nit c: only the first 50 open PRs were ever judged.
    state = tmp_path / "s.json"
    state.write_text('["o/a@aaa111:success:OK: no workflow changes", "o/b@bbb222:success:OK: no workflow changes"]')
    monkeypatch.setattr(rg, "STATE", str(state))
    monkeypatch.setattr(rg, "public_repos", lambda owners: [("o/a", "main"), ("o/b", "main")])
    seen_args = []

    def fake_gh(*args, check=True):
        if args[0].startswith("repos/o/a/pulls?"):
            seen_args.append(args)
            raise rg.GhError("gh api 502")
        if args[0].startswith("repos/o/b/pulls?"):
            seen_args.append(args)
            return ""                       # o/b really has no open PRs any more
        raise AssertionError(args[0])
    monkeypatch.setattr(rg, "gh", fake_gh)
    rg.cmd_pr(["o"], post=True)
    assert all("--paginate" in a and "per_page=100" in a[0] for a in seen_args)
    kept = state.read_text()
    assert "o/a@aaa111" in kept and "o/b@bbb222" not in kept   # failed list kept; closed PR pruned


def test_report_end_to_end_403_listing_is_an_error_and_404_is_no_workflows(monkeypatch, capsys):
    # Hub (#55 follow-up): pin the whole chain at the gh() level, not workflows_at alone.
    def world(listing_404):
        def fake_gh(*args, check=True):
            if args[0].startswith("users/o/repos"):
                return "o/r main\n"
            if args[0].startswith("repos/o/r/contents/.github/workflows"):
                raise rg.GhError("gh api contents failed", not_found=listing_404)
            raise AssertionError(args[0])
        return fake_gh
    monkeypatch.setattr(rg, "gh", world(listing_404=False))
    assert rg.cmd_report(["o"]) == 1
    assert "runner-guard sweep: ERROR (1 repo(s) unreadable: o/r)" in capsys.readouterr().out
    monkeypatch.setattr(rg, "gh", world(listing_404=True))
    assert rg.cmd_report(["o"]) == 0
    assert "runner-guard sweep: 0 hit(s) in 1 public repos" in capsys.readouterr().out


def _bt_world(monkeypatch, tmp_path, rows):
    calls = []
    monkeypatch.setattr(rg, "STATE", str(tmp_path / "s.json"))
    monkeypatch.setattr(rg, "public_repos", lambda owners: [("sneakyfree/windy-pro", "main")])

    def fake_gh(*args, check=True):
        if args[0].startswith("repos/sneakyfree/windy-pro/pulls?"):
            return "7 aaa111 sneakyfree/windy-pro\n"
        if args[0].endswith("/files?per_page=100"):
            return rows
        if "/contents/" in args[0]:
            return base64.b64encode(b"x\n").decode()
        calls.append([a for a in args if a.startswith(("context=", "state=", "description="))])
        return ""
    monkeypatch.setattr(rg, "gh", fake_gh)
    return calls


def test_pr_pass_posts_a_not_checked_note_when_github_omits_an_md_diff(monkeypatch, tmp_path):
    calls = _bt_world(monkeypatch, tmp_path, '{"f": "docs/huge.md", "p": null, "s": "modified", "c": 40000}\n')
    rg.cmd_pr(["sneakyfree"], post=True)
    bt_posts = [c for c in calls if "context=windy-git/birth-terms" in c]
    assert len(bt_posts) == 1 and "state=success" in bt_posts[0]
    assert "1 .md file(s) not checked" in [a for a in bt_posts[0] if a.startswith("description=")][0]


def test_pr_pass_splits_grant_owned_prose_on_the_public_path(monkeypatch, tmp_path):
    monkeypatch.setattr(rg.birth_terms, "MODE", "block")
    rows = '{"f": "src/client/desktop/README.md", "p": "@@ -0,0 +1 @@\\n+the hub", "s": "added", "c": 1}\n'
    calls = _bt_world(monkeypatch, tmp_path, rows)
    rg.cmd_pr(["sneakyfree"], post=True)
    post = [c for c in calls if "context=windy-git/birth-terms" in c][0]
    assert "state=success" in post and any("Grant-owned" in a for a in post)   # never blocks Grant's code
    lane, grant = rg.grant_split("sneakyfree/windy-pro", "aaa111",
                                 [rg.birth_terms.cg.Finding("docs/a.md", 1, "use x", "the hub")])
    assert len(lane) == 1 and grant == []
    assert rg.grant_split("VERONTECH/windy-pro", "aaa111", lane) == (lane, [])


def test_pr_pass_clears_a_status_this_head_already_carries(monkeypatch, tmp_path):
    calls = _bt_world(monkeypatch, tmp_path, '{"f": "docs/a.md", "p": "@@ -0,0 +1 @@\\n+`the hub`", "s": "added", "c": 1}\n')
    (tmp_path / "s.json").write_text('["sneakyfree/windy-pro@aaa111:windy-git/birth-terms:success:⚠ WARN: old"]')
    rg.cmd_pr(["sneakyfree"], post=True)
    rg.cmd_pr(["sneakyfree"], post=True)
    posts = [c for c in calls if "context=windy-git/birth-terms" in c]
    assert len(posts) == 1 and "description=OK: no retired agent-birth words added" in posts[0]   # once
