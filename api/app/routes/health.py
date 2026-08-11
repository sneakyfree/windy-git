"""G0.2 / G0.3 — /version and /health/full.

The two endpoints this ecosystem most needs to be honest, because both audits
found them lying elsewhere: nine of twelve services cannot name their commit, and
a sibling cell reported healthy while serving from a mock.

`/health/full` returns `ok` ONLY when every provider it depends on proved itself
against the real dependency. Anything else is `degraded`. There is no code path
that returns `ok` from an unconfigured provider (I-8).
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from api.app.buildinfo import get_build_info
from api.app.config import get_settings

router = APIRouter(tags=["system"])


@router.get("/version")
async def version() -> dict:
    """I-12. A runtime COMMIT_SHA override is ignored; see buildinfo.py."""
    info = get_build_info()
    s = get_settings()
    return {
        "service": s.service_name,
        "version": info.version,
        "commit_sha": info.commit_sha,
        "built_at": info.built_at,
        "source": info.source,
        "environment": s.environment,
        "repo_types_enabled": list(s.repo_types_enabled),
    }


@router.get("/health")
async def health() -> dict:
    """Cheap liveness. Says nothing about dependencies — /health/full does that."""
    return {"status": "ok"}


@router.get("/health/full")
async def health_full(request: Request, response: Response) -> dict:
    providers = request.app.state.providers
    checks: dict[str, dict] = {}

    for provider in providers:
        result = await provider.healthy()
        checks[provider.name] = {
            "ok": result.ok,
            "configured": provider.configured,
            "reachable": result.reachable,
            "detail": result.detail,
        }

    all_ok = all(c["ok"] for c in checks.values())
    status = "ok" if all_ok else "degraded"
    if not all_ok:
        # Degraded is a real answer, not a 500. But it must never read as ok.
        response.status_code = 503

    info = get_build_info()
    return {
        "status": status,
        "commit_sha": info.commit_sha,
        "checks": checks,
        # Named, not hidden. An observer should never have to wonder whether a
        # missing check means healthy or means forgotten.
        "not_checked_here": {
            "tunnel": (
                "host-scoped: cloudflared binds host loopback and is supervised "
                "by systemd (windygit-tunnel). Verify with `systemctl status`."
            )
        },
        # Grandma-words, and the D-9 vocabulary law binds this string.
        "speak": (
            "Everything is working."
            if all_ok
            else "Some parts of Windy Git aren't switched on. Nothing you have is lost."
        ),
    }
