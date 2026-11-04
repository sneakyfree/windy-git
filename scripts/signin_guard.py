#!/usr/bin/env python3
"""Sign-in guard (Windy Git, Hub's One Windy rows G1): the ways INTO the forge stay shut.

Windy Git signs in through ONE door, the "windy" OIDC source. Registration, the password form, passkeys and
OIDC auto-registration are off, account linking is `login`. docker-compose.yml SAYS so, but the compose note
itself warns that env-to-ini SETS and never UNSETS: what counts is the live app.ini and the live login sources.
So, read only:

  1. /srv/windygit/git/gitea/conf/app.ini (root-read; only the pinned keys are looked at, nothing else is printed)
  2. the login_source table: exactly ONE active source, named `windy`, OAuth2 (type 6), whose OpenID discovery
     URL host is account.windyword.ai (so the one door cannot be re-pointed at another provider; the host is
     extracted IN SQL and only the host is ever read: `cfg` holds the client secret and is never selected whole)

A pinned key that is missing counts as drift (Gitea's default would apply, and we do not guess it).
Output for windy-job --expect:   "signin guard: ok (...)"   or   "signin guard: DRIFT <pins>"   or
"signin guard: UNREADABLE <why>"  (never green unproven). Exit 0 / 1 / 2. Nothing is written anywhere.

  sudo python3 scripts/signin_guard.py          (a systemd timer runs it hourly: deploy/systemd/windygit-signin-guard.*)
"""

from __future__ import annotations

import configparser
import json
import os
import subprocess
import sys

APP_INI = os.environ.get("SIGNIN_APP_INI", "/srv/windygit/git/gitea/conf/app.ini")
OAUTH2_TYPE = 6                      # Gitea's login_source.type for OAuth2
SOURCE_NAME = "windy"
SOURCE_HOST = "account.windyword.ai"   # host of the active source's OpenID discovery URL

# (section, key, required value). The same eight must be in docker-compose.yml (a test pins both).
# OpenID 1.x is a separate sign-in door from OAuth2 (Hub, 11-04): Gitea defaults ENABLE_OPENID_SIGNIN to true.
PINS: list[tuple[str, str, str]] = [
    ("service", "DISABLE_REGISTRATION", "true"),
    ("service", "ALLOW_ONLY_EXTERNAL_REGISTRATION", "true"),
    ("service", "ENABLE_PASSWORD_SIGNIN_FORM", "false"),
    ("service", "ENABLE_PASSKEY_AUTHENTICATION", "false"),
    ("oauth2_client", "ENABLE_AUTO_REGISTRATION", "false"),
    ("oauth2_client", "ACCOUNT_LINKING", "login"),
    ("openid", "ENABLE_OPENID_SIGNIN", "false"),
    ("openid", "ENABLE_OPENID_SIGNUP", "false"),
]


def read_ini(text: str) -> configparser.ConfigParser:
    """app.ini starts with top-level keys (APP_NAME = ...), which configparser needs a section for."""
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str  # type: ignore[assignment,method-assign]  # keys are case-sensitive in Gitea
    cp.read_string("[__root__]\n" + text)
    return cp


def check_settings(cp: configparser.ConfigParser) -> list[str]:
    """The pins that do not hold, as 'section.KEY=<value|absent>' (values of these six keys are not secrets)."""
    bad = []
    for sec, key, want in PINS:
        got = cp.get(sec, key, fallback=None) if cp.has_section(sec) else None
        if got is None or got.strip().lower() != want:
            bad.append(f"{sec}.{key}={'absent' if got is None else got.strip()[:20]} (want {want})")
    return bad


def check_sources(rows: list[dict]) -> list[str]:
    """Exactly one ACTIVE login source, and it is the `windy` OAuth2 one."""
    active = [r for r in rows if r.get("is_active")]
    if len(active) != 1:
        return [f"active login sources={len(active)} (want 1)"]
    r = active[0]
    bad = []
    if r.get("name") != SOURCE_NAME:
        bad.append(f"active login source name={str(r.get('name'))[:30]!r} (want {SOURCE_NAME!r})")
    if r.get("type") != OAUTH2_TYPE:
        bad.append(f"active login source type={r.get('type')} (want {OAUTH2_TYPE} OAuth2)")
    host = r.get("host")
    if host != SOURCE_HOST:
        shown = "none" if not host else ("userinfo-in-url" if "@" in str(host) else str(host)[:60])
        bad.append(f"active login source discovery host={shown} (want {SOURCE_HOST})")
    return bad


def read_sources() -> list[dict]:
    # Only the HOST of the discovery URL leaves SQL. NEVER select cfg whole: it holds the client secret.
    q = ("select coalesce(json_agg(t), '[]'::json) from (select id, type, name, is_active, "
         "substring(cfg::json->>'OpenIDConnectAutoDiscoveryURL' from '^https?://([^/:?#]+)') as host "
         "from login_source) t;")
    out = subprocess.run(
        ["docker", "exec", "-i", "windy-git-db-1", "sh", "-c",
         'psql -U "$POSTGRES_USER" -d gitea -At -v ON_ERROR_STOP=1'],
        input=q, capture_output=True, text=True, check=True, timeout=60).stdout.strip()
    return json.loads(out or "[]")


def read_app_ini() -> str:
    with open(APP_INI) as f:                # read-only
        return f.read()


def run(read_ini_text=read_app_ini, read_rows=read_sources) -> tuple[int, str]:
    try:
        cp = read_ini(read_ini_text())
    except (OSError, configparser.Error) as e:
        return 2, f"signin guard: UNREADABLE app.ini ({type(e).__name__})"
    try:
        rows = read_rows()
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return 2, f"signin guard: UNREADABLE login sources ({type(e).__name__})"
    bad = check_settings(cp) + check_sources(rows)
    if bad:
        return 1, "signin guard: DRIFT " + "; ".join(bad)
    return 0, f"signin guard: ok ({len(PINS)} pins hold, 1 active login source: {SOURCE_NAME} @ {SOURCE_HOST})"


def main() -> int:
    rc, line = run()
    print(line)
    return rc


if __name__ == "__main__":
    sys.exit(main())
