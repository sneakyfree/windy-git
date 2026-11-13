#!/usr/bin/env python3
"""Docs-only heads start no test job (rule P4: Windy Boss GO 2026-11-11T04:56:12Z, terms (1)-(3)).

On 2026-11-11, 21 percent of the jobs queued from 00:00Z were for heads whose whole diff was TODO.md, a README
or docs/, and a test run on such a head can prove nothing new. So, for a WAITING head (status 5, 7 or 9, task_id 0):

  * DOCS HEAD = every changed path is on the STRICT list: TODO.md (any folder), README* (any folder), docs/**.
    Never "any .md": ACCESS_LOCKBOX.md and the doctrine files are .md and are not docs (term 1).
    The diff is the PR head against its merge-base with the default branch; for a push, the commit's own
    first-parent diff. Read from the sync's bare caches (no GitHub call).
  * READ BY TESTS = some test or CI file AT THAT HEAD names a changed path (the exact path, a basename for TODO.md /
    README*, one of its docs/ folders, or a bare docs/). Then the head is NOT skipped: a docs change can break a
    test that reads it (windy-pro's tests read docs/legal, docs/contracts, the handtest ledger).
  * EXCLUDED repos by NAME (term 2): EXCLUDE below (none today); PUSH_EXCLUDE: a default-branch push there
    always runs the whole suite (windy-pro); also every repo the bridge does not post for.
  * PUSH GUARD: any other default-branch push skips a job only when the same job ENDED SUCCESS at its first parent
    (through parents this rule skipped); a red, cancelled or missing parent job means the push runs. PUSHES below.
  * PER EVENT (Boss note 2026-11-12T10:15:45Z): a sha can be a PR head AND a default-branch push; each job is
    decided by ITS OWN event (the PR diff vs the push diff; the push guard on push jobs only), one state entry
    per kind ("<repo>@<sha>" for PR heads, "<repo>@<sha>#push" for pushes).
  * KEPT workflows: any whose file stem names lint, guard, drift, doc, todo, secret, link or spell. They read
    the very files a docs head changes, so they still run.

DARK (default): nothing is touched; each docs head is logged once with the jobs it WOULD cancel.
ON (the file ON_FILE exists, Boss's stamp): those jobs are cancelled with the same guards as cancel_superseded
(still waiting and unclaimed, in ONE statement that returns what it cancelled), their runs closed when nothing is
left, and the head's contexts recorded in STATE, from which the bridge posts each as success with the
description DESC (term 3: a reader of the statuses can tell a skipped test from a passed one).
Never fails the sync.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cancel_superseded as cs  # noqa: E402  (psql, board, close-run SQL)

SYNC_ROOT = Path(os.environ.get("DOCS_ONLY_SYNC_ROOT", "/srv/windygit/sync"))
STATE = Path(os.environ.get("DOCS_ONLY_STATE", "/var/lib/windygit/docs-only.json"))
LOG = Path(os.environ.get("DOCS_ONLY_LOG", "/var/log/windygit/docs-only.log"))
ON_FILE = Path(os.environ.get("DOCS_ONLY_ON", "/etc/windygit/docs-only.on"))
OWNER = os.environ.get("WINDYGIT_OWNER", "windyadmin")
# Term (2): repos excluded BY NAME (none today: no repo publishes from docs/ or serves its README).
EXCLUDE = set(os.environ.get("DOCS_ONLY_EXCLUDE", "").split())
# Repos whose DEFAULT-BRANCH PUSH always runs the whole suite, docs-only or not (Boss RULING 2026-11-11T05:06:52Z:
# windy-pro's release cut reads main's own green). Their PR heads follow the rule like every other repo.
PUSH_EXCLUDE = set(os.environ.get("DOCS_ONLY_PUSH_EXCLUDE", "windy-pro").split())
# A default-branch push carries the code before it, so a docs-only PUSH may skip a job only when the SAME job (workflow
# file + job name, a push to the same ref) at its first parent ENDED SUCCESS, or was itself skipped by this rule at a
# parent that did (P9: never paint a code red green; dark day 2026-11-11/12: 14 of 110 such push jobs failed). While
# that parent job still waits or runs, nothing is decided and the next pass looks again.
# DOCS_ONLY_PUSHES=off: no push is ever skipped (PR heads only).
PUSHES = os.environ.get("DOCS_ONLY_PUSHES", "guarded").strip().lower()
PARENT_DEPTH = 5
DESC = "docs-only head: no test job (rule P4)"
KEEP_WF = re.compile(r"lint|guard|drift|doc|todo|secret|link|spell", re.IGNORECASE)
MAX_HEADS = int(os.environ.get("DOCS_ONLY_MAX_HEADS", "40"))   # per pass: bounded git work
STATE_DAYS = 7

SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
SAFE_SHA = re.compile(r"^[0-9a-f]{40}$")
TEST_FILE = re.compile(r"(^|/)(tests?|__tests__|spec|e2e)/|\.test\.[cm]?[jt]sx?$|\.spec\.[cm]?[jt]sx?$"
                       r"|(^|/)test_[^/]*\.py$|_test\.(py|go)$|^\.(github|gitea)/workflows/|^scripts/ci/")
CODE_FILE = re.compile(r"\.(py|[cm]?[jt]sx?|sh|ya?ml|go|rs|json|toml)$")


def is_docs_path(path: str) -> bool:
    """Term (1), the STRICT list. Nothing else is a docs path, whatever its extension."""
    base = path.rsplit("/", 1)[-1]
    return base == "TODO.md" or base.upper().startswith("README") or path.startswith("docs/")


def _git(repo: str, *args: str, timeout: int = 60) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", "--git-dir", str(SYNC_ROOT / f"{repo}.git"), *args],
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except (subprocess.SubprocessError, OSError):
        return 1, ""


def changed_paths(repo: str, sha: str, event: str) -> list[str] | None:
    """The head's whole diff; None when it cannot be read (then the head is never skipped)."""
    if _git(repo, "cat-file", "-e", f"{sha}^{{commit}}")[0] != 0:
        return None
    if event.startswith("pull_request"):
        base = ""
        for ref in ("refs/heads/main", "refs/heads/master"):
            rc, out = _git(repo, "merge-base", ref, sha)
            if rc == 0 and out.strip():
                base = out.strip()
                break
        if not base:
            return None
        rc, out = _git(repo, "diff", "--name-only", "--no-renames", base, sha)
    else:
        rc, out = _git(repo, "diff-tree", "--no-commit-id", "--name-only", "--no-renames", "-r", "-m",
                       "--first-parent", sha)
    if rc != 0:
        return None
    return [p for p in out.splitlines() if p]


def _keys(path: str) -> list[str]:
    """What a test would write to read `path`: the path itself, its basename (TODO.md, README*), or a docs/ folder."""
    if path.startswith("docs/"):
        parts = path.split("/")
        return [path] + ["/".join(parts[:i]) + "/" for i in range(len(parts) - 1, 1, -1)]
    return [path, path.rsplit("/", 1)[-1]]


def read_by_tests(repo: str, sha: str, paths: list[str]) -> bool:
    """True when any test or CI file at `sha` names one of `paths` (or a bare docs/ for a docs/ path).
    Unreadable = True (fail closed: the head runs its tests)."""
    rc, out = _git(repo, "ls-tree", "-r", "--name-only", sha)
    if rc != 0:
        return True
    files = [f for f in out.splitlines()
             if TEST_FILE.search(f) and CODE_FILE.search(f) and not f.startswith(("node_modules/", "docs/"))]
    if not files:
        return False
    pats = {re.escape(k) for p in paths for k in _keys(p)}
    if any(p.startswith("docs/") for p in paths):
        pats.add(r"""(^|[^A-Za-z0-9_.-])docs/?(['"`)\s]|$)""")   # the whole docs/ folder
    pattern = "|".join(sorted(pats))
    for i in range(0, len(files), 300):
        rc, _ = _git(repo, "grep", "-I", "-q", "-E", pattern, sha, "--", *files[i:i + 300])
        if rc == 0:
            return True
        if rc not in (0, 1):
            return True   # grep failed: fail closed
    return False


def docs_head(repo: str, sha: str, event: str) -> tuple[bool, str]:
    """(skip?, why). Skip only a strict docs-only diff that no test or CI file reads."""
    paths = changed_paths(repo, sha, event)
    if paths is None:
        return False, "diff unreadable"
    if not paths:
        return False, "empty diff"
    if not all(is_docs_path(p) for p in paths):
        return False, "not docs-only"
    if read_by_tests(repo, sha, paths):
        return False, "docs-only but read by tests"
    return True, f"docs-only, {len(paths)} path(s): " + ", ".join(paths[:5])


def candidates_sql() -> str:
    return f"""
select j.id, p.name, r.event, r.ref, j.commit_sha, r.workflow_id, j.name, r.index
from action_run_job j join action_run r on r.id = j.run_id
join repository p on p.id = j.repo_id join "user" o on o.id = p.owner_id
where o.lower_name = '{OWNER.lower()}' and j.status in (5, 7, 9) and j.task_id = 0
  and ((r.event in ('pull_request', 'pull_request_sync') and r.ref like 'refs/pull/%/head')
       or (r.event = 'push' and r.ref in ('refs/heads/main', 'refs/heads/master')))
order by j.id;
"""


def _q(v: str) -> str:
    return "'" + v.replace("'", "''") + "'"


def parent_sha(repo: str, sha: str) -> str | None:
    rc, out = _git(repo, "rev-parse", "--verify", "-q", f"{sha}^1")
    p = out.strip()
    return p if rc == 0 and SAFE_SHA.match(p) else None


def parent_job_sql(repo: str, ref: str, sha: str, wf: str, job: str) -> str:
    return f"""
select j.id, j.status from action_run_job j join action_run r on r.id = j.run_id
join repository p on p.id = j.repo_id join "user" o on o.id = p.owner_id
where o.lower_name = {_q(OWNER.lower())} and p.name = {_q(repo)} and r.event = 'push' and r.ref = {_q(ref)}
  and j.commit_sha = {_q(sha)} and r.workflow_id = {_q(wf)} and j.name = {_q(job)}
order by j.id desc limit 1;
"""


def parent_green(query, st: dict, repo: str, ref: str, sha: str, wf: str, job: str, parent=None) -> bool | None:
    """True: the same job ended success at the first parent (through parents this rule skipped, at most PARENT_DEPTH).
    None: that job still waits or runs, decide later. False: anything else (red, cancelled, missing, unreadable)."""
    parent = parent or parent_sha
    cur = sha
    for _ in range(PARENT_DEPTH):
        p = parent(repo, cur)
        if not p:
            return False
        rows = query(parent_job_sql(repo, ref, p, wf, job))
        if not rows or len(rows[0]) < 2:
            return False
        jid, status = rows[0][0], rows[0][1]
        if status == "1":
            return True
        if status in ("5", "6", "7", "9"):
            return None
        if status == "3" and jid.isdigit() and any(e.get("mode") == "on" and int(jid) in e.get("jobs", [])
                                                    for e in _entries(st, repo, p)):
            cur = p
            continue
        return False
    return False


def cancel_sql(ids: list[int]) -> str:
    lst = ",".join(str(int(i)) for i in ids)
    return f"""
update action_run_job j set status = 3, stopped = extract(epoch from now())::bigint,
       updated = extract(epoch from now())::bigint
where j.id in ({lst}) and j.status in (5, 7, 9) and j.task_id = 0
returning j.id, j.run_id;
"""


def _kind(event: str) -> str:
    return "push" if event == "push" else "pr"


def _key(repo: str, sha: str, kind: str) -> str:
    """One decision per (repo, sha, EVENT KIND) (Boss note 2026-11-12T10:15:45Z): a sha can be a PR head AND a
    default-branch push (a fast-forward merge), and the two diffs differ (PR: against the merge-base; push: the
    commit's own). PR heads keep the plain key (the bridge reads it); a push decision is "<repo>@<sha>#push"."""
    return f"{repo}@{sha}" + ("#push" if kind == "push" else "")


def _entries(st: dict, repo: str, sha: str) -> list[dict]:
    return [e for e in (st.get(f"{repo}@{sha}"), st.get(f"{repo}@{sha}#push")) if isinstance(e, dict)]


def load_state() -> dict:
    try:
        st = json.loads(STATE.read_text())
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(st: dict) -> None:
    cut = time.time() - STATE_DAYS * 86400
    st = {k: v for k, v in st.items() if isinstance(v, dict) and v.get("at", 0) >= cut}
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, sort_keys=True))
        os.replace(tmp, STATE)
    except OSError:
        pass


def _log(lines: list[str]) -> None:
    if not lines:
        return
    print("\n".join("  " + x for x in lines))
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass


def main(query=cs.psql, post=cs.board, decide=docs_head, repos=None, now=time.time) -> int:
    on = ON_FILE.exists()
    if repos is None:
        import pr_status_bridge as bridge  # the bridge's own repo list: no status is posted anywhere else
        repos = set(bridge.REPOS)
    try:
        rows = query(candidates_sql())
    except Exception as e:  # noqa: BLE001 - never fails the sync
        print(f"  docs-only: skipped ({type(e).__name__})")
        return 0
    heads: dict[tuple[str, str], list[list[str]]] = {}
    for r in rows:
        if len(r) < 8 or not r[0].isdigit():
            continue
        repo, sha = r[1], r[4]
        if repo in EXCLUDE or repo not in repos or not (SAFE_NAME.match(repo) and SAFE_SHA.match(sha)):
            continue
        if r[2] == "push" and repo in PUSH_EXCLUDE:
            continue
        heads.setdefault((repo, sha), []).append(r)
    st = load_state()
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now()))
    lines: list[str] = []
    cancelled_total: dict[str, int] = {}
    work: list[tuple[str, str, str, list[list[str]]]] = []
    for (repo, sha), all_jobs in list(heads.items())[:MAX_HEADS]:
        by_kind: dict[str, list[list[str]]] = {}
        for j in all_jobs:                       # each job by ITS OWN event, never the group's first row
            by_kind.setdefault(_kind(j[2]), []).append(j)
        work += [(repo, sha, kind, by_kind[kind]) for kind in sorted(by_kind)]
    for repo, sha, kind, jobs in work:
        key = _key(repo, sha, kind)
        prev = st.get(key)
        if prev and (prev.get("mode") == "on" or (prev.get("mode") == "dark" and not on) or prev.get("skip") is False):
            continue   # decided before (a head's diff for one event kind never changes)
        skip, why = decide(repo, sha, jobs[0][2])
        victims = [j for j in jobs if not KEEP_WF.search(j[5].rsplit(".", 1)[0])]
        if skip and victims and kind == "push":
            if PUSHES == "off":
                victims, why = [], "push: DOCS_ONLY_PUSHES=off"
            else:
                try:
                    green = {j[0]: parent_green(query, st, repo, j[3], sha, j[5], j[6]) for j in victims}
                except Exception as e:  # noqa: BLE001 - never fails the sync; the push runs
                    print(f"  docs-only: {repo}@{sha[:8]} parent read skipped ({type(e).__name__})")
                    continue
                if any(v is None for v in green.values()):
                    continue   # a parent job still waits or runs: decide on a later pass
                victims = [j for j in victims if green[j[0]]]
                if not victims:
                    why = "push: the parent's same job did not end success"
        if not skip or not victims:
            st[key] = {"at": now(), "skip": False,
                       "why": why if not skip or why.startswith("push:") else "only kept workflows"}
            continue
        if not on:
            st[key] = {"at": now(), "skip": True, "mode": "dark", "why": why, "would": [int(j[0]) for j in victims]}
            lines += [f"{stamp} DARK would cancel job {j[0]} {repo} {j[3]} {sha[:8]} {j[5]}/{j[6]} ({why})" for j in victims]
            continue
        try:
            done = query(cancel_sql([int(j[0]) for j in victims]))
            run_ids = sorted({d[1] for d in done if len(d) > 1 and d[1].isdigit()})
            if run_ids:
                query(cs.CLOSE_RUNS_SQL.format(ids=",".join(run_ids)))
                if cs._has_attempts(query):
                    query(cs.CLOSE_ATTEMPTS_SQL.format(ids=",".join(run_ids)))
        except Exception as e:  # noqa: BLE001
            print(f"  docs-only: {repo}@{sha[:8]} cancel skipped ({type(e).__name__})")
            continue
        got = {d[0] for d in done}
        ctxs = sorted({(f"windy-git/{j[5].removesuffix('.yml').removesuffix('.yaml')}/{j[6]}", int(j[7]) if j[7].isdigit() else 0)
                       for j in victims if j[0] in got})
        st[key] = {"at": now(), "skip": True, "mode": "on", "why": why, "jobs": sorted(int(x) for x in got),
                   "contexts": [{"context": c, "run": n} for c, n in ctxs]}
        lines += [f"{stamp} cancelled job {j[0]} {repo} {j[3]} {sha[:8]} {j[5]}/{j[6]} ({why})" for j in victims if j[0] in got]
        if got:
            cancelled_total[repo] = cancelled_total.get(repo, 0) + len(got)
    save_state(st)
    _log(lines)
    if cancelled_total:
        post(f"[Windy Git] docs-only: {sum(cancelled_total.values())} test job(s) on docs-only heads not started ("
             + ", ".join(f"{k} {v}" for k, v in sorted(cancelled_total.items()))
             + f"); their checks read '{DESC}'. Log: {LOG}")
    return 0


def contexts_for(repo: str, sha: str, state: dict | None = None) -> list[dict]:
    """For the bridge: the contexts this rule skipped at repo@sha (ON mode only), [] otherwise."""
    st = state if state is not None else load_state()
    out, seen = [], set()
    for e in _entries(st, repo, sha):            # a commit status is per sha: both event kinds count
        if e.get("mode") != "on":
            continue
        for c in e.get("contexts", []):
            if isinstance(c, dict) and isinstance(c.get("context"), str) and c["context"] not in seen:
                seen.add(c["context"])
                out.append(c)
    return out


if __name__ == "__main__":
    sys.exit(main())
