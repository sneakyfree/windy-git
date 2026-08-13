#!/usr/bin/env python3
"""Import a GitHub repo into Windy Git (strand G11.3 / G7.4).

**Two modes, and the choice is not cosmetic.**

    --mirror   GitHub ──pull──▶ Windy Git          read-only, NO CI
    (default)  Windy Git ──push-mirror──▶ GitHub   writable, CI RUNS

**A pull mirror cannot run CI.** Measured 2026-08-12: windy-calendar imported as
a mirror sat at **0 workflow runs**. Gitea does not fire Actions on mirror sync,
and a mirror is not a push target — so a mirrored repo gives you the code and
none of the point.

So getting CI onto Veron 1 requires **real, writable repos**, which means Windy
Git is where you push and GitHub becomes the downstream copy via I-4's
push-mirror (`api/app/services/mirror.py`). That is the planned steady state,
not a shortcut — but it *is* a change to where every human and agent pushes, so
it is Grant's call, not this script's default assumption.

`--mirror` remains available for repos you want copied but not moved.

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


def all_repo_names() -> list[str]:
    out = subprocess.run(
        ["gh", "repo", "list", GITHUB_OWNER, "--limit", "300",
         "--json", "name,isArchived"],
        capture_output=True, text=True, check=True,
    )
    return sorted(r["name"] for r in json.loads(out.stdout) if not r["isArchived"])


def import_everything_as_mirrors() -> int:
    """Bulk DR copy: every repo, as a READ-ONLY pull mirror.

    Mirrors are the right shape for the bulk, and the reason is safety rather
    than tidiness. Sampling 40 repos found **18 carrying deploy / release /
    publish workflows that trigger on `push:`** — roughly 63 across the account.
    Importing those as writable repos with Actions enabled would arm sixty-odd
    production deploy triggers on Veron 1, each of which would then have to be
    disarmed by hand.

    A pull mirror cannot run Actions at all, so the bulk import carries **zero**
    deploy risk, and Gitea does the syncing itself with no script and no timer.
    What you get is a complete, current, second copy of the whole account.

    Converting one to a writable CI repo is then a deliberate per-repo act:
    delete, re-import with `mirror=false`, review its workflows, disable the
    deploying ones. That is the moment to make that judgement — not in bulk,
    sixty times, by accident.
    """
    names = all_repo_names()
    existing = 0
    done = 0
    failed = []
    print(f"{len(names)} active repos on GitHub. Importing missing ones as read-only mirrors.\n")
    for n in names:
        status, _ = _api("GET", f"/repos/{OWNER}/{n}")
        if status == 200:
            existing += 1
            continue
        if import_repo(n, mirror=True):
            done += 1
        else:
            failed.append(n)
    print(f"\n  already present: {existing}")
    print(f"  newly mirrored:  {done}")
    if failed:
        print(f"  FAILED ({len(failed)}): {', '.join(failed[:10])}")
    return 1 if failed else 0


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


def import_repo(name: str, mirror: bool = False) -> bool:
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
            "mirror": mirror,
            **({"mirror_interval": "10m"} if mirror else {}),
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
    ap.add_argument(
        "--mirror", action="store_true",
        help="import read-only pull mirrors instead of writable repos. NOTE: mirrors CANNOT run CI.",
    )
    args = ap.parse_args()

    if args.list_candidates:
        list_candidates()
        return 0

    if args.all_as_mirrors:
        return import_everything_as_mirrors()

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

    if args.mirror:
        print("mirror mode: repos will be read-only and will NOT run CI.\n")
    ok = sum(import_repo(r, mirror=args.mirror) for r in targets)
    print(f"\n{ok}/{len(targets)} imported.")
    return 0 if ok == len(targets) else 1


if __name__ == "__main__":
    sys.exit(main())
