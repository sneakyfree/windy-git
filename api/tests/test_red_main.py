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
    lines = rm.step(state, "windy-pro-mobile", SHA, reds, T0 + 25 * H)
    assert len(lines) == 1 and "RED MAIN: windy-pro-mobile" in lines[0]
    assert "windy-git/secret-guard = failure" in lines[0] and "Owner: Windy Mobile (mini)" in lines[0]
    assert rm.step(state, "windy-pro-mobile", SHA, reds, T0 + 30 * H) == []          # once a day
    assert len(rm.step(state, "windy-pro-mobile", SHA, reds, T0 + 49 * H)) == 1       # the next day


def test_the_clock_starts_at_the_failing_status_not_at_first_sight():
    """First sight of a long-red main (13 days, as found) alarms at once, not a day later."""
    state: dict = {}
    lines = rm.step(state, "windy-pro-mobile", SHA, [_st("windy-git/secret-guard", "error", T0 - 13 * 24 * H)], T0)
    assert len(lines) == 1 and "(312 h)" in lines[0]


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
    lines = rm.step({}, "some-new-repo", SHA, [_st("ci/x", "failure", T0 - 30 * H)], T0)
    assert "Owner: unknown (Boss routes)" in lines[0]
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
    rm.main(post=posts.append)
    out = capsys.readouterr().out
    assert len(posts) == 1 and "red main: 1 red > 24 h (BOARD)" in out
    assert "windy-pro-mobile|windy-git/secret-guard" in json.loads((tmp_path / "red.json").read_text())["reds"]
    rm.main(post=posts.append)
    assert len(posts) == 1                                                            # not again the same day


def test_main_reads_nothing_under_the_budget_floor(monkeypatch, tmp_path, capsys):
    calls = _fake(monkeypatch, tmp_path, 1499, [])
    rm.main(post=lambda line: None)
    assert calls == ["/rate_limit"] and "red main: skipped" in capsys.readouterr().out
