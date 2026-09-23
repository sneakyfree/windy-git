"""G3.5 — the Eternitas webhook receiver, driven over HTTP (audit 2026-08-13).

The G3.5 invariants in test_invariants.py grep webhooks.py for strings; a
refactor that kept the strings and broke the behaviour would pass them all.
These send real requests through the real route (no DB: every case here stops
before the revocation handler) and assert what the receiver DOES.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from api.app.config import Settings
from api.app.errors import RepairPointer
from api.app.routes import webhooks

SECRET = "s" * 64
URL = "/api/v1/webhooks/eternitas"


def _app(secret: str = SECRET) -> FastAPI:
    app = FastAPI()
    app.include_router(webhooks.router)
    app.state.settings = Settings(eternitas_webhook_secret=secret)

    @app.exception_handler(RepairPointer)
    async def _h(_, exc: RepairPointer) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)

    return app


async def _post(body: bytes, headers: dict, secret: str = SECRET) -> httpx.Response:
    transport = httpx.ASGITransport(app=_app(secret))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        return await c.post(
            URL, content=body, headers={"content-type": "application/json", **headers}
        )


def _sig(raw: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


# Deliberately odd spacing/key order: a receiver that re-serialises before
# hashing produces a different digest and must fail.
RAW = b'{"event":"windygit.selftest",  "data": {"b": 2, "a": 1}}'
EVENT = {"x-eternitas-event": "windygit.selftest"}


@pytest.mark.asyncio
async def test_prefixed_and_bare_digests_are_both_accepted():
    for header in (f"sha256={_sig(RAW)}", _sig(RAW)):
        r = await _post(RAW, {**EVENT, "x-eternitas-signature": header})
        assert r.status_code == 200, r.text
        assert r.json()["acted"] is False  # unknown event: received, nothing done


@pytest.mark.asyncio
async def test_digest_of_reserialised_json_is_refused():
    reserialised = json.dumps(json.loads(RAW)).encode()
    assert reserialised != RAW
    r = await _post(RAW, {**EVENT, "x-eternitas-signature": f"sha256={_sig(reserialised)}"})
    assert r.status_code == 401 and r.json()["code"] == "webhook_signature_invalid"


@pytest.mark.asyncio
async def test_forged_or_wrong_key_signature_is_refused():
    for header in ("sha256=" + "0" * 64, f"sha256={_sig(RAW, 'other-secret')}", "garbage"):
        r = await _post(RAW, {**EVENT, "x-eternitas-signature": header})
        assert r.status_code == 401, header


@pytest.mark.asyncio
async def test_signed_event_without_signature_is_refused():
    r = await _post(RAW, EVENT)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_unset_secret_refuses_rather_than_accepts():
    r = await _post(RAW, {**EVENT, "x-eternitas-signature": f"sha256={_sig(RAW)}"}, secret="")
    assert r.status_code == 503 and r.json()["code"] == "webhook_secret_unset"


@pytest.mark.asyncio
async def test_revocation_with_bad_signature_never_reaches_the_handler():
    body = b'{"event":"passport.revoked","passport":"ET26-TEST-GOOD"}'
    r = await _post(
        body,
        {"x-eternitas-event": "passport.revoked", "x-eternitas-signature": "sha256=" + "f" * 64},
    )
    assert r.status_code == 401  # refused before any DB work


@pytest.mark.asyncio
async def test_reachability_ping_acknowledges_but_never_acts():
    r = await _post(b'{"anything": "at all"}', {"x-eternitas-event": "platform.test_ping"})
    assert r.status_code == 200 and r.json()["acted"] is False
