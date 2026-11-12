"""scripts/cancel_superseded.py, the MAIN pass (Boss YES 2026-11-12T02:56:14Z, five terms): a WAITING or BLOCKED
job on an OLDER default-branch commit is cancelled when a newer default-branch push run of the same repo exists.
(1) never a running job, never the newest main, never a tag, schedule or dispatch (release) build, and never a
re-run someone asked for by name (attempt > 1); (2) never a sha on the KEEP list; (3) the first pass is a DRY RUN
that posts the count per repo and cancels nothing; (4) a real pass logs every job id and posts one count line.
Off unless MAIN_SUPERSEDE says dry or on."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("cancel_superseded_m", ROOT / "scripts" / "cancel_superseded.py")
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)

SHA_A = "a" * 40
SHA_B = "b" * 40


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "LOG", tmp_path / "log")
    monkeypatch.setattr(cs, "KEEP_FILE", tmp_path / "keep-main.txt")
    monkeypatch.setattr(cs, "DRY_MARK", tmp_path / "dry.posted")
    return tmp_path


def _norm(sql: str) -> str:
    return " ".join(sql.split())


def test_the_main_sql_carries_every_safety_line():
    sql = _norm(cs.main_cancel_sql(set()))
    assert sql.count("j.status in (5, 7, 9) and j.task_id = 0") == 2       # waiting/blocked, unclaimed; re-checked
    assert re.findall(r"j\.status in \(([^)]*)\)", sql) == ["5, 7, 9", "5, 7, 9"]   # never 6 (running)
    assert "j.attempt <= 1" in sql                                          # a re-run asked by name is never cancelled
    assert sql.count("r.event = 'push'") == 2                               # no tag, schedule or dispatch run
    assert sql.count("r.ref = 'refs/heads/' || p.default_branch") == 2      # the default branch only
    assert "order by r.repo_id, r.id desc" in sql                           # newest main run per repo
    assert "r.commit_sha <> n.commit_sha" in sql                            # never the newest main commit
    assert "for update of j skip locked" in sql and "returning" in sql


def test_keep_shas_are_never_in_the_victims_and_the_dry_sql_changes_nothing():
    sql = _norm(cs.main_cancel_sql({SHA_A, SHA_B}))
    assert f"r.commit_sha <> all(array['{SHA_A}', '{SHA_B}']::text[])" in sql
    assert "<> all(array[]::text[])" in _norm(cs.main_cancel_sql(set()))   # an empty list keeps nothing extra
    dry = _norm(cs.main_dry_sql({SHA_A})).lower()
    assert "update" not in dry and "for update" not in dry and "returning" not in dry
    assert f"<> all(array['{SHA_A}']::text[])" in dry and "j.attempt <= 1" in dry


def test_keep_file_lines_need_a_full_sha_a_lane_and_a_board_time(paths):
    (paths / "keep-main.txt").write_text(
        f"{SHA_A} Windy Traveler 2026-11-12T00:03:30Z\n"
        "# a comment\n\n"
        f"{SHA_B[:12]} Windy Calendar 2026-11-12T02:07:39Z\n"          # short sha: refused
        f"{SHA_B} 2026-11-12T02:07:39Z\n"                             # no lane: refused
        f"{SHA_B.upper()} Windy Calendar 2026-11-12T02:07:39Z\n")     # upper-case hex: refused
    shas, bad = cs.keep_shas()
    assert shas == {SHA_A} and bad == 3


def test_a_missing_keep_file_is_an_empty_list_and_an_unreadable_one_skips_the_main_pass(paths, monkeypatch):
    assert cs.keep_shas() == (set(), 0)
    (paths / "keep-main.txt").mkdir()                                      # exists but cannot be read as a file
    seen, posts = [], []
    monkeypatch.setenv("MAIN_SUPERSEDE", "on")
    assert cs.main(lambda sql: seen.append(sql) or [], posts.append) == 0
    assert not any("refs/heads/" in s for s in seen) and posts == []       # fail safe: the main pass cancels nothing


def test_off_by_default_the_main_pass_never_runs(paths, monkeypatch):
    monkeypatch.delenv("MAIN_SUPERSEDE", raising=False)
    seen = []
    assert cs.main(lambda sql: seen.append(sql) or [], lambda line: None) == 0
    assert seen == [cs.CANCEL_SQL]                                         # the PR pass only, as before


ROWS = [["21", "windy-pro", "refs/heads/main", "1111aaaa", "test", "701"],
        ["22", "windy-pro", "refs/heads/main", "1111aaaa", "lint", "701"],
        ["23", "windy-text", "refs/heads/main", "2222bbbb", "ci", "702"]]


def test_the_dry_run_posts_the_count_per_repo_once_and_cancels_nothing(paths, monkeypatch):
    monkeypatch.setenv("MAIN_SUPERSEDE", "dry")
    seen, posts = [], []

    def query(sql):
        seen.append(sql)
        return ROWS if "refs/heads/" in sql else []
    assert cs.main(query, posts.append) == 0
    main_sqls = [s for s in seen if "refs/heads/" in s]
    assert main_sqls and all("update" not in s.lower() for s in main_sqls)
    assert len(posts) == 1 and "DRY RUN" in posts[0] and "3 waiting/blocked jobs" in posts[0]
    assert "windy-pro 2, windy-text 1" in posts[0] and "cancelled nothing" in posts[0]
    assert not (paths / "log").exists()
    assert cs.main(query, posts.append) == 0 and len(posts) == 1           # later dry passes stay quiet


def test_a_real_pass_cancels_logs_every_job_closes_runs_and_posts_one_line(paths, monkeypatch):
    monkeypatch.setenv("MAIN_SUPERSEDE", "on")
    (paths / "keep-main.txt").write_text(f"{SHA_A} Windy Traveler 2026-11-12T00:03:30Z\n")
    seen, posts = [], []

    def query(sql):
        seen.append(sql)
        return ROWS if ("refs/heads/" in sql and "returning" in sql) else []
    assert cs.main(query, posts.append) == 0
    cancel = [s for s in seen if "refs/heads/" in s and "returning" in s]
    assert len(cancel) == 1 and SHA_A in cancel[0]                         # the keep list reached the SQL
    assert any("r.id in (701,702)" in s for s in seen)
    assert len(posts) == 1 and "older main commits" in posts[0] and "3 waiting/blocked jobs" in posts[0]
    log = (paths / "log").read_text()
    assert all(f"cancelled job {i} " in log for i in ("21", "22", "23")) and log.count("(main)") == 3


def test_an_unknown_mode_runs_nothing(paths, monkeypatch):
    monkeypatch.setenv("MAIN_SUPERSEDE", "yes please")
    seen = []
    assert cs.main(lambda sql: seen.append(sql) or [], lambda line: None) == 0
    assert seen == [cs.CANCEL_SQL]
