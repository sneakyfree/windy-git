"""scripts/disk_free.py: under 10% free on any watched mount = WARN to Boss (Boss 10-28)."""

from __future__ import annotations

import importlib.util
from collections import namedtuple
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("disk_free", ROOT / "scripts" / "disk_free.py")
df = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(df)
U = namedtuple("U", "total used free")


def test_ok_at_and_above_the_threshold_warn_below_it():
    at = df.check(["/"], lambda p: U(1000 * 10**9, 900 * 10**9, 100 * 10**9), 10)
    assert at == ["disk free: 10.0% (100 GB of 1000 GB) on /", "disk: ok"]
    low = df.check(["/"], lambda p: U(1000 * 10**9, 901 * 10**9, 99 * 10**9), 10)
    assert low[-1] == "disk: WARN under 10% free on / (WARN to Boss)"


def test_every_watched_mount_must_be_ok():
    sizes = {"/": U(100, 50, 50), "/srv": U(100, 95, 5)}
    out = df.check(["/", "/srv"], lambda p: sizes[p], 10)
    assert out[-1] == "disk: WARN under 10% free on /srv (WARN to Boss)" and len(out) == 3
