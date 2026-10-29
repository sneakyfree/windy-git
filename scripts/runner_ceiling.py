"""The runner's hard per-job ceiling, read from deploy/runner/config.yaml `runner.timeout` (e.g. "90m").

One source of truth for the bridge's wording and autorerun's classification: a task Gitea stopped
after running the full ceiling was CUT for being too slow or hung, not lost. Falls back to 90 min
when the file is missing or unreadable (the value it had when this was written, 10-29).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parent.parent / "deploy" / "runner" / "config.yaml"
DEFAULT_S = 90 * 60
_UNIT = {"s": 1, "m": 60, "h": 3600}


def ceiling_s(path: Path = CONFIG) -> int:
    try:
        raw = str((yaml.safe_load(path.read_text()) or {})["runner"]["timeout"]).strip()
    except (OSError, KeyError, TypeError, yaml.YAMLError):
        return DEFAULT_S
    m = re.fullmatch(r"(\d+)([smh])", raw)
    return int(m.group(1)) * _UNIT[m.group(2)] if m else DEFAULT_S
