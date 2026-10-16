"""No plaintext copies of data or secrets on disk (Boss standing rule, 10-16).

- deploy/branding/apply.sh snapshots app.ini with predeploy-snapshot, never `cp app.ini app.ini.bak-*`,
  and refuses to edit it when the helper is missing.
- scripts/backup.sh stages its plaintext bundles + dump on a tmpfs only.
- scripts/backup_state.sh refuses unless its stage dir is a tmpfs, and its unit mounts one there.

Every test drives the real script with stubs; nothing touches the real host.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _exe(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _stat_says(bin_dir: Path, fstype: str) -> None:
    """A `stat` that reports `fstype` for `stat -f -c %T`, so the test does not depend on the box."""
    _exe(bin_dir / "stat", f'#!/bin/sh\n[ "$1" = -f ] && {{ echo "{fstype}"; exit 0; }}\nexit 1\n')


# ---- branding ---------------------------------------------------------------------------------

def _branding_world(tmp_path: Path, with_helper: bool):
    custom = tmp_path / "gitea"
    (custom / "conf").mkdir(parents=True)
    ini = custom / "conf/app.ini"
    ini.write_text("APP_NAME = Gitea\n[security]\nSECRET_KEY = canary-not-a-real-secret\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # sudo [VAR=val ...] cmd args: run it here, as us (chown is the only root-only call)
    _exe(bin_dir / "sudo", '#!/bin/bash\nwhile [[ $1 == *=* ]]; do export "$1"; shift; done\n'
                           '[[ $1 == chown ]] && exit 0\nexec "$@"\n')
    calls = tmp_path / "snapshot-calls"
    if with_helper:
        _exe(bin_dir / "predeploy-snapshot",
             f'#!/bin/bash\necho "$WINDY_LANE $*" >> {calls}\n')
    env = {**os.environ, "PATH": f"{bin_dir}:{Path(sys.executable).parent}:/usr/bin:/bin",
           "GITEA_CUSTOM_HOST": str(custom)}
    return ini, calls, env


def _branding(env):
    return subprocess.run(["bash", str(ROOT / "deploy/branding/apply.sh")], env=env,
                          capture_output=True, text=True, timeout=60)


def test_branding_snapshots_app_ini_encrypted_and_leaves_no_plaintext_copy(tmp_path):
    ini, calls, env = _branding_world(tmp_path, with_helper=True)
    r = _branding(env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert calls.read_text().split() == ["windy-git", "windy-git", "gitea-app-ini", str(ini)]
    assert ini.read_text().splitlines()[0] == "APP_NAME = Windy Git"
    assert sorted(p.name for p in ini.parent.iterdir()) == ["app.ini"]  # no app.ini.bak-*


def test_branding_refuses_to_edit_app_ini_without_the_helper(tmp_path):
    ini, calls, env = _branding_world(tmp_path, with_helper=False)
    before = ini.read_text()
    r = _branding(env)
    assert r.returncode == 1
    assert "refusing to edit app.ini without a snapshot" in r.stdout
    assert ini.read_text() == before
    assert sorted(p.name for p in ini.parent.iterdir()) == ["app.ini"]


# ---- nightly state backup ---------------------------------------------------------------------

def _state_world(tmp_path: Path, fstype: str):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stat_says(bin_dir, fstype)
    ran = tmp_path / "ran"
    for tool in ("restic", "docker"):  # must never be reached when the stage is refused
        _exe(bin_dir / tool, f'#!/bin/sh\necho {tool} >> {ran}\nexit 1\n')
    pw = tmp_path / "restic.pass"
    pw.write_text("x")
    stage = tmp_path / "stage"
    env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin",
           "R2_ACCOUNT_ID": "fake", "R2_ACCESS_KEY_ID": "fake", "R2_SECRET_ACCESS_KEY": "fake",
           "RESTIC_PASSWORD_FILE": str(pw), "WG_STAGE": str(stage),
           "RESTIC_CACHE_DIR": str(tmp_path / "cache")}
    return env, ran


def _state(env):
    return subprocess.run(["bash", str(ROOT / "scripts/backup_state.sh")], env=env,
                          capture_output=True, text=True, timeout=60)


def test_state_backup_refuses_a_stage_dir_on_disk_before_dumping_anything(tmp_path):
    env, ran = _state_world(tmp_path, "ext2/ext3")
    r = _state(env)
    assert r.returncode == 1
    assert "is not a tmpfs" in r.stdout
    assert not ran.exists()  # no restic, no pg_dump


def test_state_backup_goes_past_the_check_on_a_tmpfs(tmp_path):
    env, ran = _state_world(tmp_path, "tmpfs")
    r = _state(env)
    assert "is not a tmpfs" not in r.stdout
    assert ran.read_text().split()[0] == "restic"  # the next step ran (and the stub failed it)


def test_state_backup_unit_mounts_a_private_tmpfs_on_the_default_stage():
    script = (ROOT / "scripts/backup_state.sh").read_text()
    default = script.split('STAGE="${WG_STAGE:-', 1)[1].split("}", 1)[0]
    conf = (ROOT / "deploy/systemd/windygit-state-backup.service.d/stage-tmpfs.conf").read_text()
    assert f"TemporaryFileSystem={default}:mode=0700" in conf.splitlines()


# ---- nightly bundle backup --------------------------------------------------------------------

def test_bundle_backup_refuses_to_stage_on_disk(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stat_says(bin_dir, "ext2/ext3")
    ram = tmp_path / "ram"
    ram.mkdir()
    env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin", "WG_BACKUP_TMPFS": str(ram)}
    env.pop("WG_TMPFS_ANY", None)
    r = subprocess.run(["bash", str(ROOT / "scripts/backup.sh")], env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 1
    assert "is not a tmpfs: plaintext must stay in RAM" in r.stdout
    assert list(ram.iterdir()) == []  # nothing staged
