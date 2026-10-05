"""contracts-drift sweep (S0.4): bump a schema -> the next sweep lists every consumer behind."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("contracts_drift", ROOT / "scripts" / "contracts_drift.py")
cd = importlib.util.module_from_spec(_spec)
sys.modules["contracts_drift"] = cd
_spec.loader.exec_module(cd)


def sha(b):
    return hashlib.sha256(b).hexdigest()


class Fake:
    def __init__(self, files):  # {repo: {path: bytes}}
        self.files = files

    def repos(self):
        return sorted(self.files)

    def find_locks(self, repo):
        return [p for p in self.files[repo] if p.split("/")[-1] == "contracts.lock"]

    def blob(self, repo, path):
        return self.files.get(repo, {}).get(path)


V1 = b'{"a":1}\n'
V2 = b'{"a":2}\n'


def manifest(content, version):
    return {"contracts": [{"path": "schema/mind/x.v1.json", "version": version, "sha256": sha(content)}]}


def lock(content, version="1.0.0", at="contracts/x.v1.json"):
    return json.dumps({"contracts": [{"path": "schema/mind/x.v1.json", "version": version,
                                      "sha256": sha(content), "vendored_at": at}]}).encode()


def test_current_consumer_is_not_listed():
    src = Fake({"c": {"contracts.lock": lock(V1), "contracts/x.v1.json": V1}})
    rows, n = cd.sweep(src, manifest(V1, "1.0.0"))
    assert rows == [] and n == 1


def test_bumped_schema_lists_the_lagging_consumer():
    """Acceptance (S0.4): bump a schema -> the next sweep lists every consumer behind."""
    src = Fake({"c1": {"contracts.lock": lock(V1), "contracts/x.v1.json": V1},
                "c2": {"contracts.lock": lock(V2, "1.1.0"), "contracts/x.v1.json": V2}})
    rows, n = cd.sweep(src, manifest(V2, "1.1.0"))
    assert n == 2
    assert [(r["repo"], r["status"], r["locked"], r["manifest"]) for r in rows] == [("c1", "BEHIND", "1.0.0", "1.1.0")]


def test_local_edit_and_missing_and_unknown_and_nested_lock():
    src = Fake({"c": {"sub/contracts.lock": lock(V1, at="v/x.json"), "sub/v/x.json": V2},
                "d": {"contracts.lock": lock(V1), },
                "e": {"contracts.lock": lock(V1).replace(b"schema/mind/x.v1.json", b"schema/nope.json"), "contracts/x.v1.json": V1}})
    rows, _ = cd.sweep(src, manifest(V1, "1.0.0"))
    assert {(r["repo"], r["status"]) for r in rows} == {("c", "LOCAL_EDIT"), ("d", "MISSING_VENDORED"), ("e", "UNKNOWN")}


def test_contracts_repo_itself_and_no_locks_are_ignored():
    src = Fake({"windy-contracts": {"contracts.lock": b"{}"}, "plain": {"README.md": b"x"}})
    assert cd.sweep(src, manifest(V1, "1.0.0")) == ([], 0)


def test_unreadable_lock_is_reported():
    src = Fake({"c": {"contracts.lock": b"not json"}})
    rows, n = cd.sweep(src, manifest(V1, "1.0.0"))
    assert rows[0]["status"] == "UNREADABLE_LOCK" and n == 0
