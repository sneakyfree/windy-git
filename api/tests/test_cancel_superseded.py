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
    assert "j.status in (5, 7, 9) and j.task_id = 0" in sql              # waiting/blocked/pending, unclaimed only
    assert sql.count("j.status in (5, 7, 9) and j.task_id = 0") == 2     # re-checked inside the UPDATE
    assert re.findall(r"j\.status in \(([^)]*)\)", sql) == ["5, 7, 9", "5, 7, 9"]  # never 6/8 (running/cancelling)
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
    assert not any("action_run_attempt a set" in s for s in seen)       # 1.24: no attempt table, no attempt SQL
    assert len(posts) == 1 and "3 waiting/blocked PR jobs" in posts[0] and "Windy-Clone 1, windy-pro 2" in posts[0]
    assert (tmp_path / "log").read_text().count("cancelled job") == 3


def test_nothing_to_cancel_posts_nothing_and_a_db_error_never_fails_the_sync(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "LOG", tmp_path / "log")
    posts = []
    assert cs.main(lambda sql: [], posts.append) == 0 and posts == [] and not (tmp_path / "log").exists()

    def boom(sql):
        raise OSError("db down")
    assert cs.main(boom, posts.append) == 0 and posts == []


def _ssh_down(monkeypatch):
    """Windy 0 unreachable; the lane user = whoever runs the tests (CI runs as root in a container
    with no user1-gpu account)."""
    import pwd as _pwd

    class R:
        returncode = 255
    monkeypatch.setattr(cs.subprocess, "run", lambda *a, **k: R())
    monkeypatch.setattr(cs, "BOARD_USER", _pwd.getpwuid(cs.os.getuid()).pw_name)


def test_board_fallback_writes_todays_file_not_the_newest_old_one(tmp_path, monkeypatch):
    """Boss 11-02: with Windy 0 unreachable, the line goes to BOARD-FALLBACK-<today UTC>.md, created
    if missing; an older fallback file is left alone."""
    _ssh_down(monkeypatch)
    monkeypatch.setattr(cs, "FALLBACK_DIR", str(tmp_path))
    (tmp_path / "BOARD-FALLBACK-20261027.md").write_text("old\n")
    import os
    old_umask = os.umask(0o077)                                          # a tight umask must not make it 0600
    monkeypatch.setattr(cs.time, "gmtime", lambda *a: cs.time.struct_time((2026, 11, 2, 15, 0, 0, 0, 306, 0)))
    assert cs.board("[Windy Git] hello") is True
    today = tmp_path / "BOARD-FALLBACK-20261102.md"
    assert today.read_text() == "2026-11-02T15:00:00Z [Windy Git] hello\n"
    assert (tmp_path / "BOARD-FALLBACK-20261027.md").read_text() == "old\n"
    os.umask(old_umask)
    assert oct(today.stat().st_mode & 0o777) == "0o644"
    assert cs.board("[Windy Git] again") is True                        # appends to the same file
    assert today.read_text().count("\n") == 2


def test_board_fallback_without_the_directory_is_a_failed_post(tmp_path, monkeypatch):
    _ssh_down(monkeypatch)
    monkeypatch.setattr(cs, "FALLBACK_DIR", str(tmp_path / "missing"))
    assert cs.board("x") is False and not (tmp_path / "missing").exists()


def _today(monkeypatch, tmp_path):
    _ssh_down(monkeypatch)
    monkeypatch.setattr(cs, "FALLBACK_DIR", str(tmp_path))
    monkeypatch.setattr(cs.time, "gmtime", lambda *a: cs.time.struct_time((2026, 11, 2, 15, 0, 0, 0, 306, 0)))
    return tmp_path / "BOARD-FALLBACK-20261102.md"


def test_board_fallback_never_follows_a_symlink(tmp_path, monkeypatch):
    """Hub #119: runs as root; a (dangling) symlink at today's name must not make root create or
    chown its target."""
    today = _today(monkeypatch, tmp_path)
    target = tmp_path / "elsewhere"
    today.symlink_to(target)
    assert cs.board("x") is False and not target.exists()
    target.write_text("keep\n")
    assert cs.board("x") is False and target.read_text() == "keep\n"


def test_board_fallback_refuses_a_hard_link(tmp_path, monkeypatch):
    today = _today(monkeypatch, tmp_path)
    other = tmp_path / "other"
    other.write_text("keep\n")
    import os
    os.link(other, today)
    assert cs.board("x") is False and other.read_text() == "keep\n"


def test_board_fallback_unknown_lane_user_as_root_writes_nothing(tmp_path, monkeypatch):
    """Root with no such lane user: refuse BEFORE writing, so a retry can't duplicate the line."""
    today = _today(monkeypatch, tmp_path)
    monkeypatch.setattr(cs, "BOARD_USER", "no-such-user-xyz")
    monkeypatch.setattr(cs.os, "geteuid", lambda: 0)
    assert cs.board("x") is False and not today.exists()


def test_gitea_28_closes_the_attempt_rows_too_and_never_touches_running_or_cancelling(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "LOG", tmp_path / "log")
    for sql in (cs.CANCEL_SQL, cs.CLOSE_RUNS_SQL, cs.CLOSE_ATTEMPTS_SQL):
        assert "6" not in re.findall(r"status in \(([^)]*)\)", sql)[0] and "8" not in re.findall(r"status in \(([^)]*)\)", sql)[0]
    seen = []

    def query(sql):
        seen.append(sql)
        if sql is cs.CANCEL_SQL:
            return [["21", "windy-pro", "refs/pull/9/head", "aaaaaaaa", "gates", "601"]]
        if sql is cs.HAS_ATTEMPTS_SQL:
            return [["t"]]
        return []
    assert cs.main(query, lambda line: True) == 0
    att = [s for s in seen if "action_run_attempt a set" in s]
    assert len(att) == 1 and "a.run_id in (601)" in att[0] and "j.run_attempt_id = a.id and j.status <> 3" in att[0]


# --- BOARD STANDARD (Windy Boss 2026-11-10T18:29:46Z): every line goes through board-say -------------------

def _ssh_answers(monkeypatch, rc, out="", err=""):
    import pwd as _pwd
    seen = {}

    class R:
        returncode = rc
        stdout = out
        stderr = err

    def run(args, **kw):
        seen["args"], seen["input"] = args, kw.get("input")
        return R()
    monkeypatch.setattr(cs.subprocess, "run", run)
    monkeypatch.setattr(cs, "BOARD_USER", _pwd.getpwuid(cs.os.getuid()).pw_name)
    return seen


def test_board_goes_through_board_say_without_the_prefix_or_a_time(tmp_path, monkeypatch):
    seen = _ssh_answers(monkeypatch, 0, "OK 2026-11-11T03:40:00Z 1 line(s)\n")
    monkeypatch.setattr(cs, "FALLBACK_DIR", str(tmp_path))
    assert cs.board("[Windy Git] approved-first: 2 job(s) moved") is True
    assert seen["args"][-1] == '~/windy-orchestra/bin/board-say "Windy Git"'
    assert not any("BOARD.md" in a for a in seen["args"])          # no more cat >> BOARD.md
    assert seen["input"] == "approved-first: 2 job(s) moved\n"     # board-say adds "- [time Windy Git]"
    assert list(tmp_path.iterdir()) == []                          # nothing in the fallback


def test_board_say_refusal_or_an_odd_answer_is_a_failed_post_and_the_line_goes_to_the_fallback(tmp_path, monkeypatch):
    for rc, out in ((2, ""), (0, "something else\n")):
        _ssh_answers(monkeypatch, rc, out, "REFUSED: a line already starts with a time")
        monkeypatch.setattr(cs, "FALLBACK_DIR", str(tmp_path))
        monkeypatch.setattr(cs.time, "gmtime", lambda *a: cs.time.struct_time((2026, 11, 2, 9, 0, 0, 0, 306, 0)))
        assert cs.board(f"[Windy Git] rc{rc}") is True
    text = (tmp_path / "BOARD-FALLBACK-20261102.md").read_text()
    assert "[Windy Git] rc2" in text and "[Windy Git] rc0" in text


def test_sweep_board_strips_the_time_and_lane_and_needs_ok(tmp_path):
    import subprocess as sp
    fake = tmp_path / "bin"; fake.mkdir()
    log = tmp_path / "ssh.log"
    (fake / "ssh").write_text('#!/bin/sh\nfor a in "$@"; do last="$a"; done\nprintf "%s|" "$last" >> "' + str(log)
                              + '"\ncat >> "' + str(log) + '"\n[ -n "$FAIL" ] && { echo "REFUSED: x" >&2; exit 2; }\necho "OK t 1 line(s)"\n')
    (fake / "ssh").chmod(0o755)
    common = ROOT / "deploy" / "sweep" / "common.sh"
    def run(line, fail=""):
        env = {"PATH": f"{fake}:/usr/bin:/bin", "HOME": str(tmp_path), "FAIL": fail}
        return sp.run(["bash", "-c", f'. "{common}"; board "$1"', "x", line], env=env).returncode
    assert run("2026-11-11T03:40Z Windy Git -> Boss: ✅ GUARD READY") == 0
    assert run("2026-11-11T03:41Z Windy Git: \U0001f6a8 runner-guard: 1 NEW") == 0
    assert run("plain text", fail="1") != 0                       # a refusal fails the step (never silent)
    got = log.read_text()
    assert '~/windy-orchestra/bin/board-say "Windy Git"|-> Boss: ✅ GUARD READY\n' in got
    assert '~/windy-orchestra/bin/board-say "Windy Git"|\U0001f6a8 runner-guard: 1 NEW\n' in got
    assert "BOARD.md" not in got
