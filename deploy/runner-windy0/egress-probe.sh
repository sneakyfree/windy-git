#!/usr/bin/env bash
# Prove the Windy 0 CI egress block. Run ON WINDY 0 AS ROOT (sudo bash egress-probe.sh). Exit 0 = proven, 1 = NOT.
# As the CI user (uid windygit-ci) every private v4 range AND every IPv6 target (a LAN host's GLOBAL v6 taken from the
# neighbour table at run time, never committed, plus a public v6) must refuse a TCP connect, and the matching nft drop
# counter (v4 rule, v6 rule) must rise; a public v4 address must still connect. Connects use bash /dev/tcp with a timeout: nothing is sent but a SYN.
set -u
USER_CI="${CI_USER:-windygit-ci}"
PRIVATE=("10.255.255.1:80" "192.168.0.1:80" "172.16.0.1:80" "100.64.0.1:80" "169.254.169.254:80" "127.0.0.1:22")
PUBLIC="${PUBLIC_TARGET:-1.1.1.1:443}"
drops() { nft list chain inet windygit_ci out 2>/dev/null | grep -F "$1" | sed -E 's/.*counter packets ([0-9]+) .*/\1/' | head -1; }
PUBLIC6="${PUBLIC6_TARGET:-[2606:4700:4700::1111]:443}"
LAN6=$(ip -6 neigh show 2>/dev/null | grep -E 'REACHABLE|STALE|DELAY' | grep -v '^fe80' | awk '{print $1}' | head -1)
tcp() { local h=${1%:*}; h=${h#[}; h=${h%]}; runuser -u "$USER_CI" -- timeout "${2:-4}" bash -c "exec 3<>/dev/tcp/$h/${1##*:}" 2>/dev/null; }
fail=0
nft list table inet windygit_ci >/dev/null 2>&1 || { echo "FAIL: nft table windygit_ci is not loaded"; exit 1; }
V4="windygit-ci: private v4"; V6="windygit-ci: all v6 except DNS"
before=$(drops "$V4"); before=${before:-0}; before6=$(drops "$V6"); before6=${before6:-0}
for t in "${PRIVATE[@]}"; do
  if tcp "$t"; then echo "FAIL: $USER_CI reached private $t"; fail=1; fi
done
after=$(drops "$V4"); after=${after:-0}
[ "$after" -gt "$before" ] || { echo "FAIL: v4 drop counter did not rise ($before -> $after): the block was not what stopped them"; fail=1; }
V6T=("$PUBLIC6"); [ -n "$LAN6" ] && V6T+=("[$LAN6]:22" "[$LAN6]:80") || echo "WARN: no global v6 neighbour in the table; only the public v6 target is probed"
for t in "${V6T[@]}"; do
  if tcp "$t"; then echo "FAIL: $USER_CI reached IPv6 target ${t%%]*}]... (v6 must be dropped but DNS)"; fail=1; fi
done
after6=$(drops "$V6"); after6=${after6:-0}
[ "$after6" -gt "$before6" ] || { echo "FAIL: v6 drop counter did not rise ($before6 -> $after6)"; fail=1; }
tcp "$PUBLIC" 8 || { echo "FAIL: $USER_CI cannot reach public $PUBLIC (egress too tight)"; fail=1; }
if [ "$fail" = 0 ]; then echo "egress probe: PASS (${#PRIVATE[@]} private v4 + ${#V6T[@]} v6 targets refused, v4 drops $before -> $after, v6 drops $before6 -> $after6, public $PUBLIC reachable)"; fi
exit "$fail"
