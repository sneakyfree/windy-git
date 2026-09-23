"""Compute guard: Windy Mind is the only door to AI compute (warn-only today)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("compute_guard", ROOT / "scripts" / "compute_guard.py")
cg = importlib.util.module_from_spec(_spec)
sys.modules["compute_guard"] = cg
_spec.loader.exec_module(cg)

ALLOW = cg.load_allow(ROOT / "ci" / "compute-guard-allow.yml")


@pytest.mark.parametrize(
    "path, text, kind",
    [
        # audit #1 (windy-search, closed) and #2 (windy-chat, live): the shapes they had
        ("service/app/anthropic_client.py", 'URL = "https://api.anthropic.com/v1/messages"', "provider host"),
        ("service/app/config.py", 'token = os.environ["ANTHROPIC_OAUTH_TOKEN"]', "provider key"),
        ("services/agent-roster/lib/llm.js", "const url = 'https://api.groq.com/openai/v1/chat/completions'", "provider host"),
        ("docker-compose.yml", "      GROQ_API_KEY: ${GROQ_API_KEY}", "provider key"),
        # audit #3/#4 (windy-pro account-server)
        ("account-server/src/routes/transcription.ts", "const r = await fetch('https://api.openai.com/v1/audio/transcriptions'", "provider host"),
        ("account-server/src/config.ts", "openaiKey: process.env.OPENAI_API_KEY,", "provider key"),
        # SDKs and deps
        ("app/llm.py", "from anthropic import Anthropic", "provider SDK"),
        ("app/llm.py", "import openai", "provider SDK"),
        ("app/llm.py", "import google.generativeai as genai", "provider SDK"),
        ("src/ai.ts", 'import Anthropic from "@anthropic-ai/sdk";', "provider SDK"),
        ("src/ai.js", "const Groq = require('groq-sdk')", "provider SDK"),
        ("package.json", '    "openai": "^4.52.0",', "provider SDK dep"),
        ("requirements.txt", "anthropic>=0.40", "provider SDK dep"),
        ("pyproject.toml", '  "google-generativeai>=0.8",', "provider SDK dep"),
    ],
)
def test_audit_shapes_are_flagged(path, text, kind):
    assert kind in [k for k, _ in cg.scan_line(path, text)]


@pytest.mark.parametrize(
    "path, text",
    [
        ("app/mind.py", 'MIND = "https://mind.windyword.ai/v1/chat/completions"'),  # the door itself
        ("app/models.py", "openai_compatible = True  # Mind speaks the OpenAI wire format"),
        ("app/x.py", "from app.openai_shim import x"),  # a local module, not the SDK
        ("package.json", '    "openai-types-lite": "1.0.0",'),  # a different package
        ("README.txt", "set OPENAI_API_KEY"),  # scanned-by-rule, excluded by SKIP separately
    ],
)
def test_near_misses_are_not_flagged(path, text):
    if cg.SKIP.search(path):
        return
    assert cg.scan_line(path, text) == []


@pytest.mark.parametrize(
    "path",
    ["tests/test_llm.py", "api/tests/x.py", "src/ai.test.ts", "web/foo.spec.js", "docs/setup.md",
     "README.md", "package-lock.json", "uv.lock", "node_modules/openai/index.js", ".github/workflows/ci.yml",
     "conftest.py", "app/llm_test.py"],
)
def test_tests_docs_lockfiles_vendored_ci_are_never_scanned(path):
    assert cg.SKIP.search(path)


def test_allow_list_needs_a_reason_per_entry(tmp_path):
    bad = tmp_path / "a.yml"
    bad.write_text("allow:\n  - repo: x\n    paths: ['*']\n")
    with pytest.raises(ValueError):
        cg.load_allow(bad)


@pytest.mark.parametrize(
    "repo, path, ok",
    [
        ("windy-mind", "app/providers/anthropic.py", True),
        ("windy-agent", "agent/providers.py", True),
        ("windy-code", "extensions/windy-ai/src/aiProvider.ts", True),
        ("windy-code", "web/server/llm.ts", False),  # BYOK is the extension only
        ("windy-connect", "backend/src/writers/claude_code.py", True),
        ("windy-chat", "services/agent-roster/lib/llm.js", False),  # audit #2: must be flagged
        ("windy-pro", "account-server/src/routes/translations.ts", False),
    ],
)
def test_allow_list_entries(repo, path, ok):
    assert cg.allowed(repo, path, ALLOW) is ok


DIFF = """diff --git a/app/llm.py b/app/llm.py
--- a/app/llm.py
+++ b/app/llm.py
@@ -10,0 +11,2 @@
+import anthropic
+client = anthropic.Anthropic()
diff --git a/tests/test_llm.py b/tests/test_llm.py
--- /dev/null
+++ b/tests/test_llm.py
@@ -0,0 +1 @@
+import anthropic
@@ -40 +42 @@
-x = 1
+x = 2
"""


def test_only_added_non_test_lines_are_findings():
    fs = cg.parse_added("windy-chat", DIFF, ALLOW)
    assert [(f.path, f.line, f.kind) for f in fs] == [("app/llm.py", 11, "provider SDK")]


def _repo(tmp_path, files: dict[str, str]) -> tuple[Path, str]:
    work = tmp_path / "w"
    work.mkdir()
    run = lambda *a: subprocess.run(["git", *a], cwd=work, check=True, capture_output=True)  # noqa: E731
    run("init", "-q", "-b", "main")
    for p, text in files.items():
        (work / p).parent.mkdir(parents=True, exist_ok=True)
        (work / p).write_text(text)
    run("add", "-A")
    run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x")
    bare = tmp_path / "r.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(bare)], check=True)
    sha = subprocess.run(["git", "--git-dir", str(bare), "rev-parse", "main"],
                         capture_output=True, text=True, check=True).stdout.strip()
    return bare, sha


def test_tree_scan_on_a_real_git_repo(tmp_path):
    bare, sha = _repo(tmp_path, {
        "app/llm.py": "import os\nKEY = os.environ['OPENAI_API_KEY']\n",
        "app/ok.py": "MIND = 'https://mind.windyword.ai'\n",
        "tests/test_llm.py": "import anthropic\n",
        "docs/x.md": "api.anthropic.com\n",
    })
    fs = cg.scan_tree("windy-chat", bare, sha, ALLOW)
    assert [(f.path, f.line, f.kind) for f in fs] == [("app/llm.py", 2, "provider key")]


def test_warn_mode_never_turns_red(monkeypatch):
    monkeypatch.setattr(cg, "MODE", "warn")
    state, desc, f = cg.status_for([cg.Finding("a.py", 3, "provider host", "api.openai.com")], whole_tree=False)
    assert state == "success" and desc.startswith("⚠ WARN (not blocking): 1 direct AI-provider use added")
    assert "a.py:3" in desc and f.path == "a.py"


def test_block_mode_fails(monkeypatch):
    monkeypatch.setattr(cg, "MODE", "block")
    state, desc, _ = cg.status_for([cg.Finding("a.py", 3, "provider host", "x")], whole_tree=True)
    assert state == "failure" and desc.startswith("BLOCKED")


def test_clean_is_ok():
    assert cg.status_for([], whole_tree=True)[:2] == (
        "success", "OK: no direct AI-provider use in tree (Windy Mind is the only door)")


@pytest.mark.parametrize(
    "text",
    [
        "    # The ANTHROPIC_OAUTH_TOKEN setting was removed on 2026-09-23 ON PURPOSE",  # windy-search
        "# ANTHROPIC_API_KEY=",
        "  // fallback used to call https://api.groq.com directly",
        " * @see https://api.openai.com/v1/audio",
        "<!-- api.anthropic.com -->",
    ],
)
def test_comments_are_not_calls(text):
    assert cg.scan_line("service/app/config.py", text) == []


def test_code_with_a_trailing_comment_still_counts():
    assert cg.scan_line("a.js", "fetch('https://api.openai.com/v1') // TODO move to Mind")


def test_windy_pro_desktop_is_byok_but_the_account_server_is_not():
    assert cg.allowed("windy-pro", "src/client/desktop/main.js", ALLOW)
    assert not cg.allowed("windy-pro", "account-server/src/routes/translations.ts", ALLOW)


def test_a_commit_not_fetched_yet_is_skipped_not_an_error(tmp_path, monkeypatch):
    bare, sha = _repo(tmp_path, {"app/llm.py": "import anthropic\n"})
    monkeypatch.setattr(cg, "WORK", tmp_path)
    monkeypatch.setattr(cg, "CACHE", tmp_path / "cache.json")
    (tmp_path / "windy-chat.git").symlink_to(bare)
    assert cg.check("windy-chat", "f" * 40, "main", True) is None     # pushed after the fetch
    assert [f.kind for f in cg.check("windy-chat", sha, "main", True)] == ["provider SDK"]


KEYCHAIN = "src/client/web/src/pages/panels/MindKeychain.jsx"


def test_scoped_allow_admits_only_the_oauth_endpoints():
    ok = [
        "    window.location.href = `https://openrouter.ai/auth?callback_url=${encodeURIComponent(callback)}`",
        "    const res = await fetch('https://openrouter.ai/api/v1/auth/keys', {",
    ]
    for line in ok:
        assert cg.allowed("windy-pro", KEYCHAIN, ALLOW, line)
    # an inference call smuggled into the same file still flags
    assert not cg.allowed("windy-pro", KEYCHAIN, ALLOW,
                          "  await fetch('https://openrouter.ai/api/v1/chat/completions', {")
    # a scoped entry never allows a line it can't see
    assert not cg.allowed("windy-pro", KEYCHAIN, ALLOW)


def test_scoped_allow_in_a_real_diff():
    diff = f"""--- /dev/null
+++ b/{KEYCHAIN}
@@ -0,0 +1,3 @@
+  window.location.href = `https://openrouter.ai/auth?callback_url=x`
+  const res = await fetch('https://openrouter.ai/api/v1/auth/keys', {{
+  await fetch('https://openrouter.ai/api/v1/chat/completions', {{
"""
    fs = cg.parse_added("windy-pro", diff, ALLOW)
    assert [(f.line, f.match) for f in fs] == [(3, "openrouter.ai")]
