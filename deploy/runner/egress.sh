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
set -euo pipefail

NET=windy-git-runner_jobs
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

# Hooks: remove any stale ones (the bridge name changes if the network is
# recreated), then add exactly one of each at the top.
for chain in DOCKER-USER INPUT; do
  target=$([ "$chain" = INPUT ] && echo WG-CI-INPUT || echo WG-CI-EGRESS)
  while read -r rule; do
    iptables -D $chain ${rule#-A $chain }
  done < <(iptables -S "$chain" | grep -- "-j $target" || true)
  iptables -I "$chain" 1 -i "$BR" -j "$target"
done

echo "ci egress filter active on $BR ($NET)"
