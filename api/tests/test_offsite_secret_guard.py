"""scripts/offsite_secret_guard.py (Hub #121, #133): the house-machine CI runners (Null 0 null0-*, Windy 0 w0-*)
stay repo-scoped and secret-free after registration; any violation cuts them off at once (ssh stop with a
read-back, else soft-delete in Gitea)."""

from __future__ import annotations

import importlib.util
import json
import re
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
W1 = ["31", "w0-1", "1", "50", "windy-text", "0"]
W2 = ["32", "w0-2", "1", "51", "windy-connect", "0"]
HEALTHY = (0, "LoadState=loaded\nActiveState=inactive\nResult=success\n")


class Run:
    """Fake subprocess.run for the ssh calls. `answers` maps a substring of the remote command to
    (rc, stdout); the first match wins; the default answers a healthy egress unit and a clean stop
    (2 running before, 0 after)."""

    def __init__(self, **answers):
        self.answers, self.calls, self.hosts = answers, [], []

    def __call__(self, argv, **_):
        cmd = argv[-1]
        self.calls.append(cmd)
        self.hosts.append(argv[argv.index("ConnectTimeout=8") + 1])
        for key, (rc, out) in self.answers.items():
            if key in cmd:
                return type("R", (), {"returncode": rc, "stdout": out})()
        if "systemctl show" in cmd:
            return type("R", (), {"returncode": HEALTHY[0], "stdout": HEALTHY[1]})()
        return type("R", (), {"returncode": 0, "stdout": "3 0\n"})()


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
    assert g.violations([OK1, OK2, W1, W2]) == []
    assert g.violations([["23", "null0-1", "1", "0", "", "0"]]) == ["null0-1 (id 23) is not scoped to one repo"]
    assert g.violations([["24", "null0-2", "1", "41", "windy-chat", "1"]]) == [
        "null0-2 (id 24) serves windy-chat, which now sees 1 Actions secret(s)"]
    assert g.violations([["25", "null0-2", "1", "41", "windy-chat", ""]])          # unreadable = bad
    assert g.violations([["33", "w0-1", "1", "50", "windy-text", "2"]]) == [
        "w0-1 (id 33) serves windy-text, which now sees 2 Actions secret(s)"]
    assert g.violations([["34", "w0-2", "1", "0", "", "0"]]) == ["w0-2 (id 34) is not scoped to one repo"]


def test_a_row_that_is_not_exactly_six_fields_is_a_violation():
    """A '|' in a runner name shifts the columns; it must never read as a clean row."""
    shifted = ["35", "w0-x", "1", "50", "repo", "0", "extra"]
    out = g.violations([shifted])
    assert len(out) == 1 and "7 fields instead of 6" in out[0]
    assert g.violations([["36", "w0-y"]])


def test_the_query_counts_repo_owner_and_instance_secrets():
    sql = " ".join(g.RUNNERS_SQL.split())
    assert "(r.repo_id > 0 and s.repo_id = r.repo_id)" in sql
    assert "(s.repo_id = 0 and s.owner_id = coalesce(p.owner_id, r.owner_id) and s.owner_id > 0)" in sql
    assert "(s.owner_id = 0 and s.repo_id = 0)" in sql
    assert "coalesce(r.deleted, 0) = 0 and (r.name like 'null0-%' or r.name like 'w0-%')" in sql


def test_null0_stop_lists_every_runner_service_in_the_compose_file():
    """null0-3 was once missing from the stop list: derive the names from the compose file, not from memory."""
    compose = (ROOT / "deploy" / "runner-offsite" / "docker-compose.yml").read_text()
    services = re.findall(r"^  (runner-\d+):", compose, flags=re.M)
    assert len(services) >= 3
    stop = g.HOSTS["null0-"][2]
    for svc in services:
        assert re.search(rf"stop [^;]*\b{svc}\b", stop), f"{svc} is not in the Null 0 stop list"


def test_all_clean_is_ok_and_touches_nothing(state, capsys):
    run, posts = Run(), []
    assert g.main(db([OK1, OK2, W1]), run, posts.append) == 0
    assert capsys.readouterr().out.startswith("offsite guard: ok (3 offsite runner(s)")
    assert posts == [] and not any(" stop " in c for c in run.calls)


def test_a_new_secret_stops_the_runners_and_posts_once(state, capsys):
    run, posts = Run(), []
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
    run, posts = Run(**{"systemctl show": (255, ""), "docker compose": (255, "")}), []
    q = db([["23", "null0-1", "1", "0", "", "0"]])
    assert g.main(q, run, lambda line: posts.append(line) or True) == 0
    upd = [s for s in q.seen if s.lstrip().startswith("update action_runner set deleted")]
    assert len(upd) == 1 and "name like 'null0-%'" in upd[0] and "w0-" not in upd[0]   # only the failed host
    out = capsys.readouterr().out
    assert "ssh stop FAILED on Null 0; soft-deleted in Gitea: null0-1 (id 23)" in out and "CUT OFF" in out


def test_a_failed_egress_unit_on_null0_cuts_off_too(state, capsys):
    run = Run(**{"windygit-ci-egress-offsite": (0, "LoadState=loaded\nActiveState=failed\nResult=exit-code\n")})
    assert g.main(db([OK1, OK2]), run, lambda line: True) == 0
    out = capsys.readouterr().out
    assert "CUT OFF" in out and "egress unit (windygit-ci-egress-offsite) is missing or FAILED" in out


def test_an_egress_unit_whose_last_run_did_not_succeed_is_a_violation(state, capsys):
    run = Run(**{"systemctl show": (0, "LoadState=loaded\nActiveState=inactive\nResult=exit-code\n")})
    assert g.main(db([W1]), run, lambda line: True) == 0
    assert "CUT OFF" in capsys.readouterr().out


def test_a_never_installed_egress_unit_is_a_violation_not_a_healthy_inactive(state, capsys):
    run = Run(**{"systemctl show": (0, "LoadState=not-found\nActiveState=inactive\nResult=success\n")})
    assert g.main(db([W1, W2]), run, lambda line: True) == 0
    out = capsys.readouterr().out
    assert "CUT OFF" in out and "Windy 0's egress unit (windygit-ci-egress) is missing or FAILED" in out


def test_an_ssh_timeout_is_unknown_then_a_violation_after_three_passes(state, capsys):
    run = Run(**{"systemctl show": (124, "")})
    q = db([W1, W2])
    posts = []
    for _ in range(2):
        assert g.main(q, run, lambda line: posts.append(line) or True) == 0
        assert capsys.readouterr().out.startswith("offsite guard: UNKNOWN (Windy 0")
    assert posts == [] and not any(s.lstrip().startswith("update") for s in q.seen)   # one blip cuts nothing
    assert g.main(q, run, lambda line: posts.append(line) or True) == 0
    out = capsys.readouterr().out
    assert "CUT OFF" in out and "could not be read for 3 passes in a row" in out and len(posts) == 1


def test_a_readable_unit_resets_the_unknown_streak(state, capsys):
    q = db([W1])
    g.main(q, Run(**{"systemctl show": (255, "")}), lambda line: True)
    assert json.loads(state.read_text())["unknown"] == {"w0-": 1}
    g.main(q, Run(), lambda line: True)
    assert not state.exists() or json.loads(state.read_text()) == {}


def test_a_secret_on_a_windy0_runner_stops_windy0_units_and_reads_back(state, capsys):
    run, posts = Run(), []
    bad = ["32", "w0-2", "1", "51", "windy-connect", "1"]
    assert g.main(db([OK1, W1, bad]), run, lambda line: posts.append(line) or True) == 0
    assert "stopped on Null 0 and Windy 0" in capsys.readouterr().out
    cmd = next(c for c in run.calls if "act-runner@" in c and "stop" in c)
    assert "systemctl --user" in cmd and "id -u windygit-ci" in cmd and "1002" not in cmd


def test_only_windy0_rows_never_ssh_null0(state, capsys):
    run = Run()
    bad = ["32", "w0-2", "1", "51", "windy-connect", "1"]
    assert g.main(db([W1, bad]), run, lambda line: True) == 0
    assert set(run.hosts) == {g.WINDY0}
    assert "stopped on Windy 0" in capsys.readouterr().out


@pytest.mark.parametrize("answer", [
    (0, "1 0\n"),      # fewer ran than there are live rows (2): the stop matched less than it should (MED-1)
    (0, "2 1\n"),      # one still runs after the stop
    (0, ""),           # no read-back at all
    (0, "garbage\n"),
    (1, "2 0\n"),      # stop itself failed
])
def test_a_stop_that_is_not_read_back_as_done_falls_back_to_soft_delete(state, capsys, answer):
    run = Run(**{"act-runner@": answer})
    bad = ["32", "w0-2", "1", "51", "windy-connect", "1"]
    q = db([W1, bad])
    assert g.main(q, run, lambda line: True) == 0
    assert any(s.lstrip().startswith("update action_runner set deleted") for s in q.seen)
    assert "ssh stop FAILED" in capsys.readouterr().out


def test_an_ssh_that_raises_counts_as_a_failed_stop(state, capsys):
    def run(argv, **_):
        if "act-runner@" in argv[-1] and "stop" in argv[-1]:
            raise OSError("ssh vanished")
        return type("R", (), {"returncode": 0, "stdout": HEALTHY[1]})()

    bad = ["32", "w0-2", "1", "51", "windy-connect", "1"]
    q = db([W1, bad])
    assert g.main(q, run, lambda line: True) == 0
    assert any(s.lstrip().startswith("update action_runner set deleted") for s in q.seen)
    assert "ssh stop FAILED" in capsys.readouterr().out


def test_a_failed_board_post_is_retried_next_pass(state):
    run, posts = Run(), []
    q = db([["22", "null0-2", "1", "41", "windy-chat", "2"]])
    g.main(q, run, lambda line: posts.append(line) or False)
    g.main(q, run, lambda line: posts.append(line) or True)
    assert len(posts) == 2 and json.loads(state.read_text())["posted"]


def test_unit_expects_ok_and_the_timer_is_at_least_hourly():
    unit = (ROOT / "deploy" / "systemd" / "windygit-offsite-guard.service").read_text()
    assert '--expect "^offsite guard: ok [(]"' in unit and "--owner 13" in unit
    timer = (ROOT / "deploy" / "systemd" / "windygit-offsite-guard.timer").read_text()
    assert "OnUnitActiveSec=10min" in timer


# --- Hub 2026-11-12T08:44:09Z ONE FOLLOW-UP, Boss RULED 08:45:27Z (5) --------------------------------------------

def test_a_host_already_at_zero_reads_as_stopped_not_a_failed_stop(state, capsys):
    run = Run(**{"act-runner@": (0, "0 0\n")})          # a hand stop earlier: none running before, none after
    bad = ["32", "w0-2", "1", "51", "windy-connect", "1"]
    q = db([W1, bad])
    assert g.main(q, run, lambda line: True) == 0
    assert not any(s.lstrip().startswith("update action_runner set deleted") for s in q.seen)
    assert "stopped on Windy 0" in capsys.readouterr().out


def test_one_host_failing_its_stop_soft_deletes_only_its_own_rows(state, capsys):
    run = Run(**{"act-runner@": (0, "2 1\n")})          # Windy 0: one still runs; Null 0: the default clean stop
    bad = ["32", "w0-2", "1", "51", "windy-connect", "1"]
    q = db([OK1, OK2, W1, bad], deleted=[["31", "w0-1"], ["32", "w0-2"]])
    assert g.main(q, run, lambda line: True) == 0
    upd = [s for s in q.seen if s.lstrip().startswith("update action_runner set deleted")]
    assert len(upd) == 1 and "name like 'w0-%'" in upd[0] and "null0-" not in upd[0]
    out = capsys.readouterr().out
    assert "stopped on Null 0; ssh stop FAILED on Windy 0; soft-deleted in Gitea: w0-1 (id 31), w0-2 (id 32)" in out


def test_soft_delete_only_takes_known_prefixes():
    seen = []
    assert g.soft_delete(lambda sql: seen.append(sql) or [], ["evil' or 1=1 --"]) == [] and seen == []
    g.soft_delete(lambda sql: seen.append(sql) or [], ["null0-"])
    assert "name like 'null0-%'" in seen[0] and "w0-" not in seen[0]
