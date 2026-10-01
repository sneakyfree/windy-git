#!/usr/bin/env python3
"""lockbox-put: add ONE secret to the lockbox by PR, without anyone reading, printing or
grepping the lockbox (Boss rule 10-01; Windy Hub ruling).

  lockbox-put KEY FILE [--lane NAME] [--note TEXT]

KEY  exact name, ^[A-Z][A-Z0-9_]{2,63}$ . FILE a 0600 file you own (not a symlink) whose
content is the value (one line). Appends ONE line `- **`KEY`**: `<value>`` (the format
lockbox-get reads) under a new heading at the END of ACCESS_LOCKBOX.md in a fresh temp clone,
on a new branch, and opens a kit-army-config PR. Append-only: the diff is verified to be one
file, additions only, before pushing. REFUSES if KEY already exists (a bool computed in
memory; no line, value or location is ever printed). Reviewers see the KEY NAME + lane only
if they look at the diff; the PR body never carries the value. Never echoes the value.
Env (tests): LOCKBOX_PUT_REPO=<clone url/path>, LOCKBOX_PUT_NO_PR=1.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = os.environ.get("LOCKBOX_PUT_REPO", "https://github.com/sneakyfree/kit-army-config.git")
SLUG = "sneakyfree/kit-army-config"
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
VAL_RE = re.compile(r"^[A-Za-z0-9._~+/=:@%,-]{8,512}$")  # no backtick, quote, space or newline


def die(msg: str, code: int = 2):
    print(f"lockbox-put: {msg}")
    sys.exit(code)


def git(cwd: str, *a: str, quiet=True) -> subprocess.CompletedProcess:
    # stderr is dropped: git/gh errors can echo URLs; stdout only when we need it.
    return subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True, errors="ignore")


def key_exists(clone: str, key: str) -> bool:
    """True if KEY is already defined anywhere lockbox-get reads. Bool only, nothing printed."""
    pat_env = re.compile(r"^" + re.escape(key) + r"=")
    pat_md = re.compile(r"^\s*[-*]?\s*\*\*`" + re.escape(key) + r"`\*\*\s*:")
    paths = [Path(clone, "ACCESS_LOCKBOX.md")] + [
        Path(dp, f) for dp, _d, fs in os.walk(Path(clone, "secrets")) for f in fs if f.endswith(".env")]
    for p in paths:
        try:
            with open(p, errors="ignore") as fh:
                for line in fh:
                    if pat_env.match(line) or pat_md.match(line):
                        return True
        except OSError:
            continue
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lockbox-put")
    ap.add_argument("key")
    ap.add_argument("file")
    ap.add_argument("--lane", default=os.environ.get("LOCKBOX_LANE", "a lane"))
    ap.add_argument("--note", default="")
    a = ap.parse_args(argv)
    if not KEY_RE.match(a.key):
        die("KEY must match ^[A-Z][A-Z0-9_]{2,63}$")
    try:
        st = os.lstat(a.file)
    except OSError:
        die("FILE not found")
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        die("FILE must be a regular file (not a symlink)")
    if st.st_uid != os.getuid() or (st.st_mode & 0o077):
        die("FILE must be owned by you and mode 0600")
    with open(a.file) as fh:
        value = fh.read().strip()
    if not VAL_RE.match(value):
        die("value must be one line of 8-512 chars from [A-Za-z0-9._~+/=:@%,-] (no spaces, quotes, backticks)")
    note = re.sub(r"[`\n\r]", " ", a.note)[:160]
    lane = re.sub(r"[^A-Za-z0-9 ._-]", "", a.lane)[:40]
    tmp = tempfile.mkdtemp(prefix="lockbox-put-", dir=str(Path.home() / ".cache") if (Path.home() / ".cache").is_dir() else None)
    os.chmod(tmp, 0o700)
    clone = os.path.join(tmp, "k")
    try:
        if subprocess.run(["git", "clone", "-q", "--depth", "1", REPO, clone],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
            die("clone failed (details withheld: URLs can carry tokens)")
        if key_exists(clone, a.key):
            die(f"{a.key} already exists: refusing to overwrite (append-only; pick a new KEY)", 3)
        lb = Path(clone, "ACCESS_LOCKBOX.md")
        if not lb.is_file():
            die("ACCESS_LOCKBOX.md not found in the repo")
        today = dt.date.today().isoformat()
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d%H%M")
        branch = f"lockbox-put/{a.key.lower()}-{stamp}"
        with open(lb, "a") as fh:
            fh.write(f"\n## 🗝️ {a.key} (added {today} by {lane} via lockbox-put)\n")
            fh.write(f"- **`{a.key}`**: `{value}`\n")
            if note:
                fh.write(f"- **Note:** {note}\n")
        git(clone, "checkout", "-q", "-b", branch)
        git(clone, "add", "ACCESS_LOCKBOX.md")
        ns = git(clone, "diff", "--cached", "--numstat").stdout.split()
        # numstat: <added> <deleted> <path>; exactly one file, no deletions
        if len(ns) != 3 or ns[1] != "0" or ns[2] != "ACCESS_LOCKBOX.md":
            die("diff is not a pure append to ACCESS_LOCKBOX.md: aborting, nothing pushed")
        msg = f"lockbox: add {a.key} (via lockbox-put, {lane})\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
        if git(clone, "-c", "user.name=lockbox-put", "-c", "user.email=lockbox-put@windy.invalid",
               "commit", "-q", "-m", msg).returncode != 0:
            die("commit failed")
        if git(clone, "push", "-q", "origin", branch).returncode != 0:
            die("push failed (details withheld)")
        if os.environ.get("LOCKBOX_PUT_NO_PR"):
            print(f"ok: pushed branch {branch} ({a.key}); PR skipped")
            return 0
        body = (f"Adds exactly one key: `{a.key}` (by {lane}). Append-only, one file, no deletions "
                f"(verified before push). Review by KEY NAME only; do not paste the value anywhere.\n\n"
                f"{note}\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)")
        r = subprocess.run(["gh", "pr", "create", "-R", SLUG, "--head", branch, "--base", "main",
                            "--title", f"lockbox: add {a.key} ({lane})", "--body", body],
                           capture_output=True, text=True)
        if r.returncode != 0:
            die("branch pushed but `gh pr create` failed; open the PR for the branch by hand")
        print(f"ok: {a.key} added via PR {r.stdout.strip().splitlines()[-1]}")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # never a traceback: it could carry data
        print(f"lockbox-put: error: {type(e).__name__}")
        sys.exit(2)
