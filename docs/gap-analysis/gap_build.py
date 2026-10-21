#!/usr/bin/env python3
"""Build the Windy Git DNA gap report (HTML). Scores are hand-assigned from evidence gathered 2026-10-17."""
import html
import sys

G, Y, R = "green", "yellow", "red"

STRANDS = [
    ("G0", "Cell substrate", [
        ("G0.1", "FastAPI skeleton, config, JSON logs", G, "windy-git-api live on Veron 7 days, healthy."),
        ("G0.2", "/version with baked sha; env override ignored", G, "Live: source \"baked\", sha e64a1b5. Tests test_i12_* (3)."),
        ("G0.3", "/health/full with real probes", Y, "db, gitea, r2, eternitas really probed. Tunnel and mirror are reported as \"not checked here\", not as booleans."),
        ("G0.4", "Schema + migration 001 in full, tested downgrade", G, "001_genesis creates all 9 tables incl. repo_type and model_cards; CI runs upgrade, downgrade, upgrade."),
        ("G0.5", "Dockerfile + compose, no secrets committed", G, "test_g05_no_secret_literals_committed."),
        ("G0.6", "make check = ruff + mypy + pytest + drift tests", Y, "lint, type, vocab and test run (436 pass). Membrane-drift and capabilities-drift tests don't exist yet."),
        ("G0.7", "SUBSTRATE.md", G, "Present."),
        ("G0.8", "AGENTS.md + make dev with seeded fixtures", Y, "AGENTS.md and make dev exist. No seeded repo in every state (empty, model, mirror-failed, agent-owned...)."),
        ("G0.9", "Nightly backups to R2 + quarterly restore drill", Y, "Nightly bundles + db (age-encrypted) and restic state backup, verified today. Drill passed 10-12. No make restore-drill target, no quarterly schedule."),
        ("G0.10", "canonical-domains lint in this repo", R, "windy-git has no .github/lint/canonical-domains.json."),
        ("G0.11", "Jobs table + ALERTS ladder", R, "Jobs table exists but holds 0 rows; nothing wired to an alert ladder."),
    ]),
    ("G1", "Host and ingress (Veron 1)", [
        ("G1.1", "Service user + /srv/windygit data root", Y, "/srv/windygit is the data root. The windygit service user was never created."),
        ("G1.2", "Cloudflare tunnel: app., api., models.", G, "app 200, api /version 200, models routed (404 until v2). Outbound-only."),
        ("G1.3", "Single-level DNS on windygit.com", G, "All hostnames single-level; free Universal SSL."),
        ("G1.3b", "Clone URL law (app.windygit.com/owner/repo)", G, "CI and runners clone via app.windygit.com."),
        ("G1.4", "Service units with memory and CPU limits", Y, "Tunnel is a systemd unit. Gitea and the API run in Docker (restart=unless-stopped) without MemoryMax/CPUQuota."),
        ("G1.5", "Runner capped at 12 cores / 64 GB", Y, "Caps set in compose and pinned by test. Fork-bomb acceptance test never run."),
        ("G1.6", "No inbound ports", Y, "Gitea (3080) and API (8600) bind to loopback only. UFW is inactive on Veron; no outside nmap proof."),
        ("G1.7", "RUNBOOK-VERON.md", G, "Present."),
    ]),
    ("G2", "Gitea, stock and branded", [
        ("G2.1", "Exact Gitea version pinned", G, "gitea/gitea:1.24.7; test_g21."),
        ("G2.2", "app.ini: no self-signup, no password login, LFS on", G, "Live: DISABLE_REGISTRATION, password form off, external-only registration, LFS_START_SERVER, DEFAULT_BRANCH main."),
        ("G2.3", "Branding, Gitea marks removed", G, "APP_NAME Windy Git; branding version-controlled (test_g23)."),
        ("G2.4", "LICENSES + NOTICE", G, "LICENSES/gitea-MIT.txt + NOTICE.md; test_g24."),
        ("G2.5", "patches/ empty with 3-file ceiling", G, "patches/ holds only README; test_i01_patch_ceiling."),
        ("G2.6", "Admin token in lockbox, injected by env", G, "In use by promote and sync scripts via header files."),
        ("G2.7", "Running-vs-pinned version drift test", Y, "Pin is tested; no test compares the running Gitea to the pin (health reports 1.24.7)."),
    ]),
    ("G3", "Identity and trust", [
        ("G3.1", "OIDC sign-in via account-server", G, "1 OAuth source live; password sign-in off; Stage A issuer checks enforced 10-10."),
        ("G3.2", "Dual JWKS: humans RS256 + agents ES256", Y, "Human JWT verified. The agent ES256 verifier isn't built, so agent auth fails closed in production (audit fix 08-13)."),
        ("G3.3", "EPT parity test (I-6)", R, "No parity test; agents can't authenticate yet."),
        ("G3.4", "EI-band throttling", Y, "throttle.py with bands and velocity bases, tested. Unused while agent auth is closed."),
        ("G3.5", "passport.revoked webhook fails closed", Y, "Built with HMAC tests and a one-transaction revoke. 0 webhook events received; 5-second live proof not done."),
        ("G3.6", "Trust-client status-code law", G, "test_g36: 400/404 refuse, never soft-allow."),
        ("G3.7", "agent_actions + telemetry", Y, "6 telemetry event kinds live to the admin ledger; actor_type enum tested. cost_microcents not populated."),
    ]),
    ("G4", "Storage wiring", [
        ("G4.1", "R2 buckets lfs / artifacts / backups", Y, "windy-git-backups verified today (136 objects). LFS and artifacts buckets not re-checked for this report."),
        ("G4.2", "R2 credential", G, "Scoped R2 pair in use since 09-23."),
        ("G4.3", "Gitea storage on R2 (md5 checksum)", Y, "STORAGE_TYPE minio + MINIO_CHECKSUM_ALGORITHM md5 live; 1 LFS object. The 500 MB round-trip acceptance was never run."),
        ("G4.4", "Git objects on local disk, never object storage", G, "test_i03."),
        ("G4.5", "LFS threshold .gitattributes template", R, "No template in the repo; nothing applies it at repo creation."),
        ("G4.6", "Quota check on push", R, "No call to the Cloud kernel's quota check."),
        ("G4.7", "Per-repo object and byte accounting", R, "Not built."),
        ("G4A.1-4", "Gitea/R2 traps (LFS inheritance, LFS server, env-to-ini, checksum)", G, "All four pinned by tests in test_invariants.py."),
        ("G4A.5", "100-second push cap shapes the model hub", Y, "Constraint documented and LFS rule kept; presigned R2 downloads (the fix) wait for G10."),
    ]),
    ("G5", "The shelter (permissions plane), the v0 product", [
        ("G5.1", "git-enable a Cloud folder", R, "Endpoint not built."),
        ("G5.2", "Import a folder via the kernel storage API", R, "Not built."),
        ("G5.3", "Grants API (owner / maintainer / writer / reader)", Y, "POST/GET/DELETE grants live; DB enforces exactly one grantee; agent grants default to 90 days. 4 grants exist (test data)."),
        ("G5.4", "Share links", R, "Not built."),
        ("G5.5", "Version history UI with one big Undo", R, "Not built (shelter word list is tested, G5.5 vocab)."),
        ("G5.6", "Lossless restore", R, "Not built."),
        ("G5.7", "Quota events as storage cross-sell hooks", R, "Not built."),
        ("G5.9", "On-behalf-of identity for service callers", Y, "Owner namespace is derived from the repo, not the caller (tested). Portal pass-through of the acting user not built."),
        ("G5.8", "Acceptance: folder shared, edited, restored, no git words", R, "Can't run until G5.1-G5.6 exist."),
    ]),
    ("G6", "Git protocol surface", [
        ("G6.1", "Smart HTTP clone through the tunnel", G, "Every CI job clones this way (2,827 runs in 7 days)."),
        ("G6.2", "SSH decision", G, "Deferred to R1 as the plan says."),
        ("G6.3", "Agent tokens bound to a passport", R, "No /agent-tokens endpoint; 0 tokens."),
        ("G6.4", "Shelter repo clones byte-identical to the Cloud folder", R, "Depends on G5."),
        ("G6.5", "Protected branches; force-push needs confirm", R, "0 protected branches in Gitea."),
        ("G6.6", "Push hooks fire repo.pushed and write repo_versions", R, "repo_versions holds 0 rows."),
    ]),
    ("G7", "CI (the verification payoff)", [
        ("G7.1", "Gitea Actions + runner labels incl. gpu", Y, "7 runners, labels veron-1 and linux-x64 (+ self-hosted, linux, x64). No gpu label."),
        ("G7.2", "Runner isolation (no host socket, no host network)", G, "Five I-5 tests; per-job networks; egress filter."),
        ("G7.3", "Dogfood: windy-git's own check on Gitea Actions", G, "check.yml gates every windy-git PR (e.g. #32, #33)."),
        ("G7.4", "Private repos that GitHub can't run", G, "36 repos synced and bridged, incl. windy-pro-mobile and windy-text-site today; 2,827 runs in 7 days."),
        ("G7.5", "Labels match fleet convention", G, "[self-hosted, linux, x64] runs as-is; test_g75."),
        ("G7.6", "Revive the fleet canary (deployed-state.json)", R, "kit-army-config docs/deployed-state.json last changed 07-03. A login/health canary runs instead (green today)."),
        ("G7.7", "Artifacts and logs to R2", Y, "Covered by Gitea's minio storage config; not re-verified for this report."),
        ("G7.8", "A broken commit on a private repo shows a red PR check", G, "Bridge posts windy-git/* statuses on GitHub; e.g. windy-mail run 482 flagged a real failure today."),
        ("G7A.1-6", "CI traps paid for on 08-12", G, "All six pinned by tests (DNS isolation, re-register, Python pin, timeouts, per-job network, no mid-job restart)."),
    ]),
    ("G8", "Agent surface (MCP + discovery)", [
        ("G8.1", "MCP server windy-git-mcp", R, "Not built."),
        ("G8.2", "/.well-known/windy-capabilities.json", R, "Not built."),
        ("G8.3", "4-field repair-pointer errors", G, "errors.py; test_g83 (all four fields, grandma-words speak)."),
        ("G8.4", "state_proof + next_actions on responses", R, "Not built."),
        ("G8.5", "Repair-tool family", R, "Not built as API tools (ops scripts exist, e.g. rerun_ci, promote_to_ci)."),
        ("G8.6", "windy git CLI", R, "Not built."),
    ]),
    ("G9", "Provenance (the moat)", [
        ("G9.1", "Passport-signed commits", R, "Not built."),
        ("G9.2", "GET /provenance/{sha}", R, "Not built."),
        ("G9.3", "Branch protection by integrity band", R, "Not built; must wait for G9.4."),
        ("G9.4", "Upstream integrity index fix (windy-registry)", R, "Not re-checked; treat as still blocking."),
        ("G9.5", "Acceptance: agent push, provenance, revoke flips it", R, "Can't run."),
    ]),
    ("G10", "Model hub (v2, Grant-gated)", [
        ("G10.1", "repo_type=model + model cards", R, "Schema ready (model_cards table, 0 rows); production shows code only. Enabling it is Grant's call (§7.7)."),
        ("G10.2", "HF-compatible API, fixture-pinned", R, "Not started."),
        ("G10.3", "HF_ENDPOINT moat test", R, "Not started."),
        ("G10.4", "First tenant: Windy-Clinic", R, "Not started."),
        ("G10.5", "Second tenant: Traveler LoRA pairs", R, "Not started."),
        ("G10.6", "Windy Mind pulls from the hub", R, "Not started."),
        ("G10.7", "Scope fence: no mirroring the open model ecosystem", R, "No guard yet."),
    ]),
    ("G11", "Migration and mirroring", [
        ("G11.1", "Push-mirror every repo to GitHub", Y, "Phase 1 runs the other way on purpose (GitHub is the source, Windy Git follows), so no one-way door exists. 7 push mirrors configured."),
        ("G11.2", "Mirror health monitor with P1/P2 alerts", Y, "mirror_state: 7 rows, all healthy. Lag/failure alerts not wired."),
        ("G11.3", "Bulk import of every repo", G, "155 repos in Gitea (111 read-only mirrors, 44 writable CI repos)."),
        ("G11.4", "Migration order, windy-git first, windy-pro last", Y, "CI cutover follows the order; Windy Git as PRIMARY for itself is planned (CUTOVER-PRIMARY.md), not done."),
        ("G11.5", "Resolve the windy-pro checkout ambiguity first", Y, "windy-pro runs CI here since 09-23; the written resolution wasn't re-checked for this report."),
        ("G11.6", "GitHub stays durable for a full quarter", G, "GitHub remains the source of truth; Grant's 10-01 plan keeps it as a permanent mirror."),
        ("G11.7", "Nightly bundles to R2 + 3 TB HDD cold copy", Y, "R2 nightly verified today (134 repos, 135 encrypted files). No HDD cold copy."),
    ]),
    ("G12", "Launch hardening", [
        ("G12.1", "Chaos: kill Gitea mid-push", R, "Not run."),
        ("G12.2", "Chaos: R2 unreachable", R, "Not run (health already reports r2 honestly)."),
        ("G12.3", "Chaos: tunnel drops", R, "Not run."),
        ("G12.4", "Chaos: destroy the deployment, lose no user byte", R, "Not run."),
        ("G12.5", "Restore drill end-to-end, written and dated", G, "restic drill PASSED 10-12 (1,322 files, fsck ok); cross-host drill script + RESTORE-DRILL.md."),
        ("G12.6", "Copy audit against D-9, kept by a test", G, "test_d09_vocabulary_audit_passes runs in make check."),
        ("G12.7", "Deployment identity: /version matches HEAD", Y, "/version is honest and env-proof, but the live API image is 09-23 (e64a1b5) while main has moved on; the API hasn't been redeployed."),
        ("G12.8", "Load: 50 concurrent clones", R, "Not run."),
    ]),
]

INVARIANTS = [
    ("I-1", "Gitea is a component, never a merged tree", G, "patches/ empty, ceiling tested."),
    ("I-2", "The membrane is enumerated", Y, "MEMBRANE.v1.md exists; no drift test against the code."),
    ("I-3", "Git objects local, heavy bytes remote", G, "Tested and measured."),
    ("I-4", "Never a one-way door", Y, "Satisfied in spirit (GitHub is primary); alerting on mirror lag not wired."),
    ("I-5", "CI never shares a kernel with identity", G, "Runners on Veron, isolated, five tests."),
    ("I-6", "EPT parity plus asymmetry", R, "No parity test; agent auth closed."),
    ("I-7", "repo_type from migration 001", G, "Three tests."),
    ("I-8", "Never claim live while a provider is mock", G, "No mock modes (test); health reports honestly."),
    ("I-9", "Grandma-words, D-9 vocabulary", G, "Vocabulary audit in make check."),
    ("I-10", "Always-confirm for irreversibles", R, "No CONFIRM_FLOW in the plane yet."),
    ("I-11", "One billing ladder, not ours", G, "No Stripe code in the repo."),
    ("I-12", "/version honest or refuse to boot", G, "Baked sha, env ignored, empty-sha build fails."),
    ("I-13", "The plane is not the substrate", R, "No chaos test proving it (G12.4)."),
]

LABEL = {G: "Done", Y: "Partial", R: "Not done"}


def counts(rows):
    c = {G: 0, Y: 0, R: 0}
    for r in rows:
        c[r[2]] += 1
    return c


def bar(c):
    total = sum(c.values()) or 1
    segs = "".join(
        f'<span class="seg {k}" style="width:{c[k] * 100 / total:.2f}%" title="{LABEL[k]}: {c[k]}"></span>'
        for k in (G, Y, R) if c[k])
    return f'<div class="bar" role="img" aria-label="{c[G]} done, {c[Y]} partial, {c[R]} not done">{segs}</div>'


def row(code, name, st, ev):
    return (f'<tr class="{st}"><td class="code">{html.escape(code)}</td><td>{html.escape(name)}</td>'
            f'<td><span class="pill {st}">{LABEL[st]}</span></td><td class="ev">{html.escape(ev)}</td></tr>')


all_rows = [r for _, _, rows in STRANDS for r in rows]
tot = counts(all_rows)
inv = counts(INVARIANTS)

strand_summary = "".join(
    f'<tr><td class="code"><a href="#{sid}">{sid}</a></td><td>{html.escape(name)}</td>'
    f'<td class="num g">{counts(rows)[G]}</td><td class="num y">{counts(rows)[Y]}</td><td class="num r">{counts(rows)[R]}</td>'
    f'<td class="barcell">{bar(counts(rows))}</td></tr>'
    for sid, name, rows in STRANDS)

sections = "".join(
    f'<section id="{sid}"><h2>{sid} · {html.escape(name)} <small>{counts(rows)[G]} done · {counts(rows)[Y]} partial · {counts(rows)[R]} not done</small></h2>'
    f'<div class="tw"><table class="codons"><thead><tr><th>Codon</th><th>What the plan asks</th><th>Status</th><th>Evidence (10-17)</th></tr></thead><tbody>'
    + "".join(row(*r) for r in rows) + "</tbody></table></div></section>"
    for sid, name, rows in STRANDS)

inv_rows = "".join(row(*r) for r in INVARIANTS)

page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Windy Git Gap Analysis</title>
<style>
:root {{ --bg:#fafaf9; --fg:#1c1917; --muted:#57534e; --line:#e7e5e4; --card:#fff;
  --g:#15803d; --gbg:#dcfce7; --y:#a16207; --ybg:#fef3c7; --r:#b91c1c; --rbg:#fee2e2; --link:#1d4ed8; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#1c1917; --fg:#f5f5f4; --muted:#a8a29e; --line:#44403c; --card:#292524;
  --g:#4ade80; --gbg:#14532d; --y:#facc15; --ybg:#713f12; --r:#f87171; --rbg:#7f1d1d; --link:#93c5fd; }} }}
:root[data-theme="dark"] {{ --bg:#1c1917; --fg:#f5f5f4; --muted:#a8a29e; --line:#44403c; --card:#292524;
  --g:#4ade80; --gbg:#14532d; --y:#facc15; --ybg:#713f12; --r:#f87171; --rbg:#7f1d1d; --link:#93c5fd; }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
main {{ max-width:1100px; margin:0 auto; padding:24px 16px 64px }}
h1 {{ font-size:26px; margin:0 0 4px }} h2 {{ font-size:19px; margin:32px 0 8px }} h2 small {{ font-weight:400; color:var(--muted); font-size:13px; margin-left:8px }}
.sub {{ color:var(--muted); margin:0 0 20px }}
a {{ color:var(--link) }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:16px 0 8px }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px }}
.card .n {{ font-size:30px; font-weight:700 }} .card .l {{ color:var(--muted); font-size:13px }}
.card.green .n {{ color:var(--g) }} .card.yellow .n {{ color:var(--y) }} .card.red .n {{ color:var(--r) }}
.bar {{ display:flex; height:12px; border-radius:6px; overflow:hidden; background:var(--line); min-width:80px }}
.seg.green {{ background:var(--g) }} .seg.yellow {{ background:var(--y) }} .seg.red {{ background:var(--r) }}
.big .bar {{ height:18px }}
.tw {{ overflow-x:auto; border:1px solid var(--line); border-radius:10px; background:var(--card) }}
table {{ border-collapse:collapse; width:100% }}
th,td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top }}
th {{ font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted) }}
tr:last-child td {{ border-bottom:0 }}
td.code {{ font-family:ui-monospace,Menlo,monospace; white-space:nowrap; font-size:13px }}
td.ev {{ color:var(--muted); font-size:14px; min-width:260px }}
td.num {{ text-align:right; font-weight:600; width:48px }} td.num.g {{ color:var(--g) }} td.num.y {{ color:var(--y) }} td.num.r {{ color:var(--r) }}
td.barcell {{ width:40% }}
tr.green td:first-child {{ box-shadow:inset 4px 0 var(--g) }} tr.yellow td:first-child {{ box-shadow:inset 4px 0 var(--y) }} tr.red td:first-child {{ box-shadow:inset 4px 0 var(--r) }}
.pill {{ display:inline-block; padding:2px 9px; border-radius:999px; font-size:12px; font-weight:600; white-space:nowrap }}
.pill.green {{ background:var(--gbg); color:var(--g) }} .pill.yellow {{ background:var(--ybg); color:var(--y) }} .pill.red {{ background:var(--rbg); color:var(--r) }}
.note {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; margin:16px 0 }}
.note ul {{ margin:6px 0 0; padding-left:20px }}
.legend span {{ margin-right:14px }}
</style></head><body><main>
<h1>Windy Git Gap Analysis</h1>
<p class="sub">DNA Strand Master Plan v0.1.0 (strands G0–G12) scored against the live system and repo on <strong>Saturday 10-17-2026</strong>. Evidence: repo main f4a5ea2, Veron live state, Gitea and plane databases, tests (436 pass). First Windy Git gap report.</p>

<div class="cards">
  <div class="card"><div class="n">{len(all_rows)}</div><div class="l">codons scored</div></div>
  <div class="card green"><div class="n">{tot[G]}</div><div class="l">done (green)</div></div>
  <div class="card yellow"><div class="n">{tot[Y]}</div><div class="l">partial (yellow)</div></div>
  <div class="card red"><div class="n">{tot[R]}</div><div class="l">not done (red)</div></div>
</div>
<div class="big">{bar(tot)}</div>
<p class="legend sub" style="margin-top:8px"><span><span class="pill green">Done</span> built and verified</span><span><span class="pill yellow">Partial</span> built but missing a piece or proof</span><span><span class="pill red">Not done</span> not built, or blocked</span></p>

<div class="note"><strong>The short version</strong>
<ul>
<li><strong>The verification half is real.</strong> CI for private repos (G7) is green: 36 repos, 2,827 runs in 7 days, red checks on GitHub PRs. Hosting, Gitea, backups and restore drills are mostly green.</li>
<li><strong>The product half is mostly not started.</strong> The shelter (G5, the planned v0 product), agent tokens and provenance (G6, G9), the MCP surface (G8) and the model hub (G10) are mostly red.</li>
<li><strong>The biggest unblocker is agent identity.</strong> The ES256 agent verifier (G3.2) is missing, so agent auth fails closed. That keeps G3.3, G6.3, G8 and G9 red.</li>
<li><strong>Cheap wins:</strong> the canonical-domains lint in this repo (G0.10), a gpu runner label (G7.1), mirror-lag alerts (G11.2), redeploying the API image so /version matches main (G12.7).</li>
<li><strong>Grant-gated:</strong> the model hub (§7.7), opening to non-Grant users (R0→R1), and any pricing.</li>
</ul></div>

<h2>By strand</h2>
<div class="tw"><table><thead><tr><th>Strand</th><th>Name</th><th>Done</th><th>Partial</th><th>Not done</th><th>Progress</th></tr></thead><tbody>{strand_summary}</tbody></table></div>

<h2>Invariants (I-1 to I-13) <small>{inv[G]} done · {inv[Y]} partial · {inv[R]} not done</small></h2>
<div class="tw"><table class="codons"><thead><tr><th>Invariant</th><th>Rule</th><th>Status</th><th>Evidence</th></tr></thead><tbody>{inv_rows}</tbody></table></div>

{sections}

<p class="sub" style="margin-top:32px">Scoring rule: green only with evidence seen today (live system, database rows or a passing test). Where a fact wasn't re-checked for this report, the codon is yellow and says so. Counts only; no secrets or personal data.</p>
</main></body></html>"""

open(sys.argv[1], "w").write(page)
print(f"codons {len(all_rows)}: green {tot[G]} yellow {tot[Y]} red {tot[R]}; invariants {inv}")
