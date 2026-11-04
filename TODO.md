# TODO.md: Windy Git (windy-git)

The one list for this repo. Read it first; add every promise to it the same turn. Five sections in this order. Times are UTC.
Owner of every line is the Windy Git lane unless it says otherwise. A line leaves only into Done, or on a named instruction from the coordinating lane.

## Now
- Merge the queue-priority timer (#130): a PR the coordinating lane names on the shared board runs before the rest of the CI queue, via one explicit token, expiring within 24 h. Read and approved at head dc6fd387; waits for the gate and one stamp. Then install and enable its timer. Done means: merged, the timer's first run says ok, a board line.
- Merge the third offsite CI runner (#129), scoped to one secret-free repo (windy-mind). Read and approved at head cf652696; waits for the gate and one stamp. Then start it, watch its first two jobs to green, keep >= 4 GB RAM and >= 20 GB disk free on that host. Done means: both jobs green, board BEFORE/AFTER.
- Name an out-of-memory kill inside the offsite job engine as its own red ("OOM in dind", from exit 137), count it for the first week; more than 0 a day means two concurrent jobs there. After the runner above is live.
- TODO.md rule: this file, a CLAUDE.md line in this repo, and the same in windy-git-site. Fri 2026-11-06.
- Nightly TODO checker (reads every repo, one board line a day) and the release gate `todo-gate`: plan + PR Fri 2026-11-06; the checker goes dark Sun 2026-11-08 and posts its first line Tue 2026-11-10 12:00.
- Heartbeats PR in the uptime monitor repo: ci-egress (45 min window), offsite-guard (45 min), signin-guard (3 h), priority-queue (20 min). Fri 2026-11-06.
- Network access hardening (a second wall on the private network): a named slot Sun 2026-11-08 14:00-15:30, each step on the coordinating lane's own go-ahead. Nothing before.
- Register this lane's journey identity with the identity service in its Sat 2026-11-07 13:05-13:20 window; send only the public key identifier by Fri 2026-11-06 evening.
- Daily 12:00 queue line (p95 wait target < 15 min in every hour), with the live queue depth until it is under 50. Re-arm Tue 2026-11-10.

## Waiting on
- Gate result and one stamp on #129 and #130 (coordinating lane).
- A person's hands-step: create the key for the CI status GitHub App (steps are written). Open since 2026-11-03.
- The uptime monitor repo's owner lane: merge of its #77 (my lines, reviewed).

## Later
- Check whether the scheduler reads cron in UTC (first scheduled run of the Postgres suite, Thu 2026-11-05 05:30).
- act_runner step-level timeout test (via the dispatch path) and a PR; revert the runner job ceiling 150 -> 90 minutes the day the suite owner posts a dated proof.
- Forge hardening (disable external-user features, basic auth for people): built and tested first; applied only in a slot the coordinating lane names, after the friends wave.
- Archive the four probe repositories (wg586-probe, probe-502-test, ssrfprobe527, windygit-mirror-test-553): proposal only, in the checker plan.
- App-click docs after the identity vault confirms.

## Branches
Computed 2026-11-04 from the GitHub branch list and each branch's PR. A branch whose tip equals a merged PR's head lost no work; its archive tag comes first, deletion Fri 2026-11-13.

| Branch | PR | Last | Owner | Verdict |
|---|---|---|---|---|
| ci/allow-mobile-firebase-key | #120 |  | not mine (see the PR) | open PR: keep until it merges |
| null0-runner-3 | #129 |  | Windy Git | open PR: keep until it merges |
| onboard/site-batch | #67 |  | not mine (see the PR) | open PR: keep until it merges |
| priority-queue | #130 |  | Windy Git | open PR: keep until it merges |
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
