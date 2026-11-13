"""scripts/merge_on_guards.py: a TODO/docs-only PR merges only on the three guards PRESENT + success BY NAME at the
head the caller read; an absent or pending guard waits; a red one, a code file, a moved head or kit-army-config refuse."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("merge_on_guards", ROOT / "scripts" / "merge_on_guards.py")
mg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mg)

H = "c" * 40


def _pr(files=("TODO.md",), state="OPEN", head=H):
    return {"state": state, "headRefOid": head, "files": [{"path": f} for f in files]}


def _st(**kw):
    out = []
    for i, (k, v) in enumerate(kw.items()):
        out.append({"context": "windy-git/" + k.replace("_", "-"), "state": v, "updated_at": f"2026-11-13T17:{i:02d}:00Z"})
    return out


GREEN = _st(secret_guard="success", compute_guard="success", ci_hygiene="success")


def test_three_guards_success_by_name_merges():
    assert mg.decide("windy-chat", _pr(), GREEN, H)[0] == 0
    assert mg.decide("windy-chat", _pr(("docs/a.md", "x/TODO.md", "README.md")), GREEN, H)[0] == 0


def test_an_absent_or_pending_guard_waits_never_passes():
    two = _st(secret_guard="success", compute_guard="success")
    code, why = mg.decide("windy-chat", _pr(), two, H)
    assert code == 3 and "ci-hygiene absent" in why
    code, why = mg.decide("windy-chat", _pr(), _st(secret_guard="success", compute_guard="pending", ci_hygiene="success"), H)
    assert code == 3 and "compute-guard pending" in why


def test_a_red_guard_refuses():
    code, why = mg.decide("windy-chat", _pr(), _st(secret_guard="failure", compute_guard="success", ci_hygiene="success"), H)
    assert code == 1 and "secret-guard failure" in why


def test_the_newest_status_of_each_guard_counts():
    st = GREEN + [{"context": "windy-git/secret-guard", "state": "failure", "updated_at": "2026-11-13T18:00:00Z"}]
    assert mg.decide("windy-chat", _pr(), st, H)[0] == 1
    st = [{"context": "windy-git/secret-guard", "state": "failure", "updated_at": "2026-11-13T16:00:00Z"}] + GREEN
    assert mg.decide("windy-chat", _pr(), st, H)[0] == 0


def test_code_files_a_moved_head_a_closed_pr_and_kit_army_config_refuse():
    assert mg.decide("windy-chat", _pr(("TODO.md", "app.py")), GREEN, H)[0] == 1
    assert mg.decide("windy-chat", _pr(("ACCESS_LOCKBOX.md",)), GREEN, H)[0] == 1        # .md is not docs (term 1)
    assert mg.decide("windy-chat", _pr(()), GREEN, H)[0] == 1                            # no file list: no merge
    assert mg.decide("windy-chat", _pr(head="d" * 40), GREEN, H)[0] == 1
    assert mg.decide("windy-chat", _pr(state="MERGED"), GREEN, H)[0] == 1
    assert mg.decide("kit-army-config", _pr(), GREEN, H)[0] == 1


def test_main_merges_with_match_head_commit_and_reads_the_merge_back(capsys):
    calls = []

    def run(args):
        calls.append(args)
        if args[:2] == ["pr", "view"] and "state,headRefOid,files" in args:
            return json.dumps(_pr())
        if args[0] == "api":
            return json.dumps(GREEN)
        if args[:2] == ["pr", "merge"]:
            return ""
        return json.dumps({"state": "MERGED", "mergeCommit": {"oid": "e" * 40}})
    assert mg.main(["windy-chat", "12", H], run=run) == 0
    merge = [c for c in calls if c[:2] == ["pr", "merge"]][0]
    assert merge[-2:] == ["--match-head-commit", H] and "--squash" in merge
    assert "MERGED windy-chat #12 at cccccccc -> eeeeeeee" in capsys.readouterr().out


def test_main_waits_merges_nothing_on_an_absent_guard_or_a_read_error():
    calls = []

    def run(args):
        calls.append(args)
        if args[0] == "api":
            return json.dumps(GREEN[:2])
        return json.dumps(_pr())
    assert mg.main(["windy-chat", "12", H], run=run) == 3
    assert not any(c[:2] == ["pr", "merge"] for c in calls)

    def boom(args):
        raise OSError("tls")
    assert mg.main(["windy-chat", "12", H], run=boom) == 3


def test_usage_is_checked_before_any_call():
    def run(args):
        raise AssertionError("no call on bad usage")
    assert mg.main(["windy-chat", "12", "abc"], run=run) == 2
    assert mg.main(["bad name", "12", H], run=run) == 2
    assert mg.main(["windy-chat", "12", H, "--rebase"], run=run) == 2
