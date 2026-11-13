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
    # Test-mode keys and webhook signing secrets are still credentials: a sandbox sk_test_ sat in
    # windy-pro-mobile's docs from 03-01 because only live keys had a shape (Boss, 10-27).
    # pk_ (publishable) keys are public by design: no shape.
    ("stripe test key", re.compile(r"\b[rs]k_test_[A-Za-z0-9]{20,}")),
    ("stripe webhook secret", re.compile(r"\bwhsec_[A-Za-z0-9]{24,}")),
    ("google api key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])")),
    # Twilio (Windy Text 10-01: a live auth token sat in test files for months). An auth token
    # is a bare 32-hex with no prefix, so it is only caught when ASSIGNED to a secret-ish name.
    ("twilio sid/api key", re.compile(r"\b(?:AC|SK)[0-9a-f]{32}\b")),
    ("32-hex secret assignment", re.compile(
        r"(?i)\b[a-z0-9_.-]*(?:token|secret|key|password)[a-z0-9_.-]*[\"']?\s*[:=]\s*[\"']?(?P<v>(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f]))")),
    ("pypi token", re.compile(r"\bpypi-AgE[A-Za-z0-9_-]{50,}")),
    # Cloudflare (Boss 11-06: a cfat_ account API token VALUE sat in kit-army-config #632 and nothing flagged it).
    # Prefixed formats: cfut_ = user API token, cfat_ = account API token, cfk_ = global API key; each is the
    # prefix + 40 base62 + an 8-char checksum (53 chars for cfut_/cfat_). {32,} keeps it a superset of length drift.
    ("cloudflare api token", re.compile(r"(?<![A-Za-z0-9_])cf(?:ut|at|k)_[A-Za-z0-9]{32,}(?![A-Za-z0-9_])")),
    # The older Origin CA key: v1.0-<24 hex>-<146 hex>.
    ("cloudflare origin ca key", re.compile(r"(?<![A-Za-z0-9])v1\.0-[0-9a-f]{24}-[0-9a-f]{100,}")),
    # Legacy unprefixed Cloudflare credentials: a 40-char API token or the 37-hex Global API key, only when
    # ASSIGNED to a cloudflare/CF-named token/key/secret (bare, they look like any hash).
    ("cloudflare legacy credential assignment", re.compile(
        r"(?i)\b[a-z0-9_.-]*(?:cloudflare|(?<![a-z0-9])cf(?![a-z0-9]))[a-z0-9_.-]*(?:token|key|secret)[a-z0-9_.-]*[\"']?\s*[:=]\s*[\"']?"
        r"(?P<v>[0-9a-f]{37}(?![A-Za-z0-9_-])|[A-Za-z0-9_-]{40}(?![A-Za-z0-9_-]))")),
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")),
]

# git grep -E (POSIX ERE) prefilter: cheap superset of PATTERNS.
PREFILTER = ("[0-9]{8,10}:[A-Za-z0-9_-]{35}|gh[pousr]_[A-Za-z0-9]{36}|github_pat_|(AKIA|ASIA)[0-9A-Z]{16}"
             "|xox[abprs]-|sk-ant-|sk-[A-Za-z0-9_-]{32}|sk-proj-|[rs]k_live_|[rs]k_test_|whsec_|AIza[0-9A-Za-z_-]{35}"
             "|-----BEGIN [A-Z ]*PRIVATE KEY-----|(AC|SK)[0-9a-f]{32}|[0-9a-fA-F]{32}|pypi-AgE"
             "|cf(ut|at|k)_[A-Za-z0-9]{32}|v1\\.0-[0-9a-f]{24}-|[Cc][Ll][Oo][Uu][Dd][Ff][Ll][Aa][Rr][Ee]|[Cc][Ff][_-]")


def h8(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()[:8]


def find(text: str) -> list[tuple[str, str]]:
    """[(kind, hash8)] for every secret-shaped string in `text`. Values never leave."""
    out = []
    for kind, rx in PATTERNS:
        for m in rx.finditer(text):
            out.append((kind, h8(m.group('v') if 'v' in rx.groupindex else m.group(0))))
    return out
