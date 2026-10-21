"""scripts/birth_terms.py: retired agent-birth words in ADDED *.md prose (Grant's 10-21 glossary)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("birth_terms", ROOT / "scripts" / "birth_terms.py")
bt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bt)
cg = bt.cg


def words(text):
    return [m for _, m in bt.scan_line("a.md", text)]


def test_each_retired_word_is_flagged_case_insensitive():
    assert words("Agents are born in the hatch hallway.") == ["hatch hallway"]
    assert words("the Agent Hallway and ONE HALLWAY") == ["Agent Hallway", "ONE HALLWAY"]
    assert words("Eternitas waits at the hallway end.") == ["the hallway"]
    assert words("Sign in at the Hub first.") == ["the Hub"]
    assert words("THE HUB billing page") == ["THE HUB"]


def test_the_hub_lane_is_the_allowed_name():
    assert words("Ask the Hub lane to read it.") == []
    assert words("the hub   lane reviews code") == []
    assert words("the Hub's lane") == ["the Hub"]  # possessive is not the name


def test_unrelated_words_are_not_flagged():
    assert words("GitHub hub hubs hallways, a hallway, windy hub") == []
    assert words("HUB_PLATFORM_IDS and hallway.py") == []


def test_historical_escape_on_the_line():
    assert words("older text says 'the hub' (historical)") == []
    assert words("Older text said HATCH HALLWAY (Historical)") == []


def test_markdown_only_and_never_the_glossary_or_vendored():
    assert bt.path_ok("docs/PLAN.md")
    assert bt.path_ok("README.MD")
    assert not bt.path_ok("src/hub.py")
    assert not bt.path_ok("doctrine/03-GLOSSARY-AGENT-BIRTH-TERMS.md")
    assert not bt.path_ok("node_modules/x/README.md")
    assert not bt.path_ok("docs/history/PLAN_REVIEW_2026-10-06.md")   # verbatim archive copies
    assert not bt.path_ok("docs/History/OLD.md")                      # any case
    assert bt.path_ok("docs/historyless.md")


def test_glossary_blocks_cover_their_lines_and_markers():
    text = "a\n<!-- glossary -->\nthe hub\n  <!-- /glossary -->\nthe hub\n"
    assert bt.glossary_lines(text) == {2, 3, 4}
    assert bt.glossary_lines("<!-- glossary -->\nx\ny\n") == set()   # unclosed: exempts nothing


def test_scan_patch_counts_lines_and_honours_glossary_blocks():
    patch = "@@ -1,2 +1,4 @@\n line one\n-old the hub\n+new the hub\n+fine line\n@@ -9 +10,2 @@\n+in the hallway\n+the Hub lane ok\n"
    head = "line one\nnew the hub\nfine line\n" + "\n" * 5 + "<!-- glossary -->\nin the hallway\n<!-- /glossary -->\n"
    reads = []

    def read(p):
        reads.append(p)
        return head

    found = bt.scan_patch("docs/x.md", patch, read)
    assert [(f.line, f.match) for f in found] == [(2, "the hub")]   # line 10 sits inside the block
    assert reads == ["docs/x.md"]
    assert bt.scan_patch("src/x.py", patch, read) == []
    assert bt.scan_patch("docs/x.md", None, read) == []


def test_status_warn_by_default_and_block_by_mode(monkeypatch):
    f = cg.Finding("docs/a.md", 3, "use Windy Accounts / the Hub lane", "the Hub")
    state, desc, first = bt.status_for([f])
    assert state == "success" and desc.startswith("⚠ WARN: 1 retired term(s) added")
    assert "docs/a.md:3 'the Hub' -> Windy Accounts / the Hub lane; see doctrine/" in desc
    assert len(desc) <= 140 and first is f
    monkeypatch.setattr(bt, "MODE", "block")
    assert bt.status_for([f])[0] == "failure"
    assert bt.status_for([])[:2] == ("success", "OK: no retired agent-birth words added")
    g = bt.status_for([], grant=[f])
    assert g[0] == "success" and "Grant-owned" in g[1]


def _git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True, text=True).stdout.strip()


def test_check_judges_only_pr_additions_with_blocks_outside_the_hunk(tmp_path, monkeypatch):
    work = tmp_path / "work"
    src = tmp_path / "src"
    src.mkdir()
    _git(src, "init", "-q", "-b", "main")
    (src / "PLAN.md").write_text("old text: the hub (history stays)\n<!-- glossary -->\nRetired:\n\n<!-- /glossary -->\n")
    _git(src, "add", ".")
    _git(src, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    _git(src, "checkout", "-q", "-b", "pr")
    lines = (src / "PLAN.md").read_text().splitlines()
    lines.insert(3, "'the hub' for the software: say Windy Accounts")      # inside the existing block
    lines.append("Log in through the hatch hallway.")                    # outside: flagged
    (src / "PLAN.md").write_text("\n".join(lines) + "\n")
    (src / "code.py").write_text("THE_HUB = 1  # the hub\n")
    _git(src, "add", ".")
    _git(src, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "pr")
    sha = _git(src, "rev-parse", "HEAD")
    work.mkdir()
    subprocess.run(["git", "clone", "-q", "--bare", str(src), str(work / "demo.git")], check=True)
    monkeypatch.setattr(cg, "WORK", work)
    monkeypatch.setattr(cg, "CACHE", tmp_path / "cache.json")
    found = bt.check("demo", sha, "main", is_default_head=False)
    assert [(f.path, f.line, f.match) for f in found] == [("PLAN.md", 7, "hatch hallway")]
    assert bt.check("demo", sha, "main", is_default_head=True) is None   # history is never judged
    base = _git(src, "rev-parse", "main")
    assert bt.check("demo", base, "main", is_default_head=False) is None   # nothing to say: no status
    assert bt.check("demo", "f" * 40, "main", is_default_head=False) is None  # not fetched yet


def test_lint_cli(tmp_path, capsys):
    p = tmp_path / "n.md"
    p.write_text("the hub\n<!-- glossary -->\nthe hub\n<!-- /glossary -->\nthe Hub lane\n")
    assert bt.main(["lint", str(p)]) == 1
    out = capsys.readouterr().out
    assert f"{p}:1: 'the hub' -> Windy Accounts" in out and "1 finding(s)" in out


def test_no_newline_marker_does_not_shift_line_numbers():
    patch = "@@ -1 +1,2 @@\n-old\n\\ No newline at end of file\n+first\n+the hub here\n"
    found = bt.scan_patch("a.md", patch, lambda p: "")
    assert [(f.line, f.match) for f in found] == [(2, "the hub")]


def test_long_description_keeps_the_glossary_path():
    f = cg.Finding("docs/" + "very-long-folder-name/" * 4 + "PLAN.md", 1234,
                   "use Windy Accounts / the Hub lane", "the Hub")
    desc = bt.status_for([f])[1]
    assert len(desc) <= 140 and desc.endswith(f"; see {bt.GLOSSARY}") and "…" in desc
    short = bt.status_for([cg.Finding("a.md", 1, "use Birth Canal", "one hallway")])[1]
    assert short.endswith(f"; see {bt.GLOSSARY}") and "…" not in short
