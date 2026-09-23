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

## The whole account is on Windy Git — in two tiers

    143 repos · 1.58 GB · 967 GB free      (matches the GitHub archive exactly)

| tier | count | writable | runs CI | deploy risk |
|---|---|---|---|---|
| **read-only mirrors** | 131 | no | **no** | **none** |
| **writable + CI** | 12 | yes | yes | deploys disabled |

**Why the bulk is mirrors, and why that is the safety decision:** sampling 40
repos found **18 carrying deploy / release / publish workflows that trigger on
`push:`** — roughly 63 across the account. Importing those writable with Actions
enabled would have armed sixty-odd production deploy triggers on Veron 1, each
needing disarming by hand. **A pull mirror cannot run Actions at all**, so the
bulk import carries zero execution risk and Gitea syncs it with no script and no
timer.

That splits the two things cleanly: **having a copy** (safe, do it for
everything, now) and **running code** (needs judgement, do it per repo,
deliberately).

Seven repos are empty here because they are empty on GitHub — 0 KB upstream,
verified. Not failed imports.

`windy-pro` **is** present, as a mirror. That is safe: the G11.5 caution is
about making it *writable* while six checkouts and a three-way-forked build
counter disagree on HEAD. A read-only copy of whatever GitHub currently has
carries none of that risk — and it means the DR copy is complete.

## Promoting a mirror to writable + CI

Per repo, deliberately, when that repo is quiet:

1. delete the mirror, re-import with `mirror=false`
2. **review its workflows and disable every deploying one** (see the section
   above — this is the step that matters)
3. add it to `REPOS` in `sync_from_github.sh` so it tracks GitHub
4. later, when it flips to Windy-Git-first: remove it from `REPOS` *first*,
   repoint its sessions, add a push-mirror back to GitHub

## Private repos: Windy Git IS their CI (permanent, 2026-09-23)

The platform repos stay **private** on GitHub (Grant, 2026-09-23), and private
repos cannot run GitHub Actions on this account at all. Windy Git is therefore
their CI permanently, not a stopgap:

    GitHub push ──sync (15 min)──▶ Windy Git ──runner──▶ Veron 1
         ▲                                                   │
         └──── commit status  windy-git/<workflow>/<job> ◀───┘   scripts/pr_status_bridge.py

- `pr_status_bridge.py` runs at the end of every sync. It opens a `[GH#N]`
  mirror PR in Windy Git for every open **same-repo** GitHub PR (so
  `pull_request` workflows fire), closes it when the GitHub PR closes, and posts
  each job's result back to GitHub on PR heads and the default-branch head.
  **Never merge a `[GH#N]` PR here** — merge on GitHub.
- Fork PRs are never run: their branch is never synced, and untrusted code
  beside the privileged dind is the open audit finding.
- Covered repos: `BRIDGE_REPOS` in the script. Public repos are left out on
  purpose; they run real GitHub Actions and two verdicts per commit is noise.
- `skipped` jobs post nothing — no green for a job nobody ran.

**Onboarding another private repo** — the promotion steps below, then:

    # on Veron 1, as root
    set -a; . /srv/windygit/src/.env; set +a
    python3 scripts/import_from_github.py <repo>          # writable; aborts if the repo exists
    # disable EVERY deploying workflow before anything is pushed:
    curl -X PUT -H "Authorization: token $GITEA_ADMIN_TOKEN" \
      http://localhost:3080/api/v1/repos/windyadmin/<repo>/actions/workflows/deploy.yml/disable
    # add <repo> to REPOS in sync_from_github.sh AND BRIDGE_REPOS in pr_status_bridge.py

An import fires no push event, so `main` has no verdict until its next commit.
To get one now: force Windy Git's `main` back one commit, then
`systemctl start windygit-sync` — the sync pushes it forward and CI fires.

⚠️ **`/actions/tasks` lists only jobs a runner has PICKED UP.** Queued runs are
invisible there, so a repo can read "0 runs" while work is waiting. The truth is
`action_run` in the `gitea` database (status 1 success, 2 failure, 5 waiting,
6 running).

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
