#!/usr/bin/env bash
# CI egress PROOF (2026-11-02): from inside the CI dind, exactly where a job's traffic starts,
# every private target must be CLOSED and the public controls OPEN. Run as root on the CI host
# after egress.sh (windygit-ci-egress.service does both, every 15 min, under windy-job, so a FAIL
# reaches windy-uptime's heartbeat alert, not just a log).
#
# A "closed" only counts if the HOST itself can reach that target: otherwise the port is simply
# shut and proves nothing about the filter. Targets, found fresh each run:
#   * up to 4 online tailnet peers (tailscale status --json), port 22;
#   * up to 3 LAN neighbours (ip neigh) and up to 2 WireGuard peers, the first of 22/80/443/8080
#     the host reaches (port 53 is NOT a target: egress.sh allows DNS on purpose, Docker's
#     embedded resolver forwards to the LAN router);
#   * this host's own LAN, WireGuard and tailnet IPs, port 22.
# Controls that must stay OPEN: 1.1.1.1:443 and https://app.windygit.com (jobs fetch the forge).
# Output for windy-job --expect: "egress probe: PASS ..." or "egress probe: FAIL ...". Exit 1 on FAIL.
set -uo pipefail

DIND="${CI_DIND:-windy-git-runner-dind-1}"
IMAGE="${CI_PROBE_IMAGE:-localhost/windy-git-ci/ubuntu:22.04-1}"
D=(docker exec -i "$DIND" docker -H tcp://127.0.0.1:2375)

host_open() { timeout 3 bash -c "</dev/tcp/$1/$2" 2>/dev/null; }

targets=()   # "ip port label", only ones the HOST reaches
peers=$(tailscale status --json 2>/dev/null | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except ValueError:
    sys.exit(0)
n = 0
for p in (d.get("Peer") or {}).values():
    ips = [i for i in p.get("TailscaleIPs") or [] if "." in i]
    if p.get("Online") and ips and n < 4:
        print(ips[0], p.get("HostName", "?").replace(" ", "_")); n += 1')
while read -r ip name; do
  [ -n "${ip:-}" ] && host_open "$ip" 22 && targets+=("$ip 22 tailnet:$name")
done <<< "$peers"
first_open() {   # ip label: add the first port the host reaches
  local port
  for port in 22 80 443 8080; do
    if host_open "$1" "$port"; then targets+=("$1 $port $2"); return; fi
  done
}
dev=$(ip -4 route show default | awk '{print $5; exit}')
n=0
for ip in $(ip -4 neigh show dev "$dev" 2>/dev/null | awk '$NF ~ /REACHABLE|STALE|DELAY/ {print $1}'); do
  [ $n -ge 3 ] && break
  before=${#targets[@]}; first_open "$ip" "lan:$ip"; [ ${#targets[@]} -gt "$before" ] && n=$((n + 1))
done
n=0
for ip in $(wg show all allowed-ips 2>/dev/null | grep -oE '([0-9]+\.){3}[0-9]+/32' | cut -d/ -f1); do
  [ $n -ge 2 ] && break
  before=${#targets[@]}; first_open "$ip" "wireguard:$ip"; [ ${#targets[@]} -gt "$before" ] && n=$((n + 1))
done
for ip in $(ip -4 -o addr show scope global | awk '{split($4, a, "/"); print a[1]}'); do
  case "$ip" in 172.*) continue;; esac          # docker bridges: not a route a job has
  host_open "$ip" 22 && targets+=("$ip 22 host:$ip")
done

if [ "${#targets[@]}" -eq 0 ]; then
  echo "egress probe: FAIL no private target reachable even from the host (nothing proved)"
  exit 1
fi

script='p(){ if timeout 5 bash -c "</dev/tcp/$1/$2" 2>/dev/null; then echo "OPEN $1:$2 $3"; else echo "closed $1:$2 $3"; fi; }'
for t in "${targets[@]}"; do script+="; p $t"; done
script+='; p 1.1.1.1 443 control:public'
script+='; c=$(curl -s -o /dev/null -m 15 -w "%{http_code}" https://app.windygit.com/api/healthz); [ "$c" = 200 ] && echo "OPEN forge control:forge" || echo "closed forge control:forge($c)"'

out=$("${D[@]}" run --rm --network bridge "$IMAGE" bash -c "$script" 2>&1)
rc=$?
echo "$out"
if [ $rc -ne 0 ]; then
  echo "egress probe: FAIL the probe container did not run (exit $rc)"
  exit 1
fi
leaks=$(grep -E '^OPEN ' <<< "$out" | grep -v 'control:' || true)
dead=$(grep -E '^closed .*control:' <<< "$out" || true)
if [ -n "$leaks" ] || [ -n "$dead" ]; then
  echo "egress probe: FAIL private reachable: ${leaks:-none} | controls closed: ${dead:-none}" | tr '\n' ' '
  echo
  exit 1
fi
echo "egress probe: PASS (${#targets[@]} private targets closed from a CI container, controls open)"
