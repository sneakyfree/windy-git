#!/usr/bin/env python3
"""Veron's free disk, in Windy Git's uptime beat (Boss 10-28: / hit 96% from lane scratchpads and
temp dirs; when it fills, CI, the sync and every lane's builds stop).

  disk free: 5.3% (191 GB of 3600 GB) on /
  disk: ok                                   <- the healthy line (windy-job --expect)
  disk: WARN under 10% free (WARN to Boss)   <- windy-uptime's heartbeat check alerts on it

Reads only. PATHS can name more mount points (space separated); every one must be ok.
"""

from __future__ import annotations

import os
import shutil
import sys

PATHS = os.environ.get("DISK_FREE_PATHS", "/").split()
WARN_PCT = float(os.environ.get("DISK_FREE_WARN_PCT", "10"))


def check(paths=PATHS, usage=shutil.disk_usage, warn_pct=WARN_PCT) -> list[str]:
    lines, low = [], []
    for p in paths:
        u = usage(p)
        pct = 100.0 * u.free / u.total
        lines.append(f"disk free: {pct:.1f}% ({u.free // 10**9} GB of {u.total // 10**9} GB) on {p}")
        if pct < warn_pct:
            low.append(p)
    lines.append(f"disk: WARN under {warn_pct:g}% free on {', '.join(low)} (WARN to Boss)" if low else "disk: ok")
    return lines


if __name__ == "__main__":
    print("\n".join(check()))
    sys.exit(0)
