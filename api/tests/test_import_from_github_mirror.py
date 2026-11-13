"""scripts/import_from_github.py --mirror (LASTING FIX after 2026-11-12): a pull mirror keeps its clone URL, token
included, in the Gitea repo config. So a mirror is made only for a repo GitHub serves WITHOUT a token, and no token
is ever sent for one; a private repo, or one whose visibility cannot be read, is refused with the safe path named."""

from __future__ import annotations

import importlib.util
import io
import json
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("import_from_github_t", ROOT / "scripts" / "import_from_github.py")
ig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ig)

FAKE = "gho" + "_FAKEimportTOKEN" + "0123456789abcdefgh"   # in pieces: the secret-literal invariant stays quiet


@pytest.fixture
def api(monkeypatch):
    calls = []

    def fake(method, path, body=None):
        calls.append((method, path, body))
        if method == "GET":
            return 404, {}
        return 201, {"size": 1}
    monkeypatch.setattr(ig, "_api", fake)
    monkeypatch.setattr(ig, "GITHUB_TOKEN", FAKE)
    return calls


def _posts(calls):
    return [c for c in calls if c[0] == "POST"]


@pytest.mark.parametrize("public, why", [(False, "private on GitHub"), (None, "GitHub visibility unreadable")])
def test_a_private_or_unknown_repo_is_refused_as_a_mirror_and_nothing_is_sent(api, monkeypatch, capsys, public, why):
    monkeypatch.setattr(ig, "github_is_public", lambda name: public)
    assert ig.import_repo("mortgagerecruiter", mirror=True) is False
    assert _posts(api) == []
    out = capsys.readouterr().out
    assert "REFUSED" in out and why in out and "SYNC_REPOS" in out and FAKE not in out


def test_a_public_mirror_is_made_without_any_token(api, monkeypatch):
    monkeypatch.setattr(ig, "github_is_public", lambda name: True)
    assert ig.import_repo("windy-git", mirror=True) is True
    (_, path, body), = _posts(api)
    assert path == "/repos/migrate" and body["mirror"] is True
    assert "auth_token" not in body and FAKE not in json.dumps(body)


def test_a_plain_import_still_sends_the_token(api, monkeypatch):
    monkeypatch.setattr(ig, "github_is_public", lambda name: pytest.fail("not asked for a plain import"))
    assert ig.import_repo("windy-chat", mirror=False) is True
    (_, _, body), = _posts(api)
    assert body["mirror"] is False and body["auth_token"] == FAKE


class _Resp(io.BytesIO):
    def __init__(self, status, body):
        super().__init__(json.dumps(body).encode())
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.mark.parametrize("answer, want", [
    (lambda: _Resp(200, {"private": False}), True),
    (lambda: _Resp(200, {"private": True}), False),
    (lambda: _Resp(200, {}), False),
    (lambda: (_ for _ in ()).throw(urllib.error.HTTPError("u", 404, "nf", {}, None)), False),
    (lambda: (_ for _ in ()).throw(urllib.error.HTTPError("u", 403, "rate", {}, None)), None),
    (lambda: (_ for _ in ()).throw(urllib.error.URLError("dns")), None),
])
def test_visibility_is_read_without_a_token(monkeypatch, answer, want):
    seen = {}

    def urlopen(req, timeout=None):
        seen["auth"] = req.get_header("Authorization")
        return answer()
    monkeypatch.setattr(ig.urllib.request, "urlopen", urlopen)
    assert ig.github_is_public("x") is want
    assert seen["auth"] is None
