# windy-git

**Dev name:** `windy-git` · **Brand:** **Windy Git** · **Apex:** [windygit.com](https://windygit.com) (Cloudflare, zone `9d8637dc…`, active)

**The version, permission, and provenance plane over Windy Cloud — and a code and model host that rolls out the red carpet for Eternitas-credentialed agents.**

---

## Status

**GENESIS.** Stake in the ground, 2026-08-11. No code yet. The plan is the artifact.

👉 **[`DNA_STRAND_MASTER_PLAN.md`](DNA_STRAND_MASTER_PLAN.md) is the source of truth.** Read it before writing a line.

## What this is

GitHub is hostile to agents in exactly the way Gmail is hostile to bots. An agent on GitHub wears a human's clothes: it borrows a human's token, inherits a human's permissions, has no independent standing, no spend limit, no revocation story, and no verifiable track record.

Windy Git makes the agent a **citizen** — it pushes as itself, under its own Eternitas passport, with its own scoped credential, its own limits, and a signature anyone downstream can verify.

One substrate, three repo types:

| Type | Contents | Ships |
|---|---|---|
| `code` | source, sites, projects | v1 |
| `model` | weights, LoRA adapters, model cards | v2 |
| `dataset` | corpora, eval sets | v2 |

**Second mission, and it arrives first:** both August 2026 audits converged on one root cause — *nothing anywhere checks whether a decision reached production* — because GitHub Actions is billing-locked and private repos can't run Actions at all, even self-hosted. Windy Git brings CI back on our own hardware. **That payoff lands on day one with zero customers.**

## The nine locked decisions

Full reasoning in [§0.7 of the plan](DNA_STRAND_MASTER_PLAN.md). Do not re-litigate without an ADR.

| | Decision |
|---|---|
| **D-1** | Separate repo, separate brand, **shared billing** — never a seventh Stripe ladder |
| **D-2** | **Membrane, not merge.** Do not hard-fork Gitea; build beside it against its API |
| **D-3** | **Gitea (MIT)**, not Forgejo (GPLv3 ≥ v9) — the self-host installer is why |
| **D-4** | **Veron 1 first. Cloudflare Tunnel. Never Kit 0.** |
| **D-5** | Three storage tiers: git objects local · heavy bytes on R2 · GitHub mirror |
| **D-6** | `repo_type` is a first-class column from migration 001 |
| **D-7** | `HF_ENDPOINT` compatibility is the cheapest real moat available |
| **D-8** | The permissions plane ships **before** the git protocol |
| **D-9** | **Vocabulary law** — see below |

## D-9 · Vocabulary law

**"Git" is never a countable noun. There is no such thing as "a Git."**

Git is the program. A moment in time is a **commit**; a named one is a **tag** or **release**; the container is a **repo**.

| Say | Never say |
|---|---|
| **Windy Git** | Windy GitHub, WindyGit |
| **a version** / **a save point** (general audience) | *a Git* |
| **a commit** (developers) | *a Git* |
| **a repo** / **a project** | *a Git* |

This binds all copy, UI strings, docs, marketing and stage material. `make check` enforces it (codon G12.6).

## Architecture in one breath

Stock **Gitea** (unforked, MIT) supplies the commodity half — git, LFS, PRs, CI. **Our FastAPI service beside it** supplies the product: the permissions plane over Windy Cloud, the Eternitas agent layer, the MCP surface, provenance, and the Hugging-Face-compatible model endpoint. Git objects live on Veron 1's NVMe; everything heavy lives on Cloudflare R2 at zero egress; every repo mirrors to GitHub, always.

```
app.windygit.com     → the forge (Gitea UI + git over HTTPS)
api.windygit.com     → our plane (/api/v1/repos, MCP, provenance)
models.windygit.com  → HF-compatible endpoint (v2)
windygit.com         → marketing (windy-git-site) — Grant-gated
```

## Cell boundaries

Sibling cells: `windy-cloud` (kernel — **hardened substrate, DO NOT grow it**), `windy-cloud-sites`, `windy-cloud-domains`, `windy-cloud-vps`.

The membrane is **enumerated** in invariant I-2 and mirrored in `docs/MEMBRANE.v1.md`. Additions edit the invariant first.

## Scale of the problem, measured

| | |
|---|---|
| Repos to migrate | **61** |
| Working trees | 11 GB |
| **Actual git objects** | **0.63 GB** — all history, all branches, forever |
| Host (v0) | Veron 1 — 24 cores, 251 GB RAM, 978 GB free, load 1.52 |
| Cost (v0) | **$0/month** |

## License

Our code: TBD before first external contribution. Gitea ships under MIT and its notice travels with any distribution — see `LICENSES/` (codon G2.4).
