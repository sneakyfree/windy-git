"""autorerun: only jobs that died before any step ran, once per commit, never a real red."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("autorerun_dead_jobs", ROOT / "scripts" / "autorerun_dead_jobs.py")
ar = importlib.util.module_from_spec(_spec)
sys.modules["autorerun_dead_jobs"] = ar
_spec.loader.exec_module(ar)

SHA = "a" * 40


def test_selection_sql_requires_no_step_run_and_no_newer_run():
    sql = ar.CANDIDATES
    assert "j.status = 2" in sql and "j.task_id > 0" in sql
    assert "s.status in (1, 2)" in sql           # any step that ran or failed disqualifies the job
    assert "r2.index > r.index" in sql           # someone already re-ran this commit


def test_branch_for_push_and_pull_refs():
    assert ar.branch_for("5", "refs/heads/main") == "main"

    def q(sql):
        return [["word/stt"]] if "head_branch" in sql and "i.index = 247" in sql else []

    assert ar.branch_for("5", "refs/pull/247/head", q) == "word/stt"
    assert ar.branch_for("5", "refs/pull/9/head", q) is None
    assert ar.branch_for("5", "refs/tags/v1") is None
    assert ar.branch_for("x; drop", "refs/pull/1/head") is None   # ids are digits-only before SQL


def test_one_automatic_retry_per_commit_ever():
    rows = [["5", "windy-pro", SHA, "refs/heads/main", "10"]]
    assert [t["key"] for t in ar.pick(rows, {}, 0)] == [f"windy-pro@{SHA}"]
    assert ar.pick(rows, {f"windy-pro@{SHA}": {"at": 1}}, 0) == []


def test_cap_per_pass_and_dedupe():
    rows = [["5", "r", f"{i:040d}", "refs/heads/m", str(i)] for i in range(6)]
    rows.append(["5", "r", f"{0:040d}", "refs/heads/m", "99"])  # same commit again: deduped
    assert len(ar.pick(rows, {}, 0)) == ar.MAX_PER_PASS


def test_unresolvable_branch_is_skipped_not_fatal():
    rows = [["5", "r", SHA, "refs/pull/3/head", "1"]]
    assert ar.pick(rows, {}, 0, query=lambda s: []) == []


def test_state_is_pruned_and_survives_garbage(tmp_path, monkeypatch):
    p = tmp_path / "s.json"
    monkeypatch.setattr(ar, "STATE", p)
    assert ar.load_state() == {}
    p.write_text("not json")
    assert ar.load_state() == {}
    ar.save_state({"old@x": {"at": 1}, "new@y": {"at": 4_000_000_000}})
    assert list(ar.load_state()) == ["new@y"]
