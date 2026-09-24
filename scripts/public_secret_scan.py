#!/usr/bin/env python3
"""Weekly: every PUBLIC repo in Grant's GitHub accounts, full history (every object,
reachable or not, incl. PR refs), for secret-shaped strings. Leak hunt 09-24: a
real bot token sat in a public test fixture for five months.

Output is hash + location only, never a value (house rule 10). Known fakes are
excused by ci/secret-guard-allow.yml (same file as secret-guard; the repo NAME is
matched across accounts). Runs on Veron as user1-gpu (gh is logged in there):

  python3 scripts/public_secret_scan.py [--out FILE] [--owners a,b,...]
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import secret_shapes as ss  # noqa: E402

OWNERS = ["sneakyfree", "VERONTECH", "Windstorm-Institute", "Windstorm-Labs", "Public-Streamer"]
WORK = Path.home() / "leakscan" / "public"
MAX_BLOB = 20_000_000


def _run(*a: str) -> subprocess.CompletedProcess:
    return subprocess.run(a, capture_output=True)


def blob_hits(bare: Path) -> dict[str, list[tuple[str, str]]]:
    """{blob: [(kind, hash8)]} over every blob object in the repo."""
    chk = _run("git", "-C", str(bare), "cat-file", "--batch-all-objects",
               "--batch-check=%(objectname) %(objecttype) %(objectsize)")
    blobs = [p[0] for p in (ln.split() for ln in chk.stdout.decode().splitlines())
             if len(p) == 3 and p[1] == "blob" and int(p[2]) < MAX_BLOB]
    if not blobs:
        return {}
    import threading
    p = subprocess.Popen(["git", "-C", str(bare), "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def feed() -> None:  # separate thread: writing everything first deadlocks (both pipes fill)
        p.stdin.write(("\n".join(blobs) + "\n").encode())
        p.stdin.close()
    threading.Thread(target=feed, daemon=True).start()
    out: dict[str, list[tuple[str, str]]] = {}
    for _ in blobs:
        hdr = p.stdout.readline().split()
        data = p.stdout.read(int(hdr[2]))
        p.stdout.read(1)
        found = ss.find(data.decode("utf-8", "ignore"))
        if found:
            out[hdr[0].decode()] = found
    p.wait()
    return out


def locate(bare: Path, blob: str) -> dict:
    lg = _run("git", "-C", str(bare), "log", "--all", "--format=@@%H %cI", "--name-only",
              f"--find-object={blob}").stdout.decode()
    commits, paths = [], set()
    for line in lg.splitlines():
        if line.startswith("@@"):
            commits.append(line[2:].split())
        elif line.strip():
            paths.add(line.strip())
    head = _run("git", "-C", str(bare), "ls-tree", "-r", "HEAD").stdout.decode()
    first = commits[-1] if commits else ["unreachable", "-"]
    return {"paths": sorted(paths), "first_commit": first[0][:10], "first_date": first[1],
            "in_head": blob in head}


def excused(repo: str, kind: str, h: str, paths: list[str], allow: dict) -> bool:
    a = allow.get(repo) or {"hashes": set(), "paths": []}
    if kind in {"private key block"}:
        return bool(paths) and all(any(kind in k and fnmatch.fnmatch(p, g) for g, k in a["paths"]) for p in paths)
    return h in a["hashes"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(WORK / "latest.json"))
    ap.add_argument("--owners", default=",".join(OWNERS))
    args = ap.parse_args()
    import secret_guard as sg
    allow = sg.load_allow()
    WORK.mkdir(parents=True, exist_ok=True)
    rows, scanned, errors = [], [], []
    for owner in args.owners.split(","):
        lst = _run("gh", "repo", "list", owner, "--limit", "1000", "--visibility", "public", "--json", "name")
        for r in json.loads(lst.stdout or b"[]"):
            name = r["name"]
            bare = WORK / owner / f"{name}.git"
            if bare.exists():
                c = _run("git", "-C", str(bare), "remote", "update", "--prune")
            else:
                bare.parent.mkdir(parents=True, exist_ok=True)
                c = _run("gh", "repo", "clone", f"{owner}/{name}", str(bare), "--", "--mirror", "-q")
            if c.returncode:
                errors.append(f"{owner}/{name}")
                continue
            scanned.append(f"{owner}/{name}")
            for blob, found in blob_hits(bare).items():
                loc = locate(bare, blob)
                for kind, h in sorted(set(found)):
                    rows.append({"repo": f"{owner}/{name}", "kind": kind, "hash8": h, **loc,
                                 "excused": excused(name, kind, h, loc["paths"], allow)})
    Path(args.out).write_text(json.dumps({"scanned": scanned, "errors": errors, "rows": rows}, indent=1))
    new = [r for r in rows if not r["excused"]]
    print(f"scanned {len(scanned)} public repos, {len(errors)} errors, {len(rows)} secret-shaped, {len(new)} NOT excused")
    return 0


if __name__ == "__main__":
    sys.exit(main())
