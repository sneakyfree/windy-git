#!/usr/bin/env python3
"""Import a GitHub repo into Windy Git (strand G11.3 / G7.4).

**Direction matters and is deliberate.** During the migration quarter, GitHub
stays upstream and Windy Git is the downstream copy:

    GitHub  ──pull──▶  Windy Git  ──▶  CI

Not the other way round. G11.6 keeps GitHub as the durable copy for a full
quarter after cutover, and until Grant flips that, anything that makes Windy Git
authoritative creates a two-writer problem nobody asked for. A pull mirror can
never diverge: if it breaks, the worst case is stale, not wrong.

That inversion is temporary. I-4's push-mirror (`api/app/services/mirror.py`) is
the steady state, for repos that originate here.

Usage:
    ./import_from_github.py windy-calendar [windy-mind ...]
    ./import_from_github.py --list-candidates
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

# ⚠️ Default to the HOST-LOCAL address, not the public one.
#
# Cloudflare answers the public endpoint with 403 error 1010 for this client —
# it blocks urllib's user-agent as a bot signature. The failure looks like Gitea
# rejecting the token and is not: the same call against localhost:3080 on the
# host succeeds immediately.
#
# Bulk import belongs on the host anyway: no hairpin through the edge, no
# Cloudflare ~100s proxy ceiling (G4A.5) on a large clone. Run this on Veron 1.
GITEA = os.environ.get("GITEA_BASE_URL", "http://localhost:3080")
GITEA_TOKEN = os.environ.get("GITEA_ADMIN_TOKEN", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_OWNER = os.environ.get("GITHUB_OWNER", "sneakyfree")
OWNER = os.environ.get("WINDYGIT_OWNER", "windyadmin")

# G11.4 — least risk first. windy-pro is deliberately last and deliberately not
# in this list: six checkouts exist, the build counter has forked three ways, and
# there is direct evidence conflict on which HEAD is current. Resolve that by
# reading, not by importing (G11.5).
SAFE_ORDER = [
    # scaffolds and sites — nothing depends on them
    "windy-calendar",
    "windy-search",
    "windy-registry",
    "Windy-Clone",
    # live services with real test suites
    "WindyCloud",
    "windy-cloud-sites",
    "windy-mind",
    "eternitas",
    "windy-agent",
]


def _api(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    if not GITEA_TOKEN:
        sys.exit("GITEA_ADMIN_TOKEN is unset. Refusing to guess.")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{GITEA}/api/v1{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"token {GITEA_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"message": raw[:300]}


def list_candidates() -> None:
    """Private repos whose CI cannot run on GitHub at all."""
    out = subprocess.run(
        ["gh", "repo", "list", GITHUB_OWNER, "--limit", "200",
         "--json", "name,isPrivate,isArchived,pushedAt"],
        capture_output=True, text=True, check=True,
    )
    repos = [r for r in json.loads(out.stdout) if r["isPrivate"] and not r["isArchived"]]
    print(f"{len(repos)} private repos — GitHub Actions cannot run on any of them.\n")
    for name in SAFE_ORDER:
        match = next((r for r in repos if r["name"] == name), None)
        print(f"  {name:24} {'last push ' + match['pushedAt'][:10] if match else 'NOT FOUND'}")
    print("\nwindy-pro is excluded on purpose — see G11.5.")


def import_repo(name: str) -> bool:
    existing_status, _ = _api("GET", f"/repos/{OWNER}/{name}")
    if existing_status == 200:
        print(f"  {name:24} already present — skipping (idempotent)")
        return True

    if not GITHUB_TOKEN:
        sys.exit("GITHUB_TOKEN is unset; private repos cannot be read without it.")

    status, body = _api(
        "POST",
        "/repos/migrate",
        {
            "clone_addr": f"https://github.com/{GITHUB_OWNER}/{name}.git",
            "auth_token": GITHUB_TOKEN,
            "repo_name": name,
            "repo_owner": OWNER,
            "service": "github",
            "private": True,
            # Pull mirror: GitHub stays upstream for the migration quarter.
            # A pull mirror cannot diverge — worst case it is stale, not wrong.
            "mirror": True,
            "mirror_interval": "10m",
            # Issues/PRs/releases deliberately NOT imported. They are GitHub's
            # copy of a conversation, and duplicating conversations across two
            # systems is how you end up with two half-answers to every question.
            "issues": False,
            "pull_requests": False,
            "releases": False,
            "wiki": False,
            "labels": False,
            "milestones": False,
        },
    )
    if status in (200, 201):
        print(f"  {name:24} imported  ({body.get('size', 0)} KB)")
        return True
    print(f"  {name:24} FAILED {status}: {str(body.get('message'))[:120]}")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repos", nargs="*")
    ap.add_argument("--list-candidates", action="store_true")
    ap.add_argument("--safe-batch", action="store_true", help="import SAFE_ORDER in order")
    args = ap.parse_args()

    if args.list_candidates:
        list_candidates()
        return 0

    targets = SAFE_ORDER if args.safe_batch else args.repos
    if not targets:
        ap.error("name a repo, or pass --safe-batch / --list-candidates")

    if "windy-pro" in targets:
        sys.exit(
            "REFUSING windy-pro. Six checkouts exist, the build counter has forked "
            "three ways (main 12 / overnight 34 / wave-44 56), and two sessions "
            "recorded different HEADs hours apart. Resolve which is current and "
            "write it down BEFORE importing (G11.5)."
        )

    ok = sum(import_repo(r) for r in targets)
    print(f"\n{ok}/{len(targets)} imported.")
    return 0 if ok == len(targets) else 1


if __name__ == "__main__":
    sys.exit(main())
