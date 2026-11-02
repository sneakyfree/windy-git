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

# One run at a time (Hub 11-02): the timer and a tailscaled restart can fire together.
exec 9>/run/windygit-ci-egress.lock
flock -w 120 9 || { echo "ci egress: another run held the lock for 120 s" >&2; exit 1; }

NET="${CI_JOBS_NET:-windy-git-runner_jobs}"   # Null 0's offsite runners: windy-git-runner-offsite_jobs
id=$(docker network inspect "$NET" --format '{{.Id}}')
BR="br-${id:0:12}"
ip link show "$BR" >/dev/null

# NEVER an empty or half-built filter while hooked (Hub 11-02; the 15-min timer made this matter).
# The hooks jump to a fixed ENTRY chain that holds ONE jump to the current generation (<entry>-A or
# -B). Each run builds the idle generation complete, inserts the entry's jump to it at position 1,
# THEN removes the old jump (and, once, the pre-11-02 inline rules), and only then flushes the old
# generation. A packet always meets a complete rule set.
swap() {   # swap ENTRY < rules, one per line
  local entry=$1 cur new line
  iptables -N "$entry" 2>/dev/null || true
  cur=$(iptables -S "$entry" | awk -v a="$entry-A" -v b="$entry-B" '$1 == "-A" && ($NF == a || $NF == b) {print $NF; exit}')
  if [ "$cur" = "$entry-A" ]; then new="$entry-B"; else new="$entry-A"; fi
  iptables -N "$new" 2>/dev/null || iptables -F "$new"
  while read -r line; do
    [ -n "$line" ] && iptables -A "$new" $line
  done
  iptables -I "$entry" 1 -j "$new"
  while [ "$(iptables -S "$entry" | grep -c '^-A ')" -gt 1 ]; do iptables -D "$entry" 2; done
  if [ -n "$cur" ]; then iptables -F "$cur"; fi
}

swap WG-CI-EGRESS <<EOF
-o $BR -j RETURN
-m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
-p udp --dport 53 -j RETURN
-p tcp --dport 53 -j RETURN
-d 10.0.0.0/8 -j DROP
-d 172.16.0.0/12 -j DROP
-d 192.168.0.0/16 -j DROP
-d 100.64.0.0/10 -j DROP
-d 169.254.0.0/16 -j DROP
-j RETURN
EOF

swap WG-CI-INPUT <<EOF
-m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
-j DROP
EOF

# Re-assert, and SAY when it had to (Hub 11-02): something (tailscaled restarting) got ahead.
was_first=$(iptables -S FORWARD | sed -n 2p)
if [ "$was_first" != "-A FORWARD -i $BR -j WG-CI-EGRESS" ]; then
  echo "ci egress: hook was NOT first in FORWARD (first rule was: ${was_first:-none}); moving it back to 1"
fi

# Hooks: the new jump goes in at 1 FIRST, then every older copy (stale bridge names too) is removed
# by rule number, highest first, so there is never a moment without a hook.
for chain in FORWARD DOCKER-USER INPUT; do
  target=$([ "$chain" = INPUT ] && echo WG-CI-INPUT || echo WG-CI-EGRESS)
  iptables -I "$chain" 1 -i "$BR" -j "$target"
  for n in $(iptables -L "$chain" -n --line-numbers | awk -v t="$target" 'NR > 2 && $2 == t && $1 > 1 {print $1}' | sort -rn); do
    iptables -D "$chain" "$n"
  done
done

# IPv6: the jobs network has IPv6 off; if it is ever turned on, drop every v6 packet from the CI
# bridge (forwarded or to this host) rather than leave a second, unfiltered path. Same order.
for chain in FORWARD INPUT; do
  ip6tables -I "$chain" 1 -i "$BR" -j DROP
  for n in $(ip6tables -L "$chain" -n -v --line-numbers | awk -v br="$BR" 'NR > 2 && $4 == "DROP" && $7 == br && $1 > 1 {print $1}' | sort -rn); do
    ip6tables -D "$chain" "$n"
  done
done

# FORWARD's FIRST rule must be our hook: anything ahead of it (ts-forward) can ACCEPT CI traffic
# before the drop sees it. Fail loudly, never a silent half-filter.
first=$(iptables -S FORWARD | sed -n 2p)
if [ "$first" != "-A FORWARD -i $BR -j WG-CI-EGRESS" ]; then
  echo "ci egress filter NOT first in FORWARD (first rule: $first)" >&2
  exit 1
fi

echo "ci egress filter active on $BR ($NET), first in FORWARD"
