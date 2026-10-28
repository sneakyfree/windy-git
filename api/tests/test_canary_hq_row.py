"""canary.py's HQ row (Boss 10-28 (D), Admin's monitor_silent contract): one row per run, names
only, dark without Windy Git's own token."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("canary", ROOT / "scripts" / "canary.py")
cn = importlib.util.module_from_spec(_spec)
sys.modules["canary"] = cn          # dataclasses resolve their module by name
_spec.loader.exec_module(cn)


def _r(name, status):
    return cn.Result(name=name, status=status, detail="d")


def test_the_row_matches_admins_contract():
    body = cn.hq_row([_r("health", "ok"), _r("login", "down"), _r("jwks", "unknown")], "1234", 0, "a" * 32)
    (e,) = body["events"]
    assert (e["platform"], e["service"], e["event_type"], e["actor_type"]) == \
        ("windy-git", "login-canary", "service.health", "system")
    m = e["metadata"]
    assert m == {"ok": False, "checks": 3, "failed": ["login", "jwks"], "run": 1234,
                 "synthetic": True, "population": "synthetic", "event_id": "a" * 32}
    assert "actor_id" not in e
    assert cn.hq_row([_r("health", "ok")], None, 0, "b" * 32)["events"][0]["metadata"]["ok"] is True


def test_no_token_means_dark_and_nothing_is_sent(monkeypatch):
    monkeypatch.delenv("WINDY_GIT_HQ_INGEST_TOKEN", raising=False)
    sent = []
    monkeypatch.setattr(cn.urllib.request, "urlopen", lambda *a, **k: sent.append(1))
    assert cn.send_hq_row([_r("health", "ok")]) == "hq row: dark (no ingest token yet)" and sent == []
