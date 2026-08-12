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

## Resolution — two steps

**1. Stop the bleeding.** `docker stop windy-agent-roster` at 16:50:57Z. Login
recovered from timeout to HTTP 200 immediately.

**2. Ship the real fix and bring agent chat back.** The retry fix already
existed: a parallel session diagnosed the same incident from the windy-pro side
and landed `c79f196` — *"fix(roster): back off failed mail lookups instead of
retrying every 30s forever" (#172)* — with a test
(`services/agent-roster/tests/mail-lookup-backoff.test.js`). **Kit 0 was one
commit behind and did not have it.** That is the whole reason the loop ran.

Deployed by fast-forwarding `/root/windy-chat` `ac61db6 → c79f196` and
rebuilding **only** `agent-roster` (`--no-deps`; nothing else on the box
touched). Deliberately `git merge --ff-only`, never `reset --hard` — this
checkout has a documented history of local edits a hard reset would silently
eat.

The fix caches failures per owner with exponential backoff (60 s → 30 min cap)
and suppresses logging after three attempts. Observed working in production:
`attempt 2, backing off 120s`.

| | before | after |
|---|---|---|
| login | timeout at 45 s+ | **HTTP 200 in ~18 s** |
| `/health` | timeout | 200 in 0.28 s |
| jwks | timeout | 200 in 0.16 s |
| **account-server CPU** | **168–210 %** | **0.00 %** |
| roster mail-lookup failures | 74/min | **0/min** |
| account-server calls to that route | ~50/min | **0/min** |
| agent chat | down (stopped) | **back up, healthy** |

**18 s is restored, not healthy.** A login should be well under a second. That
number is the fork-per-query adapter under a loaded box, and it is what remains
after the loop was removed.

## What is still true

- **The mail lookups still fail** — the backoff stops them amplifying, it does
  not make them succeed. Each owner now retries once per backoff window instead
  of every 30 s. The underlying 404/timeout is unexplained. The route exists
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

1. ~~Fix the retry~~ — **done**, `c79f196`, deployed 2026-08-12.
2. **Alert on the healthcheck.** A 74-deep failing streak on the identity
   service should page, not sit.
3. **Move dev/demo off the production box.** 12 containers of non-production
   load on the box that runs identity, the CA, mail, Matrix and the broker.
4. **Then** the postgres-adapter migration. Hottest paths first — login is the
   obvious first path.


## The lesson worth keeping

**The fix was written, tested, reviewed and merged — and the outage happened
anyway, because Kit 0 was one commit behind.** A merged fix that has not reached
production is not a fix; it is a belief.

That is the same root cause both August audits named — *nothing anywhere checks
whether a decision reached production* — arriving as a live outage rather than a
finding in a report. Deploy verification is not paperwork.

## Diagnostic note for whoever is next

`docker logs` / `docker stats` loops across 54 containers cost real CPU on a
saturated box. Load rose from 17 to 24.9 while this was being investigated, and
some of that was the investigation. Take one clean measurement, then back off.
