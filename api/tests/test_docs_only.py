"""scripts/docs_only.py: docs-only heads start no test job (rule P4, Windy Boss GO 2026-11-11T04:56:12Z).

Invariants tested here (named in the GO's three terms):
  (1) the STRICT list only: TODO.md, README*, docs/; never "any .md" (ACCESS_LOCKBOX.md, doctrine files);
  (2) repos excluded by NAME are never touched; a docs path a test or CI file reads is never skipped;
      a push to windy-pro main always runs (Boss RULING 2026-11-11T05:06:52Z), its PR heads follow the rule;
  (3) the bridge posts each skipped context as success with "docs-only head: no test job", so a skipped
      test is never mistaken for a passed one; a real verdict always wins.
Also: DARK by default (nothing cancelled), and the cancel is one guarded statement (waiting and unclaimed only).
Real git repos in tmp, fake DB and BOARD.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("docs_only", ROOT / "scripts" / "docs_only.py")
do = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(do)
sys.modules["docs_only"] = do
_bspec = importlib.util.spec_from_file_location("pr_status_bridge", ROOT / "scripts" / "pr_status_bridge.py")
bridge = importlib.util.module_from_spec(_bspec)
_bspec.loader.exec_module(bridge)


def _g(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A work tree whose .git is the 'bare cache' docs_only reads (git --git-dir accepts it)."""
    work = tmp_path / "work"
    work.mkdir()
    _g(work, "init", "-q", "-b", "main")
    _g(work, "config", "user.email", "t@example.invalid")
    _g(work, "config", "user.name", "t")
    (work / "app.py").write_text("x = 1\n")
    (work / "TODO.md").write_text("- [ ] a\n")
    (work / "docs").mkdir()
    (work / "docs" / "guide.md").write_text("g\n")
    (work / "tests").mkdir()
    (work / "tests" / "test_app.py").write_text("def test_x():\n    assert 1\n")
    _g(work, "add", "-A")
    _g(work, "commit", "-q", "-m", "base")
    sync = tmp_path / "sync"
    sync.mkdir()
    (sync / "windy-chat.git").symlink_to(work / ".git")
    monkeypatch.setattr(do, "SYNC_ROOT", sync)
    return work


def _branch_commit(work, files: dict[str, str], name="feat"):
    _g(work, "checkout", "-q", "-B", name, "main")
    for p, t in files.items():
        f = work / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(t)
    _g(work, "add", "-A")
    _g(work, "commit", "-q", "-m", "change")
    sha = _g(work, "rev-parse", "HEAD")
    _g(work, "checkout", "-q", "main")
    return sha


@pytest.mark.parametrize("path,ok", [
    ("TODO.md", True), ("api/TODO.md", True), ("README.md", True), ("web/README", True), ("docs/a/b.md", True),
    ("ACCESS_LOCKBOX.md", False), ("CLAUDE.md", False), ("doctrine/00-GUIDING-PRINCIPLES.md", False),
    ("CHANGELOG.md", False), ("app.py", False), ("mydocs/x.md", False),
])
def test_term1_strict_list_only(path, ok):
    assert do.is_docs_path(path) is ok


def test_todo_only_pr_head_is_skipped(repo):
    sha = _branch_commit(repo, {"TODO.md": "- [x] a\n"})
    skip, why = do.docs_head("windy-chat", sha, "pull_request_sync")
    assert skip and "TODO.md" in why


def test_code_in_the_diff_runs_the_tests(repo):
    sha = _branch_commit(repo, {"TODO.md": "- [x] a\n", "app.py": "x = 2\n"})
    assert do.docs_head("windy-chat", sha, "pull_request") == (False, "not docs-only")


def test_any_md_that_is_not_docs_runs_the_tests(repo):
    sha = _branch_commit(repo, {"ACCESS_LOCKBOX.md": "NAME\n"})
    assert do.docs_head("windy-chat", sha, "pull_request")[0] is False


def test_term2_a_docs_path_a_test_reads_is_never_skipped(repo):
    (repo / "tests" / "test_legal.py").write_text("open('docs/legal/terms.md')\n")
    _g(repo, "add", "-A")
    _g(repo, "commit", "-q", "-m", "legal test")
    sha = _branch_commit(repo, {"docs/legal/terms.md": "t\n"})
    assert do.docs_head("windy-chat", sha, "pull_request") == (False, "docs-only but read by tests")


def test_term2_a_bare_docs_folder_read_counts_too(repo):
    (repo / "tests" / "walk.test.js").write_text("fs.readdirSync('docs/')\n")
    _g(repo, "add", "-A")
    _g(repo, "commit", "-q", "-m", "walk")
    sha = _branch_commit(repo, {"docs/guide.md": "g2\n"})
    assert do.docs_head("windy-chat", sha, "pull_request")[0] is False


def test_term2_a_test_that_reads_TODO_keeps_TODO_heads_running(repo):
    (repo / ".github").mkdir()
    (repo / ".github" / "workflows").mkdir()
    (repo / ".github" / "workflows" / "todo.yml").write_text("run: python check.py TODO.md\n")
    _g(repo, "add", "-A")
    _g(repo, "commit", "-q", "-m", "wf")
    sha = _branch_commit(repo, {"TODO.md": "- [x] a\n"})
    assert do.docs_head("windy-chat", sha, "pull_request")[0] is False


def test_unreadable_head_never_skips(repo):
    assert do.docs_head("windy-chat", "f" * 40, "pull_request") == (False, "diff unreadable")


def test_push_uses_the_commits_own_diff(repo):
    (repo / "README.md").write_text("r\n")
    _g(repo, "add", "-A")
    _g(repo, "commit", "-q", "-m", "readme")
    assert do.docs_head("windy-chat", _g(repo, "rev-parse", "HEAD"), "push")[0] is True


SHA = "a" * 40


def _row(i, repo="windy-chat", wf="ci.yml", job="test", sha=SHA, run=7):
    return [str(i), repo, "pull_request_sync", "refs/pull/3/head", sha, wf, job, str(run)]


class DB:
    def __init__(self, rows):
        self.rows, self.sql = rows, []

    def __call__(self, sql):
        self.sql.append(sql)
        if "select j.id, p.name" in sql:
            return self.rows
        if sql.lstrip().startswith("update action_run_job"):
            ids = sql.split("in (", 1)[1].split(")", 1)[0].split(",")
            return [[i, "77"] for i in ids]
        if "to_regclass" in sql:
            return [["t"]]
        return []


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(do, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(do, "LOG", tmp_path / "docs-only.log")
    monkeypatch.setattr(do, "ON_FILE", tmp_path / "docs-only.on")
    monkeypatch.setattr(do, "EXCLUDE", {"windy-excluded"})
    monkeypatch.setattr(do, "PUSH_EXCLUDE", {"windy-pro"})
    return tmp_path


def test_dark_by_default_cancels_nothing_and_logs_once(paths):
    db, posts = DB([_row(1), _row(2, wf="canonical-domains-lint.yml", job="lint")]), []
    do.main(query=db, post=posts.append, decide=lambda r, s, e: (True, "docs-only, 1 path(s): TODO.md"), repos={"windy-chat"})
    assert not any(s.lstrip().startswith("update") for s in db.sql) and posts == []
    log = (paths / "docs-only.log").read_text()
    assert "DARK would cancel job 1" in log and "lint" not in log      # kept workflows are never listed
    do.main(query=db, post=posts.append, decide=lambda r, s, e: pytest.fail("decided twice"), repos={"windy-chat"})
    assert do.contexts_for("windy-chat", SHA) == []                    # dark: the bridge paints nothing


def test_on_cancels_only_guarded_waiting_unclaimed_jobs_and_records_contexts(paths):
    (paths / "docs-only.on").touch()
    db, posts = DB([_row(1), _row(2, job="e2e"), _row(3, wf="adr-046-lint.yml", job="lint")]), []
    do.main(query=db, post=posts.append, decide=lambda r, s, e: (True, "docs-only"), repos={"windy-chat"})
    upd = [s for s in db.sql if s.lstrip().startswith("update action_run_job")]
    assert len(upd) == 1 and "in (1,2)" in upd[0] and "j.status in (5, 7, 9) and j.task_id = 0" in upd[0]
    assert [c["context"] for c in do.contexts_for("windy-chat", SHA)] == ["windy-git/ci/e2e", "windy-git/ci/test"]
    assert len(posts) == 1 and "docs-only head: no test job" in posts[0]


def test_excluded_and_unbridged_repos_are_never_touched(paths):
    (paths / "docs-only.on").touch()
    db = DB([_row(1, repo="windy-excluded"), _row(2, repo="windy-git", sha="b" * 40)])
    do.main(query=db, post=lambda line: None, decide=lambda r, s, e: pytest.fail("decided"), repos={"windy-excluded", "windy-chat"})
    assert not any(s.lstrip().startswith("update") for s in db.sql)


def test_windy_pro_main_push_always_runs_but_its_pr_heads_follow_the_rule(paths):
    """Boss RULING 2026-11-11T05:06:52Z: a push to windy-pro main runs the whole suite; its PR heads follow P4."""
    (paths / "docs-only.on").touch()
    push = ["1", "windy-pro", "push", "refs/heads/main", SHA, "ci.yml", "gates", "7"]
    pr = _row(2, repo="windy-pro", sha="c" * 40)
    db = DB([push, pr])
    do.main(query=db, post=lambda line: None, decide=lambda r, s, e: (True, "docs-only"), repos={"windy-pro"})
    upd = [s for s in db.sql if s.lstrip().startswith("update action_run_job")]
    assert len(upd) == 1 and "in (2)" in upd[0]


def test_not_docs_only_head_is_left_alone(paths):
    (paths / "docs-only.on").touch()
    db = DB([_row(1)])
    do.main(query=db, post=lambda line: None, decide=lambda r, s, e: (False, "not docs-only"), repos={"windy-chat"})
    assert not any(s.lstrip().startswith("update") for s in db.sql)


def test_a_db_error_never_fails_the_sync(paths):
    def boom(sql):
        raise RuntimeError("db down")
    assert do.main(query=boom, post=lambda line: None, repos={"windy-chat"}) == 0


# --- term (3): the bridge ---------------------------------------------------------------------------------------

class GH:
    def __init__(self, runs=()):
        self.runs, self.posted = list(runs), []

    def gitea(self, method, path, body=None):
        if "/contents/" in path:
            return 404, None
        if "/actions/tasks" in path:
            return 200, {"workflow_runs": self.runs}
        raise AssertionError(path)

    def github(self, method, path, body=None):
        if method == "GET":
            return 200, []
        self.posted.append(body)
        return 201, {}


@pytest.fixture
def gh(monkeypatch):
    def make(runs=(), queued=(), ctxs=()):
        f = GH(runs)
        bridge._RUNS_CACHE.clear()
        bridge._STATUSES_CACHE.clear()
        monkeypatch.setattr(bridge, "gitea", f.gitea)
        monkeypatch.setattr(bridge, "github", f.github)
        monkeypatch.setattr(bridge, "graphql", lambda q: (503, None))
        monkeypatch.setattr(bridge, "queued_jobs", lambda repo, sha: list(queued))
        monkeypatch.setattr(bridge, "docs_only_contexts", lambda repo, sha: [{"context": c, "run": 7} for c in ctxs])
        return f
    return make


def test_term3_skipped_context_reads_success_with_the_docs_only_words(gh):
    f = gh(ctxs=["windy-git/ci/test"])
    bridge.post_statuses("windy-chat", SHA)
    assert [(p["context"], p["state"], p["description"]) for p in f.posted] == [
        ("windy-git/ci/test", "success", "docs-only head: no test job (rule P4)")]


def test_term3_a_real_verdict_or_a_queued_rerun_wins(gh):
    run = {"id": 9, "workflow_id": "ci.yml", "name": "test", "status": "failure", "head_sha": SHA, "run_number": 8}
    f = gh(runs=[run], ctxs=["windy-git/ci/test"])
    bridge.post_statuses("windy-chat", SHA)
    assert [(p["context"], p["state"]) for p in f.posted] == [("windy-git/ci/test", "failure")]
    f = gh(queued=[{"run_number": 9, "workflow_id": "ci.yml", "name": "test"}], ctxs=["windy-git/ci/test"])
    bridge.post_statuses("windy-chat", SHA)
    assert [(p["context"], p["state"]) for p in f.posted] == [("windy-git/ci/test", "pending")]


def test_bridge_without_docs_state_paints_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(do, "STATE", tmp_path / "missing.json")
    monkeypatch.setattr(bridge, "_DOCS_STATE", None)
    assert bridge.docs_only_contexts("windy-chat", SHA) == []
