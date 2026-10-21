"""autorerun: only infra-dead CI (dead-before-step, runner-lost), once per commit, never a real red,
never a commit that carries a non-allowlisted workflow. The SQL runs on a SQLite fixture DB."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("autorerun_dead_jobs", ROOT / "scripts" / "autorerun_dead_jobs.py")
ar = importlib.util.module_from_spec(_spec)
sys.modules["autorerun_dead_jobs"] = ar
_spec.loader.exec_module(ar)

SHA = "a" * 40
NOW = 2_000_000_000
ALLOW = {"windy-pro": {"ci.yml", "lint.yml"}, "r": {"ci.yml"}, "windycloud": {"ci.yml"}}


class DB:
    """The Gitea tables the script reads, with the columns it uses."""

    def __init__(self):
        self.c = sqlite3.connect(":memory:")
        self.c.executescript("""
        create table repository (id int, name text, owner_id int);
        create table secret (id int, repo_id int, owner_id int);
        create table action_run (id int, repo_id int, commit_sha text, ref text, "index" int,
                                 workflow_id text, event text);
        create table action_run_job (id int, run_id int, status int, task_id int, stopped int,
                                     runs_on text);
        create table action_runner (agent_labels text, deleted int);
        insert into action_runner values ('["veron-1","linux-x64","self-hosted"]', 0),
                                         ('["macos-latest"]', 1);
        create table action_task (id int, started int, stopped int);
        create table action_task_step (task_id int, "index" int, status int, log_length int, stopped int);
        create table issue (id int, repo_id int, "index" int);
        create table pull_request (id int, issue_id int, head_branch text, head_repo_id int);
        create table branch (repo_id int, name text, commit_id text, is_deleted int);
        insert into repository values (5, 'windy-pro', 1), (6, 'r', 1), (7, 'WindyCloud', 1);
        """)
        self.n = 0

    def q(self, sql):
        return [["" if v is None else str(v) for v in row] for row in self.c.execute(sql.strip().rstrip(";"))]

    def run(self, repo=5, wf="ci.yml", ev="push", idx=1, sha=SHA, ref="refs/heads/main"):
        self.n += 1
        self.c.execute("insert into action_run values (?,?,?,?,?,?,?)", (self.n, repo, sha, ref, idx, wf, ev))
        if ref.startswith("refs/heads/"):  # the pushed commit is the branch head unless a test moves it
            self.head(repo, ref[len("refs/heads/"):], sha)
        return self.n

    def head(self, repo, name, sha, deleted=0):
        self.c.execute("delete from branch where repo_id = ? and name = ?", (repo, name))
        self.c.execute("insert into branch values (?,?,?,?)", (repo, name, sha, deleted))

    def job(self, run, status, steps=(), stopped=NOW - 60, task_stop=None, secs=900, runs_on='["veron-1"]'):
        """steps: (status, log_length, stopped) per step, in order. No steps + status 2 = dead."""
        self.n += 1
        jid = task = self.n
        self.c.execute("insert into action_run_job values (?,?,?,?,?,?)", (jid, run, status, task, stopped, runs_on))
        ts = task_stop if task_stop is not None else stopped
        self.c.execute("insert into action_task values (?,?,?)", (task, ts - secs, ts))
        for i, (st, ln, sp) in enumerate(steps):
            self.c.execute("insert into action_task_step values (?,?,?,?,?)", (task, i, st, ln, sp))
        return jid


def lost_steps(stop):
    """windy-pro task 33941: steps ran, npm test failed mid-run, later step failed empty AT the stop."""
    return [(1, 76, stop - 900), (2, 10350, stop), (2, 0, stop)]


def real_steps(stop):
    """Error-code ratchet: failed for real, the runner marked the later steps skipped."""
    return [(1, 76, stop - 5), (2, 14, stop - 1), (4, 0, stop - 1)]


def judge(db, repo="windy-pro", repo_id=5):
    return ar.judge(repo, db.q(ar.commit_sql(repo_id, SHA)), ALLOW)


def test_runner_lost_commit_is_picked():
    db = DB()
    j = db.job(db.run(), 2, lost_steps(NOW - 60))
    db.job(db.run(wf="lint.yml"), 1, [(1, 5, NOW - 100)])
    assert judge(db) == ("runner-lost", str(j), "ok")


def test_dead_before_step_commit_is_picked():
    db = DB()
    j = db.job(db.run(), 2, [])
    assert judge(db) == ("dead-before-step", str(j), "ok")


def test_real_red_is_never_runner_lost_and_blocks_the_commit():
    db = DB()
    db.job(db.run(), 2, real_steps(NOW - 60))
    assert judge(db)[0] is None
    db2 = DB()   # the shared guard: a real red ANYWHERE at the commit blocks BOTH kinds
    db2.job(db2.run(), 2, [])
    db2.job(db2.run(wf="lint.yml"), 2, real_steps(NOW - 60))
    assert judge(db2) == (None, "", "a real red at the commit")
    db3 = DB()
    db3.job(db3.run(), 2, lost_steps(NOW - 60))
    db3.job(db3.run(wf="lint.yml"), 2, real_steps(NOW - 60))
    assert judge(db3) == (None, "", "a real red at the commit")


def test_lost_needs_every_mark():
    stop = NOW - 60
    for steps in ([(1, 76, stop - 900), (2, 10350, stop), (2, 3, stop)],       # later step has a log
                  [(1, 76, stop - 900), (2, 10350, stop), (2, 0, stop - 1)],   # not at the stop second
                  [(1, 76, stop - 900), (2, 0, stop), (2, 10350, stop)],       # empty one is FIRST, not later
                  [(1, 76, stop - 900), (2, 10350, stop), (4, 0, stop)]):      # later step skipped = runner-reported
        db = DB()
        db.job(db.run(), 2, steps)
        assert judge(db)[0] is None, steps
    db = DB()   # t.stopped > 0: a zero stop never matches
    db.job(db.run(), 2, [(1, 1, 0), (2, 5, 0), (2, 0, 0)], stopped=NOW - 60, task_stop=0)
    assert judge(db)[0] is None


def test_non_allowlisted_workflow_or_repo_refuses_the_commit():
    db = DB()
    db.job(db.run(), 2, [])
    db.job(db.run(wf="deploy.yml"), 1, [(1, 5, NOW - 100)])
    assert judge(db) == (None, "", "workflow not on the allowlist")
    db2 = DB()
    db2.job(db2.run(repo=6), 2, [])
    assert ar.judge("not-listed", db2.q(ar.commit_sql(6, SHA)), ALLOW) == (None, "", "workflow not on the allowlist")


def test_scheduled_runs_never_count():
    db = DB()
    db.job(db.run(wf="canary.yml", ev="schedule"), 2, [])
    assert judge(db) == (None, "", "no CI-event run")
    db.job(db.run(ev="push", idx=2), 2, [])        # a CI run beside it decides alone
    assert judge(db)[0] == "dead-before-step"


def test_a_running_workflow_blocks_the_commit():
    db = DB()
    db.job(db.run(), 2, [])
    db.job(db.run(wf="lint.yml"), 6, [(1, 5, 0)])
    assert judge(db) == (None, "", "a run is not finished")


def test_latest_run_is_per_workflow_and_event():
    """A newer pull_request_sync run must not hide an older real-red PUSH run of the same workflow."""
    db = DB()
    db.job(db.run(ev="push", idx=1), 2, real_steps(NOW - 60))
    db.job(db.run(ev="pull_request_sync", idx=2), 2, [])
    assert judge(db) == (None, "", "a real red at the commit")
    db2 = DB()   # a newer run of the SAME (workflow, event) supersedes: nothing infra-dead left
    db2.job(db2.run(idx=1), 2, [])
    db2.job(db2.run(idx=2), 1, [(1, 5, NOW - 10)])
    assert judge(db2) == (None, "", "nothing infra-dead in the latest runs")


def test_repo_with_actions_secrets_is_never_rerun():
    db = DB()
    db.job(db.run(), 2, [])
    db.c.execute("insert into secret values (1, 5, 0)")
    assert judge(db) == (None, "", "repo holds Actions secrets")
    db2 = DB()
    db2.job(db2.run(), 2, [])
    db2.c.execute("insert into secret values (1, 0, 1)")   # owner-level
    assert judge(db2) == (None, "", "repo holds Actions secrets")


def test_candidates_sql_window_events_and_assignment():
    db = DB()
    db.job(db.run(), 2, [], stopped=NOW - 60)
    db.job(db.run(sha="b" * 40), 2, [], stopped=NOW - 4000)                 # outside the window
    db.job(db.run(sha="c" * 40, wf="canary.yml", ev="schedule"), 2, [])     # not a CI event
    r = db.run(sha="d" * 40)
    db.c.execute("insert into action_run_job values (999, ?, 2, 0, ?, ?)", (r, NOW - 60, '["veron-1"]'))  # never assigned
    rows = db.q(ar.candidates_sql(NOW - ar.WINDOW_S))
    assert [x[2] for x in rows] == [SHA]


def test_plan_end_to_end_on_the_fixture():
    db = DB()
    db.job(db.run(), 2, lost_steps(NOW - 60))
    todo, why = ar.plan({}, ALLOW, NOW, query=db.q)
    assert [(t["key"], t["kind"], t["branch"]) for t in todo] == [(f"windy-pro@{SHA}", "runner-lost", "main")]
    assert ar.plan({f"windy-pro@{SHA}": {"at": 1}}, ALLOW, NOW, query=db.q)[0] == []   # once, ever


def test_plan_counts_refusals_and_caps_at_one_per_pass():
    db = DB()
    db.job(db.run(sha="e" * 40), 2, real_steps(NOW - 120), stopped=NOW - 120)   # judged first
    for c in "abc":
        db.job(db.run(sha=c * 40, ref=f"refs/heads/b{c}"), 2, [])   # each its own branch head
    todo, why = ar.plan({}, ALLOW, NOW, query=db.q)
    assert len(todo) == ar.MAX_PER_PASS == 1 and why == {"a real red at the commit": 1}


def test_branch_for_push_and_pull_refs():
    db = DB()
    db.c.execute("insert into issue values (1, 5, 247)")
    db.c.execute("insert into pull_request values (1, 1, 'word/stt', 5)")
    assert ar.branch_for("5", "refs/heads/main") == "main"
    assert ar.branch_for("5", "refs/pull/247/head", db.q) == "word/stt"
    assert ar.branch_for("5", "refs/pull/9/head", db.q) is None
    assert ar.branch_for("5", "refs/tags/v1") is None
    assert ar.branch_for("x; drop", "refs/pull/1/head") is None


def test_state_missing_is_empty_corrupt_is_refused_never_pruned(tmp_path, monkeypatch):
    p = tmp_path / "s.json"
    monkeypatch.setattr(ar, "STATE", p)
    assert ar.load_state() == {}
    for bad in ("not json", '["a"]', '{"k": 5}', "{torn"):
        p.write_text(bad)
        assert ar.load_state() is None, bad
    ar.save_state({"old@x": {"at": 1}})
    assert ar.load_state() == {"old@x": {"at": 1}}      # 'once ever' means ever: no pruning


def test_save_state_is_atomic(tmp_path, monkeypatch):
    p = tmp_path / "s.json"
    monkeypatch.setattr(ar, "STATE", p)
    seen = []
    real = ar.os.replace
    monkeypatch.setattr(ar.os, "replace", lambda a, b: (seen.append((str(a), str(b))), real(a, b)))
    ar.save_state({"a@b": {"at": 2}})
    assert seen and seen[0][1] == str(p) and seen[0][0] != str(p)
    assert sorted(x.name for x in tmp_path.iterdir()) == ["s.json"]


def test_allowlist_file_parses_and_malformed_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(ar, "ALLOW_FILE", ROOT / "ci" / "autorerun-allow.yml")
    allow = ar.load_allow()
    assert "ci.yml" in allow["windy-pro"] and "windy-git" not in allow
    bad = {"canary.yml", "substrate-drift.yml", "prod-drift.yml", "drift-check.yml"}
    assert not any(bad & wfs for wfs in allow.values())
    assert not any(w.startswith(("deploy", "release", "build-image", "build-installer")) for wfs in allow.values() for w in wfs)
    p = tmp_path / "a.yml"
    monkeypatch.setattr(ar, "ALLOW_FILE", p)
    assert ar.load_allow() is None
    p.write_text("repos: [1, 2]")
    assert ar.load_allow() is None


@pytest.fixture
def wired(tmp_path, monkeypatch):
    db = DB()
    monkeypatch.setattr(ar, "STATE", tmp_path / "s.json")
    monkeypatch.setattr(ar, "COUNTS", tmp_path / "c.json")
    monkeypatch.setattr(ar, "LOCK", tmp_path / "lock")
    monkeypatch.setattr(ar, "ALLOW_FILE", tmp_path / "allow.yml")
    (tmp_path / "allow.yml").write_text("repos:\n  windy-pro: [ci.yml, lint.yml]\n")
    monkeypatch.setattr(ar, "psql", db.q)
    monkeypatch.setattr(ar.time, "time", lambda: NOW)
    calls = []

    def fake_run(cmd, **k):
        calls.append({"cmd": cmd, "state": json.loads((tmp_path / "s.json").read_text())})

        class R:
            returncode, stdout = 0, "ok\n"
        return R()

    monkeypatch.setattr(ar.subprocess, "run", fake_run)
    return db, tmp_path, calls


def test_main_writes_ledger_before_and_exit_after(wired):
    db, tmp, calls = wired
    j = db.job(db.run(), 2, lost_steps(NOW - 60))
    assert ar.main() == 0
    assert len(calls) == 1 and calls[0]["cmd"][-1] == SHA[:8]
    before = calls[0]["state"][f"windy-pro@{SHA}"]
    assert (before["kind"], before["job"]) == ("runner-lost", str(j)) and "exit" not in before
    after = json.loads((tmp / "s.json").read_text())[f"windy-pro@{SHA}"]
    assert after["exit"] == 0 and after["runs_before"] == 1
    assert json.loads((tmp / "c.json").read_text()) == {"runner-lost": 1}
    assert ar.main() == 0 and len(calls) == 1          # once, ever


def test_main_rechecks_right_before_acting(wired, monkeypatch):
    db, tmp, calls = wired
    db.job(db.run(), 2, [])
    real_plan = ar.plan

    def plan_then_red(*a, **k):
        out = real_plan(*a, **k)
        db.job(db.run(wf="lint.yml", sha=SHA), 2, real_steps(NOW - 30))   # turns red after the pick
        return out

    monkeypatch.setattr(ar, "plan", plan_then_red)
    assert ar.main() == 0 and calls == []
    assert not (tmp / "s.json").exists()


def test_main_refuses_on_corrupt_ledger_or_allowlist(wired):
    db, tmp, calls = wired
    db.job(db.run(), 2, [])
    (tmp / "s.json").write_text("{torn")
    assert ar.main() == 1 and calls == [] and (tmp / "s.json").read_text() == "{torn"
    (tmp / "s.json").write_text("{}")
    (tmp / "allow.yml").write_text("::: no")
    assert ar.main() == 1 and calls == []


def test_main_skips_when_another_pass_holds_the_lock(wired):
    import fcntl

    db, tmp, calls = wired
    db.job(db.run(), 2, [])
    with open(tmp / "lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert ar.main() == 0 and calls == []
    assert ar.main() == 0 and len(calls) == 1          # lock released: the pass runs


def test_counts_accumulate_and_survive_garbage(tmp_path, monkeypatch):
    p = tmp_path / "c.json"
    monkeypatch.setattr(ar, "COUNTS", p)
    ar.bump_count("runner-lost")
    assert ar.bump_count("runner-lost") == {"runner-lost": 2}
    p.write_text("[1, 2]")
    assert ar.bump_count("dead-before-step") == {"dead-before-step": 1}


def test_first_step_real_failure_is_a_real_red_not_dead():
    """A job whose FIRST step failed for real ran a step: never dead-before-step."""
    db = DB()
    db.job(db.run(), 2, [(2, 14, NOW - 60), (4, 0, NOW - 60)])
    assert judge(db) == (None, "", "a real red at the commit")



def test_repo_name_case_matches_the_lowercase_allowlist():
    """Gitea keeps 'WindyCloud' / 'Windy-Clone'; without lowercasing they could never re-run."""
    db = DB()
    j = db.job(db.run(repo=7), 2, [])
    assert ar.judge("WindyCloud", db.q(ar.commit_sql(7, SHA)), ALLOW) == ("dead-before-step", str(j), "ok")
    assert "windycloud" in ar.load_allow() and "windy-clone" in ar.load_allow()


def test_instance_wide_secrets_count():
    db = DB()
    db.job(db.run(), 2, [])
    db.c.execute("insert into secret values (1, 0, 0)")
    assert judge(db) == (None, "", "repo holds Actions secrets")


def test_runner_lost_marks_on_a_3h_task_are_the_endless_cleanup_not_a_lost_runner():
    db = DB()
    db.job(db.run(), 2, lost_steps(NOW - 60), secs=ar.ENDLESS_S)
    assert judge(db) == (None, "", "a real red at the commit")
    db2 = DB()
    j = db2.job(db2.run(), 2, lost_steps(NOW - 60), secs=ar.ENDLESS_S - 1)
    assert judge(db2) == ("runner-lost", str(j), "ok")


def test_dead_before_step_with_green_siblings_from_the_same_push():
    """windy-mind ed3a4c27 (10-17 05:10Z): lint dead at index 2266, its siblings 2267-2269 green.
    The old 'any newer run at the sha' rule never re-ran it."""
    db = DB()
    j = db.job(db.run(wf="lint.yml", idx=2266), 2, [])
    db.job(db.run(wf="ci.yml", idx=2267), 1, [(1, 5, NOW - 50)])
    assert judge(db) == ("dead-before-step", str(j), "ok")


def test_cancelled_sibling_counts_as_red():
    db = DB()
    db.job(db.run(), 2, [])
    db.job(db.run(wf="lint.yml"), 3, [(1, 5, NOW - 50)])
    assert judge(db) == (None, "", "a real red at the commit")


def test_newer_dead_run_cannot_hide_an_older_real_red():
    db = DB()
    db.job(db.run(idx=1), 2, real_steps(NOW - 600), stopped=NOW - 600)
    db.job(db.run(idx=2), 2, [])
    assert judge(db) == (None, "", "a real red at the commit")


def test_pull_request_target_run_refuses_the_commit():
    db = DB()
    db.job(db.run(), 2, [])
    db.job(db.run(wf="ci.yml", ev="pull_request_target", idx=2), 1, [(1, 5, NOW - 50)])
    assert judge(db) == (None, "", "a pull_request_target run")


def test_max_index_is_the_newest_run_at_the_commit():
    db = DB()
    db.job(db.run(idx=3), 2, [])
    db.job(db.run(wf="lint.yml", idx=7), 1, [(1, 5, NOW - 50)])
    assert ar.max_index(db.q(ar.commit_sql(5, SHA))) == 7 and ar.max_index([]) == 0



def test_a_superseded_commit_is_skipped_and_keeps_its_try():
    """windy-chat d6a0a98 (10-18 09:14Z): picked after its branch moved on; rerun_ci.sh refused."""
    db = DB()
    db.job(db.run(), 2, [])
    db.head(5, "main", "f" * 40)                       # a newer push moved main
    todo, why = ar.plan({}, ALLOW, NOW, query=db.q)
    assert todo == [] and why == {"branch moved on": 1}
    db.head(5, "main", SHA)                            # back at the sha: eligible again (try kept)
    assert [t["kind"] for t in ar.plan({}, ALLOW, NOW, query=db.q)[0]] == ["dead-before-step"]


def test_deleted_or_unsafe_branch_is_never_at_head():
    db = DB()
    db.job(db.run(), 2, [])
    db.head(5, "main", SHA, deleted=1)
    assert ar.at_head(5, "main", SHA, db.q) is False
    for bad in ("x'; drop table branch; --", "a..b", "", "a b"):
        assert ar.at_head(5, bad, SHA, db.q) is False


def test_head_moving_between_pick_and_act_uses_no_try(wired, monkeypatch):
    db, tmp, calls = wired
    db.job(db.run(), 2, [])
    real_plan = ar.plan

    def plan_then_push(*a, **k):
        out = real_plan(*a, **k)
        db.head(5, "main", "f" * 40)                   # pushed after the pick
        return out

    monkeypatch.setattr(ar, "plan", plan_then_push)
    assert ar.main() == 0 and calls == []
    assert not (tmp / "s.json").exists()               # no ledger entry: the try is kept


def test_a_failed_attempt_on_the_current_head_still_uses_the_try(wired, monkeypatch):
    db, tmp, calls = wired
    db.job(db.run(), 2, [])

    def failing_run(cmd, **k):
        class R:
            returncode, stdout = 1, "refusing: something\n"
        return R()

    monkeypatch.setattr(ar.subprocess, "run", failing_run)
    assert ar.main() == 0
    assert json.loads((tmp / "s.json").read_text())[f"windy-pro@{SHA}"]["exit"] == 1
    monkeypatch.setattr(ar.subprocess, "run", lambda *a, **k: calls.append(a))
    assert ar.main() == 0 and calls == []              # once, ever



# --- unpicked cancels for labels no runner has (windy-pro build-electron *-latest legs)


def unpicked(db, run, runs_on, status=3):
    """A job cancelled before any runner took it: task 0, no task row."""
    db.n += 1
    db.c.execute("insert into action_run_job values (?,?,?,?,?,?)", (db.n, run, status, 0, NOW - 60, runs_on))
    return db.n


def judge_live(db, repo="windy-pro", repo_id=5):
    return ar.judge(repo, db.q(ar.commit_sql(repo_id, SHA)), ALLOW, ar.runner_labels(db.q))


def test_runner_labels_reads_live_runners_only():
    assert ar.runner_labels(DB().q) == [frozenset({"veron-1", "linux-x64", "self-hosted"})]


def test_runner_labels_unreadable_is_none():
    def boom(sql):
        raise OSError("db down")
    assert ar.runner_labels(boom) is None


def test_an_unrunnable_cancel_does_not_block_a_runner_lost_rerun():
    db = DB()
    r = db.run()
    j = db.job(r, 2, lost_steps(NOW - 60))
    unpicked(db, r, '["macos-latest"]')
    unpicked(db, r, '["windows-latest"]')
    assert judge_live(db) == ("runner-lost", str(j), "ok")


def test_without_runner_labels_every_cancel_still_blocks():
    db = DB()
    r = db.run()
    db.job(r, 2, lost_steps(NOW - 60))
    unpicked(db, r, '["macos-latest"]')
    assert judge(db) == (None, "", "a real red at the commit")          # labels not passed
    assert ar.judge("windy-pro", db.q(ar.commit_sql(5, SHA)), ALLOW, None)[0] is None


def test_an_unpicked_cancel_a_live_runner_could_take_still_blocks():
    # e.g. Gitea's concurrency cancel of a queued veron-1 job: fail closed.
    db = DB()
    r = db.run()
    db.job(r, 2, lost_steps(NOW - 60))
    unpicked(db, r, '["veron-1"]')
    assert judge_live(db) == (None, "", "a real red at the commit")


def test_a_picked_up_cancel_still_blocks_even_for_odd_labels():
    db = DB()
    r = db.run()
    db.job(r, 2, lost_steps(NOW - 60))
    db.job(r, 3, runs_on='["macos-latest"]')   # it had a task: a runner took it, then it was cancelled
    assert judge_live(db) == (None, "", "a real red at the commit")


def test_a_deleted_runners_labels_do_not_count():
    # macos-latest exists only on a DELETED runner in the fixture: still unrunnable.
    db = DB()
    r = db.run()
    j = db.job(r, 2)
    unpicked(db, r, '["macos-latest"]')
    assert judge_live(db) == ("dead-before-step", str(j), "ok")
