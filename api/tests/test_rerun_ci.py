"""scripts/rerun_ci.sh: it rewinds only when it holds the sync's push-loop lock, never while
that loop runs, and not by waiting for an idle sync (passes run back to back; 10-21)."""

from __future__ import annotations

import fcntl
import os
import stat
import subprocess
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _git(*a, cwd=None):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _exe(p: Path, body: str):
    p.write_text(body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def world(tmp_path):
    seed = tmp_path / "seed"
    _git("init", "-q", "-b", "main", str(seed))
    for n in (1, 2):
        (seed / "f").write_text(str(n))
        _git("add", "f", cwd=seed)
        _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", f"c{n}", cwd=seed)
    bare = tmp_path / "demo.git"
    _git("clone", "-q", "--bare", str(seed), str(bare))
    head = _git("--git-dir", str(bare), "rev-parse", "main")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    rewinds = tmp_path / "rewinds"
    _exe(bin_ / "sudo", '#!/bin/sh\nexec "$@"\n')
    # docker exec -u git windy-git-gitea-1 git -C <path> ARGS...  ->  git --git-dir=<bare> ARGS...
    _exe(bin_ / "docker", f'#!/bin/bash\nshift 7\n'
                          f'[ "$1" = update-ref ] && date +%s.%N >> {rewinds}\n'
                          f'exec git --git-dir={bare} "$@"\n')
    # A sync that starts "now" and has pushed GitHub's head back.
    _exe(bin_ / "systemctl", f'#!/bin/bash\ngit --git-dir={bare} update-ref refs/heads/main {head}\n'
                             "awk '{print int($1*1000000)+5000000}' /proc/uptime\n")
    _exe(bin_ / "wgq", "#!/bin/sh\ncat >/dev/null\n")
    work = tmp_path / "work"
    work.mkdir()
    env = {"PATH": f"{bin_}:{os.environ['PATH']}", "WGQ": str(bin_ / "wgq"), "SYNC_WORK": str(work),
           "HOME": str(tmp_path)}
    return {"env": env, "bare": bare, "head": head, "lock": work / ".push.lock", "rewinds": rewinds}


def _run(w, **extra):
    return subprocess.run(["bash", str(ROOT / "scripts/rerun_ci.sh"), "demo", "main", w["head"][:8]],
                          env={**w["env"], **extra}, capture_output=True, text=True, timeout=120)


def _hold(lock: Path, seconds: float):
    fh = open(lock, "w")  # noqa: SIM115 -- held past return; the timer unlocks and closes it
    fcntl.flock(fh, fcntl.LOCK_EX)
    t = threading.Timer(seconds, lambda: (fcntl.flock(fh, fcntl.LOCK_UN), fh.close()))
    t.start()
    return time.time() + seconds


def test_rewinds_only_after_the_push_loop_releases_its_lock(world):
    released = _hold(world["lock"], 1.5)
    r = _run(world)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "rewound demo:main" in r.stdout and "restored by sync" in r.stdout
    assert float(world["rewinds"].read_text().split()[0]) >= released - 0.05   # never inside the loop
    assert _git("--git-dir", str(world["bare"]), "rev-parse", "main") == world["head"]


def test_a_push_loop_that_never_lets_go_is_refused_and_nothing_moves(world):
    _hold(world["lock"], 30)
    r = _run(world, RERUN_LOCK_WAIT="1")
    assert r.returncode == 1 and "refusing: the sync's push loop held its lock for 1 s" in r.stdout
    assert not world["rewinds"].exists()
    assert _git("--git-dir", str(world["bare"]), "rev-parse", "main") == world["head"]


def test_a_busy_sync_no_longer_blocks_the_rewind(world):
    # The old idle-wait read `systemctl show -p ActiveState`; with passes back to back it never
    # saw "inactive". The fake systemctl here answers nothing for ActiveState at all.
    t0 = time.time()
    r = _run(world)
    assert r.returncode == 0 and time.time() - t0 < 30
