#!/usr/bin/env python3
"""lockbox-names: DISCOVER what the lockbox holds without reading it (Boss rule 10-01).

  lockbox-names [REGEX]        (case-insensitive; matches the section heading or the label)

Prints one row per entry: SECTION HEADING | LABEL | kind | resolvable
  kind        env   = `KEY=value` line            md = `- **`KEY`**: `value`` line
              label = a bold prose label (`**Password (X):** ...`)  file = secrets/**/*.env key
  resolvable  yes   = `lockbox-get LABEL FILE` returns exactly one value
              dup   = defined with 2+ different values (lockbox-get refuses)
              no    = a prose-only label, or not an exact key

NEVER prints a value or any prose after a label. A label or heading that itself looks
like a secret (secret_shapes) is replaced by <secret-shaped>. Memory only, stdout only.

Reads the COMMITTED lockbox at main's head, resolved ONCE, through the GitHub API (gh), the same road
as lockbox-get: no clone on disk is needed (Vault, 2026-11-12: a kit-army-config checkout is removed the
same hour, so no lockbox tool may depend on one). If gh cannot read it, lockbox-names FAILS; it never
falls back to a clone on its own.
  LOCKBOX_REF=<branch|40-hex sha>   read that instead of main
  LOCKBOX_SOURCE=clone              the old reader, on purpose: the local clone LOCKBOX_REPO (default
                                    ~/kit-army-config) at LOCKBOX_REF (default origin/main; WORKTREE = its
                                    working tree). LOCKBOX_REF=WORKTREE alone also means the clone.
  LOCKBOX_GH=<path>                 the gh to use (else PATH, then the usual places)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import secret_shapes as ss  # noqa: E402

REPO = os.environ.get("LOCKBOX_REPO", os.path.expanduser("~/kit-army-config"))
SOURCE = "clone" if os.environ.get("LOCKBOX_REF") == "WORKTREE" else os.environ.get("LOCKBOX_SOURCE", "api")
REF = os.environ.get("LOCKBOX_REF", "origin/main" if SOURCE == "clone" else "main")
OWNER, NAME, LOCKBOX = "sneakyfree", "kit-army-config", "ACCESS_LOCKBOX.md"
GH_PLACES = ("/opt/homebrew/bin/gh", "/usr/local/bin/gh", "/usr/bin/gh", "/home/linuxbrew/.linuxbrew/bin/gh",
             os.path.expanduser("~/bin/gh"), os.path.expanduser("~/.local/bin/gh"))


class ReadError(Exception):
    """The lockbox could not be read whole; the message never carries file text."""
HEAD = re.compile(r"^#{1,6}\s+(.*\S)\s*$")
ENV = re.compile(r"^([A-Z][A-Z0-9_]{2,})=(.*)$")
MD = re.compile(r"^\s*[-*]?\s*\*\*`([A-Za-z0-9_]+)`\*\*\s*:\s*`([^`]+)`")
LABEL = re.compile(r"\*\*([^*`]{2,70}?)\*\*")


def git(*a: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", REPO, *a], capture_output=True, text=True, errors="ignore")


def gh_path() -> str:
    import shutil
    if os.environ.get("LOCKBOX_GH"):
        if not os.access(os.environ["LOCKBOX_GH"], os.X_OK):
            raise ReadError("LOCKBOX_GH is not an executable gh")
        return os.environ["LOCKBOX_GH"]
    found = shutil.which("gh") or next((p for p in GH_PLACES if os.access(p, os.X_OK)), None)
    if not found:
        raise ReadError("gh not found: set LOCKBOX_GH=<path>, or LOCKBOX_SOURCE=clone on purpose")
    return found


def gh(args: list[str], stdin: bytes | None = None, raw: bool = False):
    r = subprocess.run([gh_path(), "api", *args], input=stdin, capture_output=True, timeout=120)
    if r.returncode != 0:
        what = next((a for a in args if a.startswith(("repos/", "graphql"))), "api").split("?")[0]
        raise ReadError(f"gh api failed ({what})")
    return r.stdout if raw else json.loads(r.stdout)


def api_sources() -> dict[str, str]:
    """{path: text} for ACCESS_LOCKBOX.md and secrets/**/*.env at ONE commit, read in memory through gh."""
    repo = f"repos/{OWNER}/{NAME}"
    sha = REF if re.fullmatch(r"[0-9a-f]{40}", REF) else gh([f"{repo}/git/ref/heads/{REF}"])["object"]["sha"]
    tree = gh([f"{repo}/git/trees/{sha}?recursive=1"])
    if tree.get("truncated"):
        raise ReadError("the repo tree came back truncated")
    paths = [x["path"] for x in tree["tree"]
             if x["type"] == "blob" and x["path"].startswith("secrets/") and x["path"].endswith(".env")]
    out: dict[str, str] = {}
    for i in range(0, len(paths), 50):                       # one GraphQL request per 50 files
        part = paths[i:i + 50]
        fields = "".join(f"f{j}:object(expression:{json.dumps(f'{sha}:{p}')})"
                         "{...on Blob{text isBinary isTruncated}}" for j, p in enumerate(part))
        q = f"query{{repository(owner:{json.dumps(OWNER)},name:{json.dumps(NAME)}){{{fields}}}}}"
        data = gh(["graphql", "--input", "-"], stdin=json.dumps({"query": q}).encode())["data"]["repository"]
        for j, p in enumerate(part):
            o = data.get(f"f{j}")
            if o is None or o.get("isTruncated"):
                raise ReadError(f"could not read {p} whole")
            if not o.get("isBinary"):
                out[p] = o.get("text") or ""
    md = gh(["-H", "Accept: application/vnd.github.raw", f"{repo}/contents/{LOCKBOX}?ref={sha}"], raw=True)
    return {LOCKBOX: md.decode("utf-8", "ignore"), **out}


def read_sources() -> dict[str, str]:
    """{path: text} for ACCESS_LOCKBOX.md and secrets/**/*.env."""
    if SOURCE == "api":
        return api_sources()
    if SOURCE != "clone":
        raise ReadError("LOCKBOX_SOURCE must be api or clone")
    if REF == "WORKTREE":
        out = {}
        for p in [Path(REPO, "ACCESS_LOCKBOX.md"), *Path(REPO, "secrets").rglob("*.env")]:
            if p.is_file():
                out[str(p.relative_to(REPO))] = p.read_text(errors="ignore")
        return out
    if REF.startswith("origin/"):
        git("fetch", "-q", "origin", REF.split("/", 1)[1])
    names = ["ACCESS_LOCKBOX.md"] + [
        p for p in git("ls-tree", "-r", "--name-only", REF, "--", "secrets").stdout.splitlines() if p.endswith(".env")]
    out = {}
    for n in names:
        r = git("show", f"{REF}:{n}")
        if r.returncode == 0:
            out[n] = r.stdout
    return out


def safe(text: str, limit: int = 70) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return "<secret-shaped>" if ss.find(text) else text[:limit]


def h(v: str) -> str:
    return hashlib.sha256(v.strip().strip('"').strip("'").encode()).hexdigest()[:16]


def collect(src: dict[str, str]):
    """(rows, values) where values[KEY] = {hash,...} for resolvability; nothing printed from it."""
    rows, values = [], {}
    for path, text in src.items():
        section = path
        for line in text.splitlines():
            m = HEAD.match(line) if path.endswith(".md") else None
            if m:
                section = safe(m.group(1), 90)
                continue
            m = ENV.match(line)
            if m:
                values.setdefault(m.group(1), set()).add(h(m.group(2)))
                rows.append((section, m.group(1), "file" if path.startswith("secrets/") else "env"))
                continue
            m = MD.match(line)
            if m:
                values.setdefault(m.group(1), set()).add(h(m.group(2)))
                rows.append((section, m.group(1), "md"))
                continue
            if path.endswith(".md"):
                mm = LABEL.search(line)
                if mm and not mm.group(1).startswith("http"):
                    rows.append((section, safe(mm.group(1)), "label"))
    return rows, values


def resolvable(label: str, kind: str, values) -> str:
    if kind not in ("env", "md", "file"):
        return "no"
    n = len(values.get(label, ()))
    return "yes" if n == 1 else "dup" if n > 1 else "no"


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    rx = re.compile(argv[0], re.I) if argv else None
    try:
        src = read_sources()
    except (ReadError, subprocess.TimeoutExpired, KeyError, ValueError) as e:
        msg = str(e) if isinstance(e, ReadError) else type(e).__name__
        print(f"lockbox-names: cannot read the lockbox: {msg}")
        return 2
    if not src:
        print("lockbox-names: cannot read the lockbox")
        return 2
    rows, values = collect(src)
    seen, n = set(), 0
    for section, label, kind in rows:
        if rx and not (rx.search(section) or rx.search(label)):
            continue
        key = (section, label, kind)
        if key in seen:
            continue
        seen.add(key)
        n += 1
        print(f"{section} | {label} | {kind} | {resolvable(label, kind, values)}")
    print(f"# {n} entr{'y' if n == 1 else 'ies'}; names only, values never printed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except re.error:
        print("lockbox-names: bad regex")
        sys.exit(2)
    except Exception as e:  # never a traceback
        print(f"lockbox-names: error: {type(e).__name__}")
        sys.exit(2)
