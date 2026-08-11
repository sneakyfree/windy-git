"""Repair-pointer error taxonomy (section 0.6, G8.3).

EVERY error this service emits is a 4-field repair pointer:

    {code, speak, machine_cause, remediation_tool}

No exceptions, including validation errors. `speak` is grandma-words (I-9) and
obeys the D-9 vocabulary law (see scripts/vocab_audit.py), and never uses the
word "commit" on a shelter surface.
`remediation_tool` names the tool an agent should call next, or null when a human
must act.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


class RepairPointer(HTTPException):
    """An error an agent can act on without guessing."""

    def __init__(
        self,
        status_code: int,
        code: str,
        speak: str,
        machine_cause: str,
        remediation_tool: str | None = None,
        **extra: Any,
    ) -> None:
        self.code = code
        self.speak = speak
        self.machine_cause = machine_cause
        self.remediation_tool = remediation_tool
        super().__init__(
            status_code=status_code,
            detail={
                "code": code,
                "speak": speak,
                "machine_cause": machine_cause,
                "remediation_tool": remediation_tool,
                **extra,
            },
        )


def provider_unconfigured(provider: str, missing: str) -> RepairPointer:
    """I-8: fail closed. Never answer from a mock, never claim live.

    This is the guard the domains cell did not have on its public quote route.
    """
    return RepairPointer(
        status_code=503,
        code="provider_unconfigured",
        speak=(
            "That part of Windy Git isn't switched on yet, so we're not going to "
            "guess at an answer. Nothing you have is affected."
        ),
        machine_cause=f"{provider} is not configured: {missing} is unset",
        remediation_tool=None,
        provider=provider,
    )


def passport_unresolvable(passport: str, upstream_status: int) -> RepairPointer:
    """G3.6: 404 and 400 REFUSE. There is no soft-allow path here.

    windy-chat maps 400/429 to "unreachable" and then soft-ALLOWS, which is a
    live residual bypass because 429 is trivially inducible at 100/min/IP.
    """
    return RepairPointer(
        status_code=403,
        code="passport_unresolvable",
        speak="We couldn't confirm that helper's ID, so we didn't let it make changes.",
        machine_cause=(
            f"eternitas trust lookup for {passport} returned {upstream_status}; "
            "policy is REFUSE on 400/404 and REFUSE after backoff on 429/5xx"
        ),
        remediation_tool="windy_git.reissue_agent_token",
        passport=passport,
    )


def quota_exceeded(repo_id: str, used: int, limit: int) -> RepairPointer:
    """G4.6: we emit the cross-sell hook; the KERNEL owns the price (I-11)."""
    return RepairPointer(
        status_code=413,
        code="quota_exceeded",
        speak=(
            "Your projects have outgrown the space on your plan. Nothing was lost — "
            "the newest save just didn't go through."
        ),
        machine_cause=f"repo {repo_id} would use {used} bytes against a limit of {limit}",
        remediation_tool="windy_cloud.upgrade_storage",
        repo_id=repo_id,
    )


def kit_zero_refused(host: str) -> RuntimeError:
    """D-4 / section 7.8: only Grant may overturn a never."""
    return RuntimeError(
        f"REFUSING TO START: this service is pointed at Kit 0 ({host}). "
        "Windy Git never runs on Kit 0 — CI executes untrusted code and Kit 0 "
        "holds identity, the certificate authority, mail, Matrix and the broker. "
        "See DNA_STRAND_MASTER_PLAN.md D-4."
    )
