"""windy-git's own workflows: no path filters on suites, live-host jobs manual-only unless NAMED
(Boss 10-28 07:26Z / 07:36Z / 08:27Z). Parsed YAML, block and flow forms alike, never regex on
the YAML text (Boss's ruling (d))."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".gitea" / "workflows"
GUARD = yaml.safe_load((ROOT / "ci" / "workflow-guard.yml").read_text())

# Commands that deploy, publish, upload or otherwise write to a live host (Boss's 07:36Z list).
DEPLOY = re.compile(
    r"\b(ssh|scp|rsync)\b|wrangler|pages\s+deploy|compose\s+up|aws\s+s3\s+(cp|sync|mv|rm)\b"
    r"|gh\s+release\s+(create|upload)|uploads\.github\.com|fastlane|altool|upload-google-play|eas\s+submit",
    re.I)
DEPLOY_ACTIONS = re.compile(r"ssh-action|wrangler-action|cloudflare/pages|upload-google-play|s3-sync|gh-release", re.I)


def _on(doc: dict) -> dict:
    on = doc.get("on", doc.get(True))           # PyYAML reads a bare `on:` key as True
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return dict.fromkeys(on)
    return on or {}


def workflows(directory: Path = WORKFLOWS) -> dict[str, dict]:
    return {f.name: yaml.safe_load(f.read_text()) for f in sorted(directory.glob("*.y*ml"))}


def _texts(job: dict) -> list[str]:
    return [str(s.get("run", "")) + " " + str(s.get("uses", "")) + " " + str(s.get("with", "")) for s in job.get("steps", [])]


def live_jobs(docs: dict[str, dict]) -> dict[tuple[str, str], str]:
    """{(workflow, job): why} for every job that reaches a live host."""
    out = {}
    for wf, doc in docs.items():
        for name, job in (doc.get("jobs") or {}).items():
            blob = yaml.safe_dump(job)
            why = []
            if "secrets." in blob:
                why.append("uses CI secrets")
            if any(DEPLOY.search(t) for t in _texts(job)) or any(DEPLOY_ACTIONS.search(str(s.get("uses", ""))) for s in job.get("steps", [])):
                why.append("deploys/publishes/uploads")
            if why:
                out[(wf, name)] = ", ".join(why)
    return out


def _manual_only(doc: dict, job: dict) -> bool:
    return set(_on(doc)) <= {"workflow_dispatch"} or job.get("if") in (False, "false", "${{ false }}")


def violations(docs: dict[str, dict], guard: dict) -> list[str]:
    bad = []
    named_pf = set(guard.get("path_filter_exceptions") or [])
    for wf, doc in docs.items():
        for event, spec in _on(doc).items():
            if isinstance(spec, dict) and ("paths" in spec or "paths-ignore" in spec) and wf not in named_pf:
                bad.append(f"{wf}: {event} has a paths filter")
    named_live = {(e["workflow"], e["job"]) for e in guard.get("live_host_exceptions") or []}
    live = live_jobs(docs)
    for (wf, job), why in live.items():
        jobdoc = docs[wf]["jobs"][job]
        if (wf, job) in named_live:
            if "deploys" in why:
                bad.append(f"{wf}/{job}: a NAMED read-only exception gained a deploy/publish/upload command")
        elif not _manual_only(docs[wf], jobdoc):
            bad.append(f"{wf}/{job}: live host ({why}) on {sorted(_on(docs[wf]))}, not manual-only")
    for wf, job in named_live - set(live):
        bad.append(f"{wf}/{job}: named as a live-host exception but no longer seen as one (update the guard)")
    return bad


def test_windy_git_workflows_follow_the_rules():
    assert violations(workflows(), GUARD) == []


def test_sight_the_canary_is_still_seen_as_live_host():
    """If this fails, the detector went blind, not the canary safe."""
    assert ("canary.yml", "probe") in live_jobs(workflows())
    assert ("check.yml", "gate") not in live_jobs(workflows())


def test_every_exception_has_a_reason():
    for e in GUARD["live_host_exceptions"]:
        assert e["workflow"] and e["job"] and len(e["reason"]) > 40


def _wf(on, steps, extra=None):
    job = {"runs-on": "veron-1", "steps": steps, **(extra or {})}
    return {"on": on, "jobs": {"j": job}}


@pytest.mark.parametrize("doc, why", [
    (_wf({"push": {"branches": ["main"]}}, [{"run": "rsync -a dist/ host:/srv"}]), "live host"),
    (_wf({"pull_request": None}, [{"uses": "cloudflare/wrangler-action@v3"}]), "live host"),
    (_wf("push", [{"run": "deploy", "env": {"T": "${{ secrets.TOKEN }}"}}]), "live host"),
    (_wf({"schedule": [{"cron": "0 * * * *"}]}, [{"run": "gh release create v1"}]), "live host"),
    (_wf({"push": {"tags": ["v*"]}}, [{"run": "aws s3 sync out s3://b"}]), "live host"),
    (_wf({"pull_request": {"paths-ignore": ["docs/**"]}}, [{"run": "pytest"}]), "paths filter"),
    (_wf("[push, pull_request]", [{"run": "pytest"}]), None),                     # flow form, no filter: fine
    (_wf({"workflow_dispatch": None}, [{"run": "scp a b"}]), None),              # manual-only: fine
    (_wf({"push": None}, [{"run": "ssh host true"}], {"if": False}), None),       # if: false: fine
])
def test_negatives_and_allowed_forms(doc, why):
    doc = yaml.safe_load(yaml.safe_dump(doc)) if not isinstance(doc["on"], str) else \
        {"on": yaml.safe_load(doc["on"]) if doc["on"].startswith("[") else doc["on"], "jobs": doc["jobs"]}
    bad = violations({"x.yml": doc}, {"path_filter_exceptions": [], "live_host_exceptions": []})
    assert (any(why in b for b in bad) if why else bad == []), bad


def test_a_named_exception_that_gains_a_deploy_command_fails():
    docs = workflows()
    docs["canary.yml"]["jobs"]["probe"]["steps"].append({"run": "rsync -a out/ prod:/srv"})
    assert any("gained a deploy" in b for b in violations(docs, GUARD))


def test_a_new_unnamed_live_job_fails():
    docs = workflows()
    docs["new.yml"] = _wf({"schedule": [{"cron": "*/5 * * * *"}]}, [{"run": "curl", "env": {"K": "${{ secrets.K }}"}}])
    assert any(b.startswith("new.yml/j: live host") for b in violations(docs, GUARD))
