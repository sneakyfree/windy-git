# Upgrading Gitea (the forge under Windy Git)

Windy Git runs **stock Gitea** from the official image (not a fork). Our own pieces on top: the branding
templates/CSS (`deploy/branding/`), the API service, and the CI scripts in `scripts/` that read Gitea's
database and API.

## 2026-11-07: 1.24.7 -> 28.3.0

Why: 1.24.7 was a year old; Gitea had published 175 security advisories since (12 critical, 56 high),
among them an unauthenticated file read on public repos and fork-PR Actions bugs.

### Rehearsal (a migrated copy, no production change)
A `pg_dump` of the `gitea` database and a copy of the data root, restored on an isolated docker network
with no egress. In the copy's config: local storage instead of R2, mail, cron and mirrors off, and the outgoing host list set to a TEST-NET address.

| Check | Result |
|---|---|
| Schema migrations 321 -> 357 | clean, ~12 s |
| Row counts before/after (repo, user, pr, run, job, token) | identical |
| Columns our SQL uses: removed or retyped | **none** (only additions) |
| Job status codes 1-7 | unchanged; new 8 = cancelling, 9 = pending |
| Runner pick order (`updated`, `id` ascending) | unchanged: `priority_queue.py` still works |
| Home, header, theme CSS, repo/PR/actions pages, explore | 200 |
| `link_account.tmpl` override | needs `data-global-init="initTabSwitcher"` (added) |
| API calls our code makes (statuses, contents, pulls, commits, tasks, search, admin user/repo, collaborators) | same codes as live |
| Old `/actions/runs/{index}` links (the bridge posts these) | redirect to the new run-ID URL |
| git push with a token (how the sync writes) | ok |
| act_runner 0.6.1 and gitea/runner 5.4.1: a job each, with a secret | both succeed |

### Config changes (in `docker-compose.yml`)
- `DEFAULT_ACTIONS_URL`: `https://github.com` is refused in 28.x; set to `github` (same meaning).
- `PUBLIC_URL_DETECTION = never`: 1.26 changed the default to `auto` (links built from the request Host
  header). We have one public domain, so links always come from ROOT_URL.
- Image pinned by digest.

### Cutover (in a runner pause window, Boss GO by sha)
1. Pause `windygit-sync`, `windygit-priority-queue`, `windygit-autorerun` timers. 0 jobs running.
2. Fresh `pg_dump` of `gitea` + `windygit`, and a copy of the data root (the rollback point).
3. `git pull --ff-only` in the deploy clone, `deploy/branding/apply.sh`, `docker compose up -d gitea`.
4. Verify: `/api/v1/version` = 28.3.0, `/api/healthz`, home + repo pages, SSO redirect,
   `git ls-remote`, one bridged status, one CI run on a runner.
5. Resume the timers.

Rollback: stop gitea, restore the dump into `gitea` and the data-root copy, set the image back to 1.24.7, and
start it. Migrations are one-way, so the image alone is not a rollback.

### Not in this change
- Runner image swap (act_runner 0.6.1 -> gitea/runner 5.x): the old runners work with 28.3.0; swapping
  them closes the runner sandbox-escape advisory and gets its own rehearsal (config keys).
- Using the new rerun API instead of `scripts/rerun_ci.sh`'s rewind.
- `RUN_RETENTION_DAYS` for old runs.

## Staying current (so this never takes a year again)
Mechanical, not memory-based (each is a TODO item with a date):
1. **Daily upstream watcher** (systemd timer): new Gitea/runner releases and security advisories that cover
   our running version -> one BOARD line; a critical/high advisory -> the red-tile alarm.
2. **Staleness alarm**: red when we are more than 30 days behind the latest patch release, or carry any
   critical/high advisory unpatched for more than 72 h.
3. **Scripted rehearsal** (`rehearse.sh`): the checks above, run automatically on every new release
   against a fresh copy; the report goes into an auto-opened PR that bumps the pinned image.
4. **Cutover**: patch releases (same minor) cut over automatically in a pause window after a green
   rehearsal, with automatic rollback if the post-checks fail; minor/major releases (new DB
   migrations, one-way) wait for a Boss GO on that PR's sha.
