# Why login takes 18 seconds — measured, 2026-08-12

The SOTU calls the child-process DB bridge *"the single largest stability
liability under #8"* and scopes the fix as **468 call sites, multi-week**.

That scoping is wrong, and the measurements below say so. **You do not need to
touch 468 call sites.** You need to stop spawning a node process per query,
which is one function.

## The measurements

**One login makes 9 synchronous queries**, each spawning `node -e` via
`execFileSync` (`postgres-adapter.ts:114`):

| # | query | source |
|---|---|---|
| 1 | `findUserByEmail` | `statements.ts:11` |
| 2 | `mfa_secrets` lookup | `auth.ts` inline |
| 3 | `findDevice` | `statements.ts:24` |
| 4 | `touchDevice` *or* `countDevices` + `addDevice` | `statements.ts:25-35` |
| 5 | `updateUserSeen` | `statements.ts:20` |
| 6 | `generateTokens` → scope rows | `auth.ts:220` |
| 7 | `generateTokens` → product rows | `auth.ts:229` |
| 8 | `getDeviceList` | `auth.ts:384` |
| 9 | `logAuditEvent` INSERT | `identity-service.ts:43` |

**What each fork actually costs, measured inside the running container:**

| | Kit 0 (4 vCPU, load ~20) | Veron 1 (24 cores, idle) |
|---|---|---|
| bare `node -e "0"` | **1.70 – 1.99 s** | **0.01 s** |
| node + pg connect + `SELECT 1` | 1.89 – 3.19 s | — |

**Node startup is 170× slower on Kit 0, and it is essentially the entire cost.**
Adding a Postgres connect and a real query to a bare node start adds only
~0.2–1.2 s on top of ~1.8 s of interpreter boot.

    9 forks x ~1.8 s = ~16 s.   Observed login: 17–25 s.

## The conclusion that matters

There are **two independent multipliers**, and they compound:

1. **The adapter forks a process per query** — 9x on the login path.
2. **The box is saturated**, so each fork costs 1.8 s instead of 0.01 s — 170x.

Either one alone is survivable. Together they turn a sub-second operation into
eighteen seconds, and on 2026-08-12 they turned a retry loop into an
ecosystem-wide auth outage.

**Connection pooling barely helps.** The connection is not the cost; the
interpreter boot is. PgBouncer, `pg.Pool` on the sync path, or a warmer
Postgres would all leave ~1.8 s per query untouched.

## Box census (measured same day)

    54 containers, 301% CPU of 400% available, load average 20 on 4 vCPU

| | containers | CPU |
|---|---|---|
| dev / demo / test | 12 | **55%** |
| everything else | 42 | 246% |

Top consumers: `windymail-migrate-stalwart` 31%, `scenemachine-db-prod` 30%,
`account-server-account-postgres` 27%, `windy-synapse` 25%, `windy-directory`
20%.

**Be honest about this number:** stopping every dev/demo container reclaims 55%
of 301% — it takes the box from 75% to 61% steady CPU. That is real relief and
it is *not* a fix. Forty-two non-dev containers on four cores is the actual
condition.

## What to do, in value order

1. **Stop forking a node process per query.** `querySyncViaChild`
   (`postgres-adapter.ts:114`) is one function, and its interface —
   `querySync(sql, params)` — does not change. Replace the per-query
   `execFileSync` with a persistent worker holding a `pg.Pool`, using
   `worker_threads` + `SharedArrayBuffer` + `Atomics.wait` for the synchronous
   block. **Every one of the 468 call sites gets faster without being edited**,
   including the mail-lookup route that caused today's outage.
   Expected: login 18 s → well under 1 s, on this box, unchanged.
2. **Then** migrate route families to the async path at leisure. The sync path
   is still labelled legacy and should still die — but as cleanup, not as an
   emergency.
3. **Separately, unload Kit 0.** Move dev/demo off the box that runs identity,
   the CA, mail, Matrix and the broker. This is worth doing on its own merits
   regardless of the adapter.

**Do not do #2 first.** Migrating handlers one family at a time is weeks of
edits to the most critical code in the ecosystem, and it leaves every
un-migrated call site paying 1.8 s a query the whole time.

## Why this was not implemented in this session

Replacing the sync bridge is a subtle change (`Atomics.wait`, structured-clone
limits, worker lifecycle, failure fallback) in the single most critical file in
the ecosystem, made at the end of a long session, on a box that had already had
one outage that day. It deserves a fresh session, a real load test, and a
rehearsed rollback — not a tired commit.

The measurement is the deliverable. It converts a "multi-week, 468 call sites"
job into a one-function change, and that is worth more than a rushed attempt.
