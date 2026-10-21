#!/usr/bin/env python3
"""github_has_commit.py <repo> <sha>: does GitHub still hold this commit?

Exit 0 = yes (GitHub answered 200 for the commit), 1 = no (404/422), 2 = could not
tell (any other answer, a timeout, no token). The sync deletes a Windy Git branch
that GitHub deleted only on exit 0, so every doubt keeps the branch.
"""
from __future__ import annotations

import os
import re
import sys
import urllib.error
import urllib.request

API = os.environ.get("GITHUB_API_BASE", "https://api.github.com")
OWNER = os.environ.get("GITHUB_OWNER", "sneakyfree")


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not re.fullmatch(r"[0-9a-f]{40}", argv[1]):
        return 2
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return 2
    req = urllib.request.Request(
        f"{API}/repos/{OWNER}/{argv[0]}/commits/{argv[1]}",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            # urllib's default UA is 403'd as a bot by GitHub's edge.
            "User-Agent": "windy-git-sync",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return 0 if r.status == 200 else 2
    except urllib.error.HTTPError as e:
        return 1 if e.code in (404, 422) else 2
    except (urllib.error.URLError, TimeoutError, OSError):
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
