#!/usr/bin/env bash
# CI egress PROOF (2026-11-02): from inside the CI dind, exactly where a job's traffic starts,
# every private target must be CLOSED and the public controls OPEN. Run as root on the CI host
# after egress.sh (windygit-ci-egress.service does both, every 15 min, under windy-job, so a FAIL
# reaches windy-uptime's heartbeat alert, not just a log).
#
# A "closed" only counts if the HOST itself can reach that target: otherwise the port is simply
# shut and proves nothing about the filter. Targets are an EXPLICIT FLEET LIST, never "whatever
# answers" (11-02: picking any online tailnet peer touched a person's Mac and Grant's PC; never
# again). Never Kit 0, Windy 0, a person's own device or a phone:
#   * tailnet: CI_PROBE_TAILNET host names (default null-zero kit-0c3-dell kit-0c4-lenovo
#     kit-0c5-imac), resolved via tailscale status, port 22;
#   * WireGuard: CI_PROBE_WG IPs (default 10.10.0.3 = OC3, 10.10.0.4 = OC4), port 22. Never
#     10.10.0.1 (Kit 0) or Veron's own 10.10.0.6 (that one is covered as a host IP below);
#   * LAN: the default gateway only, the first of 80/443/8080 the host reaches (port 53 is NOT a
#     target: egress.sh allows DNS on purpose, Docker's resolver forwards to the LAN router);
#   * this host's own LAN, WireGuard and tailnet IPs, port 22.
# Controls that must stay OPEN: 1.1.1.1:443 and https://app.windygit.com (jobs fetch the forge).
# Output for windy-job --expect: "egress probe: PASS ..." or "egress probe: FAIL ...". Exit 1 on FAIL.
set -uo pipefail

DIND="${CI_DIND:-windy-git-runner-dind-1}"
IMAGE="${CI_PROBE_IMAGE:-localhost/windy-git-ci/ubuntu:22.04-1}"
D=(docker exec -i "$DIND" docker -H tcp://127.0.0.1:2375)

host_open() { timeout 3 bash -c "</dev/tcp/$1/$2" 2>/dev/null; }

targets=()   # "ip port label", only ones the HOST reaches
TAILNET="${CI_PROBE_TAILNET:-null-zero kit-0c3-dell kit-0c4-lenovo kit-0c5-imac}"
WG="${CI_PROBE_WG:-10.10.0.3 10.10.0.4}"
for name in $TAILNET; do
  case "$name" in kit-0-alpha|windy-0) continue;; esac          # never, whatever the env says
  ip=$(tailscale status --json 2>/dev/null | python3 -c '
import json, sys
want = sys.argv[1]
try:
    d = json.load(sys.stdin)
except ValueError:
    sys.exit(0)
for p in (d.get("Peer") or {}).values():
    ips = [i for i in p.get("TailscaleIPs") or [] if "." in i]
    if p.get("HostName") == want and p.get("Online") and ips:
        print(ips[0]); break' "$name")
  [ -n "$ip" ] && host_open "$ip" 22 && targets+=("$ip 22 tailnet:$name")
done
for ip in $WG; do
  case "$ip" in 10.10.0.1) continue;; esac                       # Kit 0 on WireGuard: never
  host_open "$ip" 22 && targets+=("$ip 22 wireguard:$ip")
done
gw=$(ip -4 route show default | awk '{print $3; exit}')
for port in 80 443 8080; do
  if [ -n "$gw" ] && host_open "$gw" "$port"; then targets+=("$gw $port lan-gateway"); break; fi
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
