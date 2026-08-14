# Second-auditor review of the Windy Git build (Fable, 2026-08-13)

A fresh-eyes trace of Opus's build, **verified against the live system** rather
than against the transcript's own account. One critical finding was fixed during
the review; the rest are recorded here with proportion.

## Fixed during this review

### 🔴 Agent authentication was not authentication (CRITICAL, was live+public)

`auth.py` read the passport out of a bearer token **without verifying the EPT
signature**, asked Eternitas *"is this passport reputable?"*, and seated the
caller on a yes. That answers reputation, not possession.

**Proven by exploit:** a forged `alg:none` token naming a passport lifted from
the logs returned **HTTP 200** as that agent on the public API. Anyone who knows
a passport number (they appear in logs, the lockbox, and revocation messages)
could impersonate that agent.

The human path already failed closed for exactly this reason
(`require_verified_jwt`) — but the gate sat *after* the agent branch returned, so
it protected the safe path and skipped the exploitable one.

**Fix:** the agent path now fails closed in production, *before* the trust
lookup, mirroring the human path. Reopens automatically when the ES256/JWKS
verifier (G3.2/G9.1) is built. Re-tested live: forged token now `503`. Added a
**behavioral** test (forged token through real `get_caller` must raise) and a
**canary probe** (forged token must stay refused; a 2xx pages).

## Open findings (recorded, not yet fixed)

### 🟠 The EI throttle table is dead code (MEDIUM)
`BAND_MULTIPLIER` and `rate_*_per_day` (G3.4) are defined and **read by
nothing** — verified by grep. An authenticated agent has no rate limit at all.
When the agent path reopens with real verification, wire the throttle before it
does, or a single agent can hammer repo-create/token-mint unbounded.

### 🟠 The test suite is mostly source-string assertions (MEDIUM)
56 invariant tests carried **~86 "does the source contain this string"**
assertions and **zero** that exercised the auth decision. `make check` green
means the code still *contains* the patterns, not that it *behaves*. The auth
bypass passed every test. **Direction:** convert the top ~10 guards into
behavioral tests against an ephemeral instance (this review added the first
two). The live-curl proofs Opus ran were excellent but were never captured, so
they don't defend against regression.

### 🟠 Privileged dind sits beside broad-scoped tokens (MEDIUM — Grant-aware)
`dind privileged=true`, and the host `.env` holds the account-wide R2 token and
a GitHub PAT, on the same box running untrusted CI. Escape from privileged dind
→ host fs → both tokens. Grant waived *minting a new token* for the sandbox; the
specific escalation path (privileged-dind-next-to-god-token) is a separate
decision. Lowest-effort mitigations: rootless/sysbox runner, or move the two
tokens out of the API container's env into a path the API reads but the runner
host does not share.

### ✅ Revocation — was WORSE than flagged, now fixed (was CRITICAL once agent auth reopened)
Re-examined after real agent auth went live, and the finding grew teeth. A
revoked passport returns **HTTP 200, `status: revoked`, `band: unproven`,
`allowed_actions: []`** (verified live). `resolve_passport` keyed refusal only on
HTTP 4xx and `band=="untrusted"`, so it returned band `unproven` and **seated the
revoked agent** — revocation was not enforced on the live path at all. The
webhook everyone worried about was only ever cache-invalidation; the live trust
lookup was the real gate, and it wasn't checking.

**Fixed:** `decide_trust` now allows only `status=="active"`; revoked / suspended
/ frozen / unknown all refuse, fail-closed. Revocation now takes effect on the
next request, no webhook required. Eternitas additionally refuses to mint EPTs
for revoked bots, so the residual window was a pre-existing ~365-day token —
exactly what the live check now stops. 79 tests green including the full wiring.

The webhook (`webhook_secret` lost to the 500) is now genuinely LOW: it only
matters for locally-issued credentials/grants (G6.3, not built), and it is no
longer the thing standing between a revoked agent and access.

## What is genuinely strong (and worth protecting)

- **Honesty engineering is real:** fail-closed providers, `/health` refusing to
  claim green it can't prove, I-12's baked-sha proven live against a hostile env
  var. This directly cures the parent ecosystem's #1 root cause.
- **Incident response was first-rate:** the login outage was root-caused to a
  510-deep accept queue and a per-query node fork, with the "one function, not
  468 call sites" reframe that is correct and valuable.
- **It caught its own mistakes** — the mirror direction and the push-triggered
  deploy workflows, the latter *before* they fired.
- **The DR posture is right:** 131 read-only mirrors (no CI, zero deploy risk) +
  a rehearsed restore. Rehearsed restore is rare in this ecosystem; keep it.

## The one-line lesson

Opus aimed its considerable discipline at **honesty and documentation**
(excellent) more than at **adversarial correctness** — so the property that
mattered most, *is an agent really that agent*, shipped inverted and untested.
The remedy is not more process; it is **behavioral tests and canary probes for
the security-critical paths**, so verification persists instead of living in a
transcript.
