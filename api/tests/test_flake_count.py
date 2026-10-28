"""scripts/flake_count.py: logged flake retries counted per 7 days; over the limit -> a LOW to Boss
(Boss rule 10-28 for FLAKE-1: one retry, logged by name, counted, never silent)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("flake_count", ROOT / "scripts" / "flake_count.py")
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

NOW = 2_000_000_000
LOGS = {
    101: "2026-10-28T04:00:00.0000000Z [WINDY-FLAKE-RETRY] FLAKE-1 chromium-launch\nok\n",
    102: "    [WINDY-FLAKE-RETRY] FLAKE-1 chromium-launch\n",                 # indented (jest stderr)
    103: "PASS tests/x\nsome text mentioning [WINDY-FLAKE-RETRY] FLAKE-9 in prose\n",  # not at line start
    104: "2026-10-28T04:00:00Z [WINDY-FLAKE-RETRY] FLAKE-1 chromium-launch\n"
         "2026-10-28T04:00:01Z [WINDY-FLAKE-RETRY] FLAKE-2 other\n",
}


def _query(jobs, attempt=1, stopped=NOW - 3600):
    return lambda sql: [[str(j), str(attempt), str(stopped)] for j in jobs]


def test_counts_each_logged_retry_and_flags_over_the_limit(tmp_path):
    fetched = []
    lines, ok = fc.run(NOW, _query([101, 102, 103, 104]), lambda r, j: fetched.append(j) or LOGS[j], tmp_path / "s.json")
    assert ok and lines[0].startswith("flake count: 4 retries in 7 days across 4 job attempts (FLAKE-1: 3, FLAKE-2: 1)"), lines
    assert lines[1] == "over limit: FLAKE-1 x3 (more than 2 in 7 days: LOW to Boss)", lines
    assert sorted(fetched) == [101, 102, 103, 104]


def test_at_the_limit_is_still_healthy_and_logs_are_read_once(tmp_path):
    st = tmp_path / "s.json"
    lines, _ = fc.run(NOW, _query([101, 102]), lambda r, j: LOGS[j], st)
    assert lines[1] == "over limit: none", lines            # 2 is the limit, not over it
    again = []
    lines, ok = fc.run(NOW, _query([101, 102]), lambda r, j: again.append(j) or LOGS[j], st)
    assert ok and again == [] and "FLAKE-1: 2" in lines[0]  # cached: finished logs never change


def test_entries_leave_the_cache_by_age_and_an_unreadable_log_fails_the_run(tmp_path):
    st = tmp_path / "s.json"
    fc.run(NOW, _query([101], stopped=NOW - 6 * 86400), lambda r, j: LOGS[j], st)
    fc.run(NOW, _query([104]), lambda r, j: LOGS[j], st)
    lines, _ = fc.run(NOW + 2 * 86400, _query([]), lambda r, j: LOGS[j], st)   # 101 now 8 days old
    assert "FLAKE-1: 1, FLAKE-2: 1" in lines[0] and '"101:1"' not in st.read_text(), (lines, st.read_text())

    def boom(r, j):
        raise OSError("down")
    lines, ok = fc.run(NOW, _query([999]), boom, st)
    assert not ok and lines[1] == "over limit: none"


def test_the_query_only_takes_finished_watched_jobs_inside_the_window():
    seen = []
    fc.finished_jobs(NOW, lambda sql: seen.append(sql) or [])
    sql = " ".join(seen)
    assert "j.attempt" in sql and "j.status in (1, 2)" in sql and f"j.stopped > {NOW - 7 * 86400}" in sql
    assert "p.lower_name = 'windy-pro'" in sql and "j.name = 'gates'" in sql


def test_a_re_run_attempt_is_counted_too_and_a_job_mid_re_run_keeps_its_first_attempt(tmp_path):
    """Hub #88: a Gitea re-run reuses the job id and bumps attempt; its log replaces the old one."""
    st = tmp_path / "s.json"
    one = "[WINDY-FLAKE-RETRY] FLAKE-1 chromium-launch\n"
    lines, _ = fc.run(NOW, _query([101], attempt=1), lambda r, j: one, st)
    assert "flake count: 1 " in lines[0], lines
    lines, _ = fc.run(NOW, _query([], attempt=2), lambda r, j: one, st)       # 101 waiting on its re-run
    assert "flake count: 1 " in lines[0], lines                                 # attempt 1 kept
    lines, _ = fc.run(NOW, _query([101], attempt=2), lambda r, j: one, st)      # re-run finished
    assert "flake count: 2 " in lines[0] and "FLAKE-1: 2" in lines[0], lines
