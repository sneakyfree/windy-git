"""deploy/runner CI egress (11-02): Tailscale's ts-forward sat ahead of DOCKER-USER and let CI jobs
reach every tailnet machine. The hook must be FIRST in FORWARD, re-asserted after tailscaled and on a
timer, and PROVED from a CI container under windy-job so a failure alerts."""

from __future__ import annotations

import configparser
import re
import subprocess
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[2] / "deploy" / "runner"
EGRESS = (RUNNER / "egress.sh").read_text()
PROBE = (RUNNER / "egress-probe.sh").read_text()


def unit(name: str) -> configparser.ConfigParser:
    c = configparser.ConfigParser(strict=False, interpolation=None)
    c.optionxform = str
    c.read_string((RUNNER / name).read_text())
    return c


def test_both_scripts_parse():
    for f in ("egress.sh", "egress-probe.sh"):
        subprocess.run(["bash", "-n", str(RUNNER / f)], check=True)


def test_the_hook_goes_first_in_forward_and_the_script_fails_if_it_is_not():
    loop = re.search(r"for chain in ([A-Z -]+); do\n  target=", EGRESS)
    assert loop and loop.group(1).split() == ["FORWARD", "DOCKER-USER", "INPUT"]
    assert 'iptables -I "$chain" 1 -i "$BR" -j "$target"' in EGRESS
    check = EGRESS[EGRESS.index("FORWARD's FIRST rule must be our hook"):]
    assert 'iptables -S FORWARD | sed -n 2p' in check and "exit 1" in check
    assert 'moving it back to 1' in EGRESS       # it says when something had got ahead (Hub 11-02)


def test_every_private_range_is_dropped_and_dns_stays_the_only_allowance():
    rules = EGRESS.split("swap WG-CI-EGRESS <<EOF\n")[1].split("\nEOF")[0].splitlines()
    for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16"):
        assert f"-d {cidr} -j DROP" in rules
    assert re.findall(r"--dport (\d+) -j RETURN", "\n".join(rules)) == ["53", "53"]
    assert rules[-1] == "-j RETURN" and rules.index("-d 10.0.0.0/8 -j DROP") > rules.index("-p tcp --dport 53 -j RETURN")
    assert EGRESS.split("swap WG-CI-INPUT <<EOF\n")[1].split("\nEOF")[0].splitlines()[-1] == "-j DROP"


def test_ipv6_from_the_ci_bridge_is_dropped():
    assert 'ip6tables -I "$chain" 1 -i "$BR" -j DROP' in EGRESS
    assert "for chain in FORWARD INPUT; do\n  ip6tables -I" in EGRESS


def test_the_unit_reruns_after_tailscaled_and_is_restartable():
    u = unit("windygit-ci-egress.service")
    assert "tailscaled.service" in u["Unit"]["After"]
    assert "tailscaled.service" in u["Install"]["WantedBy"].split()
    assert u["Service"].get("RemainAfterExit", "no") == "no", "a RemainAfterExit unit can't be re-run by the timer"
    ex = u["Service"]["ExecStart"]
    assert ex.startswith("/usr/local/bin/windy-job windygit-ci-egress ")
    assert '--expect "^egress probe: PASS"' in ex and "--owner 13" in ex
    assert "egress.sh && exec /srv/windygit/src/deploy/runner/egress-probe.sh" in ex


def test_the_timer_reasserts_every_15_minutes():
    t = unit("windygit-ci-egress.timer")
    assert t["Timer"]["OnUnitActiveSec"] == "15min"
    assert t["Install"]["WantedBy"] == "timers.target"


def test_the_probe_fails_loudly_and_only_counts_targets_the_host_reaches():
    assert PROBE.count('echo "egress probe: PASS') == 1
    assert "exit 1" in PROBE and "egress probe: FAIL" in PROBE
    # a shut port proves nothing: every target family is gated on the HOST reaching it
    assert '[ -n "${ip:-}" ] && host_open "$ip" 22 && targets+=("$ip 22 tailnet:$name")' in PROBE
    assert 'if host_open "$1" "$port"; then targets+=("$1 $port $2"); return; fi' in PROBE
    assert 'host_open "$ip" 22 && targets+=("$ip 22 host:$ip")' in PROBE
    assert "for port in 22 80 443 8080" in PROBE and " 53 " not in PROBE.split("for port in")[1].split(";")[0]
    assert "control:public" in PROBE and "control:forge" in PROBE
    assert 'grep -v \'control:\'' in PROBE                      # any private OPEN fails the run


def _after(text: str, first: str, then: str) -> bool:
    return first in text and then in text and text.index(first) < text.index(then)


def test_never_an_empty_or_half_built_filter_while_hooked():
    """Hub 11-02: build the idle generation complete, switch the entry's jump (insert new BEFORE
    removing old), only then flush the old generation; hooks are inserted before old copies go."""
    swap = EGRESS[EGRESS.index("swap() {"):EGRESS.index("swap WG-CI-EGRESS <<EOF")]
    assert 'iptables -N "$new" 2>/dev/null || iptables -F "$new"' in swap      # only the IDLE one is flushed
    assert _after(swap, 'iptables -A "$new" $line', 'iptables -I "$entry" 1 -j "$new"')
    assert _after(swap, 'iptables -I "$entry" 1 -j "$new"', 'iptables -D "$entry" 2')
    assert _after(swap, 'iptables -D "$entry" 2', 'iptables -F "$cur"')
    assert 'iptables -F "$entry"' not in EGRESS and "iptables -F WG-CI" not in EGRESS
    hooks = EGRESS[EGRESS.index("for chain in FORWARD DOCKER-USER INPUT"):]
    assert _after(hooks, 'iptables -I "$chain" 1 -i "$BR" -j "$target"', 'iptables -D "$chain" "$n"')
    assert "$1 > 1" in hooks.split("ip6tables")[0]                             # never deletes the new one
    v6 = EGRESS[EGRESS.index("for chain in FORWARD INPUT"):]
    assert _after(v6, 'ip6tables -I "$chain" 1 -i "$BR" -j DROP', 'ip6tables -D "$chain" "$n"')


def test_one_run_at_a_time():
    assert "exec 9>/run/windygit-ci-egress.lock" in EGRESS and "flock -w 120 9 ||" in EGRESS
    assert EGRESS.index("flock -w 120 9") < EGRESS.index("swap WG-CI-EGRESS <<EOF")
