"""ept-cutoff.v1 (Eternitas #295): an EPT issued before the passport's
`ept_valid_after` is refused, though its signature and standing are fine.

The end-to-end tests sign real ES256 tokens and drive get_caller with a fake
Eternitas, so a removed or misplaced cutoff check fails them."""

from __future__ import annotations

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from api.app import auth
from api.app import ept as ept_mod
from api.app.config import Settings
from api.app.ept import EptInvalid, VerifiedEpt, parse_cutoff, refused_by_cutoff
from api.app.errors import RepairPointer

PASSPORT = "ET26-TEST-0001"


def _ept(iat):
    return VerifiedEpt(passport=PASSPORT, operator=None, bot_name=None, issued_at=iat, expires_at=None)


def test_parse_cutoff_forms():
    assert parse_cutoff(None) is None
    assert parse_cutoff("") is None
    assert parse_cutoff("2026-11-05T12:00:00Z") == 1793880000
    assert parse_cutoff("2026-11-05T12:00:00+00:00") == 1793880000
    # a fractional cutoff rounds UP, as the Eternitas SDK does
    assert parse_cutoff("2026-11-05T12:00:00.250Z") == 1793880001


@pytest.mark.parametrize("bad", ["yesterday", 12345, ["x"]])
def test_unreadable_cutoff_fails_closed(bad):
    with pytest.raises(EptInvalid):
        parse_cutoff(bad)


def test_cutoff_boundary_equal_is_valid_before_is_refused():
    assert refused_by_cutoff(_ept(99), 100) is True
    assert refused_by_cutoff(_ept(100), 100) is False
    assert refused_by_cutoff(_ept(101), 100) is False


def test_non_integer_iat_is_refused_when_a_cutoff_exists():
    assert refused_by_cutoff(_ept("9999999999"), 100) is True
    assert refused_by_cutoff(_ept(True), 100) is True
    assert refused_by_cutoff(_ept("9999999999"), None) is False


def test_missing_iat_is_before_the_cutoff_and_no_cutoff_never_refuses():
    assert refused_by_cutoff(_ept(None), 100) is True
    assert refused_by_cutoff(_ept(None), None) is False
    assert refused_by_cutoff(_ept(1), None) is False


# ---- end to end through get_caller ----------------------------------------

@pytest.fixture
def world(monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())

    class _JWK:
        def __init__(self, k):
            self.key = k

    class _JC:
        def __init__(self, *a, **k):
            pass

        def get_signing_key_from_jwt(self, token):
            return _JWK(key.public_key())

    monkeypatch.setattr(ept_mod, "_jwks_client", None)
    monkeypatch.setattr(ept_mod, "PyJWKClient", _JC)

    state = {"registry": (200, {"ept_valid_after": None}), "calls": []}

    class _Resp:
        def __init__(self, status, body):
            self.status_code, self._b = status, body

        def json(self):
            if isinstance(self._b, Exception):
                raise self._b
            return self._b

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **k):
            if "/registry/verify/" in url:
                state["calls"].append((url, k.get("headers") or {}))
                return _Resp(*state["registry"])
            return _Resp(200, {"status": "active", "band": "gold", "allowed_actions": ["read"]})

    monkeypatch.setattr(auth.httpx, "AsyncClient", _Client)
    settings = Settings(eternitas_platform_api_key="x", eternitas_base_url="https://api.eternitas.ai")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))

    def token(iat):
        claims = {"sub": PASSPORT, "iss": "eternitas.ai", "iat": iat, "exp": int(time.time()) + 3600}
        return jwt.encode(claims, key, algorithm="ES256", headers={"kid": "k", "typ": "EPT"})

    async def call(iat):
        return await auth.get_caller(request, authorization="Bearer " + token(iat), x_service_token=None)

    return SimpleNamespace(state=state, call=call)


@pytest.mark.asyncio
async def test_no_cutoff_lets_the_agent_in(world):
    caller = await world.call(int(time.time()) - 50)
    assert caller.passport == PASSPORT


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"status": "active"}, {"ept_valid_after": None}, {"ept_valid_after": ""}])
async def test_no_cutoff_in_any_shape_lets_the_agent_in(world, body):
    """Eternitas before migration 034 does not send the field at all; after it, a passport with no cutoff
    can send null. Both mean 'no cutoff': only a PRESENT, non-null value that will not parse refuses."""
    world.state["registry"] = (200, body)
    assert (await world.call(int(time.time()) - 5)).passport == PASSPORT


@pytest.mark.asyncio
async def test_ept_issued_before_the_cutoff_is_refused_401(world):
    now = int(time.time())
    world.state["registry"] = (200, {"ept_valid_after": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 10))})
    with pytest.raises(RepairPointer) as exc:
        await world.call(now - 100)
    assert exc.value.status_code == 401 and exc.value.code == "ept_before_cutoff"


@pytest.mark.asyncio
async def test_ept_issued_at_or_after_the_cutoff_is_accepted(world):
    now = int(time.time())
    world.state["registry"] = (200, {"ept_valid_after": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 10))})
    assert (await world.call(now - 10)).passport == PASSPORT
    assert (await world.call(now - 5)).passport == PASSPORT


@pytest.mark.asyncio
@pytest.mark.parametrize("registry", [(404, {}), (503, {}), (200, {"ept_valid_after": "garbage"})])
async def test_a_cutoff_we_cannot_read_refuses(world, registry):
    world.state["registry"] = registry
    with pytest.raises(RepairPointer) as exc:
        await world.call(int(time.time()) - 5)
    assert exc.value.status_code == 403 and exc.value.code == "passport_unresolvable"


@pytest.mark.asyncio
async def test_registry_call_carries_the_platform_key_and_a_quoted_passport(world):
    await world.call(int(time.time()) - 5)
    url, headers = world.state["calls"][0]
    assert headers.get("X-API-Key") == "x"  # platform tier, not the shared public IP bucket
    assert url.endswith("/api/v1/registry/verify/" + PASSPORT)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [ValueError("not json"), ["a list"], "text"])
async def test_a_registry_body_that_is_not_a_json_object_refuses_403(world, body):
    world.state["registry"] = (200, body)
    with pytest.raises(RepairPointer) as exc:
        await world.call(int(time.time()) - 5)
    assert exc.value.status_code == 403 and exc.value.code == "passport_unresolvable"
