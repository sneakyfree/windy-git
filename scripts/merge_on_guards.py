#!/usr/bin/env python3
"""merge_on_guards.py REPO PR HEAD [--squash|--merge]: the ONE shared merge for a TODO/docs-only PR (Boss ALL LANES
2026-11-13T01:44:24Z (1); the helper Boss asked for 2026-11-12T17:56:52Z (b)).

It merges ONLY when, at HEAD (the head the caller read):
  * the PR is OPEN and its head is still HEAD (never a moved head);
  * EVERY changed file is on the strict docs list (TODO.md in any folder, README* in any folder, docs/**), the same
    list docs_only.py uses: a code PR needs the Hub stamp + green CI instead, so it is REFUSED here;
  * windy-git/secret-guard, windy-git/compute-guard and windy-git/ci-hygiene are each PRESENT and their newest
    status is success, BY NAME. An ABSENT or pending guard means WAIT (exit 3), never a pass;
  * the repo is not kit-army-config (it keeps Boss's shape stamp; guards never post there).
Then: gh pr merge --match-head-commit HEAD. Exit 0 merged (prints the merge commit), 3 wait, 1 refused, 2 usage.
One read per call, no loop: a caller that waits re-runs it at most every 5 minutes (Boss 16:12:32Z).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

OWNER = "sneakyfree"
GUARDS = ("windy-git/secret-guard", "windy-git/compute-guard", "windy-git/ci-hygiene")
NEVER = {"kit-army-config": "kit-army-config merges on Boss's shape stamp alone; guards never post there"}
DOCS = re.compile(r"(^|/)TODO\.md$|(^|/)README[^/]*$|^docs/")
SAFE_REPO = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
SAFE_SHA = re.compile(r"^[0-9a-f]{40}$")


def gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True, timeout=60).stdout


def decide(repo: str, pr: dict, statuses: list[dict], head: str) -> tuple[int, str]:
    """(exit code, why) from the PR (state, headRefOid, files) and the head's statuses (newest first per GitHub)."""
    if repo in NEVER:
        return 1, f"REFUSED: {NEVER[repo]}"
    if pr.get("state") != "OPEN":
        return 1, f"REFUSED: PR is {pr.get('state')}"
    if pr.get("headRefOid") != head:
        return 1, f"REFUSED: head moved to {str(pr.get('headRefOid'))[:8]} (asked {head[:8]})"
    files = [f.get("path", "") for f in pr.get("files") or []]
    code = [f for f in files if not DOCS.search(f)]
    if not files or code:
        return 1, f"REFUSED: not TODO/docs-only ({len(code)} other file(s), e.g. {code[0] if code else 'none listed'}): the Hub stamp + CI rule applies"
    newest: dict[str, str] = {}
    for s in sorted(statuses, key=lambda s: s.get("updated_at") or "", reverse=True):
        newest.setdefault(s.get("context", ""), s.get("state", ""))
    states = {g: newest.get(g, "absent") for g in GUARDS}
    bad = {g: v for g, v in states.items() if v in ("failure", "error")}
    if bad:
        return 1, "REFUSED: " + ", ".join(f"{g} {v}" for g, v in bad.items())
    wait = {g: v for g, v in states.items() if v != "success"}
    if wait:
        return 3, "WAIT: " + ", ".join(f"{g} {v}" for g, v in wait.items())
    return 0, "three guards success by name at " + head[:8]


def main(argv: list[str], run=gh) -> int:
    if len(argv) not in (3, 4) or not SAFE_REPO.match(argv[0]) or not argv[1].isdigit() or not SAFE_SHA.match(argv[2]):
        print("usage: merge_on_guards.py REPO PR HEAD(40 hex) [--squash|--merge]")
        return 2
    repo, n, head = argv[0], argv[1], argv[2]
    how = argv[3] if len(argv) == 4 else "--squash"
    if how not in ("--squash", "--merge"):
        print("usage: the merge kind is --squash or --merge")
        return 2
    try:
        pr = json.loads(run(["pr", "view", n, "-R", f"{OWNER}/{repo}", "--json", "state,headRefOid,files"]))
        statuses = json.loads(run(["api", f"repos/{OWNER}/{repo}/commits/{head}/statuses?per_page=100"]))
    except (subprocess.SubprocessError, OSError, ValueError) as e:
        print(f"WAIT: GitHub read failed ({type(e).__name__}); nothing merged")
        return 3
    code, why = decide(repo, pr, statuses if isinstance(statuses, list) else [], head)
    print(f"{repo} #{n}: {why}")
    if code:
        return code
    try:
        run(["pr", "merge", n, "-R", f"{OWNER}/{repo}", how, "--match-head-commit", head])
        m = json.loads(run(["pr", "view", n, "-R", f"{OWNER}/{repo}", "--json", "state,mergeCommit"]))
    except (subprocess.SubprocessError, OSError, ValueError) as e:
        print(f"REFUSED: the merge call failed ({type(e).__name__}); read the PR before trying again")
        return 1
    if m.get("state") != "MERGED":
        print(f"REFUSED: after the merge call the PR reads {m.get('state')}")
        return 1
    print(f"MERGED {repo} #{n} at {head[:8]} -> {((m.get('mergeCommit') or {}).get('oid') or '')[:8]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
