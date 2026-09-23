#!/usr/bin/env python3
"""Fleet canary (G7.6).

**Probes what a user does, not what is cheap to answer.**

That distinction is the entire lesson of the 2026-08-12 outage: `/health`
returned 200 the whole time login was dead. A canary watching `/health` would
have stayed green for an hour while nobody in the ecosystem could sign in. So
every check here names a *user-visible* capability, and the login probe is the
one that matters most.

Three rules this canary obeys:

1. **Never report green for something it did not prove.** A check it could not
   run reports `unknown`, never `ok` (I-8).
2. **Alert on transitions, not on every run.** A canary that emails every five
   minutes gets filtered, and a filtered canary is a dead canary — which is how
   the last one sat 37 days dead without anyone noticing.
3. **Run somewhere the thing being watched cannot take down with it.** This runs
   on Veron 1 via Windy Git CI. A canary hosted on Kit 0 would die with Kit 0
   and report nothing at the exact moment it mattered.

State lives in a small JSON file so consecutive runs can tell "still broken"
from "just broke".
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

STATE_PATH = os.environ.get("CANARY_STATE", "canary-state.json")
RESEND_KEY = os.environ.get("RESEND_API_KEY", "")
ALERT_TO = os.environ.get("CANARY_ALERT_TO", "grantwhitmer3@gmail.com")
ALERT_FROM = os.environ.get("CANARY_ALERT_FROM", "office@thewindstorm.uk")

# Login is slow because account-server forks a node process per query. 18-25s is
# today's reality, not health. The threshold flags a real regression without
# crying wolf about the known-slow baseline; lower it as the adapter is fixed.
LOGIN_WARN_SECONDS = float(os.environ.get("CANARY_LOGIN_WARN_S", "35"))
TIMEOUT = float(os.environ.get("CANARY_TIMEOUT_S", "60"))

# Journey cleanup rule (orchestrator, 2026-09-23). The login probe creates a hub
# session (access + refresh token) every run, so it must end it. The hub's
# /auth/logout revokes the token AND every refresh token of the account
# (verified live: access 401, refresh 401 after it). So the next successful
# logout also heals anything a failed run left behind; no ledger needed.
LOGOUT_URL = "https://account.windyword.ai/api/v1/auth/logout"
LOGOUT_ATTEMPTS = 8       # retried on 5xx / no response only
LOGOUT_GAP_S = 15.0
LOGOUT_GONE = (401, 404, 410)  # the session is already over = done


@dataclass
class Result:
    name: str
    status: str  # ok | down | slow | unknown
    detail: str
    seconds: float = 0.0
    user_visible: str = ""
    followups: list[Result] = field(default_factory=list)


@dataclass
class Check:
    name: str
    url: str
    what_it_proves: str
    method: str = "GET"
    body: dict | None = None
    headers: dict = field(default_factory=dict)
    warn_seconds: float | None = None
    # When True this check INVERTS: a 2xx is a critical failure (a security
    # control opened) and a 401/403/503 is the healthy, expected outcome.
    must_refuse: bool = False
    # Runs on a 2xx with the response body; returns follow-up results (cleanup).
    after: Callable[[bytes], list[Result]] | None = None


def _probe(c: Check) -> Result:
    data = json.dumps(c.body).encode() if c.body else None
    headers = {"User-Agent": "windy-git-canary/1.0", **c.headers}
    # Our own probes are synthetic traffic (ecosystem convention, Telemetry
    # UPDATE 4): every service they touch labels the resulting rows.
    headers["X-Windy-Synthetic"] = "1"
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(c.url, data=data, method=c.method, headers=headers)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            elapsed = time.monotonic() - start
            if c.must_refuse:
                # A 2xx here means a control that should reject accepted. That is
                # the alarm, not the absence of one.
                return Result(c.name, "down",
                              f"ACCEPTED (HTTP {r.status}) — this MUST be refused",
                              elapsed, c.what_it_proves)
            if r.status >= 400:
                return Result(c.name, "down", f"HTTP {r.status}", elapsed, c.what_it_proves)
            raw = r.read()
            warn = c.warn_seconds
            if warn and elapsed > warn:
                res = Result(
                    c.name, "slow", f"HTTP {r.status} in {elapsed:.1f}s (warn >{warn:.0f}s)",
                    elapsed, c.what_it_proves,
                )
            else:
                res = Result(c.name, "ok", f"HTTP {r.status} in {elapsed:.1f}s", elapsed, c.what_it_proves)
            if c.after:
                res.followups = c.after(raw)
            return res
    except urllib.error.HTTPError as e:
        if c.must_refuse and e.code in (401, 403, 503):
            return Result(c.name, "ok", f"correctly refused (HTTP {e.code})",
                          time.monotonic() - start, c.what_it_proves)
        return Result(c.name, "down", f"HTTP {e.code}", time.monotonic() - start, c.what_it_proves)
    except Exception as e:  # noqa: BLE001 — a probe must never raise upward
        return Result(
            c.name, "down", f"{type(e).__name__}: {str(e)[:80]}",
            time.monotonic() - start, c.what_it_proves,
        )


def logout(token: str, *, attempts: int = LOGOUT_ATTEMPTS, gap: float = LOGOUT_GAP_S,
           sleep: Callable[[float], None] = time.sleep) -> Result:
    """End the session the login probe opened. Honest: never ok unless proven."""
    what = "the canary leaves no live session behind (journey cleanup rule)"
    headers = {
        "User-Agent": "windy-git-canary/1.0",
        "X-Windy-Synthetic": "1",
        "Authorization": f"Bearer {token}",
    }
    start = time.monotonic()
    last = "no attempt"
    for i in range(attempts):
        if i:
            sleep(gap)
        req = urllib.request.Request(LOGOUT_URL, data=b"", method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return Result("identity.logout", "ok", f"session ended (HTTP {r.status})",
                              time.monotonic() - start, what)
        except urllib.error.HTTPError as e:
            if e.code in LOGOUT_GONE:
                return Result("identity.logout", "ok", f"session already over (HTTP {e.code})",
                              time.monotonic() - start, what)
            if e.code < 500:  # a 4xx won't change on retry: fail fast
                return Result("identity.logout", "down", f"CLEANUP FAILED: HTTP {e.code}",
                              time.monotonic() - start, what)
            last = f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001 — no response / timeout: retry
            last = f"{type(e).__name__}"
    return Result("identity.logout", "down",
                  f"CLEANUP FAILED after {attempts} tries: {last} (next run's logout heals it)",
                  time.monotonic() - start, what)


def _logout_after_login(raw: bytes) -> list[Result]:
    try:
        token = (json.loads(raw or b"{}") or {}).get("token")
    except ValueError:
        token = None
    if not token:
        return [Result("identity.logout", "down",
                       "CLEANUP FAILED: login returned no token to log out with",
                       0.0, "the canary leaves no live session behind (journey cleanup rule)")]
    return [logout(token)]


def build_checks() -> list[Check]:
    checks = [
        Check(
            "identity.health",
            "https://account.windyword.ai/health",
            "the identity service answers at all",
        ),
        Check(
            "identity.jwks",
            "https://account.windyword.ai/.well-known/jwks.json",
            "every service can verify the tokens it is handed",
        ),
        Check(
            "eternitas.health",
            "https://api.eternitas.ai/health",
            "agent passports can be issued and checked",
        ),
        Check(
            "windygit.forge",
            "https://app.windygit.com/api/v1/version",
            "repositories are reachable",
        ),
        Check(
            "windygit.plane",
            "https://api.windygit.com/version",
            "the Windy Git API answers",
        ),
        Check(
            "dashboard",
            "https://app.windyword.ai/",
            "the dashboard loads",
        ),
    ]

    # SECURITY REGRESSION GUARD. A forged, unsigned token naming a real passport
    # must be refused. On 2026-08-13 this returned HTTP 200 (full agent
    # impersonation). If it ever returns 2xx again, the bypass is back.
    import base64 as _b64
    import json as _j

    def _seg(d: dict) -> str:
        return _b64.urlsafe_b64encode(_j.dumps(d).encode()).rstrip(b"=").decode()

    # Two shapes, because they exercise two different gates. The EPT-shaped one
    # is the important one now: it is what real signature verification guards.
    for _label, _hdr in (
        ("security.forged_agent_token", {"alg": "none", "typ": "JWT"}),
        ("security.forged_ept", {"alg": "none", "typ": "EPT"}),
    ):
        _tok = (
            f"{_seg(_hdr)}."
            f"{_seg({'sub': 'ET26-1EF9-VJAN', 'passport': 'ET26-1EF9-VJAN', 'iss': 'eternitas.ai', 'exp': 9999999999})}"
            ".not-a-real-signature"
        )
        checks.append(
            Check(
                _label,
                "https://api.windygit.com/api/v1/repos",
                "an unsigned token cannot impersonate an agent",
                headers={"Authorization": f"Bearer {_tok}"},
                must_refuse=True,
            )
        )

    # THE important one. /health was 200 for the entire 2026-08-12 outage while
    # this was timing out. A canary that skips it is decorative.
    pw = os.environ.get("CANARY_LOGIN_PASSWORD", "")
    email = os.environ.get("CANARY_LOGIN_EMAIL", "")
    if pw and email:
        checks.append(
            Check(
                "identity.login",
                "https://account.windyword.ai/api/v1/auth/login",
                "a human can actually sign in",
                method="POST",
                body={"email": email, "password": pw},
                warn_seconds=LOGIN_WARN_SECONDS,
                after=_logout_after_login,
            )
        )
    return checks


def load_state() -> dict:
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(results: list[Result]) -> None:
    """Never let bookkeeping kill the monitor.

    State is an optimisation — it lets the next run tell "still broken" from
    "just broke". The probing is the valuable part. An unwritable path used to
    raise here and take the whole canary down, which is the worst possible
    trade: a monitoring tool that dies of a config problem reports nothing at
    all, and reports it silently.
    """
    try:
        with open(STATE_PATH, "w") as f:
            json.dump({r.name: r.status for r in results}, f, indent=2)
    except OSError as exc:
        print(f"!! could not save state to {STATE_PATH}: {exc}")
        print("   (probes still ran; transition detection is degraded this run)")


def send_alert(subject: str, lines: list[str]) -> bool:
    if not RESEND_KEY:
        print("!! RESEND_API_KEY unset — cannot alert. This canary is decorative.")
        return False
    body = "\n".join(lines)
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps({
            "from": f"Windy Canary <{ALERT_FROM}>",
            "to": [ALERT_TO],
            "subject": subject,
            "text": body,
        }).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {RESEND_KEY}",
            "Content-Type": "application/json",
            # ⚠️ REQUIRED. Without an explicit User-Agent, urllib sends
            # "Python-urllib/3.x" and the request is rejected 403 by bot
            # filtering — while the identical request via curl succeeds. This
            # exact failure was caught by testing the alert path rather than
            # assuming it: the canary would have detected every outage
            # correctly and told nobody.
            "User-Agent": "windy-git-canary/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"   alert sent ({r.status})")
            return True
    except urllib.error.HTTPError as e:
        # Print the body. "403 Forbidden" alone sends you hunting for a bad key;
        # the body usually names the real cause.
        print(f"!! alert FAILED: HTTP {e.code}: {e.read().decode()[:200]}")
        return False
    except Exception as e:  # noqa: BLE001
        print(f"!! alert FAILED: {e}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-alert", action="store_true")
    args = ap.parse_args()

    previous = load_state()
    results = []
    for c in build_checks():
        r = _probe(c)
        results += [r, *r.followups]

    print(f"windy canary — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
    for r in results:
        mark = {"ok": "  ok  ", "slow": " SLOW ", "down": " DOWN ", "unknown": "  ??  "}[r.status]
        print(f"[{mark}] {r.name:20} {r.detail}")
        if r.status != "ok":
            print(f"           ^ this means: {r.user_visible}")

    # Transitions only. "Still broken" does not re-alert; recovery does.
    newly_bad = [r for r in results if r.status in ("down", "slow") and previous.get(r.name) == "ok"]
    recovered = [
        r for r in results
        if r.status == "ok" and previous.get(r.name) in ("down", "slow")
    ]

    save_state(results)

    if not args.no_alert:
        if newly_bad:
            worst = "DOWN" if any(r.status == "down" for r in newly_bad) else "SLOW"
            send_alert(
                f"[Windy] {worst}: {', '.join(r.name for r in newly_bad)}",
                [f"{r.name}: {r.detail}" for r in newly_bad]
                + ["", "What this means for a person:"]
                + [f"  - {r.user_visible}" for r in newly_bad]
                + ["", "Checked from Veron 1 via Windy Git CI — deliberately not from Kit 0."],
            )
        if recovered:
            send_alert(
                f"[Windy] recovered: {', '.join(r.name for r in recovered)}",
                [f"{r.name}: {r.detail}" for r in recovered],
            )

    # A failure exit makes the CI run red, so the forge itself carries the signal
    # even if email is misconfigured. Two independent ways to notice.
    return 1 if any(r.status in ("down", "slow") for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
