#!/usr/bin/env python3
"""lockbox-relabel: mark ONE lockbox name superseded, by PR, without anyone reading a value.

  lockbox-relabel OLD_NAME [--lane NAME]

OLD_NAME becomes OLD_NAME__SUPERSEDED_<the UTC day, yyyymmdd> in that entry's own definition line
(`- **`OLD_NAME`**: ...`) and, if the heading right above it carries the name, in that heading.
Nothing else changes: the value stays, every other byte of the file stays. It is the ONLY thing this
tool can do: it cannot rename to anything else, delete an entry or change a value.

WHY: lockbox-put is append-only and a retired entry must not look alive. Until 2026-11-06 a
superseded mark was a rename made by hand in a lockbox checkout; nobody opens a lockbox body now
(Windy Vault, BOARD 2026-11-12T03:04:50Z), so the rename is this tool's byte arithmetic.

Refuses, with nothing pushed: a name that is not defined exactly once in ACCESS_LOCKBOX.md as a
`**`NAME`**:` line; a name defined as NAME= anywhere lockbox-get reads (the lockbox file or
secrets/**/*.env: those are not this tool's to relabel); a name that already carries a
__SUPERSEDED_ label; a new name that exists already or is longer than 64 characters.
Checked BEFORE the push, each printed as yes or NO: the line count is the same; 1 or 2 lines
changed; each changed line is the old line with the suffix added to the name and nothing else; the
value bytes are identical (sha256 in memory); every other line is identical; the new name is
defined once and the old name no more; the diff is one file. Prints the two names, counts and the
PR link only: no line, value or location.

Then the road of every lockbox PR: Boss's stamp by name, scope and diff shape, the Hub's merge.
Run by the lane that owns the name, on Boss's word, after the entry that replaces it is MERGED.
Env (tests): LOCKBOX_PUT_REPO=<clone url/path>, LOCKBOX_PUT_NO_PR=1. Work folder: RAM first, as
lockbox-put does; it holds the whole lockbox while it exists (0700) and is removed on every exit.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = os.environ.get("LOCKBOX_PUT_REPO", "https://github.com/sneakyfree/kit-army-config.git")
SLUG = "sneakyfree/kit-army-config"
F = "ACCESS_LOCKBOX.md"
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
WHO = ("-c", "user.name=lockbox-put", "-c", "user.email=lockbox-put@windy.invalid")


def die(msg: str, code: int = 2):
    print(f"lockbox-relabel: {msg}")
    sys.exit(code)


def git(cwd: str, *a: str) -> subprocess.CompletedProcess:
    # git's own output is captured and never printed: errors can echo URLs or lines.
    return subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True, errors="ignore")


def work_dir() -> str | None:
    for d in (os.environ.get("XDG_RUNTIME_DIR"), "/dev/shm"):
        if d and os.path.isdir(d) and os.access(d, os.W_OK | os.X_OK):
            return d
    cache = Path.home() / ".cache"
    return str(cache) if cache.is_dir() else None


def md_def(name: str) -> re.Pattern[bytes]:
    """The definition line of NAME: everything up to and including the colon is group 1."""
    return re.compile(rb"^(\s*[-*]?\s*\*\*`" + re.escape(name).encode() + rb"`\*\*\s*:)")


def env_def(name: str) -> re.Pattern[bytes]:
    return re.compile(rb"^(?:export[ \t]+)?" + re.escape(name).encode() + rb"=")


def token(name: str) -> re.Pattern[bytes]:
    """NAME as a whole name: not inside a longer one (NAME_V2 is a different name)."""
    return re.compile(rb"(?<![A-Za-z0-9_])" + re.escape(name).encode() + rb"(?![A-Za-z0-9_])")


def in_secrets_env(clone: str, name: str) -> bool | None:
    """True if NAME= is in a secrets/**/*.env file on main; None if that could not be checked."""
    g = git(clone, "grep", "-q", "-E", "-e", r"^(export[ \t]+)?" + re.escape(name) + "=", "HEAD", "--",
            ":(glob)secrets/**/*.env")
    return True if g.returncode == 0 else False if g.returncode == 1 else None


def relabel(old_text: bytes, old: str, new: str):
    """(new_text, changed line indexes) or a refusal string. Pure bytes; nothing is printed."""
    lines = old_text.splitlines(keepends=True)
    d_old, d_new = md_def(old), md_def(new)
    hits = [i for i, ln in enumerate(lines) if d_old.match(ln)]
    if len(hits) != 1:
        return "the name is not defined exactly once in the lockbox file"
    if any(env_def(old).match(ln) for ln in lines):
        return "the name is also defined as NAME= in the lockbox file: not this tool's to relabel"
    if any(d_new.match(ln) or env_def(new).match(ln) for ln in lines):
        return "the new name exists already"
    i = hits[0]
    m = d_old.match(lines[i])
    out = list(lines)
    out[i] = token(old).sub(new.encode(), m.group(1), count=1) + lines[i][m.end():]
    changed = [i]
    h = next((k for k in range(i - 1, -1, -1) if lines[k].strip()), None)  # the nearest line above that is not blank
    if h is not None and lines[h].startswith(b"#") and token(old).search(lines[h]):
        out[h] = token(old).sub(new.encode(), lines[h])
        changed.append(h)
    return b"".join(out), sorted(changed)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lockbox-relabel", usage="lockbox-relabel OLD_NAME [--lane NAME]")
    ap.add_argument("name", metavar="OLD_NAME")
    ap.add_argument("--lane", default=os.environ.get("LOCKBOX_LANE", "a lane"))
    a = ap.parse_args(argv)
    old = a.name
    if not KEY_RE.match(old):
        die("OLD_NAME must match ^[A-Z][A-Z0-9_]{2,63}$")
    if "__SUPERSEDED" in old:
        die("the name already carries a superseded label")
    now = dt.datetime.now(dt.UTC)
    new = f"{old}__SUPERSEDED_{now.strftime('%Y%m%d')}"
    if not KEY_RE.match(new):
        die("the labelled name would be longer than 64 characters: nothing done")
    lane = re.sub(r"[^A-Za-z0-9 ._-]", "", a.lane)[:40]
    tmp = tempfile.mkdtemp(prefix="lockbox-relabel-", dir=work_dir())
    os.chmod(tmp, 0o700)
    clone = os.path.join(tmp, "k")
    try:
        if subprocess.run(["git", "clone", "-q", "--depth", "1", REPO, clone], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode != 0:
            die("clone failed (details withheld: URLs can carry tokens)")
        lb = Path(clone, F)
        if not lb.is_file():
            die("ACCESS_LOCKBOX.md not found in the repo")
        for n, words in ((old, "the name is defined in a secrets .env file: not this tool's to relabel"),
                         (new, "the new name exists already (in a secrets .env file)")):
            found = in_secrets_env(clone, n)
            if found is None:
                die("the secrets files could not be checked: nothing done")
            if found:
                die(f"{words}: nothing done", 3)
        before = lb.read_bytes()
        r = relabel(before, old, new)
        if isinstance(r, str):
            die(f"{r}: nothing done", 3)
        after, changed = r
        lb.write_bytes(after)
        branch = f"lockbox-relabel/{old.lower()}-{now.strftime('%Y%m%d%H%M')}"
        git(clone, "checkout", "-q", "-b", branch)
        git(clone, "add", F)
        ns = git(clone, "diff", "--cached", "--numstat").stdout.split()
        b_lines, a_lines = before.splitlines(keepends=True), after.splitlines(keepends=True)
        suffix = new[len(old):].encode()
        d_old, d_new = md_def(old), md_def(new)
        i = next((k for k in changed if d_new.match(a_lines[k])), None) if len(a_lines) == len(b_lines) else None
        value_same = (i is not None and hashlib.sha256(a_lines[i][d_new.match(a_lines[i]).end():]).digest()
                      == hashlib.sha256(b_lines[i][d_old.match(b_lines[i]).end():]).digest())
        checks = {
            "same_line_count": len(a_lines) == len(b_lines),
            "one_or_two_lines_changed": len(changed) in (1, 2) and len(a_lines) == len(b_lines)
            and [k for k in range(len(b_lines)) if a_lines[k] != b_lines[k]] == changed,
            "each_changed_line_differs_by_the_label_only": len(a_lines) == len(b_lines) and all(
                token(new).sub(old.encode(), a_lines[k]) == b_lines[k]
                and len(a_lines[k]) - len(b_lines[k]) == len(suffix) * len(token(new).findall(a_lines[k]))
                for k in changed),
            "value_bytes_identical": value_same,
            "new_name_defined_once": sum(1 for ln in a_lines if d_new.match(ln)) == 1,
            "old_name_defined_no_more": not any(d_old.match(ln) or env_def(old).match(ln) for ln in a_lines),
            "one_file_same_lines_in_and_out": len(ns) == 3 and ns[0] == ns[1] == str(len(changed)) and ns[2] == F,
        }
        for k, v in checks.items():
            print(f"  {k}: {'yes' if v else 'NO'}")
        if not all(checks.values()):
            die("a check failed: NOTHING PUSHED")
        msg = f"lockbox: mark {old} superseded (renamed {new}; value kept, name only; via lockbox-relabel, {lane})"
        if git(clone, *WHO, "commit", "-q", "-m", msg).returncode != 0:
            die("commit failed")
        if git(clone, "push", "-q", "origin", branch).returncode != 0:
            die("push failed (details withheld)")
        shape = f"{old} -> {new}; {len(changed)} line(s) changed, one file"
        if os.environ.get("LOCKBOX_PUT_NO_PR"):
            print(f"ok: pushed branch {branch}; {shape}; PR skipped")
            return 0
        body = (f"Marks exactly one name superseded: `{old}` becomes `{new}` (by {lane}). Name only: the value is "
                f"kept and every other byte of the file is identical (verified before push). {len(changed)} line(s) "
                f"changed, one file. Review by NAME, scope and diff shape only; do not paste the value anywhere.\n\n"
                f"🤖 Generated with [Claude Code](https://claude.com/claude-code)")
        pr = subprocess.run(["gh", "pr", "create", "-R", SLUG, "--head", branch, "--base", "main",
                             "--title", f"lockbox: mark {old} superseded ({lane})", "--body", body],
                            capture_output=True, text=True)
        if pr.returncode != 0:
            die("branch pushed but `gh pr create` failed; open the PR for the branch by hand")
        print(f"ok: {shape}; PR {pr.stdout.strip().splitlines()[-1]}")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # never a traceback: it could carry data
        print(f"lockbox-relabel: error: {type(e).__name__}")
        sys.exit(2)
