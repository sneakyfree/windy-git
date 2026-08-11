# windy-git — DNA Strand Master Plan

**v0.1.0 · 2026-08-11 · GENESIS**
Sources: Grant's 2026-08-11 vision-crystallization session (4 turns) · the two 2026-08-09 State of the Union audits (Opus 24-agent / Fable 18-agent) + `RECONCILIATION.md` · `windy-cloud-sites` cell-boundary doctrine (locked 2026-07-12/15) · measured hardware and repo-footprint survey, 2026-08-11.

**Strands G0–G12. Codons are atomic — no judgment calls are left for the ribosome.** Every `env:` value is a shipped default, not a suggestion. Every codon has an acceptance test. If a codon cannot be verified, it is not done.

---

## §0 Mission

**Windy Git is the version, permission, and provenance plane over Windy Cloud — and a code and model host that rolls out the red carpet for Eternitas-credentialed agents.**

GitHub is hostile to agents in exactly the way Gmail is hostile to bots: an agent there wears a human's clothes, borrows a human's token, inherits a human's permissions, and has no independent standing, no spend limit, no revocation story, and no verifiable track record. Windy Git makes the agent a **citizen**: it pushes as itself, under its own passport, with its own scoped credential, its own limits, and a signature anyone downstream can check.

Underneath, it is the same substrate for three things GitHub and Hugging Face split between them:

| Repo type | Contents | Ships |
|---|---|---|
| `code` | source, sites, projects | v1 |
| `model` | weights, LoRA adapters, model cards | v2 |
| `dataset` | corpora, eval sets | v2 |

**Second mission, equal in weight and earlier in time:** Windy Git is the ecosystem's missing **verification machinery**. Both August audits converged on one root cause — *nothing anywhere checks whether a decision reached production* — because GitHub Actions is billing-locked and private repos cannot run Actions at all, not even on self-hosted runners. Windy Git brings CI back. That payoff arrives on day one with zero customers and justifies the entire build on its own.

## §0.5 Storage-Kingdom doctrine (ecosystem law — inherited verbatim)

Every repo, every kept version, every uploaded weight adds gravity toward the ONE Windy Cloud storage bill (kernel tiers). Repo storage counts against kernel storage plans. Export-everything builds the trust that keeps data here. **This cell never invents a price.** See I-11.

## §0.6 FUTURE-PROOF DOCTRINE: design for Fable 7.5 (ecosystem law — vendored verbatim from the domains/sites plans)

Capability-completeness (throttle by trust, never by omission; "if it's in the runbook, it's a tool") · `/.well-known/windy-capabilities.json` discovery · errors as 4-field repair pointers `{code, speak, machine_cause, remediation_tool}` · `state_proof` + `next_actions` on every tool response for verifiable one-shot pipelines · capability classes read → act-own → repair-own (Gold+) → operator (role-gated) with I-10 always-confirm unbroken · repo agent-operable (AGENTS.md, `make dev`, deterministic tests).

## §0.7 THE NINE LOCKED DECISIONS

These were reasoned to conclusion on 2026-08-11 and are **not to be re-litigated** without an ADR that names the decision it overturns. Each records the argument that won, because a decision without its reason decays into a preference.

**D-1 · Separate repo, separate brand, shared billing.**
Windy Git is its own cell — own repo, own service, own database, own deploy cadence — a sibling to `windy-cloud-sites` / `-domains` / `-vps`. It carries a real brand because "git" is a universal untranslated noun in every developer language on earth (German *Git*, Spanish *Git*, Russian *гит*, Japanese ギット, Hindi/Chinese *Git*) and because the adoption curve for version control among AI-assisted builders is on its flat part now — which is when you build infrastructure, not when it spikes.
**But it bills through the Windy Cloud kernel ladder and never invents its own.** The ecosystem already carries six unreconciled Stripe integrations and two simultaneously-purchasable price ladders. GitHub bills through Microsoft; Windy Git bills through Windy Cloud. See I-11.

**The brand has its own apex, purchased 2026-08-11:** `windygit.com`, on Cloudflare, zone `9d8637dcac3415607b2116e6099fe567`, status active, **Free plan**. Free Universal SSL covers `windygit.com` and `*.windygit.com` — one level. **Every hostname in this plan is therefore a single-level subdomain of the apex, deliberately**, so no Advanced Certificate Manager subscription is ever required (see the G1.3 trap). This settles D-1 in hardware: Windy Git is a brand with its own front door, billing through the Cloud kernel behind it.

**D-2 · Membrane, not merge. Do not hard-fork Gitea.**
Run **stock Gitea**. Brand it with supported custom templates and CSS. Put identity in front via OIDC. Build every differentiator — the permissions plane, the Eternitas layer, the MCP surface, the model hub — as **our own services calling Gitea's REST API**. A hard fork means owning merge conflicts forever against a project that ships every 2–3 months including security fixes; for a small team that becomes the entire job within a year. This is the cell-membrane doctrine applied to a dependency: **keep it at an API boundary, not in a source tree.** A hard fork is permitted later only when a written list names the specific files that must change and why an API cannot reach them.

**D-3 · Gitea (MIT), not Forgejo (GPLv3 ≥ v9).**
Both are excellent; Forgejo arguably has better governance and real ActivityPub federation work. The license decides it. GPLv3 does **not** trigger on running a service — that is AGPL, and this is widely gotten wrong — but it **does** trigger on distributing a binary. "Self-host license + support" is a monetization line (§9) and the fat-installer doctrine ships binaries, so GPLv3 would force publication of our modifications. MIT does not. MIT obliges only that the original copyright notice and license text travel with distributed copies; it does **not** oblige us to advertise the lineage, does not restrict monetization, and does not require publishing our changes. Gitea's trademark must be stripped from all branding.
⚠️ Re-verify the current license text of both projects before the first commercial dollar. Projects relicense.

**D-4 · Veron 1 first. Cloudflare Tunnel. Never Kit 0.**
Measured 2026-08-11 — Veron 1: 24 cores, 251 GB RAM, 978 GB free, load average 1.52 (6% utilization), $0/month. Kit 0: 4 vCPU, 16 GB, measured load **7.62** while running identity, the CA, inbound SMTP on :25, Matrix, the broker, the admin console and storage.
Kit 0 is disqualified on four independent grounds, any one of which is sufficient: **(a)** CI executes arbitrary workflow code, and co-locating that with the passport database, the credential broker, `MIND_ADMIN_TOKEN` and the Eternitas super-admin password is a security-boundary violation — one poisoned transitive dependency reaches the certificate authority; **(b)** SOTU §5.6 finding #1 is already *"Kit 0. Everything."* — today a Kit 0 loss costs the company but the source survives on GitHub; putting git there makes one box loss total; **(c)** a KVM-8 upgrade takes 190% subscription to ~95%, which pays off an overdraft rather than creating headroom; **(d)** it makes the most fragile asset more expensive without making it less fragile.
Two small boxes beat one large box for this workload — failure isolation, security boundary, independent reboot — which is the cell doctrine applied to hardware.

**D-5 · Three storage tiers, and they are not interchangeable.**
Git's object database **must** live on a POSIX filesystem; a clone touches thousands of small objects and object-store round-trips make it unusable. Everything heavy goes to R2 where egress is $0. Measured 2026-08-11: **61 repos = 11 GB of working trees but only 0.63 GB of git objects.** All source code, all history, all branches, forever, is under a gigabyte. Model weights are 200× that per model.
The decisive consequence: **with LFS on R2, heavy traffic never traverses Grant's residential upstream.** Only git protocol chatter (kilobytes) and web UI cross the tunnel. This is what makes a lab machine a legitimate v0 host.

**D-6 · Repo type is a first-class column from migration 001.**
`repo_type ∈ {code, model, dataset}` exists in the schema, the API and the UI before the first repo is created, even though only `code` ships in v1. Cheap now; near-impossible to retrofit. A Hugging Face repo *is* a git repo with LFS and a model card — the consolidation is metadata and UI, not infrastructure.

**D-7 · `HF_ENDPOINT` compatibility is the cheapest real moat available.**
Hugging Face's Hub is closed source and nobody has cloned it, but its protocol is git + LFS + a documented REST API, and the `huggingface_hub` client respects an `HF_ENDPOINT` environment variable. Implement enough of that API and **unmodified existing tooling** — `from_pretrained()`, `snapshot_download()` — talks to our hub. That is the `from_pretrained` hook, which is HF's actual moat, obtained for the price of a compatibility shim instead of a network.
**Scope discipline is law:** host our own models and our customers' fine-tunes and adapters. **Never mirror the open model ecosystem.** LoRA adapters are 50–500 MB, so 2,500 Traveler pairs is ~125 GB–1.25 TB ($2–19/mo). A single 70B model in fp16 is ~140 GB. A general mirror is petabytes of paying for strangers' downloads and buys nothing.

**D-8 · The permissions plane ships before the git protocol.**
Verified 2026-08-11: `WindyCloud/api/app/routes/storage.py` and its models contain **zero** occurrences of `share`, `permission`, `acl`, `collaborat`, `seat`, `version`, `snapshot`, `history` or `revision`. Windy Cloud is pure single-owner cold storage. The shelter is not a feature bolted onto something that has one — **it fills a hole that has never been filled.**
Meanwhile the ecosystem is already reinventing versioning badly in three places: `windy-cloud-sites` hand-rolled `POST /{site_id}/versions` + `rollback` for websites only; `account-server` has `hatch_sessions` as an append-only ledger; the desktop's monotonic build registry has **forked three ways** (main 12, overnight 34, wave-44 56). One shared plane consolidates three ad-hoc implementations. **This is a Principle #4 win, not a violation** — and it is the argument to cite when anyone calls this cell portfolio bloat.
So: **v0 = permissions + version history over any Windy Cloud folder, no git vocabulary and no git protocol.** v1 = the same store starts answering `git clone`. This delivers "I want someone to help with my website" in weeks and de-risks everything after it.

**D-9 · VOCABULARY LAW.**
**"Git" is never a countable noun.** There is no such thing as "a Git." Git is the program. The moment-in-time is a **commit**; a named one is a **tag** or a **release**; the container is a **repo**. Saying "a Git" is the tell that separates people who use it from people who have read about it, and it will cost credibility with precisely the developer audience this product is for. There is a second edge: *git* is British slang for a contemptible person — which is why Torvalds chose it, self-deprecatingly — so "tracking your Gits" reads badly to a Commonwealth ear.
**Product name: Windy Git. Always.** User-facing word for a snapshot: **"version"** or **"save point"** for the general audience, **"commit"** for developers. This law binds all copy, all UI strings, all documentation, all marketing, and all stage material. See I-9 and the G12.6 copy audit.

---

## §1 Invariants

Numbered because code cites them. Changing one requires an ADR that names it.

1. **I-1 · Gitea is a component, never a merged tree.** Our code lives in our services and calls Gitea's REST API. Any patch to Gitea source lives in `patches/` as a numbered, rebasable diff with a one-line justification, and `make check` fails if `patches/` grows past **3** files without an ADR.
2. **I-2 · The membrane is ENUMERATED.**
   **Calls out:** `windy-cloud` kernel `GET /api/v1/storage/objects` + `HEAD` (read user objects to version them) · `windy-cloud` `POST /api/v1/storage/quota/check` · `eternitas` `GET /api/v1/trust/{passport}` (band + allowed_actions) · `eternitas` `GET /api/v1/registry/{passport}/integrity` · `account-server` OIDC discovery + JWKS · `windy-cloud-sites` `POST /api/v1/sites/{id}/versions` (publish docs from a repo).
   **Calls in:** `POST /internal/repo-from-folder` (Cloud portal: git-enable a folder) · `POST /internal/mirror-status` (ops).
   **Events out:** `repo.created`, `repo.pushed`, `release.published`, `model.published`, `ci.completed`.
   **Events in:** `passport.revoked` (fail-closed), `storage.quota.exceeded`, `identity.created`.
   This list is the complete surface. Additions edit this invariant **first**, then `docs/MEMBRANE.v1.md`, mirrored in both repos.
3. **I-3 · Git objects local, heavy bytes remote. Never the reverse.** Git object databases and Postgres live on local NVMe. LFS, releases, packages, artifacts, archives and avatars live on R2. No code path may place a git object store on object storage or an LFS blob on the host disk.
4. **I-4 · Never a one-way door.** Every repo push-mirrors to GitHub, continuously, from the first commit. Mirror health is a monitored, alerting signal — not a hope. A mirror lag over **60 minutes** raises a P2.
5. **I-5 · CI never shares a kernel with identity.** Runners execute untrusted code and are isolated from Eternitas, mail, Matrix and the broker by machine boundary, not by container boundary. No runner may hold a credential scoped beyond its own job.
6. **I-6 · EPT parity plus asymmetry.** An Eternitas passport in good standing gets full human parity — every button a human can push, an agent can push. No passport gets flagged, challenged and rate-limited. **Never audience-gate an EPT.** Issuer is `eternitas.ai`. Where `windy-cloud-sites/api/app/services/entitlements.py:70-84` silently demotes a tiered agent to FREE, we do the opposite and there is a test proving it.
7. **I-7 · `repo_type` exists from migration 001.** Never inferred, never defaulted at read time, never added later.
8. **I-8 · Never claim live while a provider is mock.** Inherited from the `edge_live` gate (`windy-cloud-sites`, commit a8ff948) and the registrar seam that raises `RuntimeError("Refusing to pretend")`. Every provider seam here — R2, Gitea API, Eternitas, tunnel — fails **closed** and refuses to report a healthy state it cannot prove. The domains cell shipped a portal on a mock and told the public google.com was available for $18. That failure mode is banned by construction.
9. **I-9 · Grandma-words everything, hardest on failure**, and the D-9 vocabulary law binds every string. Failure copy names the fix: *"Your project is safe — that save didn't go through. Tap Undo, or ask your helper."*
10. **I-10 · Always-confirm for irreversibles.** Delete-repo, force-push to a protected branch, rotate-token, revoke-collaborator, delete-release. Agent-initiated irreversibles go through CONFIRM_FLOW.v1. Owner-agent ordinary writes are `auto_allow`.
11. **I-11 · One billing ladder, and it is not ours.** This cell emits usage events and quota hooks. It **never** creates a Stripe product, price, or checkout. Six unreconciled Stripe integrations and two live colliding ladders are existing findings; this cell adds zero.
12. **I-12 · `/version` must be honest, or the service refuses to boot.** Nine of twelve live services cannot name their running commit; one reports *another repo's* commit. Root cause per the 08-10 claims ledger: hardcoded `COMMIT_SHA` pins in `/opt/*/.env` overriding the build arg. Here the commit sha is baked into the image at build time as a build arg, read from the artifact's own stamp, and **an env-var override is ignored with a loud warning**. `make check` fails if `/version` disagrees with `git rev-parse HEAD` in CI.
13. **I-13 · The plane is not the substrate.** Windy Git never owns a user's bytes. Windy Cloud stores; Windy Git versions, permits and proves. A deploy of this cell can therefore never lose a user file — and there is a chaos test that proves it (G12.4).

---

## §2 Non-goals (hard, v1)

No mirroring the public model ecosystem (D-7) · no public code search across other people's repos · no issue tracker beyond Gitea's stock one · no wiki product · no package registry beyond Gitea stock · no federation/ActivityPub v1 · no self-hosted installer v1 · no mobile app · **no Stripe anything, ever, in this repo** (I-11) · no email hosting · no hard fork of Gitea (D-2).

---

## §3 Architecture snapshot

```
                    ┌──────────────── Cloudflare ────────────────┐
   git / https ────►│  Tunnel (outbound-only, no open ports)     │
                    │  zone windygit.com (9d8637dc…) · Free SSL  │
                    │  app. · api. · models.  (single-level)     │
                    └────────────────────┬───────────────────────┘
                                         │
        ┌────────────────────────────────▼──────────────────────────────┐
        │  VERON 1 · 24 cores · 251 GB · NVMe          (v0 host, $0)    │
        │                                                               │
        │  ┌─────────────┐   REST    ┌──────────────────────────────┐   │
        │  │ Gitea       │◄──────────┤ windy-git-api  (OUR service) │   │
        │  │ :3000 stock │           │  · permissions plane (G5)    │   │
        │  │ MIT, unforked│          │  · Eternitas/EPT layer (G3)  │   │
        │  └──────┬──────┘           │  · MCP surface (G8)          │   │
        │         │                  │  · provenance (G9)           │   │
        │  ┌──────▼──────┐           │  · HF-compat API (G10)       │   │
        │  │ git objects │           └───────────┬──────────────────┘   │
        │  │ + Postgres  │                       │                      │
        │  │ local NVMe  │           ┌───────────▼──────────────────┐   │
        │  └─────────────┘           │ act_runner ×N (isolated)     │   │
        │       ~1-10 GB             └──────────────────────────────┘   │
        └───────────────────────────────┬───────────────────────────────┘
                                        │  S3 API
              ┌─────────────────────────▼──────────────────────────┐
              │  CLOUDFLARE R2 · LFS · releases · packages ·        │
              │  CI artifacts · archives · avatars · bundles        │
              │  $0.015/GB-mo · ZERO EGRESS                         │
              └────────────────────────────────────────────────────┘
                                        │
              ┌─────────────────────────▼──────────────────────────┐
              │  GITHUB MIRROR (I-4)  +  3 TB HDD cold copy        │
              └────────────────────────────────────────────────────┘

  MEMBRANE (I-2) ──► windy-cloud kernel · eternitas · account-server · windy-cloud-sites
  KIT 0 ──────────► NEVER. Not in v0, not in v1, not ever. (D-4)
```

**Stack:** Python 3.12 + FastAPI (matches every sibling cell) · Postgres schema `windgit` · own alembic · Gitea as an unforked upstream container · `act_runner` for CI · `cloudflared` for ingress. **Our JS surface is zero in v1** — the UI is Gitea's, themed.

**Why our service exists at all rather than configuring Gitea harder:** Gitea has no concept of an Eternitas passport, no concept of a Windy Cloud folder, no MCP surface, and no per-agent spend cap. Those are the product. Gitea supplies git, LFS, PRs and CI — the commodity half — and we never write it.

---

## §4 Data model

Schema `windgit`. Postgres is truth; Gitea's own DB is a component's private state we never write to directly (I-1).

- **`repos`** — `id`, `identity_id`, `passport` (nullable; agent-owned repos), `slug`, `display_name`, **`repo_type` ∈ {code,model,dataset} NOT NULL (I-7)**, `gitea_repo_id`, `visibility` ∈ {private,unlisted,public}, `cloud_folder_ref` (nullable — set when git-enabled from a Cloud folder, D-8), `default_branch`, `lfs_bytes`, `object_bytes`, `state` ∈ {active,archived,deleted-soft}, `created_via` ∈ {portal,agent,import,cloud-folder}, timestamps.
- **`repo_grants`** — the shelter (D-8). `repo_id`, `grantee_identity_id` (nullable), `grantee_passport` (nullable), `role` ∈ {owner,maintainer,writer,reader}, `granted_by`, `expires_at` (nullable — **agent grants default to 90 days**), `confirm_ref`, `revoked_at`. Exactly one of the two grantee columns is non-null: enforced by CHECK constraint, not application code.
- **`repo_versions`** — the plane's own view of history, independent of Gitea. `repo_id`, `seq` (monotonic per repo), `commit_sha`, `tree_sha`, `author_identity_id` (nullable), `author_passport` (nullable), `signed` bool, `signature_verified` bool, `ei_at_action` (integrity band at push time — frozen, never recomputed), `message`, `bytes_added`, `created_at`.
- **`mirror_state`** — `repo_id`, `remote_url`, `direction` ∈ {push,pull,both}, `last_success_at`, `last_error`, `lag_seconds`, `state` ∈ {healthy,degraded,failed}. **I-4's alerting reads this table.**
- **`agent_tokens`** — `passport`, `repo_id` (nullable = account-wide), `scopes` (array), `token_hash`, `expires_at`, `last_used_at`, `revoked_at`, `revoked_reason`. Never store the token.
- **`agent_actions`** — every agent-initiated write: `passport`, `repo_id`, `action`, `ei_at_action`, `confirm_ref`, `result`, `cost_microcents`, `ts`.
- **`model_cards`** (v2) — `repo_id`, `base_model`, `license`, `pipeline_tag`, `tags[]`, `library`, `card_yaml` (jsonb), `card_body`.
- **`jobs`**, **`webhook_events`** — standard cell substrate, copied from the sites cell.

**Migration 001 creates every table above, including `model_cards` and `repo_type`.** Shipping v1 with the v2 columns absent is forbidden by I-7.

---

## §5 The pinned contracts

Three artifacts. Each is authored **before** the code that serves it, and each has consumer-driven contract tests.

**§5.1 `docs/REPOS_API.v1.md`** — our plane, mounted at `/api/v1/repos`.
`POST /` create (`repo_type` required) · `GET /` · `GET /{id}` · `DELETE /{id}` (I-10 confirm) · `GET /{id}/versions` · `POST /{id}/grants` · `DELETE /{id}/grants/{grant_id}` · `GET /{id}/grants` · `POST /{id}/git-enable {cloud_folder_ref}` (D-8) · `POST /{id}/mirror` · `GET /{id}/mirror` · `GET /{id}/provenance/{commit_sha}` · `GET /{id}/status` dual-register (`speak` + machine states) · `GET /{id}/events` SSE (`repo.pushed`, `ci.*`, `mirror.*`; heartbeat 15s; 10s-poll fallback) · `GET /version` (I-12) · `GET /health/full` (booleans for db, R2, gitea, eternitas, tunnel, mirror).

**§5.2 `docs/MEMBRANE.v1.md`** — I-2 verbatim, mirrored into `windy-cloud` and `eternitas`.

**§5.3 `docs/HF_COMPAT.v1.md`** (v2) — the subset of the Hugging Face Hub API we answer, so that `HF_ENDPOINT=https://models.windygit.com` works with unmodified clients. Minimum viable set: `GET /api/whoami-v2` · `GET /api/models/{repo_id}` · `GET /api/models/{repo_id}/revision/{rev}` · `GET /{repo_id}/resolve/{revision}/{filename}` (302 → R2 presigned) · `POST /api/repos/create` · LFS batch endpoints. **Each endpoint's exact response shape is pinned by a recorded fixture captured from the real HF API, committed to `tests/fixtures/hf/`.** Guessing the shape is banned.

---

## §6 Hosting ladder

Three rungs. **Each rung is a promotion, never a rewrite** — Gitea is one Go binary, a Postgres dump and a directory, so the move is an rsync plus a DNS change.

| Rung | When | Control plane | Runners | Trigger to advance |
|---|---|---|---|---|
| **R0** | now | Veron 1 + Cloudflare Tunnel | Veron 1, cgroup-capped | — |
| **R1** | first non-Grant user | dedicated VPS (KVM-4, **not Kit 0**) | Veron 1 | any external human or agent pushes |
| **R2** | sustained load | VPS + read replica | dedicated runner box | p95 clone > 3s, or runner queue > 5 min |

**R0's honest limits, stated up front so nobody is surprised:** no SLA (power, ISP, or a reboot takes it down); it is Grant's workstation, so runners are capped; 978 GB free on a 72%-full disk; no VPS-style snapshots. All four are acceptable while Grant is the only user and all four are disqualifying the moment a stranger depends on it. **R1's trigger is not a date — it is the first external push.**

---

# THE STRANDS

Strands G0–G4 are sequential. G5–G12 are concurrent once G4 lands.

## Strand G0 — Cell substrate

- **G0.1** FastAPI skeleton `api/app/main.py`, `config.py` (pydantic-settings), structured JSON logging with `request_id`.
- **G0.2** `GET /version` — returns `{version, commit_sha, built_at, repo_type_support[]}`. `commit_sha` comes from a Docker build arg baked at image build. **If the env var `COMMIT_SHA` is set at runtime it is IGNORED and a warning is logged** (I-12). *Accept:* a test asserts the env var cannot override the baked value.
- **G0.3** `GET /health/full` — booleans `{db, r2, gitea, eternitas, tunnel, mirror}`. Every one is a real probe; **none may return `true` from a mock** (I-8). *Accept:* with R2 creds unset, `r2:false` and the overall status is `degraded`, never `ok`.
- **G0.4** Postgres schema `windgit` + alembic; migration 001 creates §4 **in full**, including `repo_type` and `model_cards`. Every migration has a tested downgrade.
- **G0.5** `Dockerfile` + `docker-compose.yml` with an explicit `name:`. Compose files that wire prod to its database are **committed with secrets stripped** — three such files currently exist in exactly one place on earth (SOTU §5.6.3) and this cell will not add a fourth.
- **G0.6** `make check` = `ruff` + `mypy` + `pytest` + membrane-drift test + capabilities-drift test + `/version` honesty test. **The local gate IS the merge gate.**
- **G0.7** `SUBSTRATE.md` — hosts, ports, buckets, KV ids, tunnel name, what is truth and what is cache.
- **G0.8** `AGENTS.md` + `make dev` — one command brings up app + Gitea + Postgres + seeded fixtures including one repo in every state (empty, code, model, mirrored, mirror-failed, agent-owned, shelter-only).
- **G0.9** Backups: nightly `pg_dump` → R2; nightly `git bundle` of every repo → R2; **quarterly restore drill with a written result.** *Accept:* the drill is a `make restore-drill` target that provisions from backup into a scratch namespace and diffs.
- **G0.10** `.github/lint/canonical-domains.json` at v9 + the standard lint set. *(kit-army-config is the only repo without one — this cell will not be the second.)*
- **G0.11** Jobs table + ALERTS ladder wiring, copied from the sites cell.

## Strand G1 — Host and ingress (Veron 1)

- **G1.1** Create `windygit` service user on Veron 1. Data root `/srv/windygit/` — `git/` (object stores), `pg/`, `etc/`. **Not** under Grant's home.
- **G1.2** Install `cloudflared`; `cloudflared tunnel create windy-git`. Ingress map:

  | Hostname | → | Serves |
  |---|---|---|
  | `app.windygit.com` | `localhost:3000` | the forge — Gitea UI **and** git-over-HTTPS |
  | `api.windygit.com` | `localhost:8600` | our plane (`/api/v1/repos`, MCP, provenance) |
  | `models.windygit.com` | `localhost:8600` | HF-compatible endpoint (v2, D-7) |
  | `windygit.com` (apex) | Cloudflare Pages | marketing site — **`windy-git-site`, Grant-gated (§7.6)** |

  **Outbound-only — no inbound port is opened on Grant's network, and a dynamic residential IP is irrelevant.**
- **G1.3** DNS on zone `windygit.com` (`9d8637dcac3415607b2116e6099fe567`): three proxied CNAMEs to the tunnel target. Use the **DNS:Edit** token — the god token has Zone:Read but **no DNS:Edit**, a gap already documented in the lockbox. **All three are single-level subdomains, which free Universal SSL covers on this zone's Free plan.**
  ⚠️ **Never introduce a two-level hostname here** (`*.repos.windygit.com`). Universal SSL does not cover two-level wildcards; that needs Advanced Certificate Manager at $10/mo. The sites cell lost hours to exactly this: the request dies in the TLS handshake — `curl` exit 35, **no HTTP status at all** — *before* the Worker or app is ever consulted, so a perfect application presents as "the app is broken."
- **G1.3b** **Clone-URL law.** The canonical clone URL is `https://app.windygit.com/{owner}/{repo}`. Repos are **not** served from the apex: the apex belongs to marketing, and separating them keeps user-controlled content off the brand's operating origin (the `github.io` lesson, already ruled on for `windy-cloud-sites`). If rendered user pages are ever needed, they reuse the existing `*.sites.windycloud.com` root, which already has its ACM cert — **we never buy a second one.**
- **G1.4** systemd units `windygit-api`, `windygit-gitea`, `windygit-tunnel`, all `Restart=always`, all with `MemoryMax` and `CPUQuota`.
- **G1.5** **Runner containment:** `act_runner` runs under a systemd slice with `CPUQuota=1200%` (12 of 24 cores) and `MemoryMax=64G`. *Accept:* a deliberate fork-bomb workflow leaves Grant's interactive session responsive — tested, not assumed.
- **G1.6** UFW: deny all inbound except LAN SSH. The tunnel needs no inbound rule. *Accept:* `nmap` from outside the LAN shows no open port.
- **G1.7** `docs/RUNBOOK-VERON.md` — start, stop, restore, promote-to-R1, and what to do when Grant reboots his workstation.

## Strand G2 — Gitea, stock and branded

- **G2.1** Pin an exact Gitea version in compose; **never `latest`**. Record it in `SUBSTRATE.md`.
- **G2.2** `app.ini` from a committed template: disable self-registration, disable local password login (OIDC only, G3), `[repository] DEFAULT_BRANCH = main`, LFS on.
- **G2.3** Branding via `custom/templates/` + `custom/public/css/` — logo, wordmark, colors, footer. **All Gitea trademarks removed** (D-3). *Accept:* `grep -ri gitea` over rendered HTML returns only license-notice hits.
- **G2.4** `LICENSES/` directory carrying Gitea's MIT text and a `NOTICE` file, plus an "Open Source Licenses" link in the footer. Satisfies MIT's only obligation and is the right thing regardless of whether SaaS technically triggers it.
- **G2.5** `patches/` established **empty**, with `README` stating I-1's 3-file ceiling and the ADR requirement.
- **G2.6** Gitea admin API token minted, stored in the fleet lockbox, injected by env — never committed.
- **G2.7** Version-pin drift test: `make check` fails if the running Gitea version differs from the pinned one.

## Strand G3 — Identity and trust

- **G3.1** OIDC client registration on account-server; Gitea configured via `gitea admin auth add-oauth --provider openidConnect` against the discovery document. *Accept:* a fresh browser signs in end-to-end with no local password anywhere.
- **G3.2** Dual-JWKS middleware in our API — account-server RS256 (humans) and Eternitas ES256 (agents). Copy the module the sibling cells already share; do not re-derive.
- **G3.3** **EPT parity test (I-6):** an agent EPT and a human JWT of the same tier receive byte-identical capability sets from `GET /api/v1/repos/{id}/status`. This test is the invariant; if it goes red the build is broken, not the test.
- **G3.4** EI-band throttling from `EI_CAPABILITY_MATRIX.v1`: Platinum ×10 / Gold ×4 / Standard ×1 / Watch ×0.5 / Untrusted read-only. Velocity bases — `env:` pushes 500/day, repo-creates 50/day, grants 100/day, force-pushes 10/day — multiplied by band.
- **G3.5** `passport.revoked` webhook → **fail-closed**: revoke every `agent_tokens` row for that passport within one transaction, cancel in-flight CI jobs, mark grants revoked. *Accept:* revoke a test passport and prove a push with its token is refused within 5 seconds.
- **G3.6** ⚠️ **Trust-client status-code law.** `windy-chat` maps HTTP 400 and 429 from the trust API to "unreachable" and then soft-**ALLOWS** — a live residual bypass, since 429 is trivially inducible at 100/min/IP. **Here: 404 and 400 REFUSE. 429 and 5xx retry with backoff, then REFUSE.** There is no code path where an unresolvable passport is allowed to write.
- **G3.7** `agent_actions` + telemetry with `cost_microcents` actually populated. `platform: 'windy-git'`, `actor_type` from the enum `{human,agent,system}` — **`'service'` is not a legal value** and produces a 422 that silently drops the whole batch (windy-chat is losing telemetry to exactly this today).

## Strand G4 — Storage wiring

- **G4.1** R2 buckets: `windy-git-lfs`, `windy-git-artifacts`, `windy-git-backups` on account `193b347aedeaafe35de0b5a534b2d9aa`.
- **G4.2** R2 credential: **use an existing fleet token** (Grant's ruling, 2026-08-11 — sandbox phase, months from launch; a scoped platform token is a launch-hardening item, not a blocker). The non-obvious part worth recording: R2's S3 credentials are *derived* from a Cloudflare API token — **access key id = the token's id, secret = SHA-256 of the token value**.
- **G4.3** Gitea `[storage]` → `STORAGE_TYPE = minio` pointed at R2, covering LFS, attachments, packages, avatars and actions artifacts. ⚠️ **Known R2 trap:** R2 rejects the default checksum algorithm several S3 clients send; if uploads fail with a checksum error, set the MD5 checksum option. *Accept:* a 500 MB file round-trips through LFS and the object is confirmed present in R2 with a matching etag — **verify against the exact pinned Gitea version's docs, do not trust this key name from memory.**
- **G4.4** Git object stores on `/srv/windygit/git` (local NVMe). A test asserts no git object path resolves to a network mount (I-3).
- **G4.5** LFS threshold policy: files **> 5 MB** or matching binary/weight extensions (`.safetensors .bin .gguf .pt .ckpt .onnx .zip .mp4 .wav`) go to LFS via a committed `.gitattributes` template applied at repo creation. **Small text files stay in git proper** — LFS-for-everything makes clones slow and operations heavy.
- **G4.6** Quota: on push, call the kernel's quota check; over-quota → refuse with a repair-pointer error whose `speak` is grandma-words and whose `remediation_tool` names the upgrade path (Storage-Kingdom cross-sell hook, §0.5). **We emit the hook; the kernel owns the price** (I-11).
- **G4.7** Object-count and byte accounting per repo, recomputed nightly, exposed on `GET /{id}/status`.

## Strand G4A — Gitea/R2 traps paid for on 2026-08-11

Four failures hit while wiring G2–G4 live. Each cost a crash loop or a dead end,
and each presents as a different problem than it is. All four are now pinned by
tests in `api/tests/test_invariants.py`.

- **G4A.1 — `[lfs] STORAGE_TYPE` breaks storage inheritance.** Naming a storage
  type inside `[lfs]` creates a **separate** storage section that does *not*
  inherit the endpoint or credentials from `[storage]`. Gitea crash-loops on
  `Endpoint: does not follow ip address or domain name standards` — an error that
  names the symptom and not the cause. **Let LFS inherit `[storage]`.** Avatars
  initialising correctly is the tell that the rest of the config is fine.
- **G4A.2 — setting the storage backend does not turn LFS on.** `[server]
  LFS_START_SERVER = true` is separate. Without it the batch endpoint 404s and
  the client reports *"Repository or object not found"*, which reads like a
  permissions or credentials problem and is neither.
- **G4A.3 — ⚠️ Gitea's env-to-ini SETS but never UNSETS.** Removing a `GITEA__*`
  variable from compose does **not** remove the line from the persisted
  `app.ini`. The container will keep booting with a setting that no longer exists
  anywhere in the repo, so the config in git and the config in production
  silently disagree — the exact class of drift this whole cell exists to end.
  **To remove a setting you must edit `app.ini` on the host**
  (`/srv/windygit/git/gitea/conf/app.ini`), not just the compose file.
- **G4A.4 — R2 rejects the default S3 checksum algorithm.** Set
  `MINIO_CHECKSUM_ALGORITHM = md5` or uploads fail with an opaque checksum error.

### G4A.5 — ⚠️ Cloudflare's 100-second limit caps a push, and it shapes G10

A plain (non-LFS) push of an 8 MB file over the tunnel died with **HTTP 524**.
Cloudflare's proxy times out at ~100 s on the Free plan, and Grant's residential
upstream measured ~19 KB/s during the LFS test, so anything large is a coin flip.

This is not a bug to fix; it is a constraint that **dictates the model-hub
architecture**:

1. **The LFS threshold (G4.5) is load-bearing, not tidiness.** Anything big must
   go via LFS, because a large blob inside a git pack has no way to be resumed
   or offloaded.
2. **G10 must serve LFS objects via presigned R2 URLs — client straight to R2 —
   rather than proxying blobs through the tunnel.** That removes the 100 s
   ceiling, removes Grant's home upstream from the path entirely, and is exactly
   what Hugging Face does. Until that lands, model repos are capped by whatever
   fits in 100 seconds.

**Verified working on 2026-08-11:** a 3 MB LFS object pushed through the tunnel
and landed in R2 at `lfs/34/2d/…`, with **no local `lfs/` directory on the host**
— I-3 confirmed by measurement rather than by assertion.

## Strand G5 — THE SHELTER (permissions plane over Windy Cloud) · **the v0 product**

*This strand is the one that ships first and the one that has no competitor. Windy Cloud today has no sharing, no permissions and no versioning of any kind (D-8).*

- **G5.1** `POST /api/v1/repos/{id}/git-enable {cloud_folder_ref}` — takes an existing Windy Cloud folder and creates a version plane over it. **Opt-in per folder, never automatic on an account:** the initial import hashes everything, which is trivial for a website and expensive for a 200 GB media archive.
- **G5.2** Import walks the folder via the kernel's storage API, writes blobs as LFS pointers into R2 for anything over the G4.5 threshold, builds trees and an initial commit. **The user's files remain first-class Cloud objects, directly downloadable, never re-uploaded** — the Hugging Face property Grant specified.
- **G5.3** Grants API — `role ∈ {owner,maintainer,writer,reader}` over a repo, grantable to a human identity **or** an agent passport. Agent grants carry a default 90-day expiry.
- **G5.4** Share links: short-lived signed URLs for read access without an account. Never indexed.
- **G5.5** **Version history UI with one giant Undo.** Grandma-words throughout, and D-9 binds every string: "version", "save point", "restore" — **never "commit," never "a Git"** on this surface.
- **G5.6** `POST /{id}/restore {version_seq}` — lossless, and itself a new version. **Undo is never destructive.**
- **G5.7** Quota events double as storage-plan cross-sell hooks (§0.5).
- **G5.9** ⚠️ **Service callers need an on-behalf-of identity.** Verified live on
  2026-08-11: a repo created through `X-Service-Token` lands in a `u-system`
  namespace, because the service caller has no identity of its own. That is
  correct for `/internal/*` plumbing and **wrong for anything a person owns** —
  the Cloud portal must pass the acting user, and this cell must refuse to
  create a user-owned repo without one. Until then, service-created repos are
  ops artifacts, not customer data.
- **G5.8** *Accept — the strand's whole point in one test:* a Cloud folder is git-enabled, a second human is granted `writer`, that human edits a file through the portal, the owner restores the previous version, and **at no point does either user encounter the word "commit," "repo," "branch," or "Git."**

## Strand G6 — Git protocol surface

- **G6.1** Smart HTTP through the tunnel: `git clone https://app.windygit.com/{owner}/{repo}` works with stock git, no configuration.
- **G6.2** SSH access decision: **deferred to R1.** The tunnel does HTTPS cleanly; SSH through it needs extra setup and there is no v0 user who needs it. Recorded as deferred, not forgotten.
- **G6.3** Agent tokens: `POST /api/v1/agent-tokens` mints a repo- or account-scoped credential bound to a passport, with an expiry, usable as an HTTPS git credential. **Never a human's PAT wearing an agent's name** — this is the entire GitHub grievance and the reason the product exists.
- **G6.4** *Accept:* the **same** G5 shelter repo from G5.8 clones with stock `git clone` and its file tree byte-matches the Cloud folder. **This is the product's central claim** — grandma's folder and a developer's repo are the same object — and it is a test, not a slogan.
- **G6.5** Protected branches; force-push gated behind I-10 confirm.
- **G6.6** Push hooks fire `repo.pushed` on the membrane and write `repo_versions` with `ei_at_action` frozen at push time.

## Strand G7 — CI (the verification payoff)

*The reason this cell is justified today with zero customers.*

- **G7.1** Enable Gitea Actions; register `act_runner` on Veron 1 under the G1.5 slice with labels `veron-1`, `linux-x64`, `gpu` (the 5090 becomes a labelled capability for later model work).
- **G7.2** Runner isolation: containers only, no host Docker socket mount, no host network, no credential in the runner environment beyond the job's own scoped token (I-5).
- **G7.3** Migrate `windy-git`'s own `make check` to Gitea Actions. **Dogfood before anything else moves.**
- **G7.4** Migrate the **private** repos that GitHub cannot run at all — the ones where Actions is dead entirely, even self-hosted. This is the single largest immediate win in the plan.
- **G7.5** ⚠️ **Ban `ubuntu-latest`.** All four `windy-registry` workflows use it and every run fails. Runner labels are explicit and pinned.
- **G7.6** Revive the fleet canary: regenerate `kit-army-config/docs/deployed-state.json` on a schedule from Windy Git CI. **It has been 37+ days dead since 2026-07-03**, and its old workflow returns `startup_failure` on every run.
- **G7.7** Artifacts and logs to R2 (G4.1).
- **G7.8** *Accept:* a deliberately broken commit to a private repo produces a red check on the PR — **which is something that has not happened anywhere in this ecosystem in over a month.**

## Strand G8 — Agent surface (MCP + capability discovery)

- **G8.1** MCP server `windy-git-mcp` exposing the full knob-set — every button a human can push. Follows `windy-word-mcp` conventions.
  ⚠️ **Publish it to npm at the same version as the repo, in the same action that tags a release.** `windy-word-mcp` sat at repo v1.11.0 while npm `latest` was v1.5.0 from May, so the documented install fetched pre-auth-wall code that 401'd on every one of 114 routes for eleven weeks. A drift test fails `make check` if repo version ≠ npm `latest`.
- **G8.2** `/.well-known/windy-capabilities.json`, auto-generated, with a drift test.
- **G8.3** Error taxonomy: every error is a 4-field repair pointer `{code, speak, machine_cause, remediation_tool}`. No exceptions, including validation errors.
- **G8.4** `state_proof` + `next_actions` on every tool response, enabling verifiable one-shot agent pipelines.
- **G8.5** Repair-tool family (repair-own, Gold+, idempotent, doctor-referenced): `resync_mirror(repo)` · `rebuild_index(repo)` · `reissue_agent_token(passport, repo)` · `replay_webhook(event_id)` · `recompute_quota(repo)`.
- **G8.6** CLI `windy git …` wrapping the same API surface — parity with MCP, no capability reachable only through one door.

## Strand G9 — Provenance (the moat)

- **G9.1** Passport-signed commits: an agent's commit is signed with a key bound to its Eternitas passport; `signature_verified` is recorded on `repo_versions` at push time, never recomputed later.
- **G9.2** `GET /{id}/provenance/{commit_sha}` answers: **which agent, which passport, which integrity band at the time, which model produced it, in whose employ.** No other forge can answer this — GitHub has no agent identity, Hugging Face has no code review.
- **G9.3** Branch protection by integrity band — "only `proven` or better may push to main" is a repo setting.
- **G9.4** ⚠️ **HARD DEPENDENCY, currently broken upstream.** The integrity index **has never been populated**: `windy-registry/src/windy_registry/jobs/refresh_integrity.py:35-43` calls `/api/v1/passports/{p}/status`, which 404s; the real path is `/api/v1/registry/{passport}/integrity`, and the job fails silently into a counter, so author integrity is permanently NULL. **G9.3 must not ship, and provenance must not be marketed, until that is fixed and backfilled.** Until then `GET /provenance` returns `integrity: unknown` — honestly (I-8), never a fabricated band.
- **G9.5** *Accept:* a hatched agent pushes a commit; provenance returns its real passport, its band, and its model; and revoking the passport (G3.5) flips the verification result on the historical commit to `revoked` without rewriting history.

## Strand G10 — Model hub (v2)

- **G10.1** `repo_type=model` enabled; `model_cards` table populated from `README.md` YAML frontmatter on push.
- **G10.2** HF-compatible API per §5.3, fixture-pinned against recorded real responses.
- **G10.3** *Accept — the moat test:* `HF_ENDPOINT=https://models.windygit.com python -c "from huggingface_hub import snapshot_download; snapshot_download('windy/<pair>')"` succeeds with the **unmodified** `huggingface_hub` client.
- **G10.4** **First tenant: `Windy-Clinic`.** 2,144 files, the only artifact tying the model fleet to its provenance and upstream lineage, currently a **single copy with no backup** — SOTU SPOF #4, where nobody had ever asked the question. Onboarding it closes that finding the same way G7 closes the verification finding.
- **G10.5** Second tenant: the Windy Traveler LoRA pairs (1,188 built, targeting 2,500). Adapters at 50–500 MB → ~125 GB–1.25 TB → **$2–19/month on R2 with zero egress.**
- **G10.6** Windy Mind pulls models from the hub directly — our `from_pretrained` (D-7).
- **G10.7** ⛔ **SCOPE FENCE (D-7):** no mirroring of the open model ecosystem. A `make check` guard fails if any repo's upstream remote points at `huggingface.co` for a model we did not train or fine-tune.

## Strand G11 — Migration and mirroring

- **G11.1** Bidirectional push-mirror to GitHub for every repo, from the first commit (I-4).
- **G11.2** Mirror health monitor writing `mirror_state`; lag > 60 min raises a P2; failure raises a P1.
- **G11.3** Import tooling: bulk-import all 61 repos. **Measured footprint: 11 GB working trees, 0.63 GB git objects — the whole company's source history fits on a phone.**
- **G11.4** Migration order, least-risk first: `windy-git` itself → 0-LOC scaffolds → marketing sites → dormant repos → live services → `windy-pro` **last**.
- **G11.5** ⚠️ **Do not resolve the windy-pro checkout ambiguity by guessing.** Six windy-pro-family checkouts exist with a **build counter forked three ways** (main 12, overnight 34, wave-44 56) and direct evidence conflict on HEAD (`f69d363` vs `911f5ccf`, recorded hours apart by two sessions). Resolve, write down the answer, *then* migrate.
- **G11.6** GitHub stays the durable copy for a **full quarter** minimum after cutover. Advancing that date is a Grant decision (§7).
- **G11.7** Nightly `git bundle` of every repo → R2, plus a periodic sync to the 3 TB HDD for a cold copy in Grant's hands.

## Strand G12 — Launch hardening

- **G12.1** Chaos: kill Gitea mid-push — no corruption, no half-written `repo_versions` row.
- **G12.2** Chaos: R2 unreachable — LFS operations fail **loudly** with a repair pointer; git operations on non-LFS content continue working; `/health/full` reports `r2:false` and status `degraded` (I-8).
- **G12.3** Chaos: tunnel drops — service self-heals on reconnect; no manual step.
- **G12.4** Chaos: **destroy the entire Windy Git deployment and prove not one user byte was lost** (I-13). Windy Cloud still holds every file; only the version plane is gone, and it rebuilds from the R2 bundles.
- **G12.5** Restore drill executed end-to-end with a **written, dated result** — the ecosystem currently has no rehearsed restore for anything, anywhere (SOTU §5.6).
- **G12.6** **Copy audit against D-9.** Grep every user-facing string for "a Git", "Gits", "your Git". Zero hits, and a `make check` test that keeps it at zero forever.
- **G12.7** Deployment-identity proof: `/version` matches HEAD, on a machine where an env-var override is present and correctly ignored (I-12).
- **G12.8** Load: 50 concurrent clones of the largest repo without disturbing Grant's interactive session (G1.5).

---

## §7 Grant-gated — decisions no agent may take

1. **Opening to any non-Grant user.** Triggers the R0 → R1 promotion (§6); until then this is internal infrastructure with no tile and no marketing site.
2. **Any pricing.** This cell emits usage events only (I-11).
3. **Advancing off the GitHub mirror** (G11.6) — the one-way-door decision.
4. **Marketing provenance** before G9.4's upstream integrity fix lands (I-8).
5. **A hard fork of Gitea** (D-2/I-1) — requires the named-files list and an ADR.
6. **`windy-git-site` content and launch.** Repo staked at `sneakyfree/windy-git-site`, deliberately empty.
7. **Enabling `repo_type=model` in production** — flips the storage cost curve by roughly two orders of magnitude per repo.
8. **Any Kit 0 involvement whatsoever.** D-4 says never; only Grant may overturn a never.

---

## §8 Verification law

Both audits found the same root cause: *nothing anywhere checks whether a decision reached production.* This cell is partly a cure for that, so it is held to a higher standard than the cell it is curing.

1. **`make check` is the merge gate**, runs locally and in CI, identical both places.
2. **No decorative CI.** A workflow that cannot run is deleted, not committed. Nine decorative workflow files in `windy-pro` alone imply a verification that is not happening — worse than none.
3. **Every invariant I-1…I-13 has a named test.** A test file header cites the invariant it defends.
4. **Every codon above has an acceptance criterion.** An unverifiable codon is not done, no matter how finished the code looks.
5. **The canary is ours now** (G7.6). If `deployed-state.json` goes stale again, that is this cell's failure.

---

## §9 Cost model

| Line | v0 (R0) | v1 (R1) | With models (v2) |
|---|---|---|---|
| Compute | **$0** (Veron 1) | + VPS | + VPS |
| R2 storage | ~$0.01 (0.63 GB) | ~$1 | $2–19 (Traveler pairs) |
| R2 egress | **$0** | **$0** | **$0** |
| Tunnel | $0 | $0 | $0 |
| CI | $0 (own hardware) | $0 | $0 |
| GitHub mirror | $0 | $0 | $0 |

**All 61 repos of source history cost roughly one cent a month to store.** The cost curve is entirely a model-weights curve, which is why G10.7's scope fence is load-bearing and why 100 TB (~$1,500/mo) is a business decision, not an accident to drift into.

---

## §10 Glossary — binding on all copy (D-9)

| Say | Never say | Notes |
|---|---|---|
| **Windy Git** | Windy GitHub, WindyGit | The product. |
| **a version** / **a save point** | *a Git* | General audience, and the G5 shelter surface. |
| **a commit** | *a Git* | Developer audience. |
| **a repo** / **a project** | *a Git* | The container. |
| **a release** / **a tag** | *a Git* | A named version. |
| **Git** | *gits*, *a git* | The program. Never countable, ever. |

---

## §11 Provenance of this plan

Everything above traces to one of: the 2026-08-11 vision session (D-1 … D-9); the 2026-08-09 Opus/Fable audits and their reconciliation (every ⚠️ trap, every SOTU citation); direct measurement on 2026-08-11 (repo footprint 11 GB / 0.63 GB objects across 61 repos; Veron 1 at 24 cores / 251 GB / 978 GB free / load 1.52; Kit 0 at load 7.62; Windy Cloud storage confirmed to have zero sharing, permission or versioning code).

Where this plan carries a warning, an ecosystem sibling already paid for that lesson in production. **The traps are not hypothetical — every ⚠️ in this document is somebody's bad week, written down so it is not repeated here.**
