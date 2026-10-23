"""deploy/runner: the CI job image is built locally, pinned, and never pruned (10-22)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

RUNNER = Path(__file__).resolve().parents[2] / "deploy" / "runner"


def _tag() -> str:
    m = re.search(r'CI_IMAGE_TAG:-([^}"]+)', (RUNNER / "build-ci-image.sh").read_text())
    assert m, "build-ci-image.sh names its tag"
    return m.group(1)


def test_every_job_label_runs_the_built_image():
    labels = yaml.safe_load((RUNNER / "config.yaml").read_text())["runner"]["labels"]
    images = {lab.split(":", 1)[1] for lab in labels}
    assert images == {f"docker://{_tag()}"}, images        # one image, the one the script builds


def test_base_is_pinned_by_digest_and_tools_by_version():
    df = (RUNNER / "ci-image" / "Dockerfile").read_text()
    assert re.search(r"^FROM catthehacker/ubuntu@sha256:[0-9a-f]{64}$", df, re.M)
    for pkg in re.findall(r"install -y[^\n]*?((?:[a-z0-9.+-]+=?[^\s&\\]*\s*)+)", df):
        for name in pkg.split():
            if not name.startswith("-"):
                assert "=" in name, f"apt package not version-pinned: {name}"
    assert 'windy-git.keep="1"' in df


def test_prune_never_removes_the_local_image():
    lines = [ln for ln in (RUNNER / "prune.sh").read_text().splitlines()
             if "image prune" in ln and not ln.lstrip().startswith("#")]
    assert lines and all("label!=windy-git.keep=1" in ln for ln in lines), lines
