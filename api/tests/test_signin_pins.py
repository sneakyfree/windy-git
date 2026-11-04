"""scripts/signin_guard.py + docker-compose.yml: the ways into the forge stay shut (Hub's One Windy rows, G1).

Pinned: DISABLE_REGISTRATION, ALLOW_ONLY_EXTERNAL_REGISTRATION, the password form off, passkeys off, OIDC
auto-registration off, account linking `login`, OpenID 1.x sign-in and sign-up off, and `windy` the only ACTIVE
login source, whose discovery URL host is account.windyword.ai. Two halves:
the compose file says it (static), the guard reads the live app.ini + login_source (read-only, hourly)."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("signin_guard", ROOT / "scripts" / "signin_guard.py")
sg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sg)

GOOD_INI = """APP_NAME = Windy Git
RUN_MODE = prod

[service]
DISABLE_REGISTRATION = true
ALLOW_ONLY_EXTERNAL_REGISTRATION = true
ENABLE_PASSWORD_SIGNIN_FORM = false
ENABLE_PASSKEY_AUTHENTICATION = false
REGISTER_EMAIL_CONFIRM = false

[oauth2_client]
ENABLE_AUTO_REGISTRATION = false
ACCOUNT_LINKING = login
USERNAME = email

[openid]
ENABLE_OPENID_SIGNIN = false
ENABLE_OPENID_SIGNUP = false

[security]
INTERNAL_TOKEN = not-a-real-token
"""
GOOD_ROWS = [{"id": 1, "type": 6, "name": "windy", "is_active": True, "host": "account.windyword.ai"}]


def _run(ini=GOOD_INI, rows=GOOD_ROWS):
    return sg.run(lambda: ini, lambda: rows)


def _flip(ini: str, key: str, new: str | None) -> str:
    """Set `key` to `new` in the ini text (None removes the line)."""
    out = []
    for line in ini.splitlines():
        if re.match(rf"{key}\s*=", line):
            if new is not None:
                out.append(f"{key} = {new}")
            continue
        out.append(line)
    return "\n".join(out) + "\n"


# ---- the compose file says it ------------------------------------------------------------------

def _compose_env() -> dict[str, str]:
    env = {}
    for m in re.finditer(r'^\s+GITEA__(\w+?)__(\w+):\s*"?([^"\n#]*?)"?\s*(?:#.*)?$',
                         (ROOT / "docker-compose.yml").read_text(), re.M):
        env[f"{m.group(1)}.{m.group(2)}"] = m.group(3).strip()
    return env


def test_docker_compose_declares_every_pin_with_the_pinned_value():
    env = _compose_env()
    for sec, key, want in sg.PINS:
        assert env.get(f"{sec}.{key}") == want, f"docker-compose.yml: GITEA__{sec}__{key} must be {want!r}"


def test_the_pins_are_exactly_these_eight():
    """Adding a pin is fine; REMOVING or loosening one must be a deliberate edit of this test."""
    assert sg.PINS == [
        ("service", "DISABLE_REGISTRATION", "true"),
        ("service", "ALLOW_ONLY_EXTERNAL_REGISTRATION", "true"),
        ("service", "ENABLE_PASSWORD_SIGNIN_FORM", "false"),
        ("service", "ENABLE_PASSKEY_AUTHENTICATION", "false"),
        ("oauth2_client", "ENABLE_AUTO_REGISTRATION", "false"),
        ("oauth2_client", "ACCOUNT_LINKING", "login"),
        ("openid", "ENABLE_OPENID_SIGNIN", "false"),
        ("openid", "ENABLE_OPENID_SIGNUP", "false"),
    ]
    assert sg.SOURCE_NAME == "windy" and sg.OAUTH2_TYPE == 6 and sg.SOURCE_HOST == "account.windyword.ai"


# ---- the live app.ini ---------------------------------------------------------------------------

def test_a_good_config_is_ok_and_names_nothing_secret():
    rc, line = _run()
    assert rc == 0 and line.startswith("signin guard: ok ") and "not-a-real-token" not in line


def test_each_pin_flipped_is_drift_that_names_that_pin_and_only_it():
    flips = {"DISABLE_REGISTRATION": "false", "ALLOW_ONLY_EXTERNAL_REGISTRATION": "false",
             "ENABLE_PASSWORD_SIGNIN_FORM": "true", "ENABLE_PASSKEY_AUTHENTICATION": "true",
             "ENABLE_AUTO_REGISTRATION": "true", "ACCOUNT_LINKING": "auto",
             "ENABLE_OPENID_SIGNIN": "true", "ENABLE_OPENID_SIGNUP": "true"}
    for key, bad in flips.items():
        rc, line = _run(_flip(GOOD_INI, key, bad))
        assert rc == 1 and line.startswith("signin guard: DRIFT ") and f".{key}={bad}" in line, (key, line)
        assert line.count("(want ") == 1, (key, line)


def test_each_pin_missing_is_drift_not_a_default_we_guess():
    for _sec, key, _want in sg.PINS:
        rc, line = _run(_flip(GOOD_INI, key, None))
        assert rc == 1 and f".{key}=absent" in line, (key, line)


def test_a_pin_in_the_wrong_section_does_not_count():
    moved = _flip(GOOD_INI, "DISABLE_REGISTRATION", None) + "\n[server]\nDISABLE_REGISTRATION = true\n"
    rc, line = _run(moved)
    assert rc == 1 and "service.DISABLE_REGISTRATION=absent" in line


def test_values_are_compared_case_and_space_insensitively_like_gitea_reads_them():
    rc, _ = _run(_flip(GOOD_INI, "DISABLE_REGISTRATION", "  TRUE  "))
    assert rc == 0


def test_the_top_level_keys_before_any_section_parse():
    assert sg.read_ini(GOOD_INI).get("__root__", "APP_NAME") == "Windy Git"


# ---- the login sources --------------------------------------------------------------------------

def test_login_sources_exactly_one_active_and_it_is_windy_oauth2():
    def r(rows):
        return _run(rows=rows)
    assert r(GOOD_ROWS)[0] == 0
    assert r([])[0] == 1 and "active login sources=0" in r([])[1]
    two = GOOD_ROWS + [{"id": 2, "type": 6, "name": "github", "is_active": True, "host": "github.com"}]
    assert r(two)[0] == 1 and "active login sources=2" in r(two)[1]
    other = [{"id": 1, "type": 6, "name": "other", "is_active": True, "host": "account.windyword.ai"}]
    assert r(other)[0] == 1 and "name='other'" in r(other)[1]
    ldap = [{"id": 1, "type": 2, "name": "windy", "is_active": True, "host": "account.windyword.ai"}]
    assert r(ldap)[0] == 1 and "type=2" in r(ldap)[1]
    assert r(GOOD_ROWS + [{"id": 2, "type": 2, "name": "old-ldap", "is_active": False}])[0] == 0   # inactive extras are fine
    assert r([{"id": 1, "type": 6, "name": "windy", "is_active": False, "host": "account.windyword.ai"}])[0] == 1   # windy off


def test_the_one_door_cannot_be_repointed_at_another_provider():
    """Hub 11-04: a `windy` OAuth2 source whose discovery URL was edited to another host passes every other check."""
    def with_host(h):
        return [{"id": 1, "type": 6, "name": "windy", "is_active": True, "host": h}]
    assert _run(rows=with_host("account.windyword.ai"))[0] == 0
    rc, line = _run(rows=with_host("evil.example.com"))
    assert rc == 1 and "discovery host=evil.example.com (want account.windyword.ai)" in line
    rc, line = _run(rows=with_host(None))
    assert rc == 1 and "discovery host=none" in line
    for trick in ("account.windyword.ai.evil.com", "evilaccount.windyword.ai", "x.account.windyword.ai"):
        assert _run(rows=with_host(trick))[0] == 1, trick                  # prefix / suffix tricks are not the host
    rc, line = _run(rows=with_host("Account.WindyWord.ai"))                 # exact match, as the SQL gives it
    assert rc == 1
    rc, line = _run(rows=with_host("tok:secret@evil.com"))                   # userinfo is never echoed
    assert rc == 1 and "userinfo-in-url" in line and "secret" not in line and "tok" not in line


def test_the_sql_never_selects_the_secret_bearing_cfg_whole():
    src = (ROOT / "scripts" / "signin_guard.py").read_text()
    q = src[src.index("q = ("):src.index("    out = subprocess.run(")]
    assert q.count("cfg") == 1 and "substring(cfg::json->>'OpenIDConnectAutoDiscoveryURL' from '^https?://([^/:?#]+)')" in q
    assert "select *" not in q.lower() and "t.cfg" not in q and ", cfg" not in q and "cfg," not in q


def test_unreadable_is_never_green():
    def boom():
        raise OSError("denied")
    rc, line = sg.run(lambda: GOOD_INI, boom)
    assert rc == 2 and line.startswith("signin guard: UNREADABLE login sources")
    rc, line = sg.run(boom, lambda: GOOD_ROWS)
    assert rc == 2 and line.startswith("signin guard: UNREADABLE app.ini")
    rc, line = sg.run(lambda: "not [an ini", lambda: GOOD_ROWS)
    assert rc == 2 and "UNREADABLE app.ini" in line


# ---- read-only, and wired the way red_main is -----------------------------------------------------

def test_the_guard_only_reads():
    src = (ROOT / "scripts" / "signin_guard.py").read_text()
    code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
    sql = code[code.index("q = ("):code.index("    out = subprocess.run(")]
    assert sql.lstrip().startswith("q = (") and "select coalesce(json_agg(t)" in sql
    assert not re.search(r"\b(insert|update|delete|drop|alter|truncate|grant)\b\s", sql, re.I)
    assert code.count("open(") == 1 and "open(APP_INI) as f" in code    # the only open() is the app.ini read (default mode r)
    assert ".write" not in code and "os.remove" not in code and "shutil" not in code


def test_the_service_heartbeat_expects_ok_and_not_drift_or_unreadable():
    unit = (ROOT / "deploy" / "systemd" / "windygit-signin-guard.service").read_text()
    pattern = re.search(r'--expect "([^"]+)"', unit).group(1)
    assert "\\" not in pattern
    expect = re.compile(pattern)
    ok = _run()[1]
    assert expect.search(ok)
    assert not expect.search(_run(_flip(GOOD_INI, "DISABLE_REGISTRATION", "false"))[1])
    assert not expect.search("signin guard: UNREADABLE app.ini (OSError)")
    assert "/srv/windygit/src/scripts/signin_guard.py" in unit and "--owner 13" in unit


def test_the_timer_runs_it_hourly():
    timer = (ROOT / "deploy" / "systemd" / "windygit-signin-guard.timer").read_text()
    assert "OnCalendar=*-*-* *:23:00" in timer and "Persistent=true" in timer
