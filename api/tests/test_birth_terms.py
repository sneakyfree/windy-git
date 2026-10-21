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


def test_inline_code_is_not_prose():
    assert words("set `the hub` in config") == []
    assert words("``the hub`` and ```one hallway```") == []
    assert words("`x` then the hub, then `y`") == ["the hub"]
    assert words("a stray ` then the hub") == ["the hub"]          # unpaired backtick is not code


def test_fenced_blocks_cover_their_lines_closed_only():
    text = "a\n```md\nthe hub\n```\nthe hub\n~~~~\nthe hallway\n~~~\nstill fenced\n~~~~\n"
    assert bt.fenced_lines(text) == {2, 3, 4, 6, 7, 8, 9, 10}      # ~~~ (3) can't close ~~~~ (4)
    assert bt.fenced_lines("```\nthe hub\n") == set()               # unclosed: exempts nothing
    assert bt.fenced_lines("```\nx\n``` not a close\n") == set()    # text after a fence: not a close
    assert bt.fenced_lines("```\nx\n~~~\n") == set()                # other fence char: not a close
    assert bt.exempt_lines("<!-- glossary -->\nthe hub\n<!-- /glossary -->\n```\nthe hub\n```\n") == {1, 2, 3, 4, 5, 6}


def test_scan_patch_drops_findings_inside_a_fence_at_the_head():
    patch = "@@ -0,0 +1,4 @@\n+```\n+the hub\n+```\n+the hub\n"
    found = bt.scan_patch("a.md", patch, lambda p: "```\nthe hub\n```\nthe hub\n")
    assert [(f.line, f.match) for f in found] == [(4, "the hub")]


def test_unreadable_head_keeps_findings_and_is_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(cg, "CACHE", tmp_path / "cache.json")
    pf = [{"f": "a.md", "p": "@@ -0,0 +1,3 @@\n+```\n+the hub\n+```\n", "c": 3}]
    assert [f.line for f in bt.scan_pr("o/r", "s1", pf, lambda p: None)] == [2]   # can't see the fence: stays
    import json
    assert list(json.loads((tmp_path / "cache.json").read_text())) == [            # ...and is not final
        f"birth-pub:o/r:s1:{bt.FINGERPRINT}:unread"]
    assert bt.scan_pr("o/r", "s1", pf, lambda p: "```\nthe hub\n```\n") == []      # readable next cycle
    reads = []
    assert bt.scan_pr("o/r", "s1", pf, lambda p: reads.append(p)) == [] and reads == []   # cached now
    with __import__("pytest").raises(bt.Unread):
        bt.drop_glossary([cg.Finding("a.md", 1, "use x", "the hub")], lambda p: None, strict=True)


def test_unchecked_counts_md_files_without_a_diff():
    pf = [{"f": "big.md", "p": None, "c": 9000}, {"f": "moved.md", "p": None, "c": 0},
          {"f": "x.py", "p": None, "c": 5}, {"f": "unknown.md", "p": None}, {"f": "ok.md", "p": "@@", "c": 1}]
    assert bt.unchecked(pf) == 2


def test_status_names_unchecked_files_and_still_fits():
    state, desc, first = bt.status_for([], unchecked=2)
    assert state == "success" and first is None and "2 .md file(s) not checked" in desc
    f = cg.Finding("docs/" + "x" * 80 + ".md", 7, "use Birth Canal", "one hallway")
    state, desc, _ = bt.status_for([f], unchecked=1)
    assert "(+1 .md not checked: no diff)" in desc and len(desc) <= 140 and desc.endswith(bt.GLOSSARY)


def test_a_head_that_had_findings_gets_a_clearing_ok(tmp_path, monkeypatch):
    # A rule change (e.g. fenced code exempt) can empty a head that already carries a WARN/BLOCK:
    # check() returns [] (post the OK, bridge skips it if unchanged) instead of None (stay silent).
    monkeypatch.setattr(cg, "CACHE", tmp_path / "cache.json")
    monkeypatch.setattr(cg, "WORK", tmp_path)
    (tmp_path / "demo.git").mkdir()
    monkeypatch.setattr(cg, "fetched", lambda bare, sha: True)
    monkeypatch.setattr(cg, "scan_added", lambda *a, **k: [])
    assert bt.check("demo", "s1", "main", is_default_head=False) is None          # nothing ever found
    import json
    (tmp_path / "cache.json").write_text(json.dumps({
        "birth-pr:demo:s1:oldfp": [{"path": "a.md", "line": 1, "kind": "use x", "match": "the hub"}]}))
    assert bt.check("demo", "s1", "main", is_default_head=False) == []            # clear the old WARN
    assert bt.check("demo", "s2", "main", is_default_head=False) is None          # other heads: silent


# --- Hub #56 review: fail-safe fences (never skip prose CommonMark renders as a paragraph)

PROSE = "The hub issues the token."


def test_fence_after_a_list_marker_or_quote_exempts_nothing():
    for marker in ("- ", "1. ", "2) ", "> ", "* > "):
        text = f"{marker}```sh\nmake\n```\n{PROSE}\n```sh\nrun\n```\n"
        assert bt.fenced_lines(text) == set(), marker


def test_a_list_item_fence_cut_short_by_an_unindented_line_exempts_nothing():
    # Hub #56: CommonMark ends the list item at line 4 (a <p> in pandoc); pairing 2 and 5 skipped it.
    assert bt.fenced_lines(f"- Install:\n  ```sh\n  npm i\n{PROSE}\n  ```\n") == set()
    assert bt.fenced_lines(f"> quote\n\n  ```\n  x\n{PROSE}\n  ```\n") == set()
    assert bt.fenced_lines(f"- a\n ```\n{PROSE}\n ```\n") == set()               # 1-3 spaces, by rule
    assert bt.fenced_lines("- a list\n\n```\nthe hub\n```\n") == {3, 4, 5}       # flush fence: still fine
    assert bt.fenced_lines("  ```\nthe hub\n  ```\n") == {1, 2, 3}                 # no list: still fine


def test_multiline_html_block_exempts_nothing_but_a_one_line_comment_is_fine():
    assert bt.fenced_lines(f"<!--\n```\n-->\n{PROSE}\n```\n") == set()
    assert bt.fenced_lines(f"<div>\n```\n</div>\n{PROSE}\n```\n") == set()
    assert bt.fenced_lines("<!-- glossary -->\n```\nthe hub\n```\n<!-- /glossary -->\n") == {2, 3, 4}


def test_backtick_in_info_string_is_not_a_fence_but_long_fences_are():
    assert bt.fenced_lines(f"```bash``` is the syntax.\n{PROSE}\n```\n") == set()
    assert bt.fenced_lines("````\nthe hub\n````\n") == {1, 2, 3}
    assert bt.fenced_lines("``````md\nthe hub\n``````\n") == {1, 2, 3}
    assert bt.fenced_lines("~~~ a`b\nthe hub\n~~~\n") == {1, 2, 3}       # ~~~ info may hold a backtick


def test_tab_or_deep_indent_before_a_fence_exempts_nothing():
    assert bt.fenced_lines(f"\t```\n{PROSE}\n\t```\n") == set()
    assert bt.fenced_lines(f"    ```\n{PROSE}\n    ```\n") == set()
    assert bt.fenced_lines("   ```\nthe hub\n   ```\n") == {1, 2, 3}     # up to 3 spaces is a fence
    # CommonMark: the list item's fence closes at the tab-indented ```; PROSE is a paragraph and the
    # last ``` opens a new (unclosed) block. Pairing line 3 with line 7 would skip PROSE.
    assert bt.fenced_lines(f"- x\n\n  ```\n  code\n\t```\n{PROSE}\n```\n") == set()
    assert bt.fenced_lines(f"- x\n\n  ```\n  code\n      ```\n{PROSE}\n```\n") == set()


def test_odd_line_breaks_cannot_shift_the_exempt_range():
    for ch in (" ", "\u0085", "\x0b", "\x0c", "\x1c", "\x1e"):
        head = f"a{ch}b\n```\nx\n```\n{PROSE}\n"
        assert bt.fenced_lines(head) == {2, 3, 4}, repr(ch)
        patch = f"@@ -0,0 +1,5 @@\n+a{ch}b\n+```\n+x\n+```\n+{PROSE}\n"
        assert [(f.line, f.match) for f in bt.scan_patch("a.md", patch, lambda p, h=head: h)] == [(5, "The hub")]
    assert bt.fenced_lines(f"x\ry\n```\nz\n```\n{PROSE}\n") == set()        # lone CR: CommonMark != git
    assert bt.glossary_lines("a b\n<!-- glossary -->\nthe hub\n<!-- /glossary -->\n") == {2, 3, 4}


def test_a_line_separator_inside_an_added_line_hides_nothing():
    patch = "@@ -0,0 +1 @@\n+Note: The hub issues the token.\n"
    assert [f.match for f in bt.scan_patch("a.md", patch, lambda p: "")] == ["The hub"]
    diff = "+++ b/a.md\n@@ -0,0 +1 @@\n+Note: The hub issues the token.\r\n"
    found = cg.parse_added("r", diff, [], line_fn=bt.scan_line, path_ok=bt.path_ok)
    assert [(f.line, f.match) for f in found] == [(1, "The hub")]


def test_escaped_backticks_are_not_code():
    assert words("\\`the hub\\`") == ["the hub"]
    assert words("`` `the hub` ``") == []


def test_private_check_keeps_findings_when_the_head_file_is_unreadable(tmp_path, monkeypatch):
    # Hub M7: check() must use the strict path, so an unreadable head neither exempts nor caches.
    monkeypatch.setattr(cg, "CACHE", tmp_path / "cache.json")
    monkeypatch.setattr(cg, "WORK", tmp_path)
    (tmp_path / "demo.git").mkdir()
    monkeypatch.setattr(cg, "fetched", lambda bare, sha: True)
    monkeypatch.setattr(cg, "scan_added", lambda *a, **k: [cg.Finding("a.md", 2, "use x", "the hub")])
    monkeypatch.setattr(bt, "_show", lambda bare, sha, path: None)
    assert [f.line for f in bt.check("demo", "s1", "main", is_default_head=False)] == [2]
    import json
    keys = list(json.loads((tmp_path / "cache.json").read_text()))
    assert keys == [f"birth-pr:demo:s1:{bt.FINGERPRINT}:unread"]           # the result itself is not final
    monkeypatch.setattr(bt, "_show", lambda bare, sha, path: "```\nthe hub\n```\n")
    assert bt.check("demo", "s1", "main", is_default_head=False) == []   # readable: exempt (and clears)


def test_zero_checked_never_reads_ok():
    state, desc, _ = bt.status_for([], unchecked=2, checked=0)
    assert desc.startswith("NOT CHECKED") and "OK" not in desc
    assert bt.status_for([], unchecked=2, checked=1)[1].startswith("OK in checked lines")
