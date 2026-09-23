"""The canary's login probe must end the session it opens (journey cleanup rule)."""

from __future__ import annotations

import importlib.util
import io
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("canary", ROOT / "scripts" / "canary.py")
canary = importlib.util.module_from_spec(_spec)
sys.modules["canary"] = canary  # dataclasses resolve their module by name
_spec.loader.exec_module(canary)


class _Resp:
    def __init__(self, status=200, body=b"{}"):
        self.status, self._body = status, body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _err(code):
    return urllib.error.HTTPError(canary.LOGOUT_URL, code, "x", {}, io.BytesIO(b""))


def _script(monkeypatch, outcomes):
    calls = []

    def fake(req, timeout=None):
        calls.append((req.get_method(), req.full_url, req.get_header("Authorization")))
        o = outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return o

    monkeypatch.setattr(canary.urllib.request, "urlopen", fake)
    return calls


def test_logout_ends_the_session(monkeypatch):
    calls = _script(monkeypatch, [_Resp(200)])
    r = canary.logout("tok", sleep=lambda s: None)
    assert r.status == "ok"
    assert calls == [("POST", canary.LOGOUT_URL, "Bearer tok")]


def test_5xx_and_no_response_are_retried_then_succeed(monkeypatch):
    calls = _script(monkeypatch, [_err(502), OSError("reset"), _Resp(200)])
    assert canary.logout("tok", sleep=lambda s: None).status == "ok"
    assert len(calls) == 3


def test_already_over_counts_as_done(monkeypatch):
    _script(monkeypatch, [_err(401)])
    assert canary.logout("tok", sleep=lambda s: None).status == "ok"


def test_other_4xx_fails_fast_and_honestly(monkeypatch):
    calls = _script(monkeypatch, [_err(400)])
    r = canary.logout("tok", sleep=lambda s: None)
    assert r.status == "down" and r.detail.startswith("CLEANUP FAILED") and len(calls) == 1


def test_retries_are_bounded_and_reported(monkeypatch):
    calls = _script(monkeypatch, [_err(503)] * 8)
    r = canary.logout("tok", attempts=8, sleep=lambda s: None)
    assert r.status == "down" and "CLEANUP FAILED after 8 tries" in r.detail and len(calls) == 8


def test_login_probe_logs_out_with_the_token_it_got(monkeypatch):
    calls = _script(monkeypatch, [_Resp(200, b'{"token": "abc"}'), _Resp(200)])
    c = canary.Check("identity.login", "https://account.windyword.ai/api/v1/auth/login", "x",
                     method="POST", body={"email": "e", "password": "p"},
                     after=canary._logout_after_login)
    r = canary._probe(c)
    assert r.status == "ok" and [f.status for f in r.followups] == ["ok"]
    assert calls[1] == ("POST", canary.LOGOUT_URL, "Bearer abc")


def test_login_without_token_is_a_cleanup_failure_not_a_pass():
    [f] = canary._logout_after_login(b"{}")
    assert f.status == "down" and "CLEANUP FAILED" in f.detail
