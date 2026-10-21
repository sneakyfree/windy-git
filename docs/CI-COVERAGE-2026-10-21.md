# CI coverage: which repos depend on GitHub Actions (2026-10-21)

Boss's ask, BOARD 19:02Z and corrected at 19:0xZ: list the repos whose PRs need checks that only
GitHub Actions produces, and propose moving them to Windy Git's own CI on Veron (P6: one CI).
**Nothing here is changed yet;** each move below is a PR (Hub OK) plus a Boss GO.

## Two facts that frame everything

1. **GitHub can't require anything on our private repos.** sneakyfree is a GitHub Free account:
   branch protection and rulesets on private repos answer `403 Upgrade to GitHub Pro or make
   this repository public` (checked: windy-pro, eternitas, windy-mind, windy-search). So no
   check is GitHub-"required" anywhere. "Required" exists only as our rule: merge on POSTED
   green. `merge_audit.py` checks that rule after the fact for windy-vault and windy-contracts.
2. **GitHub-hosted Actions don't run on our private repos** (a billing lock for weeks, not
   today's news). The real CI is Windy Git's `windy-git/*` statuses. windy-agent is the one
   repo whose GitHub Actions still run: it has 2 GitHub-registered **self-hosted** runners on
   Veron (`veron1-windy-agent`, `-2`), so it uses no GitHub minutes.

Method: every workflow file on `main` of the 35 repos Windy Git syncs, read from Windy Git's
own copies (no GitHub quota), classified per pull-request job by `runs-on`. Gitea runs
`.gitea/workflows` if that folder exists, else `.github/workflows`. Our runners carry
`self-hosted, linux, x64, veron-1` (+ `userns` for windy-mind-acp only). Then every active
sneakyfree repo (pushed in the last 14 days) that Windy Git does not sync.

## A. Covered: Windy Git already runs their PR checks (31 repos)

eternitas, windy-chat, windy-pro, Windy-Clone, WindyCloud, windy-drops, windy-mail, windy-text,
windy-search, windy-mind, windy-connect, windy-inbox, windy-registry, windy-translate,
windy-pro-mobile, windy-mind-acp, windy-calendar, windy-cloud-domains, windy-cloud-sites,
windy-cloud-vps, windy-code-web, windy-contracts, windy-git, windy-hand, windy-traveler,
windy-uptime, windy-vault, windy-text-site, windytranslate-site, windytraveler-site; plus
windy-agent (runs on its own self-hosted GitHub runners). Their GitHub-side startup_failures
change nothing.

Known, accepted gaps inside covered repos:
- **windy-pro:** `build-installer.yml` (mac arm64/x64, win, linux installers + e2e), the
  `build-electron` mac/win matrix and `deploy` need macOS/Windows or GitHub-hosted runners. They
  are Grant-owned desktop release builds (made on the Mac mini). They stay OFF CI; PRs don't
  wait on them, and the janitor cancels the unpicked legs.
- **windy-mind-acp:** its `.github` jobs fail on GitHub, but `.gitea/workflows` runs the same
  `test` matrix + `hostname-gate` (the userns VM). Covered.

## B. Partial: synced, but the real build/test never runs anywhere

| Repo | What runs on Windy Git | What never runs | Proposal |
|---|---|---|---|
| **windy-code** (VS Code fork) | api-proposal check, canonical-domains-lint (+1) | compile, unit tests, extension builds: all `ubuntu/macos/windows-latest` or `vscode-large-runners` | A `.gitea/workflows/ci.yml` with **compile + unit tests on `[self-hosted, linux, x64]`** (heavy: VS Code compile wants ~16 GB RAM and 20+ min; 1 job, not the full matrix). Windy Code owns the scope; Windy Git sizes the runner. |

## C. Not on Windy Git CI at all, with PRs

| Repo | Open PRs | Proposal |
|---|---|---|
| **windy-admin** | 6 | **IN PROGRESS** with Admin (Boss 19:0xZ): promote the pull mirror to a CI repo + sync/bridge; Admin adds `.gitea/workflows/ci.yml` (`uv run --extra dev pytest -q` in `service/`, ~11 min, sibling windy-pro checkout via a windy-pro-only read token: Boss GO asked). Status `windy-git/ci/test`. |
| **windyword-site** | 5 | Onboard like the other `*-site` repos: build + canonical-domains-lint on Windy Git. Word picks the checks. |
| **Windy-Clone-site** | 1 | Same, a site batch. |
| **windy-connect-site** | 1 | Same, a site batch. |
| eternitas-site, windy-code-site, windy-mail-site, windy-fly-site, windy-mind-site, windy-search-site, windy-call-site, windy-drops-site, windycloud-site | 0 | Same site batch, so their next PR has a posted verdict. Cheap: 1 lint/build job each. |
| windy-session | 0 | Code's; pull mirror today. Onboard when Code next opens PRs. |
| windy-word-mcp, windy-node | 0 | Public repos: GitHub-hosted Actions run free on public repos, so nothing to move. |

## D. Deliberately NOT on Windy Git CI

- **kit-army-config:** it holds the lockbox and must never be cloned into a CI workspace. Its
  PRs are reviewed and merged by Boss; that stays.
- Grant's personal and business repos (grantwhitmer-site, thewindstorm-*, wagyutank*,
  ancient-firelight, black-box-declassified, impossible-documentary, facemortgage, anima,
  the kit-* souls): not Windy lanes.
- Test/probe repos (ssrfprobe527, probe-502-test, wg586-probe, windygit-mirror-test-553).

## "Required" without GitHub branch protection

Since GitHub can't enforce it, the proposal is: **extend `merge_audit.py` to every Windy Git CI
repo**, each with its own list of required contexts (e.g. windy-admin: `windy-git/ci/test`). The
nightly sweep then flags any merge to `main` whose PR head lacked a posted green (Boss sees it on
the BOARD next morning). That is the "required status" Boss asked for. It needs Boss's GO per
repo list.

## Order (each its own PR, Hub OK, Boss GO)

1. windy-admin (in progress; needs the windy-pro read token GO).
2. merge_audit per-repo required contexts, starting with windy-admin.
3. The site batch (windyword-site first: 5 open PRs).
4. windy-code compile + unit tests (with Windy Code; biggest runner cost).

Capacity: 6 general runners (12 cores / 64 GB for the CI engine). The site batch costs little;
windy-code compile is the one to schedule (see the load cap rule: load > 48 stops runners 3-6).
