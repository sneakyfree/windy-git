# Migration plan — GitHub first, Windy Git second, flip per repo

**Superseded the 2026-08-13 "daily driver" cutover, which was premature.**

## What went wrong, recorded so it is not repeated

Nine repos were migrated writable with **push-mirrors pointed at GitHub**. At
the same time a dozen agent sessions on the Mac mini were pushing to GitHub
continuously — so GitHub, not Windy Git, was where the live work actually was.

A push-mirror force-updates refs. On its 8-hour timer it would have pushed Windy
Git's stale copy **over live work, silently, with no conflict to notice.**

All nine mirrors were removed before the first timer fired, and every GitHub
repo was verified untouched (latest push predated the mirrors). **No work was
lost.** The mistake was direction, and the lesson is: *the source of truth is
wherever people are actually typing, not wherever the plan says it should be.*

## Phase 1 — now. Nothing changes for anyone.

    Mac mini agents ──push──▶ GitHub ──sync every 15 min──▶ Windy Git ──▶ CI on Veron

- **You do not have to tell your agents anything.** No remote changes, no
  coordination, no "everyone stop pushing." They keep working exactly as they
  are.
- `windygit-sync.timer` runs `scripts/sync_from_github.sh` every 15 minutes.
- Windy Git is **force-updated** on purpose: it holds nothing anyone depends on,
  so GitHub always wins and there is **no merge to reconcile**. That is the
  whole point of not flipping until a repo is quiet.
- CI runs on Veron 1 against current code, on the 36 workflows that already say
  `runs-on: [self-hosted, linux, x64]`.

Tracked repos live in `REPOS` in the script (currently 9 of 141).

## Phase 2 — later, one repo at a time, only when that repo is idle

For a single repo, when nobody is mid-work on it:

1. Remove it from `REPOS` in `sync_from_github.sh` — **first**, or the sync will
   fight its authors and win.
2. Point that repo's sessions at Windy Git:
   `git remote set-url origin https://app.windygit.com/windyadmin/<repo>.git`
3. Add a push-mirror back to GitHub with `sync_on_commit: true`, so GitHub stays
   a current second copy.

**Never flip more than one repo at a time, and never while an agent is working
in it.** A dozen parallel sessions is exactly the situation where a big-bang
cutover produces the dirty-branch mess this plan exists to avoid.

## What is NOT on Windy Git

**9 of 141 repos.** The whole GitHub account is 1.58 GB, so the rest is a
capacity non-issue — it simply has not been imported yet. Add repos to the
import list as they become useful to build.

**`windy-pro` is excluded on purpose.** Six checkouts, a build counter forked
three ways, two sessions recording different HEADs hours apart. Resolve which is
current and write it down before importing (G11.5). The import script refuses it
by name.

## ⚠️ Deploy workflows are DISABLED on Windy Git, deliberately

Six workflows fire on `push:` and deploy to production:
`windy-registry`, `Windy-Clone`, `WindyCloud`, `windy-mind`, `eternitas`
(`deploy.yml`) and `windy-agent` (`release.yml`).

Windy Git now has a working runner, so the next synced commit to `main` would
have attempted a **production deploy from Veron 1**. Their secrets
(`DEPLOY_HOST` / `DEPLOY_KEY` / `VPS_SSH_KEY`) are unset here, so they would
have failed — but they would have failed *loudly on every push*, and any step
before the SSH step would still have run.

All six are now `disabled_manually`. Tests, lints and migration checks stay
**active** — those need no secrets at all, which is why Phase 1 delivers real CI
value immediately.

**Before re-enabling any deploy workflow here, decide deliberately whether
production should be deployable from Windy Git at all.** Kit 0 deploys are
currently manual runbooks; that is a feature, not a gap.

## Backups

`windygit-backup.timer`, nightly 04:17, `git bundle --all` + verify + `windgit`
schema dump to R2, 30-day retention. **Restore rehearsed:** a bundle was pulled
from R2, cloned, and its HEAD matched live `origin/main` exactly.
