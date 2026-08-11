# AGENTS.md — windy-git

Read this before touching anything. Then read `DNA_STRAND_MASTER_PLAN.md`, which is the source of truth.

## Current state

**GENESIS.** No code. No `make dev` yet — building it is codon **G0.8**.

The next work is Strand **G0** (cell substrate), then **G1** (Veron 1 host + Cloudflare Tunnel), then **G2** (Gitea, stock and branded), then **G3** (identity), then **G4** (storage). G0–G4 are sequential. G5–G12 are concurrent once G4 lands.

## The rules that will get you reverted if you break them

1. **Do not fork Gitea.** (D-2 / I-1.) Our code calls Gitea's REST API from our own service. Any patch to Gitea source goes in `patches/` as a numbered rebasable diff with a one-line justification, and `make check` fails past **3** files without an ADR.
2. **Never say "a Git."** (D-9 / I-9.) Git is not a countable noun. A moment in time is a *commit*; user-facing, it is a *version* or *save point*. `make check` greps for violations.
3. **Never touch Kit 0.** (D-4 / §7.8.) Not in v0, not in v1. Only Grant may overturn a never.
4. **No Stripe. No prices. No checkout.** (I-11.) This cell emits usage events; the Windy Cloud kernel owns the ladder.
5. **Never claim live while a provider is mock.** (I-8.) Every seam fails closed. `/health/full` reports what it can prove and nothing more.
6. **`repo_type` exists from migration 001.** (I-7.) Never inferred, never defaulted at read time, never retrofitted.
7. **Git objects on local disk, heavy bytes on R2. Never the reverse.** (I-3.)
8. **`/version` must be honest.** (I-12.) The commit sha is baked at image build; a runtime `COMMIT_SHA` env var is **ignored with a warning**. Nine of twelve sibling services cannot name their own commit — we will not be the tenth.
9. **Every invariant has a named test.** Cite the invariant in the test file header.
10. **An unverifiable codon is not done.** Every codon in the plan has an acceptance criterion. Finished-looking code without its acceptance test is not finished.

## House conventions

- Python 3.12 · FastAPI · pydantic-settings · Postgres schema `windgit` · own alembic, every migration with a tested downgrade.
- `make check` = `ruff` + `mypy` + `pytest` + membrane-drift + capabilities-drift + `/version` honesty + vocabulary audit. **The local gate IS the merge gate.**
- Errors are 4-field repair pointers: `{code, speak, machine_cause, remediation_tool}`. No exceptions, including validation errors.
- Every tool response carries `state_proof` + `next_actions`.
- Telemetry `actor_type` comes from the enum `{human, agent, system}`. **`'service'` is not legal** — it 422s and silently drops the whole batch. A sibling service is losing telemetry to exactly this today.
- Runner labels are explicit and pinned. **`ubuntu-latest` is banned** — all four `windy-registry` workflows use it and every run fails.

## Membrane

Calls out, calls in, and events are **enumerated in invariant I-2** and mirrored in `docs/MEMBRANE.v1.md`. Adding a call means editing I-2 first, then the doc, then the code. Not the other way round.

## What needs Grant

See §7 of the plan. Short version: opening to any non-Grant user · any pricing · advancing off the GitHub mirror · marketing provenance before the upstream integrity fix lands · a hard fork of Gitea · the marketing site · enabling `repo_type=model` in production · anything involving Kit 0.
