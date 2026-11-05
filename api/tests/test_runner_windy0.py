"""deploy/runner-windy0: Windy 0 builds CI for secret-free repos as the rootless-podman user windygit-ci (Grant 11-04).
The host config is files + one nft template; these tests pin what must not drift: the egress block, the CPU/memory cap,
the per-runner limits, and that nothing about the home network is committed to this PUBLIC repo."""

from __future__ import annotations

import configparser
import re
import subprocess
from pathlib import Path

import pytest

D = Path(__file__).resolve().parents[2] / "deploy" / "runner-windy0"
NFT = (D / "windygit-ci.nft.in").read_text()
PRIVATE_V4 = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16", "127.0.0.0/8"]


def unit(name: str) -> configparser.ConfigParser:
    c = configparser.ConfigParser(strict=False, interpolation=None)
    c.optionxform = str
    c.read_string((D / name).read_text())
    return c


@pytest.mark.parametrize("f", ["register.sh", "install.sh", "egress-probe.sh"])
def test_the_scripts_parse(f):
    subprocess.run(["bash", "-n", str(D / f)], check=True)


def test_the_filter_only_ever_matches_the_ci_user_and_says_so_first():
    rules = [ln.strip() for ln in NFT.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    first = next(r for r in rules if r.startswith("meta "))
    assert first == "meta skuid != 1002 return"                         # every other process on the host is untouched
    assert "type filter hook output priority 0; policy accept;" in NFT   # accept: only the drops below block
    assert NFT.index("meta skuid != 1002 return") < NFT.index("drop")


def test_every_private_range_is_dropped_for_the_ci_user_and_dns_goes_to_one_resolver_only():
    for r in PRIVATE_V4:
        assert r in NFT
    drop = next(ln for ln in NFT.splitlines() if "private v4" in ln)
    assert "counter drop" in drop and all(r in drop for r in PRIVATE_V4)
    assert "fe80::/10" in NFT and "fc00::/7" in NFT and "::1" in NFT
    allow = [ln for ln in NFT.splitlines() if "dport 53 accept" in ln]
    assert len(allow) == 4 and all("@DNS4@" in ln or "@DNS6@" in ln for ln in allow)
    # the DNS allowances come BEFORE the drops (the router is inside 192.168/16)
    assert max(NFT.index(a) for a in allow) < NFT.index("counter drop")


def test_no_home_network_address_is_committed_to_this_public_repo():
    for f in D.iterdir():
        text = f.read_text()
        assert not re.search(r"\b192\.168\.\d+\.\d+\b", text.replace("192.168.0.0/16", "").replace("192.168.0.1:80", "")), f.name
        assert "2600:" not in text and "fe80::1" not in text, f.name
    assert NFT.count("@DNS4@") == 2 and NFT.count("@DNS6@") == 2


def test_the_cap_is_four_cpus_and_24_gb_with_no_swap():
    s = unit("windygit-cap.conf")["Slice"]
    assert s["CPUQuota"] == "400%" and s["MemoryMax"] == "24G" and s["MemorySwapMax"] == "0"


def test_the_egress_unit_is_loaded_before_the_network_and_remove_it_on_stop():
    u = unit("windygit-ci-egress.service")
    assert u["Service"]["Type"] == "oneshot" and u["Service"]["RemainAfterExit"] == "yes"
    assert "nft -f /etc/nftables.d/windygit-ci.nft" in u["Service"]["ExecStart"]
    assert "delete table inet windygit_ci" in u["Service"]["ExecStop"]
    assert u["Unit"]["Before"] == "network.target" and u["Install"]["WantedBy"] == "multi-user.target"


def test_the_runner_unit_is_a_per_number_user_unit_on_the_podman_socket():
    u = unit("act-runner@.service")
    s = u["Service"]
    assert "podman.sock" in s["Environment"] and "runner-%i" in s["WorkingDirectory"]
    assert s["ExecStart"].endswith("--config /var/lib/windygit-ci/runner-%i/config.yaml") and s["Restart"] == "on-failure"
    assert u["Install"]["WantedBy"] == "default.target"


def test_the_runner_config_runs_one_job_unprivileged_with_its_own_limits():
    c = (D / "config.yaml.in").read_text()
    assert "capacity: 1" in c and "privileged: false" in c and "--cpus=2" in c and "--memory=4g" in c
    assert "--memory-swap=4g" in c and "timeout: 150m" in c and c.count("@N@") == 2
    assert "windy-git-ci/ubuntu:22.04-1" in c and "valid_volumes: []" in c


def test_register_refuses_a_repo_with_any_actions_secret_and_keeps_the_token_off_argv():
    r = (D / "register.sh").read_text()
    assert 'REFUSED: windyadmin/$repo sees $secrets Actions secret(s)' in r and '[ "$secrets" = 0 ]' in r
    assert "s.repo_id=0 and s.owner_id=p.owner_id" in r and "s.owner_id=0 and s.repo_id=0" in r      # owner + instance level
    assert re.search(r"printf '%s\\n' \"\$tok\" \| ssh", r)                                       # stdin, not argv
    assert "--token" not in r and "REGISTRATION_TOKEN=" not in r.replace('"$T"', "")
    assert '[[ "$tok" =~ ^[A-Za-z0-9]{30,80}$ ]]' in r and '[[ "$n" =~ ^[1-4]$ ]]' in r


def test_the_probe_proves_the_block_by_refusals_and_by_the_drop_counter_and_checks_the_open_side():
    p = (D / "egress-probe.sh").read_text()
    for t in ("10.255.255.1", "192.168.0.1", "172.16.0.1", "100.64.0.1", "169.254.169.254", "127.0.0.1"):
        assert t in p
    assert "drop counters did not rise" in p and "cannot reach public" in p and "runuser -u" in p
    assert 'exit "$fail"' in p


def test_install_checks_the_uid_validates_the_rule_set_and_does_not_start_runners():
    i = (D / "install.sh").read_text()
    assert '"$UID_CI" = 1002' in i and "nft -c -f /etc/nftables.d/windygit-ci.nft" in i
    code = [ln for ln in i.splitlines() if not ln.lstrip().startswith(("#", "echo"))]
    assert "enable --now windygit-ci-egress.service" in i
    assert not any("systemctl --user" in ln or "act_runner register" in ln for ln in code)     # starts no runner
