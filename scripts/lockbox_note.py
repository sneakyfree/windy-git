#!/usr/bin/env python3
"""lockbox-note: add ONE plain-words note to the lockbox, by PR, without anyone opening it.

  lockbox-note --lane NAME --title "SHORT TITLE" "THE NOTE, ONE LINE OF PLAIN WORDS"

Appends ONE block at the END of ACCESS_LOCKBOX.md, exactly as lockbox-put appends an entry:

    ## 📝 NOTE <yyyy-mm-dd> (<lane>): <title>
    - **Note:** <text>

No line in the middle of the file is touched, so nobody has to find or open the section the note
is about: the note names it by its heading as lockbox-names prints it. lockbox-names shows the
note's own heading (the title) to every later reader; the text is in the PR and in the file.

WHY: a label on a whole section (for example "an EPT in this section signed by key id X is refused
after <date>") used to be a hand edit in a lockbox checkout. Nobody opens a lockbox body now
(Windy Vault, BOARD 2026-11-12T03:19:24Z).

A NOTE IS NEVER A SECRET AND NEVER A NAME. Refused, with nothing pushed: a title over 60 or a text
over 300 characters; any character outside letters, digits, space and . , : ; ( ) ' / _ + - # ? !
(so no backtick, no equals sign, no asterisk: a note cannot define a name in either form the
lockbox reads); anything secret-shaped (secret_shapes, the shapes secret-guard knows); any run of
24 or more characters that is not a plain UPPER_CASE name; 7 or more digits in a row with spaces,
dashes, dots or brackets between them, dates, times and digits inside a word or name aside (a phone number); a web address ("://"). The text is given on
the command line on purpose: it is public words, and what is typed there is what is checked.

lockbox-names lists each note's "Note" label as one label row of the note's own heading: that row is
the note, not a secret.

Checked before the push: one file, 3 lines added, 0 removed, main's bytes kept, no name defined
by the block. Then the road of every lockbox PR: Boss's shape stamp, the Hub's merge.
Env (tests): LOCKBOX_PUT_REPO=<clone url/path>, LOCKBOX_PUT_NO_PR=1. Work folder as lockbox-put.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import secret_shapes as ss  # noqa: E402

REPO = os.environ.get("LOCKBOX_PUT_REPO", "https://github.com/sneakyfree/kit-army-config.git")
SLUG = "sneakyfree/kit-army-config"
F = "ACCESS_LOCKBOX.md"
WORDS = re.compile(r"^[A-Za-z0-9 .,:;()'/_+#?!-]+$")
RUN = re.compile(r"[A-Za-z0-9_+/-]{24,}")
PLAIN_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
PHONE = re.compile(r"\d(?:[\s.()-]*\d){6,}")
WORDY = re.compile(r"\w*[A-Za-z_]\w*")  # a token with a letter or underscore (a name, an id) is not a phone number
DATE_TIME = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?Z?)?\b|\b\d{1,2}:\d{2}(?::\d{2})?Z?\b")  # dates and times are not phone numbers
DEFINES = re.compile(rb"^\s*[-*]?\s*\*\*`|^(?:export[ \t]+)?[A-Z][A-Z0-9_]{2,63}=", re.M)
WHO = ("-c", "user.name=lockbox-put", "-c", "user.email=lockbox-put@windy.invalid")


def die(msg: str, code: int = 2):
    print(f"lockbox-note: {msg}")
    sys.exit(code)


def git(cwd: str, *a: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True, errors="ignore")


def work_dir() -> str | None:
    for d in (os.environ.get("XDG_RUNTIME_DIR"), "/dev/shm"):
        if d and os.path.isdir(d) and os.access(d, os.W_OK | os.X_OK):
            return d
    cache = Path.home() / ".cache"
    return str(cache) if cache.is_dir() else None


def refuse(what: str, text: str, limit: int) -> str | None:
    """Why this text may not go into the lockbox, or None. Never echoes the text."""
    text = text.strip()
    if not 4 <= len(text) <= limit:
        return f"the {what} must be 4 to {limit} characters"
    if not WORDS.match(text):
        return (f"the {what} holds a character that is not allowed (letters, digits, space and "
                f". , : ; ( ) ' / _ + - # ? ! only; no backtick, equals sign or asterisk)")
    if ss.find(text):
        return f"the {what} holds something secret-shaped: a note is never a secret"
    if PHONE.search(WORDY.sub(" ", DATE_TIME.sub(" ", text))) or "://" in text:
        return f"the {what} holds a phone-number-like run of 7 or more digits or a web address: a note names no person or place"
    if any(not PLAIN_NAME.match(m) for m in RUN.findall(text)):
        return f"the {what} holds a long run that is not a plain UPPER_CASE name: it could be a value"
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lockbox-note",
                                 usage='lockbox-note --lane NAME --title "SHORT TITLE" "THE NOTE"')
    ap.add_argument("text", metavar="TEXT")
    ap.add_argument("--title", required=True)
    ap.add_argument("--lane", required=True)
    a = ap.parse_args(argv)
    title, text = a.title.strip(), a.text.strip()
    lane = re.sub(r"[^A-Za-z0-9 ._-]", "", a.lane).strip()[:40]
    if not lane:
        die("--lane must name the lane that writes the note")
    for what, value, limit in (("title", title, 60), ("text", text, 300)):
        why = refuse(what, value, limit)
        if why:
            die(f"{why}: nothing done")
    now = dt.datetime.now(dt.UTC)
    block = f"\n## 📝 NOTE {now.strftime('%Y-%m-%d')} ({lane}): {title}\n- **Note:** {text}\n".encode()
    if DEFINES.search(block):
        die("the note would define a name: nothing done")
    tmp = tempfile.mkdtemp(prefix="lockbox-note-", dir=work_dir())
    os.chmod(tmp, 0o700)
    clone = os.path.join(tmp, "k")
    try:
        if subprocess.run(["git", "clone", "-q", "--depth", "1", REPO, clone], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode != 0:
            die("clone failed (details withheld: URLs can carry tokens)")
        lb = Path(clone, F)
        if not lb.is_file():
            die("ACCESS_LOCKBOX.md not found in the repo")
        before = lb.read_bytes()
        if not before.endswith(b"\n"):
            die("the lockbox file does not end with a newline: nothing done")
        lb.write_bytes(before + block)
        branch = f"lockbox-note/{now.strftime('%Y%m%d%H%M%S')}"
        git(clone, "checkout", "-q", "-b", branch)
        git(clone, "add", F)
        ns = git(clone, "diff", "--cached", "--numstat").stdout.split()
        after = lb.read_bytes()
        if not (len(ns) == 3 and ns[0] == "3" and ns[1] == "0" and ns[2] == F
                and after.startswith(before) and after[len(before):] == block):
            die("the change is not a pure 3-line append to ACCESS_LOCKBOX.md: aborting, nothing pushed")
        if git(clone, *WHO, "commit", "-q", "-m", f"lockbox: note ({lane}): {title} (via lockbox-note)").returncode != 0:
            die("commit failed")
        if git(clone, "push", "-q", "origin", branch).returncode != 0:
            die("push failed (details withheld)")
        if os.environ.get("LOCKBOX_PUT_NO_PR"):
            print(f"ok: pushed branch {branch}; one note, 3 lines added, one file; PR skipped")
            return 0
        body = (f"Adds exactly one NOTE block at the end of the lockbox file (by {lane}): 3 lines added, 0 removed, "
                f"one file, no name defined, no value (verified before push).\n\nTitle: {title}\n\nNote: {text}\n\n"
                f"🤖 Generated with [Claude Code](https://claude.com/claude-code)")
        pr = subprocess.run(["gh", "pr", "create", "-R", SLUG, "--head", branch, "--base", "main",
                             "--title", f"lockbox: note ({lane}): {title}", "--body", body],
                            capture_output=True, text=True)
        if pr.returncode != 0:
            die("branch pushed but `gh pr create` failed; open the PR for the branch by hand")
        print(f"ok: one note, 3 lines added, one file; PR {pr.stdout.strip().splitlines()[-1]}")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # never a traceback: it could carry data
        print(f"lockbox-note: error: {type(e).__name__}")
        sys.exit(2)
