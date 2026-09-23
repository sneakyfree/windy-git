"""Field telemetry from the API (step 2): behavioural, no network.

A refusal must become exactly one forge.auth.failed row in the DECLARED shape
(the ledger quarantines anything else); non-refusal errors must not; the
heartbeat must count what happened and never invent a p95 for no traffic.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import Depends, FastAPI

from api.app import telemetry as tmod
from api.app.errors import RepairPointer

DECLARED_AUTH_KEYS = {"code", "http_status", "caller", "route", "upstream_status"}


def _app(tel: tmod.Telemetry) -> FastAPI:
    """The real middleware + handler, re-registered on a bare app (no DB)."""
    from api.app import main

    app = FastAPI()
    app.state.telemetry = tel
    app.middleware("http")(main._count_requests)
    app.exception_handler(RepairPointer)(main._repair_pointer_handler)

    def refuse(code: str, status: int):
        def dep():
            raise RepairPointer(
                status_code=status,
                code=code,
                speak="no",
                machine_cause="test",
                remediation_tool=None,
            )

        return dep

    @app.get("/api/v1/repos/{repo}/grants", dependencies=[Depends(refuse("passport_revoked", 403))])
    async def grants(repo: str):
        return {}

    @app.get("/api/v1/nope", dependencies=[Depends(refuse("repo_not_found", 404))])
    async def nope():
        return {}

    @app.get("/ok")
    async def ok():
        return {"ok": True}

    return app


async def _get(app, path, headers=None):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(path, headers=headers or {})


def _tel():
    return tmod.Telemetry(
        "http://ledger.invalid/v1/events",
        "tok",
        environment="test",
        commit_sha="abc1234",
        version="0.1.0",
    )


@pytest.mark.asyncio
async def test_refusal_emits_one_declared_row_with_route_template_not_path():
    tel = _tel()
    r = await _get(
        _app(tel),
        "/api/v1/repos/grandmas-secret-project/grants",
        {"Authorization": "Bearer eyJhbGciOiJFUzI1NiIsInR5cCI6IkVQVCJ9.e30.x"},
    )
    assert r.status_code == 403
    rows = [e for e in tel.buffer if e["event_type"] == "forge.auth.failed"]
    assert len(rows) == 1
    row = rows[0]
    assert row["actor_type"] == "system" and "actor_id" not in row
    assert set(row["metadata"]) <= DECLARED_AUTH_KEYS
    assert row["metadata"]["code"] == "passport_revoked"
    assert row["metadata"]["http_status"] == 403
    assert row["metadata"]["caller"] == "anonymous_agent"
    assert row["metadata"]["route"] == "/api/v1/repos/{repo}/grants"
    assert "grandmas-secret-project" not in str(row)


@pytest.mark.asyncio
async def test_non_auth_errors_are_counted_but_not_refusal_rows():
    tel = _tel()
    await _get(_app(tel), "/api/v1/nope")
    assert not [e for e in tel.buffer if e["event_type"] == "forge.auth.failed"]
    assert tel.errors_4xx == 1 and tel.refusals_4xx == 0


@pytest.mark.asyncio
async def test_heartbeat_counts_requests_refusals_and_p95():
    tel = _tel()
    app = _app(tel)
    for _ in range(3):
        await _get(app, "/ok")
    await _get(app, "/api/v1/repos/x/grants")
    meta = tel.health_row()
    assert meta["requests"] == 4 and meta["refusals_4xx"] == 1 and meta["errors_5xx"] == 0
    assert isinstance(meta["p95_ms"], int)
    assert {"interval_s", "uptime_s"} <= set(meta)


def test_no_traffic_means_no_p95_not_a_fake_zero():
    assert "p95_ms" not in _tel().health_row()


def test_no_token_sends_and_buffers_nothing():
    tel = tmod.Telemetry("http://ledger.invalid", "")
    tel.boot()
    tel.auth_failed(code="token_invalid", http_status=401, caller="unknown")
    assert tel.buffer == []


def test_unknown_code_is_never_sent_as_a_refusal():
    tel = _tel()
    tel.auth_failed(code="made_up_code", http_status=401, caller="unknown")
    assert tel.buffer == []


def test_boot_omits_an_unknown_commit_rather_than_inventing_one():
    tel = tmod.Telemetry("http://x", "tok", commit_sha=None, version="0.1.0")
    tel.boot()
    assert "commit_sha" not in tel.buffer[0]["metadata"]


def test_caller_classes_are_the_declared_three():
    assert tmod.caller_class({}) == "unknown"
    assert tmod.caller_class({"x-service-token": "s"}) == "unknown"
    assert (
        tmod.caller_class({"authorization": "Bearer eyJhbGciOiJSUzI1NiJ9.e30.x"})
        == "anonymous_human"
    )
