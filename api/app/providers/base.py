"""Provider seams — all of them fail CLOSED (I-8).

`windy-cloud-sites` ships an `edge_live` gate whose whole job is "never claim
live while the provider is mock" (commit a8ff948). `windy-cloud-domains` has a
registrar seam that literally raises `RuntimeError("Refusing to pretend")` — and
then shipped its public portal without wiring the equivalent gate on the quote
route, which is why production told anyone who asked that google.com was
available for $18.00 a year.

The lesson those two cells paid for: a fail-closed seam is worth nothing if a
route can reach the data without passing through it. So here the probe and the
gate are the SAME object, and `healthy()` can never return True for a provider
that `configured` reports False.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    detail: str
    # True only when we actually reached the real dependency. A provider that is
    # merely "not configured" is ok=False, reachable=False — never ok=True.
    reachable: bool = False


class Provider(abc.ABC):
    """A dependency outside this process."""

    name: str

    @property
    @abc.abstractmethod
    def configured(self) -> bool:
        """Do we hold every credential needed to talk to the real thing?"""

    @abc.abstractmethod
    async def probe(self) -> ProbeResult:
        """Reach the real dependency. Never simulate."""

    async def healthy(self) -> ProbeResult:
        if not self.configured:
            return ProbeResult(
                ok=False,
                detail=f"{self.name} is not configured; refusing to report healthy",
                reachable=False,
            )
        try:
            return await self.probe()
        except Exception as exc:  # noqa: BLE001 - a probe must never raise upward
            return ProbeResult(ok=False, detail=f"{self.name} probe failed: {exc}")
