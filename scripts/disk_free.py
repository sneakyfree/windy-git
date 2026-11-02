#!/usr/bin/env python3
"""Veron's free disk, in Windy Git's uptime beat (Boss 10-28: / hit 96% from lane scratchpads and
temp dirs; when it fills, CI, the sync and every lane's builds stop). Tiers in GB free, not percent
(Boss 11-02: on a 3.6 TB disk 10% is 360 GB, far too early):

  under 150 GB  LOW       ONE BOARD line when a mount crosses down into it, plus one fleet-say line to Windy Boss
  under  50 GB  CRITICAL  ONE bold BOARD line on that crossing, plus the same fleet-say line
  Each crossing speaks once. Staying in a tier is silent; recovering above it re-arms it. No pages to Grant.

  disk free: 238 GB of 3664 GB (6.5%) on /
  disk: ok                                              <- the healthy line (windy-job --expect)
  disk: LOW under 150 GB free on / (BOARD + Boss)       <- windy-uptime's heartbeat check alerts on it
  disk: CRITICAL under 50 GB free on / (BOARD + Boss)

A crossing is recorded only after its BOARD line was written; a failed fleet-say is retried on the next
run WITHOUT a second BOARD line. Everything else reads only. PATHS can name more mount points
(space separated); the worst one decides the last line.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cancel_superseded as cs  # noqa: E402  (the BOARD line: Windy 0, else the fallback board)

PATHS = os.environ.get("DISK_FREE_PATHS", "/").split()
LOW_GB = float(os.environ.get("DISK_FREE_LOW_GB", "150"))
CRITICAL_GB = float(os.environ.get("DISK_FREE_CRITICAL_GB", "50"))
STATE = Path(os.environ.get("DISK_FREE_STATE", "/var/lib/windygit/disk-free.json"))
FLEET_SAY = os.environ.get("FLEET_SAY", f"/home/{cs.BOARD_USER}/.local/bin/fleet-say")
NAMES = {0: "ok", 1: "LOW", 2: "CRITICAL"}


def tier(free_gb: float, low_gb: float = LOW_GB, critical_gb: float = CRITICAL_GB) -> int:
    return 2 if free_gb < critical_gb else 1 if free_gb < low_gb else 0


def check(paths=PATHS, usage=shutil.disk_usage, low_gb=LOW_GB, critical_gb=CRITICAL_GB):
    """(output lines, {path: (tier, free_gb)}). Pure: reads the disks, posts nothing."""
    lines, tiers = [], {}
    for p in paths:
        u = usage(p)
        free_gb = u.free // 10**9
        lines.append(f"disk free: {free_gb} GB of {u.total // 10**9} GB ({100.0 * u.free / u.total:.1f}%) on {p}")
        tiers[p] = (tier(u.free / 10**9, low_gb, critical_gb), free_gb)
    worst = max((t for t, _ in tiers.values()), default=0)
    if worst:
        limit = critical_gb if worst == 2 else low_gb
        bad = ", ".join(p for p, (t, _) in tiers.items() if t == worst)
        lines.append(f"disk: {NAMES[worst]} under {limit:g} GB free on {bad} (BOARD + Boss)")
    else:
        lines.append("disk: ok")
    return lines, tiers


def say_boss(text: str) -> bool:
    """One line to Windy Boss on the Mac mini (message on stdin). True only on {"success":true}."""
    try:
        r = subprocess.run(["runuser", "-u", cs.BOARD_USER, "--", "timeout", "60", FLEET_SAY,
                            "eth-macmini", "Windy Boss", "-"],
                           input=text + "\n", text=True, capture_output=True, timeout=90)
    except (subprocess.SubprocessError, OSError):
        return False
    return r.returncode == 0 and '"success":true' in r.stdout.replace(" ", "")


def load_state(path: Path = STATE) -> dict:
    try:
        d = json.loads(path.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state: dict, path: Path = STATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".disk-free.")
    with os.fdopen(fd, "w") as f:
        json.dump(state, f)
    os.replace(tmp, path)


def announce(tiers: dict, state: dict, board=cs.board, say=say_boss) -> dict:
    """Speak once per downward crossing; return the new state. state[path] = {"tier": n, "board": bool}
    where "tier" is the tier last announced, "board" says its BOARD line was written (so a failed
    fleet-say retries alone) and "done" that both went out. Moving to a better tier is silent and
    re-arms the worse ones."""
    new = {}
    for p, (t, free_gb) in tiers.items():
        old = state.get(p) if isinstance(state.get(p), dict) else {"tier": 0, "board": True}
        if t < old.get("tier", 0):
            new[p] = {"tier": t, "board": True, "done": True}  # recovered (maybe only partly): re-arms the tiers above
            continue
        if t == 0 or (t == old.get("tier", 0) and old.get("done")):
            new[p] = {"tier": t, "board": True, "done": True}
            continue
        text = f"[AUTOMATED disk-watch] Veron free {free_gb} GB"
        where = f" on {p}" if p != "/" else ""
        stamp = f"{text}{where}: {NAMES[t]}, under {(CRITICAL_GB if t == 2 else LOW_GB):g} GB"
        entry = {"tier": t, "board": old["board"] if t == old.get("tier", 0) else False}
        if not entry["board"]:
            line = f"[Windy Git] {stamp}" if t == 1 else f"[Windy Git] **{stamp}. CRITICAL: CI and the lanes stop when it fills.**"
            entry["board"] = bool(board(line))
        if entry["board"] and say(text + where):
            entry["done"] = True
        new[p] = entry
    return new


def main() -> int:
    lines, tiers = check()
    print("\n".join(lines))
    try:
        save_state(announce(tiers, load_state()))
    except OSError as e:  # the check itself still ran; the heartbeat line above is what windy-uptime reads
        print(f"disk: state not saved ({e.__class__.__name__})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
