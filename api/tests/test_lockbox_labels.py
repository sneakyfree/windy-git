"""lockbox-relabel and lockbox-note against a LOCAL fake lockbox repo only (never the real one; made-up values).

The entries are made by the REAL scripts/lockbox_put.py, so both tools are proven on its true output.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUT = str(ROOT / "scripts" / "lockbox_put.py")
RELABEL = str(ROOT / "scripts" / "lockbox_relabel.py")
NOTE = str(ROOT / "scripts" / "lockbox_note.py")
T = ("-c", "user.name=t", "-c", "user.email=t@t.invalid")
V1, V2 = "oldVALUE0001AAAA====", "newVALUE0002BBBB"  # synthetic
DAY = dt.datetime.now(dt.UTC).strftime("%Y%m%d")
HAND = ("## an older entry, made by hand (no name in the heading)\n\nsome words\n"
        "- **`HAND_MADE_TOKEN`**: `handVALUE0003CCCC`\n- **`HAND_MADE_TOKEN_V2`**: `handVALUE0004DDDD`\n"
        "OLD_STYLE_ENV_NAME=envVALUE0005EEEE\n")


def git(cwd, *a, check=True):
    return subprocess.run(["git", "-C", str(cwd), *T, *a], check=check, capture_output=True, text=True)


def make_remote(tmp_path):
    work = tmp_path / "seed"
    work.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    lines = ["# FAKE LOCKBOX (made-up values, a test)", ""]
    for i in range(200):
        lines += [f"## key {i}", f"- **`FAKE_KEY_{i:04d}`**: `fake-value-{i:04d}-{'x' * 40}`", "- **Note:** made up", ""]
    (work / "ACCESS_LOCKBOX.md").write_text("\n".join(lines) + "\n" + HAND)
    (work / "secrets" / "a").mkdir(parents=True)
    (work / "secrets" / "a" / "x.env").write_text("IN_ENV_ONLY=fake-env-value-1234\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "seed")
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(bare)], check=True)
    return bare


def env(tmp_path, bare):
    (tmp_path / "h" / ".cache").mkdir(parents=True, exist_ok=True)
    return {**os.environ, "LOCKBOX_PUT_REPO": str(bare), "LOCKBOX_PUT_NO_PR": "1", "HOME": str(tmp_path / "h")}


def run(tmp_path, bare, script, *args, stdin=None):
    r = subprocess.run([sys.executable, script, *args], input=stdin, capture_output=True, text=True,
                       env=env(tmp_path, bare))
    return r.returncode, r.stdout + r.stderr


def branch_of(out):
    m = re.search(r"pushed branch (\S+?)[; ]", out)
    assert m, out
    return m.group(1)


def merge_to_main(tmp_path, bare, branch):
    d = tmp_path / "m"
    subprocess.run(["rm", "-rf", str(d)], check=True)
    subprocess.run(["git", "clone", "-q", str(bare), str(d)], check=True, capture_output=True)
    git(d, "merge", "-q", "--no-ff", "-m", f"merge {branch}", f"origin/{branch}")
    git(d, "push", "-q", "origin", "main")


def text_at(bare, rev="main"):
    return subprocess.run(["git", "-C", str(bare), "show", f"{rev}:ACCESS_LOCKBOX.md"], check=True,
                          capture_output=True, text=True).stdout


def refs(bare):
    return subprocess.run(["git", "-C", str(bare), "for-each-ref", "--format=%(refname) %(objectname)"], check=True,
                          capture_output=True, text=True).stdout


def put(tmp_path, bare, key, value):
    rc, out = run(tmp_path, bare, PUT, key, "-", "--lane", "test", "--note", "n", stdin=value)
    assert rc == 0, out
    merge_to_main(tmp_path, bare, branch_of(out))


# ---------- lockbox-relabel ----------

def test_relabel_marks_a_lockbox_put_entry_in_its_heading_and_its_line_and_nothing_else(tmp_path):
    bare = make_remote(tmp_path)
    put(tmp_path, bare, "PROBE_TOKEN_20261102", V1)
    put(tmp_path, bare, "PROBE_TOKEN_20261112", V2)
    before = text_at(bare)
    rc, out = run(tmp_path, bare, RELABEL, "PROBE_TOKEN_20261102", "--lane", "test")
    assert rc == 0 and "NO" not in out and out.count(": yes") == 7, out
    new = f"PROBE_TOKEN_20261102__SUPERSEDED_{DAY}"
    assert f"PROBE_TOKEN_20261102 -> {new}; 2 line(s) changed, one file" in out
    for secret in (V1, V2, "VALUE", "fake-value"):
        assert secret not in out
    after = text_at(bare, branch_of(out))
    b, a = before.splitlines(keepends=True), after.splitlines(keepends=True)
    diff = [(x, y) for x, y in zip(b, a, strict=True) if x != y]
    assert len(diff) == 2 and all(x.replace("PROBE_TOKEN_20261102", new) == y for x, y in diff)
    assert f"- **`{new}`**: `{V1}`\n" in a  # the value is kept, under the labelled name
    assert f"- **`PROBE_TOKEN_20261112`**: `{V2}`\n" in a  # the entry that replaced it is untouched
    assert "- **`PROBE_TOKEN_20261102`**:" not in after


def test_relabel_a_hand_made_entry_changes_one_line_and_never_the_longer_name(tmp_path):
    bare = make_remote(tmp_path)
    before = text_at(bare)
    rc, out = run(tmp_path, bare, RELABEL, "HAND_MADE_TOKEN")
    new = f"HAND_MADE_TOKEN__SUPERSEDED_{DAY}"
    assert rc == 0 and f"HAND_MADE_TOKEN -> {new}; 1 line(s) changed, one file" in out, out
    after = text_at(bare, branch_of(out))
    assert after == before.replace("- **`HAND_MADE_TOKEN`**:", f"- **`{new}`**:")
    assert "- **`HAND_MADE_TOKEN_V2`**: `handVALUE0004DDDD`\n" in after  # NAME_V2 is a different name


def relabel_refused(tmp_path, bare, name, words, code=3):
    snapshot = refs(bare)
    rc, out = run(tmp_path, bare, RELABEL, name)
    assert rc == code and words in out, out
    assert "ok: " not in out and "VALUE" not in out
    assert refs(bare) == snapshot  # nothing was pushed


def test_relabel_refuses_what_is_not_one_plain_lockbox_entry(tmp_path):
    bare = make_remote(tmp_path)
    relabel_refused(tmp_path, bare, "NOT_THERE_AT_ALL", "not defined exactly once")
    relabel_refused(tmp_path, bare, "OLD_STYLE_ENV_NAME", "not defined exactly once")  # a NAME= line, not an entry
    relabel_refused(tmp_path, bare, "IN_ENV_ONLY", "in a secrets .env file")
    relabel_refused(tmp_path, bare, f"FAKE_KEY_0001__SUPERSEDED_{DAY}", "already carries a superseded label", code=2)
    relabel_refused(tmp_path, bare, "lower_case", "OLD_NAME must match", code=2)
    relabel_refused(tmp_path, bare, "A" * 50, "longer than 64 characters", code=2)


def test_relabel_refuses_a_name_defined_twice_and_a_label_that_exists(tmp_path):
    bare = make_remote(tmp_path)
    d = tmp_path / "e"
    subprocess.run(["git", "clone", "-q", str(bare), str(d)], check=True, capture_output=True)
    with open(d / "ACCESS_LOCKBOX.md", "a") as fh:
        fh.write("\n## twice\n- **`FAKE_KEY_0002`**: `anotherVALUE0006`\n"
                 f"\n## taken\n- **`FAKE_KEY_0003__SUPERSEDED_{DAY}`**: `takenVALUE0007`\n")
    git(d, "commit", "-qam", "a duplicate and a taken label")
    git(d, "push", "-q", "origin", "main")
    relabel_refused(tmp_path, bare, "FAKE_KEY_0002", "not defined exactly once")
    relabel_refused(tmp_path, bare, "FAKE_KEY_0003", "the new name exists already")


def test_relabel_never_a_traceback(tmp_path):
    rc, out = run(tmp_path, tmp_path / "no-such-repo.git", RELABEL, "FAKE_KEY_0001")
    assert rc == 2 and "clone failed" in out and "Traceback" not in out


# ---------- lockbox-note ----------

TITLE = "suquT EPTs dead after 2026-11-16"
TEXT = ("An EPT in the sections Fleet bot Eternitas passports and SEARCH_PROBE_EPT signed by key id suquT "
        "is refused after CA Phase 4, MON 2026-11-16 11:00Z. See WINDY_CALENDAR_PROBE_EPT_20261102__SUPERSEDED_20261112.")


def test_note_appends_three_lines_at_the_end_and_defines_no_name(tmp_path):
    bare = make_remote(tmp_path)
    before = text_at(bare)
    rc, out = run(tmp_path, bare, NOTE, "--lane", "Windy Admin Panel", "--title", TITLE, TEXT)
    assert rc == 0 and "one note, 3 lines added, one file" in out, out
    after = text_at(bare, branch_of(out))
    assert after.startswith(before)
    block = after[len(before):]
    day = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    assert block == f"\n## 📝 NOTE {day} (Windy Admin Panel): {TITLE}\n- **Note:** {TEXT}\n"
    assert "**`" not in block and "=" not in block


def note_refused(tmp_path, bare, title, text, words):
    snapshot = refs(bare)
    rc, out = run(tmp_path, bare, NOTE, "--lane", "test", "--title", title, text)
    assert rc == 2 and words in out, out
    assert "ok: " not in out and refs(bare) == snapshot
    return out


def test_note_refuses_anything_that_could_be_a_secret_or_a_name(tmp_path):
    bare = make_remote(tmp_path)
    ok_title, ok_text = "a title", "plain words only"
    note_refused(tmp_path, bare, ok_title, "a backtick ` here", "not allowed")
    note_refused(tmp_path, bare, ok_title, "SOME_NAME=value1234", "not allowed")  # no equals sign: never a NAME= line
    note_refused(tmp_path, bare, ok_title, "- **bold** words", "not allowed")  # no asterisk: never a **`NAME`**: line
    note_refused(tmp_path, bare, ok_title, "two\nlines", "not allowed")
    note_refused(tmp_path, bare, "x" * 61, ok_text, "4 to 60 characters")
    note_refused(tmp_path, bare, ok_title, "w " * 151, "4 to 300 characters")
    long_value = "Zk3vQ8mT1pLw7Xn2Rb5Hd9YcQ4"  # synthetic, 26 characters, mixed case
    out = note_refused(tmp_path, bare, ok_title, f"see {long_value} for it", "could be a value")
    assert long_value not in out  # a refused text is never echoed
    fake_aws = "AKIA" + "ABCDEFGHIJKLMNOP"  # synthetic, the shape only
    out = note_refused(tmp_path, bare, ok_title, f"the key {fake_aws} is old", "secret-shaped")
    assert fake_aws not in out
    note_refused(tmp_path, bare, f"about {fake_aws}", ok_text, "secret-shaped")


def test_note_needs_a_lane_and_never_a_traceback(tmp_path):
    bare = make_remote(tmp_path)
    rc, out = run(tmp_path, bare, NOTE, "--lane", "!!!", "--title", "a title", "plain words only")
    assert rc == 2 and "--lane must name the lane" in out
    rc, out = run(tmp_path, tmp_path / "no-such-repo.git", NOTE, "--lane", "test", "--title", "a title", "plain words only")
    assert rc == 2 and "clone failed" in out and "Traceback" not in out
