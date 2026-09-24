"""guards_report: job attribution and the Grant-owned split."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("guards_report", ROOT / "scripts" / "guards_report.py")
gr = importlib.util.module_from_spec(_spec)
sys.modules["guards_report"] = gr
_spec.loader.exec_module(gr)

OWNED = yaml.safe_load((ROOT / "ci" / "grant-owned.yml").read_text())["grant_owned"]
WF = """name: CI
on:
  push:
jobs:
  reality-check:
    runs-on: x
    steps:
      - run: npm install jsdom
  test-backend:
    runs-on: x
    steps:
      - run: pip install pytest
"""


def test_job_of_attributes_lines_to_their_job():
    assert gr.job_of(WF, 3) is None            # `on:` block, not a job
    assert gr.job_of(WF, 8) == "reality-check"
    assert gr.job_of(WF, 12) == "test-backend"


def test_windy_pro_desktop_jobs_and_paths_are_grant_owned():
    ci = ".github/workflows/ci.yml"
    assert gr.grant_owned("windy-pro", ci, "reality-check", OWNED)
    assert gr.grant_owned("windy-pro", ci, "build-electron", OWNED)
    assert not gr.grant_owned("windy-pro", ci, "test-backend", OWNED)       # server side: 8c
    assert gr.grant_owned("windy-pro", ".github/workflows/release-mac.yml", None, OWNED)
    assert gr.grant_owned("windy-pro", "src/client/desktop/main.js", None, OWNED)
    assert not gr.grant_owned("windy-pro", "services/account-server/Dockerfile", None, OWNED)
    assert not gr.grant_owned("windy-chat", "src/client/desktop/main.js", None, OWNED)


def test_render_splits_lane_and_grant_counts():
    F = gr.cg.Finding
    res = {"windy-pro": {"sha": "a" * 40, "compute": [],
                         "hygiene": [(F("ci.yml", 8, "floating install", "npm install"), "reality-check", True),
                                     (F("ci.yml", 12, "floating install", "pip x"), "test-backend", False)]},
           "windy-git": {"sha": "b" * 40, "compute": [], "hygiene": []}}
    md = gr.render(res)
    assert "| ci-hygiene (house rule 6) | 1 | 1 | ❌ not yet |" in md
    assert "| compute-guard (Mind is the only door) | 0 | 0 | ✅ YES |" in md
    assert "| windy-git | Windy Git | bbbbbbb | 0 | 0 | clean ✅ |" in md
    assert "| windy-pro | Windy Hub | aaaaaaa |" in md  # owner = session to message
    assert "(job reality-check)" in md


def test_windy_pro_root_env_example_is_grant_owned_but_not_the_account_servers():
    assert gr.grant_owned("windy-pro", ".env.example", None, OWNED)
    assert not gr.grant_owned("windy-pro", "account-server/.env.example", None, OWNED)


def test_split_grant_sends_desktop_code_to_grant(monkeypatch):
    F = gr.cg.Finding
    fs = [F("src/client/desktop/main.js", 3, "provider host", "x"),
          F("account-server/src/llm.ts", 5, "provider host", "y")]
    lane, grant = gr.split_grant("windy-pro", "a" * 40, fs)
    assert [f.path for f in grant] == ["src/client/desktop/main.js"]
    assert [f.path for f in lane] == ["account-server/src/llm.ts"]
    assert gr.split_grant("windy-chat", "a" * 40, fs) == (fs, [])
