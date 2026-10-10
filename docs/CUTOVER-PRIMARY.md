# Making Windy Git the PRIMARY home of one repo, starting with `windy-git` (after launch)

Status 2026-10-10: PLAN for Hub review. Nothing flipped. GitHub stays the source of truth until Hub
(with Grant's go) says otherwise. First repo: `windy-git` itself: public, one lane writes to it, and
its own gate (`.gitea/workflows/check.yml`) already runs green here on every push to main.

**After the flip:** lanes push to Windy Git. Windy Git pushes every new commit on to GitHub within
5 minutes. GitHub becomes the free off-site copy and the deploy source of last resort. Every step can
be undone, and nothing is deleted in either direction.

## Facts checked 2026-10-10 (re-check on the day)
- Checkouts that push: only OC5 `~/windy-git` (this lane). Veron `/srv/windygit/src` only fetches
  (from GitHub). Last 30 commits on GitHub: Windy Git lane 10, Kit OC5 7, plus 13 "Merge pull request"
  commits made through `gh` on GitHub.
- Windy Git repo `windyadmin/windy-git`: not a mirror, public. Every merge style is OFF (it only ever
  received the sync's force-pushes). No push mirror.
- `check.yml` (pytest + ruff) runs on every push to main here and is green (c95f3cf, 8fdba90, 8e7229a,
  11d7abf, ca41e5c). It has never run on windy-git PRs: the repo is public, so it is not in
  `BRIDGE_REPOS`, and its GitHub PRs get only `windy-git/runner-guard`. After the flip, PRs are native
  here and the gate runs on every PR. That is a gain.
- The sync no longer exposes tokens (#18). Every transfer has a 300 s timeout. The work dir is root 0750.
- Veron root disk: 65% (it was 95% on 10-10 morning).

## Preconditions (all must be true before step 1)
- [x] Encrypted nightly state backup (Postgres + Gitea config + repos); cross-host restore drill passed (10-01).
- [x] Gitea on a patched release (1.24.7); the upgrade path takes a snapshot first (docs/RESTORE-DRILL.md).
- [x] `windygit-state-backup` writes a heartbeat (`/var/lib/windy-heartbeats/windygit-state-backup.json`, ok).
- [ ] A missed backup actually PAGES: confirm it is on the paging list, and test once by skipping a night.
- [ ] Boss/Grant capacity call on Veron storage for DB + git. The root disk is at 65% now, but it hit 95% this morning.
- [ ] Post-launch freeze lifted (Hub). No cutover during store review or a launch window.
- [ ] Decisions D1–D3 below made.

## Decisions needed (Hub, with Grant where it touches his identity or credentials)
- **D1. Who acts on Windy Git.** `windyadmin` is Grant's identity (hub SSO), and nothing is done AS
  Grant. Proposal: two local Gitea bot users, created by admin (registration stays closed, no SSO, no
  member sign-in, so Hub's 10-01 four conditions are untouched):
  - `windy-git-lane`: write on `windy-git` only. It pushes branches, opens PRs and merges after approval.
  - `windy-hub-review`: read plus review on `windy-git` only. Hub approves PRs here.

  Tokens are scoped (`write:repository` and `read:repository` respectively). They are stored in the
  lockbox and in macOS keychain / root-0600 files, never in a URL.
- **D2. How GitHub stays current.** Proposal: NOT Gitea's built-in push mirror. Gitea keeps the
  credential in the repo's git config and passes it in a URL, which is exactly the leak class fixed in
  #18. Instead the sync script gets a second list, `PRIMARY`. For those repos it fetches from Windy Git
  and pushes to GitHub with the same header-in-env method and timeout as #18, every 5 minutes.
  - It pushes **without `--force`**. If anyone commits straight to GitHub, the push fails, the sync
    heartbeat goes red, and nothing is overwritten. That is the 08-13 lesson: a mirror must never
    silently push over live work.
  - It needs a GitHub token with contents:write on `sneakyfree/windy-git` only. Grant issues it
    (fine-grained). Lockbox name to be set by Boss.
- **D3. Merge rules on Windy Git.** Enable "Create merge commit" only, to match today's GitHub history.
  Protect `main`: no direct pushes; merge only via PR with 1 approval from `windy-hub-review` and a
  green `check / gate` status.

## Cutover for `windy-git` (reversible at every step)
0. BOARD line, and tell every lane that reads this repo. Confirm 0 open windy-git PRs on GitHub
   (merge or close them first) and that nobody has unpushed work on a branch. Run the cutover between sync runs.
1. **One windy-git PR (merged on GitHub, the old way, for the last time):**
   - Move `windy-git` from `REPOS` to `PRIMARY` in `scripts/sync_from_github.sh`, with the
     non-force reverse push and tests in the style of `test_sync_token_hygiene.py`.
   - Point the GitHub repo description/README at app.windygit.com as the home of the repo.

   Deploy it on Veron (ff-merge; the next sync run uses it). From that run on, the sync no longer
   overwrites Windy Git's windy-git, and it pushes Windy Git → GitHub.
2. **Verify both sides are equal:** main sha on Windy Git == GitHub, all branches and tags present
   (`git ls-remote` on both, diff empty). Note: the sync never pushed `archive/*` here, so archive
   branches exist only on GitHub. That is fine, and the non-force reverse push leaves them alone.
3. **Windy Git repo settings (admin, once):** create the D1 bot users with collaborator rights on
   `windy-git` only; turn on the D3 merge style and branch protection.
4. **Repoint the lane:** on OC5,
   `git remote set-url origin https://app.windygit.com/windyadmin/windy-git.git`, with the
   `windy-git-lane` token in the macOS keychain credential helper. Keep a `github` remote as read-only
   reference.
   - Veron `/srv/windygit/src` keeps FETCHING FROM GITHUB on purpose. GitHub lags at most about 5 min,
     and a broken Gitea must never stop us deploying the fix for Gitea.
5. **Test with a throwaway PR on Windy Git:** `check / gate` runs on the PR. Hub approves as
   `windy-hub-review`. The lane merges. Within 5 min the merge commit is on GitHub main. A direct push
   to GitHub (on a throwaway branch only) is never overwritten.
6. **Watch 3 days:**
   - reverse-push lag under 10 min, with no FAILED lines;
   - the nightly bundle and state backup include the new commits;
   - Hub's review flow works;
   - no checkout still pushes to GitHub (`git log` authors on GitHub == mirror pushes only).
7. **Rollback, at any time and in this order:**
   1. Repoint OC5 `origin` back to GitHub.
   2. Move `windy-git` from `PRIMARY` back to `REPOS`. GitHub already holds every commit, because the
      reverse push is non-force, so the normal sync resumes with nothing to reconcile.
   3. Turn the Windy Git merge styles back off.

   Nothing is deleted on either side.

## Doc changes that go with the flip
- `docs/CUTOVER.md`, "Phase 2": point to this file, and replace "add a push-mirror back to GitHub" with
  the `PRIMARY` reverse push (D2).
- `scripts/sync_from_github.sh` header: describe both directions.

## NOT in scope for a first cutover
- Deploy workflows: they stay disabled. Deploys stay manual until a separate runner and scoped deploy keys exist.
- Credential repos (soul/anima/kit-army-config).
- windy-pro (the importer refuses it by name).
- Opening the forge to other members (Grant 09-23: registration closed; Hub 10-01: jit false, 4
  conditions before any change). The D1 bot users are local accounts, not member sign-in.
- Any second repo: only after `windy-git` has run clean for a week, one repo at a time, never while
  an agent is working in it.
