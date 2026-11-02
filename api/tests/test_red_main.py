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
    assert "windy-git/secret-guard = failure" in due[0][1] and "Owner: Windy Mobile (mini)" in due[0][1]
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


def test_history_from_github_stops_at_the_last_green(monkeypatch):
    commits = [{"sha": c * 40} for c in "abcd"]
    status = {"a": "failure", "b": "error", "c": "success", "d": "failure"}           # c: the red began after it
    created = {"a": T0, "b": T0 - 5 * H, "c": T0 - 9 * H, "d": T0 - 20 * H}

    def github(method, path, body=None):
        if "/commits?sha=" in path:
            return 200, commits
        k = path.split("/commits/")[1][0]
        return 200, {"statuses": [_st("ci/x", status[k], created[k])]}
    monkeypatch.setattr(rm.b, "github", github)
    assert rm.history_from_github("r", "main")("r", "ci/x") == T0 - 5 * H


def test_a_corrupt_state_file_says_so(monkeypatch, tmp_path, capsys):
    f = tmp_path / "red.json"
    f.write_text("{not json")
    monkeypatch.setattr(rm, "STATE", f)
    assert rm.load() == {} and "state unreadable: clocks reset" in capsys.readouterr().out


def test_a_known_false_positive_carries_its_note_but_still_posts():
    due = rm.step({}, "windytalk", SHA, [_st("windy-git/secret-guard", "failure", T0 - 30 * H)], T0)
    assert len(due) == 1 and "likely header-only" in due[0][1] and "path + kind" in due[0][1]
