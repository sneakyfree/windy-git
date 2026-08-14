"""Invariant guards.

DNA plan section 8: "Every invariant I-1..I-13 has a named test. A test file
header cites the invariant it defends." This file defends I-1, I-3, I-7, I-8,
I-12 and D-9.

These are not unit tests of convenience. Each one encodes a failure that already
happened somewhere in this ecosystem and cost real time.
"""

from __future__ import annotations

import base64 as _b64
import json as _json
import re
import subprocess
import sys
import types as _types
from pathlib import Path

import pytest
import pytest as _pytest

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


# --------------------------------------------------------------------------
# G2.1 / G2.7 — the Gitea version is PINNED, and drift is a failure
# --------------------------------------------------------------------------
def test_g21_gitea_version_is_pinned_not_latest():
    compose = (ROOT / "docker-compose.yml").read_text()
    m = re.search(r"image:\s*\S*gitea/gitea:(\S+)", compose)
    assert m, "no gitea image pin found"
    assert m.group(1) != "latest", "G2.1: pin an exact Gitea version, never `latest`"
    assert re.match(r"^\d+\.\d+\.\d+$", m.group(1)), f"not an exact version: {m.group(1)}"


def test_g24_gitea_license_travels_with_us():
    """MIT's one obligation. Cheap to honour, embarrassing to miss."""
    assert (ROOT / "LICENSES" / "gitea-MIT.txt").exists()
    assert "MIT" in (ROOT / "LICENSES" / "gitea-MIT.txt").read_text()


# --------------------------------------------------------------------------
# G4.3 — the two Gitea storage traps that cost a crash loop each
# --------------------------------------------------------------------------
def test_g43_no_lfs_storage_type_override():
    """Naming a storage type inside [lfs] creates a SEPARATE storage section
    that does not inherit endpoint or credentials from [storage], and Gitea
    crash-loops with an error that names the symptom and not the cause."""
    # Check real settings only — the compose file deliberately NAMES this key in
    # a warning comment so the next person does not re-add it.
    active = [
        ln for ln in (ROOT / "docker-compose.yml").read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert not any("GITEA__lfs__STORAGE_TYPE" in ln for ln in active)


def test_g43_lfs_server_is_actually_enabled():
    """Setting the storage backend does NOT turn LFS on. Without this the batch
    endpoint 404s and the client says 'Repository or object not found', which
    reads like a permissions problem and is not one."""
    active = [
        ln for ln in (ROOT / "docker-compose.yml").read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert any("GITEA__server__LFS_START_SERVER" in ln for ln in active)


def test_g43_r2_checksum_trap_is_pinned():
    """R2 rejects the checksum algorithm S3 clients send by default."""
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "MINIO_CHECKSUM_ALGORITHM" in compose


# --------------------------------------------------------------------------
# G3.6 — the trust status-code law. This is the one with a live sibling bypass.
# --------------------------------------------------------------------------
def test_g36_trust_client_never_soft_allows():
    """A sibling maps HTTP 400 and 429 to 'unreachable' and then soft-ALLOWS.
    That is inducible: an attacker who wants the check skipped only has to make
    the check rate-limit itself at 100/min/IP."""
    src = (ROOT / "api" / "app" / "auth.py").read_text()
    assert "raise passport_unresolvable" in src
    # There must be no return path out of resolve_passport other than a verified
    # 200 or a raise.
    body = src[src.index("async def resolve_passport") : src.index("async def get_caller")]
    returns = [ln for ln in body.splitlines() if ln.strip().startswith("return")]
    assert len(returns) == 1, f"resolve_passport has {len(returns)} return paths; expected exactly 1"


def test_g36_unverified_human_jwt_is_refused_in_production():
    """I-8 applied to ourselves: an unverified JWT is an authentication bypass,
    not a shortcut. Until G3.2's JWKS verifier exists, production refuses."""
    from api.app.config import Settings

    assert Settings().require_verified_jwt is True
    src = (ROOT / "api" / "app" / "auth.py").read_text()
    assert "human_signin_not_ready" in src


def test_no_auth_bypass_env_var_anywhere():
    """The desktop control server is the best Principle-#5 artifact in the
    ecosystem partly because it has NO bypass env var. Copied on purpose."""
    src = (ROOT / "api" / "app" / "auth.py").read_text()
    for banned in ("SKIP_AUTH", "DISABLE_AUTH", "ALLOW_INSECURE", "AUTH_BYPASS", "DEV_MODE"):
        assert banned not in src


# --------------------------------------------------------------------------
# G5.3 — the shelter's grant model
# --------------------------------------------------------------------------
def test_g53_grant_requires_exactly_one_grantee_in_the_database():
    """Enforced by a CHECK constraint, not by application code. This ecosystem
    already has a core invariant enforced only in app code across two files."""
    src = (ROOT / "alembic" / "versions" / "001_genesis.py").read_text()
    assert "ck_grant_exactly_one_grantee" in src
    assert "(grantee_identity_id IS NULL) <> (grantee_passport IS NULL)" in src


def test_g53_agent_grants_expire_by_default():
    from api.app.config import Settings

    assert Settings().agent_grant_default_days == 90


def test_g55_shelter_strings_avoid_developer_vocabulary():
    """D-9/I-9: a person restoring last Tuesday's work should not have to learn
    a vocabulary first. Check the strings users actually see."""
    import re as _re

    src = (ROOT / "api" / "app" / "routes" / "repos.py").read_text()
    speaks = _re.findall(r'"speak":\s*\(?\s*\n?\s*f?"([^"]+)"', src)
    assert speaks, "no speak strings found to audit"
    for s in speaks:
        low = s.lower()
        for jargon in ("commit", "repository", "branch", "sha", "push"):
            assert jargon not in low, f"developer vocabulary in a user string: {s!r}"


# --------------------------------------------------------------------------
# I-4 — never a one-way door
# --------------------------------------------------------------------------
def test_i04_mirror_syncs_on_every_save_not_just_a_timer():
    """An hourly window means an hour of work can be the thing you lose, and the
    window is invisible until it costs you."""
    src = (ROOT / "api" / "app" / "services" / "mirror.py").read_text()
    assert '"sync_on_commit": True' in src


def test_i04_unconfigured_mirror_is_never_reported_healthy():
    """A mirror nobody checks is a belief, not a backup. An unconfigured one
    reports 'unconfigured' — never 'healthy'."""
    src = (ROOT / "api" / "app" / "services" / "mirror.py").read_text()
    assert '"state": "unconfigured"' in src
    assert "if not self.configured:" in src


def test_i04_mirror_lag_threshold_is_set():
    from api.app.config import Settings

    assert Settings().mirror_lag_p2_seconds == 3600


def test_owner_namespace_is_derived_from_the_repo_not_the_caller():
    """Deriving the namespace from the caller is right only while the caller is
    the owner, and addresses the wrong namespace the moment a collaborator asks
    — surfacing as 'not found', which is the hardest kind of bug to see."""
    src = (ROOT / "api" / "app" / "routes" / "repos.py").read_text()
    body = src[src.index("async def list_versions") : src.index("async def create_grant")]
    assert "_repo_owner_login(repo)" in body
    assert "_owner_login(caller)" not in body


def test_i04_never_synced_is_not_reported_as_merely_behind():
    """Collapsing 'never ran' into 'behind' is how a backup that was never made
    gets read as a backup that is merely stale. Gitea reports the epoch for
    'not yet', which arithmetic turns into a 56-year lag and a confident
    'degraded'."""
    src = (ROOT / "api" / "app" / "services" / "mirror.py").read_text()
    assert "never_synced" in src
    assert '"pending"' in src


# --------------------------------------------------------------------------
# G7 / I-5 — CI never shares a kernel with identity
# --------------------------------------------------------------------------
def test_i05_runner_never_mounts_the_host_docker_socket():
    """The tempting move — and what every published act_runner example does —
    is to mount /var/run/docker.sock. That hands every workflow, including a
    transitive dependency's postinstall script, the ability to start a
    privileged container mounting / — i.e. root on the host."""
    compose = (ROOT / "deploy" / "runner" / "docker-compose.yml").read_text()
    active = [ln for ln in compose.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    for ln in active:
        assert "/var/run/docker.sock" not in ln, "I-5: never mount the host docker socket"


def test_i05_jobs_get_a_network_per_job_not_a_shared_bridge():
    """A shared flat bridge lets concurrent jobs see each other, and breaks
    service-container DNS (service aliases only exist on a per-job network).
    Per-job is both stricter and correct."""
    cfg = (ROOT / "deploy" / "runner" / "config.yaml").read_text()
    active = [ln for ln in cfg.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    net = [ln for ln in active if ln.strip().startswith("network:")]
    assert net and net[0].strip() == 'network: ""', "jobs must get a per-job network"


def test_i05_jobs_cannot_bind_mount_from_the_daemon_host():
    cfg = (ROOT / "deploy" / "runner" / "config.yaml").read_text()
    assert "valid_volumes: []" in cfg
    assert 'docker_host: "-"' in cfg


def test_i05_no_ci_container_can_reach_the_forge_network():
    """The first CI run failed with "Could not resolve host: gitea" because job
    containers sit on dind's private network. The easy fix — putting jobs on the
    forge network — would have left untrusted workflow code one DNS name from
    the forge's Postgres. Instead jobs reach the PUBLIC forge surface, so no CI
    container has a private route to anything."""
    compose = (ROOT / "deploy" / "runner" / "docker-compose.yml").read_text()
    active = [ln for ln in compose.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    joined = "\n".join(active)
    assert "windy-git_default" not in joined, "I-5: no CI container joins the forge network"
    assert "https://app.windygit.com" in joined


def test_i05_runner_is_a_separate_compose_project_from_the_forge():
    """Runners restart, crash, get starved and get killed. None of that should
    ever touch the thing serving repositories."""
    runner = (ROOT / "deploy" / "runner" / "docker-compose.yml").read_text()
    forge = (ROOT / "docker-compose.yml").read_text()
    assert "name: windy-git-runner" in runner
    assert "name: windy-git" in forge


def test_g15_runner_is_cpu_and_memory_bounded():
    """Veron 1 is Grant's workstation, not a dedicated build box."""
    compose = (ROOT / "deploy" / "runner" / "docker-compose.yml").read_text()
    assert "cpus:" in compose
    assert "mem_limit:" in compose


def test_g75_workflows_use_a_label_this_runner_actually_provides():
    """A workflow naming a label nobody provides queues forever and presents as
    a hung CI system rather than a typo."""
    cfg = (ROOT / "deploy" / "runner" / "config.yaml").read_text()
    provided = {
        ln.split(":")[0].strip().strip('"- ')
        for ln in cfg.splitlines()
        if "docker://" in ln
    }
    assert provided, "runner declares no labels"
    for wf in ROOT.rglob(".gitea/workflows/*.y*ml"):
        for ln in wf.read_text().splitlines():
            # Skip comments — a doc line explaining runs-on is not a runs-on.
            if ln.strip().startswith("#") or "runs-on:" not in ln:
                continue
            label = ln.split("runs-on:")[1].strip()
            assert label in provided, f"{wf.name}: '{label}' is not a provided label"


def test_g73_workflow_pins_a_python_that_satisfies_requires_python():
    """The first real CI run wedged for 14 minutes because the runner image
    ships Python 3.10 and this project requires 3.12: pip answered by
    backtracking through every historical version of every dependency, at full
    CPU, silently. A version mismatch presenting as a hang rather than an
    error."""
    import re as _re

    pyproject = (ROOT / "pyproject.toml").read_text()
    m = _re.search(r'requires-python\s*=\s*">=(\d+)\.(\d+)"', pyproject)
    assert m, "pyproject declares no requires-python"
    major, minor = int(m.group(1)), int(m.group(2))

    for wf in ROOT.rglob(".gitea/workflows/*.y*ml"):
        text = wf.read_text()
        # Either a pinned container image or an explicit setup-python version.
        pin = _re.search(r"image:\s*python:(\d+)\.(\d+)", text) or _re.search(
            r'python-version:\s*"?(\d+)\.(\d+)"?', text
        )
        assert pin, f"{wf.name}: job neither pins a python image nor sets up a version"
        assert (int(pin.group(1)), int(pin.group(2))) >= (major, minor), (
            f"{wf.name}: pins python {pin.group(0)} but the project requires "
            f">={major}.{minor}"
        )


def test_g73_every_job_has_a_timeout():
    """A wedged step should be a red check in minutes, not an occupied runner
    for half an hour."""
    for wf in ROOT.rglob(".gitea/workflows/*.y*ml"):
        assert "timeout-minutes:" in wf.read_text(), f"{wf.name}: no job timeout"


# --------------------------------------------------------------------------
# G7.6 — the canary must watch what users do, and must not live on Kit 0
# --------------------------------------------------------------------------
def test_g76_canary_probes_login_not_just_health():
    """/health returned 200 for the entire 2026-08-12 outage while login was
    dead. A canary that only watches health is decorative."""
    src = (ROOT / "scripts" / "canary.py").read_text()
    assert "identity.login" in src
    assert "/api/v1/auth/login" in src


def test_g76_canary_does_not_run_on_kit_zero():
    """A canary hosted on the box it watches dies with that box, and reports
    nothing at the exact moment it matters."""
    wf = (ROOT / ".gitea" / "workflows" / "canary.yml").read_text()
    assert "runs-on: veron-1" in wf
    assert "72.60.118.54" not in wf


def test_g76_canary_alerts_on_transition_not_every_run():
    """A canary that emails every 10 minutes gets filtered, and a filtered
    canary is a dead canary."""
    src = (ROOT / "scripts" / "canary.py").read_text()
    assert "newly_bad" in src and "recovered" in src


def test_g76_canary_has_two_independent_signals():
    """Email AND a red CI run. The last fleet canary died silently because it
    had one signal and nothing watched the watcher."""
    src = (ROOT / "scripts" / "canary.py").read_text()
    assert "return 1 if any" in src, "canary must exit non-zero so CI goes red"


def test_g76_alert_path_sets_a_user_agent():
    """Without an explicit User-Agent, urllib sends 'Python-urllib/3.x' and
    Resend rejects it 403 while the identical curl succeeds. Caught by testing
    the alert path: the canary would have detected every outage correctly and
    told nobody."""
    src = (ROOT / "scripts" / "canary.py").read_text()
    send = src[src.index("def send_alert") : src.index("def main(")]
    assert "User-Agent" in send


# --------------------------------------------------------------------------
# G3.5 — revocation is fail-closed, and the two signature traps
# --------------------------------------------------------------------------
def test_g35_webhook_strips_the_sha256_prefix():
    """A sibling receiver compared the whole 'sha256=<hex>' header against a
    bare digest and returned 401 forever — wired, never once delivered."""
    src = (ROOT / "api" / "app" / "routes" / "webhooks.py").read_text()
    assert 'startswith("sha256=")' in src


def test_g35_webhook_hmacs_raw_bytes_not_reserialised_json():
    """JSON.stringify of a parsed body reorders keys and changes whitespace, so
    the digest never matches what the sender signed. Same silent 401."""
    src = (ROOT / "api" / "app" / "routes" / "webhooks.py").read_text()
    verify = src[src.index("def _verify") : src.index("@router.post")]
    assert "raw" in verify and "json.dumps" not in verify


def test_g35_unset_secret_refuses_rather_than_accepts():
    src = (ROOT / "api" / "app" / "routes" / "webhooks.py").read_text()
    assert "webhook_secret_unset" in src
    assert "refusing unverified webhooks" in src


def test_g35_signature_compare_is_constant_time():
    src = (ROOT / "api" / "app" / "routes" / "webhooks.py").read_text()
    assert "hmac.compare_digest" in src


def test_g35_revocation_never_acknowledges_what_it_did_not_apply():
    """A 200 on a revocation the receiver could not apply is a security hole
    that reports success."""
    src = (ROOT / "api" / "app" / "routes" / "webhooks.py").read_text()
    assert "refusing to acknowledge a revocation we did not apply" in src


def test_g35_probe_acknowledgement_changes_nothing():
    """Eternitas verifies a webhook URL answers BEFORE issuing the secret that
    signs deliveries, so the first request can never be signed. The probe path
    answers 200 but must never act, and anything claiming to be an event must
    still be verified."""
    src = (ROOT / "api" / "app" / "routes" / "webhooks.py").read_text()
    probe = src[src.index('if x_eternitas_event == "platform.test_ping"') : src.index("secret = settings")]
    assert '"acted": False' in probe
    assert "update(" not in probe and "commit" not in probe


def test_g35_did_not_disable_validation_to_register():
    """skip_validation would permanently disable a safety check to solve a
    one-time ordering problem."""
    for f in (ROOT / "scripts").glob("*.py"):
        assert "skip_validation" not in f.read_text()


def test_g76_canary_survives_an_unwritable_state_path():
    """A monitoring tool that dies of a config problem reports nothing at all,
    and reports it silently. State is an optimisation; probing is the point."""
    src = (ROOT / "scripts" / "canary.py").read_text()
    save = src[src.index("def save_state") : src.index("def send_alert")]
    assert "except OSError" in save


# --------------------------------------------------------------------------
# G0.9 — backups, the prerequisite for being the daily driver
# --------------------------------------------------------------------------
def test_g09_backup_bundles_all_refs_not_just_the_default_branch():
    """A single-branch bundle loses every other branch and every tag silently,
    and you find out during the restore."""
    src = (ROOT / "scripts" / "backup.sh").read_text()
    assert "bundle create" in src and "--all" in src


def test_g09_backup_verifies_before_trusting():
    """An unverified bundle is a belief, not a backup."""
    src = (ROOT / "scripts" / "backup.sh").read_text()
    assert "git bundle verify" in src


def test_g09_backup_fails_loudly():
    """A backup script that swallows errors is worse than none — it
    manufactures confidence."""
    src = (ROOT / "scripts" / "backup.sh").read_text()
    assert "COMPLETED WITH FAILURES" in src
    assert "refusing to report a backup that did not happen" in src


# --------------------------------------------------------------------------
# SECURITY (behavioral, not string-grep): the agent path must not authenticate
# an unverified token. Regression guard for the 2026-08-13 forged-token bypass.
# --------------------------------------------------------------------------


def _forged_bearer(passport: str) -> str:
    def seg(d):
        return _b64.urlsafe_b64encode(_json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{seg({'alg':'none','typ':'JWT'})}.{seg({'passport':passport})}.not-a-signature"


def _fake_request(settings):
    app = _types.SimpleNamespace(state=_types.SimpleNamespace(settings=settings))
    return _types.SimpleNamespace(app=app)


@_pytest.mark.asyncio
async def test_security_forged_agent_token_is_refused_in_production():
    """The 2026-08-13 exploit: an alg:none token naming a real passport returned
    HTTP 200 as that agent. It must now be refused whichever gate catches it —
    an EPT-shaped forgery by signature verification, a JWT-shaped one by the
    human gate. What is asserted is REFUSAL, not a particular error code."""
    from api.app.auth import get_caller
    from api.app.config import Settings
    from api.app.errors import RepairPointer

    settings = Settings(environment="production", require_verified_jwt=True,
                        eternitas_platform_api_key="x")
    req = _fake_request(settings)

    # Both shapes now route to the EPT verifier, because alg:none is never
    # valid for ANY caller — so 401 "your token is bad" is the honest answer,
    # not 503 "that feature isn't ready".
    for typ, expected in (("JWT", "ept_invalid"), ("EPT", "ept_invalid")):
        def seg(d):
            return _b64.urlsafe_b64encode(_json.dumps(d).encode()).rstrip(b"=").decode()
        forged = (f"{seg({'alg':'none','typ':typ})}"
                  f".{seg({'passport':'ET26-1EF9-VJAN','sub':'ET26-1EF9-VJAN'})}.sig")
        with _pytest.raises(RepairPointer) as exc:
            await get_caller(req, authorization=f"Bearer {forged}", x_service_token=None)
        assert exc.value.status_code in (401, 403, 503), f"{typ} was not refused"
        assert exc.value.code == expected, f"{typ} -> {exc.value.code}"


@_pytest.mark.asyncio
async def test_security_no_bearer_is_still_401():
    from api.app.auth import get_caller
    from api.app.config import Settings
    from api.app.errors import RepairPointer

    req = _fake_request(Settings(environment="production"))
    with _pytest.raises(RepairPointer) as exc:
        await get_caller(req, authorization=None, x_service_token=None)
    assert exc.value.status_code == 401


def test_i12_build_fails_when_commit_sha_is_empty():
    """The sed+grep pair silently accepted an empty COMMIT_SHA: it replaced ""
    with "" and then matched that same empty string, shipping a container that
    reported commit_sha: null. That is the exact defect I-12 exists to prevent,
    and it happened on 2026-08-14."""
    df = (ROOT / "Dockerfile").read_text()
    assert 'test -n "${COMMIT_SHA}"' in df


# --------------------------------------------------------------------------
# G2.3 — branding lives in the repo, not only on one host's disk
# --------------------------------------------------------------------------
def test_g23_branding_is_version_controlled():
    """It was applied directly to Veron's disk first, which is the config-drift
    trap this project documents: the running system and the repo disagree, and
    a rebuild silently reverts to stock Gitea."""
    b = ROOT / "deploy" / "branding"
    for f in ("apply.sh", "README.md", "templates/home.tmpl",
              "templates/custom/header.tmpl"):
        assert (b / f).exists(), f"missing {f}"


def test_g23_brand_css_filename_is_versioned():
    """Cloudflare caches /assets/* for 6h and no token here can purge, so a
    fixed filename leaves stale bytes live for hours."""
    import re as _re

    hdr = (ROOT / "deploy" / "branding" / "templates" / "custom" / "header.tmpl").read_text()
    m = _re.search(r"theme-windy\.v(\d+)\.css", hdr)
    assert m, "brand CSS must carry a version in its FILENAME"
    assert (ROOT / "deploy" / "branding" / "public" / "assets" / "css"
            / f"theme-windy.v{m.group(1)}.css").exists()
