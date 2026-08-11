# SUBSTRATE.md — windy-git

What runs where, what is truth, and what is only a cache.

## Hosts

| Rung | Host | Role | Status |
|---|---|---|---|
| **R0** | **Veron 1** (`Veron-1-5090`, WireGuard `10.10.0.6`) | everything | **current** |
| R1 | dedicated VPS (**not Kit 0**) | control plane | on first external push |
| R2 | VPS + read replica, dedicated runner box | split | p95 clone > 3s |

**Veron 1, measured 2026-08-11:** 24 cores · 251 GB RAM · 3.6 TB root, 978 GB free · load 1.52 · $0/mo.

⛔ **Kit 0 (72.60.118.54) is never a host for this service.** D-4, and there is a
boot guard in `api/app/main.py` that refuses to start there in production.

## Ports (all bound to localhost; the tunnel is the only ingress)

| Port | Service |
|---|---|
| 8600 | `windy-git-api` — our plane |
| **3080** | Gitea — host 3000 and 3300 are taken by resident projects on Veron 1 |
| 5432 | Postgres |
| 2000 | cloudflared metrics (probe target) |

## Ingress — Cloudflare Tunnel `windy-git`

Zone `windygit.com` = `9d8637dcac3415607b2116e6099fe567` · account `193b347aedeaafe35de0b5a534b2d9aa` · **Free plan**.

| Hostname | → |
|---|---|
| `app.windygit.com` | Gitea :3080 — UI **and** git over HTTPS |
| `api.windygit.com` | our plane :8600 |
| `models.windygit.com` | HF-compatible endpoint :8600 (v2) |
| `windygit.com` | Cloudflare Pages — marketing, Grant-gated |

**No inbound port is opened.** The tunnel connects outbound, so the residential
dynamic IP is irrelevant.

⚠️ **All hostnames are single-level subdomains, on purpose.** Free Universal SSL
covers `windygit.com` + `*.windygit.com` and stops there. A two-level name needs
Advanced Certificate Manager ($10/mo) and without it the request dies in the TLS
handshake — `curl` exit 35, **no HTTP status at all** — *before* the app is ever
consulted, so a perfect service presents as "the app is broken."

## Storage — what is truth

| Store | Holds | Truth? |
|---|---|---|
| `/srv/windygit/git` (local NVMe) | **git object databases** | **truth** |
| Postgres `windgit` | repos, grants, versions, tokens, mirrors | **truth** |
| Gitea's own DB | Gitea's private state | component-owned; we never write it (I-1) |
| R2 `windy-git-lfs` | LFS objects | truth for blobs |
| R2 `windy-git-artifacts` | CI artifacts, logs | derived |
| R2 `windy-git-backups` | nightly pg_dump + git bundles | derived |
| GitHub mirror | full copy of every repo | **belt and suspenders (I-4)** |
| 3 TB HDD | periodic cold copy | derived |

**I-3: git objects never go to object storage; LFS blobs never go to host disk.**

## Pinned versions

| Component | Version | Note |
|---|---|---|
| Gitea | `1.24.6` | **exact pin, never `latest`** (G2.1). A drift test fails `make check` if the running version differs. |
| Postgres | `16-alpine` | |
| Python | 3.12 | matches every sibling cell |

## Credentials

All in the fleet lockbox, injected by env, **never committed**. `make check`
fails on any `cfat_` / `cfut_` / `gh[pousr]_` / `et_plt_` literal in the tree.

### R2 credential — RULED, not a debt (Grant, 2026-08-11)

This cell uses an existing fleet Cloudflare token for R2. **That is the decision,
not an oversight.** Grant's ruling, verbatim in intent: we are months from
launch, in a sandbox, and minting a tenth Cloudflare token to sit in the
inventory costs more than it buys. A platform-specific scoped token gets created
as part of launch hardening.

Recorded here so the next reader knows it was chosen rather than missed. **Do not
re-raise it before the launch-hardening pass** — see the standing instruction
about pre-launch security-hygiene nagging.

Access key id = the API token's id; secret = SHA-256 of the token value. That
derivation is not obvious and is the thing worth writing down.

## Backups (G0.9)

Nightly `pg_dump` → R2 · nightly `git bundle` per repo → R2 · **quarterly restore
drill via `make restore-drill`, with a written, dated result.** The ecosystem
currently has no rehearsed restore for anything, anywhere.
