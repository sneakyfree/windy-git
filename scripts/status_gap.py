#!/usr/bin/env python3
"""Every open PR head (and each default-branch head) must get Windy Git CI statuses within 30 min.

Boss 10-28: two heads got none for hours. windy-pro #1582: its only change was under docs/**,
which ci.yml's pull_request paths-ignore skips, so no run was created at all. windy-admin
70a3c27: a main commit followed 42 s later by another, synced in ONE push; Gitea runs CI on a
push's head only. Neither was dropped, but nothing said so. This check says so.

For each repo the status bridge serves (BRIDGE_REPOS): every open same-repo PR head plus the
default-branch head. For each head older than GAP_MIN minutes, EVERY workflow that
should run for it (its `on:` event, branches and paths filters applied to the changed files) must
have at least one windy-git/<workflow>/<job> status. Otherwise:
  INFO  explained: the workflow is disabled in the repo's Gitea Actions settings (deploy / release
        / macOS-Windows builds, on purpose), its branches/paths filter skips it, nothing listens to
        the event, or it ran but only jobs the bridge hides by design (image builds, non-blocking)
  WARN  it should run and has no status: no Gitea run was created (e.g. an imported repo that
        never got a push), it ran and the bridge posted nothing, or the commit isn't on Windy Git
        at all (sync lag)
Main commits a newer head replaced are never checked (Gitea runs a push's head only), and the
log says so. COST: the sync token is shared with the status bridge, so a covered or explained
head is cached and never re-read, PR files are fetched only when a paths filter needs them, and
the run refuses when fewer than MIN_BUDGET GitHub calls are left. Output for windy-job --expect: "status gaps: none" or "status gaps: N (WARN to Boss
and the owner)".

  sudo python3 scripts/status_gap.py      (env: /etc/windygit/sync.env, as the bridge)
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pr_status_bridge as b  # noqa: E402  (same tokens, same API helpers, same repo list)

GAP_MIN = int(os.environ.get("STATUS_GAP_MIN", "30"))
STATE = Path(os.environ.get("STATUS_GAP_STATE", "/var/lib/windygit/status-gap.json"))
# The sync token is SHARED with the status bridge, whose posts the whole fleet waits on. A run
# needs about 100 calls; below this budget it refuses (10-28: dry runs emptied the quota once).
MIN_BUDGET = int(os.environ.get("STATUS_GAP_MIN_BUDGET", "1500"))


def _glob_re(pat: str) -> re.Pattern[str]:
    """GitHub-style path filter: `**` crosses `/`, `*` and `?` don't."""
    out, i = "", 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pat.startswith("**", i):
            out += ".*"
            i += 2
        elif pat[i] == "*":
            out += "[^/]*"
            i += 1
        elif pat[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pat[i])
            i += 1
    return re.compile(out + r"\Z")


def _matches(path: str, patterns: list[str]) -> bool:
    """`paths` semantics: the LAST pattern that matches decides; a leading ! excludes."""
    hit = False
    for p in patterns:
        neg = p.startswith("!")
        if _glob_re(p[1:] if neg else p).match(path):
            hit = not neg
    return hit


def triggers(on, event: str, files: list[str], branch: str = "main") -> bool | None:
    """True/False: does a workflow with this `on:` run for `event` (push to `branch`, or a PR
    into `branch`) on these changed files? None: it doesn't listen to `event` at all."""
    if isinstance(on, str):
        on = {on: None}
    elif isinstance(on, list):
        on = dict.fromkeys(on)
    if not isinstance(on, dict) or event not in on:
        return None
    spec = on[event] or {}
    if "branches" in spec and not _matches(branch, [str(x) for x in spec["branches"]]):
        return False
    if "branches-ignore" in spec and _matches(branch, [str(x) for x in spec["branches-ignore"]]):
        return False
    if not files:
        return True
    if "paths" in spec:
        return any(_matches(f, list(spec["paths"])) for f in files)
    if "paths-ignore" in spec:
        return not all(_matches(f, list(spec["paths-ignore"])) for f in files)
    return True


def workflow_ons(repo: str, sha: str) -> dict[str, object]:
    """{workflow file: its `on:`} at sha, from Windy Git (.gitea/workflows wins over .github)."""
    for d in (".gitea/workflows", ".github/workflows"):
        st, entries = b.gitea("GET", f"/repos/{b.WG_OWNER}/{repo}/contents/{d}?ref={sha}")
        if st != 200 or not isinstance(entries, list):
            continue
        out = {}
        for e in entries:
            if not e.get("name", "").endswith((".yml", ".yaml")):
                continue
            st, f = b.gitea("GET", f"/repos/{b.WG_OWNER}/{repo}/contents/{e['path']}?ref={sha}")
            if st != 200:
                continue
            try:
                doc = yaml.safe_load(base64.b64decode(f.get("content") or ""))
            except yaml.YAMLError:
                continue
            if isinstance(doc, dict):
                # PyYAML reads the bare key `on` as True.
                out[e["name"]] = doc.get("on", doc.get(True))
        if out:
            return out
    return {}


def psql(sql: str) -> list[list[str]]:
    out = subprocess.run(
        ["docker", "exec", "-i", "windy-git-db-1", "sh", "-c",
         'psql -U "$POSTGRES_USER" -d gitea -At -F "|" -v ON_ERROR_STOP=1'],
        input=sql, capture_output=True, text=True, check=True, timeout=30,
    ).stdout.strip()
    return [line.split("|") for line in out.splitlines() if line]


def run_jobs(repo: str, sha: str, wf_file: str, query=psql) -> list[str] | None:
    """Job names of Gitea runs of wf_file at sha; None when there is no run at all."""
    if not (b.SAFE_NAME.match(repo) and b.SAFE_SHA.match(sha) and b.SAFE_NAME.match(wf_file)):
        return None
    rows = query(
        "select r.id, j.name from action_run r join repository p on p.id = r.repo_id "
        "left join action_run_job j on j.run_id = r.id "
        f"where p.lower_name = '{repo.lower()}' and r.commit_sha = '{sha}' and r.workflow_id = '{wf_file}';")
    return [r[1] for r in rows if len(r) > 1 and r[1]] if rows else None


def has_path_filter(on, event: str) -> bool:
    """Does this workflow filter `event` by paths? (Only then are the changed files needed.)"""
    if isinstance(on, dict) and isinstance(on.get(event), dict):
        return "paths" in on[event] or "paths-ignore" in on[event]
    return False


def api_budget() -> int:
    """Calls left on the sync token (GET /rate_limit itself is free)."""
    st, body = b.github("GET", "/rate_limit")
    try:
        return int(body["resources"]["core"]["remaining"]) if st == 200 else 0
    except (KeyError, TypeError, ValueError):
        return 0


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def disabled_workflows(repo: str, query=psql) -> set[str]:
    """Workflow files the repo's Gitea Actions settings disable ON PURPOSE (deploy, release, macOS /
    Windows builds: they must not run on Windy Git). Gitea creates no run for them."""
    if not b.SAFE_NAME.match(repo):
        return set()
    rows = query("select u.config from repo_unit u join repository r on r.id = u.repo_id "
                 f"where r.lower_name = '{repo.lower()}' and u.type = 10;")
    try:
        return set(json.loads("|".join(rows[0])).get("DisabledWorkflows") or []) if rows else set()
    except (ValueError, AttributeError):
        return set()


def evaluate(repo: str, contexts: list[str], decisions: dict[str, bool | None], jobs_of,
             disabled: frozenset[str] = frozenset()) -> tuple[list[str], list[str]]:
    """(warns, infos) for ONE head older than GAP_MIN. Each workflow that should run must have
    at least one windy-git/<workflow>/<job> status (the bridge's context: the file name minus .yml)."""
    warns, infos = [], []
    listening = {w: d for w, d in decisions.items() if d is not None}
    if not listening:
        return [], ["no workflow listens to this event"]
    for wf, runs_here in sorted(listening.items()):
        stem = wf.removesuffix(".yml")
        if wf in disabled:
            infos.append(f"{wf} is disabled on Windy Git by design (repo Actions settings)")
            continue
        if not runs_here:
            infos.append(f"{wf} skipped by its branches/paths filter")
            continue
        if any(c.startswith(f"windy-git/{stem}/") for c in contexts):
            continue
        jobs = jobs_of(wf)
        if jobs is None:
            warns.append(f"no Gitea run was created although {wf} should run")
        elif jobs and all(b.needs_daemon(repo, stem, j) or f"{stem}/{j}" in b.NON_BLOCKING.get(repo, ())
                          for j in jobs):
            infos.append(f"{wf} ran, but only jobs the bridge hides by design (image builds / non-blocking)")
        else:
            warns.append(f"{wf} ran on Windy Git but no windy-git/{stem}/* status was posted (bridge)")
    return warns, infos


def _age_min(iso: str, now: float) -> float:
    return (now - datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()) / 60


def main() -> int:
    now = time.time()
    budget = api_budget()
    if budget < MIN_BUDGET:
        print(f"status gaps: skipped (GitHub API budget {budget} < {MIN_BUDGET}; the bridge needs it more)")
        return 0
    state = load_state()
    done: dict[str, str] = state.get("done", {})          # sha -> "ok" | "info" (never re-read)
    branches: dict[str, str] = state.get("default_branch", {})
    warns, infos, checked, seen = [], [], 0, set()
    print("main: only each default-branch HEAD is checked; commits a newer head replaced in the same "
          "push are skipped by design (Gitea runs a push's head only)")
    for repo in b.REPOS:
        try:
            st, prs = b.github("GET", f"/repos/{b.GH_OWNER}/{repo}/pulls?state=open&per_page=100")
            heads = []
            for pr in prs if st == 200 else []:
                if (pr["head"].get("repo") or {}).get("full_name") != f"{b.GH_OWNER}/{repo}":
                    continue
                heads.append((f"PR #{pr['number']}", pr["head"]["sha"], pr["updated_at"], "pull_request",
                              pr["base"]["ref"], f"/repos/{b.GH_OWNER}/{repo}/pulls/{pr['number']}/files?per_page=100"))
            if repo not in branches:
                st, rp = b.github("GET", f"/repos/{b.GH_OWNER}/{repo}")
                if st == 200:
                    branches[repo] = rp["default_branch"]
            dbr = branches.get(repo, "main")
            st, br = b.github("GET", f"/repos/{b.GH_OWNER}/{repo}/branches/{dbr}")
            if st == 200:
                c = br["commit"]
                heads.append((dbr, c["sha"], c["commit"]["committer"]["date"], "push", dbr,
                              f"/repos/{b.GH_OWNER}/{repo}/commits/{c['sha']}"))
            off = None
            for label, sha, when, event, branch, files_path in heads:
                checked += 1
                seen.add(sha)
                age = _age_min(when, now)
                if sha in done or age < GAP_MIN:
                    continue
                head = f"{repo} {label} {sha[:8]} ({age:.0f} min)"
                st, _ = b.gitea("GET", f"/repos/{b.WG_OWNER}/{repo}/git/commits/{sha}")
                if st == 404:  # GitHub has it, Windy Git doesn't: the sync is behind, so nothing can run
                    warns.append(f"{head}: commit is not on Windy Git (sync lag)")
                    continue
                contexts = [s["context"] for s in b.commit_statuses(repo, sha)]
                ons = workflow_ons(repo, sha)
                files: list[str] = []
                uncovered = [w for w, on in ons.items()
                             if not any(c.startswith(f"windy-git/{w.removesuffix('.yml')}/") for c in contexts)]
                if any(has_path_filter(ons[w], event) for w in uncovered):   # files only when a filter decides
                    st, body = b.github("GET", files_path)
                    files = [f["filename"] for f in (body if event == "pull_request" else body.get("files", []))] \
                        if st == 200 else []
                if off is None:
                    off = frozenset(disabled_workflows(repo))
                decisions = {w: triggers(on, event, files, branch) for w, on in ons.items()}
                w, i = evaluate(repo, contexts, decisions, lambda wf, _r=repo, _s=sha: run_jobs(_r, _s, wf), off)
                warns += [f"{head}: {x}" for x in w]
                infos += [f"{head}: {x}" for x in i]
                if not w:
                    done[sha] = "info" if i else "ok"
        except Exception as e:  # noqa: BLE001 - one repo's failure must not hide the others
            warns.append(f"{repo}: check failed ({type(e).__name__}: {str(e)[:80]})")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"done": {k: v for k, v in done.items() if k in seen},
                                 "default_branch": branches}, sort_keys=True))
    for line in infos:
        print("INFO " + line)
    for line in warns:
        print("WARN " + line)
    print(f"checked {checked} heads in {len(b.REPOS)} repos (GitHub budget at start: {budget})")
    print("status gaps: none" if not warns else f"status gaps: {len(warns)} (WARN to Boss and the owner)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
