"""scripts/red_main.py: a default-branch status red for more than 24 h gets ONE BOARD line, then daily
(Boss 11-02, after windy-pro-mobile's main was red on secret-guard for 13 days unseen)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("red_main", ROOT / "scripts" / "red_main.py")
rm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rm)

H = 3600
T0 = 1_800_000_000.0
SHA = "a" * 40


def _st(ctx, state, created=T0):
    from datetime import UTC, datetime
    return {"context": ctx, "state": state, "created_at": datetime.fromtimestamp(created, UTC).isoformat()}


def test_a_red_context_alarms_only_after_24_h_then_once_a_day():
    state: dict = {}
    reds = [_st("windy-git/secret-guard", "failure")]
    assert rm.step(state, "windy-pro-mobile", SHA, reds, T0 + 23 * H) == []          # not yet a day
    due = rm.step(state, "windy-pro-mobile", SHA, reds, T0 + 25 * H)
    assert len(due) == 1 and "RED MAIN: windy-pro-mobile" in due[0][1]
    assert "windy-git/secret-guard = failure" in due[0][1] and "Owner: Windy Fly Mobile" in due[0][1]
    state["reds"][due[0][0]]["last_post"] = T0 + 25 * H                               # main() does this on a confirmed post
    assert rm.step(state, "windy-pro-mobile", SHA, reds, T0 + 30 * H) == []          # once a day
    assert len(rm.step(state, "windy-pro-mobile", SHA, reds, T0 + 49 * H)) == 1       # the next day


def test_the_clock_starts_at_the_failing_status_not_at_first_sight():
    """First sight of a long-red main (13 days, as found) alarms at once, not a day later."""
    state: dict = {}
    due = rm.step(state, "windy-pro-mobile", SHA, [_st("windy-git/secret-guard", "error", T0 - 13 * 24 * H)], T0)
    assert len(due) == 1 and "(312 h)" in due[0][1]


def test_success_clears_pending_keeps_and_a_new_head_keeps_the_clock():
    state: dict = {}
    rm.step(state, "r", SHA, [_st("ci/test", "failure")], T0)
    rm.step(state, "r", "b" * 40, [_st("ci/test", "pending")], T0 + 10 * H)         # a re-run: still the same red
    assert "r|ci/test" in state["reds"] and state["reds"]["r|ci/test"]["since"] == T0
    rm.step(state, "r", "b" * 40, [_st("ci/test", "success")], T0 + 11 * H)
    assert "r|ci/test" not in state["reds"]


def test_only_the_newest_status_per_context_counts():
    state: dict = {}
    newest_first = [_st("ci/test", "success"), _st("ci/test", "failure", T0 - 48 * H)]
    assert rm.step(state, "r", SHA, newest_first, T0) == [] and state["reds"] == {}


def test_every_bridged_repo_has_an_owner_or_says_unknown():
    missing = [r for r in rm.b.REPOS if r not in rm.OWNERS]
    due = rm.step({}, "some-new-repo", SHA, [_st("ci/x", "failure", T0 - 30 * H)], T0)
    assert "Owner: unknown (Boss routes)" in due[0][1]
    assert rm.OWNERS["windy-mind"] == "Windy Mind"                                    # not gr.OWNERS' "WIndy Mind"
    assert set(missing) <= {"windy-contracts"}, missing        # the one owner not known for sure


def _fake(monkeypatch, tmp_path, budget, statuses):
    monkeypatch.setattr(rm, "STATE", tmp_path / "red.json")
    monkeypatch.setattr(rm.b, "REPOS", ["windy-pro-mobile"])
    calls = []

    def github(method, path, body=None):
        calls.append(path)
        if path == "/rate_limit":
            return 200, {"resources": {"core": {"remaining": budget}}}
        if path == "/repos/sneakyfree/windy-pro-mobile":
            return 200, {"default_branch": "main"}
        if path.endswith("/branches/main"):
            return 200, {"commit": {"sha": SHA}}
        if path.endswith(f"/commits/{SHA}/status?per_page=100"):
            return 200, {"statuses": statuses}
        return 404, {}
    monkeypatch.setattr(rm.b, "github", github)
    return calls


def test_main_posts_once_and_writes_its_state(monkeypatch, tmp_path, capsys):
    _fake(monkeypatch, tmp_path, 4000, [_st("windy-git/secret-guard", "failure", 1.0)])
    posts = []
    ok = lambda line: posts.append(line) or True  # noqa: E731  (a confirmed BOARD write)
    rm.main(post=ok)
    out = capsys.readouterr().out
    assert len(posts) == 1 and "red main: 1 red > 24 h (BOARD)" in out
    assert "windy-pro-mobile|windy-git/secret-guard" in json.loads((tmp_path / "red.json").read_text())["reds"]
    rm.main(post=ok)
    assert len(posts) == 1                                                            # not again the same day


def test_main_reads_nothing_under_the_budget_floor(monkeypatch, tmp_path, capsys):
    calls = _fake(monkeypatch, tmp_path, 1499, [])
    rm.main(post=lambda line: None)
    assert calls == ["/rate_limit"] and "red main: skipped" in capsys.readouterr().out



def test_a_lost_board_post_is_retried_and_the_heartbeat_goes_red(monkeypatch, tmp_path, capsys):
    """Hub #112: last_post only after a CONFIRMED write; a lost one is said and retried."""
    import re
    _fake(monkeypatch, tmp_path, 4000, [_st("windy-git/secret-guard", "failure", 1.0)])
    rm.main(post=lambda line: False)
    out = capsys.readouterr().out
    unit = (ROOT / "deploy" / "systemd" / "windygit-red-main.service").read_text()
    pattern = re.search(r'--expect "([^"]+)"', unit).group(1)
    assert "\\" not in pattern                                                        # no systemd unescaping to get wrong
    expect = re.compile(pattern)                                                      # the service's own --expect
    assert expect.search("red main: none") and expect.search("red main: 2 red > 24 h (BOARD)")
    last = out.strip().splitlines()[-1]
    assert "BOARD post FAILED" in out and not expect.search(last) and "BOARD post failed" in last
    assert json.loads((tmp_path / "red.json").read_text())["reds"]["windy-pro-mobile|windy-git/secret-guard"]["last_post"] == 0.0
    posts = []
    rm.main(post=lambda line: posts.append(line) or True)
    assert len(posts) == 1                                                            # retried at once


def test_a_context_gone_from_the_head_is_not_counted_and_is_dropped_after_7_days():
    """Hub #112: a stored clock alone is not a red (renamed context, removed workflow, unbridged repo)."""
    state: dict = {}
    rm.step(state, "r", SHA, [_st("ci/old", "failure", T0 - 30 * H)], T0)
    assert rm.red_count(state, T0) == 1
    assert rm.step(state, "r", "b" * 40, [_st("ci/new", "success")], T0 + 2 * H) == []
    assert rm.red_count(state, T0 + 2 * H) == 0                                      # not seen this run
    assert rm.prune(state, T0 + 6 * 86400) == [] and "r|ci/old" in state["reds"]
    assert rm.prune(state, T0 + 8 * 86400) == ["r|ci/old"] and state["reds"] == {}


def test_first_sight_backfills_the_red_from_older_commits():
    """Boss 11-02: windy-pro-mobile counts from its FIRST red, not from today's head."""
    state: dict = {}
    due = rm.step(state, "windy-pro-mobile", SHA, [_st("windy-git/secret-guard", "failure", T0 - 1 * H)], T0,
                  history=lambda repo, ctx: T0 - 13 * 24 * H)
    assert state["reds"]["windy-pro-mobile|windy-git/secret-guard"]["since"] == T0 - 13 * 24 * H
    assert len(due) == 1 and "(312 h)" in due[0][1]


def _history(monkeypatch, commits, status, created):
    def github(method, path, body=None):
        if "/commits?sha=" in path:
            return 200, commits
        k = path.split("/commits/")[1][0]
        return 200, {"statuses": [_st("ci/x", status[k], created[k])]}
    monkeypatch.setattr(rm.b, "github", github)
    return rm.history_from_github("r", "main")("r", "ci/x")


def _c(sha, *parents):
    return {"sha": sha * 40, "parents": [{"sha": p * 40} for p in parents]}


def test_a_squash_main_stops_at_the_last_green(monkeypatch):
    """Linear main (squash merges): a <- b <- c(green) <- d. The red began after c."""
    commits = [_c("a", "b"), _c("b", "c"), _c("c", "d"), _c("d")]
    status = {"a": "failure", "b": "error", "c": "success", "d": "failure"}
    created = {"a": T0, "b": T0 - 5 * H, "c": T0 - 9 * H, "d": T0 - 20 * H}
    assert _history(monkeypatch, commits, status, created) == (T0 - 5 * H, True)


def test_a_merge_whose_pr_side_is_green_does_not_reset_the_clock(monkeypatch):
    """Boss 11-02, windy-pro-mobile a1aeb83a: merge m has parents [p (main, red), q (PR head, green in
    PR mode)]. GitHub lists q between m and p; first-parent history skips it."""
    commits = [_c("m", "p", "q"), _c("q", "o"), _c("p", "o"), _c("o", "n"), _c("n")]
    status = {"m": "failure", "q": "success", "p": "failure", "o": "failure", "n": "success"}
    created = {"m": T0, "q": T0 - 1 * H, "p": T0 - 30 * H, "o": T0 - 60 * H, "n": T0 - 90 * H}
    assert rm.first_parent_chain(commits, "m" * 40, 30) == ["m" * 40, "p" * 40, "o" * 40, "n" * 40]
    assert _history(monkeypatch, commits, status, created) == (T0 - 60 * H, True)  # from o, not reset by q


def test_the_chain_continues_onto_the_next_page_when_a_pr_branch_fills_this_one(monkeypatch):
    """windy-pro-mobile (live, 11-02): the first-parent chain left page 1 after 8 commits, all red."""
    page1 = [_c("m", "p", "q"), _c("q", "x"), _c("p", "o")]                         # o's commit is not on page 1
    page2 = [_c("o", "n"), _c("n")]
    status = {"m": "failure", "q": "success", "p": "failure", "o": "failure", "n": "success", "x": "success"}
    created = {"m": T0, "q": T0, "p": T0 - 10 * H, "o": T0 - 50 * H, "n": T0 - 99 * H, "x": T0}
    asked = []

    def github(method, path, body=None):
        if "/commits?sha=" in path:
            asked.append(path.split("sha=")[1].split("&")[0][:1])
            return 200, (page1 if path.split("sha=")[1].startswith("main") else page2)
        k = path.split("/commits/")[1][0]
        return 200, {"statuses": [_st("ci/x", status[k], created[k])]}
    monkeypatch.setattr(rm.b, "github", github)
    assert rm.history_from_github("r", "main")("r", "ci/x") == (T0 - 50 * H, True)
    assert asked == ["m", "o"]                                                          # page 2 starts at o


def test_a_walk_ended_by_a_limit_is_a_lower_bound_and_says_at_least(monkeypatch):
    monkeypatch.setattr(rm, "HISTORY_MAX", 2)
    commits = [_c("a", "b"), _c("b", "c"), _c("c")]
    got = _history(monkeypatch, commits, {"a": "failure", "b": "failure", "c": "failure"},
                   {"a": T0, "b": T0 - 40 * H, "c": T0 - 80 * H})
    assert got == (T0 - 40 * H, False)
    due = rm.step({}, "r", SHA, [_st("ci/x", "failure", T0)], T0 + H, history=lambda repo, ctx: got)
    assert "since at least" in due[0][1]


def test_a_corrupt_state_file_says_so(monkeypatch, tmp_path, capsys):
    f = tmp_path / "red.json"
    f.write_text("{not json")
    monkeypatch.setattr(rm, "STATE", f)
    assert rm.load() == {} and "state unreadable: clocks reset" in capsys.readouterr().out


def test_a_known_false_positive_carries_its_note_but_still_posts():
    due = rm.step({}, "windytalk", SHA, [_st("windy-git/secret-guard", "failure", T0 - 30 * H)], T0)
    assert len(due) == 1 and "likely header-only" in due[0][1] and "path + kind" in due[0][1]



def test_an_unreadable_backfill_is_inexact_not_exact(monkeypatch):
    """Hub #112: GitHub 502 on the history walk -> the head's own time, but "since at least"."""
    monkeypatch.setattr(rm.b, "github", lambda m, p, body=None: (502, {}))
    got = rm.history_from_github("r", "main")("r", "ci/x")
    assert got == (None, False)
    state: dict = {}
    due = rm.step(state, "r", SHA, [_st("ci/x", "failure", T0 - 30 * H)], T0, history=lambda repo, ctx: got)
    assert state["reds"]["r|ci/x"]["since"] == T0 - 30 * H and "since at least" in due[0][1]


# --- the known-red exemption (Boss 11-04): windy-pro's account-server-on-Postgres suite -------------------------

PG = "windy-git/account-server-pg/test-account-server-pg"


def _utc(iso):
    from datetime import datetime
    return datetime.fromisoformat(iso).timestamp()


def test_the_exemption_is_exactly_one_context_with_a_pinned_expiry():
    """The name and the date are pinned: widening the list or moving the date must fail here and be read."""
    assert rm.EXEMPT == {("windy-pro", PG): "2026-11-30"}
    # the bridge builds this context from the workflow FILE name (account-server-pg.yml) and the job name
    assert PG == "windy-git/" + "account-server-pg" + "/" + "test-account-server-pg"


def test_the_exempt_red_never_alarms_while_the_exemption_lasts_including_its_last_day():
    state: dict = {}
    red = [_st(PG, "failure", _utc("2026-11-03T00:00:00+00:00"))]
    for when in ("2026-11-05T12:00:00+00:00", "2026-11-20T00:00:00+00:00", "2026-11-30T23:59:00+00:00"):
        assert rm.step(state, "windy-pro", SHA, red, _utc(when)) == []
    assert state.get("reds", {}) == {} and rm.red_count(state, _utc("2026-11-30T23:59:00+00:00")) == 0


def test_the_exempt_red_alarms_again_from_the_first_day_after_the_expiry():
    state: dict = {}
    red = [_st(PG, "failure", _utc("2026-11-03T00:00:00+00:00"))]
    assert rm.step(state, "windy-pro", SHA, red, _utc("2026-11-30T23:59:00+00:00")) == []
    due = rm.step(state, "windy-pro", SHA, red, _utc("2026-12-01T00:00:00+00:00"))
    assert len(due) == 1 and PG in due[0][1] and "RED MAIN: windy-pro" in due[0][1]


def test_every_other_windy_pro_context_still_alarms_beside_the_exempt_one():
    state: dict = {}
    now = _utc("2026-11-10T12:00:00+00:00")
    old = _utc("2026-11-03T00:00:00+00:00")
    statuses = [_st(PG, "failure", old), _st("windy-git/ci/gates", "failure", old),
                _st("windy-git/ci/test-account-server", "failure", old)]
    due = rm.step(state, "windy-pro", SHA, statuses, now)
    assert sorted(k for k, _ in due) == ["windy-pro|windy-git/ci/gates", "windy-pro|windy-git/ci/test-account-server"]
    assert rm.red_count(state, now) == 2


def test_the_same_context_name_in_another_repo_is_not_exempt_and_nor_are_look_alike_names():
    now = _utc("2026-11-10T12:00:00+00:00")
    old = _utc("2026-11-03T00:00:00+00:00")
    assert len(rm.step({}, "windy-pro-mobile", SHA, [_st(PG, "failure", old)], now)) == 1
    for ctx in ("windy-git/ci/test-account-server-pg",            # the name it had in ci.yml: not the one that exists now
                "windy-git/account-server-pg/test-account-server-pg-2", "windy-git/account-server-pg"):
        assert len(rm.step({}, "windy-pro", SHA, [_st(ctx, "failure", old)], now)) == 1, ctx


def test_main_stays_silent_about_the_exempt_red_and_counts_none(monkeypatch, tmp_path, capsys):
    _fake(monkeypatch, tmp_path, 4000, [_st(PG, "failure", 1.0)])
    monkeypatch.setattr(rm.b, "REPOS", ["windy-pro"])
    monkeypatch.setattr(rm.b, "github", lambda m, p, body=None: (
        (200, {"resources": {"core": {"remaining": 4000}}}) if p == "/rate_limit" else
        (200, {"default_branch": "main"}) if p == "/repos/sneakyfree/windy-pro" else
        (200, {"commit": {"sha": SHA}}) if p.endswith("/branches/main") else
        (200, {"statuses": [_st(PG, "failure", 1.0)]}) if p.endswith(f"/commits/{SHA}/status?per_page=100") else (404, {})))
    import time as _time
    import types
    monkeypatch.setattr(rm, "time", types.SimpleNamespace(
        time=lambda: _utc("2026-11-10T12:00:00+00:00"), strftime=_time.strftime, gmtime=_time.gmtime))
    posts = []
    rm.main(post=lambda line: posts.append(line) or True)
    assert posts == [] and capsys.readouterr().out.strip().splitlines()[-1] == "red main: none"
