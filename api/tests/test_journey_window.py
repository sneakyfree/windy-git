"""deploy/journey-window: Veron's general runners take no new jobs in the sign-up journey window (Boss 11-04), and only one
is active outside it (Boss 11-05 throttle). A fake runner table stands in for Postgres; nothing real is touched."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import re
import types
from pathlib import Path

import pytest

DIR = Path(__file__).resolve().parents[2] / "deploy" / "journey-window"
ORIG = '["veron-1","linux-x64","self-hosted","linux","x64"]'
OTHER = '["veron-1","self-hosted","linux","x64","linux-x64"]'


def load():
    loader = importlib.machinery.SourceFileLoader("jw", str(DIR / "windygit-journey-window"))
    spec = importlib.util.spec_from_loader("jw", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


@pytest.fixture
def jw(tmp_path):
    m = load()
    m.STATE, m.OFF, m.HOURS_FILE = str(tmp_path / "s.json"), str(tmp_path / "off"), str(tmp_path / "hours")
    return m


class Db:
    """Three general runners, ids 2/4/5, and the two statements the script sends."""

    def __init__(self, jw):
        self.jw, self.rows = jw, {"2": ORIG, "4": ORIG, "5": ORIG}

    def __call__(self, sql):
        if sql.startswith("select"):
            return [[k, "r" + k, v] for k, v in sorted(self.rows.items(), key=lambda kv: int(kv[0]))]
        labels = re.search(r"agent_labels = '(.*?)'", sql).group(1)
        rid = re.search(r"id = (\d+)", sql).group(1)
        if "and agent_labels" in sql and self.rows[rid] != self.jw.PAUSED:   # restore only what we paused
            return []
        self.rows[rid] = labels
        return []


def at(h, m):
    return lambda: types.SimpleNamespace(tm_min=m, tm_hour=h)


def run(jw, db, h, m, argv=("x",)):
    return jw.main(list(argv), at(h, m), db)


def test_the_window_is_17_to_40_and_to_50_in_the_j3_hours(jw):
    assert jw.in_window(17, 3) and jw.in_window(39, 3)
    assert not jw.in_window(16, 3) and not jw.in_window(40, 3) and not jw.in_window(0, 3)
    for h in (15, 19, 23):
        assert jw.in_window(49, h) and not jw.in_window(50, h)
    assert not jw.in_window(45, 4)


def test_extra_hours_come_from_the_file_and_junk_in_it_is_ignored(jw):
    Path(jw.HOURS_FILE).write_text("4\n9\nx\n99\n-1\n")
    assert jw.in_window(45, 4) and jw.in_window(45, 9) and not jw.in_window(45, 5)


def test_inside_the_window_all_three_are_held(jw):
    db = Db(jw)
    run(jw, db, 3, 20)
    assert set(db.rows.values()) == {jw.PAUSED}


def test_outside_the_window_exactly_one_runner_stays_active(jw):
    db = Db(jw)
    run(jw, db, 3, 5)
    assert db.rows == {"2": ORIG, "4": jw.PAUSED, "5": jw.PAUSED}              # the lowest id keeps working


def test_the_window_ending_gives_the_keeper_back_and_holds_the_rest(jw):
    db = Db(jw)
    run(jw, db, 3, 20)
    run(jw, db, 3, 41)
    assert db.rows == {"2": ORIG, "4": jw.PAUSED, "5": jw.PAUSED} and set(jw.load()) == {"4", "5"}
    run(jw, db, 3, 41)
    assert set(jw.load()) == {"4", "5"}                                          # idempotent


def test_the_real_labels_are_saved_and_a_restarted_runner_keeps_its_new_ones(jw):
    db = Db(jw)
    run(jw, db, 3, 20)
    assert jw.load() == {"2": ORIG, "4": ORIG, "5": ORIG}
    db.rows["4"] = OTHER                                                         # runner restarted, re-declared labels
    run(jw, db, 3, 21)
    assert db.rows["4"] == jw.PAUSED and jw.load()["4"] == OTHER                # paused again, new list remembered
    run(jw, db, 3, 55, ("x", "restore"))
    assert db.rows == {"2": ORIG, "4": OTHER, "5": ORIG}


def test_the_off_file_and_restore_put_everything_back(jw):
    db = Db(jw)
    run(jw, db, 3, 20)
    Path(jw.OFF).write_text("")
    run(jw, db, 3, 20)                                                           # in the window, but OFF wins
    assert db.rows == {"2": ORIG, "4": ORIG, "5": ORIG} and jw.load() == {}
    Path(jw.OFF).unlink()
    run(jw, db, 3, 5)
    run(jw, db, 3, 5, ("x", "restore"))
    assert set(db.rows.values()) == {ORIG}


def test_a_label_value_with_a_quote_cannot_break_the_sql(jw):
    seen = []
    evil = '["a\' or 1=1 --"]'
    jw.save({"2": evil})
    jw.restore(lambda sql: seen.append(sql) or [])
    assert "or 1=1" in seen[0] and "'a' or" not in seen[0] and "a' or" not in seen[0]     # the quote is stripped


def test_only_the_three_general_runners_are_ever_selected(jw):
    seen = []
    jw.general_runners(lambda sql: seen.append(sql) or [])
    q = seen[0]
    assert "repo_id = 0" in q and "'veron-1','veron-1-2','veron-1-3'" in q and "last_online >" in q
    assert "null0" not in q and "w0-" not in q and "canary" not in q and "userns" not in q


def test_the_unit_files_run_it_every_minute_as_root_oneshot():
    svc = (DIR / "windygit-journey-window.service").read_text()
    tim = (DIR / "windygit-journey-window.timer").read_text()
    assert "Type=oneshot" in svc and "ExecStart=/usr/local/sbin/windygit-journey-window" in svc and "User=" not in svc
    assert "OnCalendar=*:*:00" in tim and "WantedBy=timers.target" in tim


def test_restore_never_overwrites_labels_a_runner_declared_itself(jw):
    db = Db(jw)
    run(jw, db, 3, 20)                                                           # all held, ORIG saved
    db.rows["4"] = OTHER                                                         # runner 4 restarts: its own new labels
    run(jw, db, 3, 30, ("x", "restore"))                                         # restore BEFORE the next pause pass
    assert db.rows["4"] == OTHER and db.rows["2"] == ORIG and db.rows["5"] == ORIG


def test_the_keeper_restore_also_strips_quotes_and_only_touches_what_was_paused(jw):
    seen = []
    jw.save({"2": '["a\' or 1=1 --"]'})
    rows = [["2", "veron-1", jw.PAUSED], ["4", "veron-1-2", ORIG], ["5", "veron-1-3", ORIG]]

    def q(sql):
        seen.append(sql)
        return rows if sql.startswith("select") else []
    jw.pause(q, hold=1)
    restore_sql = [s for s in seen if s.startswith("update") and "id = 2" in s][0]
    assert "a' or" not in restore_sql and f"and agent_labels = '{jw.PAUSED}'" in restore_sql
