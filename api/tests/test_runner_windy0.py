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
    # IPv6: everything but DNS is dropped (the LAN's global prefix is on-link; dropping only ::1/fe80/fc00 left it open)
    v6 = next(ln for ln in NFT.splitlines() if "all v6 except DNS" in ln)
    assert v6.strip() == 'meta nfproto ipv6 counter drop comment "windygit-ci: all v6 except DNS"'
    assert "fe80::/10" not in NFT and max(NFT.index(x) for x in NFT.splitlines() if "ip6 daddr @DNS6@" in x) < NFT.index(v6)
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
    assert "v6 drop counter did not rise" in p and "v4 drop counter did not rise" in p and "cannot reach public" in p and "runuser -u" in p
    assert 'exit "$fail"' in p


def test_install_checks_the_uid_validates_the_rule_set_and_does_not_start_runners():
    i = (D / "install.sh").read_text()
    assert '"$UID_CI" = 1002' in i and "nft -c -f /etc/nftables.d/windygit-ci.nft" in i
    code = [ln for ln in i.splitlines() if not ln.lstrip().startswith(("#", "echo"))]
    assert "enable --now windygit-ci-egress.service" in i
    assert not any("systemctl --user" in ln or "act_runner register" in ln for ln in code)     # starts no runner


# ---------------------------------------------------------------- the probe, run against fake nft / runuser / ip
FAKE_RUNUSER = r"""#!/usr/bin/env bash
# runuser -u USER -- timeout N bash -c "exec 3<>/dev/tcp/HOST/PORT": decide from HOST like the real firewall would
cmd="${@: -1}"; host=${cmd#*/dev/tcp/}; host=${host%%/*}
case " $FAKE_OPEN " in *" $host "*) exit 0;; esac
if [[ "$host" == *:* ]]; then [ -n "${FAKE_NO_COUNT:-}" ] || echo $(( $(cat "$FAKE_DIR/v6") + 1 )) > "$FAKE_DIR/v6"; exit 1; fi
if [ "$host" = 1.1.1.1 ]; then [ -n "${FAKE_PUBLIC_BLOCKED:-}" ] && exit 1 || exit 0; fi
[ -n "${FAKE_NO_COUNT:-}" ] || echo $(( $(cat "$FAKE_DIR/v4") + 1 )) > "$FAKE_DIR/v4"; exit 1
"""
FAKE_NFT = r"""#!/usr/bin/env bash
[ "$1 $2" = "list table" ] && exit 0
echo "    ip daddr { 10.0.0.0/8 } counter packets $(cat "$FAKE_DIR/v4") bytes 0 drop comment \"windygit-ci: private v4\""
echo "    meta nfproto ipv6 counter packets $(cat "$FAKE_DIR/v6") bytes 0 drop comment \"windygit-ci: all v6 except DNS\""
"""
FAKE_IP = r"""#!/usr/bin/env bash
[ -n "${FAKE_NO_NEIGH:-}" ] && exit 0
echo "fe80::1 dev eth0 lladdr aa:bb:cc:dd:ee:ff router REACHABLE"
echo "2001:db8:1::77 dev eth0 lladdr aa:bb:cc:dd:ee:01 REACHABLE"
"""


def probe(tmp_path, **env):
    import os
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    for n, body in (("runuser", FAKE_RUNUSER), ("nft", FAKE_NFT), ("ip", FAKE_IP)):
        (bindir / n).write_text(body)
        (bindir / n).chmod(0o755)
    (tmp_path / "v4").write_text("0")
    (tmp_path / "v6").write_text("0")
    e = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_DIR": str(tmp_path), **env}
    r = subprocess.run(["bash", str(D / "egress-probe.sh")], capture_output=True, text=True, env=e, timeout=60)
    return r.returncode, r.stdout


def test_probe_passes_when_v4_and_v6_are_blocked_and_the_public_side_is_open(tmp_path):
    rc, out = probe(tmp_path)
    assert rc == 0 and "PASS (6 private v4 + 3 v6 targets refused" in out


def test_probe_fails_when_a_lan_host_is_reachable_over_global_v6(tmp_path):
    rc, out = probe(tmp_path, FAKE_OPEN="2001:db8:1::77")                  # the exact gap Hub found on 11-05
    assert rc == 1 and "reached IPv6 target" in out and "PASS" not in out


def test_probe_fails_when_a_public_v6_target_is_reachable(tmp_path):
    rc, out = probe(tmp_path, FAKE_OPEN="2606:4700:4700::1111")
    assert rc == 1 and "reached IPv6 target" in out


def test_probe_fails_when_the_v6_drop_counter_does_not_rise_even_if_connects_fail(tmp_path):
    rc, out = probe(tmp_path, FAKE_NO_COUNT="1")
    assert rc == 1 and "v6 drop counter did not rise" in out and "v4 drop counter did not rise" in out


def test_probe_fails_on_a_reachable_private_v4_and_on_a_too_tight_public_side(tmp_path):
    rc, out = probe(tmp_path, FAKE_OPEN="192.168.0.1")
    assert rc == 1 and "reached private 192.168.0.1:80" in out
    rc, out = probe(tmp_path, FAKE_PUBLIC_BLOCKED="1")
    assert rc == 1 and "cannot reach public" in out


def test_probe_with_no_lan_neighbour_warns_and_still_proves_the_public_v6_drop(tmp_path):
    rc, out = probe(tmp_path, FAKE_NO_NEIGH="1")
    assert rc == 0 and "WARN: no global v6 neighbour" in out and "PASS (6 private v4 + 1 v6 targets" in out
