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


def _entry(**kw):
    base = dict(repo="x", paths=["*"], reason="r", exemption="owner-approved", expires="2099-01-01",
                approved_by="windy-hub")
    base.update(kw)
    lines = ["allow:", "  - repo: x", "    paths: ['*']", "    reason: r"]
    for k in ("exemption", "expires", "approved_by"):
        if base.get(k) is not None:
            lines.append(f"    {k}: {base[k]}")
    return "\n".join(lines) + "\n"


def test_allow_entries_need_a_named_exemption_and_an_expiry(tmp_path):
    from datetime import date
    f = tmp_path / "a.yml"
    f.write_text(_entry(exemption=None))
    with pytest.raises(ValueError):
        cg.load_allow(f)
    f.write_text(_entry(exemption="because-i-said-so"))
    with pytest.raises(ValueError):
        cg.load_allow(f)
    f.write_text(_entry(expires=None))
    with pytest.raises(ValueError):
        cg.load_allow(f)
    f.write_text(_entry(expires="someday"))
    with pytest.raises(ValueError):
        cg.load_allow(f)
    f.write_text(_entry(expires="2026-12-01"))
    assert len(cg.load_allow(f, today=date(2026, 10, 2))) == 1


def test_expired_exemption_stops_excusing_and_is_reported(tmp_path):
    from datetime import date
    f = tmp_path / "a.yml"
    f.write_text(_entry(expires="2026-10-01"))
    assert cg.load_allow(f, today=date(2026, 10, 1))        # the expiry day is still valid
    assert cg.load_allow(f, today=date(2026, 10, 2)) == []   # the next day it no longer excuses anything
    assert cg.EXPIRED and cg.EXPIRED[0]["repo"] == "x" and cg.EXPIRED[0]["expires"] == "2026-10-01"


def test_shipped_allow_file_is_valid_today():
    assert cg.load_allow() and not cg.EXPIRED  # nothing in the repo's own file may already be expired


@pytest.mark.parametrize("text, kind", [
    ('u = "https://api.deepgram.com/v1/listen"', "voice-ai host"),
    ("fetch(`https://api.elevenlabs.io/v1/tts`)", "voice-ai host"),
    ('h = "api.cartesia.ai"', "voice-ai host"),
    ('h = "app.resemble.ai"', "voice-ai host"),
    ('h = "speech.googleapis.com"', "voice-ai host"),
    ('h = "transcribe.us-east-1.amazonaws.com"', "voice-ai host"),
    ('h = "polly.eu-west-1.amazonaws.com"', "voice-ai host"),
    ("DEEPGRAM_API_KEY=abc", "voice-ai key"),
    ("ELEVENLABS_API_KEY = x", "voice-ai key"),
    ('u = f"https://api.cloudflare.com/client/v4/accounts/{a}/ai/run/@cf/m"', "cloudflare workers ai"),
    ('ENGINE = "http://10.0.0.5:8791/v1"', "talk engine port"),
    ('ENGINE = "http://h:8788/ws"', "talk engine port"),
    ('x = "http://h:8099/health"', "talk engine port"),
])
def test_gatekeeper_rules_fire(text, kind):
    assert kind in [k for k, _ in cg.scan_line("app/x.py", text)]


def test_workers_ai_binding_only_in_wrangler_and_near_misses_are_quiet():
    assert [k for k, _ in cg.scan_line("wrangler.toml", "[ai]")] == ["workers ai binding"]
    assert [k for k, _ in cg.scan_line("apps/x/wrangler.jsonc", '  "ai": {')] == ["workers ai binding"]
    assert cg.scan_line("other.toml", "[ai]") == []
    assert cg.scan_line("app/x.py", "port = 87912") == []
    assert cg.scan_line("app/x.py", "# talk engine was :8791 (removed)") == []


def test_rolling_out_kinds_warn_but_dont_block_and_hard_kinds_still_do(monkeypatch):
    monkeypatch.setattr(cg, "MODE", "block")
    monkeypatch.setattr(cg, "SOFT_KINDS", {"voice-ai host", "voice-ai key"})
    soft = cg.Finding("a.py", 1, "voice-ai host", "api.deepgram.com")
    hard = cg.Finding("a.py", 2, "provider host", "api.openai.com")
    state, desc, _ = cg.status_for([soft], whole_tree=True)
    assert state == "success" and "rolling out" in desc and len(desc) <= 140
    assert cg.status_for([soft, hard], whole_tree=True)[0] == "failure"
    monkeypatch.setattr(cg, "SOFT_KINDS", set())
    assert cg.status_for([soft], whole_tree=True)[0] == "failure"   # rollout over: it blocks


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


def test_block_mode_never_blocks_grant_owned(monkeypatch):
    monkeypatch.setattr(cg, "MODE", "block")
    g = cg.Finding("src/client/desktop/x.js", 9, "provider host", "api.openai.com")
    state, desc, f = cg.status_for([], whole_tree=True, grant=[g])
    assert state == "success" and desc.startswith("⚠ WARN (Grant-owned, not blocking): 1") and f is g
    lane = cg.Finding("a.py", 3, "provider host", "x")
    assert cg.status_for([lane], whole_tree=True, grant=[g])[0] == "failure"


def test_veron_ollama_warns_on_added_lines_and_never_blocks(monkeypatch):
    hits = cg.scan_line("app/llm.py", 'OLLAMA = "http://192.168.1.73:11434/api/generate"')
    assert [k for k, _ in hits] == ["veron ollama"]
    assert cg.scan_line("app/llm.py", 'port = 114345') == []                # not the port
    assert cg.scan_line("app/llm.py", "# was http://x:11434 (removed)") == []  # a comment is not a call
    f = cg.Finding("app/llm.py", 7, "veron ollama", ":11434")
    monkeypatch.setattr(cg, "MODE", "block")
    state, desc, _ = cg.status_for([f], whole_tree=False)
    assert state == "success" and desc.startswith("⚠ WARN: new Veron Ollama ref app/llm.py:7")
    assert "Windy Mind" in desc and len(desc) <= 140
    hard = cg.Finding("app/llm.py", 1, "provider host", "api.openai.com")
    assert cg.status_for([f, hard], whole_tree=False)[0] == "failure"       # a real violation still blocks


def test_ollama_in_added_pr_lines_only():
    diff = ("+++ b/svc/client.py\n@@ -0,0 +1,2 @@\n+import httpx\n"
            "+URL = 'http://veron:11434/api/chat'\n")
    got = cg.parse_added("some-repo", diff, [])
    assert [(f.kind, f.line) for f in got] == [("veron ollama", 2)]


def test_non_structural_exemptions_need_an_independent_approver_and_a_90_day_cap(tmp_path):
    from datetime import date
    f = tmp_path / "a.yml"
    f.write_text(_entry(approved_by=None))
    with pytest.raises(ValueError):
        cg.load_allow(f, today=date(2026, 10, 2))
    f.write_text(_entry(approved_by="windy-chat"))     # a lane may not approve itself/another lane
    with pytest.raises(ValueError):
        cg.load_allow(f, today=date(2026, 10, 2))
    f.write_text(_entry(expires="2026-12-31"))           # exactly 90 days: fine
    assert len(cg.load_allow(f, today=date(2026, 10, 2))) == 1
    f.write_text(_entry(expires="2027-01-01"))           # 91 days: does NOT apply, and is reported
    assert cg.load_allow(f, today=date(2026, 10, 2)) == [] and cg.OVERCAP
    f.write_text(_entry(exemption="compute-door", approved_by=None, expires="2027-10-02"))
    assert len(cg.load_allow(f, today=date(2026, 10, 2))) == 1   # structural: yearly, no approver field


def test_shipped_allow_file_obeys_its_own_rules():
    allow = cg.load_allow()
    assert allow and not cg.EXPIRED and not cg.OVERCAP
    for e in allow:
        if e["exemption"] not in cg.STRUCTURAL:
            assert e["approved_by"] in cg.APPROVERS


def test_findings_carry_kind_and_name_never_the_value_and_ports_skip_contracts():
    for line, kind in [("ELEVENLABS_API_KEY=sk_live_SUPERSECRET123456789", "voice-ai key"),
                       ('DEEPGRAM_API_KEY = "dg-VALUE-0123456789abcdef"', "voice-ai key")]:
        hits = cg.scan_line("app/x.py", line)
        assert [k for k, _ in hits] == [kind]
        assert all("SUPERSECRET" not in m and "VALUE" not in m for _, m in hits)
    assert cg.scan_line("engine/contracts/ops.mcp.v1.json", '"url": "http://h:8099/x"') == []
    assert cg.scan_line("services/api/openapi/spec.json", '"url": "http://h:8099/x"') == []
    assert [k for k, _ in cg.scan_line("deploy/docker-compose.yml", "    - 8099:8099 # :8099")] == ["talk engine port"]
