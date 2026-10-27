"""deploy/runner: Veron runs at most TWO CI jobs at once (Boss 10-27 20:19Z: load 37-56 on 24 cores)."""

from __future__ import annotations

from pathlib import Path

import yaml

RUNNER = Path(__file__).resolve().parents[2] / "deploy" / "runner"


def test_a_plain_compose_up_starts_exactly_two_runners_at_capacity_one():
    services = yaml.safe_load((RUNNER / "docker-compose.yml").read_text())["services"]
    runners = {n: s for n, s in services.items() if n == "runner" or n.startswith("runner-")}
    default = sorted(n for n, s in runners.items() if not s.get("profiles"))
    assert default == ["runner", "runner-2"], default
    extra = sorted(n for n, s in runners.items() if s.get("profiles"))
    assert extra == ["runner-3", "runner-4", "runner-5", "runner-6"], extra
    assert all(runners[n]["profiles"] == ["extra-runners"] for n in extra)
    cfg = yaml.safe_load((RUNNER / "config.yaml").read_text())
    assert cfg["runner"]["capacity"] == 1, "capacity > 1 would multiply the cap (and share act's cache)"
