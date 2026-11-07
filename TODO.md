# TODO.md: Windy Git (windy-git)

The one list for this repo. Read it first; add every promise to it the same turn. Five sections in this order. Times are UTC.
Owner of every line is the Windy Git lane unless it says otherwise. A line leaves only into Done, or on a named instruction from the coordinating lane.

## WE ARE LIVE (Grant's standing rule, BOARD 2026-11-06 23:29:54Z; read 2026-11-07)
Build, wire and ship for real at full speed; nothing waits for "after the friends' trial" because a stray visitor might have a rough time. Unchanged: principle 1 (do not break what is live; every change has a way back), principle 9 (say only what is true), consent is a human act, secrets stay in the lockbox, the coordinating lane's go-ahead by commit id for production.
Grant's five gates before the big marketing push: (1) Grant and friends say "really solid"; (2) the back-end records work across the repos (ledger, legal sign/archive/recall, support email, smooth sign-up); (3) an attorney reviews the legal documents; (4) Grant rolls every token (the vault lane leads); (5) then the marketing money. Public Windstorm Labs address: the Lehi line in windy-contracts registry/company.json.
For this repo: CI throughput, the mirror work and the queue priority are on the live path. Load safety (principle 1) is the limit, not caution about visitors.

## Now
Line standard (coordinating lane): `- [ ] what · OWNER · ADDED · DUE · STATUS · SOURCE`. Times are UTC. Dated lines first.
- [ ] Gitea 1.24.7 to 28.3.0 (175 upstream security advisories since 1.24.7): live cutover with tools/gitea-cutover.sh after a runner drain (tools/runner-drain.sh: each runner stopped only when idle); preflight 0 running jobs, minute :17-:30, load1 under 14; fresh dump + data copy; automatic rollback; AFTER includes one real multi-job run (status 9 to 7 to 5 seen live) · Windy Git · 2026-11-07 · proposed Sun 2026-11-08 07:17 (retry 08:17, latest start 09:17, done by 09:50) · PR #149 at bc43181a: Hub STAMPED; needs the coordinating lane's read + stamp, PRIORITY for its gate, then a go-ahead by commit id · Russ (human) 2026-11-07 ~08:15; coordinating lane 2026-11-07 14:0x (no cutover today, propose Sunday)
- [ ] Delete the rehearsal copy (it holds production data; root-only) · Windy Git · 2026-11-07 · Sun 2026-11-08 12:00 (the runner-swap rehearsal takes a fresh copy) · kept until then · this lane 2026-11-07
- [ ] Delete the cutover rollback point (holds secrets) · Windy Git · 2026-11-07 · cutover + 7 days · not made yet (made at cutover) · this lane 2026-11-07
- [ ] veron-1-4 runner trial (the veron-1 label had 64 waiting jobs on 1 runner): restart only when load1 stays under 12 for 10 min, stops with a 240 s grace (never a 10 s kill), drop at io avg60 over 20 OR load1 over 18 · Windy Git · 2026-11-07 · when load allows · STOPPED 13:51:16 by the drop rule (load1 18.22) after 14 jobs in 12.5 min; that 10 s stop cut windy-admin #882's job (re-run run 318 PASSED) · coordinating lane 2026-11-07 13:32:02Z and 13:54:02Z
- [ ] windyword-site #316 at 56e6daa3: post the re-run's result (Gitea made no run when the head moved ~10:14) · Windy Git · 2026-11-07 · when run 305 ends · run 305 queued · coordinating lane 2026-11-07 13:32:02Z (1)
- [ ] test-boss mirror (private, docs-only, sync-only); then send its Windy Git address to the Veron infra lane · Windy Git · 2026-11-07 · after #150 merges · PR #150 (a9505c63) needs a reader + stamp · Grant via the Veron infra lane 2026-11-07 ~09:2x
- [ ] Bridge windy-drops-site (guard checks only, Gitea Actions stays OFF: its one workflow deploys) and windy-control-panel (Actions ON at deploy); AFTER line reads back has_actions + run counts · Windy Git · 2026-11-07 · after #151 merges · PR #151 (9148b362), Drops READ OK; needs Hub + stamp · Windy Drops 2026-11-07
- [ ] Eternitas lab passport: P-256 agent key, private half in the lockbox; check the stored key matches its public half, then send ONLY the 43-char thumbprint at least 1 h before the slot · Windy Git · 2026-11-07 · new slot (asked: Sun 2026-11-08 13:20-13:35) · key made; lockbox add PR open · Eternitas 2026-11-07; 11-07 13:05 slot did not run (board 12:48:23Z)
- [ ] windy-uptime Eternitas journey to ET26-TEST + tokens/agent (DPoP, its own key), dark first; then Eternitas revokes the old passport · Windy Git · 2026-11-07 · Tue 2026-11-10 if the lab slot is by Sun 2026-11-08, else that slot + 2 days · not started · Eternitas TODO #327 + this lane 2026-11-07
- [ ] Sun 2026-11-08 night: nightly TODO checker, dark first, then one board line a day (per repo: TODO.md present, last updated, commits since) · Windy Git · 2026-11-06 · Sun 2026-11-08 · not started · coordinating lane 2026-11-06
- [ ] Gitea staying current, mechanical not memory: (a) daily upstream watcher timer (new releases + advisories covering our version: board line; critical/high: red tile) and (b) staleness alarm (over 30 days behind a patch release, or a critical/high unpatched over 72 h) · Windy Git · 2026-11-07 · Mon 2026-11-09 18:00 · not started · Russ (human) 2026-11-07
- [ ] Gitea rehearsal as a script (tools/gitea-rehearse.sh) that runs on each new release and opens the image-bump PR with its report; later auto-cutover for patch releases only, on the coordinating lane's OK of that policy · Windy Git · 2026-11-07 · Wed 2026-11-11 18:00 · not started · Russ (human) 2026-11-07
- [ ] Runner image swap act_runner 0.6.1 to gitea/runner 5.x (closes the runner sandbox-escape advisory): own rehearsal + ask · Windy Git · 2026-11-07 · Tue 2026-11-10 · not started (old and new both proven against 28.3.0) · this lane 2026-11-07
- [ ] Windy 0 runners: one action-clone cache per runner (each act-runner@N unit gets its own XDG_CACHE_HOME); today all 5 share one and two jobs refreshing the same action break each other (windy-search job 72430, 11-07; likely windy-connect #131 too) · Windy Git · 2026-11-07 · PR Mon 2026-11-09 18:00; applied only on the coordinating lane's go-ahead, each runner restarted only when idle · not started · Windy Search 2026-11-07
- [ ] windy-search main 87962d1e job 72430: ONE re-run on the coordinating lane's go-ahead, then the result to Search · Windy Git · 2026-11-07 · on the go-ahead · asked on the board 14:4x · Windy Search 2026-11-07
- [ ] Bridge: when main (or a PR head) moves, post one final state on the previous head (today it stays "pending" forever; seen again 11-07 on windy-calendar #144 3065aa19) · Windy Git · 2026-11-07 · Mon 2026-11-09 18:00 · not started · Windy Hand question 2026-11-07
- [ ] Docs-only fast path: a PR touching ONLY TODO.md, README.md or docs/** runs lint, secret-guard and ci-hygiene only · Windy Git · 2026-11-06 · Mon 2026-11-09 12:00 · not started · coordinating lane 2026-11-06
- [ ] Null 0 Chromium launch flake (windy-chat Calls test, 7 of 120 on null0-2): read the other failure logs, find the cause, fix, board line · Windy Git · 2026-11-06 · Mon 2026-11-09 12:00 · not started · coordinating lane 2026-11-06
- [ ] Windy Git tile line on the board ("TILE Windy Git: label, badge, link, note TRUE" or what must change) and here, same turn · Windy Git · 2026-11-06 · Mon 2026-11-09 18:00 · not started · coordinating lane 2026-11-06
- [ ] Read the Hub's windy-hub move plan, then the Word lane's windy-fly-desktop move plan, for CI, runners, PRIORITY, cancel-superseded and the Kit 0 scripts · Windy Git · 2026-11-06 · Tue 2026-11-10 18:00 and Wed 2026-11-11 18:00 · waiting for the plans · coordinating lane 2026-11-06
- [ ] One codon line in the repo master plan ("Windy Log", pointing at the Windy Fly vision chronicle) + the matching lines here · Windy Git · 2026-11-06 · Wed 2026-11-11 18:00 · not started · coordinating lane 2026-11-06
- [ ] windy-contracts machinery plus its TODO.md and owner line (this lane merges no contract PR) · Windy Git · 2026-11-06 · Fri 2026-11-13 · not started · coordinating lane 2026-11-06
- [ ] Name alignment: per candidate repo, the COUNT of references to the old name (CI lists, Kit 0 and Veron scripts, Pages links, uptime checks, docs); plus counts for windy-pro and windy-pro-mobile · Windy Git · 2026-11-06 · Fri 2026-11-13 18:00 · preliminary 11-06: 46 and 11 files here · coordinating lane 2026-11-06
- [ ] Nightly REGISTRY check (every Windy repo in the Hub registry exactly once, else a board alarm), dark first · Windy Git · 2026-11-06 · Fri 2026-11-13, once the registry draft exists · waiting for the draft · coordinating lane 2026-11-06
- [ ] Delete the merged leftover branches in the Branches table, each with its archive tag first (tip = a merged PR's head), on the coordinating lane's OK · Windy Git · 2026-11-04 · Fri 2026-11-13 · table ready · coordinating lane 2026-11-04
- [ ] Repo renames in batches of three, BEFORE and AFTER on the board; after the windy-pro split: windy-pro to windy-word, windy-pro-mobile to windy-fly-mobile · Windy Git · 2026-11-06 · from Mon 2026-11-16 · not started · coordinating lane 2026-11-06
- [ ] Tailscale slot preparation (slot 14:00-15:30), each step on the coordinating lane's go-ahead · Windy Git · 2026-11-06 · Sun 2026-11-08 13:30 · waiter armed · coordinating lane 2026-11-06
- [ ] windy-board (owner: this lane): windy-uptime #81 heartbeat read + stamp; snapshot code into deploy/board-snapshot here; a repo-scoped deploy key via the vault lane; add windy-board to the registry check · Windy Git · 2026-11-06 · with the registry check · snapshot live hourly (now rebases before commit) · coordinating lane 2026-11-06
- [ ] Heartbeats PR in the uptime monitor repo: ci-egress, offsite-guard, signin-guard, priority-queue · Windy Git · 2026-11-04 · open · not started · this lane 2026-11-04
- [ ] Daily 12:00 queue line (p95 wait target under 15 min), re-armed after the checker goes live · Windy Git · 2026-11-04 · Tue 2026-11-10 12:00 · loop armed · coordinating lane 2026-11-04
- [ ] Standing rules: PRIORITY tokens (newest three count) and cancel-superseded keep running; a re-run only after a board line names it; birth-terms ABSENT is a pass only with this lane's board line naming the exact head with "findings None"; a head behind main ONLY by TODO.md-only commits may merge without a rebase under the 2026-11-07 04:13:51Z rule · Windy Git · 2026-11-06 · standing · in force · coordinating lane 2026-11-06 13:55Z and 2026-11-07 04:13:51Z

## Waiting on
- [ ] Stamp + reader on #148 (lane map, Hub READ OK), #147 (Cloudflare token shapes), #149 (Hub stamped), #150 and #151 · coordinating lane · 2026-11-06 · none set · asked on the board · this lane's asks 11-06/11-07
- [ ] Stamp on #142 (cross-host drill reads the dated R2 key pair); a waiter merges it at head 4f25683d, then one drill run and a lockbox note PR · coordinating lane · 2026-11-05 · none set · stale, asked for direction · this lane 2026-11-05
- [ ] Windy Cell: when its next PR (strand refresh) has been open 10 min or more, check its windy-git contexts and post the result on the board · Windy Cell (opens) / Windy Git (checks) · 2026-11-07 · Fri 2026-11-13 · waiting for the PR · Windy Cell 2026-11-07
- [ ] Windy CFO: read windy-cfo #8 (DNA v1.0) at its FINAL head · Windy CFO (asks) / Windy Git (reads) · 2026-11-07 · around Thu 2026-11-12 · waiting for the final head · Windy CFO 2026-11-07
- [ ] Answer on deleting 13 stale *-soul pull-mirror copies plus legal-ops (~270 MB) from the forge (recommendation: delete) · coordinating lane · 2026-11-04 · none set · asked · this lane 2026-11-04
- [ ] Repo deletes (windygit-mirror-test-553, windy-stt) only after Grant grants delete_repo and the go-ahead names the repo · Grant · 2026-11-04 · none set · waiting · coordinating lane 2026-11-04
- [ ] The vault lane: GitHub App ids and install numbers (CI status app, mirror app), then the consumer PRs; a repo-scoped deploy key for the windy-board push · Windy Vault · 2026-11-03 · none set · asked · this lane 2026-11-03
- [ ] A person's hands-step: create the key for the CI status GitHub App (steps written) · Grant · 2026-11-03 · none set · waiting · this lane 2026-11-03
- [ ] Option B (the windy-pro runner split and its read token): ONCE, on the final repos after the windy-pro split, not before · coordinating lane · 2026-11-06 · after the split · waiting · coordinating lane 2026-11-06 19:22Z

## Later
- [ ] Switch scripts/rerun_ci.sh's rewind to the rerun API Gitea 28.x has; turn on RUN_RETENTION_DAYS; bridge links by run id · Windy Git · 2026-11-07 · after the Gitea cutover · not started · this lane 2026-11-07
- [ ] Windy Cell: the #38/#39 cutover after the rename; windy-cell-site CI when that lane wants it · Windy Git · 2026-11-06 · when asked · waiting · Windy Cell 2026-11-06
- [ ] Forge hardening (external-user features off, basic auth for people): built and tested first, applied only in a named slot · Windy Git · 2026-11-04 · none set · not started · coordinating lane 2026-11-04
- [ ] act_runner step-level timeout test and a PR; revert the runner job ceiling 150 to 90 minutes the day the suite owner posts a dated proof · Windy Git · 2026-10-29 · none set · waiting for the proof · this lane 2026-10-29
- [ ] Check whether the scheduler reads cron in UTC (first scheduled Postgres suite run) · Windy Git · 2026-11-04 · none set · not started · this lane 2026-11-04
- [ ] Archive the four probe repositories (wg586-probe, probe-502-test, ssrfprobe527, windygit-mirror-test-553): proposal only · Windy Git · 2026-11-04 · none set · not started · this lane 2026-11-04
- [ ] A monthly archive of the board file (windy-board): a plan first; the PRIORITY reader and every lane's tail must keep working · Windy Git · 2026-11-06 · none set · not started · this lane 2026-11-06
- [ ] Name an out-of-memory kill inside the offsite job engine as its own red; count it for the first week · Windy Git · 2026-11-04 · none set · not started · this lane 2026-11-04
- [ ] veron-1 label capacity: a lasting answer (more runners or fewer veron-1-only jobs); trial data: veron-1-4 did 14 jobs in 12.5 min but took load1 from 10 to 18 · Windy Git · 2026-11-07 · Tue 2026-11-10 18:00 · trial stopped, data in · this lane 2026-11-07

## Branches
Table computed 2026-11-04, refreshed 2026-11-07 for open PRs below; the rest is unchanged from the GitHub branch list and each branch's PR. A branch whose tip equals a merged PR's head lost no work; its archive tag comes first, deletion Fri 2026-11-13.

| Branch | PR | Last | Owner | Verdict |
|---|---|---|---|---|
| todo-md | #131 | 2026-11-07 | Windy Git | open PR (this one): keep until it merges |
| drill-new-r2-names | #142 | 2026-11-05 | Windy Git | open PR: keep until it merges (waiter armed) |
| ops/windy-cell-rename | #144 | 2026-11-06 | Windy Git | closed unmerged 2026-11-07 (superseded by #146): archive tag, then delete Fri 2026-11-13 |
| ops/add-windy-legal-cfo | #145 | 2026-11-06 | Windy Git | merged 2026-11-07 (as #146's ancestor): delete after its archive tag, Fri 2026-11-13 |
| ops/mirror-all-81 | #146 | 2026-11-07 | Windy Git | merged 2026-11-07 (merge commit 26782051): delete after its archive tag, Fri 2026-11-13 |
| sec/secret-guard-cloudflare | #147 | 2026-11-06 | Windy Git | open PR: keep until it merges |
| ops/lane-map-final | #148 | 2026-11-07 | Windy Git | open PR: keep until it merges |
| ops/gitea-28.3.0 | #149 | 2026-11-07 | Windy Git | open PR: keep until it merges |
| ops/mirror-test-boss | #150 | 2026-11-07 | Windy Git | open PR: keep until it merges |
| ops/bridge-drops-site-cp | #151 | 2026-11-07 | Windy Git | open PR: keep until it merges |
| ci/allow-mobile-firebase-key | #120 |  | not mine (see the PR) | open PR: keep until it merges |
| null0-runner-3 | #129 | 2026-11-04 | Windy Git | merged 2026-11-04 22:17Z; delete after its archive tag, Fri 2026-11-13 |
| onboard/site-batch | #67 |  | not mine (see the PR) | open PR: keep until it merges |
| priority-queue | #130 | 2026-11-04 | Windy Git | merged 2026-11-04 22:15Z; delete after its archive tag, Fri 2026-11-13 |
| approved-first | #96 |  | Windy Git | closed unmerged 2026-10-28; superseded in intent by the priority timer (#130). KEEP, archive tag archive/approved-first-2026-11-04 exists; final verdict Fri 2026-11-13 |
| vault/lockbox-put-batch | #115 |  | Windy Git | closed unmerged 2026-11-02. KEEP, archive tag archive/vault-lockbox-put-batch-2026-11-04 exists; final verdict Fri 2026-11-13 (read the PR's closing comment first) |
| add-windy-contracts | #7 | 2026-10-05 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| allow-scan-1012-fixtures | #26 | 2026-10-12 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| allow-vault-rfc9180-vector | #25 | 2026-10-10 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| allow/windy-mind-site-openrouter | #66 | 2026-10-23 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| autorerun-dead-jobs | #12 | 2026-10-07 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| autorerun/ignore-unrunnable-cancels | #46 | 2026-10-21 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| backup-age-encrypt | #22 | 2026-10-10 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| bridge-archive-branch-explain | #17 | 2026-10-10 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| bridge-cache-runs-and-step | #10 | 2026-10-06 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| bridge-explicit-step-names | #15 | 2026-10-10 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| bridge-infra-hint-fix | #11 | 2026-10-06 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| bridge-one-statuses-get | #30 | 2026-10-16 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| cg-allow-reason-names | #28 | 2026-10-14 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| cg/clone-byoc-only | #47 | 2026-10-21 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| ci-prune-keep-toolcache | #29 | 2026-10-16 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| ci-prune-networks | #9 | 2026-10-06 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| ci-wait-for-postgres | #21 | 2026-10-10 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| ci/autorerun-head-check | #41 | 2026-10-18 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| ci/autorerun-runner-lost | #40 | 2026-10-18 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| ci/bridge-page-gitea-pulls | #37 | 2026-10-17 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| ci/bridge-runner-lost | #39 | 2026-10-18 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| ci/bridge-statuses-empty-on-error | #36 | 2026-10-17 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| ci/compute-guard-legal-prose | #34 | 2026-10-17 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| ci/doc-tunnel-metrics-2021 | #38 | 2026-10-17 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| ci/mirror-lag-alert | #44 | 2026-10-21 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| ci/mirror-lag-page-cap | #49 | 2026-10-21 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| ci/onboard-windy-mind-acp | #48 | 2026-10-21 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| ci/prune-job-networks-often | #54 | 2026-10-21 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| ci/reap-finished-task-containers | #58 | 2026-10-21 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| ci/rerun-push-lock | #59 | 2026-10-21 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| ci/sync-control-panel-text-site | #33 | 2026-10-17 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| ci/sync-windy-pro-mobile | #32 | 2026-10-17 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| ci/unlist-control-panel | #35 | 2026-10-17 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| compute-guard-gatekeeper | #3 | 2026-10-02 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| contracts-drift-sweep | #8 | 2026-10-05 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| docs-cutover-primary-windy-git | #19 | 2026-10-10 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| docs/ci-coverage-2026-10-21 | #61 | 2026-10-21 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| docs/salvage-windy0-specs | #50 | 2026-10-21 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| facts-only-messages | #13 | 2026-10-07 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| guard-drop-8099 | #4 | 2026-10-02 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| guard-exempt-talk-client | #6 | 2026-10-02 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| guard-exempt-talk-registry | #5 | 2026-10-02 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| guard/birth-terms | #53 | 2026-10-21 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| guard/birth-terms-pre-block | #56 | 2026-10-21 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| guard/sweep-nits | #55 | 2026-10-21 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| hub/lockbox-put-stdin | #65 | 2026-10-23 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| merge-audit | #24 | 2026-10-10 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| onboard-windy-uptime | #27 | 2026-10-12 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| onboard-windy-vault | #23 | 2026-10-10 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| onboard/windy-admin | #60 | 2026-10-21 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| onboard/windy-mind-site | #64 | 2026-10-23 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| predeploy-snapshot-no-plaintext | #31 | 2026-10-16 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| runner-guard | #2 | 2026-10-01 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| runner/ci-image-envsubst | #62 | 2026-10-23 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| runner/prune-live-volume | #63 | 2026-10-23 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| sweep/move-to-veron | #42 | 2026-10-21 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| sync-narrow-gitea-token | #16 | 2026-10-10 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| sync-token-hygiene-check | #20 | 2026-10-10 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| sync-token-out-of-argv | #18 | 2026-10-10 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| sync/fetch-timeout-retry | #57 | 2026-10-21 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| sync/has-commit-graphql | #51 | 2026-10-21 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| sync/has-commit-reachable | #52 | 2026-10-21 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| sync/prune-cursor-string-compare | #45 | 2026-10-21 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| sync/prune-gone-branches | #43 | 2026-10-21 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| vault/lockbox-put-value-4096 | #116 | 2026-11-02 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| veron-ollama-warn | #1 | 2026-10-01 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |
| windy0-one-nightly-sweep | #14 | 2026-10-10 | Windy Git | merged leftover (tip = the merged PR's head): delete OK after its archive tag; deletion Fri 2026-11-13 |

## Done (last 30 days)
- 2026-11-07 windy-git #131 merged (2c2a75bf) and windy-git-site #2 merged (26723a6e): TODO.md on main in both, every open line in the standard
- 2026-11-07 #149 gate fixes: G2.1 accepts a digest pin; Gitea 28.x job status 9 (pending on needs) and 8 (cancelling) plus run-attempt rows handled in cancel_superseded and telemetry, checked on the migrated copy and on live (EXPLAIN); Hub stamped bc43181a
- 2026-11-07 tools/runner-drain.sh (status, drain, restore) for all 13 runners on 3 hosts; status read-only checked on all of them
- 2026-11-07 windy-admin #882 re-run after the veron-1-4 stop: run 318 PASSED
- 2026-11-07 windy-connect #131 job 71367: ONE re-run on the go-ahead (11:56:26Z), 3.11 passed on the same runner (w0-2) at 12:04:41Z, so a runner checkout race, not the code
- 2026-11-07 #146 merged with a merge commit (#145 as ancestor); Gitea renames windy-cell to windy-cell-legacy and windy-mobile to windy-cell, legacy refs identical before/after; #144 closed
- 2026-11-07 Gitea 28.3.0 rehearsal on a migrated copy: migrations clean, no column our SQL uses removed, API calls and old run links work, old and new runners each ran a job (docs/UPGRADE-GITEA.md in #149)
- 2026-11-07 board-snapshot job made merge-safe (fetch + rebase before commit; on failure a heartbeat, no push)
- 2026-11-07 Veron container DNS fixed for good (applied 23:52:58Z by the Veron infra lane); 3 of 3 container lookups verified; alert-only watcher on for 24 h
- 2026-11-06 windy-board: repo imported, first push 99468db1, hourly snapshot timer on Windy 0 live, first scheduled run 21:07Z clean (counts in the commit message, secret hit = no push + alarm)
- 2026-11-06 mirror-all: 3 + 8 + 30 + 3 repos imported to the forge (windy-log, windy-log-site, windy-hub, windy-fly-desktop, windy-legal, windy-cfo, windy-board among them); mirror-only repos have Actions off
- 2026-11-06 Veron general runners 1 to 3 overnight under the load rules, back to 1 at 09:30Z; stale queue pruned (closed PRs, replaced heads); calendar main job jumped; windy-hand #37 CI re-queued once
- 2026-11-05 #143 priority timer: accept an end time with seconds + board WARN on an unparseable PRIORITY line
- 2026-11-05 #141 priority timer: move every workflow of the PR head, not only the newest run
- 2026-11-05 #140 status bridge: read EVERY open GitHub PR, not just the first 100 (windy-pro #885 had no CI)
- 2026-11-05 #139 Windy 0 CI runners: version the host config, register script, egress probe, install, tests
- 2026-11-05 #138 journey window + Veron throttle: version the live script, units, tests
- 2026-11-05 #137 mirror lag: once-a-day board line for mirrors out of step 24 h+ (known-stale included)
- 2026-11-05 #136 veron-heavy: nice/ionice, worker caps, wait while load1 >= 48 or io >= 30
- 2026-11-05 #135 priority timer: resolve a GitHub PR number to its Windy Git PR (head sha)
- 2026-11-05 #134 ept-cutoff test: absent or null ept_valid_after = no cutoff
- 2026-11-04 #133 offsite guard: cover the Windy 0 runners (w0-*) and stop null0-3 too
- 2026-11-04 #132 auth: refuse an EPT issued before the passport's ept_valid_after (ept-cutoff.v1)
- 2026-11-04 #130 priority_queue: a PR the coordinating lane names on the board runs first (PRIORITY repo#PR until ISO)
- 2026-11-04 #129 offsite runners: a third Null 0 runner (null0-3) for windy-mind
- 2026-11-04 #128 signin guard: pin the ways into the forge, read-only hourly check
- 2026-11-04 #127 red_main: exempt windy-pro's known-red Postgres suite until 11-30
- 2026-11-03 #126 runner_guard: record a status as posted only after GitHub accepted it
- 2026-11-02 #125 disk_free: GB tiers (150 LOW / 50 CRITICAL), one BOARD + Boss line per crossing; retire the 10% WARN
- 2026-11-02 #124 bridge: one GraphQL query per pass for open PRs + default heads (~950 fewer shared REST calls/h) + call counter
- 2026-11-02 #123 register.sh: pass only the last line of generate-runner-token (Gitea prints a log line on stdout first)
- 2026-11-02 #122 Offsite guard: Null 0 runners stay repo-scoped + secret-free, else cut off (Hub #121); Null 0 egress unit; probe fixes
- 2026-11-02 #121 Offsite CI runners for Null 0: repo-scoped, never veron-1, capped, no mounts (Boss GO 11-02)
- 2026-11-02 #119 autorerun SQL refuses a non-40-hex sha itself (Hub #117); BOARD fallback writes TODAY's file (Boss)
- 2026-11-02 #118 CI egress: hook FIRST in FORWARD (ahead of tailscale), re-asserted + proved every 15 min (11-02)
- 2026-11-02 #117 autorerun: dead-before-step in secret-holding repos, once, under Hub's six limits (Hub 11-02)
- 2026-11-02 #116 lockbox-put: values up to 4096 chars (was 512); stdin cap 8192
- 2026-11-02 #114 secret guard: allow windy-agent's old 20-char stripe-live-SHAPED fixture by hash
- 2026-11-02 #113 secret guard: allow windytalk's release script PEM header/footer, that ONE file only
- 2026-11-02 #112 red_main: a default-branch status red > 24 h gets one BOARD line, then daily (Boss 11-02)
- 2026-10-29 #111 runner docs: the ceiling is the ONLY job limit; act_runner 0.6.1 ignores job timeout-minutes
- 2026-10-29 #110 runner: per-job ceiling 90 -> 150 min (windy-admin's serial suite)
- 2026-10-29 #109 bridge: name the runner ceiling (not "runner lost"), never auto re-run a ceiling cut, show waiting -> running
- 2026-10-29 #108 windygitci.slice: CPUWeight 50, persistent (Boss 10-29 GO)
- 2026-10-29 #107 secret guard: allow the published cosign TEST key in eternitas-authenticator, that ONE file only
- 2026-10-28 #106 approved_first: a cached approval expires after 30 min and is re-read (Hub #96 LOW)
- 2026-10-28 #105 status_gap: PR files paged, Gitea's own run beats a head-commit filter, budget skips deferred (Hub #90 LOWs)
- 2026-10-28 #104 canary runner: mounts nothing, and only canary.yml may run on it (Hub #95 LOWs)
- 2026-10-28 #103 cancel_superseded: also cancel BLOCKED (needs:) jobs of replaced PR commits (Hub #94 LOW)
- 2026-10-28 #102 onboard eternitas-site and eternitas-authenticator to Windy Git CI (sync + bridge)
- 2026-10-28 #101 queue_jump: an unreadable job state is a FAILURE, never "picked" (Hub #97 LOW)
- 2026-10-28 #100 approved_first: fully-approved PRs' jobs go first, oldest first, a slot at a time (re-open of #96)
- 2026-10-28 #99 bridge step 2: re-read a head only when Windy Git has news (cross-pass cache, hourly backstop)
- 2026-10-28 #98 CI image: bake the Mirror's cipher module, pinned twice (gate downloads nothing)
- 2026-10-28 #97 queue_jump: OK only when the job really got a task; cancelled-while-waiting is a FAILURE
- 2026-10-28 #95 canary: its own runner, a silence WARN, and a dark HQ row
- 2026-10-28 #94 cancel_superseded: cancel WAITING PR jobs whose commit a newer push replaced
- 2026-10-28 #93 workflow guard: no path filters on suites; live-host jobs manual-only unless NAMED
- 2026-10-28 #92 bridge: skip a pass below 1500 GitHub calls left; 3 skips in a row fail the pass
- 2026-10-28 #91 onboard windy-mobile and windycloud-site to Windy Git CI (sync + bridge)
- 2026-10-28 #90 status_gap: every PR / default head gets Windy Git CI statuses within 30 min, or says why
- 2026-10-28 #89 disk_free: Veron's free disk in the uptime beat; under 10% = WARN to Boss
- 2026-10-28 #88 flake_count: count logged CI flake retries per 7 days; over 2 = a LOW to Boss
- 2026-10-28 #87 runbook: queue jump (scripts/queue_jump.sh) and the safe runner drain
- 2026-10-27 #86 CI jobs: docker-init as PID 1 (--init) so orphans are reaped
- 2026-10-27 #85 CI image: Chromium for Playwright 1.59.1 (r1217), baked in
- 2026-10-27 #84 CI runners: 2 by default, runners 3-6 behind a compose profile
- 2026-10-27 #83 CI no-skip drop-in: allow only the named LIVE_ONLY.txt list
- 2026-10-27 #82 CI no-skip: sessionfinish backstop for skips the hooks can't see
- 2026-10-27 #81 CI image: add rclone v1.60.1, sha256-pinned
- 2026-10-27 #80 secret-guard: allow windy-contracts' IndexNow test placeholder by hash
- 2026-10-27 #79 CI: a skipped test fails under CI=true
- 2026-10-27 #78 CI image: add age (pinned) so backup-encryption tests run in CI
- 2026-10-27 #77 secret-guard: Stripe test-key and webhook-secret shapes
- 2026-10-27 #76 ci-image guard: the sha256 check must be able to stop the build
- 2026-10-27 #75 CI image: PowerShell 7.4 LTS (sha256-pinned) + prove every pinned tool
- 2026-10-27 #74 recreate-idle.sh: stop any idle runner each pass, not one at a time
- 2026-10-27 #73 mirror-lag: mark lagging private mirrors as KNOWN-STALE
- 2026-10-27 #72 CI runners: own top-level slice at CPUWeight=20
- 2026-10-25 #71 compute-guard allow: windyword-site legal-generated.js
- 2026-10-25 #70 Onboard windyword-site to CI
- 2026-10-24 #69 CI image: add zsh for windy-pro-mobile's mobile-round tests
- 2026-10-24 #68 secret-guard allow: windy-code-web cabinet decoy fixtures
- 2026-10-23 #66 compute-guard allow: windy-mind-site openrouter.ai data + redirect-host guard (lines-only)
- 2026-10-23 #65 lockbox-put: '-' reads the value from stdin (no temp file; refuses a TTY)
- 2026-11-04 Forge sign-in pins live and checked hourly (see #128); the local admin password replaced with a random one nobody knows (tokens unaffected); `veron-heavy` heavy-job semaphore installed on the shared host.
