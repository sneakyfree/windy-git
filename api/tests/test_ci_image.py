"""deploy/runner: the CI job image is built locally, pinned, never pruned, and has a real
rollback; runner restarts drain instead of killing jobs (10-22, Hub #62)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

RUNNER = Path(__file__).resolve().parents[2] / "deploy" / "runner"
DIGEST = re.compile(r"^FROM catthehacker/ubuntu@sha256:[0-9a-f]{64}$", re.M)


def _default(var: str) -> str:
    m = re.search(rf'{var}:-([^}}"]+)', (RUNNER / "build-ci-image.sh").read_text())
    assert m, f"build-ci-image.sh sets {var}"
    return m.group(1)


def _apt_packages(dockerfile: str) -> list[str]:
    """Every argument of every `apt-get install` (continuation lines joined; flags dropped)."""
    text = dockerfile.replace("\\\n", " ")
    pkgs = []
    for m in re.finditer(r"apt-get\s+install\b([^&;\n]*)", text):
        pkgs += [t for t in m.group(1).split() if not t.startswith("-")]
    return pkgs


def test_every_job_label_runs_the_built_localhost_image():
    labels = yaml.safe_load((RUNNER / "config.yaml").read_text())["runner"]["labels"]
    images = {lab.split(":", 1)[1] for lab in labels}
    tag = _default("CI_IMAGE_TAG")
    assert images == {f"docker://{tag}"}, images
    assert tag.startswith("localhost/"), "a missing local image must never be pulled from Docker Hub"


def test_both_images_pin_the_same_base_by_digest_and_keep_themselves():
    job = (RUNNER / "ci-image" / "Dockerfile").read_text()
    base = (RUNNER / "ci-image" / "Dockerfile.base").read_text()
    assert DIGEST.search(job) and DIGEST.search(base)
    assert DIGEST.search(job).group(0) == DIGEST.search(base).group(0)
    assert 'windy-git.keep="1"' in job and 'windy-git.keep="1"' in base
    assert "apt-get" not in base, "the rollback image is the old image, unchanged"


def _hash_pinned_debs(dockerfile: str) -> set[str]:
    """Local .deb paths the Dockerfile checks with `sha256sum -c` against an ARG whose default
    is a full 64-hex sha256: pinned by content, which is stronger than name=version."""
    shas = {m.group(1) for m in re.finditer(r"^ARG (\w+)=[0-9a-f]{64}$", dockerfile, re.M)}
    text = dockerfile.replace("\\\n", " ")
    return {m.group(2) for m in re.finditer(r'echo "\$\{(\w+)\}\s+(/\S+\.deb)" \| sha256sum -c', text)
            if m.group(1) in shas}


def _pinned(pkg: str, debs: set[str]) -> bool:
    return "=" in pkg or pkg in debs


def test_apt_packages_are_version_pinned():
    df = (RUNNER / "ci-image" / "Dockerfile").read_text()
    pkgs, debs = _apt_packages(df), _hash_pinned_debs(df)
    assert pkgs, "the job image installs something"
    assert all(_pinned(p, debs) for p in pkgs), pkgs
    assert _apt_packages("RUN apt-get install -qq -y \\\n  foo=1 \\\n  bar\n") == ["foo=1", "bar"]


def test_a_local_deb_counts_as_pinned_only_with_a_sha256_check():
    sha = "a" * 64
    good = f'ARG X_SHA={sha}\nRUN curl -o /tmp/x.deb u \\\n && echo "${{X_SHA}}  /tmp/x.deb" | sha256sum -c - \\\n && apt-get install -y /tmp/x.deb\n'
    assert _hash_pinned_debs(good) == {"/tmp/x.deb"}
    no_check = "RUN curl -o /tmp/x.deb u && apt-get install -y /tmp/x.deb\n"
    assert not all(_pinned(p, _hash_pinned_debs(no_check)) for p in _apt_packages(no_check))
    short_sha = good.replace(sha, "a" * 12)  # not a full sha256: not a pin
    assert _hash_pinned_debs(short_sha) == set()
    other_file = good.replace('"${X_SHA}  /tmp/x.deb"', '"${X_SHA}  /tmp/y.deb"')  # checks another file
    assert not all(_pinned(p, _hash_pinned_debs(other_file)) for p in _apt_packages(other_file))


def test_rollback_points_at_the_kept_base_image():
    cfg = (RUNNER / "config.yaml").read_text()
    assert f"docker://{_default('CI_IMAGE_BASE_TAG')}" in cfg


def test_prune_never_removes_the_local_images():
    lines = [ln for ln in (RUNNER / "prune.sh").read_text().splitlines()
             if "image prune" in ln and not ln.lstrip().startswith("#")]
    assert lines and all("label!=windy-git.keep=1" in ln for ln in lines), lines


def test_restart_drains_longer_than_the_runner_shutdown_timeout():
    s = (RUNNER / "restart-idle.sh").read_text()
    stop = int(re.search(r'RESTART_STOP_TIMEOUT:-(\d+)', s).group(1))
    shutdown = yaml.safe_load((RUNNER / "config.yaml").read_text())["runner"]["shutdown_timeout"]
    m = re.fullmatch(r"(\d+)([sm])", shutdown)
    assert stop > int(m.group(1)) * (60 if m.group(2) == "m" else 1)
    assert 'docker restart -t "$STOP_T"' in s
    assert '[ -x "$WGQ" ] ||' in s, "a missing DB helper must refuse, not wait for hours"
