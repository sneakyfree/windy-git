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

BATCH (2026-11-02, Boss: one key = one PR; lockbox-put-pem stores a long key as KEY_PART1..N):
  lockbox-put --batch - [--lane NAME] [--note TEXT]
stdin = up to 40 lines `KEY<TAB>VALUE[<TAB>NOTE]` (at most 64 KiB; never a TTY). Every line obeys the
single-key rules (KEY_RE, VAL_RE); NOTE: spaces allowed, no tab/newline/backtick, at most 200 chars; a
line without a NOTE gets --note. ALL-OR-NOTHING: any bad line, a KEY twice in the batch, or a KEY that
already exists refuses the WHOLE batch before anything is written: exit 3, stderr
"lockbox-put: batch refused: line <i>: <reason>" (never a value; never where a KEY exists). One clone,
ONE commit appending exactly the batch's lines (verified: one file, additions only, the expected count),
one branch, one PR whose body lists KEY names + count only. A clone/commit/push/PR failure after the
checks = exit 4, and a pushed branch whose PR could not be opened is deleted (nothing half-pushed).
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
BATCH_MAX_BYTES = 64 * 1024
BATCH_MAX_LINES = 40
NOTE_MAX = 200


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


def batch_die(msg: str, code: int):
    print(f"lockbox-put: {msg}", file=sys.stderr)
    sys.exit(code)


def read_batch(default_note: str) -> list[tuple[str, str, str]]:
    """[(KEY, VALUE, NOTE)] from a piped stdin, every line checked; refuses the WHOLE batch on any bad line
    (exit 3). Never prints a value."""
    stream = sys.stdin
    try:
        tty = stream is None or stream.isatty()
    except (OSError, ValueError):
        tty = True
    if tty:
        batch_die("batch refused: stdin must be a pipe (never a terminal)", 3)
    raw = getattr(stream, "buffer", stream).read(BATCH_MAX_BYTES + 1)
    if isinstance(raw, str):
        raw = raw.encode("utf-8", errors="replace")
    if len(raw) > BATCH_MAX_BYTES:
        batch_die(f"batch refused: stdin is longer than {BATCH_MAX_BYTES} bytes", 3)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        batch_die("batch refused: stdin is not valid UTF-8", 3)
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()                                  # one trailing newline is fine
    if not lines:
        batch_die("batch refused: stdin was empty", 3)
    if len(lines) > BATCH_MAX_LINES:
        batch_die(f"batch refused: {len(lines)} lines, at most {BATCH_MAX_LINES}", 3)
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for i, line in enumerate(lines, 1):
        f = line.split("\t")
        if len(f) not in (2, 3):
            batch_die(f"batch refused: line {i}: expected KEY<TAB>VALUE[<TAB>NOTE]", 3)
        key, value = f[0], f[1]
        note = f[2] if len(f) == 3 else default_note
        if not KEY_RE.match(key):
            batch_die(f"batch refused: line {i}: KEY must match ^[A-Z][A-Z0-9_]{{2,63}}$", 3)
        if not VAL_RE.match(value):
            batch_die(f"batch refused: line {i}: value must be one line of 8-512 chars from [A-Za-z0-9._~+/=:@%,-]", 3)
        if len(note) > NOTE_MAX or re.search(r"[`\r\n\t]", note):
            batch_die(f"batch refused: line {i}: NOTE must be at most {NOTE_MAX} chars with no tab, newline or backtick", 3)
        if key in seen:
            batch_die(f"batch refused: line {i}: {key} appears twice in the batch", 3)
        seen.add(key)
        out.append((key, value, note))
    return out


def main_batch(argv) -> int:
    ap = argparse.ArgumentParser(prog="lockbox-put", usage="lockbox-put --batch - [--lane NAME] [--note TEXT]")
    ap.add_argument("--batch", metavar="-", required=True)
    ap.add_argument("--lane", default=os.environ.get("LOCKBOX_LANE", "a lane"))
    ap.add_argument("--note", default="")
    a = ap.parse_args(argv)
    if a.batch != "-":
        batch_die("batch refused: --batch takes '-' (stdin) only", 3)
    lane = re.sub(r"[^A-Za-z0-9 ._-]", "", a.lane)[:40]
    rows = read_batch(re.sub(r"[`\n\r\t]", " ", a.note)[:NOTE_MAX])
    tmp = tempfile.mkdtemp(prefix="lockbox-put-", dir=work_dir())
    os.chmod(tmp, 0o700)
    clone = os.path.join(tmp, "k")
    try:
        if subprocess.run(["git", "clone", "-q", "--depth", "1", REPO, clone],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
            batch_die("clone failed (details withheld: URLs can carry tokens); nothing written", 4)
        for i, (key, _v, _n) in enumerate(rows, 1):
            if key_exists(clone, key):
                batch_die(f"batch refused: line {i}: {key} already exists (append-only; pick a new KEY)", 3)
        lb = Path(clone, "ACCESS_LOCKBOX.md")
        if not lb.is_file():
            batch_die("ACCESS_LOCKBOX.md not found in the repo; nothing written", 4)
        today = dt.date.today().isoformat()
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d%H%M")
        first = rows[0][0]
        branch = f"lockbox-put/{first.lower()}-batch{len(rows)}-{stamp}"
        added = 2                                    # the blank line + the heading
        with open(lb, "a") as fh:
            fh.write(f"\n## 🗝️ {first} and {len(rows) - 1} more (added {today} by {lane} via lockbox-put --batch)\n")
            for key, value, note in rows:
                fh.write(f"- **`{key}`**: `{value}`\n")
                added += 1
                if note:
                    fh.write(f"- **Note ({key}):** {note}\n")
                    added += 1
        git(clone, "checkout", "-q", "-b", branch)
        git(clone, "add", "ACCESS_LOCKBOX.md")
        ns = git(clone, "diff", "--cached", "--numstat").stdout.split()
        # numstat: <added> <deleted> <path>; exactly one file, no deletions, exactly the batch's lines
        if len(ns) != 3 or ns[1] != "0" or ns[2] != "ACCESS_LOCKBOX.md" or ns[0] != str(added):
            batch_die("diff is not exactly the batch appended to ACCESS_LOCKBOX.md: aborting, nothing pushed", 4)
        names = ", ".join(k for k, _v, _n in rows)
        msg = f"lockbox: add {len(rows)} keys (via lockbox-put --batch, {lane})\n\n{names}\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
        if git(clone, "-c", "user.name=lockbox-put", "-c", "user.email=lockbox-put@windy.invalid",
               "commit", "-q", "-m", msg).returncode != 0:
            batch_die("commit failed; nothing pushed", 4)
        if git(clone, "push", "-q", "origin", branch).returncode != 0:
            batch_die("push failed (details withheld); nothing pushed", 4)
        if os.environ.get("LOCKBOX_PUT_NO_PR"):
            print(f"ok: pushed branch {branch} ({len(rows)} keys: {names}); PR skipped")
            return 0
        body = (f"Adds exactly {len(rows)} keys in ONE commit (by {lane}): {names}. Append-only, one file, no "
                f"deletions, exactly the batch's lines (verified before push). Review by KEY NAMES only; do not "
                f"paste a value anywhere.\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)")
        r = subprocess.run(["gh", "pr", "create", "-R", SLUG, "--head", branch, "--base", "main",
                            "--title", f"lockbox: add {len(rows)} keys, {first}.. ({lane})", "--body", body],
                           capture_output=True, text=True)
        if r.returncode != 0:
            git(clone, "push", "-q", "origin", "--delete", branch)   # nothing half-pushed
            batch_die("`gh pr create` failed; the pushed branch was deleted again; nothing written", 4)
        print(f"ok: {len(rows)} keys added via PR {r.stdout.strip().splitlines()[-1]}")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--batch" in argv:
        return main_batch(argv)
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
