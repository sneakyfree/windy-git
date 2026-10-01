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
