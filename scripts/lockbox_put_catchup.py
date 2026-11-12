#!/usr/bin/env python3
"""lockbox-put-catchup: bring ONE lockbox-put branch up to main, without anyone reading a value.

  lockbox-put-catchup BRANCH KEY        (BRANCH = lockbox-put/<key>-<stamp>, as lockbox-put printed it)

WHY: lockbox-put appends its block at the END of ACCESS_LOCKBOX.md. Two puts made from the same
main both append at the same spot, so the second one to merge CONFLICTS (kit-army-config #694 after
#693, 2026-11-12). The conflict sits on value lines, and no person or lane reads a lockbox body, so
it cannot be resolved by hand. This tool does it by byte arithmetic, never a text merge:

    appended = branch_file[len(base_file):]      (refused unless branch_file starts with base_file)
    new_file = main_file + appended              (what lockbox-put would have written on today's main)

then ONE merge commit on the branch (parents: the old head, main; tree: main's tree with that one
file), checked BEFORE a plain push (never a force push: a branch that moved meanwhile is refused by
git). Checks, each printed as yes or NO, and any NO pushes nothing: against main the diff is one
file, the SAME number of added lines as before, 0 deleted; main's bytes are kept; the appended
bytes are identical (sha256 compared in memory); KEY is defined exactly once; no conflict marker;
both parents present. Prints booleans, counts and commit ids only: no line, value or location.

Refuses, with the branch unmoved: a branch that is not KEY's put branch, that changes any other
file, or that is not a pure append; an appended block that is not one lockbox-put block, defines
KEY not exactly once, or defines any second name; a main that already defines KEY (in the lockbox
file or as KEY= in secrets/**/*.env, the places lockbox-get reads). Main MAY have been edited in
the middle since the branch's base: main's bytes + the appended bytes is exact whatever main did.

RULE (Windy Vault, BOARD 2026-11-12T00:39:28Z): one PR per name stays; when a run makes two puts,
the second PR is caught up with this tool after the first merges and BEFORE it is stamped.

Written by Windy Word (proposal of 2026-11-12, sha256/16 551d39340dd440c8), read whole and taken
into the tool by Windy Vault with four changes (BOARD 2026-11-12T00:42:05Z): no traceback ever;
the secrets .env check; exactly one name per block; no refusal for a main edited in the middle.
Env (tests): LOCKBOX_PUT_REPO=<clone url/path>. Work folder: RAM first, as lockbox-put does; it
holds the whole lockbox while it exists (mode 0700) and is removed on every exit.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = os.environ.get("LOCKBOX_PUT_REPO", "https://github.com/sneakyfree/kit-army-config.git")
F = "ACCESS_LOCKBOX.md"
NAME = rb"[A-Z][A-Z0-9_]{2,63}"
#: every form in which the lockbox file defines a name (what lockbox-put's key_exists looks for)
ANY_MD = re.compile(rb"^\s*[-*]?\s*\*\*`" + NAME + rb"`\*\*\s*:", re.M)
ANY_ENV = re.compile(rb"^(?:export[ \t]+)?" + NAME + rb"=", re.M)
WHO = ("-c", "user.name=lockbox-put", "-c", "user.email=lockbox-put@windy.invalid")


def die(msg, code=2):
    print(f"lockbox-put-catchup: {msg}")
    sys.exit(code)


def run(cwd, *a, binary=False):
    # git's own output is captured and never printed: errors can echo URLs or lines.
    return subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=not binary,
                          **({} if binary else {"errors": "ignore"}))


def blob(cwd, rev):
    r = run(cwd, "show", f"{rev}:{F}", binary=True)
    if r.returncode != 0:
        die("a version of the lockbox file could not be read (details withheld)")
    return r.stdout


def work_dir():
    for d in (os.environ.get("XDG_RUNTIME_DIR"), "/dev/shm"):
        if d and os.path.isdir(d) and os.access(d, os.W_OK | os.X_OK):
            return d
    c = Path.home() / ".cache"
    return str(c) if c.is_dir() else None


def main(argv=None):
    a = (argv or sys.argv)[1:]
    if (len(a) != 2 or not re.match(r"^lockbox-put/[a-z0-9_]+-[0-9]{12}$", a[0])
            or not re.match(r"^[A-Z][A-Z0-9_]{2,63}$", a[1])):
        die("usage: lockbox-put-catchup lockbox-put/<key>-<stamp> KEY")
    branch, key = a
    if not re.match(r"^lockbox-put/" + re.escape(key.lower()) + r"-[0-9]{12}$", branch):
        die("the branch is not this key's put branch")
    kb = re.escape(key).encode()
    key_md = re.compile(rb"^\s*[-*]?\s*\*\*`" + kb + rb"`\*\*\s*:", re.M)
    key_env = re.compile(rb"^(?:export[ \t]+)?" + kb + rb"=", re.M)
    tmp = tempfile.mkdtemp(prefix="lockbox-catchup-", dir=work_dir())
    os.chmod(tmp, 0o700)
    c = os.path.join(tmp, "k")
    try:
        if subprocess.run(["git", "clone", "-q", REPO, c], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode != 0:
            die("clone failed (details withheld)")
        if run(c, "checkout", "-q", "-b", "w", f"origin/{branch}").returncode != 0:
            die("no such branch on origin")
        old = run(c, "rev-parse", "HEAD").stdout.strip()
        main_ = run(c, "rev-parse", "origin/main").stdout.strip()
        base = run(c, "merge-base", old, main_).stdout.strip()
        if not old or not main_ or not base:
            die("no common commit with main")
        if base == main_:
            print(f"nothing to do: {branch} already holds main {main_[:8]}")
            return 0
        if base == old:
            print(f"nothing to do: {branch} is already in main {main_[:8]}")
            return 0
        if run(c, "diff", "--name-only", base, old).stdout.split() != [F]:
            die("the branch changes more than the lockbox file: not a put branch")
        b0, b1, m = blob(c, base), blob(c, old), blob(c, main_)
        if not b1.startswith(b0):
            die("the branch is not a pure append to its base: nothing done")
        app = b1[len(b0):]
        if not app.startswith(b"\n## ") or not app.endswith(b"\n"):
            die("the appended part is not one lockbox-put block: nothing done")
        if len(key_md.findall(app)) != 1:
            die("the appended part does not define KEY exactly once: nothing done")
        if len(ANY_MD.findall(app)) != 1 or ANY_ENV.search(app):
            die("the appended part defines more than one name: nothing done")
        if key_md.search(m) or key_env.search(m):
            die("main already defines KEY: nothing done", 3)
        # the other place lockbox-get reads: KEY= lines in secrets/**/*.env (lockbox-put's key_exists does the same)
        g = run(c, "grep", "-q", "-E", "-e", r"^(export[ \t]+)?" + re.escape(key) + "=", main_, "--",
                ":(glob)secrets/**/*.env")
        if g.returncode == 0:
            die("main already defines KEY in a secrets .env file: nothing done", 3)
        if g.returncode != 1:
            die("main's secrets files could not be checked: nothing done")
        if not m.endswith(b"\n"):
            die("main's lockbox file does not end with a newline: nothing done")
        new = m + app
        before = run(c, "diff", "--numstat", base, old).stdout.split()
        if run(c, *WHO, "merge", "-q", "--no-commit", "-s", "ours", "origin/main").returncode != 0:
            die("could not start the merge commit")
        # the tree is main's tree exactly (the branch touched only the lockbox file); then that file = main's bytes + the append
        if run(c, "read-tree", "--reset", "-u", "origin/main").returncode != 0:
            die("could not take main's files")
        Path(c, F).write_bytes(new)
        if run(c, "add", "-A").returncode != 0:
            die("could not stage the file")
        msg = (f"lockbox: bring the put of {key} up to main {main_[:12]} "
               f"(bytes appended unchanged; via lockbox-put-catchup)")
        if run(c, *WHO, "commit", "-q", "-m", msg).returncode != 0:
            die("commit failed")
        new_head = run(c, "rev-parse", "HEAD").stdout.strip()
        after = run(c, "diff", "--numstat", main_, new_head).stdout.split()
        parents = run(c, "rev-list", "--parents", "-n", "1", new_head).stdout.split()[1:]
        got = blob(c, new_head)
        checks = {
            "one_file_additions_only": len(after) == 3 and after[1] == "0" and after[2] == F,
            "same_added_line_count": len(after) == 3 and len(before) == 3 and after[0] == before[0],
            "main_bytes_kept": got.startswith(m),
            "appended_bytes_identical": hashlib.sha256(got[len(m):]).digest() == hashlib.sha256(app).digest(),
            "key_defined_once": len(key_md.findall(got)) == 1 and not key_env.search(got),
            "no_conflict_marker_added": not re.search(rb"^(<<<<<<<|=======|>>>>>>>)", got[len(m):], re.M),
            "only_the_lockbox_file_differs_from_main": run(c, "diff", "--name-only", main_, new_head).stdout.split() == [F],
            "old_head_is_a_parent": old in parents,
            "main_is_a_parent": main_ in parents,
        }
        for k, v in checks.items():
            print(f"  {k}: {'yes' if v else 'NO'}")
        if not all(checks.values()):
            die("a check failed: NOTHING PUSHED")
        if run(c, "push", "-q", "origin", f"HEAD:{branch}").returncode != 0:
            die("push failed (details withheld); nothing changed on origin")
        print(f"ok: {branch} moved {old[:12]} -> {new_head} on main {main_[:12]}; "
              f"+{after[0]}/-0, one file, {key} defined once")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # never a traceback: it could carry data
        print(f"lockbox-put-catchup: error: {type(e).__name__}")
        sys.exit(2)
