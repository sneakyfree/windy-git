#!/usr/bin/env python3
"""lockbox-put: add ONE secret to the lockbox by PR, without anyone reading, printing or
grepping the lockbox (Boss rule 10-01; Windy Hub ruling).

  lockbox-put KEY FILE [--lane NAME] [--note TEXT]
  lockbox-put KEY -    [--lane NAME] [--note TEXT]     (value on stdin; same as --stdin)

KEY  exact name, ^[A-Z][A-Z0-9_]{2,63}$ . FILE a 0600 file you own (not a symlink) whose
content is the value (one line). FILE "-" (or --stdin) reads the value from stdin instead,
so no temp file ever exists (Boss rule 10-22: secrets via stdin only, no temp file):

  openssl rand -hex 32 | lockbox-put NEW_KEY -              # value never touches argv/disk
  ssh host 'lockbox-put NEW_KEY -' < /run/user/$UID/dir/f   # pipe from tmpfs over ssh

Stdin rules: a TTY is REFUSED (typing would echo the secret on screen and into scrollback
and transcripts: pipe it in); at most 4096 bytes are read and longer input is refused;
empty input is refused; surrounding whitespace/newline is stripped exactly as for FILE; the
same value rules apply. Do NOT put the value in argv (`echo $VAL`, `printf %s $VAL` from a
non-builtin, `env VAL=...`): argv is visible in ps to every user on the box. A bash
builtin printf is not in ps, but prefer piping from a generator or a 0600 tmpfs file.
Over ssh, pipe on the LOCAL side (`ssh host 'lockbox-put KEY -' < file`): typing into ssh
WITHOUT -t echoes locally and cannot be detected remotely.
Appends ONE line `- **`KEY`**: `<value>`` (the format
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
STDIN_MAX = 4096  # bytes; longer stdin is refused unprocessed


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


def work_dir() -> str | None:
    """Where the temporary lockbox clone lives. It holds EVERY lockbox value while it exists, so
    prefer RAM (Boss 10-23: secrets never on a persistent disk): $XDG_RUNTIME_DIR, then /dev/shm.
    Only where neither exists (macOS) does it fall back to ~/.cache, as before."""
    for d in (os.environ.get("XDG_RUNTIME_DIR"), "/dev/shm"):
        if d and os.path.isdir(d) and os.access(d, os.W_OK | os.X_OK):
            return d
    cache = Path.home() / ".cache"
    return str(cache) if cache.is_dir() else None


def read_stdin_value() -> str:
    """Value from a piped stdin. Refuses a TTY, empty input and > STDIN_MAX bytes.
    Never prints the value or any part of it."""
    stream = sys.stdin
    if stream is None:
        die("no stdin to read from: pipe the value in")
    try:
        tty = stream.isatty()
    except (OSError, ValueError):
        die("stdin is not readable: pipe the value in")
    if tty:
        die("refusing to read the value from a terminal (it would echo on screen and into "
            "scrollback/transcripts): pipe it in, e.g. `openssl rand -hex 32 | lockbox-put KEY -`")
    raw = getattr(stream, "buffer", stream).read(STDIN_MAX + 1)
    if isinstance(raw, str):
        raw = raw.encode("utf-8", errors="replace")
    if len(raw) > STDIN_MAX:
        die(f"stdin is longer than {STDIN_MAX} bytes: refusing (nothing read further, details withheld)")
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError:
        die("stdin is not valid UTF-8 (details withheld)")
    value = value.strip()
    if not value:
        die("stdin was empty: pipe the value in")
    return value


def read_file_value(path: str) -> str:
    try:
        st = os.lstat(path)
    except OSError:
        die("FILE not found")
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        die("FILE must be a regular file (not a symlink)")
    if st.st_uid != os.getuid() or (st.st_mode & 0o077):
        die("FILE must be owned by you and mode 0600")
    with open(path) as fh:
        return fh.read().strip()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="lockbox-put",
        usage="lockbox-put KEY (FILE | - | --stdin) [--lane NAME] [--note TEXT]",
        epilog="FILE '-' or --stdin: read the value from a pipe (never a TTY); no temp file.")
    ap.add_argument("key", metavar="KEY")
    ap.add_argument("file", metavar="FILE", nargs="?",
                    help="0600 regular file you own holding the value, or '-' for stdin")
    ap.add_argument("--stdin", action="store_true", help="same as FILE '-'")
    ap.add_argument("--lane", default=os.environ.get("LOCKBOX_LANE", "a lane"))
    ap.add_argument("--note", default="")
    a = ap.parse_args(argv)
    if not KEY_RE.match(a.key):
        die("KEY must match ^[A-Z][A-Z0-9_]{2,63}$")
    if a.stdin and a.file not in (None, "-"):
        die("give FILE or --stdin, not both")
    if not a.stdin and a.file is None:
        die("FILE is required (or '-' / --stdin to read a piped value)")
    value = read_stdin_value() if (a.stdin or a.file == "-") else read_file_value(a.file)
    if not VAL_RE.match(value):
        die("value must be one line of 8-512 chars from [A-Za-z0-9._~+/=:@%,-] (no spaces, quotes, backticks)")
    note = re.sub(r"[`\n\r]", " ", a.note)[:160]
    lane = re.sub(r"[^A-Za-z0-9 ._-]", "", a.lane)[:40]
    tmp = tempfile.mkdtemp(prefix="lockbox-put-", dir=work_dir())
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
