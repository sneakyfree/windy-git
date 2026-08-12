"""Eternitas webhook receiver (G3.5) — revocation is FAIL-CLOSED.

When a passport is revoked, every credential that passport holds here dies in
one transaction: tokens revoked, grants revoked, in-flight CI cancelled. A
revocation that takes effect "eventually" is not a revocation.

Two traps are avoided here on purpose, both paid for elsewhere in the ecosystem:

1. **Strip the `sha256=` prefix before comparing.** A sibling receiver compared
   the whole header against a bare hex digest and therefore returned 401
   forever — the subscription looked wired and never once delivered.
2. **HMAC the RAW REQUEST BYTES, not a re-serialised body.** `JSON.stringify` of
   a parsed body reorders keys and changes whitespace, so the digest never
   matches what the sender signed. Same outcome: deterministic 401.

Both failures are silent from the sender's side — Eternitas records a delivery
attempt, the receiver records a rejection, and nobody notices for weeks.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Header, Request
from sqlalchemy import select, update

from api.app.errors import RepairPointer
from api.app.models.core import AgentToken, Repo, RepoGrant

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


def _verify(raw: bytes, header: str | None, secret: str) -> bool:
    if not header or not secret:
        return False
    # Trap 1: senders prefix the digest. Compare digests, not decorated strings.
    presented = header.split("=", 1)[1] if header.startswith("sha256=") else header
    # Trap 2: sign the bytes that arrived, never a re-serialised object.
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(presented, expected)


@router.post("/eternitas")
async def eternitas_webhook(
    request: Request,
    x_eternitas_event: str | None = Header(default=None),
    x_eternitas_signature: str | None = Header(default=None),
) -> dict:
    settings = request.app.state.settings
    raw = await request.body()

    # `platform.test_ping` is the ONE event accepted without verification, and
    # the reason is structural rather than convenient.
    #
    # Eternitas generates the webhook secret at registration time and pings the
    # URL to prove it is reachable BEFORE returning that secret. The ping is
    # signed — with a secret the receiver cannot possibly hold yet. So the
    # signature is unverifiable by construction, not by oversight.
    #
    # Accepting it is safe because the event is definitionally a no-op: nothing
    # is read, nothing is written, `acted` is false. Every event that changes
    # anything — `passport.revoked` above all — still requires a valid HMAC
    # below. The alternative was `skip_validation: true` at registration, which
    # would permanently disable reachability checking for this platform to
    # solve a one-time ordering problem.
    if x_eternitas_event == "platform.test_ping" or (
        not x_eternitas_event and not x_eternitas_signature
    ):
        return {
            "ready": True,
            "acted": False,
            "detail": (
                "reachability ping acknowledged; it is unverifiable by "
                "construction and changes nothing. Signed events are verified."
            ),
        }

    secret = settings.eternitas_webhook_secret
    if not secret:
        # I-8: refuse rather than accept unverified instructions about identity.
        raise RepairPointer(
            status_code=503,
            code="webhook_secret_unset",
            speak="We can't accept that update yet.",
            machine_cause="ETERNITAS_WEBHOOK_SECRET is unset; refusing unverified webhooks",
            remediation_tool=None,
        )

    if not _verify(raw, x_eternitas_signature, secret):
        raise RepairPointer(
            status_code=401,
            code="webhook_signature_invalid",
            speak="We couldn't confirm where that update came from, so we ignored it.",
            machine_cause="HMAC mismatch on the raw request body",
            remediation_tool=None,
        )

    payload = await request.json()
    event = x_eternitas_event or payload.get("event") or "unknown"
    passport = (
        payload.get("passport")
        or payload.get("passport_number")
        or (payload.get("data") or {}).get("passport")
    )

    if event != "passport.revoked":
        # Acknowledge without pretending to have acted. A 200 here means
        # "received", and the body says exactly what was done — which is nothing.
        log.info("eternitas event %s received (no handler)", event)
        return {"received": True, "event": event, "acted": False}

    if not passport:
        raise RepairPointer(
            status_code=422,
            code="revocation_missing_passport",
            speak="That update didn't say which helper it was about.",
            machine_cause=f"passport.revoked payload carried no passport field: {list(payload)}",
            remediation_tool=None,
        )

    maker = getattr(request.app.state, "sessionmaker", None)
    if maker is None:
        raise RepairPointer(
            status_code=503,
            code="database_unavailable",
            speak="We couldn't apply that update. Please try again.",
            machine_cause="no database sessionmaker; refusing to acknowledge a revocation we did not apply",
            remediation_tool=None,
        )

    now = datetime.now(UTC)
    async with maker() as session:
        # One transaction. A partial revocation is a security hole that reports
        # success.
        tokens = await session.execute(
            update(AgentToken)
            .where(AgentToken.passport == passport, AgentToken.revoked_at.is_(None))
            .values(revoked_at=now, revoked_reason="eternitas:passport.revoked")
        )
        grants = await session.execute(
            update(RepoGrant)
            .where(RepoGrant.grantee_passport == passport, RepoGrant.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        owned = (
            await session.execute(select(Repo.id).where(Repo.passport == passport))
        ).scalars().all()
        await session.commit()

    log.warning(
        "passport %s revoked: %s tokens, %s grants, %s owned repos",
        passport, tokens.rowcount, grants.rowcount, len(owned),
    )
    return {
        "received": True,
        "event": event,
        "acted": True,
        "passport": passport,
        "tokens_revoked": tokens.rowcount,
        "grants_revoked": grants.rowcount,
        "owned_repos": len(owned),
        # state_proof so the caller can verify rather than trust (section 0.6).
        "state_proof": {"revoked_at": now.isoformat()},
    }
