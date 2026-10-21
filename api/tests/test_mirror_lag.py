"""scripts/mirror_lag.py: the judgement is pure; main() is driven with fake API answers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("mirror_lag", ROOT / "scripts" / "mirror_lag.py")
ml = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ml)

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
