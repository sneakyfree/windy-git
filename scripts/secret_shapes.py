"""Secret-shaped strings, shared by secret_guard (bridged repos) and
public_secret_scan (weekly, every public repo). A finding NEVER carries the value:
only its kind and sha256[:8] (house rule 10). Leak hunt 09-24: @Windy_0_bot's
token sat in a public repo's test fixture for five months."""

from __future__ import annotations

import hashlib
import re

# (kind, regex). Order matters only for readability; each match is reported once.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("telegram bot token", re.compile(r"(?<![0-9])[0-9]{8,10}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])")),
    ("github token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82})\b")),
    ("aws access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai key", re.compile(r"\bsk-(?:proj-|svcacct-)?(?!ant-)[A-Za-z0-9_-]{32,}")),
    ("stripe live key", re.compile(r"\b[rs]k_live_[A-Za-z0-9]{20,}")),
    ("google api key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])")),
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")),
]

# git grep -E (POSIX ERE) prefilter: cheap superset of PATTERNS.
PREFILTER = ("[0-9]{8,10}:[A-Za-z0-9_-]{35}|gh[pousr]_[A-Za-z0-9]{36}|github_pat_|(AKIA|ASIA)[0-9A-Z]{16}"
             "|xox[abprs]-|sk-ant-|sk-[A-Za-z0-9_-]{32}|sk-proj-|[rs]k_live_|AIza[0-9A-Za-z_-]{35}"
             "|-----BEGIN [A-Z ]*PRIVATE KEY-----")


def h8(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()[:8]


def find(text: str) -> list[tuple[str, str]]:
    """[(kind, hash8)] for every secret-shaped string in `text`. Values never leave."""
    out = []
    for kind, rx in PATTERNS:
        for m in rx.finditer(text):
            out.append((kind, h8(m.group(0))))
    return out
