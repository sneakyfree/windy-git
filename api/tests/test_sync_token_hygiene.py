"""scripts/sync_from_github.sh keeps its tokens out of argv and off disk.

10-10: GITHUB_TOKEN rode in every clone URL, so it showed in `ps` to any local
user on Veron and sat in all 32 bare repos' config files. These tests run the
real script and real git against a local smart-HTTP server that only answers
when the right auth header arrives, with fake tokens: the sync must still work,
the tokens (and their base64 forms) must never appear in any process's argv
or in any file under the work dir, and one hung transfer must time out.
"""

from __future__ import annotations

import base64
import os
import shutil
import stat
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# Built in pieces so the repo's own secret-literal invariant (test_g05) stays quiet.
GH_TOKEN = "gho" + "_FAKEsyncTOKENnotREAL" + "0123456789abcdef"
WG_TOKEN = "fakegitea" + "synctoken0123456789abcdefabcd"
GH_AUTH = "Basic " + base64.b64encode(f"x-access-token:{GH_TOKEN}".encode()).decode()
WG_AUTH = "Basic " + base64.b64encode(f"windyadmin:{WG_TOKEN}".encode()).decode()
SECRETS = [GH_TOKEN, WG_TOKEN, GH_AUTH.split()[1], WG_AUTH.split()[1]]

BACKEND = Path(
    subprocess.run(["git", "--exec-path"], capture_output=True, text=True).stdout.strip()
) / "git-http-backend"
pytestmark = pytest.mark.skipif(not BACKEND.exists(), reason="git-http-backend not installed")


def _git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class _Server:
    """/gh/<owner>/<repo>.git and /wg/<owner>/<repo>.git, each demanding its own header."""

    def __init__(self, root: Path, delay=0.0, hang_gh=False):
        self.root, self.delay, self.hang_gh = root, delay, hang_gh
        self.denied = []
        srv = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _serve(self):
                prefix = self.path.split("/")[1]
                want = {"gh": GH_AUTH, "wg": WG_AUTH}.get(prefix)
                if self.headers.get("Authorization") != want:
                    srv.denied.append(self.path)
                    self.send_response(401)
                    self.send_header("WWW-Authenticate", 'Basic realm="t"')
                    self.end_headers()
                    return
                if prefix == "gh" and srv.hang_gh:
                    time.sleep(60)
                    return
                time.sleep(srv.delay)
                path, _, query = self.path.partition("?")
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                env = {
                    "PATH": os.environ["PATH"],
                    "GIT_PROJECT_ROOT": str(srv.root / prefix),
                    "GIT_HTTP_EXPORT_ALL": "1",
                    "REMOTE_USER": "sync",
                    "REQUEST_METHOD": self.command,
                    "PATH_INFO": path[len(prefix) + 1 :],
                    "QUERY_STRING": query,
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                    "CONTENT_LENGTH": str(len(body)),
                    "HTTP_CONTENT_ENCODING": self.headers.get("Content-Encoding", ""),
                    "GIT_PROTOCOL": self.headers.get("Git-Protocol", ""),
                }
                out = subprocess.run([str(BACKEND)], input=body, env=env, capture_output=True).stdout
                head, _, payload = out.partition(b"\r\n\r\n")
                status, headers = 200, []
                for line in head.decode().split("\r\n"):
                    k, _, v = line.partition(": ")
                    if k.lower() == "status":
                        status = int(v.split()[0])
                    elif k:
                        headers.append((k, v))
                self.send_response(status)
                for k, v in headers:
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = _serve

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def world(tmp_path):
    """A GitHub-side repo with one commit on main + a feature branch, an empty Windy Git side,
    and a copy of the sync script whose follow-on steps are no-op stubs."""
    seed = tmp_path / "seed"
    _git("init", "-q", "-b", "main", str(seed))
    (seed / "f").write_text("x")
    _git("add", "f", cwd=seed)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c", cwd=seed)
    _git("branch", "feat/x", cwd=seed)
    for side in ("gh/o", "wg/windyadmin"):
        (tmp_path / "srv" / side).mkdir(parents=True)
    _git("clone", "-q", "--bare", str(seed), str(tmp_path / "srv/gh/o/demo.git"))
    _git("init", "-q", "--bare", str(tmp_path / "srv/wg/windyadmin/demo.git"))

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(ROOT / "scripts/sync_from_github.sh", scripts)
    (scripts / "cancel_unrunnable.sh").write_text("exit 0\n")
    for stub in ("pr_status_bridge.py", "runner_guard.py", "telemetry_emit.py"):
        (scripts / stub).write_text("")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if not shutil.which("timeout"):  # macOS: a minimal `timeout -k K N cmd...`
        shim = bin_dir / "timeout"
        shim.write_text(
            f"#!{sys.executable}\n"
            "import subprocess, sys\n"
            "a = sys.argv[1:]\n"
            "a = a[2:] if a[0] == '-k' else a\n"
            "p = subprocess.Popen(a[1:])\n"
            "try:\n    sys.exit(p.wait(timeout=float(a[0])))\n"
            "except subprocess.TimeoutExpired:\n    p.kill(); sys.exit(124)\n"
        )
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    return tmp_path


def _run(world: Path, server: _Server, timeout_s="300"):
    env = {
        "PATH": f"{world / 'bin'}:{os.environ['PATH']}",
        "HOME": str(world),
        "GITHUB_TOKEN": GH_TOKEN,
        "GITEA_SYNC_TOKEN": WG_TOKEN,
        "GITHUB_OWNER": "o",
        "SYNC_REPOS": "demo",
        "SYNC_NO_TAGS": "",
        "SYNC_WORK": str(world / "work"),
        "GITHUB_GIT_BASE": f"{server.base}/gh",
        "WG_GIT_BASE": f"{server.base}/wg",
        "SYNC_GIT_TIMEOUT": timeout_s,
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }
    ps = subprocess.run(["ps", "-eo", "pid="], capture_output=True, text=True).stdout
    before = {int(x) for x in ps.split()}
    proc = subprocess.Popen(
        ["bash", str(world / "scripts/sync_from_github.sh")],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    argvs = set()
    while proc.poll() is None:  # every new process's argv, as any local user would see it
        ps = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True).stdout
        for line in ps.splitlines():
            pid, _, args = line.strip().partition(" ")
            if "git" in args and int(pid) not in before:
                argvs.add(args)
        time.sleep(0.02)
    return proc.returncode, proc.stdout.read(), argvs


def _files_with_secrets(d: Path):
    hits = []
    for p in d.rglob("*"):
        if p.is_file():
            data = p.read_bytes()
            if any(s.encode() in data for s in SECRETS):
                hits.append(str(p.relative_to(d)))
    return hits


def test_sync_works_with_tokens_only_in_headers(world):
    server = _Server(world / "srv", delay=0.3)  # slow enough for ps to see every git process
    try:
        rc, out, argvs = _run(world, server)
    finally:
        server.close()
    assert rc == 0, out
    assert "all repos in step with GitHub" in out
    assert server.denied == []
    heads = subprocess.run(
        ["git", "--git-dir", str(world / "srv/wg/windyadmin/demo.git"), "branch", "--format=%(refname:short)"],
        capture_output=True, text=True,
    ).stdout.split()
    assert sorted(heads) == ["feat/x", "main"]
    assert any("remote-http" in a or "fetch" in a or "push" in a for a in argvs), "ps never saw git"
    assert [a for a in argvs if any(s in a for s in SECRETS)] == []
    assert _files_with_secrets(world / "work") == []
    assert stat.S_IMODE((world / "work").stat().st_mode) == 0o750


def test_old_clone_with_token_in_its_url_is_cleaned(world):
    server = _Server(world / "srv")
    try:
        (world / "work").mkdir()
        _git("clone", "-q", "--bare", str(world / "srv/gh/o/demo.git"), str(world / "work/demo.git"))
        old = f"{server.base.replace('://', f'://x-access-token:{GH_TOKEN}@')}/gh/o/demo.git"
        _git("--git-dir", str(world / "work/demo.git"), "remote", "set-url", "origin", old)
        assert _files_with_secrets(world / "work") == ["demo.git/config"]
        rc, out, _ = _run(world, server)
    finally:
        server.close()
    assert rc == 0, out
    assert _files_with_secrets(world / "work") == []


def test_wrong_header_is_refused_so_the_test_server_is_honest(world):
    # The server must reject an unauthenticated git: otherwise the tests above prove nothing.
    server = _Server(world / "srv")
    try:
        r = subprocess.run(
            ["git", "ls-remote", f"{server.base}/gh/o/demo.git"],
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_GLOBAL": "/dev/null"},
            capture_output=True, text=True, timeout=30,
        )
    finally:
        server.close()
    assert r.returncode != 0 and server.denied


def test_a_hung_fetch_times_out_instead_of_stalling_the_sync(world):
    server = _Server(world / "srv", hang_gh=True)
    try:
        t0 = time.monotonic()
        rc, out, _ = _run(world, server, timeout_s="3")
    finally:
        server.close()
    assert rc == 1
    assert "FAILED initial clone of demo (timed out after 3s)" in out
    assert time.monotonic() - t0 < 30
