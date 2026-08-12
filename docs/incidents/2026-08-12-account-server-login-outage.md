# Incident — account.windyword.ai login outage, 2026-08-12

**Found while adding a dashboard tile. Not caused by Windy Git.**
Recorded here because Windy Git is the ecosystem's verification cell and this is
the failure mode its CI exists to catch earlier.

## Impact

`POST /api/v1/auth/login` timed out for at least ~50 minutes (45 s+, no
response). `/health` and `/.well-known/jwks.json` also timed out for part of it.
This is the identity service every Windy product authenticates against — Word,
Chat, Mail, Cloud, Eternitas hand-offs, and Windy Git's own OIDC.

## Root cause — two faults multiplying

**1. A hot retry loop.** `windy-agent-roster` called
`POST /api/v1/identity/mail/address-by-windy-id` for every identity it knows,
got a timeout, retried immediately, and never backed off. Measured: **74
failures/minute, 2,220 in 30 minutes**, sustained. Every log line read
`Pro mail-lookup failed for <uuid>: The operation was aborted due to timeout`.

**2. Every one of those calls is expensive.** `account-server/src/db/postgres-adapter.ts:114`
runs `execFileSync` with a **new `node -e` child process per query** — new pg
client, new TCP connection, new TLS handshake, blocking the event loop up to
30 s. Confirmed live: a host process reading
`node -e const { Client } = require('pg'); ...`. Each 404 cost 0.6–2.1 s of
blocking work.

**The multiplication is the story.** Either alone is survivable. Together they
form a positive feedback loop: slow responses cause timeouts, timeouts cause
immediate retries, retries add load, load makes responses slower. The listening
socket inside the container showed **`Recv-Q 510`** — 510 connections accepted
by the kernel that node was too blocked to pick up. Login sat in that queue.

Background condition: **54 containers on a 4-vCPU box**, 12 of them dev/demo
(`eternitas-dev-*`, `windymind-dev-*`, `nacholos-demo-*`, `nachope-demo-*`).
Baseline load 17–19. That is the amplifier — a process fork is cheap on an idle
box and ruinous on a saturated one.

## Resolution

`docker stop windy-agent-roster` at 16:50:57Z. Reversible with `docker start`.

| | before | after |
|---|---|---|
| login | timeout at 45 s+ | **HTTP 200 in ~18 s** |
| `/health` | timeout | 200 in 0.28 s |
| jwks | timeout | 200 in 0.16 s |
| account-server CPU | 168–210 % | out of the top 4 |

**18 s is restored, not healthy.** A login should be well under a second. That
number is the fork-per-query adapter under a loaded box, and it is what remains
after the loop was removed.

## What is still true

- **`windy-agent-roster` is stopped.** Agent chat is down until someone starts
  it. Bringing it back **without fixing the retry** re-creates this outage.
- The mail-lookup 404 itself is unexplained. The route exists
  (`identity.ts:1014-1022`, reads `x-service-token`). Either the identities are
  genuinely absent or the caller sends the wrong shape — worth knowing before
  the roster returns.
- The postgres adapter is unchanged. It is the single largest stability
  liability in the ecosystem, 468 call sites, and a multi-week job.

## What would have caught this

Nothing did. There is no alerting on account-server latency, and the fleet
canary has been dead since 2026-07-03. The service was `(unhealthy)` with a
**failing healthcheck streak of 74** and nothing said so.

## Recommendations, ordered

1. **Fix the retry before restarting the roster** — exponential backoff and a
   circuit breaker. A client that retries a failing dependency at 74/min is a
   denial-of-service against your own identity service.
2. **Alert on the healthcheck.** A 74-deep failing streak on the identity
   service should page, not sit.
3. **Move dev/demo off the production box.** 12 containers of non-production
   load on the box that runs identity, the CA, mail, Matrix and the broker.
4. **Then** the postgres-adapter migration. Hottest paths first — login is the
   obvious first path.
