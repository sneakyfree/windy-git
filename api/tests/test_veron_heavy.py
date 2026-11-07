"""deploy/veron-heavy: the fleet-wide semaphore for heavy jobs (Boss's VERON LOAD RULE + the 11-05 caps).

The behaviour is proved by the shell suite next to the script (private temp dir, fake pressure and loadavg files):
slot counting, IO and LOAD gates that WAIT, nice/ionice, worker caps, timeout, SIGKILL release, privacy. This file runs it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

DIR = Path(__file__).resolve().parents[2] / "deploy" / "veron-heavy"
NEEDS = ("bash", "flock", "nice", "ionice", "timeout", "logger")


@pytest.mark.skipif(any(shutil.which(t) is None for t in NEEDS), reason="needs util-linux tools")
def test_the_shell_suite_passes():
    r = subprocess.run(["bash", str(DIR / "test_veron_heavy.sh"), str(DIR / "veron-heavy")],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-1500:]
    assert "failed 0" in r.stdout.splitlines()[-1]


def test_the_script_pins_the_ruled_numbers():
    s = (DIR / "veron-heavy").read_text()
    assert 'LOAD_MAX=${VERON_HEAVY_LOAD_MAX:-48}' in s and 'IO_MAX=${VERON_HEAVY_IO_MAX:-30}' in s
    assert '"$ld" -ge "$LOAD_MAX"' in s and '"$p" -ge "$IO_MAX"' in s            # >=, not >
    assert "nice -n 10" in s and "ionice -c2 -n7" in s
    assert 'WORKERS=${VERON_HEAVY_WORKERS:-2}' in s and 'MAKEFLAGS="-j$WORKERS"' in s
    assert "JEST_MAX_WORKERS" in s and "PYTEST_XDIST_AUTO_NUM_WORKERS" in s and "PYTEST_XDIST_WORKERS" in s
