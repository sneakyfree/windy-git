"""G3.2 / I-8 — human tokens are verified, never read (SSO #14, 2026-09-23).

Behavioral: every case signs a real RS256 token with a locally generated key
and drives `get_caller`, so a green run means the gate refuses what it must —
not that some string appears in auth.py.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from api.app import hub_jwt
from api.app.config import Settings
from api.app.errors import RepairPointer

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)
IDENTITY = "5e1b9569-7f01-489d-bf14-6fe5a367fa3f"


def _claims(**over):
    now = int(time.time())
    c = {
        "iss": "windy-identity",
        "type": "human",
        "sub": "row-id-not-identity",
        "windy_identity_id": IDENTITY,
        "email": "grant@example.com",
        "iat": now,
        "exp": now + 900,
    }
    c.update(over)
    return {k: v for k, v in c.items() if v is not None}


def _sign(claims, key=KEY, alg="RS256"):
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": "test"})


class _Req:
    def __init__(self, settings):
        self.app = type("A", (), {"state": type("S", (), {"settings": settings})()})()


@pytest.fixture(autouse=True)
def _local_jwks(monkeypatch):
    """The hub's JWKS, served from KEY's public half — no network."""

    class _Key:
        key = KEY.public_key()

    class _Client:
        def get_signing_key_from_jwt(self, token):
            return _Key()

    monkeypatch.setattr(hub_jwt, "_client", lambda base_url: _Client())


async def _caller(token, **settings):
    from api.app.auth import get_caller

    s = Settings(environment="production", **settings)
    return await get_caller(_Req(s), authorization=f"Bearer {token}", x_service_token=None)


async def _refused(token, **settings):
    with pytest.raises(RepairPointer) as exc:
        await _caller(token, **settings)
    assert exc.value.status_code == 401 and exc.value.code == "token_invalid"
    return exc.value


@pytest.mark.asyncio
async def test_genuine_hub_token_is_a_human_named_by_windy_identity_id():
    c = await _caller(_sign(_claims()))
    assert c.actor_type == "human"
    assert c.identity_id == IDENTITY  # NOT `sub`, which is the per-row user id


@pytest.mark.asyncio
async def test_forged_signature_is_refused():
    await _refused(_sign(_claims(), key=OTHER))


@pytest.mark.asyncio
async def test_expired_token_is_refused():
    await _refused(_sign(_claims(iat=int(time.time()) - 2000, exp=int(time.time()) - 60)))


@pytest.mark.asyncio
async def test_wrong_issuer_and_id_tokens_are_refused():
    await _refused(_sign(_claims(iss="https://evil.example")))
    # Contract v1: the discovery-URL issuer is legal for ACCESS tokens...
    c = await _caller(_sign(_claims(iss="https://account.windyword.ai")))
    assert c.identity_id == IDENTITY
    # ...but an id_token minted for the forge (aud = Gitea's client id
    # "windy-git", no type, sub = identity) must never act as a bearer here.
    id_token = _claims(
        iss="https://account.windyword.ai",
        aud="windy-git",
        type=None,
        windy_identity_id=None,
        sub=IDENTITY,
    )
    await _refused(_sign(id_token))
    await _refused(_sign(dict(id_token, windy_identity_id=IDENTITY, type="human")))


@pytest.mark.asyncio
async def test_hs256_confusion_is_refused():
    # The classic forgery: HMAC the token with the PUBLIC key as the secret.
    pub = KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).rstrip(
        b"="
    )
    body = base64.urlsafe_b64encode(json.dumps(_claims()).encode()).rstrip(b"=")
    sig = base64.urlsafe_b64encode(
        hmac.new(pub, header + b"." + body, hashlib.sha256).digest()
    ).rstrip(b"=")
    await _refused((header + b"." + body + b"." + sig).decode())


@pytest.mark.asyncio
async def test_non_human_or_missing_type_is_refused():
    await _refused(_sign(_claims(type="agent")))
    await _refused(_sign(_claims(type=None)))


@pytest.mark.asyncio
async def test_missing_windy_identity_is_refused_not_read_from_sub():
    await _refused(_sign(_claims(windy_identity_id=None)))


@pytest.mark.asyncio
async def test_aud_is_tolerated_when_it_names_windy_git_and_refused_otherwise():
    """PyJWT rejects ANY aud-bearing token when no audience is configured — the
    trap that would break the day the hub starts emitting aud."""
    c = await _caller(_sign(_claims(aud=["windy_chat", "windy_git", "windy_mail"])))
    assert c.identity_id == IDENTITY
    await _refused(_sign(_claims(aud=["windy_chat"])))


@pytest.mark.asyncio
async def test_require_aud_refuses_tokens_without_it():
    await _refused(_sign(_claims()), hub_require_aud=True)
    c = await _caller(_sign(_claims(aud=["windy_git"])), hub_require_aud=True)
    assert c.identity_id == IDENTITY


@pytest.mark.asyncio
async def test_production_verifies_even_if_the_flag_is_off():
    """require_verified_jwt=False is a local-dev convenience; production must
    never take the unverified path."""
    await _refused(_sign(_claims(), key=OTHER), require_verified_jwt=False)


def test_algorithm_list_is_exactly_rs256():
    assert hub_jwt.ALGORITHMS == ["RS256"]
