"""scripts/sync_token_hygiene.sh: the nightly by-count check that #18's fix has not regressed.

Fake tokens only. Linux only (GNU stat/base64, /proc), like the host it runs on.
"""

from __future__ import annotations

import grp
import os
import pwd
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="runs on Veron (Linux)")

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "sync_token_hygiene.sh"
# Built in pieces so the repo's secret-literal invariant (test_g05) stays quiet.
GH = "gho" + "_FAKEhygieneTOKEN" + "0123456789abcdefgh"
WG = "fakegitea" + "hygienetoken0123456789abcdef"


def _world(tmp_path: Path, url: str) -> dict:
    work = tmp_path / "work"
    work.mkdir()
    work.chmod(0o750)
    bare = work / "demo.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(["git", "--git-dir", str(bare), "remote", "add", "origin", url], check=True)
    (bare / "config").chmod(0o600)
    env_file = tmp_path / "sync.env"
    env_file.write_text(f"GITHUB_TOKEN={GH}\nGITEA_SYNC_TOKEN={WG}\n")
    me = f"{pwd.getpwuid(os.getuid()).pw_name}:{grp.getgrgid(os.getgid()).gr_name}"
    gitea = tmp_path / "repositories"
    gitea.mkdir()
    return {**os.environ, "SYNC_WORK": str(work), "SYNC_ENV_FILE": str(env_file), "EXPECT_OWNER": me,
            "GITEA_REPOS": str(gitea)}


def _run(env):
    return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)


def test_clean_work_dir_passes(tmp_path):
    r = _run(_world(tmp_path, "https://github.com/o/demo.git"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "files=0 remote-creds=0 argv=0" in r.stdout


def test_token_in_a_remote_url_fails_and_is_never_printed(tmp_path):
    r = _run(_world(tmp_path, f"https://x-access-token:{GH}@github.com/o/demo.git"))
    assert r.returncode == 1
    assert "files=1 remote-creds=1" in r.stdout
    assert GH not in r.stdout + r.stderr


def test_loose_config_mode_fails(tmp_path):
    env = _world(tmp_path, "https://github.com/o/demo.git")
    (Path(env["SYNC_WORK"]) / "demo.git" / "config").chmod(0o644)
    r = _run(env)
    assert r.returncode == 1 and "loose-configs=1" in r.stdout


def test_unreadable_tokens_is_an_error_not_a_pass(tmp_path):
    env = _world(tmp_path, "https://github.com/o/demo.git")
    Path(env["SYNC_ENV_FILE"]).write_text("GITHUB_TOKEN=\n")
    r = _run(env)
    assert r.returncode == 1 and "ERROR" in r.stdout


# --- LASTING FIX (2026-11-12 incident): every GITEA repo config is counted too ---------------------------------

def _gitea_repo(env, owner, name, url):
    bare = Path(env["GITEA_REPOS"]) / owner / f"{name}.git"
    bare.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(["git", "--git-dir", str(bare), "remote", "add", "origin", url], check=True)
    return bare


def test_clean_gitea_configs_pass(tmp_path):
    env = _world(tmp_path, "https://github.com/o/demo.git")
    _gitea_repo(env, "windyadmin", "pub", "https://github.com/o/pub.git")
    r = _run(env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "gitea-creds=0" in r.stdout


def test_a_pull_mirror_config_with_a_token_fails_and_is_never_printed(tmp_path):
    env = _world(tmp_path, "https://github.com/o/demo.git")
    _gitea_repo(env, "windyadmin", "mortgage", f"https://oauth2:{GH}@github.com/o/mortgage.git")
    _gitea_repo(env, "windyadmin", "pub", "https://github.com/o/pub.git")
    r = _run(env)
    assert r.returncode == 1 and "gitea-creds=1" in r.stdout
    assert GH not in r.stdout + r.stderr


def test_any_credential_url_fails_even_with_an_unknown_token(tmp_path):
    env = _world(tmp_path, "https://github.com/o/demo.git")
    _gitea_repo(env, "someone", "x", "https://user:" + "notasynctoken" + "@example.com/x.git")
    r = _run(env)
    assert r.returncode == 1 and "gitea-creds=1" in r.stdout


def test_a_sync_token_anywhere_in_a_gitea_config_fails(tmp_path):
    env = _world(tmp_path, "https://github.com/o/demo.git")
    bare = _gitea_repo(env, "windyadmin", "hdr", "https://github.com/o/hdr.git")
    with open(bare / "config", "a") as f:
        f.write(f'[http]\n\textraheader = Authorization: token {WG}\n')
    r = _run(env)
    assert r.returncode == 1 and "gitea-creds=1" in r.stdout
    assert WG not in r.stdout + r.stderr


def test_no_gitea_tree_is_skipped_not_failed(tmp_path):
    env = _world(tmp_path, "https://github.com/o/demo.git")
    env["GITEA_REPOS"] = str(tmp_path / "none")
    r = _run(env)
    assert r.returncode == 0 and "gitea-creds=skipped" in r.stdout


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a 000 folder")
def test_an_unreadable_gitea_tree_fails(tmp_path):
    env = _world(tmp_path, "https://github.com/o/demo.git")
    Path(env["GITEA_REPOS"]).chmod(0)
    try:
        r = _run(env)
    finally:
        Path(env["GITEA_REPOS"]).chmod(0o700)
    assert r.returncode == 1 and "gitea-creds=unreadable" in r.stdout
