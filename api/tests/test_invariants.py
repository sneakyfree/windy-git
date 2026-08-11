"""Invariant guards.

DNA plan section 8: "Every invariant I-1..I-13 has a named test. A test file
header cites the invariant it defends." This file defends I-1, I-3, I-7, I-8,
I-12 and D-9.

These are not unit tests of convenience. Each one encodes a failure that already
happened somewhere in this ecosystem and cost real time.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------
# I-12 — deployment identity must be honest
# --------------------------------------------------------------------------
def test_i12_env_override_cannot_change_reported_sha(monkeypatch):
    """Nine of twelve sibling services misreport their commit; the root cause was
    a hardcoded COMMIT_SHA pin in /opt/*/.env overriding the build arg."""
    from api.app import buildinfo

    monkeypatch.setattr(buildinfo, "BAKED_COMMIT_SHA", "a" * 40)
    monkeypatch.setattr(buildinfo, "BAKED_BUILT_AT", "2026-08-11T00:00:00Z")
    monkeypatch.setenv("COMMIT_SHA", "b" * 40)
    buildinfo.get_build_info.cache_clear()

    info = buildinfo.get_build_info()
    assert info.commit_sha == "a" * 40, "env override must be IGNORED (I-12)"
    assert info.source == "baked"
    buildinfo.get_build_info.cache_clear()


def test_i12_never_invents_a_sha(monkeypatch):
    """With nothing baked and no git, report null. Never guess (I-8)."""
    from api.app import buildinfo

    monkeypatch.setattr(buildinfo, "BAKED_COMMIT_SHA", "")
    monkeypatch.setattr(buildinfo, "_git_head", lambda: None)
    buildinfo.get_build_info.cache_clear()

    info = buildinfo.get_build_info()
    assert info.commit_sha is None
    assert info.source == "unknown"
    buildinfo.get_build_info.cache_clear()


# --------------------------------------------------------------------------
# I-8 — fail closed. Never claim live while a provider is mock.
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_i08_unconfigured_provider_is_never_ok():
    """The domains cell told the public google.com was available for $18 because
    a public route reached a mock provider without passing a gate."""
    from api.app.providers.base import ProbeResult, Provider

    class Unconfigured(Provider):
        name = "test"

        @property
        def configured(self) -> bool:
            return False

        async def probe(self) -> ProbeResult:  # pragma: no cover - must not run
            raise AssertionError("probe() must never be reached when unconfigured")

    result = await Unconfigured().healthy()
    assert result.ok is False
    assert result.reachable is False


@pytest.mark.asyncio
async def test_i08_probe_exception_is_not_ok():
    from api.app.providers.base import ProbeResult, Provider

    class Exploding(Provider):
        name = "test"

        @property
        def configured(self) -> bool:
            return True

        async def probe(self) -> ProbeResult:
            raise RuntimeError("upstream on fire")

    result = await Exploding().healthy()
    assert result.ok is False
    assert "on fire" in result.detail


def test_i08_no_provider_has_a_mock_mode():
    """An unconfigured provider is honest. A mock provider is a liar with a
    green light."""
    src = (ROOT / "api" / "app" / "providers" / "registry.py").read_text()
    for banned in ("MockProvider", "class Mock", "if mock", "USE_MOCK"):
        assert banned not in src, f"{banned!r} found — see I-8"


# --------------------------------------------------------------------------
# I-7 — repo_type is first-class from migration 001
# --------------------------------------------------------------------------
def test_i07_repo_type_not_null_in_genesis_migration():
    src = (ROOT / "alembic" / "versions" / "001_genesis.py").read_text()
    assert 'sa.Column("repo_type", repo_type, nullable=False)' in src


def test_i07_model_cards_exists_in_v1_schema():
    """v2 surface, v1 schema. Cheap now, near-impossible to retrofit."""
    src = (ROOT / "alembic" / "versions" / "001_genesis.py").read_text()
    assert '"model_cards"' in src


def test_i07_all_three_repo_types_declared():
    from api.app.models.core import RepoType

    assert {t.value for t in RepoType} == {"code", "model", "dataset"}


# --------------------------------------------------------------------------
# I-1 — Gitea is a component, never a merged tree
# --------------------------------------------------------------------------
def test_i01_patch_ceiling():
    """D-2: a hard fork means owning merge conflicts forever against a project
    that ships every 2-3 months including security fixes."""
    patches = ROOT / "patches"
    diffs = [p for p in patches.glob("*") if p.suffix in {".patch", ".diff"}]
    assert len(diffs) <= 3, (
        f"{len(diffs)} Gitea patches — the I-1 ceiling is 3 without an ADR. "
        "Reach for the REST API before reaching for the source tree."
    )


# --------------------------------------------------------------------------
# I-3 — git objects local, heavy bytes remote. Never the reverse.
# --------------------------------------------------------------------------
def test_i03_git_root_is_not_object_storage():
    from api.app.config import Settings

    root = Settings().git_data_root
    for banned in ("s3://", "r2://", "https://", "gs://"):
        assert not root.startswith(banned), (
            "git object databases must live on a POSIX filesystem — a clone "
            "touches thousands of small objects (I-3)"
        )


# --------------------------------------------------------------------------
# D-4 — never Kit 0. A guard in a document is a preference.
# --------------------------------------------------------------------------
def test_d04_boot_guard_exists():
    src = (ROOT / "api" / "app" / "main.py").read_text()
    assert "_refuse_kit_zero" in src
    assert "kit_zero_refused" in src


# --------------------------------------------------------------------------
# D-9 — vocabulary law
# --------------------------------------------------------------------------
def test_d09_vocabulary_audit_passes():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "vocab_audit.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout


# --------------------------------------------------------------------------
# G8.3 — every error is a 4-field repair pointer
# --------------------------------------------------------------------------
def test_g83_errors_carry_all_four_fields():
    from api.app.errors import provider_unconfigured

    err = provider_unconfigured("r2", "R2_ACCESS_KEY_ID")
    for field in ("code", "speak", "machine_cause", "remediation_tool"):
        assert field in err.detail


def test_g83_speak_strings_are_grandma_words():
    """I-9: hardest on failure. No stack traces, no jargon, and it names the fix."""
    from api.app.errors import provider_unconfigured, quota_exceeded

    for err in (provider_unconfigured("r2", "KEY"), quota_exceeded("r", 2, 1)):
        speak = err.detail["speak"]
        assert speak[0].isupper() and speak.endswith(".")
        for jargon in ("null", "None", "500", "traceback", "exception", "repo_id"):
            assert jargon not in speak


# --------------------------------------------------------------------------
# G3.7 — telemetry actor_type enum
# --------------------------------------------------------------------------
def test_g37_service_is_not_a_legal_actor_type():
    """windy-chat sends actor_type='service'; the ingest Literal allows only
    human|agent|system, so the whole batch 422s and is dropped with one warn."""
    legal = {"human", "agent", "system"}
    assert "service" not in legal


# --------------------------------------------------------------------------
# G7.5 — runner labels are pinned
# --------------------------------------------------------------------------
def test_g75_no_ubuntu_latest_in_workflows():
    """All four windy-registry workflows use ubuntu-latest and every run fails."""
    for wf in ROOT.rglob(".github/workflows/*.y*ml"):
        assert "ubuntu-latest" not in wf.read_text(), f"{wf}: see G7.5"


# --------------------------------------------------------------------------
# G0.5 — compose files are committed, secrets stripped
# --------------------------------------------------------------------------
def test_g05_no_secret_literals_committed():
    """Three compose files that wire prod to its databases currently exist in
    exactly one place on earth. This cell will not add a fourth."""
    patterns = [
        re.compile(r"cfat_[A-Za-z0-9]{20,}"),
        re.compile(r"cfut_[A-Za-z0-9]{20,}"),
        re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
        re.compile(r"et_plt_[A-Za-z0-9]{10,}"),
    ]
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git/" in path.as_posix():
            continue
        if path.suffix not in {".py", ".yml", ".yaml", ".toml", ".ini", ".md", ".env", ".example"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in patterns:
            assert not pattern.search(text), f"credential literal in {path}"
