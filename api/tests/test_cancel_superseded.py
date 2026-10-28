"""scripts/cancel_superseded.py: waiting/blocked PR jobs on replaced commits are cancelled, nothing else
(Boss 10-28 08:44Z: never running, main, tag or schedule; logged; one BOARD line when > 0)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("cancel_superseded", ROOT / "scripts" / "cancel_superseded.py")
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)


def test_the_cancel_sql_carries_every_safety_line():
    sql = " ".join(cs.CANCEL_SQL.split())
    assert "j.status in (5, 7) and j.task_id = 0" in sql                 # waiting/blocked, unclaimed only
    assert sql.count("j.status in (5, 7) and j.task_id = 0") == 2        # re-checked inside the UPDATE
    assert re.findall(r"j\.status in \(([^)]*)\)", sql) == ["5, 7", "5, 7"]    # never 6 (running)
    assert "r.ref like 'refs/pull/%/head'" in sql                        # PR refs only: no main, no tag
    assert "r.event in ('pull_request', 'pull_request_sync')" in sql     # no push, schedule or dispatch
    assert "r.commit_sha <> n.commit_sha" in sql and "order by r.repo_id, r.ref, r.id desc" in sql
    assert "for update of j skip locked" in sql                          # never races a claiming runner
    assert "returning" in sql                                            # logs exactly what it cancelled


def test_cancels_are_logged_runs_closed_and_one_board_line_posted(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "LOG", tmp_path / "log")
    seen, posts = [], []

    def query(sql):
        seen.append(sql)
        if sql is cs.CANCEL_SQL:
            return [["11", "windy-pro", "refs/pull/824/head", "c53fb492", "gates", "501"],
                    ["12", "windy-pro", "refs/pull/824/head", "c53fb492", "lint", "501"],
                    ["13", "Windy-Clone", "refs/pull/30/head", "68d5b74a", "ci", "502"]]
        return []
    assert cs.main(query, posts.append) == 0
    assert any("r.id in (501,502)" in s for s in seen)                   # runs closed when all cancelled
    assert len(posts) == 1 and "3 waiting/blocked PR jobs" in posts[0] and "Windy-Clone 1, windy-pro 2" in posts[0]
    assert (tmp_path / "log").read_text().count("cancelled job") == 3


def test_nothing_to_cancel_posts_nothing_and_a_db_error_never_fails_the_sync(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "LOG", tmp_path / "log")
    posts = []
    assert cs.main(lambda sql: [], posts.append) == 0 and posts == [] and not (tmp_path / "log").exists()

    def boom(sql):
        raise OSError("db down")
    assert cs.main(boom, posts.append) == 0 and posts == []
