"""Push-velocity detection (scripts/telemetry_emit.py): detect + alert only.

Driven through the real function with rows shaped like the Gitea query's.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("telemetry_emit", ROOT / "scripts" / "telemetry_emit.py")
te = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(te)

NOW = 1_800_000_000.0


def row(login="agent-et26abcd1234", uid=7, p1h=0, p24h=0, d24h=0, repos=1):
    return {"uid": uid, "login": login, "p1h": p1h, "p24h": p24h, "d24h": d24h, "repos": repos}


def test_under_every_threshold_emits_nothing():
    ev, keep = te.push_velocity_events([row(p1h=60, p24h=500, d24h=10)], NOW, {})
    assert ev == [] and keep == {}


def test_burst_emits_one_declared_row_with_the_passport():
    ev, keep = te.push_velocity_events([row(p1h=61, p24h=61, repos=3)], NOW, {})
    assert len(ev) == 1
    e = ev[0]
    assert e["event_type"] == "forge.push_velocity" and e["service"] == "forge"
    assert e["actor_type"] == "agent" and e["actor_id"] == "ET26-ABCD-1234"
    assert e["metadata"] == {
        "rule": "pushes_1h", "window_s": 3600, "count": 61, "threshold": 60,
        "repos": 3, "gitea_user_id": 7,
    }
    assert keep == {"7:pushes_1h": NOW}


def test_still_over_is_reported_once_per_window_not_every_run():
    _, keep = te.push_velocity_events([row(p1h=90)], NOW, {})
    ev, keep = te.push_velocity_events([row(p1h=95)], NOW + 300, keep)
    assert ev == [] and keep == {"7:pushes_1h": NOW}
    ev, _ = te.push_velocity_events([row(p1h=95)], NOW + 3601, keep)
    assert len(ev) == 1


def test_dropping_back_under_rearms():
    _, keep = te.push_velocity_events([row(p1h=90)], NOW, {})
    _, keep = te.push_velocity_events([row(p1h=5)], NOW + 300, keep)
    assert keep == {}
    ev, _ = te.push_velocity_events([row(p1h=90)], NOW + 600, keep)
    assert len(ev) == 1


def test_the_sync_account_is_exempt():
    ev, _ = te.push_velocity_events([row(login="windyadmin", uid=1, p1h=9999, p24h=9999)], NOW, {})
    assert ev == []


def test_human_rows_carry_no_invented_actor_id():
    ev, _ = te.push_velocity_events([row(login="u-5e1b9569abc", d24h=11)], NOW, {})
    assert [(e["actor_type"], e["metadata"]["rule"]) for e in ev] == [("human", "ref_deletes_24h")]
    assert "actor_id" not in ev[0]


def test_unparseable_agent_login_keeps_agent_type_without_actor_id():
    ev, _ = te.push_velocity_events([row(login="agent-weird", p24h=501)], NOW, {})
    assert ev[0]["actor_type"] == "agent" and "actor_id" not in ev[0]


def test_passport_round_trip():
    assert te.passport_from_login("agent-et26p1zgttp8") == "ET26-P1ZG-TTP8"
    assert te.passport_from_login("u-abc") is None
