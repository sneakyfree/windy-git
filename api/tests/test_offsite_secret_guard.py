"""scripts/offsite_secret_guard.py (Hub #121): Null 0's runners stay repo-scoped and secret-free
after registration; any violation cuts them off at once (ssh stop, else soft-delete in Gitea)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("offsite_secret_guard", ROOT / "scripts" / "offsite_secret_guard.py")
g = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g)

OK1 = ["21", "null0-1", "1", "40", "eternitas", "0"]
OK2 = ["22", "null0-2", "1", "41", "windy-chat", "0"]


class Run:
    """Fake subprocess.run for the ssh calls: maps a substring of the remote command to (rc, stdout)."""

    def __init__(self, **answers):
        self.answers, self.calls = answers, []

    def __call__(self, argv, **_):
        cmd = argv[-1]
        self.calls.append(cmd)
        for key, (rc, out) in self.answers.items():
            if key in cmd:
                return type("R", (), {"returncode": rc, "stdout": out})()
        return type("R", (), {"returncode": 0, "stdout": ""})()


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "STATE", tmp_path / "s.json")
    return tmp_path / "s.json"


def db(rows, deleted=None):
    seen = []

    def q(sql):
        seen.append(sql)
        if sql.lstrip().startswith("update"):
            return deleted if deleted is not None else [[r[0], r[1]] for r in rows]
        return rows
    q.seen = seen
    return q


def test_violations_need_one_repo_and_zero_secrets():
    assert g.violations([OK1, OK2]) == []
    assert g.violations([["23", "null0-1", "1", "0", "", "0"]]) == ["null0-1 (id 23) is not scoped to one repo"]
    assert g.violations([["24", "null0-2", "1", "41", "windy-chat", "1"]]) == [
        "null0-2 (id 24) serves windy-chat, which now sees 1 Actions secret(s)"]
    assert g.violations([["25", "null0-2", "1", "41", "windy-chat", ""]])          # unreadable = bad


def test_the_query_counts_repo_owner_and_instance_secrets():
    sql = " ".join(g.RUNNERS_SQL.split())
    assert "(r.repo_id > 0 and s.repo_id = r.repo_id)" in sql
    assert "(s.repo_id = 0 and s.owner_id = coalesce(p.owner_id, r.owner_id) and s.owner_id > 0)" in sql
    assert "(s.owner_id = 0 and s.repo_id = 0)" in sql
    assert "coalesce(r.deleted, 0) = 0 and (r.name like 'null0-%' or r.name like 'w0-%')" in sql


def test_all_clean_is_ok_and_touches_nothing(state, capsys):
    run, posts = Run(**{"is-failed": (1, "active\n")}), []
    assert g.main(db([OK1, OK2]), run, posts.append) == 0
    assert capsys.readouterr().out.startswith("offsite guard: ok (2 offsite runner(s)")
    assert posts == [] and not any("stop" in c for c in run.calls)


def test_a_new_secret_stops_the_runners_and_posts_once(state, capsys):
    run, posts = Run(**{"is-failed": (1, "active\n")}), []
    bad = ["22", "null0-2", "1", "41", "windy-chat", "1"]
    q = db([OK1, bad])
    assert g.main(q, run, lambda line: posts.append(line) or True) == 0
    out = capsys.readouterr().out
    assert out.startswith("offsite guard: CUT OFF (") and "stopped on Null 0" in out
    assert any("docker compose -p windy-git-runner-offsite stop runner-1 runner-2 runner-3" in c for c in run.calls)
    assert not any(s.lstrip().startswith("update") for s in q.seen)      # ssh worked: no soft-delete
    assert len(posts) == 1 and "windy-chat, which now sees 1 Actions secret(s)" in posts[0]
    assert g.main(q, run, lambda line: posts.append(line) or True) == 0  # same violation: no 2nd line
    assert len(posts) == 1


def test_ssh_failure_falls_back_to_soft_delete_in_gitea(state, capsys):
    run, posts = Run(**{"is-failed": (255, ""), "stop": (255, "")}), []
    q = db([["23", "null0-1", "1", "0", "", "0"]])
    assert g.main(q, run, lambda line: posts.append(line) or True) == 0
    assert any(s.lstrip().startswith("update action_runner set deleted") and "name like 'null0-%'" in s and "name like 'w0-%'" in s for s in q.seen)
    out = capsys.readouterr().out
    assert "ssh stop FAILED; soft-deleted in Gitea: null0-1 (id 23)" in out and "CUT OFF" in out


def test_a_failed_egress_unit_on_null0_cuts_off_too(state, capsys):
    run = Run(**{"is-failed": (0, "failed\n")})
    assert g.main(db([OK1, OK2]), run, lambda line: True) == 0
    out = capsys.readouterr().out
    assert "CUT OFF" in out and "egress unit (windygit-ci-egress-offsite) is FAILED" in out


def test_null0_unreachable_is_not_itself_a_violation(state, capsys):
    run = Run(**{"is-failed": (255, "")})
    assert g.main(db([OK1, OK2]), run, lambda line: True) == 0
    assert capsys.readouterr().out.startswith("offsite guard: ok")


def test_a_failed_board_post_is_retried_next_pass(state):
    run, posts = Run(**{"is-failed": (1, "active\n")}), []
    q = db([["22", "null0-2", "1", "41", "windy-chat", "2"]])
    g.main(q, run, lambda line: posts.append(line) or False)
    g.main(q, run, lambda line: posts.append(line) or True)
    assert len(posts) == 2 and json.loads(state.read_text())["posted"]


def test_unit_expects_ok_and_the_timer_is_at_least_hourly():
    unit = (ROOT / "deploy" / "systemd" / "windygit-offsite-guard.service").read_text()
    assert '--expect "^offsite guard: ok [(]"' in unit and "--owner 13" in unit
    timer = (ROOT / "deploy" / "systemd" / "windygit-offsite-guard.timer").read_text()
    assert "OnUnitActiveSec=10min" in timer


W1 = ["31", "w0-1", "1", "50", "windy-text", "0"]
W2 = ["32", "w0-2", "1", "51", "windy-connect", "0"]


def test_windy0_runners_are_checked_with_the_same_rules():
    assert g.violations([W1, W2]) == []
    assert g.violations([["33", "w0-1", "1", "50", "windy-text", "2"]]) == [
        "w0-1 (id 33) serves windy-text, which now sees 2 Actions secret(s)"]
    assert g.violations([["34", "w0-2", "1", "0", "", "0"]]) == ["w0-2 (id 34) is not scoped to one repo"]


def test_null0_stop_includes_runner_3():
    """null0-3 (windy-mind) was missing from the stop list: a secret there left it running."""
    assert "stop runner-1 runner-2 runner-3" in g.HOSTS["null0-"][2]


def test_a_secret_on_a_windy0_runner_stops_only_windy0_units(state, capsys):
    run, posts = Run(**{"is-failed": (1, "active\n")}), []
    bad = ["32", "w0-2", "1", "51", "windy-connect", "1"]
    assert g.main(db([OK1, W1, bad]), run, lambda line: posts.append(line) or True) == 0
    assert "stopped on Null 0 and Windy 0" in capsys.readouterr().out
    assert any("systemctl --user stop 'act-runner@*.service'" in c for c in run.calls)


def test_only_windy0_rows_never_ssh_null0(state, capsys):
    hosts = []

    def run(argv, **_):
        hosts.append(argv[argv.index("ConnectTimeout=8") + 1])
        return type("R", (), {"returncode": 0, "stdout": "active\n"})()

    bad = ["32", "w0-2", "1", "51", "windy-connect", "1"]
    assert g.main(db([W1, bad]), run, lambda line: True) == 0
    assert set(hosts) == {g.WINDY0}
    assert "stopped on Windy 0" in capsys.readouterr().out


def test_a_failed_egress_unit_on_windy0_cuts_off(state, capsys):
    run = Run(**{"windygit-ci-egress.service": (0, "failed\n")})
    assert g.main(db([W1, W2]), run, lambda line: True) == 0
    out = capsys.readouterr().out
    assert "CUT OFF" in out and "Windy 0's egress unit (windygit-ci-egress) is FAILED" in out


def test_windy0_stop_failure_falls_back_to_soft_delete(state, capsys):
    run = Run(**{"is-failed": (1, "active\n"), "systemctl --user stop": (1, "")})
    bad = ["32", "w0-2", "1", "51", "windy-connect", "1"]
    q = db([W1, bad])
    assert g.main(q, run, lambda line: True) == 0
    assert any(s.lstrip().startswith("update action_runner set deleted") for s in q.seen)
    assert "ssh stop FAILED" in capsys.readouterr().out


def test_an_ssh_that_raises_counts_as_a_failed_stop(state, capsys):
    def run(argv, **_):
        if "systemctl --user stop" in argv[-1]:
            raise OSError("ssh vanished")
        return type("R", (), {"returncode": 0, "stdout": "active\n"})()

    bad = ["32", "w0-2", "1", "51", "windy-connect", "1"]
    q = db([W1, bad])
    assert g.main(q, run, lambda line: True) == 0
    assert any(s.lstrip().startswith("update action_runner set deleted") for s in q.seen)
    assert "ssh stop FAILED" in capsys.readouterr().out
