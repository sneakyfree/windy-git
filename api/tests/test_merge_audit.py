"""scripts/merge_audit.py, driven against a fake GitHub API (no network)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("merge_audit", ROOT / "scripts" / "merge_audit.py")
ma = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ma)

SINCE = "2026-10-11T00:00:00Z"
OK = [{"context": "windy-hub/approved", "state": "success"},
      {"context": "windy-git/check/gate", "state": "success"}]


def fake(commits, pulls, statuses):
    def api(path):
        if "/commits?sha=main" in path:
            return commits
        if path.endswith("/pulls"):
            return pulls.get(path.split("/commits/")[1].split("/")[0], [])
        if "/statuses" in path:
            return statuses.get(path.split("/commits/")[1].split("/")[0], [])
        raise AssertionError(path)
    return api


def pr(n, head, merged="2026-10-11T01:00:00Z"):
    return {"number": n, "merged_at": merged, "head": {"sha": head}}


def test_approved_and_green_merge_passes():
    api = fake([{"sha": "m1"}, {"sha": "c1"}], {"m1": [pr(5, "h5")], "c1": [pr(5, "h5")]}, {"h5": OK})
    assert ma.audit("windy-vault", SINCE, api) == (1, [])  # two commits, one PR, counted once


def test_missing_approval_is_flagged():
    api = fake([{"sha": "m1"}], {"m1": [pr(6, "h6")]},
               {"h6": [{"context": "windy-git/check/gate", "state": "success"}]})
    merged, flags = ma.audit("windy-contracts", SINCE, api)
    assert merged == 1 and len(flags) == 1 and "no windy-hub/approved=success" in flags[0]


def test_red_or_missing_check_is_flagged():
    red = fake([{"sha": "m1"}], {"m1": [pr(7, "h7")]},
               {"h7": [{"context": "windy-hub/approved", "state": "success"},
                       {"context": "windy-git/check/gate", "state": "failure"}]})
    none = fake([{"sha": "m1"}], {"m1": [pr(8, "h8")]},
                {"h8": [{"context": "windy-hub/approved", "state": "success"}]})
    assert "not green: windy-git/check/gate" in ma.audit("r", SINCE, red)[1][0]
    assert "no windy-git/check status" in ma.audit("r", SINCE, none)[1][0]


def test_latest_status_wins_newest_first():
    # an old failure superseded by a newer success is green; a withdrawn approval is not
    states = ma.latest_states([{"context": "windy-git/check/gate", "state": "success"},
                               {"context": "windy-git/check/gate", "state": "failure"},
                               {"context": "windy-hub/approved", "state": "failure"},
                               {"context": "windy-hub/approved", "state": "success"}])
    assert states == {"windy-git/check/gate": "success", "windy-hub/approved": "failure"}


def test_direct_push_is_flagged():
    api = fake([{"sha": "d1"}], {}, {})
    merged, flags = ma.audit("windy-vault", SINCE, api)
    assert merged == 0 and "direct push" in flags[0]


def test_merges_before_the_rule_are_not_judged():
    api = fake([{"sha": "m1"}], {"m1": [pr(9, "h9", merged="2026-10-10T20:00:00Z")]}, {"h9": []})
    assert ma.audit("windy-vault", SINCE, api) == (0, [])
