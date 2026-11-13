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
            return [["attempts", "t"]]
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


# --- the push guard (MISSES/ASK 2026-11-12T10:02:54Z: 14 of 110 docs-only main pushes failed in the dark day) ---

P1, P2 = "1" * 40, "2" * 40


def _push(i, sha=SHA, repo="windy-chat", wf="ci.yml", job="test"):
    return [str(i), repo, "push", "refs/heads/main", sha, wf, job, "7"]


class PushDB(DB):
    """DB with the parent job's (id, status) per parent sha."""
    def __init__(self, rows, parents):
        super().__init__(rows)
        self.parents = parents

    def __call__(self, sql):
        if "and r.event = 'push' and r.ref =" in sql:
            self.sql.append(sql)
            for sha, row in self.parents.items():
                if f"j.commit_sha = '{sha}'" in sql:
                    return [row] if row else []
            return []
        return super().__call__(sql)


@pytest.fixture
def chain(monkeypatch):
    monkeypatch.setattr(do, "parent_sha", lambda repo, sha: {SHA: P1, P1: P2}.get(sha))
    monkeypatch.setattr(do, "PUSHES", "guarded")


def _updates(db):
    return [s for s in db.sql if s.lstrip().startswith("update action_run_job")]


def test_push_skips_when_the_parents_same_job_ended_success(paths, chain):
    (paths / "docs-only.on").touch()
    db = PushDB([_push(1)], {P1: ["50", "1"]})
    do.main(query=db, post=lambda line: None, decide=lambda r, s, e: (True, "docs-only"), repos={"windy-chat"})
    assert len(_updates(db)) == 1 and "in (1)" in _updates(db)[0]


@pytest.mark.parametrize("status", ["2", "3", "4"])
def test_push_runs_when_the_parents_same_job_did_not_end_success(paths, chain, status):
    """P9: a TODO-only push carries the code before it; a red parent must not be painted green."""
    (paths / "docs-only.on").touch()
    db = PushDB([_push(1)], {P1: ["50", status]})
    do.main(query=db, post=lambda line: None, decide=lambda r, s, e: (True, "docs-only"), repos={"windy-chat"})
    assert _updates(db) == []
    assert do.load_state()[f"windy-chat@{SHA}#push"]["why"].startswith("push:")


def test_push_with_no_parent_job_runs(paths, chain):
    (paths / "docs-only.on").touch()
    db = PushDB([_push(1)], {})
    do.main(query=db, post=lambda line: None, decide=lambda r, s, e: (True, "docs-only"), repos={"windy-chat"})
    assert _updates(db) == []


def test_push_waits_while_the_parents_job_still_waits_then_decides(paths, chain):
    (paths / "docs-only.on").touch()
    db = PushDB([_push(1)], {P1: ["50", "5"]})
    do.main(query=db, post=lambda line: None, decide=lambda r, s, e: (True, "docs-only"), repos={"windy-chat"})
    assert _updates(db) == [] and f"windy-chat@{SHA}#push" not in do.load_state()    # nothing decided yet
    db.parents[P1] = ["50", "1"]
    do.main(query=db, post=lambda line: None, decide=lambda r, s, e: (True, "docs-only"), repos={"windy-chat"})
    assert len(_updates(db)) == 1


def test_push_follows_a_parent_this_rule_skipped_to_a_green_grandparent(paths, chain):
    (paths / "docs-only.on").touch()
    do.save_state({f"windy-chat@{P1}": {"at": __import__("time").time(), "skip": True, "mode": "on", "jobs": [50]}})
    db = PushDB([_push(1)], {P1: ["50", "3"], P2: ["40", "1"]})
    do.main(query=db, post=lambda line: None, decide=lambda r, s, e: (True, "docs-only"), repos={"windy-chat"})
    assert len(_updates(db)) == 1


def test_a_cancelled_parent_this_rule_did_not_skip_is_not_green(paths, chain):
    (paths / "docs-only.on").touch()
    db = PushDB([_push(1)], {P1: ["50", "3"], P2: ["40", "1"]})
    do.main(query=db, post=lambda line: None, decide=lambda r, s, e: (True, "docs-only"), repos={"windy-chat"})
    assert _updates(db) == []


def test_pushes_off_skips_no_push_but_pr_heads_still_follow_the_rule(paths, chain, monkeypatch):
    monkeypatch.setattr(do, "PUSHES", "off")
    (paths / "docs-only.on").touch()
    db = PushDB([_push(1), _row(2, sha="c" * 40)], {P1: ["50", "1"]})
    do.main(query=db, post=lambda line: None, decide=lambda r, s, e: (True, "docs-only"), repos={"windy-chat"})
    assert len(_updates(db)) == 1 and "in (2)" in _updates(db)[0]


def test_a_job_name_with_a_quote_is_escaped_in_the_parent_read():
    sql = do.parent_job_sql("windy-chat", "refs/heads/main", P1, "ci.yml", "it's (3.12)")
    assert "j.name = 'it''s (3.12)'" in sql


def test_parent_sha_reads_the_first_parent(repo):
    first = _g(repo, "rev-parse", "HEAD")
    (repo / "TODO.md").write_text("- [ ] x\n")
    _g(repo, "add", "-A")
    _g(repo, "commit", "-q", "-m", "todo")
    assert do.parent_sha("windy-chat", _g(repo, "rev-parse", "HEAD")) == first


# --- PER-JOB EVENT (Boss note 2026-11-12T10:15:45Z on #177): main() read jobs[0][2] for the whole (repo, sha) group ---

def test_a_sha_that_is_both_a_pr_head_and_a_push_decides_each_by_its_own_event(paths, chain):
    """Push row FIRST: the old code took 'push' for the whole group, so the PR job got the push diff and the push
    guard (red parent -> the PR job ran too). Now each kind is decided by its own event and diff."""
    (paths / "docs-only.on").touch()
    db = PushDB([_push(1), _row(2)], {P1: ["50", "2"]})          # the parent's same job is RED
    events = []

    def decide(r, s, e):
        events.append(e)
        return True, "docs-only"
    do.main(query=db, post=lambda line: None, decide=decide, repos={"windy-chat"})
    assert sorted(events) == ["pull_request_sync", "push"]
    assert len(_updates(db)) == 1 and "in (2)" in _updates(db)[0]   # the PR job skipped, the push job runs
    st = do.load_state()
    assert st[f"windy-chat@{SHA}"]["mode"] == "on" and st[f"windy-chat@{SHA}#push"]["why"].startswith("push:")


def test_pr_row_first_never_lets_the_push_job_skip_the_push_guard(paths, chain):
    (paths / "docs-only.on").touch()
    db = PushDB([_row(2), _push(1)], {P1: ["50", "3"]})          # cancelled parent this rule did not skip
    do.main(query=db, post=lambda line: None, decide=lambda r, s, e: (True, "docs-only"), repos={"windy-chat"})
    assert len(_updates(db)) == 1 and "in (2)" in _updates(db)[0] and "1" not in _updates(db)[0].split("in (")[1].split(")")[0].split(",")


def test_the_diff_is_decided_per_event_kind(paths, chain):
    """A PR diff (against the merge-base) can carry code while the push commit's own diff is docs-only."""
    (paths / "docs-only.on").touch()
    db = PushDB([_row(2), _push(1)], {P1: ["50", "1"]})
    do.main(query=db, post=lambda line: None,
            decide=lambda r, s, e: (e == "push", "docs-only" if e == "push" else "not docs-only"), repos={"windy-chat"})
    assert len(_updates(db)) == 1 and "in (1)" in _updates(db)[0]
    assert do.load_state()[f"windy-chat@{SHA}"]["skip"] is False


def test_each_kind_is_decided_once(paths, chain):
    db = PushDB([_push(1), _row(2)], {P1: ["50", "1"]})
    do.main(query=db, post=lambda line: None, decide=lambda r, s, e: (True, "docs-only"), repos={"windy-chat"})
    do.main(query=db, post=lambda line: None, decide=lambda r, s, e: pytest.fail("decided twice"), repos={"windy-chat"})


def test_contexts_for_reads_both_event_kinds_once_each():
    st = {f"windy-chat@{SHA}": {"mode": "on", "contexts": [{"context": "windy-git/ci/test", "run": 7}]},
          f"windy-chat@{SHA}#push": {"mode": "on", "contexts": [{"context": "windy-git/ci/test", "run": 7},
                                                                {"context": "windy-git/ci/e2e", "run": 8}]},
          f"windy-chat@{P1}#push": {"mode": "dark", "contexts": [{"context": "windy-git/ci/x", "run": 1}]}}
    assert [c["context"] for c in do.contexts_for("windy-chat", SHA, st)] == ["windy-git/ci/test", "windy-git/ci/e2e"]
    assert do.contexts_for("windy-chat", P1, st) == []
