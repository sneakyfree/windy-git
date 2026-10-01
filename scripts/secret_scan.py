#!/usr/bin/env python3
"""secret-scan: hash-only secret finder. Boss ruling 10-01 after three lanes printed secrets
into their own transcripts while hunting secrets (house rule 10).

  secret-scan <path> [--history] [--repo <git url or path>] [--no-lockbox]

Reports `file:line` (and the commit with --history), WHICH lockbox entry matched (the KEY
NAME only) or which secret SHAPE matched (twilio, zai, aws, ...), plus a sha256[:8] of the
token for allow-listing. It NEVER prints, logs or writes a value or any fragment of one
(no context line, no masking). The lockbox is loaded in memory only. stdout only.
Exit 0 = clean, 1 = findings, 2 = usage/error.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import secret_shapes as ss  # noqa: E402  (the SAME shapes as secret-guard)

HOME = Path.home()
LOCKBOX_PATHS = [p for p in os.environ.get("SECRET_SCAN_LOCKBOX_PATHS", "").split(":") if p] or [
    str(HOME / "kit-army-config" / "secrets"), str(HOME / "kit-army-config" / "ACCESS_LOCKBOX.md")]
# Extra shapes that are scan-only (not in the blocking guard): label, regex.
EXTRA = [("zai key", re.compile(r"(?<![0-9a-f])[0-9a-f]{32}\.[A-Za-z0-9]{16}(?![A-Za-z0-9])"))]
SKIP_DIRS = {".git", "node_modules", "vendor", "third_party", "__pycache__", ".venv"}
MAX_BYTES = 5_000_000

RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]{15,199}")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
NAME = re.compile(r"[\s>*`|-]*([A-Za-z][A-Za-z0-9_]{2,60})\s*[=:|]")


def h16(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()[:16]


def cands(line: str):
    """Token candidates: runs >=16 chars with a digit and a letter; git shas/uuids excluded."""
    for chunk in re.split(r"[^A-Za-z0-9_\-.]+", line):
        parts = [chunk, *chunk.split(".")] if "." in chunk else [chunk]
        for p in parts:
            for m in RUN.finditer(p):
                t = m.group(0)
                if not (re.search(r"\d", t) and re.search(r"[A-Za-z]", t)):
                    continue
                if re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", t) or UUID.match(t.lower()):
                    continue
                yield t


def load_lockbox() -> dict[str, set[str]]:
    """{hash16: {key-name labels}}; values never leave this dict."""
    out: dict[str, set[str]] = {}
    files: list[str] = []
    for p in LOCKBOX_PATHS:
        if os.path.isdir(p):
            for root, _d, fs in os.walk(p):
                files += [os.path.join(root, f) for f in fs]
        elif os.path.isfile(p):
            files.append(p)
    for f in files:
        try:
            with open(f, errors="ignore") as fh:
                for line in fh:
                    m = NAME.match(line)
                    label = m.group(1) if m else "?"
                    for t in cands(line):
                        out.setdefault(h16(t), set()).add(label)
        except OSError:
            continue
    return out


def scan_line(line: str, lockbox: dict[str, set[str]]) -> list[tuple[str, str]]:
    """[(label, hash8)]: `shape:<kind>` and/or `lockbox:<NAMES>`. No value escapes."""
    res: list[tuple[str, str]] = []
    for kind, h in ss.find(line):
        res.append((f"shape:{kind}", h))
    for kind, rx in EXTRA:
        for m in rx.finditer(line):
            res.append((f"shape:{kind}", ss.h8(m.group(0))))
    for t in cands(line):
        k = h16(t)
        if k in lockbox:
            names = sorted(n for n in lockbox[k])
            res.append(("lockbox:" + ",".join(names)[:70], k[:8]))
    return sorted(set(res))


def is_text(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            return b"\0" not in fh.read(4096)
    except OSError:
        return False


def scan_tree(root: Path, lockbox):
    files = [root] if root.is_file() else [
        Path(dp) / f for dp, dn, fn in os.walk(root) for f in fn
        if not set(Path(dp).relative_to(root).parts) & SKIP_DIRS]
    for p in sorted(files):
        try:
            if p.stat().st_size > MAX_BYTES or not is_text(p):
                continue
            with open(p, errors="ignore") as fh:
                for n, line in enumerate(fh, 1):
                    for label, h in scan_line(line, lockbox):
                        yield (str(p), n, None, label, h)
        except OSError:
            continue


def git(repo: str, *a: str) -> subprocess.Popen:
    return subprocess.Popen(["git", "--git-dir", repo, *a], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, errors="ignore")


def scan_history(gitdir: str, lockbox):
    """Every ADDED line on every ref (incl. PR refs). Oldest commit per (hash, file, line)."""
    seen: dict[tuple, str] = {}
    p = git(gitdir, "log", "--all", "-p", "-U0", "--no-color", "--format=@@C %h", "-a")
    commit = path = None
    ln = 0
    for row in p.stdout:  # type: ignore[union-attr]
        if row.startswith("@@C "):
            commit = row[4:].strip()
        elif row.startswith("+++ "):
            path = row[6:].strip() if row.startswith("+++ b/") else None
        elif row.startswith("@@ "):
            m = re.search(r"\+(\d+)", row)
            ln = int(m.group(1)) - 1 if m else 0
        elif row.startswith("+") and path:
            ln += 1
            for label, h in scan_line(row[1:], lockbox):
                seen[(label, h, path, ln)] = commit or "?"
    p.wait()
    for (label, h, path, ln), c in sorted(seen.items(), key=lambda x: (x[0][2], x[0][3])):
        yield (path, ln, c, label, h)


def resolve_gitdir(p: Path) -> str | None:
    for cand in (p / ".git", p):
        if (cand / "HEAD").exists() and ((cand / "objects").exists()):
            return str(cand)
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="secret-scan", description=__doc__.split("\n\n")[1] if __doc__ else "")
    ap.add_argument("path", nargs="?", help="file, directory, or git repo (with --history)")
    ap.add_argument("--history", action="store_true", help="scan every added line in all git history")
    ap.add_argument("--repo", help="git URL or path to scan (mirror-cloned to a temp dir, then deleted)")
    ap.add_argument("--no-lockbox", action="store_true", help="shapes only")
    a = ap.parse_args(argv)
    if not (a.path or a.repo):
        ap.print_usage()
        return 2
    lockbox = {} if a.no_lockbox else load_lockbox()
    print(f"# secret-scan: {len(lockbox)} lockbox tokens in memory, values never printed", flush=True)
    tmp = None
    findings = 0
    try:
        if a.repo:
            tmp = tempfile.mkdtemp(prefix="secret-scan-", dir=str(HOME / ".cache") if (HOME / ".cache").is_dir() else None)
            os.chmod(tmp, 0o700)
            target = os.path.join(tmp, "r.git")
            rc = subprocess.run(["git", "clone", "-q", "--mirror", a.repo, target],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
            if rc != 0:
                print("error: clone failed (details withheld: URLs can carry tokens)")
                return 2
            a.history = True
            gitdir = target
        elif a.history:
            gitdir = resolve_gitdir(Path(a.path))
            if not gitdir:
                print("error: --history needs a git repo path")
                return 2
        if a.history:
            for path, ln, c, label, h in scan_history(gitdir, lockbox):
                findings += 1
                print(f"{path}:{ln}  commit={c}  {label} #{h}")
        else:
            for path, ln, _c, label, h in scan_tree(Path(a.path), lockbox):
                findings += 1
                print(f"{path}:{ln}  {label} #{h}")
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"# {findings} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:  # never a traceback: it could carry data
        print(f"error: {type(e).__name__}")
        sys.exit(2)
