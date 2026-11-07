"""deploy/runner-offsite (Null 0, Boss GO 11-02): the same isolation as Veron's runners, plus
repo-scoped registration, labels that never claim to be Veron, per-job caps and no mounts."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
OFF = ROOT / "deploy" / "runner-offsite"
VERON = yaml.safe_load((ROOT / "deploy" / "runner" / "config.yaml").read_text())
CFG = yaml.safe_load((OFF / "config.yaml").read_text())
COMPOSE = yaml.safe_load((OFF / "docker-compose.yml").read_text())
REGISTER = (OFF / "register.sh").read_text()
STORE = (OFF / "store-token.sh").read_text()


def test_labels_never_claim_to_be_veron():
    names = [lab.split(":", 1)[0] for lab in CFG["runner"]["labels"]]
    assert names == ["self-hosted", "linux", "x64"]
    assert "veron-1" not in names and "linux-x64" not in names


def test_same_runner_and_container_settings_as_veron_except_the_named_differences():
    off_r, ver_r = dict(CFG["runner"]), dict(VERON["runner"])
    off_r.pop("labels"), ver_r.pop("labels")
    assert off_r == ver_r                                     # capacity 1, 150m ceiling, ...
    off_c, ver_c = dict(CFG["container"]), dict(VERON["container"])
    assert off_c.pop("options") == "--init --cpus=2 --memory=4g --memory-swap=4g"
    assert off_c.pop("valid_volumes") == []                   # nothing a job may mount
    ver_c.pop("options"), ver_c.pop("valid_volumes")
    assert off_c == ver_c
    assert off_c["privileged"] is False and off_c["docker_host"] == "-"


def test_dind_is_sysbox_not_privileged_and_nothing_mounts_a_host_path():
    s = COMPOSE["services"]
    assert COMPOSE["name"] == "windy-git-runner-offsite"
    assert s["dind"]["runtime"] == "sysbox-runc" and not s["dind"].get("privileged")
    for name, svc in s.items():
        for v in svc.get("volumes", []):
            src = v.split(":", 1)[0]
            assert src in ("./config.yaml",) or not src.startswith(("/", "~", ".")), (name, v)
        assert "/var/run/docker.sock" not in str(svc)
    assert s["dind"]["cpus"] == 4.0 and s["dind"]["mem_limit"] == "7g"      # the host keeps >= 4 GB of its 11 (Boss 11-04)


def test_three_runners_each_with_its_own_token_and_volume():
    s = COMPOSE["services"]
    runners = {n: v for n, v in s.items() if n.startswith("runner-")}
    assert sorted(runners) == ["runner-1", "runner-2", "runner-3"]
    assert runners["runner-1"]["environment"]["GITEA_RUNNER_NAME"] == "null0-1"
    assert runners["runner-2"]["environment"]["GITEA_RUNNER_NAME"] == "null0-2"
    assert runners["runner-3"]["environment"]["GITEA_RUNNER_NAME"] == "null0-3"
    assert runners["runner-1"]["environment"]["GITEA_RUNNER_REGISTRATION_TOKEN"] == "${RUNNER_1_TOKEN:-}"
    assert runners["runner-2"]["environment"]["GITEA_RUNNER_REGISTRATION_TOKEN"] == "${RUNNER_2_TOKEN:-}"
    assert runners["runner-3"]["environment"]["GITEA_RUNNER_REGISTRATION_TOKEN"] == "${RUNNER_3_TOKEN:-}"
    vols = [v for r in runners.values() for v in r["volumes"] if not v.startswith("./")]
    assert vols == ["runner-data-1:/data", "runner-data-2:/data", "runner-data-3:/data"]
    assert sorted(COMPOSE["volumes"]) == ["dind-storage", "runner-data-1", "runner-data-2", "runner-data-3"]
    # every runner is capacity 1 and none claims a Veron-only label
    for r in runners.values():
        assert r.get("mem_limit") == "1g" and r.get("cpus") == 1.0


def test_register_refuses_a_repo_with_secrets_and_scopes_the_token_to_one_repo():
    assert 'REFUSED: windyadmin/$repo holds $secrets Actions secret(s)' in REGISTER
    assert '[ "$secrets" = 0 ] ||' in REGISTER
    assert "(s.repo_id = p.id or (s.owner_id = p.owner_id and s.repo_id = 0) or (s.owner_id = 0 and s.repo_id = 0))" in REGISTER
    assert 'generate-runner-token --scope "windyadmin/$repo"' in REGISTER
    assert REGISTER.index('[ "$secrets" = 0 ]') < REGISTER.index("generate-runner-token")
    assert '"sudo -n $DIR/store-token.sh $n"' in REGISTER                 # token only on stdin
    # Gitea prints a log line on stdout before the token: only the last line goes on (11-02)
    gen = REGISTER.index("generate-runner-token")
    assert REGISTER.index("| tail -n 1", gen) < REGISTER.index("| runuser", gen)


def test_register_accepts_runner_1_2_3_and_nothing_else(tmp_path):
    """register.sh stops at its argument check, before touching Gitea or Null 0."""
    def run(n, repo="windy-mind"):
        return subprocess.run(["bash", str(OFF / "register.sh"), n, repo], capture_output=True, text=True,
                              env={"PATH": "/usr/bin:/bin", "WGQ": "/nonexistent-wgq"}, timeout=30)
    for bad in ("0", "4", "12", "x", ""):
        r = run(bad)
        assert r.returncode == 2 and "runner must be 1, 2 or 3" in r.stdout, bad
    r = run("3", "bad repo!")
    assert r.returncode == 2 and "bad repo name" in r.stdout            # runner 3 got past the number check


def test_store_token_reads_stdin_only_and_writes_a_0600_file(tmp_path):
    import getpass
    d = tmp_path / "off"
    d.mkdir()
    (d / "store-token.sh").write_text(STORE)
    (d / ".env").write_text("OTHER=1\nRUNNER_2_TOKEN=keep-this-one-xxxxxxxxxx\n")
    env = {"PATH": "/usr/bin:/bin", "OFFSITE_OWNER": getpass.getuser()}
    r = subprocess.run(["bash", str(d / "store-token.sh"), "1"], input="faketokenfaketoken12345\n",
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "faketoken" not in r.stdout + r.stderr
    text = (d / ".env").read_text()
    assert "RUNNER_1_TOKEN=faketokenfaketoken12345\n" in text and "OTHER=1" in text and "RUNNER_2_TOKEN=keep" in text
    assert oct((d / ".env").stat().st_mode & 0o777) == "0o600"
    r = subprocess.run(["bash", str(d / "store-token.sh"), "1"], input="secondtokensecondtoken9\n",
                       capture_output=True, text=True, env=env)
    text = (d / ".env").read_text()
    assert r.returncode == 0 and text.count("RUNNER_1_TOKEN=") == 1 and "secondtokensecondtoken9" in text
    for bad, code in (("short\n", 3), ("has space in it xxxxxxxxxx\n", 3)):
        r = subprocess.run(["bash", str(d / "store-token.sh"), "1"], input=bad, capture_output=True, text=True, env=env)
        assert r.returncode == code and bad.strip() not in r.stdout + r.stderr
    r = subprocess.run(["bash", str(d / "store-token.sh"), "4"], input="x" * 30, capture_output=True, text=True, env=env)
    assert r.returncode == 2
    r = subprocess.run(["bash", str(d / "store-token.sh"), "3"], input="thirdtokenthirdtoken1234\n", capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "RUNNER_3_TOKEN=thirdtokenthirdtoken1234\n" in (d / ".env").read_text()


def test_the_ci_image_build_can_target_the_offsite_dind():
    b = (ROOT / "deploy" / "runner" / "build-ci-image.sh").read_text()
    assert 'docker exec -i "${CI_DIND:-windy-git-runner-dind-1}"' in b
