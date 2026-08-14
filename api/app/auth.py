"""Identity: humans, agents, and internal services (G3.2 / G3.6 / I-6).

Three caller classes, all first-class, none a bypass:

  * **human**   — account-server RS256 JWT (OIDC)
  * **agent**   — Eternitas ES256 EPT
  * **service** — `X-Service-Token`, for the Cloud portal calling `/internal/*`

There is deliberately no fourth class and no escape hatch. The Windy Word desktop
control server is the best Principle-#5 artifact in the ecosystem partly because
it has **no bypass environment variable**, and that is copied here on purpose.

I-6 — EPT parity plus asymmetry: an agent in good standing gets exactly what a
human of the same tier gets. Where a sibling cell silently demotes a tiered agent
to FREE because its EPT carries no tier, we do the opposite, and a test proves it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

import httpx
from fastapi import Header, Request

from api.app.config import Settings
from api.app.ept import EptInvalid, looks_like_ept, verify_ept
from api.app.errors import RepairPointer, passport_unresolvable

log = logging.getLogger(__name__)


class ActorType(StrEnum):
    """G3.7 — these three are the ONLY legal values.

    A sibling service emits `actor_type: 'service'` into a telemetry ingest whose
    Literal allows only human|agent|system, so every batch 422s and is dropped
    with a single console warning. `service` is not spelled `service` here.
    """

    human = "human"
    agent = "agent"
    system = "system"


@dataclass(frozen=True)
class Caller:
    actor_type: ActorType
    identity_id: str | None = None
    passport: str | None = None
    band: str | None = None
    allowed_actions: tuple[str, ...] = ()

    @property
    def subject(self) -> str:
        return self.identity_id or self.passport or "system"


# EI_CAPABILITY_MATRIX.v1 — velocity multipliers by integrity band.
BAND_MULTIPLIER: dict[str, float] = {
    "platinum": 10.0,
    "gold": 4.0,
    "standard": 1.0,
    "proven": 1.0,
    "watch": 0.5,
    "untrusted": 0.0,  # read-only
    # Eternitas began emitting this band on 2026-07-30 and it is not in the
    # documented enum yet. Treating an unknown band as untrusted would lock out
    # every freshly hatched agent; treating it as trusted would be a hole.
    # Standard-with-no-bonus is the honest middle.
    "unproven": 1.0,
}


class PassportNotInGoodStanding(Exception):
    """The passport resolved, but Eternitas does not list it as active
    (revoked / suspended / frozen / unknown status)."""

    def __init__(self, passport: str, status: str) -> None:
        self.passport = passport
        self.status = status
        super().__init__(f"{passport} status={status!r}")


def decide_trust(body: dict, passport: str) -> tuple[str, tuple[str, ...]]:
    """The trust body -> (band, allowed_actions), or refuse.

    THE GATE THAT WAS MISSING. A revoked passport returns HTTP 200 with
    `status: revoked`, `band: unproven`, `allowed_actions: []` — verified live
    2026-08-13. The previous code keyed refusal only on HTTP 4xx and on
    band=="untrusted", so a revoked agent (200, band unproven) authenticated and
    acted normally. Revocation was not enforced on the live path at all; the
    webhook that was supposed to be the backup was never the primary gate.

    Only `status == "active"` is allowed. Anything else — including a status
    Eternitas invents tomorrow — refuses. Fail-closed on the field that carries
    the most consequential fact about an identity.
    """
    status = str(body.get("status", "")).lower()
    if status != "active":
        raise PassportNotInGoodStanding(passport, status or "missing")
    return body.get("band", "unproven"), tuple(body.get("allowed_actions", ()))


async def resolve_passport(settings: Settings, passport: str) -> tuple[str, tuple[str, ...]]:
    """G3.6 — THE STATUS-CODE LAW.

    404 and 400 REFUSE. 429 and 5xx retry with backoff, then REFUSE.

    A sibling service maps 400 and 429 to "unreachable" and then soft-ALLOWS.
    That is a live residual bypass, because 429 is trivially inducible at
    100/min/IP: an attacker who wants the check skipped only has to make the
    check rate-limit itself. There is no code path here where an unresolvable
    passport is permitted to write.
    """
    if not settings.eternitas_configured:
        raise RepairPointer(
            status_code=503,
            code="trust_unavailable",
            speak="We can't confirm helper IDs right now, so we didn't let that change through.",
            machine_cause="eternitas is not configured; policy is fail-closed",
            remediation_tool=None,
        )

    url = f"{settings.eternitas_base_url}/api/v1/trust/{passport}"
    headers = {"X-API-Key": settings.eternitas_platform_api_key}
    last_status = 0
    for attempt in range(3):
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
            try:
                r = await client.get(url, headers=headers)
            except httpx.RequestError as exc:
                last_status = 599
                log.warning("eternitas unreachable (attempt %s): %s", attempt + 1, exc)
                continue
        last_status = r.status_code
        if r.status_code == 200:
            # decide_trust raises PassportNotInGoodStanding on a non-active
            # status; that propagates past the retry loop as a hard refusal.
            return decide_trust(r.json(), passport)
        if r.status_code in (400, 404):
            # Malformed or not-issued. Refuse immediately — retrying cannot help
            # and pretending it might is how a soft-allow gets written.
            break
        # 429 / 5xx: retry, then refuse. Never allow.
    raise passport_unresolvable(passport, last_status)


async def get_caller(
    request: Request,
    authorization: str | None = Header(default=None),
    x_service_token: str | None = Header(default=None),
) -> Caller:
    settings: Settings = request.app.state.settings

    # --- internal service caller (the Cloud portal) ------------------------
    if x_service_token:
        expected = settings.service_token
        if not expected:
            raise RepairPointer(
                status_code=503,
                code="service_auth_unconfigured",
                speak="That connection isn't set up yet.",
                machine_cause="SERVICE_TOKEN is unset; refusing to accept service calls",
                remediation_tool=None,
            )
        # Constant-time compare, copied from the desktop control server's
        # control-auth pattern rather than reinvented.
        import hmac

        if not hmac.compare_digest(x_service_token, expected):
            raise RepairPointer(
                status_code=401,
                code="service_token_invalid",
                speak="That connection isn't authorised.",
                machine_cause="X-Service-Token did not match",
                remediation_tool=None,
            )
        return Caller(actor_type=ActorType.system, identity_id="system")

    if not authorization or not authorization.lower().startswith("bearer "):
        raise RepairPointer(
            status_code=401,
            code="not_signed_in",
            speak="You'll need to sign in first.",
            machine_cause="no bearer token and no service token presented",
            remediation_tool=None,
        )

    token = authorization.split(" ", 1)[1].strip()

    # --- agent (Eternitas EPT) --------------------------------------------
    # Possession FIRST, reputation second. The signature proves the caller holds
    # this passport; the trust lookup then says what it may do. Doing only the
    # second was the 2026-08-13 impersonation bypass.
    if looks_like_ept(token):
        try:
            verified = verify_ept(token, settings.eternitas_base_url)
        except EptInvalid as exc:
            raise RepairPointer(
                status_code=401,
                code="ept_invalid",
                speak="We couldn't confirm that helper's ID, so we didn't let it in.",
                machine_cause=f"EPT verification failed: {exc}",
                remediation_tool="windy_git.reissue_agent_token",
            ) from exc

        # The token is authentic. It is NOT evidence of current standing: these
        # EPTs live ~365 days and carry `rev`/`tru` baked in at issuance, so a
        # year-old `rev: false` proves nothing. Revocation and band come from a
        # live lookup, every time.
        try:
            band, actions = await resolve_passport(settings, verified.passport)
        except PassportNotInGoodStanding as exc:
            # The signature is authentic, but the identity is no longer good.
            # Revocation takes effect here, live, on the next request — no
            # webhook required. That is the honest place for it: the token can't
            # be un-issued, but its standing is checked every time.
            raise RepairPointer(
                status_code=403,
                code="passport_revoked",
                speak="That helper's access has been turned off.",
                machine_cause=f"eternitas status for {verified.passport} is {exc.status!r}, not active",
                remediation_tool=None,
            ) from exc
        if band.lower() == "untrusted":
            raise RepairPointer(
                status_code=403,
                code="agent_read_only",
                speak="That helper can look, but it isn't allowed to make changes yet.",
                machine_cause=f"passport {verified.passport} band=untrusted is read-only",
                remediation_tool=None,
            )
        return Caller(
            actor_type=ActorType.agent,
            passport=verified.passport,
            band=band,
            allowed_actions=actions,
        )

    # --- human (account-server RS256) -------------------------------------
    if settings.is_production and settings.require_verified_jwt:
        # I-8, applied to ourselves. G3.2's JWKS verifier is not written yet, and
        # an unverified JWT is an authentication bypass rather than a shortcut.
        # Refusing is the only honest answer until the verifier exists.
        raise RepairPointer(
            status_code=503,
            code="human_signin_not_ready",
            speak="Signing in isn't switched on yet. Nothing you have is affected.",
            machine_cause=(
                "JWKS verification (G3.2) is not implemented; refusing to accept "
                "an unverified human token in production"
            ),
            remediation_tool=None,
        )

    identity_id = _unverified_claim(token, "windy_identity_id") or _unverified_claim(token, "sub")
    if not identity_id:
        raise RepairPointer(
            status_code=401,
            code="token_unrecognised",
            speak="We couldn't read that sign-in. Try signing in again.",
            machine_cause="token carried neither a passport nor an identity claim",
            remediation_tool=None,
        )
    return Caller(actor_type=ActorType.human, identity_id=identity_id)


def _unverified_claim(token: str, claim: str) -> str | None:
    """Read a claim WITHOUT verifying the signature.

    Used only to decide which verifier a token belongs to. Every path that acts
    on the result re-establishes trust independently: an agent's authority comes
    from a live Eternitas trust lookup, never from the token's own assertions.

    ⚠️ Full RS256/ES256 JWKS verification for the human path lands in G3.2's
    verifier and MUST be in place before `api.windygit.com` accepts a human
    token from outside. Until then the human path is reachable only from inside
    the tunnel, and `settings.require_verified_jwt` refuses it in production.
    """
    import base64
    import json

    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get(claim)
    except Exception:  # noqa: BLE001
        return None
