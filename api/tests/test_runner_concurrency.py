"""deploy/runner: Veron runs at most TWO CI jobs at once (Boss 10-27 20:19Z: load 37-56 on 24 cores)."""

from __future__ import annotations

from pathlib import Path

import yaml

RUNNER = Path(__file__).resolve().parents[2] / "deploy" / "runner"


def test_a_plain_compose_up_starts_exactly_two_runners_at_capacity_one():
    services = yaml.safe_load((RUNNER / "docker-compose.yml").read_text())["services"]
    runners = {n: s for n, s in services.items()
               if (n == "runner" or n.startswith("runner-")) and n != "runner-canary"}
    default = sorted(n for n, s in runners.items() if not s.get("profiles"))
    assert default == ["runner", "runner-2"], default
    extra = sorted(n for n, s in runners.items() if s.get("profiles"))
    assert extra == ["runner-3", "runner-4", "runner-5", "runner-6"], extra
    assert all(runners[n]["profiles"] == ["extra-runners"] for n in extra)
    cfg = yaml.safe_load((RUNNER / "config.yaml").read_text())
    assert cfg["runner"]["capacity"] == 1, "capacity > 1 would multiply the cap (and share act's cache)"


def test_the_canary_runner_is_outside_the_cap_and_serves_only_the_canary():
    """Boss 10-28 (B): the login canary must never wait behind builds, and nothing else may use its runner."""
    services = yaml.safe_load((RUNNER / "docker-compose.yml").read_text())["services"]
    c = services["runner-canary"]
    assert not c.get("profiles"), "it starts by default"
    assert "./config-canary.yaml:/config.yaml:ro" in c["volumes"]
    assert c["environment"]["GITEA_RUNNER_NAME"] == "veron-1-canary"
    cfg = yaml.safe_load((RUNNER / "config-canary.yaml").read_text())
    assert [lab.split(":", 1)[0] for lab in cfg["runner"]["labels"]] == ["canary"]
    assert cfg["runner"]["capacity"] == 1
    build = dict(yaml.safe_load((RUNNER / "config.yaml").read_text())["container"])
    canary = dict(cfg["container"])
    assert canary.pop("valid_volumes") == [], "the canary mounts nothing (Hub #95 LOW)"
    build.pop("valid_volumes")
    assert canary == build, "otherwise the same container settings as the build runners"
    wf = yaml.safe_load((RUNNER.parents[1] / ".gitea" / "workflows" / "canary.yml").read_text())
    assert wf["jobs"]["probe"]["runs-on"] == "canary"
    main_labels = [lab.split(":", 1)[0] for lab in yaml.safe_load((RUNNER / "config.yaml").read_text())["runner"]["labels"]]
    assert "canary" not in main_labels, "the build runners must not take canary jobs either"


def test_only_canary_yml_may_run_on_the_canary_runner():
    """Hub #95 LOW: the canary runner is outside the cap, so any other workflow on it would jump the
    CI queue. It is registered to the windy-git repo, so windy-git's own workflows are all that can
    reach it."""
    users = []
    for wf in sorted((RUNNER.parents[1] / ".gitea" / "workflows").glob("*.y*ml")):
        for job in (yaml.safe_load(wf.read_text()).get("jobs") or {}).values():
            labels = job.get("runs-on")
            labels = labels if isinstance(labels, list) else [labels]
            if "canary" in labels:
                users.append(wf.name)
    assert users == ["canary.yml"], users
