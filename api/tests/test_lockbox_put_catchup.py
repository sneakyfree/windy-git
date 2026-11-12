"""lockbox-put-catchup against a LOCAL fake lockbox repo only (never the real one; made-up values).

The puts are made by the REAL scripts/lockbox_put.py, so the catch-up is proven on its true output.
Ported from Windy Word's prove.sh (24 of 24 on 2026-11-12), plus the cases for Windy Vault's four changes.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUT = str(ROOT / "scripts" / "lockbox_put.py")
CATCHUP = str(ROOT / "scripts" / "lockbox_put_catchup.py")
T = ("-c", "user.name=t", "-c", "user.email=t@t.invalid")
V1, V2, V3 = "revokeVALUE0001AAAA", "keyVALUE0002BBBB====", "ccccVALUE0003cccc"  # synthetic


def git(cwd, *a, check=True):
    return subprocess.run(["git", "-C", str(cwd), *T, *a], check=check, capture_output=True, text=True)


def make_remote(tmp_path):
    """A fake lockbox of real shape and size: 600 entries, about 3,600 lines, plus a secrets .env."""
    work = tmp_path / "seed"
    work.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    lines = ["# FAKE LOCKBOX (made-up values, a test)", ""]
    for i in range(600):
        lines += [f"## key {i}", f"- **`FAKE_KEY_{i:04d}`**: `fake-value-{i:04d}-{'x' * 40}`", "- **Note:** made up", "",
                  "text line", ""]
    (work / "ACCESS_LOCKBOX.md").write_text("\n".join(lines) + "\n")
    (work / "secrets" / "a").mkdir(parents=True)
    (work / "secrets" / "a" / "x.env").write_text("IN_ENV_ALREADY=fake-env-value-1234\n")
    (work / "README.txt").write_text("OTHER=1\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "seed")
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(bare)], check=True)
    return bare


def env(tmp_path, bare):
    (tmp_path / "h" / ".cache").mkdir(parents=True, exist_ok=True)
    return {**os.environ, "LOCKBOX_PUT_REPO": str(bare), "LOCKBOX_PUT_NO_PR": "1", "HOME": str(tmp_path / "h")}


def put(tmp_path, bare, key, value):
    r = subprocess.run([sys.executable, PUT, key, "-", "--lane", "test", "--note", "n"], input=value,
                       capture_output=True, text=True, env=env(tmp_path, bare))
    m = re.search(r"pushed branch (\S+) ", r.stdout)
    assert r.returncode == 0 and m, r.stdout
    return m.group(1)


def catchup(tmp_path, bare, *args):
    r = subprocess.run([sys.executable, CATCHUP, *args], capture_output=True, text=True, env=env(tmp_path, bare))
    return r.returncode, r.stdout + r.stderr


def clone(tmp_path, bare, name):
    d = tmp_path / name
    subprocess.run(["rm", "-rf", str(d)], check=True)
    subprocess.run(["git", "clone", "-q", str(bare), str(d)], check=True, capture_output=True)
    return d


def merge_to_main(tmp_path, bare, branch):
    """What the Hub's merge does: a merge commit of the put branch into main. Returns True if it merged."""
    d = clone(tmp_path, bare, "m")
    if git(d, "merge", "-q", "--no-ff", "-m", f"merge {branch}", f"origin/{branch}", check=False).returncode != 0:
        return False
    git(d, "push", "-q", "origin", "main")
    return True


def main_text(bare):
    return subprocess.run(["git", "-C", str(bare), "show", "main:ACCESS_LOCKBOX.md"], check=True,
                          capture_output=True, text=True).stdout


def values(bare, key):
    return re.findall(r"^- \*\*`" + re.escape(key) + r"`\*\*: `(.*)`$", main_text(bare), re.M)


def head(bare, branch):
    return subprocess.run(["git", "-C", str(bare), "rev-parse", branch], check=True, capture_output=True,
                          text=True).stdout.strip()


def push_extra_commit(tmp_path, bare, branch, edit):
    """Add one commit on a put branch (to build the cases the tool must refuse)."""
    d = clone(tmp_path, bare, "e")
    git(d, "checkout", "-q", "-b", "x", f"origin/{branch}")
    edit(d)
    git(d, "add", "-A")
    git(d, "commit", "-qm", "a test edit")
    git(d, "push", "-q", "origin", f"x:{branch}")


def test_the_real_case_second_put_conflicts_then_catches_up_and_merges(tmp_path):
    bare = make_remote(tmp_path)
    lines_before = main_text(bare).count("\n")
    b1 = put(tmp_path, bare, "TEST_REVOKE_B64_20261112", V1)
    b2 = put(tmp_path, bare, "TEST_KEY_B64_20261112", V2)
    assert merge_to_main(tmp_path, bare, b1)
    assert not merge_to_main(tmp_path, bare, b2)  # the fault, reproduced
    old = head(bare, b2)
    rc, out = catchup(tmp_path, bare, b2, "TEST_KEY_B64_20261112")
    assert rc == 0 and "ok: " in out and "NO" not in out, out
    for secret in (V1, V2, "VALUE", "fake-value"):
        assert secret not in out  # nothing of the file is printed
    assert out.count(": yes") == 9
    new = head(bare, b2)
    parents = subprocess.run(["git", "-C", str(bare), "rev-list", "--parents", "-n", "1", new], check=True,
                             capture_output=True, text=True).stdout.split()[1:]
    assert parents == [old, head(bare, "main")]  # a merge commit, never a rewrite of the branch
    assert merge_to_main(tmp_path, bare, b2)
    assert values(bare, "TEST_REVOKE_B64_20261112") == [V1]
    assert values(bare, "TEST_KEY_B64_20261112") == [V2]
    assert len(values(bare, "FAKE_KEY_0000")) == 1 and len(values(bare, "FAKE_KEY_0599")) == 1
    assert main_text(bare).count("\n") == lines_before + 8  # two blocks of 4 lines (blank, heading, entry, note)
    rc, out = catchup(tmp_path, bare, b2, "TEST_KEY_B64_20261112")
    assert rc == 0 and "nothing to do" in out


def test_three_puts_open_at_once_each_catches_up_in_turn(tmp_path):
    bare = make_remote(tmp_path)
    a = put(tmp_path, bare, "TEST_A_20261112", V1)
    b = put(tmp_path, bare, "TEST_B_20261112", V2)
    c = put(tmp_path, bare, "TEST_C_20261112", V3)
    assert merge_to_main(tmp_path, bare, a)
    assert catchup(tmp_path, bare, b, "TEST_B_20261112")[0] == 0 and merge_to_main(tmp_path, bare, b)
    assert catchup(tmp_path, bare, c, "TEST_C_20261112")[0] == 0 and merge_to_main(tmp_path, bare, c)  # base two merges old
    assert [values(bare, k) for k in ("TEST_A_20261112", "TEST_B_20261112", "TEST_C_20261112")] == [[V1], [V2], [V3]]


def test_main_edited_in_the_middle_is_kept_and_the_put_still_lands(tmp_path):
    """Change (iv): main's bytes + the appended bytes is exact whatever main did since the base."""
    bare = make_remote(tmp_path)
    b1 = put(tmp_path, bare, "TEST_ONE_20261112", V1)
    b2 = put(tmp_path, bare, "TEST_TWO_20261112", V2)
    d = clone(tmp_path, bare, "e")
    p = d / "ACCESS_LOCKBOX.md"
    p.write_text(p.read_text().replace("fake-value-0300-", "fake-value-0300-EDITED-", 1))
    git(d, "commit", "-qam", "an edit in the middle of main")
    git(d, "push", "-q", "origin", "main")
    assert merge_to_main(tmp_path, bare, b1)
    rc, out = catchup(tmp_path, bare, b2, "TEST_TWO_20261112")
    assert rc == 0 and "NO" not in out, out
    assert merge_to_main(tmp_path, bare, b2)
    assert values(bare, "TEST_ONE_20261112") == [V1] and values(bare, "TEST_TWO_20261112") == [V2]
    assert values(bare, "FAKE_KEY_0300")[0].startswith("fake-value-0300-EDITED-")  # the edit is kept
    assert len(values(bare, "FAKE_KEY_0299")) == 1 and len(values(bare, "FAKE_KEY_0301")) == 1


def refused(tmp_path, bare, branch, key, words, code=2):
    h = head(bare, branch)
    rc, out = catchup(tmp_path, bare, branch, key)
    assert rc == code and words in out, out
    assert "ok: " not in out and "VALUE" not in out
    assert head(bare, branch) == h  # the branch did not move


def test_refuses_a_branch_that_touches_another_file(tmp_path):
    bare = make_remote(tmp_path)
    b2 = put(tmp_path, bare, "TEST_TWO_20261112", V2)
    push_extra_commit(tmp_path, bare, b2, lambda d: (d / "README.txt").write_text("OTHER=1\nmore\n"))
    assert merge_to_main(tmp_path, bare, put(tmp_path, bare, "TEST_ONE_20261112", V1))
    refused(tmp_path, bare, b2, "TEST_TWO_20261112", "more than the lockbox file")


def test_refuses_a_branch_that_is_not_a_pure_append(tmp_path):
    bare = make_remote(tmp_path)
    b2 = put(tmp_path, bare, "TEST_TWO_20261112", V2)

    def edit(d):
        p = d / "ACCESS_LOCKBOX.md"
        p.write_text(p.read_text().replace("fake-value-0100-", "fake-value-0100-CHANGED-", 1))
    push_extra_commit(tmp_path, bare, b2, edit)
    assert merge_to_main(tmp_path, bare, put(tmp_path, bare, "TEST_ONE_20261112", V1))
    refused(tmp_path, bare, b2, "TEST_TWO_20261112", "not a pure append to its base")


def test_refuses_a_block_that_defines_a_second_name(tmp_path):
    """Change (iii): one PR, one name, in either form the lockbox file defines a name."""
    for i, extra in enumerate(("- **`SECOND_NAME_20261112`**: `secondVALUE0009`\n", "SECOND_ENV_NAME=secondVALUE0009\n")):
        sub = tmp_path / f"case{i}"
        sub.mkdir()
        bare = make_remote(sub)
        b2 = put(sub, bare, "TEST_TWO_20261112", V2)

        def edit(d, extra=extra):
            with open(d / "ACCESS_LOCKBOX.md", "a") as fh:
                fh.write(extra)
        push_extra_commit(sub, bare, b2, edit)
        assert merge_to_main(sub, bare, put(sub, bare, "TEST_ONE_20261112", V1))
        refused(sub, bare, b2, "TEST_TWO_20261112", "more than one name")


def test_refuses_when_main_already_defines_the_key(tmp_path):
    bare = make_remote(tmp_path)
    b2 = put(tmp_path, bare, "TEST_TWO_20261112", V2)
    d = clone(tmp_path, bare, "e")
    with open(d / "ACCESS_LOCKBOX.md", "a") as fh:
        fh.write("\n## by hand\n- **`TEST_TWO_20261112`**: `otherVALUE0007`\n")
    git(d, "commit", "-qam", "the same name, put on main by another road")
    git(d, "push", "-q", "origin", "main")
    refused(tmp_path, bare, b2, "TEST_TWO_20261112", "main already defines KEY", code=3)


def test_refuses_when_main_defines_the_key_in_a_secrets_env_file(tmp_path):
    """Change (ii): the same two places lockbox-put's key_exists looks."""
    bare = make_remote(tmp_path)
    b2 = put(tmp_path, bare, "TEST_TWO_20261112", V2)
    d = clone(tmp_path, bare, "e")
    (d / "secrets" / "b" / "deep").mkdir(parents=True)
    (d / "secrets" / "b" / "deep" / "y.env").write_text("# a comment\nTEST_TWO_20261112=envVALUE0008\n")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "the same name in a secrets .env")
    git(d, "push", "-q", "origin", "main")
    refused(tmp_path, bare, b2, "TEST_TWO_20261112", "in a secrets .env file", code=3)


def test_refuses_the_wrong_key_a_non_put_branch_and_a_longer_key(tmp_path):
    bare = make_remote(tmp_path)
    b2 = put(tmp_path, bare, "TEST_TWO_20261112", V2)
    assert merge_to_main(tmp_path, bare, put(tmp_path, bare, "TEST_ONE_20261112", V1))
    refused(tmp_path, bare, b2, "TEST_OTHER_20261112", "not this key's put branch")
    refused(tmp_path, bare, b2, "TEST_TWO", "not this key's put branch")  # a shorter name must not match a longer branch
    rc, out = catchup(tmp_path, bare, "word/some-branch", "TEST_TWO_20261112")
    assert rc == 2 and "usage" in out
    rc, out = catchup(tmp_path, bare, "lockbox-put/test_gone_20261112-202611120000", "TEST_GONE_20261112")
    assert rc == 2 and "no such branch" in out


def test_a_merged_branch_and_an_up_to_date_branch_are_nothing_to_do(tmp_path):
    bare = make_remote(tmp_path)
    b1 = put(tmp_path, bare, "TEST_ONE_20261112", V1)
    h = head(bare, b1)
    rc, out = catchup(tmp_path, bare, b1, "TEST_ONE_20261112")  # main has not moved: the branch already holds it
    assert rc == 0 and "nothing to do" in out and head(bare, b1) == h
    assert merge_to_main(tmp_path, bare, b1)
    rc, out = catchup(tmp_path, bare, b1, "TEST_ONE_20261112")
    assert rc == 0 and "nothing to do" in out and head(bare, b1) == h


def test_never_a_traceback(tmp_path):
    """Change (i): a failure says one plain line, never a Python traceback."""
    rc, out = catchup(tmp_path, tmp_path / "no-such-repo.git", "lockbox-put/test_two_20261112-202611120000",
                      "TEST_TWO_20261112")
    assert rc == 2 and "clone failed" in out and "Traceback" not in out
