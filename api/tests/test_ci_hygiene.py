"""CI hygiene guard (house rule 6): lockfile-only installs, no host-port services."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("ci_hygiene", ROOT / "scripts" / "ci_hygiene.py")
hy = importlib.util.module_from_spec(_spec)
sys.modules["ci_hygiene"] = hy
_spec.loader.exec_module(hy)

WF = ".github/workflows/ci.yml"


@pytest.mark.parametrize("path, text", [
    (WF, "          .venv/bin/pip install -e \".[dev]\""),          # windy-git's own, before e64a1b5
    ("Dockerfile", "RUN pip install --no-cache-dir -e ."),              # windy-git image, before e64a1b5
    (WF, "      - run: uv pip install -e \".[dev]\""),                # WindyCloud #109's CI
    (WF, "        run: pip install fastapi uvicorn"),
    (WF, "      - run: uv sync --all-extras"),                         # windy-mind style, not locked
    (WF, "      - run: npm install"),                                  # windy-drops / windytalk
    (WF, "      - run: npm install --no-save --no-audit --no-fund jsdom"),  # windy-pro reality-check
    (WF, "      - run: yarn install"),
    (WF, "      - run: cd web && pnpm install"),
    ("docker/api.Dockerfile", "RUN apt-get update && pip install requests"),
])
def test_floating_installs_are_flagged(path, text):
    assert [k for k, _ in hy.scan_line(path, text)] == ["floating install"]


@pytest.mark.parametrize("path, text", [
    (WF, "          python3 -m pip install -q uv==0.12.5"),            # exact tool pin
    (WF, "          uv sync --locked --extra dev"),
    (WF, "      - run: uv sync --frozen"),
    (WF, "      - run: npm ci"),
    (WF, "      - run: npm install --no-save jsdom@24.1.0"),
    (WF, "      - run: pip install -r requirements.lock --require-hashes"),
    (WF, "      - run: pip install -r requirements.txt"),
    ("Dockerfile", " && pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt \\\\"),
    ("Dockerfile", "RUN pip install --no-cache-dir --no-deps -e ."),       # project only, deps from the lock
    (WF, "          .venv/bin/pip install -q --upgrade pip"),
    (WF, "      - run: yarn install --frozen-lockfile"),
    (WF, "      # - run: npm install   (commented out)"),
    (WF, "      - run: echo 'pip is great'"),
])
def test_locked_or_pinned_installs_pass(path, text):
    assert hy.scan_line(path, text) == []


@pytest.mark.parametrize("text, port", [
    ("          - 5432:5432", "5432"),          # windy-mind / eternitas (collided 09-23)
    ("          - '15432:5432'", "15432"),      # WindyCloud
    ('          - "6379:6379"', "6379"),
])
def test_services_publishing_a_host_port_are_flagged(text, port):
    [(kind, match)] = hy.scan_line(WF, text)
    assert kind == "host port" and port in match


def test_host_port_rule_is_for_workflows_only():
    assert hy.scan_line("docker-compose.yml", "      - 5432:5432") == []


@pytest.mark.parametrize("path, ok", [
    (".github/workflows/ci.yml", True), (".gitea/workflows/check.yaml", True),
    ("Dockerfile", True), ("api/Dockerfile.prod", True), ("docker/web.Dockerfile", True),
    ("scripts/setup.sh", False), ("README.md", False), ("node_modules/x/Dockerfile", False),
    (".github/lint/x.yml", False),
])
def test_scope_is_ci_workflows_and_dockerfiles(path, ok):
    assert hy.path_ok(path) is ok


def test_warn_mode_never_turns_red(monkeypatch):
    monkeypatch.setattr(hy, "MODE", "warn")
    state, desc, f = hy.status_for([hy.cg.Finding(WF, 12, "floating install", "npm install (use npm ci)")], True)
    assert state == "success" and desc.startswith("⚠ WARN (not blocking): 1 CI hygiene issue in CI/Dockerfiles")


def test_allow_file_is_line_scoped_exceptions_only():
    """Every exception is line-scoped (`matches`), so an allowed file can't hide a
    NEW floating install or docker step. Today: windy-pro's if:false deploy job."""
    allow = hy.cg.load_allow(hy.ALLOW_FILE)
    assert [(e["repo"], e["paths"]) for e in allow] == [("windy-pro", [".github/workflows/ci.yml"])]
    assert all(e.get("matches") for e in allow)
    ok = "        run: docker build -f account-server/Dockerfile -t windy-pro:${{ github.sha }} ."
    new = "        run: docker build -t windy-pro-api ."
    assert hy.cg.allowed("windy-pro", WF, allow, ok)
    assert not hy.cg.allowed("windy-pro", WF, allow, new)
    assert not hy.cg.allowed("windy-chat", WF, allow, ok)


@pytest.mark.parametrize("path, text, want", [
    ("Dockerfile", "COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv", "ghcr.io/astral-sh/uv:latest"),  # Mail #147
    ("Dockerfile", "FROM python:latest", "python:latest"),
    ("Dockerfile", "FROM --platform=linux/amd64 node:latest AS web", "node:latest"),
    (WF, "        image: postgres:latest", "postgres:latest"),
    (WF, "      - uses: docker://ghcr.io/foo/bar:latest", "ghcr.io/foo/bar:latest"),
])
def test_latest_images_are_flagged(path, text, want):
    hits = hy.scan_line(path, text)
    assert ("floating image", want) in hits


@pytest.mark.parametrize("text", [
    "COPY pyproject.toml uv.lock* ./",       # Windy Mail #147
    "COPY package.json package-lock.json* ./",
])
def test_optional_lock_globs_are_flagged(text):
    assert [k for k, _ in hy.scan_line("Dockerfile", text)] == ["optional lock"]


@pytest.mark.parametrize("path, text", [
    ("Dockerfile", "COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv"),
    ("Dockerfile", "FROM python:3.12-slim"),
    ("Dockerfile", "COPY pyproject.toml uv.lock ./"),
    ("Dockerfile", "COPY src/*.py ./src/"),
    ("Dockerfile", "RUN echo latest release notes"),
])
def test_pinned_images_and_real_locks_pass(path, text):
    assert hy.scan_line(path, text) == []


@pytest.mark.parametrize("text", [
    "      - run: docker compose -f docker-compose.yml -f docker-compose.ci.yml build",  # eternitas ci/build
    "        run: docker build -t windy-mail .",
    "      - run: docker-compose up -d",
    "        run: docker buildx build --load .",
    "      - uses: docker/build-push-action@v6",
])
def test_docker_in_ci_is_flagged_with_the_fix(text):
    hits = hy.scan_line(WF, text)
    assert [k for k, _ in hits] == ["needs docker"]
    assert "no-Docker smoke test" in hits[0][1]


@pytest.mark.parametrize("path, text", [
    ("Dockerfile", "RUN docker build ."),                     # not a workflow
    (WF, "        run: ssh host 'docker compose up -d'"),      # remote host has a daemon
    (WF, "      # docker compose build"),                     # comment
    (WF, "        run: echo docker build"),
])
def test_docker_not_flagged_outside_ci_steps(path, text):
    assert [k for k, _ in hy.scan_line(path, text) if k == "needs docker"] == []


def test_needs_docker_skips_workflows_disabled_on_windy_git(monkeypatch):
    """deploy.yml runs on the target host (a real daemon); Gitea has it disabled here."""
    F = hy.cg.Finding
    monkeypatch.setattr(hy, "_DISABLED", {"eternitas": {"deploy.yml"}})
    got = hy._runs_here("Eternitas", [
        F(".github/workflows/deploy.yml", 70, "needs docker", "docker compose in CI"),
        F(".github/workflows/ci.yml", 176, "needs docker", "docker compose in CI"),
        F(".github/workflows/deploy.yml", 12, "floating install", "npm install"),
    ])
    assert [(f.path.rsplit("/", 1)[1], f.kind) for f in got] == [
        ("ci.yml", "needs docker"), ("deploy.yml", "floating install")]
    assert hy._runs_here("eternitas", None) is None
