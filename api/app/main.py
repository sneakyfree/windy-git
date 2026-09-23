"""windy-git — the version, permission and provenance plane over Windy Cloud.

Strand G0. This process is OUR service. Gitea runs beside it as an unforked
component and is reached only over its REST API (D-2 / I-1).
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.app.buildinfo import get_build_info
from api.app.config import get_settings
from api.app.errors import RepairPointer, kit_zero_refused
from api.app.providers.registry import (
    DatabaseProvider,
    EternitasProvider,
    GiteaProvider,
    R2Provider,
)
from api.app.routes import health, repos, webhooks
from api.app.telemetry import Telemetry, caller_class, is_synthetic

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
log = logging.getLogger("windy-git")


def _refuse_kit_zero(settings) -> None:
    """D-4 / section 7.8 — only Grant may overturn a never.

    Kit 0 is disqualified on four independent grounds, any one sufficient. The
    strongest: CI executes arbitrary workflow code, and Kit 0 holds identity, the
    certificate authority, inbound SMTP, Matrix, the broker and the admin console.
    A guard in a document is a preference; a guard in the boot path is a rule.
    """
    if not settings.is_production:
        return
    try:
        local_ips = {info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None)}
    except socket.gaierror:
        return
    if settings.kit0_host in local_ips:
        raise kit_zero_refused(settings.kit0_host)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    _refuse_kit_zero(settings)

    info = get_build_info()
    log.info(
        "starting windy-git %s commit=%s source=%s env=%s",
        info.version,
        (info.commit_sha or "unknown")[:12],
        info.source,
        settings.environment,
    )
    if info.source == "unknown":
        log.warning(
            "This process cannot name its own commit. It will report null rather "
            "than guess (I-12), but a production deploy in this state is a defect."
        )

    engine = None
    try:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("database engine not created: %s", exc)

    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = (
        async_sessionmaker(engine, expire_on_commit=False) if engine is not None else None
    )
    app.state.providers = [
        DatabaseProvider(engine),
        GiteaProvider(settings),
        R2Provider(settings),
        EternitasProvider(settings),
        # NOTE: the tunnel is deliberately NOT probed from here. cloudflared
        # binds its metrics on the host's loopback, so a container can never
        # reach it -- the check would be permanently red no matter what the
        # tunnel is doing. A check that structurally cannot succeed is worse
        # than no check: it trains people to ignore the dashboard, which is
        # exactly how a fleet canary goes 37 days dead without anyone noticing.
        # Tunnel health is a host concern and lives where it can be observed:
        # systemd Restart=always, plus the runbook's `systemctl status`.
    ]

    telemetry = Telemetry(
        settings.telemetry_ingest_url,
        settings.windygit_telemetry_token,
        environment=settings.environment,
        commit_sha=info.commit_sha,
        version=info.version,
    )
    app.state.telemetry = telemetry
    telemetry.boot()
    await telemetry.flush()
    task = asyncio.create_task(telemetry.run()) if telemetry.enabled else None

    yield

    if task is not None:
        task.cancel()
        await telemetry.flush()
    if engine is not None:
        await engine.dispose()


app = FastAPI(
    title="Windy Git",
    description=(
        "The version, permission and provenance plane over Windy Cloud. "
        "Agents are citizens here, not tourists wearing a human's token."
    ),
    version=get_build_info().version,
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(repos.router)
app.include_router(webhooks.router)


@app.middleware("http")
async def _count_requests(request: Request, call_next):
    """Heartbeat counts (requests, 4xx/5xx, refusals, p95). Never raises."""
    start = time.perf_counter()
    response = await call_next(request)
    tel = getattr(request.app.state, "telemetry", None)
    if tel is not None:
        tel.record_request(
            response.status_code,
            (time.perf_counter() - start) * 1000,
            refused=getattr(request.state, "refused", False),
        )
    return response


@app.exception_handler(RepairPointer)
async def _repair_pointer_handler(request: Request, exc: RepairPointer) -> JSONResponse:
    tel = getattr(request.app.state, "telemetry", None)
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    code = detail.get("code")
    if tel is not None and code in tel.auth_codes:
        # A refusal is a failure row (field-visibility rule 1). The caller is
        # unauthenticated by definition, so: system actor, no actor_id, and
        # the route TEMPLATE, never the concrete path.
        request.state.refused = True
        route = request.scope.get("route")
        tel.auth_failed(
            code=code,
            http_status=exc.status_code,
            caller=caller_class(request.headers),
            route=getattr(route, "path", None),
            upstream_status=getattr(exc, "upstream_status", None),
            synthetic=is_synthetic(
                request.headers, request.app.state.settings.windygit_synthetic_key
            )
            if hasattr(request.app.state, "settings")
            else False,
        )
    return JSONResponse(status_code=exc.status_code, content=exc.detail)


@app.exception_handler(RequestValidationError)
async def _validation_handler(_, exc: RequestValidationError) -> JSONResponse:
    """G8.3: EVERY error is a repair pointer. Including validation errors.

    FastAPI's default 422 body is machine-readable and human-hostile. It is also
    the single most common error an agent will hit, so it is the last place to
    drop the contract.
    """
    return JSONResponse(
        status_code=422,
        content={
            "code": "invalid_request",
            "speak": "Something in that request didn't look right, so we didn't act on it.",
            "machine_cause": f"request validation failed: {exc.errors()}",
            "remediation_tool": None,
        },
    )
