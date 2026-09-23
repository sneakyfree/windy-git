#!/usr/bin/env python3
"""Give private GitHub repos a CI signal from Windy Git (P1, 2026-09-23).

GitHub Actions cannot run on private repos on this account — not even on
self-hosted runners ([[reference-github-actions-billing-lock]]). The code is
already synced into Windy Git every 15 min and CI runs there, so the only thing
missing is the *signal on GitHub*, where people and agents actually read PRs.

Two jobs, run after every sync:

1. **Mirror open PRs.** The sync carries branches, not PRs, and the workflows
   trigger on `pull_request` — so a PR branch alone fires nothing. For each open
   same-repo GitHub PR we keep one open Windy Git PR with the same head/base.
   Gitea then fires `pull_request` on open and `synchronize` whenever the sync
   moves the branch. Windy Git PRs whose GitHub PR closed are closed here too.
   Fork PRs are ignored: their head branch is never synced, and untrusted fork
   code on this runner is exactly the blast radius the audit warned about.

2. **Post results back** as GitHub commit statuses (context
   `windy-git/<workflow>/<job>`) on each PR head and on the default-branch head.
   Only posts when a context's state changed, so a 15-min loop doesn't pile
   hundreds of identical statuses onto one commit.

Runs ON Veron 1 (localhost Gitea; no Cloudflare hairpin). Needs
GITEA_ADMIN_TOKEN and a GITHUB_TOKEN with `repo` scope. Nothing here executes
repo code, and no secret is handed to any repo.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

GITEA = os.environ.get("BRIDGE_GITEA_URL", "http://localhost:3080").rstrip("/")
PUBLIC = "https://app.windygit.com"
GITEA_TOKEN = os.environ.get("GITEA_ADMIN_TOKEN", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GH_OWNER = os.environ.get("GITHUB_OWNER", "sneakyfree")
WG_OWNER = os.environ.get("WINDYGIT_OWNER", "windyadmin")
# Private repos only. Public repos run real GitHub Actions on veron1's GitHub
# runner; bridging those too would put two competing verdicts on every commit.
REPOS = os.environ.get(
    "BRIDGE_REPOS",
    "windy-chat windy-mail windy-calendar Windy-Clone WindyCloud windy-search windy-connect",
).split()

# Gitea run status -> GitHub status state. `skipped` is deliberately absent: a
# job skipped by its own `if:` (e.g. substrate-drift's no-secrets path) has no
# verdict, and painting it green would be a claim nobody tested.
STATE = {
    "success": "success",
    "failure": "failure",
    "cancelled": "error",
    "running": "pending",
    "waiting": "pending",
    "blocked": "pending",
}
MIRROR_TAG = "[GH#"


def _call(base: str, token_header: str, method: str, path: str, body=None):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Authorization": token_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
            # urllib's default UA is 403'd as a bot by GitHub's edge and CF.
            "User-Agent": "windy-git-pr-bridge/1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, None


def gitea(method, path, body=None):
    return _call(GITEA + "/api/v1", f"token {GITEA_TOKEN}", method, path, body)


def github(method, path, body=None):
    return _call("https://api.github.com", f"Bearer {GITHUB_TOKEN}", method, path, body)


def sync_prs(repo: str) -> list[str]:
    """Mirror open same-repo GitHub PRs into Windy Git. Returns their head shas."""
    st, gh_prs = github("GET", f"/repos/{GH_OWNER}/{repo}/pulls?state=open&per_page=100")
    if st != 200:
        raise RuntimeError(f"{repo}: GitHub PR list -> {st}")
    st, wg_prs = gitea("GET", f"/repos/{WG_OWNER}/{repo}/pulls?state=open&limit=50")
    if st != 200:
        raise RuntimeError(f"{repo}: Windy Git PR list -> {st}")
    ours = {p["title"].split("]")[0] + "]": p for p in wg_prs if p["title"].startswith(MIRROR_TAG)}

    heads, wanted = [], set()
    for pr in gh_prs:
        if pr["head"]["repo"] is None or pr["head"]["repo"]["full_name"] != f"{GH_OWNER}/{repo}":
            continue  # fork PR — never synced, never run here
        tag = f"{MIRROR_TAG}{pr['number']}]"
        wanted.add(tag)
        heads.append(pr["head"]["sha"])
        if tag in ours:
            continue
        st, _ = gitea(
            "POST",
            f"/repos/{WG_OWNER}/{repo}/pulls",
            {
                "head": pr["head"]["ref"],
                "base": pr["base"]["ref"],
                "title": f"{tag} {pr['title']}"[:250],
                "body": f"Mirror of {pr['html_url']} so CI runs here. Do not merge in Windy Git — "
                "GitHub is the source of truth; merge there.",
            },
        )
        print(f"  {repo}: opened mirror PR for GH#{pr['number']} -> {st}")

    for tag, p in ours.items():
        if tag not in wanted:
            gitea("PATCH", f"/repos/{WG_OWNER}/{repo}/pulls/{p['number']}", {"state": "closed"})
            print(f"  {repo}: closed mirror PR {tag} (closed on GitHub)")
    return heads


def post_statuses(repo: str, sha: str) -> None:
    # Gitea caps a page at 50 (MAX_RESPONSE_ITEMS) whatever `limit` says, and a
    # daily scheduled workflow can push a quiet main's runs off page 1.
    runs = []
    for page in range(1, 6):
        st, body = gitea("GET", f"/repos/{WG_OWNER}/{repo}/actions/tasks?limit=50&page={page}")
        if st != 200:
            raise RuntimeError(f"{repo}: Windy Git runs -> {st}")
        runs += body.get("workflow_runs", [])
        if len(body.get("workflow_runs", [])) < 50:
            break
    latest: dict[str, dict] = {}
    for r in runs:
        if r["head_sha"] != sha:
            continue
        ctx = f"windy-git/{r['workflow_id'].removesuffix('.yml')}/{r['name']}"
        if ctx not in latest or r["id"] > latest[ctx]["id"]:
            latest[ctx] = r
    if not latest:
        return

    st, existing = github("GET", f"/repos/{GH_OWNER}/{repo}/commits/{sha}/statuses?per_page=100")
    current: dict[str, str] = {}
    for s in existing or []:  # newest first
        current.setdefault(s["context"], s["state"])

    for ctx, r in sorted(latest.items()):
        state = STATE.get(r["status"])
        if state is None or current.get(ctx) == state:
            continue
        st, _ = github(
            "POST",
            f"/repos/{GH_OWNER}/{repo}/statuses/{sha}",
            {
                "state": state,
                "context": ctx,
                "description": f"Windy Git CI on Veron 1: {r['status']}"[:140],
                "target_url": f"{PUBLIC}/{WG_OWNER}/{repo}/actions/runs/{r['run_number']}",
            },
        )
        print(f"  {repo}@{sha[:7]} {ctx} = {state} -> {st}")


def main() -> int:
    if not (GITEA_TOKEN and GITHUB_TOKEN):
        sys.exit("GITEA_ADMIN_TOKEN and GITHUB_TOKEN are required")
    failed = 0
    for repo in REPOS:
        try:
            shas = sync_prs(repo)
            st, br = github("GET", f"/repos/{GH_OWNER}/{repo}")
            if st == 200:
                st, b = github("GET", f"/repos/{GH_OWNER}/{repo}/branches/{br['default_branch']}")
                if st == 200:
                    shas.append(b["commit"]["sha"])
            for sha in dict.fromkeys(shas):
                post_statuses(repo, sha)
        except Exception as e:  # one repo's failure must not hide the others'
            print(f"  FAILED {repo}: {e}")
            failed = 1
    return failed


if __name__ == "__main__":
    sys.exit(main())
