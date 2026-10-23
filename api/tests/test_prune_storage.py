"""deploy/runner/prune.sh measures the volume dind really uses (10-22: it measured the idle
pre-sysbox volume, so the 60 GB cap and the toolcache cap never fired)."""

from __future__ import annotations

import re
from pathlib import Path

PRUNE = (Path(__file__).resolve().parents[2] / "deploy" / "runner" / "prune.sh").read_text()


def test_no_hardcoded_volume_name():
    assert "windy-git-runner_dind-storage" not in PRUNE


def test_store_comes_from_dinds_own_var_lib_docker_mount_and_unknown_refuses():
    assert re.search(r'STORE=\$\(docker inspect .*\.Destination "/var/lib/docker".*windy-git-runner-dind-1\)', PRUNE)
    assert re.search(r'\[\[ -n "\$STORE" && -d "\$STORE" \]\] \|\| \{ echo "ci storage UNKNOWN', PRUNE)


def test_both_caps_measure_the_store():
    assert 'TC="$STORE/volumes/act-toolcache"' in PRUNE
    assert PRUNE.count('du -s --block-size=1G "$STORE"') == 2
