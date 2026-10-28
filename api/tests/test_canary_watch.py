"""scripts/canary_watch.py: 20 min with no canary RUN is a WARN (Boss 10-28 (D))."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("canary_watch", ROOT / "scripts" / "canary_watch.py")
cw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cw)


def test_ok_within_twenty_minutes_warn_after():
    assert cw.verdict(1000, 0, 1000 + 19 * 60).startswith("canary: ok")
    v = cw.verdict(1000, 9, 1000 + 104 * 60)
    assert v == "canary: WARN silent 104 min, 9 schedules in a row missed (WARN to Boss and Admin)"
    assert cw.verdict(0, 0, 5000).startswith("canary: WARN it has never run")


def test_the_query_counts_only_runs_that_ran_and_reads_schedules_by_trigger_event():
    sql = " ".join(cw.SQL.split())
    assert "j.status in (1, 2)" in sql                       # success or failure = it RAN; cancelled is not
    assert "r.trigger_event = 'schedule'" in sql             # Gitea stores schedules as event push
    assert "r.workflow_id = 'canary.yml'" in sql


def test_an_unreadable_db_is_a_warn_not_a_silent_ok(capsys):
    def boom(sql):
        raise OSError("db")
    cw.main(boom)
    assert capsys.readouterr().out.startswith("canary: WARN cannot read")
