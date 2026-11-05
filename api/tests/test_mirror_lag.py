"""scripts/mirror_lag.py: the judgement is pure; main() is driven with fake API answers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("mirror_lag", ROOT / "scripts" / "mirror_lag.py")
ml = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ml)

@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    """Never the real /var/lib/windygit state, never a real BOARD."""
    monkeypatch.setattr(ml, "STATE", tmp_path / "mirror-lag.json")
    monkeypatch.setattr(ml.cs, "board", lambda line: pytest.fail("a test posted to the real BOARD: " + line))


NOW = 1_800_000_000.0
SRC = "https://github.com/sneakyfree/site.git"
A, B = "a" * 40, "b" * 40


def mirror(head=A, updated=NOW - 300, interval=600, source=SRC):
    return {"name": "windyadmin/site", "source": source, "updated": updated, "interval": interval, "head": head}


def gh(head=A, pushed=NOW - 7200):
    return {SRC: {"head": head, "pushed": pushed}}


def test_in_step_is_quiet():
    assert ml.judge([mirror()], gh(), NOW) == []


def test_both_empty_is_in_step():
    assert ml.judge([mirror(head=None)], gh(head=None), NOW) == []


def test_refresh_older_than_an_hour_is_stale():
    out = ml.judge([mirror(updated=NOW - 3601)], gh(), NOW)
    assert out == ["STALE windyadmin/site: last refresh 60 min ago"]


def test_never_refreshed_is_stale():
    assert ml.judge([mirror(updated=None)], gh(), NOW) == ["STALE windyadmin/site: last refresh never"]


def test_a_daily_mirror_is_judged_by_its_own_interval():
    daily = 86400
    assert ml.judge([mirror(updated=NOW - 25 * 3600, interval=daily)], gh(), NOW) == []
    assert ml.judge([mirror(updated=NOW - 49 * 3600, interval=daily)], gh(), NOW)[0].startswith("STALE")
    # GitHub moved a day ago, after the last daily refresh: not behind yet.
    assert ml.judge([mirror(head=A, updated=NOW - 23 * 3600, interval=daily)], gh(head=B, pushed=NOW - 20 * 3600), NOW) == []


def test_different_head_after_the_grace_window_is_behind():
    out = ml.judge([mirror(head=A)], gh(head=B, pushed=NOW - 1801), NOW)
    assert out == [f"BEHIND windyadmin/site: Windy Git {A[:8]}, GitHub {B[:8]}"]


def test_a_fresh_github_push_is_not_behind_yet():
    assert ml.judge([mirror(head=A)], gh(head=B, pushed=NOW - 600), NOW) == []


def test_github_unreadable_counts_as_a_problem():
    assert ml.judge([mirror()], {SRC: None}, NOW) == [
        f"UNREADABLE windyadmin/site: GitHub source {SRC} not readable"
    ]
    assert ml.judge([mirror(source="")], {"": None}, NOW)[0].startswith("UNREADABLE")


def test_interval_parses_go_durations():
    assert ml.interval_s("10m0s") == 600
    assert ml.interval_s("24h0m0s") == 86400
    assert ml.interval_s("1h30m0s") == 5400
    assert ml.interval_s("") == 600
    assert ml.interval_s(None) == 600


def test_main_prints_the_summary_and_exits_1_when_any_mirror_lags(monkeypatch, capsys):
    monkeypatch.setattr(ml, "gitea_mirrors", lambda: [mirror(head=A), {**mirror(), "name": "windyadmin/other"}])
    monkeypatch.setattr(ml, "github_heads", lambda sources: gh(head=B, pushed=NOW - 7200))
    monkeypatch.setattr(ml.dt, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: _Fixed())}))
    assert ml.main() == 1
    out = capsys.readouterr().out
    assert out.strip().splitlines()[-1] == "mirror lag: 2 mirrors checked, 2 behind"


def test_main_reports_an_api_error_as_a_failure(monkeypatch, capsys):
    def boom():
        raise OSError("down")
    monkeypatch.setattr(ml, "gitea_mirrors", boom)
    assert ml.main() == 1
    assert capsys.readouterr().out.strip() == "mirror lag: ERROR (OSError)"


class _Fixed:
    def timestamp(self):
        return NOW

    def date(self):
        # NOW = 2027-01-15T08:00:00Z. Not via datetime.datetime: the tests patch that very class.
        import datetime
        return datetime.date(2027, 1, 15)


def test_zero_mirrors_is_a_failure_not_all_clear(monkeypatch, capsys):
    monkeypatch.setattr(ml, "gitea_mirrors", lambda: [])
    monkeypatch.setattr(ml, "github_heads", lambda sources: {})
    assert ml.main() == 1
    assert capsys.readouterr().out.strip() == "mirror lag: ERROR (no mirrors found)"


def test_paging_continues_until_an_empty_page(monkeypatch):
    # A page smaller than 50 must not end the walk: Gitea's page cap may be lower.
    pages = {
        1: [{"full_name": "windyadmin/a", "default_branch": "main", "empty": True}] * 2,
        2: [{"full_name": "windyadmin/b", "default_branch": "main", "empty": True}],
        3: [],
    }

    def fake(path):
        if path.startswith("/repos/search"):
            return {"data": pages[int(path.rsplit("page=", 1)[1])]}
        raise AssertionError(path)

    monkeypatch.setattr(ml, "gitea", fake)
    assert [m["name"] for m in ml.gitea_mirrors()] == ["windyadmin/a", "windyadmin/a", "windyadmin/b"]


def test_heartbeat_expects_at_least_one_mirror():
    import re
    conf = (ROOT / "deploy/systemd/windygit-mirror-lag.service.d/windy-job.conf").read_text()
    pattern = re.search(r'--expect "([^"]+)"', conf).group(1)
    assert re.search(pattern, "mirror lag: 116 mirrors checked, 0 behind")
    assert not re.search(pattern, "mirror lag: 0 mirrors checked, 0 behind")
    assert not re.search(pattern, "mirror lag: 116 mirrors checked, 1 behind")


def test_paging_has_a_cap_and_fails_loud_past_it(monkeypatch, capsys):
    calls = []

    def endless(path):
        calls.append(path)
        return {"data": [{"full_name": "windyadmin/x", "default_branch": "main", "empty": True}]}

    monkeypatch.setattr(ml, "gitea", endless)
    monkeypatch.setattr(ml, "MAX_PAGES", 3)
    assert ml.main() == 1
    assert capsys.readouterr().out.strip() == "mirror lag: ERROR (ValueError)"
    assert len(calls) == 3


# ---- KNOWN-STALE (Boss 10-27): private mirrors (no credential) are marked, never read as current ----

def test_a_private_mirror_lagging_is_marked_not_counted():
    import datetime
    real, known = ml.split_known(["BEHIND windyadmin/site: Windy Git aaaaaaaa, GitHub bbbbbbbb"],
                                 {"windyadmin/site"}, datetime.date(2026, 11, 1))
    assert real == []
    assert known[0].startswith("KNOWN-STALE BEHIND windyadmin/site: Windy Git aaaaaaaa, GitHub bbbbbbbb (private pull mirror")
    assert known[0].endswith("excused until 2026-11-26)")


def test_a_public_mirror_lagging_still_counts():
    import datetime
    line = "BEHIND windyadmin/site: Windy Git aaaaaaaa, GitHub bbbbbbbb"
    assert ml.split_known([line], set(), datetime.date(2026, 11, 1)) == ([line], [])


def test_private_mirrors_count_again_after_the_end_date():
    import datetime
    line = "STALE windyadmin/site: last refresh 61 min ago"
    assert ml.split_known([line], {"windyadmin/site"}, datetime.date(2026, 11, 27)) == ([line], [])


def test_main_exits_0_when_only_private_mirrors_lag(monkeypatch, capsys):
    import datetime
    import re
    monkeypatch.setattr(ml, "PRIVATE_NO_KEY_UNTIL", datetime.date(2027, 1, 31))
    monkeypatch.setattr(ml, "gitea_mirrors", lambda: [mirror(head=A)])
    monkeypatch.setattr(ml, "github_heads", lambda sources: {SRC: {"head": B, "pushed": NOW - 7200, "private": True}})
    monkeypatch.setattr(ml.dt, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: _Fixed())}))
    assert ml.main() == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0].strip().startswith("KNOWN-STALE BEHIND windyadmin/site:")
    assert lines[-1] == "mirror lag: 1 mirrors checked, 0 behind, 1 known-stale"
    conf = (ROOT / "deploy/systemd/windygit-mirror-lag.service.d/windy-job.conf").read_text()
    assert re.search(re.search(r'--expect "([^"]+)"', conf).group(1), lines[-1])


def test_the_amnesty_has_a_near_end_date():
    import datetime
    latest_allowed = datetime.date(2026, 10, 27) + datetime.timedelta(days=31)
    assert latest_allowed >= ml.PRIVATE_NO_KEY_UNTIL


def test_main_counts_a_lagging_public_mirror(monkeypatch, capsys):
    # The mirror image (Hub, #73): a PUBLIC source that lags is a real problem, never excused.
    import datetime
    monkeypatch.setattr(ml, "PRIVATE_NO_KEY_UNTIL", datetime.date(2027, 1, 31))
    monkeypatch.setattr(ml, "gitea_mirrors", lambda: [mirror(head=A)])
    monkeypatch.setattr(ml, "github_heads", lambda sources: {SRC: {"head": B, "pushed": NOW - 7200, "private": False}})
    monkeypatch.setattr(ml.dt, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: _Fixed())}))
    assert ml.main() != 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0].strip() == f"BEHIND windyadmin/site: Windy Git {A[:8]}, GitHub {B[:8]}"
    assert "KNOWN-STALE" not in "\n".join(lines)
    assert lines[-1] == "mirror lag: 1 mirrors checked, 1 behind"


def test_github_heads_reads_private_from_isPrivate_only(monkeypatch):
    # Pins the parse itself: main()'s tests stub github_heads out, so only this catches
    # "private" being set without GitHub saying so (that would excuse every mirror).
    pub = "https://github.com/sneakyfree/pub.git"
    priv = "https://github.com/sneakyfree/priv.git"
    answer = {"data": {
        "a0": {"pushedAt": None, "isPrivate": False, "defaultBranchRef": {"target": {"oid": A}}},
        "a1": {"pushedAt": None, "isPrivate": True, "defaultBranchRef": {"target": {"oid": B}}},
    }}
    monkeypatch.setattr(ml, "github_graphql", lambda q: answer)
    out = ml.github_heads([pub, priv])
    assert out[pub]["private"] is False
    assert out[priv]["private"] is True


# ------------------------------------------------------------------ the 24-hour alarm
DAY = 24 * 3600
TODAY = "2027-01-15"


def stale(name, ago):
    return {"name": name, "source": SRC, "updated": NOW - ago, "interval": 600, "head": A}


def problems_of(mirrors, **kw):
    return ml.judge(mirrors, {m["source"]: {"head": A, "pushed": NOW - 7200, **kw} for m in mirrors}, NOW)


def test_a_stale_mirror_counts_from_its_last_refresh_not_from_first_sight():
    ms = [stale("o/a", 3 * DAY + 5 * 3600)]
    since, aged = ml.track(problems_of(ms), ms, {}, NOW)
    assert aged == [("o/a", 3 * DAY + 5 * 3600)] and since["o/a"] == NOW - (3 * DAY + 5 * 3600)


def test_under_24_hours_is_quiet_and_exactly_24_hours_alarms():
    ms = [stale("o/a", DAY - 1)]
    assert ml.track(problems_of(ms), ms, {}, NOW)[1] == []
    ms = [stale("o/a", DAY)]
    assert ml.track(problems_of(ms), ms, {}, NOW)[1] == [("o/a", DAY)]


def test_a_behind_mirror_counts_from_first_sight_and_a_recovered_one_is_forgotten():
    m = mirror(head=A)
    m["name"] = "o/b"
    p = ml.judge([m], {SRC: {"head": B, "pushed": NOW - 7200}}, NOW)           # BEHIND, refresh is fresh
    since, aged = ml.track(p, [m], {}, NOW)
    assert aged == [] and since == {"o/b": NOW}                                  # first sight: the clock starts
    since, aged = ml.track(p, [m], since, NOW + DAY + 60)
    assert aged == [("o/b", DAY + 60)]
    since, aged = ml.track([], [m], since, NOW + DAY + 120)                      # back in step
    assert since == {} and aged == []
    since, aged = ml.track(p, [m], since, NOW + DAY + 180)                       # lags again: a NEW clock
    assert aged == [] and since == {"o/b": NOW + DAY + 180}


def test_the_known_stale_private_ones_are_in_the_alarm_though_the_hourly_check_excuses_them():
    ms = [stale("o/priv", 5 * DAY)]
    every = problems_of(ms, private=True)
    real, known = ml.split_known(every, {"o/priv"}, __import__("datetime").date(2026, 11, 5))
    assert real == [] and len(known) == 1                                        # hourly: green
    assert ml.track(every, ms, {}, NOW)[1] == [("o/priv", 5 * DAY)]              # alarm: named


def test_oldest_first_and_the_line_is_capped_at_ten_names():
    ms = [stale(f"o/m{i}", (2 + i) * DAY) for i in range(13)]
    _, aged = ml.track(problems_of(ms), ms, {}, NOW)
    assert [a[0] for a in aged][:2] == ["o/m12", "o/m11"]
    line = ml.alarm_line(aged, {"o/m12"})
    assert "13 pull mirror(s)" in line and "+3 more" in line
    assert "o/m12 (14d 0h, private, KNOWN-STALE)" in line and "o/m3 (5d 0h)" in line     # the ten oldest: m12 .. m3
    assert "o/m2 " not in line and "o/m0 " not in line and "\n" not in line


def run_main(monkeypatch, ms, board, **gh_kw):
    monkeypatch.setattr(ml, "gitea_mirrors", lambda: ms)
    monkeypatch.setattr(ml, "github_heads", lambda sources: {SRC: {"head": A, "pushed": NOW - 7200, **gh_kw}})
    monkeypatch.setattr(ml.dt, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: _Fixed())}))
    monkeypatch.setattr(ml.cs, "board", board)
    return ml.main()


def test_one_line_a_day_not_one_an_hour(monkeypatch, capsys):
    posts = []
    ms = [stale("o/a", 3 * DAY)]
    run_main(monkeypatch, ms, lambda line: posts.append(line) or True)
    run_main(monkeypatch, ms, lambda line: posts.append(line) or True)           # the next hourly run, same day
    assert len(posts) == 1 and "o/a (3d 0h)" in posts[0] and posts[0].startswith("[Windy Git] MIRROR LAG 24h+")
    monkeypatch.setattr(_Fixed, "date", lambda self: __import__("datetime").date(2027, 1, 16))
    run_main(monkeypatch, ms, lambda line: posts.append(line) or True)           # the next UTC day: said again
    assert len(posts) == 2


def test_nothing_is_posted_while_nothing_is_a_day_old(monkeypatch):
    posts = []
    run_main(monkeypatch, [stale("o/a", 2 * 3600)], lambda line: posts.append(line) or True)
    assert posts == []


def test_a_line_that_could_not_be_written_is_retried_the_next_run(monkeypatch, capsys):
    posts = []
    ms = [stale("o/a", 3 * DAY)]
    run_main(monkeypatch, ms, lambda line: False)
    assert "BOARD line not written anywhere" in capsys.readouterr().out
    run_main(monkeypatch, ms, lambda line: posts.append(line) or True)
    assert len(posts) == 1


def test_state_that_cannot_be_saved_fails_the_run_and_posts_nothing(monkeypatch, tmp_path, capsys):
    posts = []
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setattr(ml, "STATE", blocker / "sub" / "state.json")            # parent is a FILE: cannot be created
    rc = run_main(monkeypatch, [stale("o/a", 3 * DAY)], lambda line: posts.append(line) or True)
    assert rc == 1 and posts == [] and "state not saved" in capsys.readouterr().out


def test_dry_run_says_what_it_would_post_and_writes_nothing(monkeypatch, capsys):
    monkeypatch.setattr(ml, "gitea_mirrors", lambda: [stale("o/a", 3 * DAY)])
    monkeypatch.setattr(ml, "github_heads", lambda sources: {SRC: {"head": A, "pushed": NOW - 7200}})
    monkeypatch.setattr(ml.dt, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: _Fixed())}))
    monkeypatch.setattr(ml.cs, "board", lambda line: pytest.fail("posted in a dry run"))
    ml.main(dry=True)
    assert "would post: [Windy Git] MIRROR LAG 24h+" in capsys.readouterr().out and not ml.STATE.exists()


def test_the_summary_line_the_heartbeat_reads_is_unchanged(monkeypatch, capsys):
    import re
    run_main(monkeypatch, [stale("o/a", 3 * DAY)], lambda line: True)
    last = capsys.readouterr().out.strip().splitlines()[-1]
    conf = (ROOT / "deploy/systemd/windygit-mirror-lag.service.d/windy-job.conf").read_text()
    assert last.startswith("mirror lag: 1 mirrors checked, 1 behind")
    assert re.search(r'--expect "([^"]+)"', conf)


def test_an_unsaved_state_alone_turns_an_otherwise_green_run_red(monkeypatch, tmp_path, capsys):
    import datetime
    monkeypatch.setattr(ml, "PRIVATE_NO_KEY_UNTIL", datetime.date(2027, 1, 31))
    blocker = tmp_path / "file"
    blocker.write_text("x")
    ok = run_main(monkeypatch, [stale("o/priv", 3 * DAY)], lambda line: True, private=True)
    assert ok == 0                                                              # only a KNOWN-STALE private mirror: green
    monkeypatch.setattr(ml, "STATE", blocker / "sub" / "state.json")
    bad = run_main(monkeypatch, [stale("o/priv", 3 * DAY)], lambda line: True, private=True)
    assert bad == 1 and "state not saved" in capsys.readouterr().out
