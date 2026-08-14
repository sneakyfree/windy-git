"""EPT signature verification (G3.2 / G9.1) — the gate that makes an agent an agent.

Trust is not authentication. A trust lookup answers *"is this passport
reputable?"*; only a signature answers *"does this caller actually hold it?"*.
Skipping the second question was a live impersonation bypass on 2026-08-13 — a
forged `alg:none` token naming a passport read out of the logs returned HTTP 200.

What this module refuses, deliberately and by construction:

* **`alg: none`** — the original exploit. `algorithms=["ES256"]` makes it
  unrepresentable rather than merely unlikely.
* **Algorithm confusion.** Only ES256 is accepted. If an attacker presents an
  HS256 token, PyJWT will not try to use an EC public key as an HMAC secret,
  which is the classic way "verified" JWTs get forged.
* **An unknown `kid`.** The key must be one Eternitas currently publishes.
* **A wrong issuer or an expired token** — checked by the library, not by us.

What it deliberately does NOT decide: whether the agent is *allowed* to act.
The EPT carries `rev` and `tru` claims baked in at issuance, and these tokens
live for a year (observed `exp` ≈ 365 days). A year-old `rev: false` is not
evidence of anything. **Revocation and trust must come from a live lookup**, so
this module returns only identity and the caller re-checks standing.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx
import jwt
from jwt import PyJWKClient

log = logging.getLogger(__name__)

ISSUER = "eternitas.ai"
ALGORITHMS = ["ES256"]  # exactly one. Never widen this list.

_jwks_client: PyJWKClient | None = None
_jwks_url: str | None = None


class EptInvalid(Exception):
    """The token is not a valid, currently-signed Eternitas EPT."""


@dataclass(frozen=True)
class VerifiedEpt:
    passport: str
    operator: str | None
    bot_name: str | None
    issued_at: int | None
    expires_at: int | None


def _client(base_url: str) -> PyJWKClient:
    """One cached JWKS client. PyJWKClient caches keys and refetches on an
    unknown kid, so a key rotation heals itself without a redeploy."""
    global _jwks_client, _jwks_url
    url = f"{base_url.rstrip('/')}/.well-known/eternitas-keys"
    if _jwks_client is None or _jwks_url != url:
        _jwks_client = PyJWKClient(url, cache_keys=True, lifespan=300)
        _jwks_url = url
    return _jwks_client


def verify_ept(token: str, eternitas_base_url: str) -> VerifiedEpt:
    """Verify an EPT's signature and claims. Raises EptInvalid on ANY doubt.

    There is no partial success and no "probably fine" path: every failure mode
    below produces the same refusal, because a caller that cannot prove
    possession is indistinguishable from an attacker.
    """
    try:
        signing_key = _client(eternitas_base_url).get_signing_key_from_jwt(token)
    except Exception as exc:  # noqa: BLE001 - unknown kid, unreachable JWKS, malformed
        raise EptInvalid(f"no usable signing key: {type(exc).__name__}: {exc}") from exc

    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=ALGORITHMS,   # ES256 only — closes alg:none and alg confusion
            issuer=ISSUER,
            options={
                "require": ["sub", "iss", "exp"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_iss": True,
            },
        )
    except jwt.PyJWTError as exc:
        raise EptInvalid(f"{type(exc).__name__}: {exc}") from exc

    # The REAL claim name. Eternitas puts the passport in `sub`; the previous
    # code looked for `passport` / `sub_passport`, which no genuine EPT carries —
    # so real agents were never recognised and only forged tokens ever "worked".
    passport = claims.get("sub")
    if not isinstance(passport, str) or not passport.strip():
        raise EptInvalid("EPT carried no passport in `sub`")

    return VerifiedEpt(
        passport=passport,
        operator=claims.get("ope"),
        bot_name=claims.get("bot"),
        issued_at=claims.get("iat"),
        expires_at=claims.get("exp"),
    )


def looks_like_ept(token: str) -> bool:
    """Cheap, unauthenticated triage: is this token even claiming to be an EPT?

    Used ONLY to route a token to the right verifier. It decides nothing about
    trust — an attacker controls every byte it reads.
    """
    try:
        header = jwt.get_unverified_header(token)
    except Exception:  # noqa: BLE001
        return False
    return header.get("typ") == "EPT" or header.get("alg") == "ES256"


async def eternitas_reachable(base_url: str) -> bool:
    """Whether the key set can be fetched at all. Used by /health/full so an
    unreachable JWKS is reported rather than discovered during an outage."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0)) as c:
            r = await c.get(
                f"{base_url.rstrip('/')}/.well-known/eternitas-keys",
                headers={"User-Agent": "windy-git/1.0"},
            )
        return r.status_code == 200 and "keys" in r.json()
    except Exception:  # noqa: BLE001
        return False


def seconds_until_expiry(ept: VerifiedEpt) -> int | None:
    return None if ept.expires_at is None else int(ept.expires_at - time.time())
