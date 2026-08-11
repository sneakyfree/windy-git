"""Concrete providers: Gitea, R2, Eternitas, Postgres, tunnel.

Each is a real probe against the real dependency (I-8). None of them has a mock
mode. If you find yourself adding one, add it behind `configured` returning False
instead — an unconfigured provider is honest; a mock provider is a liar with a
green light.
"""

from __future__ import annotations

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from api.app.config import Settings
from api.app.providers.base import ProbeResult, Provider

_TIMEOUT = httpx.Timeout(5.0, connect=3.0)


class GiteaProvider(Provider):
    """Gitea is a COMPONENT behind an API membrane, never a merged tree (I-1)."""

    name = "gitea"

    def __init__(self, settings: Settings) -> None:
        self._s = settings

    @property
    def configured(self) -> bool:
        return self._s.gitea_configured

    async def probe(self) -> ProbeResult:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(
                f"{self._s.gitea_base_url}/api/v1/version",
                headers={"Authorization": f"token {self._s.gitea_admin_token}"},
            )
        if r.status_code != 200:
            return ProbeResult(False, f"gitea /api/v1/version -> {r.status_code}", True)
        return ProbeResult(True, f"gitea {r.json().get('version', '?')}", True)


class R2Provider(Provider):
    """I-3: LFS, releases, artifacts, archives. NEVER git object stores."""

    name = "r2"

    def __init__(self, settings: Settings) -> None:
        self._s = settings

    @property
    def configured(self) -> bool:
        return self._s.r2_configured

    async def probe(self) -> ProbeResult:
        # HEAD the bucket via the S3 endpoint. boto3 is sync, so we keep the
        # probe to a plain reachability check here and let G4 wire the signed
        # client; a 400/403 still proves the endpoint is real and answering.
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.head(f"{self._s.r2_endpoint_url}/{self._s.r2_bucket_lfs}")
        reachable = r.status_code < 500
        return ProbeResult(
            ok=r.status_code in (200, 400, 403),
            detail=f"r2 endpoint -> {r.status_code}",
            reachable=reachable,
        )


class EternitasProvider(Provider):
    """The one issuer. Every agent identity in the ecosystem terminates here."""

    name = "eternitas"

    def __init__(self, settings: Settings) -> None:
        self._s = settings

    @property
    def configured(self) -> bool:
        return self._s.eternitas_configured

    async def probe(self) -> ProbeResult:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{self._s.eternitas_base_url}/health")
        return ProbeResult(r.status_code == 200, f"eternitas /health -> {r.status_code}", True)


class DatabaseProvider(Provider):
    """Postgres is truth. Gitea's own DB is a component's private state."""

    name = "db"

    def __init__(self, engine: AsyncEngine | None) -> None:
        self._engine = engine

    @property
    def configured(self) -> bool:
        return self._engine is not None

    async def probe(self) -> ProbeResult:
        assert self._engine is not None
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return ProbeResult(True, "postgres reachable", True)


class TunnelProvider(Provider):
    """cloudflared is the only ingress. No inbound port is ever opened (G1.2)."""

    name = "tunnel"

    def __init__(self, settings: Settings) -> None:
        self._s = settings

    @property
    def configured(self) -> bool:
        # The tunnel is a host-level concern, not a credential we hold, so there
        # is nothing to "configure" here. The probe alone decides health, and in
        # dev it will honestly say cloudflared is not running (I-8).
        return True

    async def probe(self) -> ProbeResult:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                r = await client.get("http://localhost:2000/metrics")
            except httpx.RequestError as exc:
                return ProbeResult(False, f"cloudflared metrics unreachable: {exc}")
        return ProbeResult(r.status_code == 200, f"cloudflared metrics -> {r.status_code}", True)
