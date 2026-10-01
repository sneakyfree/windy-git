"""lockbox-put against a LOCAL fake lockbox repo only (never the real one)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAKE = "Zk3vQ8mT1pLw7Xn2Rb5Hd9Yc"  # synthetic


def sh(*a, cwd=None):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True)


def make_remote(tmp_path):
    work = tmp_path / "seed"
    work.mkdir()
    sh("git", "init", "-q", "-b", "main", cwd=work)
    (work / "ACCESS_LOCKBOX.md").write_text("# LOCKBOX\n\n- **`EXISTING_KEY`**: `abcdefgh12345678`\nOLD_ENV_KEY=whatever123456\n")
    sh("git", "add", "-A", cwd=work)
    sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed", cwd=work)
    bare = tmp_path / "remote.git"
    sh("git", "clone", "-q", "--bare", str(work), str(bare))
    return bare


def put(tmp_path, bare, key, content, mode=0o600):
    f = tmp_path / "val"
    f.write_text(content)
    os.chmod(f, mode)
    e = {**os.environ, "LOCKBOX_PUT_REPO": str(bare), "LOCKBOX_PUT_NO_PR": "1", "HOME": str(tmp_path / "h")}
    (tmp_path / "h" / ".cache").mkdir(parents=True, exist_ok=True)
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "lockbox_put.py"), key, str(f), "--lane", "test", "--note", "n"],
                       capture_output=True, text=True, env=e)
    return r.returncode, r.stdout + r.stderr


def test_appends_one_key_by_branch_and_never_echoes_value(tmp_path):
    bare = make_remote(tmp_path)
    rc, out = put(tmp_path, bare, "NEW_TEST_KEY", FAKE)
    assert rc == 0 and "pushed branch lockbox-put/new_test_key-" in out
    assert FAKE not in out and FAKE[:6] not in out
    br = [b.strip() for b in sh("git", "branch", "--list", "lockbox-put/*", cwd=bare).stdout.splitlines()]
    assert len(br) == 1
    diff = sh("git", "diff", "--numstat", f"main..{br[0]}", cwd=bare).stdout.split()
    assert diff[1] == "0" and diff[2] == "ACCESS_LOCKBOX.md"  # additions only
    content = sh("git", "show", f"{br[0]}:ACCESS_LOCKBOX.md", cwd=bare).stdout
    assert f"- **`NEW_TEST_KEY`**: `{FAKE}`" in content and "EXISTING_KEY" in content
    # main is untouched
    assert FAKE not in sh("git", "show", "main:ACCESS_LOCKBOX.md", cwd=bare).stdout


def test_refuses_existing_key_both_formats_and_bad_input(tmp_path):
    bare = make_remote(tmp_path)
    for k in ("EXISTING_KEY", "OLD_ENV_KEY"):
        rc, out = put(tmp_path, bare, k, FAKE)
        assert rc == 3 and "already exists" in out and FAKE not in out
    assert put(tmp_path, bare, "lower_case", FAKE)[0] == 2
    assert put(tmp_path, bare, "OK_KEY_1", FAKE, mode=0o644)[0] == 2        # not 0600
    assert put(tmp_path, bare, "OK_KEY_2", "has space `tick`")[0] == 2        # unsafe value
    assert not sh("git", "branch", "--list", "lockbox-put/*", cwd=bare).stdout.strip()  # nothing pushed


def test_symlink_refused(tmp_path):
    bare = make_remote(tmp_path)
    real = tmp_path / "real"
    real.write_text(FAKE)
    os.chmod(real, 0o600)
    link = tmp_path / "link"
    link.symlink_to(real)
    e = {**os.environ, "LOCKBOX_PUT_REPO": str(bare), "LOCKBOX_PUT_NO_PR": "1"}
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "lockbox_put.py"), "SYM_KEY", str(link)],
                       capture_output=True, text=True, env=e)
    assert r.returncode == 2 and FAKE not in r.stdout + r.stderr
