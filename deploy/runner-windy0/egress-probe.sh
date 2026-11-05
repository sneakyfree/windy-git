#!/usr/bin/env bash
# Prove the Windy 0 CI egress block. Run ON WINDY 0 AS ROOT (sudo bash egress-probe.sh). Exit 0 = proven, 1 = NOT.
# As the CI user (uid windygit-ci) every private range must refuse a TCP connect and the nft drop counter must rise;
# a public address must still connect. Connects use bash /dev/tcp with a timeout: nothing is sent but a SYN.
set -u
USER_CI="${CI_USER:-windygit-ci}"
PRIVATE=("10.255.255.1:80" "192.168.0.1:80" "172.16.0.1:80" "100.64.0.1:80" "169.254.169.254:80" "127.0.0.1:22")
PUBLIC="${PUBLIC_TARGET:-1.1.1.1:443}"
drops() { nft list chain inet windygit_ci out 2>/dev/null | grep -E 'counter packets [0-9]+ bytes [0-9]+ drop' \
  | sed -E 's/.*counter packets ([0-9]+) .*/\1/' | paste -sd+ - | bc 2>/dev/null; }
tcp() { runuser -u "$USER_CI" -- timeout "${2:-4}" bash -c "exec 3<>/dev/tcp/${1%:*}/${1#*:}" 2>/dev/null; }
fail=0
nft list table inet windygit_ci >/dev/null 2>&1 || { echo "FAIL: nft table windygit_ci is not loaded"; exit 1; }
before=$(drops); before=${before:-0}
for t in "${PRIVATE[@]}"; do
  if tcp "$t"; then echo "FAIL: $USER_CI reached private $t"; fail=1; fi
done
after=$(drops); after=${after:-0}
[ "$after" -gt "$before" ] || { echo "FAIL: drop counters did not rise ($before -> $after): the block was not what stopped them"; fail=1; }
tcp "$PUBLIC" 8 || { echo "FAIL: $USER_CI cannot reach public $PUBLIC (egress too tight)"; fail=1; }
if [ "$fail" = 0 ]; then echo "egress probe: PASS (${#PRIVATE[@]} private targets refused, drop counters $before -> $after, public $PUBLIC reachable)"; fi
exit "$fail"
