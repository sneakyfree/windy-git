"""The daily Gitea watch (11-07, Russ: staying current must be mechanical): range parsing and the alarms."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import gitea_upstream_watch as w  # noqa: E402

DAY = 86400.0
NOW = 1_800_000_000.0


def iso(t: float) -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def rel(tag: str, age_days: float, pre: bool = False) -> dict:
    return {"tag_name": tag, "prerelease": pre, "draft": False, "published_at": iso(NOW - age_days * DAY)}


def adv(ghsa: str, sev: str, rng: str, patched: str = "", age_days: float = 10) -> dict:
    return {"ghsa_id": ghsa, "severity": sev, "published_at": iso(NOW - age_days * DAY),
            "vulnerabilities": [{"package": {"name": "gitea.dev"}, "vulnerable_version_range": rng,
                                 "patched_versions": patched}]}


def test_ranges_as_gitea_writes_them():
    v = w.parse("1.24.7")
    assert w.covers(">= 1.19.0, <= 28.2.0", v) and w.covers("<= 1.26.4", v) and w.covers("< 1.27.0", v)
    assert not w.covers(">= 1.25.0, < 1.26.3", v) and not w.covers("<= 1.24.6", v)
    assert w.covers("1.24.7", v) and not w.covers("1.26.2", v)          # a bare version means "="
    assert w.covers(">= nonsense", v)                                     # unreadable = assume covered


def test_on_the_newest_release_with_nothing_severe_is_quiet():
    alarm, line = w.check("28.3.0", [rel("v28.3.0", 6), rel("v28.2.0", 20)],
                          [adv("GHSA-a", "high", ">= 1.19.0, <= 28.2.0", "28.3.0"),
                           adv("GHSA-b", "medium", ">=1.27.1")], NOW)
    assert not alarm and "on the newest release" in line and "covering us: 1 (critical 0, high 0, medium 1" in line


def test_a_critical_or_high_covering_us_alarms_only_after_72_hours():
    a = [adv("GHSA-h", "high", "<= 28.2.0", "28.3.0", age_days=2)]
    assert not w.check("28.2.0", [rel("v28.3.0", 2)], a, NOW)[0]
    a[0]["published_at"] = iso(NOW - 4 * DAY)
    alarm, line = w.check("28.2.0", [rel("v28.3.0", 4)], a, NOW)
    assert alarm and line.startswith("ALARM ") and "GHSA-h" in line


def test_a_newer_patch_of_our_minor_alarms_after_30_days_and_pre_releases_never_count():
    assert not w.check("28.2.0", [rel("v28.2.1", 29), rel("v28.3.0-rc1", 1, pre=True)], [], NOW)[0]
    alarm, line = w.check("28.2.0", [rel("v28.2.1", 31), rel("v28.2.2", 3)], [], NOW)
    assert alarm and "patch 28.2.2 out (first newer patch 31 d ago)" in line


def test_a_patched_version_at_or_below_ours_is_not_counted():
    assert "covering us: 0" in w.check("1.24.7", [rel("v1.24.7", 300)],
                                       [adv("GHSA-p", "critical", "<= 1.26.4", "1.24.7")], NOW)[1]


def test_an_unreadable_version_is_an_alarm():
    assert w.check("dev-build", [], [], NOW)[0]
