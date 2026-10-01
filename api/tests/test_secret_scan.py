"""secret-scan + env-names: findings carry label/location/hash, NEVER a value or fragment."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
# Synthetic, random-looking, never real. FAKE_LB is in the fake lockbox; TWI matches a shape.
FAKE_LB = "k7Xv2QpLm9RtZw4HnB8dYc3S"
TWI = "9f3a7c1e5b2d48806a1f4e7d2c9b0835"


def run(script, *args, env=None):
    e = {**os.environ, **(env or {})}
    r = subprocess.run([sys.executable, str(SCRIPTS / script), *args], capture_output=True, text=True, env=e)
    return r.returncode, r.stdout + r.stderr


def no_fragment(out: str, value: str, n: int = 6):
    assert value not in out
    for i in range(len(value) - n + 1):
        assert value[i:i + n] not in out, f"fragment of the value leaked at {i}"


def seeded(tmp_path):
    lb = tmp_path / "lockbox.md"
    lb.write_text(f"FAKE_VENDOR_API_KEY={FAKE_LB}\nNOTE: nothing here\n")
    repo = tmp_path / "repo"
    repo.mkdir()
    g = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)  # noqa: E731
    g("init", "-q", "-b", "main")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    (repo / "app.py").write_text(f'KEY = "{FAKE_LB}"\nTWILIO_AUTH_TOKEN = "{TWI}"\n')
    g("add", "-A")
    g("commit", "-qm", "add secrets")
    (repo / "app.py").write_text("KEY = None\n")  # removed from HEAD, still in history
    g("commit", "-qam", "remove")
    return lb, repo


def test_tree_scan_labels_locations_no_value(tmp_path):
    lb, repo = seeded(tmp_path)
    (repo / "live.py").write_text(f'x = "{FAKE_LB}"\n')
    rc, out = run("secret_scan.py", str(repo / "live.py"), env={"SECRET_SCAN_LOCKBOX_PATHS": str(lb)})
    assert rc == 1
    assert "live.py:1" in out and "lockbox:FAKE_VENDOR_API_KEY" in out
    no_fragment(out, FAKE_LB)


def test_history_finds_removed_secret_with_commit(tmp_path):
    lb, repo = seeded(tmp_path)
    rc, out = run("secret_scan.py", str(repo), "--history", env={"SECRET_SCAN_LOCKBOX_PATHS": str(lb)})
    assert rc == 1
    assert "app.py:1" in out and "commit=" in out and "lockbox:FAKE_VENDOR_API_KEY" in out
    assert "app.py:2" in out and "32-hex secret assignment" in out
    no_fragment(out, FAKE_LB)
    no_fragment(out, TWI)


def test_repo_flag_clones_scans_and_cleans_up(tmp_path):
    lb, repo = seeded(tmp_path)
    cache = tmp_path / "home"
    (cache / ".cache").mkdir(parents=True)
    rc, out = run("secret_scan.py", "--repo", str(repo),
                  env={"SECRET_SCAN_LOCKBOX_PATHS": str(lb), "HOME": str(cache)})
    assert rc == 1 and "app.py:1" in out
    no_fragment(out, FAKE_LB)
    assert not [p for p in (cache / ".cache").iterdir() if p.name.startswith("secret-scan-")]


def test_clean_tree_and_bad_input(tmp_path):
    (tmp_path / "ok.txt").write_text("hello world\n")
    rc, out = run("secret_scan.py", str(tmp_path / "ok.txt"), "--no-lockbox")
    assert rc == 0 and "0 finding(s)" in out
    rc, out = run("secret_scan.py", str(tmp_path), "--history", "--no-lockbox")
    assert rc == 2 and "needs a git repo" in out


def test_env_names_never_prints_values(tmp_path):
    a = tmp_path / "a.env"
    b = tmp_path / "b.env"
    a.write_text(f"# c\nexport DB_PASSWORD={FAKE_LB}\nTOKEN=\"{TWI}\"\nEMPTY=\nONLY_A=1\n")
    b.write_text(f"DB_PASSWORD={FAKE_LB}\nTOKEN=different-value-here\nONLY_B=2\n")
    rc, out = run("env_names.py", str(a), "--hash")
    assert rc == 0 and "DB_PASSWORD" in out and "set" in out and "empty" in out and "len=24" in out
    assert "sha256:" in out
    no_fragment(out, FAKE_LB)
    no_fragment(out, TWI, 7)
    rc, out = run("env_names.py", str(a), "--compare", str(b))
    assert "DB_PASSWORD" in out and "SAME" in out and "DIFFERENT" in out
    assert "only-in-A" in out and "only-in-B" in out
    no_fragment(out, FAKE_LB)
    rc, out = run("env_names.py", str(tmp_path / "missing.env"))
    assert rc == 2


def test_shapes_are_the_guards_shapes():
    sys.path.insert(0, str(SCRIPTS))
    import secret_scan as sc
    import secret_shapes as ss
    assert sc.ss is ss  # one source of shapes: a new guard shape is automatically a scan shape
