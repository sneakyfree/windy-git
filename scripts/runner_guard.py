#!/usr/bin/env python3
"""Runner guard: no workflow may let a STRANGER's code reach a self-hosted runner (Boss 10-01).

Our self-hosted GitHub runners run on Veron as `github-runner`, which is in the docker group
(= root on Veron). Until ephemeral containerised runners exist (after launch), the cheap
guard is to refuse the workflow shapes that hand a self-hosted runner to outsiders:

  R1 pull_request_target            : runs with secrets/write token in the BASE repo context
  R2 pull_request on self-hosted    : fork PRs run their own code, unless the job is gated to
                                      same-repo heads (`if:` on head.repo.full_name == github.repository
                                      or head.repo.fork == false) or an `environment:`
  R3 issue_comment / workflow_run / issues / discussion* / pull_request_review* / fork / watch
                                    : anyone can fire these; never on self-hosted without an environment gate
  (push, tags, schedule, workflow_dispatch, repository_dispatch, workflow_call: writers only, fine)

A job counts as self-hosted when its runs-on names `self-hosted`, or is an expression we
can't resolve (conservative). Findings carry file:line, never file content beyond that.

  python3 scripts/runner_guard.py lint FILE...              # local files
  python3 scripts/runner_guard.py report [--owners a,b]     # default branch of every PUBLIC repo
  python3 scripts/runner_guard.py pr [--owners a,b] [--post]  # open PRs on public repos: changed workflows
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import birth_terms  # noqa: E402  (same directory)

OWNERS = ["sneakyfree", "VERONTECH", "Windstorm-Institute", "Windstorm-Labs", "Public-Streamer"]
CTX = "windy-git/runner-guard"
BT_CTX = "windy-git/birth-terms"
OUTSIDE = {"issue_comment", "workflow_run", "issues", "discussion", "discussion_comment",
           "pull_request_review", "pull_request_review_comment", "fork", "watch"}
SAME_REPO_GATES = ("head.repo.full_name == github.repository", "github.repository == github.event.pull_request.head.repo.full_name",
                   "head.repo.fork == false", "!github.event.pull_request.head.repo.fork")


def _node_map(node):
    """{key: (value_node, line)} for a YAML mapping node."""
    if not isinstance(node, yaml.MappingNode):
        return {}
    return {k.value: (v, k.start_mark.line + 1) for k, v in node.value if isinstance(k, yaml.ScalarNode)}


def _triggers(on_node) -> dict[str, int]:
    """{event: line}."""
    if isinstance(on_node, yaml.ScalarNode):
        return {on_node.value: on_node.start_mark.line + 1}
    if isinstance(on_node, yaml.SequenceNode):
        return {n.value: n.start_mark.line + 1 for n in on_node.value if isinstance(n, yaml.ScalarNode)}
    return {k: line for k, (_v, line) in _node_map(on_node).items()}


def _self_hosted(runs_on) -> bool:
    if runs_on is None:
        return False
    text = yaml.serialize(runs_on) if isinstance(runs_on, yaml.Node) else str(runs_on)
    return "self-hosted" in text or "${{" in text


def lint_text(path: str, text: str) -> list[tuple[str, int, str, str]]:
    """[(path, line, rule, message)]. Unparseable YAML is a finding (it cannot be reviewed)."""
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as e:
        line = getattr(getattr(e, "problem_mark", None), "line", 0) + 1
        return [(path, line, "R0", "workflow YAML does not parse; cannot be checked")]
    top = _node_map(root)
    if "on" not in top or "jobs" not in top:
        return []
    trig = _triggers(top["on"][0])
    jobs = _node_map(top["jobs"][0])
    out = []
    if "pull_request_target" in trig:
        out.append((path, trig["pull_request_target"], "R1",
                    "pull_request_target runs fork code with base-repo secrets; not allowed"))
    for name, (jnode, jline) in jobs.items():
        j = _node_map(jnode)
        ro = j.get("runs-on", (None, jline))
        if not _self_hosted(ro[0]):
            continue
        has_env = "environment" in j
        cond = j["if"][0].value if "if" in j and isinstance(j["if"][0], yaml.ScalarNode) else ""
        same_repo = any(g in cond.replace("  ", " ") for g in SAME_REPO_GATES)
        if "pull_request" in trig and not (has_env or same_repo):
            out.append((path, ro[1], "R2", f"job '{name}' runs fork PR code on a self-hosted runner "
                        "(gate it: if: github.event.pull_request.head.repo.full_name == github.repository, or an environment)"))
        for ev in sorted(OUTSIDE & trig.keys()):
            if not has_env:
                out.append((path, trig[ev], "R3", f"'{ev}' can be fired by anyone and job '{name}' is self-hosted "
                            "without an environment gate"))
    return out


# ---------------------------------------------------------------- GitHub side
def gh(*args: str, check=True) -> str:
    r = subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=60)
    if check and r.returncode != 0:
        raise RuntimeError(f"gh api {args[0]} failed")
    return r.stdout


def public_repos(owners) -> list[tuple[str, str]]:
    out = []
    for o in owners:
        txt = gh(f"users/{o}/repos?per_page=100&type=owner", "--paginate",
                 "--jq", '.[]|select(.private==false and .archived==false)|.full_name+" "+.default_branch', check=False)
        out += [tuple(row.split()) for row in txt.splitlines() if row.strip()]
    return out


def workflows_at(full: str, ref: str) -> list[tuple[str, str]]:
    txt = gh(f"repos/{full}/contents/.github/workflows?ref={ref}", "--jq",
             '.[]|select(.type=="file")|.path', check=False)
    files = [p for p in txt.splitlines() if p.endswith((".yml", ".yaml"))]
    return [(p, file_at(full, p, ref)) for p in files]


class Unreadable(Exception):
    """GitHub didn't give us the bytes: never judge a file we didn't read (Hub, #53 B1)."""


def file_at(full: str, path: str, ref: str) -> str:
    """The file's text at ref. Raises Unreadable on any failure (403 rate limit, 404, 5xx,
    an empty or non-base64 .content): "" would lint clean and post a false OK."""
    try:
        raw = gh(f"repos/{full}/contents/{path}?ref={ref}", "--jq", ".content").strip()
    except (RuntimeError, subprocess.SubprocessError) as e:
        raise Unreadable(path) from e
    if not raw:
        raise Unreadable(path)
    try:
        return base64.b64decode(raw, validate=False).decode("utf-8", "replace")
    except (ValueError, TypeError) as e:
        raise Unreadable(path) from e


def cmd_report(owners) -> int:
    hits = 0
    repos = public_repos(owners)
    unreadable = []
    for full, branch in repos:
        try:
            pairs = workflows_at(full, branch)
        except Unreadable:
            unreadable.append(full)
            continue
        for path, text in pairs:
            for p, line, rule, msg in lint_text(path, text):
                hits += 1
                print(f"{full}\t{p}:{line}\t{rule}\t{msg}")
    if unreadable:  # never a green sweep over workflows it couldn't read
        print(f"# runner-guard sweep: ERROR ({len(unreadable)} repo(s) unreadable: {', '.join(unreadable)[:200]})")
        return 1
    print(f"# runner-guard sweep: {hits} hit(s) in {len(repos)} public repos")
    return 1 if hits else 0


STATE = os.environ.get("RUNNER_GUARD_STATE", "/var/lib/windy-git/runner-guard-posted.json")
FILES_CAP = 3000  # GitHub's PR files API never lists more


def _text_or_none(full: str, path: str, ref: str) -> str | None:
    try:
        return file_at(full, path, ref)
    except Unreadable:
        return None  # birth-terms: no glossary exemption; the finding stays


def pr_files(full: str, num: str) -> list[dict] | None:
    """[{f: filename, p: patch|None}] for an open PR, or None if GitHub didn't answer with a
    file list (an error body, HTML, rate limit): never parse an error as filenames."""
    try:  # every page (Hub #53 B2: a workflow in file 101+ was never seen)
        rows = gh(f"repos/{full}/pulls/{num}/files?per_page=100", "--paginate", "--jq",
                  '.[]|{f:.filename,p:.patch,s:.status}')
    except (RuntimeError, subprocess.SubprocessError):
        return None
    out, total = [], 0
    for r in rows.splitlines():
        if not r.strip():
            continue
        try:
            x = json.loads(r)
        except ValueError:
            return None
        if not isinstance(x, dict) or "message" in x or not isinstance(x.get("f"), str):
            return None
        total += 1
        if x.get("s") != "removed":
            out.append({"f": x["f"], "p": x.get("p")})
    if total >= FILES_CAP:  # GitHub lists at most 3,000 files: the rest are invisible to us
        return None
    return out


def cmd_pr(owners, post: bool) -> int:
    # Post each (repo, sha, state, description) ONCE: the sync runs every 5 min and GitHub caps
    # statuses per sha+context at 1000.
    try:
        with open(STATE) as fh:
            posted = set(json.load(fh))
    except (OSError, ValueError):
        posted = set()
    seen = set()

    def keep(full: str, sha: str) -> None:  # a skipped PR keeps what was already posted (Hub N1)
        seen.update(k for k in posted if k.startswith(f"{full}@{sha}:"))

    for full, _branch in public_repos(owners):
        prs = gh(f"repos/{full}/pulls?state=open&per_page=50", "--jq",
                 '.[]|(.number|tostring)+" "+.head.sha+" "+.head.repo.full_name', check=False)
        for line in prs.splitlines():
            num, sha, head_repo = line.split(" ", 2)
            # One files call per PR feeds both guards (filename + patch); the birth-terms
            # guard reads only the added lines of *.md patches (no extra GitHub call).
            pf = pr_files(full, num)
            if pf is None:  # the files call failed (403/404/5xx): no status from a broken answer
                print(f"{full}#{num}@{sha[:7]} skipped: PR files unreadable this run")
                keep(full, sha)
                continue
            files = [x["f"] for x in pf]
            wf = [f for f in files if f.startswith(".github/workflows/") and f.endswith((".yml", ".yaml"))]
            # a fork's own content is read from the head repo at the head sha
            src = head_repo if head_repo and head_repo != "null" else full
            bt = [h for x in pf for h in birth_terms.scan_patch(x["f"], x.get("p"),
                                                               lambda p, s=src, h=sha: _text_or_none(s, p, h))]
            bstate, bdesc, _ = birth_terms.status_for(bt)
            bkey = f"{full}@{sha}:{BT_CTX}:{bstate}:{bdesc}"
            seen.add(bkey)
            if bt and bkey not in posted:  # only when there is something to say (secondary rate limit)
                print(f"{full}#{num}@{sha[:7]} {BT_CTX} {bstate} {bdesc}")
                if post:
                    gh(f"repos/{full}/statuses/{sha}", "-f", f"state={bstate}", "-f", f"context={BT_CTX}",
                       "-f", f"description={bdesc}", check=False)
                    posted.add(bkey)
            try:
                found = [h for f in wf for h in lint_text(f, file_at(src, f, sha))]
            except Unreadable as e:  # Hub #53 B1: never an OK for a workflow we didn't read
                print(f"{full}#{num}@{sha[:7]} skipped: {e} unreadable this run")
                keep(full, sha)
                continue
            if found:
                p, ln, rule, msg = found[0]
                state, desc = "failure", f"BLOCKED: {rule} {p}:{ln}: {msg}"[:140]
            else:
                state, desc = "success", ("OK: no workflow changes" if not wf else
                                          "OK: no stranger-code path to a self-hosted runner")
            key = f"{full}@{sha}:{state}:{desc}"
            seen.add(key)
            if key in posted:
                continue
            print(f"{full}#{num}@{sha[:7]} {state} {desc}")
            if post:
                gh(f"repos/{full}/statuses/{sha}", "-f", f"state={state}", "-f", f"context={CTX}",
                   "-f", f"description={desc}", check=False)
                posted.add(key)
    if post:  # keep only keys for PRs still open, so the file never grows without bound
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w") as fh:
            json.dump(sorted(posted & seen), fh)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="runner_guard")
    sub = ap.add_subparsers(dest="cmd", required=True)
    lint_p = sub.add_parser("lint")
    lint_p.add_argument("files", nargs="+")
    rep = sub.add_parser("report")
    rep.add_argument("--owners", default=",".join(OWNERS))
    prp = sub.add_parser("pr")
    prp.add_argument("--owners", default="sneakyfree")  # self-hosted runners exist only there
    prp.add_argument("--post", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "lint":
        hits = []
        for f in a.files:
            with open(f, errors="replace") as fh:
                hits += lint_text(f, fh.read())
        for p_, ln, rule, msg in hits:
            print(f"{p_}:{ln}\t{rule}\t{msg}")
        return 1 if hits else 0
    owners = a.owners.split(",")
    return cmd_report(owners) if a.cmd == "report" else cmd_pr(owners, a.post)


if __name__ == "__main__":
    sys.exit(main())
