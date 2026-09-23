#!/usr/bin/env python3
"""Give private GitHub repos a CI signal from Windy Git (P1, 2026-09-23).

GitHub Actions cannot run on private repos on this account — not even on
self-hosted runners ([[reference-github-actions-billing-lock]]). The code is
already synced into Windy Git every 15 min and CI runs there, so the only thing
missing is the *signal on GitHub*, where people and agents actually read PRs.

Two jobs, run after every sync:

1. **Mirror open PRs.** The sync carries branches, not PRs, and the workflows
   trigger on `pull_request` — so a PR branch alone fires nothing. For each open
   same-repo GitHub PR we keep one open Windy Git PR with the same head/base.
   Gitea then fires `pull_request` on open and `synchronize` whenever the sync
   moves the branch. Windy Git PRs whose GitHub PR closed are closed here too.
   Fork PRs are ignored: their head branch is never synced, and untrusted fork
   code on this runner is exactly the blast radius the audit warned about.

2. **Post results back** as GitHub commit statuses (context
   `windy-git/<workflow>/<job>`) on each PR head and on the default-branch head.
   Only posts when a context's state changed, so a 15-min loop doesn't pile
   hundreds of identical statuses onto one commit.

Runs ON Veron 1 (localhost Gitea; no Cloudflare hairpin). Needs
GITEA_ADMIN_TOKEN and a GITHUB_TOKEN with `repo` scope. Nothing here executes
repo code, and no secret is handed to any repo.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

import yaml

GITEA = os.environ.get("BRIDGE_GITEA_URL", "http://localhost:3080").rstrip("/")
PUBLIC = "https://app.windygit.com"
GITEA_TOKEN = os.environ.get("GITEA_ADMIN_TOKEN", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GH_OWNER = os.environ.get("GITHUB_OWNER", "sneakyfree")
WG_OWNER = os.environ.get("WINDYGIT_OWNER", "windyadmin")
# Private repos only. Public repos run real GitHub Actions on veron1's GitHub
# runner; bridging those too would put two competing verdicts on every commit.
REPOS = os.environ.get(
    "BRIDGE_REPOS",
    "windy-chat windy-mail windy-calendar Windy-Clone WindyCloud windy-search windy-connect"
    " windy-drops windy-code-web windy-code windy-traveler windy-registry eternitas"
    " windy-translate windytranslate-site windytraveler-site windy-hand"
    " windy-cloud-sites windy-cloud-domains windy-cloud-vps windytalk windy-pro windy-mind",
).split()

# Gitea run status -> GitHub status state. `skipped` is deliberately absent: a
# job skipped by its own `if:` (e.g. substrate-drift's no-secrets path) has no
# verdict, and painting it green would be a claim nobody tested.
STATE = {
    "success": "success",
    "failure": "failure",
    "cancelled": "error",
    "running": "pending",
    "waiting": "pending",
    "blocked": "pending",
}
MIRROR_TAG = "[GH#"

# Image-build jobs cannot pass here BY DESIGN: job containers get no Docker
# daemon (I-5 — the host socket would hand every workflow root on Veron 1).
# Posting them would put a permanent red X on every commit, and a signal that is
# always red trains everyone to ignore red. Not posted until a rootless builder
# exists; that is a decision, recorded in docs/CUTOVER.md, not a failure.
NO_DAEMON_JOB = re.compile(r"docker", re.IGNORECASE)

# Jobs Grant ruled NON-BLOCKING (GRANT_DECISIONS_2026-09-23): still run on
# Windy Git and visible there, but not posted to GitHub, so they cannot turn a
# commit's combined status red. Format: "repo:workflow/job,workflow/job;repo2:..."
# windy-pro's desktop/installer jobs belong to Grant's desktop side (fixed from
# his Mac mini), not to any lane's merge gate.
NON_BLOCKING: dict[str, set[str]] = {}
for _entry in os.environ.get(
    "BRIDGE_NON_BLOCKING", "windy-pro:ci/build-desktop,ci/test-installer,ci/reality-check"
).split(";"):
    if ":" in _entry:
        _repo, _jobs = _entry.split(":", 1)
        NON_BLOCKING[_repo.strip()] = {j.strip() for j in _jobs.split(",") if j.strip()}


# Gitea reads the FIRST of these dirs that has workflow files at a commit (1.24).
WORKFLOW_DIRS = (".gitea/workflows", ".github/workflows")


def workflow_problem(text: str) -> str | None:
    """Why Gitea would drop this workflow file, or None if it looks runnable.

    Gitea skips an invalid workflow with one log line and fires no run at all,
    so on GitHub the PR just shows nothing, and people wait for CI that is never
    coming. These are the shapes we have actually hit, not a full schema.
    """
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        return f"invalid YAML at line {mark.line + 1}" if mark else "invalid YAML"
    if not isinstance(doc, dict):
        return "not a YAML mapping"
    if "on" not in doc and True not in doc:  # YAML 1.1 reads a bare `on` as True
        return "no `on:` trigger"
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return "no `jobs:`"
    for name, job in jobs.items():
        if not isinstance(job, dict):
            return f"job `{name}` is not a mapping"
        if "runs-on" not in job and "uses" not in job:
            return f"job `{name}` has no `runs-on:`"
    return None


def invalid_workflows(repo: str, sha: str) -> dict[str, tuple[str, str]]:
    """{context: (path, problem)} for each workflow file at `sha` that won't run."""
    for d in WORKFLOW_DIRS:
        st, entries = gitea("GET", f"/repos/{WG_OWNER}/{repo}/contents/{d}?ref={sha}")
        if st == 404:
            continue
        if st != 200:
            raise RuntimeError(f"{repo}: Windy Git {d}@{sha[:7]} -> {st}")
        files = [e for e in entries or [] if e.get("type") == "file"
                 and e["name"].endswith((".yml", ".yaml"))]
        if not files:
            continue
        bad = {}
        for e in files:
            st, f = gitea("GET", f"/repos/{WG_OWNER}/{repo}/contents/{e['path']}?ref={sha}")
            if st != 200:
                raise RuntimeError(f"{repo}: Windy Git {e['path']}@{sha[:7]} -> {st}")
            problem = workflow_problem(base64.b64decode(f["content"]).decode("utf-8", "replace"))
            if problem:
                stem = re.sub(r"\.ya?ml$", "", e["name"])
                bad[f"windy-git/{stem}/workflow"] = (e["path"], problem)
        return bad
    return {}


def _call(base: str, token_header: str, method: str, path: str, body=None):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Authorization": token_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
            # urllib's default UA is 403'd as a bot by GitHub's edge and CF.
            "User-Agent": "windy-git-pr-bridge/1",
        },
    )
    # Transport errors (TLS handshake timeout, reset) are retried: one GitHub
    # blip used to fail the whole sync, flip its heartbeat to ok:false and page
    # someone for nothing. HTTP errors are answers, not blips — never retried.
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            return e.code, None
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    raise AssertionError("unreachable")


def gitea(method, path, body=None):
    return _call(GITEA + "/api/v1", f"token {GITEA_TOKEN}", method, path, body)


def github(method, path, body=None):
    return _call("https://api.github.com", f"Bearer {GITHUB_TOKEN}", method, path, body)


def sync_prs(repo: str) -> list[str]:
    """Mirror open same-repo GitHub PRs into Windy Git. Returns their head shas."""
    st, gh_prs = github("GET", f"/repos/{GH_OWNER}/{repo}/pulls?state=open&per_page=100")
    if st != 200:
        raise RuntimeError(f"{repo}: GitHub PR list -> {st}")
    st, wg_prs = gitea("GET", f"/repos/{WG_OWNER}/{repo}/pulls?state=open&limit=50")
    if st != 200:
        raise RuntimeError(f"{repo}: Windy Git PR list -> {st}")
    ours = {p["title"].split("]")[0] + "]": p for p in wg_prs if p["title"].startswith(MIRROR_TAG)}

    heads, wanted = [], set()
    for pr in gh_prs:
        if pr["head"]["repo"] is None or pr["head"]["repo"]["full_name"] != f"{GH_OWNER}/{repo}":
            continue  # fork PR — never synced, never run here
        tag = f"{MIRROR_TAG}{pr['number']}]"
        wanted.add(tag)
        heads.append(pr["head"]["sha"])
        if tag in ours:
            continue
        st, _ = gitea(
            "POST",
            f"/repos/{WG_OWNER}/{repo}/pulls",
            {
                "head": pr["head"]["ref"],
                "base": pr["base"]["ref"],
                "title": f"{tag} {pr['title']}"[:250],
                "body": f"Mirror of {pr['html_url']} so CI runs here. Do not merge in Windy Git — "
                "GitHub is the source of truth; merge there.",
            },
        )
        print(f"  {repo}: opened mirror PR for GH#{pr['number']} -> {st}")

    for tag, p in ours.items():
        if tag not in wanted:
            gitea("PATCH", f"/repos/{WG_OWNER}/{repo}/pulls/{p['number']}", {"state": "closed"})
            print(f"  {repo}: closed mirror PR {tag} (closed on GitHub)")
    return heads


SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
SAFE_SHA = re.compile(r"^[0-9a-f]{40}$")


def queued_jobs(repo: str, sha: str) -> list[dict]:
    """Jobs at `sha` that are waiting for a runner and that a runner CAN take.

    Gitea 1.24's API lists only PICKED-UP jobs (/actions/tasks), so a queued PR
    showed nothing on GitHub and people asked whether the push was lost. The
    truth is in the gitea DB. Bounded + non-fatal: during the 09-23 IO stall
    `docker exec` hung for an hour and must never wedge the bridge again.

    Only status 5 (waiting) with labels some live runner has. A `pending` we
    post must end in a verdict we will also see, or it sits yellow forever:
    blocked jobs (7) often end SKIPPED, and jobs for labels no runner has
    (macos-/windows-/ubuntu-latest) are cancelled by the janitor unpicked;
    neither ever appears in /actions/tasks.
    """
    if not (SAFE_NAME.match(repo) and SAFE_NAME.match(WG_OWNER) and SAFE_SHA.match(sha)):
        return []
    query = (
        "select json_build_object("
        " 'jobs', (select coalesce(json_agg(t), '[]'::json) from ("
        "  select ar.index as run_number, ar.workflow_id, j.name, j.runs_on"
        "  from action_run_job j join action_run ar on ar.id = j.run_id"
        "  join repository r on r.id = j.repo_id join \"user\" o on o.id = r.owner_id"
        f"  where o.lower_name = '{WG_OWNER.lower()}' and r.lower_name = '{repo.lower()}'"
        f"  and ar.commit_sha = '{sha}' and j.status = 5) t),"
        " 'labels', (select coalesce(json_agg(agent_labels), '[]'::json)"
        "  from action_runner where coalesce(deleted, 0) = 0));"
    )
    try:
        out = subprocess.run(
            ["docker", "exec", "-i", "windy-git-db-1", "sh", "-c",
             'psql -U "$POSTGRES_USER" -d gitea -At -v ON_ERROR_STOP=1'],
            input=query, capture_output=True, text=True, check=True, timeout=30,
        ).stdout.strip()
        got = json.loads(out or "{}")
        runners = [set(json.loads(x or "[]")) for x in got.get("labels") or []]
        return [
            j for j in got.get("jobs") or []
            if any(set(json.loads(j.get("runs_on") or "[]")) <= r for r in runners)
        ]
    except (subprocess.SubprocessError, OSError, ValueError) as e:
        print(f"  {repo}: queued-job lookup skipped ({type(e).__name__})")
        return []


def post_statuses(repo: str, sha: str) -> None:
    # Gitea caps a page at 50 (MAX_RESPONSE_ITEMS) whatever `limit` says, and a
    # daily scheduled workflow can push a quiet main's runs off page 1.
    runs = []
    for page in range(1, 6):
        st, body = gitea("GET", f"/repos/{WG_OWNER}/{repo}/actions/tasks?limit=50&page={page}")
        if st != 200:
            raise RuntimeError(f"{repo}: Windy Git runs -> {st}")
        runs += body.get("workflow_runs", [])
        if len(body.get("workflow_runs", [])) < 50:
            break
    latest: dict[str, dict] = {}
    for r in runs:
        if r["head_sha"] != sha or NO_DAEMON_JOB.search(r["name"]):
            continue
        if f"{r['workflow_id'].removesuffix('.yml')}/{r['name']}" in NON_BLOCKING.get(repo, ()):
            continue
        ctx = f"windy-git/{r['workflow_id'].removesuffix('.yml')}/{r['name']}"
        if ctx not in latest or r["id"] > latest[ctx]["id"]:
            latest[ctx] = r
    # Queued jobs: `pending` where nothing newer has been picked up. A re-run
    # queued behind an old failure must read pending, not the stale red.
    for q in queued_jobs(repo, sha):
        if NO_DAEMON_JOB.search(q["name"]):
            continue
        wf = q["workflow_id"].removesuffix(".yml")
        if f"{wf}/{q['name']}" in NON_BLOCKING.get(repo, ()):
            continue
        ctx = f"windy-git/{wf}/{q['name']}"
        if ctx not in latest or q["run_number"] > latest[ctx]["run_number"]:
            latest[ctx] = {"id": 0, "status": "waiting", "run_number": q["run_number"]}
    bad = invalid_workflows(repo, sha)
    if not (latest or bad):
        return

    st, existing = github("GET", f"/repos/{GH_OWNER}/{repo}/commits/{sha}/statuses?per_page=100")
    current: dict[str, str] = {}
    for s in existing or []:  # newest first
        current.setdefault(s["context"], s["state"])

    for ctx, (path, problem) in sorted(bad.items()):
        if current.get(ctx) == "error":
            continue
        st, _ = github(
            "POST",
            f"/repos/{GH_OWNER}/{repo}/statuses/{sha}",
            {
                "state": "error",
                "context": ctx,
                "description": f"Windy Git ignored this workflow, no CI ran: {problem}"[:140],
                "target_url": f"{PUBLIC}/{WG_OWNER}/{repo}/src/commit/{sha}/{path}",
            },
        )
        print(f"  {repo}@{sha[:7]} {ctx} = error ({problem}) -> {st}")

    for ctx, r in sorted(latest.items()):
        state = STATE.get(r["status"])
        if state is None or current.get(ctx) == state:
            continue
        st, _ = github(
            "POST",
            f"/repos/{GH_OWNER}/{repo}/statuses/{sha}",
            {
                "state": state,
                "context": ctx,
                "description": f"Windy Git CI on Veron 1: {r['status']}"[:140],
                "target_url": f"{PUBLIC}/{WG_OWNER}/{repo}/actions/runs/{r['run_number']}",
            },
        )
        print(f"  {repo}@{sha[:7]} {ctx} = {state} -> {st}")


def main() -> int:
    if not (GITEA_TOKEN and GITHUB_TOKEN):
        sys.exit("GITEA_ADMIN_TOKEN and GITHUB_TOKEN are required")
    failed = 0
    for repo in REPOS:
        try:
            shas = sync_prs(repo)
            st, br = github("GET", f"/repos/{GH_OWNER}/{repo}")
            if st == 200:
                st, b = github("GET", f"/repos/{GH_OWNER}/{repo}/branches/{br['default_branch']}")
                if st == 200:
                    shas.append(b["commit"]["sha"])
            for sha in dict.fromkeys(shas):
                post_statuses(repo, sha)
        except Exception as e:  # one repo's failure must not hide the others'
            print(f"  FAILED {repo}: {e}")
            failed = 1
    return failed


if __name__ == "__main__":
    sys.exit(main())
