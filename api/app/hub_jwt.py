"""Human token verification (G3.2) — hub access tokens from account.windyword.ai.

Until this existed the human path refused every token in production (503
`human_signin_not_ready`), because reading an unverified JWT's claims is an
authentication bypass, not a shortcut. This module is what lets it say yes.

The token it accepts is the hub's ACCESS token, as observed live 2026-09-23:

    header  {alg: RS256, typ: JWT, kid: <published at /.well-known/jwks.json>}
    claims  iss = "windy-identity"   (contract v1 also allows the discovery URL)
            type = "human", exp - iat = 900 s
            sub = per-row user id    ← NOT the cross-product identity
            windy_identity_id = the Windy Account UUID (what Gitea's OIDC links on)
            no `aud` yet

What it refuses, by construction:

* **Anything but RS256.** One algorithm, never a list. Closes `alg: none` and
  HS256-with-the-public-key confusion.
* **An unknown `kid`**, a wrong issuer, an expired token — library-checked.
* **An id_token used as a bearer.** id_tokens prove a login happened to a
  relying party (for the forge: aud `windy-git`), not that this caller may act
  here. They carry no `type` and no `windy_identity_id`, and their aud is a
  client id, not the product name `windy_git` — any one of the three refuses.
* **A non-human `type`.** An agent's authority comes from its EPT and a live
  Eternitas lookup, never from a hub token dressed as a person.
* **A token with no `windy_identity_id`.** `sub` is a different namespace (the
  per-row user id); falling back to it would silently mint identities that
  match nothing Gitea knows.

`aud` (token contract v1, lane 8c): an array; first-party tokens list every
product and Windy Git's is `windy_git`. Optional until the hub emits it; when
present it MUST include `windy_git`.
`hub_require_aud=True` makes it mandatory — flip it once the hub emits it.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from jwt import PyJWKClient

ALGORITHMS = ["RS256"]  # exactly one. Never widen this list.

_jwks_client: PyJWKClient | None = None
_jwks_url: str | None = None


class HubTokenInvalid(Exception):
    """Not a valid, currently-signed hub access token for a human."""


@dataclass(frozen=True)
class VerifiedHuman:
    identity_id: str
    email: str | None
    expires_at: int | None


def _client(base_url: str) -> PyJWKClient:
    """Cached JWKS client; refetches on an unknown kid so rotation self-heals."""
    global _jwks_client, _jwks_url
    url = f"{base_url.rstrip('/')}/.well-known/jwks.json"
    if _jwks_client is None or _jwks_url != url:
        _jwks_client = PyJWKClient(url, cache_keys=True, lifespan=300)
        _jwks_url = url
    return _jwks_client


def verify_hub_token(
    token: str,
    base_url: str,
    *,
    issuers: tuple[str, ...],
    audiences: tuple[str, ...],
    require_aud: bool,
    signing_key=None,
) -> VerifiedHuman:
    """Verify a hub access token. Raises HubTokenInvalid on ANY doubt.

    `signing_key` exists for tests only (a locally generated key, no network).
    """
    try:
        key = (
            signing_key
            if signing_key is not None
            else _client(base_url).get_signing_key_from_jwt(token).key
        )
    except Exception as exc:  # noqa: BLE001 - unknown kid, unreachable JWKS, malformed
        raise HubTokenInvalid(f"no usable signing key: {type(exc).__name__}: {exc}") from exc

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=ALGORITHMS,
            issuer=list(issuers),
            options={
                "require": ["iss", "exp", "iat"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_iss": True,
                # Checked by hand below: PyJWT rejects any token CARRYING aud
                # when no audience is passed, which would break the moment the
                # hub starts emitting it — the exact trap the SSO matrix names.
                "verify_aud": False,
            },
        )
    except jwt.PyJWTError as exc:
        raise HubTokenInvalid(f"{type(exc).__name__}: {exc}") from exc

    aud = claims.get("aud")
    if aud is None:
        if require_aud:
            raise HubTokenInvalid("token carries no aud and hub_require_aud is on")
    else:
        presented = {aud} if isinstance(aud, str) else set(aud) if isinstance(aud, list) else set()
        if not presented & set(audiences):
            raise HubTokenInvalid(f"aud {sorted(presented)} does not name Windy Git")

    # REQUIRED, not defaulted: id_tokens carry no `type`, and this is one of the
    # two claims (with windy_identity_id) that keep them from acting as bearers.
    if claims.get("type") != "human":
        raise HubTokenInvalid(f"token type {claims.get('type')!r} is not a human access token")

    identity = claims.get("windy_identity_id") or claims.get("windyIdentityId")
    if not isinstance(identity, str) or not identity.strip():
        raise HubTokenInvalid("token carries no windy_identity_id")

    return VerifiedHuman(
        identity_id=identity, email=claims.get("email"), expires_at=claims.get("exp")
    )
