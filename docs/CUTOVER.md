# Windy Git is the daily driver — 2026-08-13

Grant's call, 2026-08-12: **push to Windy Git; GitHub is the second copy.**

    you ──push──▶ Windy Git (Veron 1) ──▶ CI on 24 cores
                       │
                       └──push-mirror on every commit──▶ GitHub

## 🔴 The one rule this creates

**Do not push directly to GitHub for a migrated repo.**

A push mirror makes GitHub match Windy Git. Anything committed straight to
GitHub is **overwritten on the next sync**, silently, with no conflict and no
warning. That is the cost of having one writer, and one writer is the point —
two writers with no reconciliation is how you lose work you thought was saved.

If you must hotfix on GitHub: push there, then immediately pull that commit into
Windy Git *before* anything triggers a mirror sync. Better: don't.

## Migrated (9)

`windy-calendar` · `windy-search` · `windy-registry` · `Windy-Clone` ·
`WindyCloud` · `windy-cloud-sites` · `windy-mind` · `eternitas` · `windy-agent`

All writable (`mirror=false`), all push-mirroring to GitHub with
`sync_on_commit: true`. Clone from `https://app.windygit.com/windyadmin/<repo>.git`.

**Not migrated on purpose:** `windy-pro`. Six checkouts exist, the build counter
has forked three ways (main 12 / overnight 34 / wave-44 56), and two sessions
recorded different HEADs hours apart. Resolve which is current and write it
down first (G11.5). The import script refuses it by name.

## CI

The runner advertises `veron-1`, `linux-x64`, `self-hosted`, `linux`, `x64`.
**36 of 36 active workflows in the fleet already say
`runs-on: [self-hosted, linux, x64]`** — they were written for the self-hosted
runners that died when the repos went private, so they run **as-is, unedited**.

Proven: `windy-calendar`'s existing `.github/workflows/ci.yml` ran on Veron 1
and reported success with no changes.

**Per-repo secrets are not imported.** A repo whose CI needs a database URL or
an API key will fail until those are set in its Gitea repo settings. Set them as
each repo needs them, not speculatively.

## Backups

Nightly `windygit-backup.timer` at 04:17 (`Persistent=true`, so a window missed
while the workstation is off is caught up rather than skipped). Every repo is
bundled `--all`, verified, and uploaded to R2 with the `windgit` schema.

**Restore is rehearsed, not assumed:** a bundle was pulled back from R2, cloned,
and its HEAD matched live `origin/main` exactly.

## Verify the loop yourself

```bash
git clone https://app.windygit.com/windyadmin/windy-calendar.git
cd windy-calendar && git commit --allow-empty -m "probe" && git push
# CI runs on Veron 1; GitHub receives the commit within ~20s
```
