"""Secret guard: shapes, hash-only findings, allow by hash."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("secret_guard", ROOT / "scripts" / "secret_guard.py")
sg = importlib.util.module_from_spec(_spec)
sys.modules["secret_guard"] = sg
_spec.loader.exec_module(sg)
ss = sg.ss

# Synthetic shapes only: none of these is a real credential.
TG = "1234567890:" + "A" * 35
CASES = [
    ("telegram bot token", f"TELEGRAM_BOT_TOKEN={TG}"),
    ("github token", "token = 'ghp_" + "a1" * 18 + "'"),
    ("aws access key", "aws_access_key_id = AKIA" + "ABCDEFGHIJKLMNOP"),
    ("slack token", "xoxb-" + "1234567890-abcdefghij"),
    ("anthropic key", "ANTHROPIC_API_KEY=sk-ant-" + "x" * 30),
    ("openai key", "OPENAI_API_KEY=sk-proj-" + "y" * 40),
    ("stripe live key", "STRIPE=sk_live_" + "z" * 24),
    ("google api key", "key=AIza" + "B" * 35),
    ("private key block", "-----BEGIN OPENSSH PRIVATE KEY-----"),
]


@pytest.mark.parametrize("kind, text", CASES)
def test_each_shape_is_found_and_only_its_hash_is_kept(kind, text):
    hits = sg.scan_line("app.py", text)
    assert [k for k, _ in hits] == [kind]
    match = hits[0][1]
    assert match.startswith(f"{kind} #") and len(match.rsplit("#", 1)[1]) == 8
    # house rule 10: the value itself must never appear in a finding
    secret = text.split("=", 1)[-1].strip(" '")
    assert secret not in match


@pytest.mark.parametrize("text", [
    "sha512-" + "Q" * 86 + "==",           # lockfile integrity
    "version: 12345678:abc",               # short, not a token
    "sk-ant-short",                        # too short
    "re_test_register_sends_verification", # windy-pro's fake Resend key
    "ANTHROPIC_API_KEY=",                  # a name, not a value
])
def test_non_secrets_are_not_flagged(text):
    assert sg.scan_line("x", text) == []


def test_anthropic_key_is_not_double_counted_as_openai():
    assert [k for k, _ in sg.scan_line("x", "sk-ant-" + "q" * 40)] == ["anthropic key"]


def test_allow_is_by_hash_only():
    F = sg.cg.Finding
    fake = F("tests/t.py", 3, "telegram bot token", f"telegram bot token #{ss.h8(TG)}")
    real = F("tests/t.py", 9, "telegram bot token", "telegram bot token #deadbeef")
    kept = sg._drop_allowed("windy-chat", [fake, real], {"windy-chat": {ss.h8(TG)}})
    assert kept == [real]
    assert sg._drop_allowed("windy-mail", [fake], {"windy-chat": {ss.h8(TG)}}) == [fake]


def test_allow_file_loads_and_needs_reasons(tmp_path):
    assert sg.load_allow() == {} or isinstance(sg.load_allow(), dict)
    bad = tmp_path / "a.yml"
    bad.write_text("allow:\n  - repo: r\n    hashes: [abcd1234]\n")
    with pytest.raises(ValueError):
        sg.load_allow(bad)


def test_block_and_warn(monkeypatch):
    f = sg.cg.Finding("a.py", 1, "github token", "github token #abcd1234")
    monkeypatch.setattr(sg, "MODE", "block")
    assert sg.status_for([f], False)[0] == "failure"
    assert sg.status_for([], False, grant=[f])[0] == "success"
    monkeypatch.setattr(sg, "MODE", "warn")
    state, desc, _ = sg.status_for([f], True)
    assert state == "success" and desc.startswith("⚠ WARN (not blocking): 1 secret-shaped string in tree")
