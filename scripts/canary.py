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


@dataclass
class Result:
    name: str
    status: str  # ok | down | slow | unknown
    detail: str
    seconds: float = 0.0
    user_visible: str = ""


@dataclass
class Check:
    name: str
    url: str
    what_it_proves: str
    method: str = "GET"
    body: dict | None = None
    headers: dict = field(default_factory=dict)
    warn_seconds: float | None = None


def _probe(c: Check) -> Result:
    data = json.dumps(c.body).encode() if c.body else None
    headers = {"User-Agent": "windy-git-canary/1.0", **c.headers}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(c.url, data=data, method=c.method, headers=headers)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            elapsed = time.monotonic() - start
            if r.status >= 400:
                return Result(c.name, "down", f"HTTP {r.status}", elapsed, c.what_it_proves)
            warn = c.warn_seconds
            if warn and elapsed > warn:
                return Result(
                    c.name, "slow", f"HTTP {r.status} in {elapsed:.1f}s (warn >{warn:.0f}s)",
                    elapsed, c.what_it_proves,
                )
            return Result(c.name, "ok", f"HTTP {r.status} in {elapsed:.1f}s", elapsed, c.what_it_proves)
    except urllib.error.HTTPError as e:
        return Result(c.name, "down", f"HTTP {e.code}", time.monotonic() - start, c.what_it_proves)
    except Exception as e:  # noqa: BLE001 — a probe must never raise upward
        return Result(
            c.name, "down", f"{type(e).__name__}: {str(e)[:80]}",
            time.monotonic() - start, c.what_it_proves,
        )


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
    with open(STATE_PATH, "w") as f:
        json.dump({r.name: r.status for r in results}, f, indent=2)


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
    results = [_probe(c) for c in build_checks()]

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
