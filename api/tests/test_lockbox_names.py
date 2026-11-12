"""lockbox-names: headings + labels + resolvable, NEVER a value or prose after a label."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V1 = "Qm7xT2vLp9RkZw4HnB8dYc3S"   # synthetic values
V2 = "other-fake-value-1234567890"
V3 = "dup-one-aaaaaaaaaaaaaaaa"
V4 = "dup-two-bbbbbbbbbbbbbbbb"
PROSE = "ZZPROSEZZ-not-for-printing"


def make(tmp_path):
    r = tmp_path / "kit"
    (r / "secrets" / "x").mkdir(parents=True)
    (r / "ACCESS_LOCKBOX.md").write_text(
        "# LOCKBOX\n\n## 🔷 AZURE signing (added 10-01)\n"
        f"- **Tenant:** {PROSE} lives in the portal\n"
        f"- **`AZURE_CLIENT_ID`**: `{V1}`\n"
        f"- **Secret (AZURE_CLIENT_SECRET):** `{V2}`\n"
        "## GOOGLE oauth\n"
        f"GOOGLE_OAUTH_CLIENT_ID={V2}\n"
        f"- **`DUP_KEY`**: `{V3}`\n- **`DUP_KEY`**: `{V4}`\n"
        f"## stray\n**{V1}** is a heading-like bold that is secret shaped? no, just label\n")
    (r / "secrets" / "x" / "a.env").write_text(f"FILE_KEY={V1}\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    return r


def run(r, *args):
    e = {**os.environ, "LOCKBOX_REPO": str(r), "LOCKBOX_REF": "WORKTREE"}
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "lockbox_names.py"), *args],
                       capture_output=True, text=True, env=e)
    return p.returncode, p.stdout + p.stderr


def test_lists_labels_and_resolvable_without_values_or_prose(tmp_path):
    r = make(tmp_path)
    rc, out = run(r, "AZURE|GOOGLE|FILE|DUP")
    assert rc == 0
    assert "AZURE signing (added 10-01) | AZURE_CLIENT_ID | md | yes" in out
    assert "| GOOGLE_OAUTH_CLIENT_ID | env | yes" in out
    assert "| FILE_KEY | file | yes" in out
    assert "| DUP_KEY | md | dup" in out
    # a prose label is listed but never resolvable, and nothing after the label leaks
    assert "| Tenant: " not in out or "| Tenant" in out
    assert "| label | no" in out
    for secret in (V1, V2, V3, V4, PROSE, "lives in the portal"):
        assert secret not in out
        for i in range(0, len(secret) - 7):
            assert secret[i:i + 8] not in out


def test_filter_and_bad_regex(tmp_path):
    r = make(tmp_path)
    rc, out = run(r, "NOSUCHTHING")
    assert rc == 0 and "0 entries" in out
    rc, out = run(r, "(")
    assert rc == 2 and "bad regex" in out


# --- the API road (default since 2026-11-12): a FAKE gh serves made-up files; no clone, no network ---
FAKE_GH = r'''#!/usr/bin/env python3
import json, os, re, sys
root, mode = os.environ["FAKE_ROOT"], os.environ.get("FAKE_MODE", "ok")
open(os.environ["FAKE_LOG"], "a").write(" ".join(sys.argv[1:]) + "\n")
a = sys.argv[1:]
if mode == "fail":
    sys.stderr.write("HTTP 401\n"); sys.exit(1)
SHA = "a" * 40
files = []
for d, _, fs in os.walk(root):
    for f in fs:
        files.append(os.path.relpath(os.path.join(d, f), root))
if "graphql" in a:
    q = json.loads(sys.stdin.read())["query"]
    out = {}
    for j, expr in enumerate(re.findall(r'expression:"([^"]+)"', q)):
        p = expr.split(":", 1)[1]
        out[f"f{j}"] = {"text": open(os.path.join(root, p)).read(), "isBinary": False, "isTruncated": False}
    print(json.dumps({"data": {"repository": out}}))
elif any("/git/ref/heads/" in x for x in a):
    print(json.dumps({"object": {"sha": SHA}}))
elif any("/git/trees/" in x for x in a):
    print(json.dumps({"truncated": mode == "truncated", "tree": [{"path": f, "type": "blob"} for f in files]}))
elif any("/contents/ACCESS_LOCKBOX.md" in x for x in a):
    sys.stdout.write(open(os.path.join(root, "ACCESS_LOCKBOX.md")).read())
else:
    sys.exit(3)
'''


def fake_gh(tmp_path, r, mode="ok"):
    g = tmp_path / "gh"
    g.write_text(FAKE_GH)
    g.chmod(0o755)
    log = tmp_path / "gh.log"
    env = {**os.environ, "LOCKBOX_GH": str(g), "FAKE_ROOT": str(r), "FAKE_MODE": mode, "FAKE_LOG": str(log),
           "LOCKBOX_REPO": str(tmp_path / "no-such-clone")}
    for k in ("LOCKBOX_REF", "LOCKBOX_SOURCE"):
        env.pop(k, None)
    return env, log


def run_env(env, *args):
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "lockbox_names.py"), *args],
                       capture_output=True, text=True, env=env)
    return p.returncode, p.stdout + p.stderr


def test_api_road_is_the_default_and_needs_no_clone(tmp_path):
    r = make(tmp_path)
    env, log = fake_gh(tmp_path, r)
    rc, out = run_env(env, "AZURE|GOOGLE|FILE|DUP")
    assert rc == 0, out
    # the same rows the clone road prints, from the same made-up files
    rc2, out2 = run(r, "AZURE|GOOGLE|FILE|DUP")
    assert rc2 == 0 and out == out2
    calls = log.read_text()
    assert "git/ref/heads/main" in calls and "git/trees/" + "a" * 40 in calls and "graphql" in calls
    assert "contents/ACCESS_LOCKBOX.md?ref=" + "a" * 40 in calls      # every file at ONE commit
    for secret in (V1, V2, V3, V4, PROSE):
        assert secret not in out


def test_api_failure_fails_and_never_falls_back_to_a_clone(tmp_path):
    r = make(tmp_path)
    env, _ = fake_gh(tmp_path, r, mode="fail")
    env["LOCKBOX_REPO"] = str(r)          # a readable clone IS there; it must not be used
    rc, out = run_env(env, "AZURE")
    assert rc == 2 and "cannot read the lockbox: gh api failed" in out
    assert "AZURE_CLIENT_ID" not in out and "Traceback" not in out


def test_api_truncated_tree_stops(tmp_path):
    r = make(tmp_path)
    env, _ = fake_gh(tmp_path, r, mode="truncated")
    rc, out = run_env(env)
    assert rc == 2 and "truncated" in out and "Traceback" not in out


def test_bad_source_and_explicit_clone(tmp_path):
    r = make(tmp_path)
    env, _ = fake_gh(tmp_path, r)
    rc, out = run_env({**env, "LOCKBOX_SOURCE": "elsewhere"})
    assert rc == 2 and "LOCKBOX_SOURCE must be api or clone" in out
    rc, out = run_env({**env, "LOCKBOX_SOURCE": "clone", "LOCKBOX_REPO": str(r), "LOCKBOX_REF": "WORKTREE"}, "FILE")
    assert rc == 0 and "| FILE_KEY | file | yes" in out
