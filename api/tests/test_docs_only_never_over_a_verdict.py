"""The bridge never paints a docs-only skip over a real verdict already on GitHub (Hub 2026-11-13T17:33:28Z, for
the DOCS-ONLY ON ask): a PR-kind skip and a push-kind run of one sha share the context name."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("pr_status_bridge_nov", ROOT / "scripts" / "pr_status_bridge.py")
bridge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bridge)

SHA = "b" * 40
CTX = "windy-git/ci/test"


class GH:
    def __init__(self, statuses=()):
        self.statuses, self.posted = list(statuses), []

    def gitea(self, method, path, body=None):
        if "/contents/" in path:
            return 404, None
        if "/actions/tasks" in path:
            return 200, {"workflow_runs": []}           # the real run fell out of the 250-run window
        raise AssertionError(path)

    def github(self, method, path, body=None):
        if method == "GET":
            return 200, self.statuses
        self.posted.append(body)
        return 201, {}


@pytest.fixture
def gh(monkeypatch):
    def make(statuses=()):
        f = GH(statuses)
        bridge._RUNS_CACHE.clear()
        bridge._STATUSES_CACHE.clear()
        monkeypatch.setattr(bridge, "gitea", f.gitea)
        monkeypatch.setattr(bridge, "github", f.github)
        monkeypatch.setattr(bridge, "queued_jobs", lambda repo, sha: [])
        monkeypatch.setattr(bridge, "docs_only_contexts", lambda repo, sha: [{"context": CTX, "run": 7}])
        return f
    return make


def test_a_red_push_verdict_on_github_is_never_painted_green_by_a_skip(gh):
    f = gh([{"context": CTX, "state": "failure", "description": "Windy Git CI on Veron 1: failure"}])
    bridge.post_statuses("windy-chat", SHA)
    assert f.posted == []


@pytest.mark.parametrize("state", ["success", "pending", "error"])
def test_no_real_verdict_of_any_state_is_replaced_by_a_skip(gh, state):
    f = gh([{"context": CTX, "state": state, "description": f"Windy Git CI on Veron 1: {state}"}])
    bridge.post_statuses("windy-chat", SHA)
    assert f.posted == []


def test_a_skip_still_paints_where_github_shows_nothing_and_stays_put(gh):
    f = gh([])
    bridge.post_statuses("windy-chat", SHA)
    assert [(p["context"], p["state"], p["description"]) for p in f.posted] == [
        (CTX, "success", bridge.DOCS_ONLY_DESC)]
    f = gh([{"context": CTX, "state": "success", "description": bridge.DOCS_ONLY_DESC}])
    bridge.post_statuses("windy-chat", SHA)
    assert f.posted == []                                 # already the skip: nothing posted again
