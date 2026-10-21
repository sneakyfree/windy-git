"""scripts/github_has_commit.py: only a GitHub 'yes' (exit 0) lets the sync delete a branch."""

from __future__ import annotations

import importlib.util
import io
import json
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("github_has_commit", ROOT / "scripts" / "github_has_commit.py")
hc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hc)

SHA = "a" * 40


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def answer(monkeypatch, payload=None, exc=None, seen=None):
    def fake(req, timeout=0):
        if seen is not None:
            seen.append(json.loads(req.data))
        if exc:
            raise exc
        return _Resp(json.dumps(payload).encode())
    monkeypatch.setattr(hc.urllib.request, "urlopen", fake)
    monkeypatch.setenv("GITHUB_TOKEN", "t")


def test_yes_when_github_returns_the_object(monkeypatch):
    seen = []
    answer(monkeypatch, {"data": {"repository": {"object": {"oid": SHA}}}}, seen=seen)
    assert hc.main(["windy-pro", SHA]) == 0
    assert seen[0]["variables"] == {"o": "sneakyfree", "n": "windy-pro", "s": SHA}
    assert "graphql" in hc.API


def test_no_when_the_repo_answers_without_the_object(monkeypatch):
    answer(monkeypatch, {"data": {"repository": {"object": None}}})
    assert hc.main(["windy-pro", SHA]) == 1


def test_cannot_tell_on_errors_unreadable_repo_or_transport(monkeypatch):
    answer(monkeypatch, {"data": {"repository": None}})
    assert hc.main(["windy-pro", SHA]) == 2
    answer(monkeypatch, {"errors": [{"message": "rate limited"}]})
    assert hc.main(["windy-pro", SHA]) == 2
    answer(monkeypatch, exc=urllib.error.URLError("down"))
    assert hc.main(["windy-pro", SHA]) == 2


def test_bad_input_or_no_token_cannot_tell(monkeypatch):
    answer(monkeypatch, {"data": {"repository": {"object": {"oid": SHA}}}})
    assert hc.main(["windy-pro", "nothex"]) == 2
    assert hc.main(['bad"name', SHA]) == 2
    monkeypatch.delenv("GITHUB_TOKEN")
    assert hc.main(["windy-pro", SHA]) == 2


def test_an_empty_github_graphql_url_from_ci_is_ignored(monkeypatch):
    # Gitea/GitHub runners export GITHUB_GRAPHQL_URL, sometimes empty: it must not be used.
    monkeypatch.setenv("GITHUB_GRAPHQL_URL", "")
    spec = importlib.util.spec_from_file_location("ghc_env", ROOT / "scripts" / "github_has_commit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.API == "https://api.github.com/graphql"


def test_a_bad_url_is_cannot_tell_not_a_crash(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setattr(hc, "API", "")
    assert hc.main(["windy-pro", SHA]) == 2
