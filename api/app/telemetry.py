"""Field telemetry to the admin ledger (admin.windyword.ai) — step 2, 2026-09-23.

Shapes are DECLARED with Telemetry Boss (the ledger owner); the server
quarantines any row that doesn't match, so never add a key or a code here
without re-declaring it first:

  service.boot       once per process start   {commit_sha, version, environment}
  service.health     hourly, in-process       interval_s, uptime_s, requests,
                                              errors_5xx, errors_4xx,
                                              refusals_4xx, p95_ms
  forge.auth.failed  every refused request    {code, http_status, caller,
                                              route?, upstream_status?}

Refusals come first: a refused caller is the most expensive silent failure
("the button did nothing"). An UNAUTHENTICATED caller has no trustworthy id, so
per the all-lanes actor rule the row is actor_type "system", no actor_id, and
the caller class goes in metadata.caller.

Privacy: codes, statuses, route TEMPLATES, counts, durations. Never a passport
number, an email, a token fragment or a concrete path with names in it.

No token → nothing is sent and nothing is buffered. A failed flush keeps the
rows (bounded) and retries on the next tick; it never raises into a request.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import time
import urllib.request
from datetime import UTC, datetime

log = logging.getLogger("windy-git.telemetry")

PLATFORM, SERVICE = "windy-git", "api"
FLUSH_EVERY_S = 60
HEALTH_EVERY_S = 3600
MAX_BUFFER = 5000
MAX_LATENCY_SAMPLES = 20000

# The declared forge.auth.failed code enum (Telemetry Boss, 2026-09-23). A code
# outside this set is NOT a refusal row — it counts in errors_* instead.
AUTH_CODES = frozenset(
    {
        "not_signed_in",
        "token_invalid",
        "token_unrecognised",
        "ept_invalid",
        "passport_revoked",
        "passport_unresolvable",
        "agent_read_only",
        "agent_rate_limited",
        "quota_exceeded",
        "trust_unavailable",
        "throttle_unavailable",
        "service_token_invalid",
        "service_auth_unconfigured",
    }
)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat().replace("+00:00", "Z")


# Ecosystem convention (Telemetry UPDATE 4): synthetic traffic travels END TO
# END. Originators (canaries, probes, journeys) send `X-Windy-Synthetic: 1`;
# every service marks all of that request's rows synthetic:true AND forwards the
# header on every downstream call. Absent = real. Never strip it, never set it
# on real traffic. The label separates rows — it never suppresses them.
SYNTHETIC: contextvars.ContextVar[bool] = contextvars.ContextVar("windy_synthetic", default=False)


def is_synthetic(headers) -> bool:
    return bool((headers.get("x-windy-synthetic") or "").strip())


def synthetic_headers() -> dict:
    """Merge into every downstream request made while serving this one."""
    return {"X-Windy-Synthetic": "1"} if SYNTHETIC.get() else {}


def caller_class(headers) -> str:
    """Declared values: anonymous_human | anonymous_agent | unknown."""
    from api.app.ept import looks_like_ept

    if headers.get("x-service-token"):
        return "unknown"
    auth = headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return "unknown"
    return "anonymous_agent" if looks_like_ept(auth.split(" ", 1)[1].strip()) else "anonymous_human"


class Telemetry:
    def __init__(
        self,
        url: str,
        token: str,
        *,
        environment: str = "",
        commit_sha: str | None = None,
        version: str = "",
    ) -> None:
        self.url, self.token = url, token
        self.environment, self.commit_sha, self.version = environment, commit_sha, version
        self.started = time.time()
        self.buffer: list[dict] = []
        self.auth_codes = AUTH_CODES
        self._reset_window()

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def _reset_window(self) -> None:
        self.window_start = time.time()
        self.requests = self.errors_5xx = self.errors_4xx = self.refusals_4xx = 0
        self.latencies_ms: list[float] = []
        # UPDATE 7: rows the ledger quarantined (it still answers 202) and rows
        # this process lost (buffer overflow). Non-zero = a bug in this emitter.
        self.quarantined = self.dropped = 0

    # ---- recording (never raises into a request) --------------------------
    def record_request(self, status: int, duration_ms: float, *, refused: bool = False) -> None:
        self.requests += 1
        if status >= 500:
            self.errors_5xx += 1
        elif refused:
            self.refusals_4xx += 1
        elif status >= 400:
            self.errors_4xx += 1
        if len(self.latencies_ms) < MAX_LATENCY_SAMPLES:
            self.latencies_ms.append(duration_ms)

    def _event(self, event_type: str, metadata: dict, *, ts: float | None = None) -> None:
        if not self.enabled:
            return
        self.buffer.append(
            {
                "ts": _iso(ts or time.time()),
                "platform": PLATFORM,
                "service": SERVICE,
                "event_type": event_type,
                "actor_type": "system",
                "metadata": metadata,
            }
        )
        if len(self.buffer) > MAX_BUFFER:
            self.dropped += len(self.buffer) - MAX_BUFFER
            del self.buffer[: len(self.buffer) - MAX_BUFFER]

    def boot(self) -> None:
        meta = {"version": self.version, "environment": self.environment}
        if self.commit_sha:  # unknown is absent, never invented (I-12)
            meta["commit_sha"] = self.commit_sha
        self._event("service.boot", meta, ts=self.started)

    def auth_failed(
        self,
        *,
        code: str,
        http_status: int,
        caller: str,
        route: str | None = None,
        upstream_status: int | None = None,
        synthetic: bool = False,
    ) -> None:
        if code not in AUTH_CODES:
            return
        meta: dict = {
            "code": code,
            "http_status": int(http_status),
            "caller": caller,
            "synthetic": bool(synthetic),
        }
        if route:
            meta["route"] = route
        if upstream_status is not None:
            meta["upstream_status"] = int(upstream_status)
        self._event("forge.auth.failed", meta)

    def health_row(self) -> dict:
        now = time.time()
        meta = {
            "interval_s": int(now - self.window_start),
            "uptime_s": int(now - self.started),
            "requests": self.requests,
            "errors_5xx": self.errors_5xx,
            "errors_4xx": self.errors_4xx,
            "refusals_4xx": self.refusals_4xx,
            "telemetry_quarantined": self.quarantined,
            "telemetry_dropped": self.dropped,
        }
        if self.latencies_ms:  # no traffic = no p95, not a fake 0
            s = sorted(self.latencies_ms)
            meta["p95_ms"] = int(s[min(len(s) - 1, int(0.95 * (len(s) - 1) + 0.5))])
        return meta

    def health(self) -> None:
        self._event("service.health", self.health_row())
        self._reset_window()

    # ---- sending ------------------------------------------------------------
    def _post(self, batch: list[dict]) -> tuple[int, dict]:
        req = urllib.request.Request(
            self.url,
            data=json.dumps({"events": batch}).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "windy-git-api-telemetry/1",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            try:
                body = json.loads(r.read() or b"{}")
            except ValueError:
                body = {}
            return r.status, body if isinstance(body, dict) else {}

    async def flush(self) -> None:
        if not self.enabled or not self.buffer:
            return
        batch = self.buffer[:500]
        try:
            status, body = await asyncio.to_thread(self._post, batch)
        except Exception as exc:  # noqa: BLE001 - telemetry must never take the API down
            log.warning("telemetry flush failed (%d rows kept): %s", len(self.buffer), exc)
            return
        if 200 <= status < 300:
            del self.buffer[: len(batch)]
            self.note_quarantine(body)

    def note_quarantine(self, body: dict) -> None:
        # 202 does NOT mean every row landed: refused rows are dead-lettered.
        q = body.get("quarantined")
        if isinstance(q, int) and q > 0:
            self.quarantined += q
            log.warning("telemetry: %d row(s) QUARANTINED by the ledger: %s", q,
                        "; ".join(map(str, body.get("rejections") or [])) or "no reason given")

    async def run(self) -> None:
        """The one in-process timer: flush every minute, heartbeat every hour."""
        last_health = time.monotonic()
        while True:
            await asyncio.sleep(FLUSH_EVERY_S)
            if time.monotonic() - last_health >= HEALTH_EVERY_S:
                self.health()
                last_health = time.monotonic()
            await self.flush()
