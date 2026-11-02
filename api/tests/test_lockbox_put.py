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


# ---- stdin mode: FILE "-" / --stdin (Boss rule 10-22: secrets via stdin only, no temp file) ----


def put_stdin(tmp_path, bare, key, data, *, args=("-",), stdin=None):
    """Run lockbox-put with the value piped on stdin (`data`, bytes) or with `stdin` (an fd)."""
    e = {**os.environ, "LOCKBOX_PUT_REPO": str(bare), "LOCKBOX_PUT_NO_PR": "1", "HOME": str(tmp_path / "h")}
    (tmp_path / "h" / ".cache").mkdir(parents=True, exist_ok=True)
    kw = {"input": data} if stdin is None else {"stdin": stdin}
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "lockbox_put.py"), key, *args, "--lane", "test", "--note", "n"],
                       capture_output=True, env=e, **kw)
    return r.returncode, (r.stdout + r.stderr).decode(errors="replace")


def branches(bare):
    return [b.strip() for b in sh("git", "branch", "--list", "lockbox-put/*", cwd=bare).stdout.splitlines()]


def test_stdin_dash_appends_exactly_one_line_and_never_echoes(tmp_path):
    bare = make_remote(tmp_path)
    rc, out = put_stdin(tmp_path, bare, "STDIN_KEY", (FAKE + "\n").encode())
    assert rc == 0 and "pushed branch lockbox-put/stdin_key-" in out
    assert FAKE not in out and FAKE[:6] not in out
    br = branches(bare)
    assert len(br) == 1
    diff = sh("git", "diff", "--numstat", f"main..{br[0]}", cwd=bare).stdout.split()
    assert diff[1] == "0" and diff[2] == "ACCESS_LOCKBOX.md"
    content = sh("git", "show", f"{br[0]}:ACCESS_LOCKBOX.md", cwd=bare).stdout
    assert content.count(FAKE) == 1  # exactly one line carries the value, newline stripped
    assert f"- **`STDIN_KEY`**: `{FAKE}`\n" in content
    assert FAKE not in sh("git", "show", "main:ACCESS_LOCKBOX.md", cwd=bare).stdout


def test_stdin_flag_is_same_as_dash(tmp_path):
    bare = make_remote(tmp_path)
    rc, out = put_stdin(tmp_path, bare, "STDIN_FLAG_KEY", FAKE.encode(), args=("--stdin",))
    assert rc == 0 and FAKE not in out
    content = sh("git", "show", f"{branches(bare)[0]}:ACCESS_LOCKBOX.md", cwd=bare).stdout
    assert f"- **`STDIN_FLAG_KEY`**: `{FAKE}`" in content


def test_stdin_refuses_a_tty(tmp_path):
    import pty

    bare = make_remote(tmp_path)
    master, slave = pty.openpty()
    try:
        rc, out = put_stdin(tmp_path, bare, "TTY_KEY", None, stdin=slave)
    finally:
        os.close(master)
        os.close(slave)
    assert rc == 2 and "terminal" in out and "pipe it in" in out
    assert not branches(bare)


def test_stdin_rejects_invalid_empty_and_oversized(tmp_path):
    bare = make_remote(tmp_path)
    bad = "has space `Qx7mark` " + FAKE
    for data in (bad.encode(), b"short", b"", b"\n  \n", (FAKE * 30).encode(), (FAKE * 200).encode(), b"A" * 5000 + b"\n"):
        rc, out = put_stdin(tmp_path, bare, "BAD_STDIN_KEY", data)
        assert rc == 2, data[:20]
        assert FAKE not in out and "Qx7mark" not in out
    assert "empty" in put_stdin(tmp_path, bare, "BAD_STDIN_KEY", b"")[1]
    assert "longer than 4096" in put_stdin(tmp_path, bare, "BAD_STDIN_KEY", b"A" * 4097)[1]
    assert not branches(bare)


def test_stdin_refuses_existing_key_and_file_plus_flag(tmp_path):
    bare = make_remote(tmp_path)
    for k in ("EXISTING_KEY", "OLD_ENV_KEY"):
        rc, out = put_stdin(tmp_path, bare, k, FAKE.encode())
        assert rc == 3 and "already exists" in out and FAKE not in out
    rc, out = put_stdin(tmp_path, bare, "BOTH_KEY", FAKE.encode(), args=(str(tmp_path / "x"), "--stdin"))
    assert rc == 2 and "not both" in out
    rc, out = put_stdin(tmp_path, bare, "NONE_KEY", FAKE.encode(), args=())
    assert rc == 2 and "FILE is required" in out
    assert not branches(bare)


def test_file_path_still_refuses_symlink_and_dev_stdin(tmp_path):
    """Regression: the FILE path keeps lstat + regular + 0600 checks; /dev/stdin is not '-'."""
    bare = make_remote(tmp_path)
    real = tmp_path / "real2"
    real.write_text(FAKE)
    os.chmod(real, 0o600)
    link = tmp_path / "link2"
    link.symlink_to(real)
    rc, out = put_stdin(tmp_path, bare, "SYM2_KEY", b"", args=(str(link),))
    assert rc == 2 and "symlink" in out and FAKE not in out
    rc, out = put_stdin(tmp_path, bare, "DEVSTDIN_KEY", FAKE.encode(), args=("/dev/stdin",))
    assert rc == 2 and FAKE not in out
    assert not branches(bare)


def test_work_dir_prefers_ram(monkeypatch, tmp_path):
    """The temp lockbox clone holds every value: it goes to RAM ($XDG_RUNTIME_DIR, then /dev/shm),
    ~/.cache only where neither exists (Windy Git review of #65)."""
    import importlib.util
    import pathlib

    spec = importlib.util.spec_from_file_location(
        "lockbox_put_wd", pathlib.Path(__file__).resolve().parents[2] / "scripts" / "lockbox_put.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    run = tmp_path / "run"
    run.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(run))
    assert mod.work_dir() == str(run)
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    monkeypatch.setattr(mod.os.path, "isdir", lambda d: d == "/dev/shm")
    monkeypatch.setattr(mod.os, "access", lambda d, m: d == "/dev/shm")
    assert mod.work_dir() == "/dev/shm"


# ── --batch (2026-11-02, Boss: one key = one PR; lockbox-put-pem stores KEY_PART1..N + KEY_PARTS) ──

V1, V2, V3 = "Ab3dEf6hIj9kLm2nOp5q", "Qr8sTu1vWx4yZa7bCd0e", "Fg2hIj5kLm8nOp1qRs4t"  # synthetic


def batch(tmp_path, bare, stdin, extra_env=None, note="n"):
    e = {**os.environ, "LOCKBOX_PUT_REPO": str(bare), "LOCKBOX_PUT_NO_PR": "1", "HOME": str(tmp_path / "h"), **(extra_env or {})}
    if extra_env and extra_env.get("LOCKBOX_PUT_NO_PR") == "":
        e.pop("LOCKBOX_PUT_NO_PR")
    (tmp_path / "h" / ".cache").mkdir(parents=True, exist_ok=True)
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "lockbox_put.py"), "--batch", "-", "--lane", "test", "--note", note],
                       input=stdin, capture_output=True, text=True, env=e)
    return r.returncode, r.stdout, r.stderr


def test_batch_appends_all_lines_in_ONE_commit_and_never_echoes(tmp_path):
    bare = make_remote(tmp_path)
    rc, out, err = batch(tmp_path, bare, f"NEW_PEM_PART1\t{V1}\tpart 1 of 2\nNEW_PEM_PART2\t{V2}\tpart 2 of 2\nNEW_PEM_PARTS\tparts=02\n")
    assert rc == 0, err
    assert all(v not in out + err for v in (V1, V2, "parts=02")) and "3 keys" in out
    br = branches(bare)
    assert len(br) == 1
    assert sh("git", "rev-list", "--count", f"main..{br[0]}", cwd=bare).stdout.strip() == "1"   # ONE commit
    added, deleted, path = sh("git", "diff", "--numstat", f"main..{br[0]}", cwd=bare).stdout.split()
    assert (deleted, path) == ("0", "ACCESS_LOCKBOX.md") and added == str(2 + 3 + 3)        # blank + heading, 3 keys, 3 notes (--note n for line 3)
    content = sh("git", "show", f"{br[0]}:ACCESS_LOCKBOX.md", cwd=bare).stdout
    for k, v in (("NEW_PEM_PART1", V1), ("NEW_PEM_PART2", V2), ("NEW_PEM_PARTS", "parts=02")):
        assert f"- **`{k}`**: `{v}`" in content
    assert "- **Note (NEW_PEM_PART1):** part 1 of 2" in content and "- **Note (NEW_PEM_PARTS):** n" in content
    assert V1 not in sh("git", "show", "main:ACCESS_LOCKBOX.md", cwd=bare).stdout


def test_batch_one_bad_value_on_line_3_writes_nothing(tmp_path):
    bare = make_remote(tmp_path)
    rc, out, err = batch(tmp_path, bare, f"NEW_A\t{V1}\nNEW_B\t{V2}\nNEW_C\tbad value with spaces\nNEW_D\t{V3}\n")
    assert rc == 3 and "batch refused: line 3:" in err
    assert branches(bare) == []
    assert all(v not in out + err for v in (V1, V2, V3, "bad value"))


def test_batch_refuses_duplicates_existing_keys_bad_notes_and_shapes(tmp_path):
    bare = make_remote(tmp_path)
    cases = [
        (f"NEW_A\t{V1}\nNEW_A\t{V2}\n", "line 2:", "twice"),
        (f"NEW_A\t{V1}\nEXISTING_KEY\t{V2}\n", "line 2:", "already exists"),
        (f"NEW_A\t{V1}\nOLD_ENV_KEY\t{V2}\n", "line 2:", "already exists"),
        (f"NEW_A\t{V1}\tnote with a `backtick`\n", "line 1:", "NOTE"),
        (f"NEW_A\t{V1}\t{'x' * 201}\n", "line 1:", "NOTE"),
        (f"new_lower\t{V1}\n", "line 1:", "KEY must match"),
        (f"NEW_A {V1}\n", "line 1:", "expected KEY<TAB>VALUE"),
        (f"NEW_A\t{V1}\tn\textra\n", "line 1:", "expected KEY<TAB>VALUE"),
        ("".join(f"NEW_K{i:02d}\t{V1}\n" for i in range(41)), "41 lines", "at most 40"),
        ("", "empty", "empty"),
    ]
    for stdin, where, why in cases:
        rc, out, err = batch(tmp_path, bare, stdin)
        assert rc == 3 and where in err and why in err, (where, why, err)
        assert V1 not in out + err and V2 not in out + err
    assert branches(bare) == []
    # the existing-KEY refusal never says WHERE the key lives
    rc, out, err = batch(tmp_path, bare, f"EXISTING_KEY\t{V1}\n")
    assert "ACCESS_LOCKBOX" not in err and "secrets/" not in err


def test_batch_refuses_more_than_64_kib(tmp_path):
    bare = make_remote(tmp_path)
    rc, _out, err = batch(tmp_path, bare, "A" * (64 * 1024 + 1))
    assert rc == 3 and "65536 bytes" in err
    assert branches(bare) == []


def test_batch_pr_failure_deletes_the_pushed_branch(tmp_path):
    bare = make_remote(tmp_path)
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    (fakebin / "gh").write_text("#!/bin/sh\nexit 1\n")
    os.chmod(fakebin / "gh", 0o755)
    rc, out, err = batch(tmp_path, bare, f"NEW_A\t{V1}\n", {"LOCKBOX_PUT_NO_PR": "", "PATH": f"{fakebin}:{os.environ['PATH']}"})
    assert rc == 4 and "deleted" in err
    assert branches(bare) == []
