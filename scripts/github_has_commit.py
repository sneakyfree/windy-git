#!/usr/bin/env python3
"""github_has_commit.py <repo> <sha>: will GitHub KEEP this commit?

Exit 0 = yes: GitHub returned the commit AND at least one pull request is associated
with it (a PR's refs keep its commits for good). 1 = no: the repo answered and the
commit is absent, or present but in no PR (an unreachable commit GitHub may
garbage-collect, so Windy Git's copy could be the last one; Hub, 10-21). 2 = could not tell (any error, a timeout, no token, the repo not
readable). The sync deletes a Windy Git branch that GitHub deleted only on exit 0,
so every doubt keeps the branch.

It asks GraphQL, not REST: GitHub meters the two separately, and the REST budget
(5,000/h) is what the PR bridge and every lane spend, often down to ~1,000 left by
the hour's end (10-21). One object lookup costs one GraphQL point from a budget
the fleet barely uses.

A commit that is merely PRESENT is not enough: an unreachable commit (its branch
deleted, no PR) still answers until GitHub garbage-collects it. A commit reachable
only from a branch, with no PR, also answers 1: keeping a branch that was safe to
delete costs nothing; deleting the last copy costs everything.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

# Not GITHUB_GRAPHQL_URL: CI runners set that one, sometimes to "" (10-21 gate run 46066).
API = os.environ.get("WINDYGIT_GITHUB_GRAPHQL_URL") or "https://api.github.com/graphql"
OWNER = os.environ.get("GITHUB_OWNER", "sneakyfree")
_NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
QUERY = (
    "query($o:String!,$n:String!,$s:GitObjectID!){repository(owner:$o,name:$n)"
    "{object(oid:$s){oid ... on Commit{associatedPullRequests(first:1){totalCount}}}}}"
)


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not _NAME.match(argv[0]) or not re.fullmatch(r"[0-9a-f]{40}", argv[1]):
        return 2
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return 2
    body = json.dumps({"query": QUERY, "variables": {"o": OWNER, "n": argv[0], "s": argv[1]}}).encode()
    try:
        req = urllib.request.Request(
            API,
            data=body,
            headers={
                "Authorization": f"bearer {token}",
                "Content-Type": "application/json",
                # urllib's default UA is 403'd as a bot by GitHub's edge.
                "User-Agent": "windy-git-sync",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status != 200:
                return 2
            d = json.loads(r.read() or b"null") or {}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return 2
    if d.get("errors"):
        return 2
    repo = (d.get("data") or {}).get("repository")
    if repo is None:
        return 2  # repo not readable: can't tell
    obj = repo.get("object")
    if not obj or obj.get("oid") != argv[1]:
        return 1
    prs = (obj.get("associatedPullRequests") or {}).get("totalCount")
    if not isinstance(prs, int):
        return 2
    return 0 if prs > 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
