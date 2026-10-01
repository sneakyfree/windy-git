# Checklist: making Windy Git the PRIMARY home of one repo (after launch)

Status 2026-10-01: DRAFT, nothing flipped. GitHub stays the source of truth until Grant says otherwise.
First candidate: `windy-git` itself (public, low blast radius). GitHub becomes the free off-site push-mirror.

## Preconditions (all must be true)
- [x] Encrypted state backup (Postgres + Gitea config + repos) nightly, restore drill passed cross-host (10-01).
- [x] Gitea on a patched release (1.24.7); upgrade path = snapshot first (docs/RESTORE-DRILL.md).
- [ ] Heartbeat `windygit-state-backup` in heartbeats-veron expected list (asked Cloud/Super Admin 10-01).
- [ ] A missed/failed backup PAGES (heartbeat 26h), tested once by skipping a night in a drill.
- [ ] Boss/Grant capacity call on Veron (dedicated non-SMR volume for DB + git storage; root disk < 80%).
- [ ] Post-launch freeze lifted (Hub). No cutover during store review or a launch window.

## Cutover for ONE repo (reversible at every step)
1. Announce on BOARD; tell every consuming lane (no schema drift rule). Pause the sync for that repo only:
   remove it from `REPOS` in `scripts/sync_from_github.sh` FIRST (the sync force-overwrites Windy Git).
2. Verify Windy Git main == GitHub main (sha equal), all branches/tags present, LFS (if any) in R2.
3. Add a PUSH-mirror on the Windy Git repo -> GitHub (deploy key or scoped token, write on that repo only,
   interval 8h + on-commit), so GitHub keeps a current copy. Test with a throwaway branch.
4. Flip the lanes' remote: `origin` = Windy Git (SSH/HTTPS via Windy SSO token), `github` = secondary.
   Lanes push to Windy Git only; the mirror carries it to GitHub.
5. CI keeps running here (no change); remove the `pr_status_bridge` mirror-PR duplication for that repo
   (PRs are now native here; the bridge's GitHub status posting for it can stay for any open GitHub PRs).
6. Watch 3 days: mirror lag, backup includes the new writes, no push rejected, no lane still pushing to GitHub.
7. Rollback at any time: re-add the repo to `REPOS` (sync resumes GitHub->Windy Git, GitHub is intact via the
   push-mirror) and point lanes' remote back. Nothing is destroyed in either direction.

## NOT in scope for a first cutover
Deploy workflows (stay disabled; deploys remain manual until a separate runner + scoped deploy keys exist),
credential repos (soul/anima/kit-army-config), windy-pro (importer refuses by name), opening the forge to
other members (Grant 09-23: registration closed; Hub 10-01: jit false, 4 conditions before any change).
