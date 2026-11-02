#!/usr/bin/env bash
# CI egress filter (2026-09-23) — jobs reach the internet, never Grant's network.
#
# Measured before this existed: an ordinary (unprivileged) job container inside
# the CI dind could open SSH, Ollama, and every dev server on Veron
# (192.168.1.73:22/3000/3300/8080/11434) and anything else on the LAN, WireGuard
# or Tailscale. No container escape needed — a malicious npm/pip dependency in
# any first-party repo's CI could walk straight onto the fleet.
#
# All CI traffic leaves through the `windy-git-runner_jobs` bridge (dind NATs
# its job containers onto it). This script, run at boot and after any runner
# compose change, allows on that bridge:
#   * traffic between the runners and dind (same bridge)
#   * replies (ESTABLISHED/RELATED)
#   * DNS (53) — Docker's embedded resolver forwards to the LAN router
#   * everything public
# and drops: RFC1918, CGNAT/Tailscale (100.64/10), link-local, and ANY packet
# addressed to the host itself (INPUT), whatever interface IP it targets.
# Idempotent: owned chains are flushed and rebuilt; hooks are added once.
#
# 2026-11-02 (self-found, Boss + Hub told): the DOCKER-USER hook alone was NOT enough. Tailscale
# puts its own `ts-forward` chain FIRST in FORWARD, and it ACCEPTs everything leaving through
# tailscale0, so a CI job could open TCP to every tailnet machine (null-zero:22 and OC5:22 were
# open; the LAN and this host were closed). The egress chain is now ALSO hooked at FORWARD
# position 1, ahead of anything Tailscale or Docker adds, and this script fails if it is not
# first. Tailscale re-inserts its chain when tailscaled restarts, so windygit-ci-egress.timer
# re-runs this every 15 min (and the unit runs after tailscaled). Proof: egress-probe.sh.
set -euo pipefail

NET="${CI_JOBS_NET:-windy-git-runner_jobs}"   # Null 0's offsite runners: windy-git-runner-offsite_jobs
id=$(docker network inspect "$NET" --format '{{.Id}}')
BR="br-${id:0:12}"
ip link show "$BR" >/dev/null

iptables -N WG-CI-EGRESS 2>/dev/null || iptables -F WG-CI-EGRESS
iptables -A WG-CI-EGRESS -o "$BR" -j RETURN
iptables -A WG-CI-EGRESS -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
iptables -A WG-CI-EGRESS -p udp --dport 53 -j RETURN
iptables -A WG-CI-EGRESS -p tcp --dport 53 -j RETURN
for cidr in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 169.254.0.0/16; do
  iptables -A WG-CI-EGRESS -d "$cidr" -j DROP
done
iptables -A WG-CI-EGRESS -j RETURN

iptables -N WG-CI-INPUT 2>/dev/null || iptables -F WG-CI-INPUT
iptables -A WG-CI-INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
iptables -A WG-CI-INPUT -j DROP

# Re-assert, and SAY when it had to (Hub 11-02): something (tailscaled restarting) got ahead.
was_first=$(iptables -S FORWARD | sed -n 2p)
if [ "$was_first" != "-A FORWARD -i $BR -j WG-CI-EGRESS" ]; then
  echo "ci egress: hook was NOT first in FORWARD (first rule was: ${was_first:-none}); moving it back to 1"
fi

# Hooks: remove any stale ones (the bridge name changes if the network is
# recreated), then add exactly one of each at the top.
for chain in FORWARD DOCKER-USER INPUT; do
  target=$([ "$chain" = INPUT ] && echo WG-CI-INPUT || echo WG-CI-EGRESS)
  while read -r rule; do
    iptables -D $chain ${rule#-A $chain }
  done < <(iptables -S "$chain" | grep -- "-j $target" || true)
  iptables -I "$chain" 1 -i "$BR" -j "$target"
done

# IPv6: the jobs network has IPv6 off; if it is ever turned on, drop every v6 packet from the CI
# bridge (forwarded or to this host) rather than leave a second, unfiltered path.
for chain in FORWARD INPUT; do
  while ip6tables -C "$chain" -i "$BR" -j DROP 2>/dev/null; do ip6tables -D "$chain" -i "$BR" -j DROP; done
  ip6tables -I "$chain" 1 -i "$BR" -j DROP
done

# FORWARD's FIRST rule must be our hook: anything ahead of it (ts-forward) can ACCEPT CI traffic
# before the drop sees it. Fail loudly, never a silent half-filter.
first=$(iptables -S FORWARD | sed -n 2p)
if [ "$first" != "-A FORWARD -i $BR -j WG-CI-EGRESS" ]; then
  echo "ci egress filter NOT first in FORWARD (first rule: $first)" >&2
  exit 1
fi

echo "ci egress filter active on $BR ($NET), first in FORWARD"
