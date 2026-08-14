"""EI-band velocity limits (G3.4) — throttle by trust, never by omission.

`BAND_MULTIPLIER` and the `rate_*_per_day` settings existed since G0 and were
**read by nothing**: a documented invariant with no implementation, which is the
exact failure pattern the ecosystem audits kept finding. This module is the
missing consumer.

The doctrine (§0.6) is *capability-completeness*: an agent is never denied a
capability it should have, it is **rate-limited by how much it has proven**.
Platinum gets 10x, gold 4x, standard 1x, watch 0.5x, and untrusted is read-only.

Counting is done against `agent_actions`, which is already the append-only record
of every agent write. That is deliberate: a limiter with its own private counter
disagrees with the audit log the moment either is restarted, and then nobody can
say what actually happened. One source of truth, queried.

**Fail-closed.** If the count cannot be taken, the action is refused. A limiter
that fails open is decoration — it protects you right up until the moment
something is wrong, which is the only moment it matters.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.auth import BAND_MULTIPLIER, ActorType, Caller
from api.app.config import Settings
from api.app.errors import RepairPointer
from api.app.models.core import AgentAction

log = logging.getLogger(__name__)

WINDOW = timedelta(days=1)

# Actions this module ACTUALLY enforces: they pass through our API, so we can
# both count and refuse them.
ACTION_BASE: dict[str, str] = {
    "repo.create": "rate_repo_creates_per_day",
    "grant.create": "rate_grants_per_day",
}

# ⚠️ DECLARED BUT NOT ENFORCEABLE HERE — and named, rather than quietly listed
# alongside the real ones.
#
# `git push` goes straight to Gitea over HTTPS and never touches this API, so
# nothing records a `push` action and a count of them would be zero forever.
# Listing these in ACTION_BASE (as this module first did) would make `enforce`
# look up a limit, count nothing, and allow everything — a silent no-op wearing
# the costume of a control. That is the same dead-code pattern this module was
# written to remove, and it is worse here because the config name implies the
# protection exists.
#
# Enforcing push velocity requires a Gitea-side hook (pre-receive or the push
# webhook) that reports into `agent_actions`. Until that exists these settings
# are inert, and saying so is the honest option.
NOT_ENFORCED_HERE: dict[str, str] = {
    "push": "rate_pushes_per_day",
    "push.force": "rate_force_pushes_per_day",
}


def limit_for(settings: Settings, action: str, band: str | None) -> int:
    """Effective per-day allowance. Unknown bands get the standard rate.

    Unknown-band handling is a real decision, not a default. Eternitas began
    emitting `unproven` on 2026-07-30 without it appearing in the documented
    enum. Treating an unrecognised band as untrusted would lock out every freshly
    hatched agent the day Eternitas adds a name; treating it as platinum would be
    a hole. Standard-with-no-bonus is the honest middle.
    """
    base = getattr(settings, ACTION_BASE[action])
    mult = BAND_MULTIPLIER.get((band or "").lower(), 1.0)
    return int(base * mult)


async def enforce(
    session: AsyncSession,
    settings: Settings,
    caller: Caller,
    action: str,
) -> None:
    """Raise 429 if this agent has spent its allowance. No-op for humans.

    Humans are governed by account tier and their own session; this is the
    agent-velocity control specifically (I-6: parity in capability, asymmetry in
    throttle).
    """
    if caller.actor_type != ActorType.agent or not caller.passport:
        return
    if action not in ACTION_BASE:  # unknown action = unlimited would be a hole
        raise RepairPointer(
            status_code=500,
            code="throttle_unknown_action",
            speak="Something went wrong on our side. Nothing was changed.",
            machine_cause=f"no rate base configured for action {action!r}",
            remediation_tool=None,
        )

    band = (caller.band or "").lower()

    # Untrusted is read-only. This is a capability decision, not a rate: it gets
    # a 403 with a different explanation, because "slow down" would be a lie.
    if BAND_MULTIPLIER.get(band, 1.0) <= 0:
        raise RepairPointer(
            status_code=403,
            code="agent_read_only",
            speak="That helper can look, but it isn't allowed to make changes yet.",
            machine_cause=f"passport {caller.passport} band={band!r} is read-only",
            remediation_tool=None,
        )

    allowed = limit_for(settings, action, band)
    since = datetime.now(UTC) - WINDOW

    try:
        used = (
            await session.execute(
                select(func.count())
                .select_from(AgentAction)
                .where(
                    AgentAction.passport == caller.passport,
                    AgentAction.action == action,
                    AgentAction.result == "ok",
                    AgentAction.ts >= since,
                )
            )
        ).scalar_one()
    except Exception as exc:  # noqa: BLE001
        # FAIL CLOSED. A limiter that fails open protects you until the moment
        # something is wrong, which is the only moment it matters.
        log.warning("throttle count failed for %s/%s: %s", caller.passport, action, exc)
        raise RepairPointer(
            status_code=503,
            code="throttle_unavailable",
            speak="We couldn't check that helper's limits, so we didn't make the change.",
            machine_cause=f"agent_actions count failed: {type(exc).__name__}",
            remediation_tool=None,
        ) from exc

    if used >= allowed:
        raise RepairPointer(
            status_code=429,
            code="agent_rate_limited",
            speak=(
                "That helper has done a lot in the last day, so we've paused it. "
                "It'll be able to continue shortly."
            ),
            machine_cause=(
                f"passport {caller.passport} used {used}/{allowed} of {action} "
                f"in 24h (band={band or 'unknown'})"
            ),
            remediation_tool=None,
            used=used,
            allowed=allowed,
            band=band or "unknown",
        )


async def record(
    session: AsyncSession,
    caller: Caller,
    action: str,
    result: str = "ok",
    repo_id=None,
) -> None:
    """Append the action that was just allowed.

    Written AFTER the work succeeds, on purpose: counting attempts would let a
    failing agent exhaust its own allowance by retrying, turning a transient
    error into a lockout.
    """
    if caller.actor_type != ActorType.agent or not caller.passport:
        return
    session.add(
        AgentAction(
            passport=caller.passport,
            repo_id=repo_id,
            action=action,
            ei_at_action=caller.band,
            result=result,
        )
    )
    await session.flush()
