"""scripts/priority_queue.py: Boss's `PRIORITY <repo>#<PR> until <ISO>` BOARD token moves that PR's WAITING jobs first."""

from __future__ import annotations

import calendar
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import priority_queue as pq  # noqa: E402

NOW = calendar.timegm((2026, 11, 4, 17, 0, 0))


def fake_sha(pr):
    """A deterministic 40-hex 'head sha' that encodes the PR number, so the Fake can map a commit back to its PR."""
    return format(int(pr), "040x")


def at(h, m=0, day=4):
    return calendar.timegm((2026, 11, day, h, m, 0))


BOARD = """\
[2026-11-04T15:41Z, Windy Boss] VERON LOAD RULE (now): nothing about priority here
[2026-11-04T16:52Z, Windy Boss] PRIORITY windy-pro#1706 until 2026-11-05T12:35Z and PRIORITY windy-pro#1704 until 2026-11-05T12:00Z
2026-11-04T16:53:10Z Windy Git PRIORITY windy-pro#9999 until 2026-11-05T12:00Z   (quoting, from a lane)
"""


# ---------------------------------------------------------------- parsing
def test_two_tokens_on_one_boss_line_count_and_a_lane_quoting_the_token_does_not():
    act, notes = pq.parse_board(BOARD, NOW)
    assert act == {("windy-pro", 1706): at(12, 35, 5), ("windy-pro", 1704): at(12, 0, 5)} and notes == []


@pytest.mark.parametrize("line", [
    "[2026-11-04T16:52Z, Windy Boss] PRIORITY windy-pro#1706 until 2026-11-05T12:35Z",
    "[2026-11-04T16:52:09Z Windy Boss] PRIORITY windy-pro#1706 until 2026-11-05T12:35Z",
    "2026-11-04T16:52:09Z Windy Boss PRIORITY windy-pro#1706 until 2026-11-05T12:35Z",
    "- 2026-11-04T16:52Z Windy Boss PRIORITY windy-pro#1706 until 2026-11-05T12:35Z",
    "[2026-11-04T16:52Z Windy Boss] PRIORITY windy-pro#1706 until 2026-11-05T12:35Z.",
    "[2026-11-04T16:52Z Windy Boss] (PRIORITY windy-pro#1706 until 2026-11-05T12:35Z)",
])
def test_the_boss_header_formats_seen_on_the_board(line):
    assert pq.parse_board(line, NOW)[0] == {("windy-pro", 1706): at(12, 35, 5)}


@pytest.mark.parametrize("line", [
    "[2026-11-04T16:52Z, Windy Hub] PRIORITY windy-pro#1706 until 2026-11-05T12:35Z",
    "[2026-11-04T16:52Z, Windy Git] relaying Windy Boss: PRIORITY windy-pro#1706 until 2026-11-05T12:35Z",
    "Windy Boss said PRIORITY windy-pro#1706 until 2026-11-05T12:35Z",                       # no time header
    "[2026-11-04T16:52Z, Windy Boss] priority windy-pro#1706 until 2026-11-05T12:35Z",       # lower case
    "[2026-11-04T16:52Z, Windy Boss] PRIORITY windy-pro 1706 until 2026-11-05T12:35Z",       # no #
    "[2026-11-04T16:52Z, Windy Boss] PRIORITY windy-pro#1706 until tomorrow",
    "[2026-11-04T16:52Z, Windy Boss] PRIORITY windy-pro#1706 until 2026-11-05T12:35Zx",
    "[2026-11-04T16:52Z, Windy Boss] PRIORITY wind y#1706 until 2026-11-05T12:35Z",
    "[2026-11-04T16:52Z, Windy Boss] PRIORITY windy';drop table x;--#1706 until 2026-11-05T12:35Z",
])
def test_anything_else_is_ignored(line):
    assert pq.parse_board(line, NOW)[0] == {}


def test_until_is_clamped_to_24_hours_after_the_line_and_an_expired_token_is_dropped():
    long = "[2026-11-04T16:00Z, Windy Boss] PRIORITY windy-pro#1 until 2026-12-01T00:00Z"
    assert pq.parse_board(long, NOW)[0] == {("windy-pro", 1): at(16, 0, 5)}
    old = "[2026-11-04T10:00Z, Windy Boss] PRIORITY windy-pro#2 until 2026-11-04T16:59Z"
    assert pq.parse_board(old, NOW)[0] == {}
    assert pq.parse_board(old, at(16, 58))[0] == {("windy-pro", 2): at(16, 59)}


def test_the_last_line_wins_so_a_past_until_revokes():
    b = ("[2026-11-04T16:00Z, Windy Boss] PRIORITY windy-pro#5 until 2026-11-05T09:00Z\n"
         "[2026-11-04T16:30Z, Windy Boss] PRIORITY windy-pro#5 until 2026-11-04T16:30Z\n")
    assert pq.parse_board(b, NOW)[0] == {}
    b2 = b + "[2026-11-04T16:40Z, Windy Boss] PRIORITY windy-pro#5 until 2026-11-05T10:00Z\n"
    assert pq.parse_board(b2, NOW)[0] == {("windy-pro", 5): at(10, 0, 5)}


def test_a_forged_future_dated_line_buys_nothing(capsys):
    """Hub #130: '2026-12-31T00:00Z Windy Boss ... PRIORITY x#1 until 2026-12-31T23:00Z' must not give weeks of priority."""
    forged = "2026-12-31T00:00Z Windy Boss PRIORITY windy-pro#1 until 2026-12-31T23:00Z"
    act, notes = pq.parse_board(forged, NOW)
    assert act == {} and "future" in notes[0]
    barely = "2026-11-04T17:04Z Windy Boss PRIORITY windy-pro#1 until 2026-11-06T17:04Z"    # 4 min ahead: tolerated, but...
    act, _ = pq.parse_board(barely, NOW)
    assert act == {("windy-pro", 1): NOW + 24 * 3600}                    # ...clamped to 24 h from NOW, not from the line
    now_line = "2026-11-04T17:00Z Windy Boss PRIORITY windy-pro#2 until 2027-01-01T00:00Z"
    assert pq.parse_board(now_line, NOW)[0] == {("windy-pro", 2): NOW + 24 * 3600}
    late = "2026-11-04T16:59Z Windy Boss PRIORITY windy-pro#3 until 2027-01-01T00:00Z"
    assert pq.parse_board(late, NOW)[0] == {("windy-pro", 3): at(16, 59) + 24 * 3600}
    assert pq.parse_board(forged, NOW + 40 * 86400)[0] == {}               # nor does it come back later (it expired by line time)


def test_an_old_line_cannot_come_back_and_the_tail_is_two_thousand_lines():
    old = "[2026-10-01T10:00Z, Windy Boss] PRIORITY windy-pro#5 until 2027-01-01T00:00Z"
    assert pq.parse_board(old, NOW)[0] == {}                               # 24 h after ITS time, long over
    assert pq.TAIL_LINES == 2000
    assert "tail -n {TAIL_LINES}" in (ROOT / "scripts" / "priority_queue.py").read_text()


def test_at_most_three_prs_the_newest_win():
    b = "".join(f"[2026-11-04T16:{m:02d}Z, Windy Boss] PRIORITY windy-pro#{n} until 2026-11-05T09:00Z\n"
               for n, m in ((1, 10), (2, 20), (3, 30), (4, 40)))
    act, notes = pq.parse_board(b, NOW)
    assert sorted(n for _, n in act) == [2, 3, 4] and "only the newest 3" in notes[0]


def test_a_line_dated_in_the_future_is_ignored():
    b = "[2026-11-04T23:00Z, Windy Boss] PRIORITY windy-pro#7 until 2026-11-05T09:00Z"
    act, notes = pq.parse_board(b, NOW)
    assert act == {} and "future" in notes[0]


# ---------------------------------------------------------------- the SQL
def test_the_sql_only_touches_waiting_unclaimed_jobs_of_the_newest_run_of_one_repo_and_pr():
    s = pq.jobs_sql("windy-pro", 1706, fake_sha(1706))
    assert "p.owner_name = 'windyadmin' and p.name = 'windy-pro'" in s and f"r.commit_sha = '{fake_sha(1706)}'" in s
    assert "j.status = 5 and j.task_id = 0" in s and "select max(r2.id)" in s
    assert "r.event in ('pull_request', 'pull_request_sync')" in s
    m = pq.move_sql([3, 4], 1000)
    assert "set updated = 999 where id in (3,4) and status = 5 and task_id = 0 and updated >= 1000" in m
    assert "status = 3" not in m and "delete" not in m.lower()
    f = pq.floor_sql([3, 4])
    assert "status = 5 and task_id = 0 and id not in (3,4)" in f


@pytest.mark.parametrize("repo", ["a;b", "a b", "a'b", "", "x" * 101, "a--"[:0] + "é"])
def test_a_bad_repo_name_never_reaches_sql(repo):
    with pytest.raises(AssertionError):
        pq.jobs_sql(repo, 1, fake_sha(1))


def test_a_bad_pr_number_never_reaches_sql():
    with pytest.raises(AssertionError):
        pq.jobs_sql("windy-pro", 0, fake_sha(1))
    with pytest.raises(AssertionError):
        pq.jobs_sql("windy-pro", "1; drop", fake_sha(1))      # type: ignore[arg-type]


# ---------------------------------------------------------------- the run
class Fake:
    """A tiny queue: {job_id: (repo#pr or None, updated)}; understands the three statements priority_queue sends."""

    def __init__(self, jobs):
        self.jobs = dict(jobs)
        self.sql = []

    def query(self, sql):
        self.sql.append(sql)
        if "select j.id, j.name from action_run_job" in sql:
            import re
            repo = re.search(r"p.name = '([^']+)'", sql).group(1)
            pr = str(int(re.search(r"r.commit_sha = '([0-9a-f]{40})'", sql).group(1), 16))
            return [[str(i), "gate"] for i, (k, _u) in sorted(self.jobs.items()) if k == f"{repo}#{pr}"]
        if sql.lstrip().startswith("select coalesce(min(updated)"):
            import re
            ids = {int(x) for x in re.search(r"not in \(([\d,]+)\)", sql).group(1).split(",")}
            rest = [u for i, (_k, u) in self.jobs.items() if i not in ids]
            return [[str(min(rest) if rest else 0), str(len(rest))]]
        if sql.lstrip().startswith("update action_run_job"):
            import re
            new = int(re.search(r"set updated = (\d+)", sql).group(1))
            fl = int(re.search(r"updated >= (\d+)", sql).group(1))
            ids = [int(x) for x in re.search(r"id in \(([\d,]+)\)", sql).group(1).split(",")]
            out = []
            for i in ids:
                k, u = self.jobs[i]
                if u >= fl:
                    self.jobs[i] = (k, new)
                    out.append([str(i), "gate"])
            return out
        raise AssertionError(sql)


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setattr(pq, "STATE", tmp_path / "state.json")


def run(fake, board=BOARD, now=NOW, posts=None, dry=False, read=None, head=lambda repo, pr: fake_sha(pr)):
    posts = [] if posts is None else posts
    rc = pq.main(query=fake.query, post=lambda s: posts.append(s) or True,
                 read=read or (lambda: board), now_fn=lambda: now, dry=dry, head=head)
    return rc, posts


def test_moves_only_the_named_prs_waiting_jobs_ahead_of_everyone_else(capsys):
    f = Fake({1: ("windy-chat#10", 100), 2: ("windy-pro#1706", 500), 3: ("windy-pro#1706", 600),
              4: ("windy-pro#1800", 200), 5: (None, 150)})
    rc, posts = run(f)
    assert rc == 0
    assert f.jobs[2][1] == 99 and f.jobs[3][1] == 99                     # one second below the oldest OTHER job
    assert f.jobs[1][1] == 100 and f.jobs[4][1] == 200 and f.jobs[5][1] == 150    # nobody else touched
    assert "priority: ok (2 active token(s): windy-pro#1704, windy-pro#1706; 2 job(s) moved)" in capsys.readouterr().out
    assert sum("PRIORITY ACTIVE" in p for p in posts) == 2 and sum("moved 2 waiting job(s)" in p for p in posts) == 1


def test_a_second_run_changes_nothing_and_posts_nothing():
    f = Fake({1: ("windy-chat#10", 100), 2: ("windy-pro#1706", 500)})
    run(f)
    before = dict(f.jobs)
    rc, posts = run(f, now=NOW + 120)
    assert rc == 0 and f.jobs == before and posts == []


def test_new_jobs_of_the_same_pr_are_picked_up_on_the_next_run_and_the_post_is_rate_limited():
    f = Fake({1: ("windy-chat#10", 100), 2: ("windy-pro#1706", 500)})
    run(f)
    f.jobs[3] = ("windy-pro#1706", 900)                                   # a dependent job became waiting
    rc, posts = run(f, now=NOW + 120)
    assert f.jobs[3][1] == 99 and posts == []                             # moved, but within 30 min: no new BOARD line
    f.jobs[4] = ("windy-pro#1706", 950)
    rc, posts = run(f, now=NOW + 1900)
    assert f.jobs[4][1] == 99 and sum("moved 1 waiting job(s)" in p for p in posts) == 1


def test_when_every_waiting_job_is_a_priority_job_nothing_moves():
    f = Fake({2: ("windy-pro#1706", 500)})
    run(f)
    assert f.jobs[2][1] == 500


def test_a_job_that_a_runner_took_in_between_is_not_touched():
    class Racy(Fake):
        def query(self, sql):
            if sql.lstrip().startswith("update action_run_job"):
                self.jobs[2] = ("windy-pro#1706", 99)                    # already ahead (or claimed): the guard refuses
            return super().query(sql)
    f = Racy({1: ("windy-chat#10", 100), 2: ("windy-pro#1706", 500)})
    run(f)
    assert f.jobs[2][1] == 99


def test_an_unreadable_board_does_nothing_and_never_says_ok(capsys):
    f = Fake({1: ("windy-chat#10", 100), 2: ("windy-pro#1706", 500)})
    rc, posts = run(f, read=lambda: None)
    out = capsys.readouterr().out
    assert rc == 1 and out.startswith("priority: UNREADABLE") and "ok" not in out.split(":")[1][:4]
    assert f.sql == [] and posts == [] and f.jobs[2][1] == 500


def test_dry_run_writes_nothing(capsys):
    f = Fake({1: ("windy-chat#10", 100), 2: ("windy-pro#1706", 500)})
    rc, posts = run(f, dry=True)
    assert rc == 0 and posts == [] and f.jobs[2][1] == 500 and not pq.STATE.exists()
    assert "would move 1 waiting job(s) of windy-pro#1706 below updated=100" in capsys.readouterr().out
    assert not any(s.lstrip().startswith("update") for s in f.sql)


def test_expiry_posts_one_ended_line_and_stops_moving():
    f = Fake({1: ("windy-chat#10", 100), 2: ("windy-pro#1706", 500)})
    run(f)
    late = at(12, 36, 5)
    f.jobs[2] = ("windy-pro#1706", 500)
    rc, posts = run(f, now=late)
    assert f.jobs[2][1] == 500 and sum("PRIORITY ENDED" in p for p in posts) == 2
    rc, posts = run(f, now=late + 120)
    assert posts == []


def test_a_changed_until_is_announced_again():
    f = Fake({1: ("windy-chat#10", 100)})
    run(f)
    b2 = BOARD + "[2026-11-04T16:58Z, Windy Boss] PRIORITY windy-pro#1706 until 2026-11-05T13:00Z\n"
    rc, posts = run(f, board=b2, now=NOW + 120)
    assert sum("PRIORITY ACTIVE windy-pro#1706 until 2026-11-05T13:00Z" in p for p in posts) == 1


def test_the_script_never_cancels_deletes_or_writes_the_board_file_directly():
    src = (ROOT / "scripts" / "priority_queue.py").read_text()
    code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
    assert "status = 3" not in code and "delete from" not in code.lower() and "drop " not in code.lower()
    assert "cat >>" not in code and ">>" not in code            # it reads the BOARD with `tail`; writes go through cs.board()
    assert "tail -n {TAIL_LINES}" in code


def test_the_units_run_it_every_two_minutes_under_a_heartbeat_that_rejects_unreadable():
    svc = (ROOT / "deploy" / "systemd" / "windygit-priority-queue.service").read_text()
    tim = (ROOT / "deploy" / "systemd" / "windygit-priority-queue.timer").read_text()
    assert 'windy-job windygit-priority-queue 20m --expect "^priority: ok " --owner 13' in svc
    assert "scripts/priority_queue.py" in svc and "Type=oneshot" in svc
    assert "OnUnitActiveSec=2min" in tim and "WantedBy=timers.target" in tim
    import re
    assert re.search(r"^priority: ok ", "priority: ok (0 active token(s): none; 0 job(s) moved)")
    assert not re.search(r"^priority: ok ", "priority: UNREADABLE board (Windy 0 down and no fallback file): nothing moved")


# ---------------------------------------------------------------- "unverified token" (Boss 11-04 17:07Z)
TOKEN_LINE = "[2026-11-04T16:52Z, Windy Boss] PRIORITY windy-pro#1706 until 2026-11-05T12:35Z"


def unv(board, key="windy-pro#1706"):
    f = Fake({1: ("windy-chat#10", 100), 2: ("windy-pro#1706", 500)})
    rc, posts = run(f, board=board)
    return [p for p in posts if "UNVERIFIED TOKEN " + key in p], f, posts


def test_a_token_no_other_boss_line_names_is_logged_as_unverified_but_still_applied():
    u, f, _ = unv(TOKEN_LINE)
    assert len(u) == 1 and "#1706" in u[0] and "applied" in u[0]
    assert f.jobs[2][1] == 99                                            # Boss wants to SEE it, not to have it blocked


@pytest.mark.parametrize("other", [
    "[2026-11-04T16:40Z, Windy Boss] Slot plan: #1706 deploys Thu 12:35Z",
    "[2026-11-04T08:00Z Windy Boss] windy-pro#1706 is the slot PR",
    "2026-11-04T23:59:59Z Windy Boss (#1706)",
])
def test_another_boss_line_the_same_utc_day_naming_the_pr_verifies_it(other):
    assert unv(other + "\n" + TOKEN_LINE)[0] == []
    assert unv(TOKEN_LINE + "\n" + other.replace("2026-11-04T23:59:59Z", "2026-11-04T16:59:59Z"))[0] == []


@pytest.mark.parametrize("other", [
    "[2026-11-04T16:40Z, Windy Hub] #1706 deploys Thu 12:35Z",               # not Boss
    "[2026-11-03T16:40Z, Windy Boss] #1706 deploys Thu 12:35Z",              # another day
    "[2026-11-04T16:40Z, Windy Boss] #17061 is something else",              # a different number
    "[2026-11-04T16:40Z, Windy Boss] PRIORITY windy-pro#1706 until 2026-11-05T12:35Z",   # the token itself again
    "[2026-11-04T16:40Z, Windy Boss] no number here",
])
def test_these_do_not_verify_a_token(other):
    assert len(unv(other + "\n" + TOKEN_LINE)[0]) == 1


def test_the_unverified_line_is_posted_once_and_again_only_if_the_token_changes():
    f = Fake({1: ("windy-chat#10", 100)})
    _, p1 = run(f, board=TOKEN_LINE)
    _, p2 = run(f, board=TOKEN_LINE, now=NOW + 120)
    assert sum("UNVERIFIED" in p for p in p1) == 1 and sum("UNVERIFIED" in p for p in p2) == 0
    t2 = TOKEN_LINE + "\n[2026-11-04T16:58Z, Windy Boss] PRIORITY windy-pro#1706 until 2026-11-05T13:00Z"
    _, p3 = run(f, board=t2, now=NOW + 240)
    assert sum("UNVERIFIED" in p for p in p3) == 1
    t3 = t2 + "\n[2026-11-04T16:59Z, Windy Boss] slot: #1706 at Thu 13:00Z"
    _, p4 = run(f, board=t3, now=NOW + 360)
    assert sum("UNVERIFIED" in p for p in p4) == 0


def test_the_token_lines_own_prose_does_not_verify_it():
    own = "[2026-11-04T16:52Z, Windy Boss] slot #1706 (prose on the token's own line): PRIORITY windy-pro#1706 until 2026-11-05T12:35Z"
    assert len(unv(own)[0]) == 1


# ------------------------------------------- GitHub PR number != Windy Git PR number (windy-calendar #130 = PR 73)
SHA = "09958b6c17d40f23b2a47d51d05179618fc6d9f8"
CAL = "[2026-11-04T16:52Z, Windy Boss] PRIORITY windy-calendar#130 until 2026-11-05T12:00Z\n"


class BySha(Fake):
    """The Gitea side: the run for SHA sits on refs/pull/73/head; jobs are keyed by the Windy Git PR number."""

    def query(self, sql):
        if "select j.id, j.name from action_run_job" in sql and "r.commit_sha = '" in sql:
            self.sql.append(sql)
            import re
            repo = re.search(r"p.name = '([^']+)'", sql).group(1)
            sha = re.search(r"r.commit_sha = '([0-9a-f]+)'", sql).group(1)
            pr = {SHA: "73"}.get(sha, "0")
            return [[str(i), "test"] for i, (k, _u) in sorted(self.jobs.items()) if k == f"{repo}#{pr}"]
        return super().query(sql)


def test_the_sql_matches_by_commit_when_the_head_sha_is_known():
    s = pq.jobs_sql("windy-calendar", 130, SHA)
    assert f"r.ref like 'refs/pull/%/head' and r.commit_sha = '{SHA}'" in s and "refs/pull/130/head" not in s
    assert "j.status = 5 and j.task_id = 0" in s and "select max(r2.id)" in s
    with pytest.raises(AssertionError):
        pq.jobs_sql("windy-calendar", 130, "x' or 1=1 --")


def test_a_github_number_is_resolved_to_the_windy_git_pr_through_its_head_sha(capsys):
    f = BySha({1: ("windy-chat#10", 100), 2: ("windy-calendar#73", 500), 3: ("windy-calendar#130", 700)})
    rc, posts = run(f, board=CAL, head=lambda repo, pr: SHA if (repo, pr) == ("windy-calendar", 130) else None)
    assert rc == 0
    assert f.jobs[2][1] == 99                                    # Windy Git PR 73 = GitHub #130: moved
    assert f.jobs[3][1] == 700 and f.jobs[1][1] == 100          # a different PR that merely has the number 130 is NOT
    assert "1 job(s) moved" in capsys.readouterr().out


def test_when_github_cannot_be_asked_and_nothing_is_cached_nothing_moves_and_it_is_said_once(capsys):
    # the bare number would be a DIFFERENT Windy Git PR on most repos: fail closed (Hub #135 MED)
    f = Fake({1: ("windy-chat#10", 100), 2: ("windy-pro#1706", 500), 3: ("windy-pro#1704", 600)})
    posts = []
    rc, _ = run(f, head=lambda repo, pr: None, posts=posts)
    assert rc == 0 and f.jobs[2][1] == 500 and f.jobs[3][1] == 600
    assert not any("select j.id, j.name" in q for q in f.sql)                # no job query was even sent
    out = capsys.readouterr().out
    assert "UNRESOLVED windy-pro#1706" in out and "0 job(s) moved" in out
    un = [p for p in posts if "UNRESOLVED" in p]
    assert len(un) == 2 and any("windy-pro#1706 (GitHub unreachable), nothing moved" in p for p in un)
    run(f, head=lambda repo, pr: None, posts=posts, now=NOW + 600)           # next ticks: retried, not re-posted
    assert len([p for p in posts if "UNRESOLVED" in p]) == 2
    run(f, head=lambda repo, pr: None, posts=posts, now=NOW + 1900)          # after 30 min: said again
    assert len([p for p in posts if "UNRESOLVED" in p]) == 4


def test_a_cached_sha_is_still_used_while_github_is_down():
    f = Fake({1: ("windy-chat#10", 100), 2: ("windy-pro#1706", 500)})
    run(f)                                                                   # resolves and caches
    f.jobs[2] = ("windy-pro#1706", 500)                                      # a new waiting job appears
    rc, _ = run(f, head=lambda repo, pr: None, now=NOW + 400)                # 6+ min later, gh down: cached sha used
    assert rc == 0 and f.jobs[2][1] == 99


def test_the_head_sha_is_asked_once_per_five_minutes_and_remembered():
    asked = []
    f = BySha({1: ("windy-chat#10", 100), 2: ("windy-calendar#73", 500)})

    def head(repo, pr):
        asked.append((repo, pr))
        return SHA
    run(f, board=CAL, head=head)
    run(f, board=CAL, head=head, now=NOW + 120)
    assert asked == [("windy-calendar", 130)]
    run(f, board=CAL, head=head, now=NOW + 400)
    assert len(asked) == 2


def test_gh_head_never_trusts_odd_output_or_names(monkeypatch):
    import subprocess as sp
    monkeypatch.setattr(pq.subprocess, "run", lambda *a, **k: sp.CompletedProcess(a, 0, stdout="not a sha\n", stderr=""))
    assert pq.gh_head("windy-calendar", 130) is None
    monkeypatch.setattr(pq.subprocess, "run", lambda *a, **k: sp.CompletedProcess(a, 0, stdout=SHA + "\n", stderr=""))
    assert pq.gh_head("windy-calendar", 130) == SHA and pq.gh_head("a;b", 1) is None

    def boom(*a, **k):
        raise OSError("no runuser")
    monkeypatch.setattr(pq.subprocess, "run", boom)
    assert pq.gh_head("windy-calendar", 130) is None
