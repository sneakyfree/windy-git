# Windy Git branding (G2.3)

Gitea's **supported** customisation surface: custom templates and public assets.
No Gitea source is modified, so upstream upgrades keep arriving (D-2, I-1).

    deploy/branding/  →  $GITEA_CUSTOM (/data/gitea) in the container
                      →  /srv/windygit/git/gitea/ on Veron 1

Apply with `./deploy/branding/apply.sh`.

## Two traps this cost, both worth knowing

**1. `GITEA__DEFAULT__APP_NAME` does not work.** Gitea reads `APP_NAME` from the
*top level* of `app.ini` (before any `[section]`). The env var instead created a
literal `[default]` section, which Gitea ignores — and the installer's stock
`APP_NAME` kept winning, so the site said "Gitea: Git with a cup of tea" while
the config looked correct. Worse, the env-to-ini pass **appended** a second
`APP_NAME` rather than replacing the first. `apply.sh` sets it at the top level
directly.

**2. Cloudflare caches `/assets/*` for 6 hours and no token in this stack can
purge.** Editing a fixed filename leaves the old bytes live for hours — the new
logo and CSS were both invisible while being correct at origin. **Version the
filename** (`theme-windy.v2.css`) on every brand change; a `?query` is not
enough because some caches ignore it.

The nav logo is swapped in CSS rather than by overriding Gitea's navbar
template — a one-line rule instead of a forked template that would drift.
