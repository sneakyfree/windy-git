#!/usr/bin/env python3
"""Nightly contract-drift sweep (Mind plan v2.1 S0.4).

Finds every `contracts.lock` in every repo on Windy Git (default branch), compares
each locked contract with windy-contracts' MANIFEST.json (main), and prints one TSV
line per lock entry that is not current. A consumer is "behind" when its locked
sha256 differs from MANIFEST's. Read-only: nothing is written to any repo.

Runs ON Veron 1 (sudo docker exec into the Gitea container, like rerun_ci.sh):

    python3 scripts/contracts_drift.py                # TSV on stdout, summary line last
    python3 scripts/contracts_drift.py --json         # same data as JSON

TSV columns: repo, lock_path, contract_path, status, locked_version, manifest_version
status: BEHIND | LOCAL_EDIT (vendored file's bytes != its own lock) | UNKNOWN (path not in
MANIFEST) | MISSING_VENDORED. Last line: `# contracts drift sweep: N consumer(s), M behind`.
The Windy 0 wrapper (~/bin/nightly-contracts-drift.sh) turns new rows into BOARD lines.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys

CONTRACTS_REPO = "windy-contracts"
CONTAINER = os.environ.get("GITEA_CONTAINER", "windy-git-gitea-1")
REPO_DIR = "/data/git/repositories/windyadmin"
LOCK_NAME = "contracts.lock"


class GiteaGit:
    """Reads blobs from the bare repos inside the Gitea container."""

    def _run(self, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
        return subprocess.run(["sudo", "-n", "docker", "exec", "-u", "git", CONTAINER, *args],
                              capture_output=True, text=True, timeout=timeout)

    def repos(self) -> list[str]:
        r = self._run("ls", REPO_DIR)
        return sorted(n[:-4] for n in r.stdout.split() if n.endswith(".git"))

    def find_locks(self, repo: str) -> list[str]:
        r = self._run("git", "-C", f"{REPO_DIR}/{repo}.git", "ls-tree", "-r", "--name-only", "HEAD")
        return [p for p in r.stdout.splitlines() if p.split("/")[-1] == LOCK_NAME]

    def blob(self, repo: str, path: str) -> bytes | None:
        r = subprocess.run(["sudo", "-n", "docker", "exec", "-u", "git", CONTAINER, "git", "-C",
                            f"{REPO_DIR}/{repo}.git", "show", f"HEAD:{path}"], capture_output=True, timeout=60)
        return r.stdout if r.returncode == 0 else None


def sweep(src, manifest: dict) -> tuple[list[dict], int]:
    """-> (rows that are not current, number of consumer repos with a lock)."""
    current = {c["path"]: c for c in manifest.get("contracts", [])}
    rows: list[dict] = []
    consumers = 0
    for repo in src.repos():
        if repo == CONTRACTS_REPO:
            continue
        for lp in src.find_locks(repo):
            raw = src.blob(repo, lp)
            try:
                lock = json.loads(raw) if raw else None
            except ValueError:
                lock = None
            if not lock:
                rows.append({"repo": repo, "lock": lp, "path": "-", "status": "UNREADABLE_LOCK", "locked": "-", "manifest": "-"})
                continue
            consumers += 1
            base = lp.rsplit("/", 1)[0] + "/" if "/" in lp else ""
            for e in lock.get("contracts", []):
                m = current.get(e["path"])
                row = {"repo": repo, "lock": lp, "path": e["path"], "locked": e.get("version", "?"),
                       "manifest": m["version"] if m else "-"}
                vend = src.blob(repo, base + e["vendored_at"])
                if m is None:
                    rows.append({**row, "status": "UNKNOWN"})
                elif m["sha256"] != e.get("sha256"):
                    rows.append({**row, "status": "BEHIND"})
                elif vend is None:
                    rows.append({**row, "status": "MISSING_VENDORED"})
                elif hashlib.sha256(vend).hexdigest() != e["sha256"]:
                    rows.append({**row, "status": "LOCAL_EDIT"})
    return rows, consumers


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    g = GiteaGit()
    raw = g.blob(CONTRACTS_REPO, "MANIFEST.json")
    if raw is None:
        print("# contracts drift sweep: ERROR (no MANIFEST.json on windy-contracts main in Windy Git)")
        return 1
    rows, consumers = sweep(g, json.loads(raw))
    if a.json:
        print(json.dumps({"consumers": consumers, "rows": rows}, indent=2))
    for r in rows:
        print("\t".join([r["repo"], r["lock"], r["path"], r["status"], r["locked"], r["manifest"]]))
    behind = len({r["repo"] for r in rows})
    print(f"# contracts drift sweep: {consumers} consumer(s), {behind} behind")
    return 0


if __name__ == "__main__":
    sys.exit(main())
