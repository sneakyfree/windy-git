#!/usr/bin/env bash
# CI egress PROOF (2026-11-02): from inside the CI dind, exactly where a job's traffic starts, every
# private target must be CLOSED, and it must be OUR filter that closed it. Run as root on the CI host
# after egress.sh (windygit-ci-egress.service does both, every 15 min, under windy-job, so a FAIL
# reaches windy-uptime's heartbeat alert, not just a log).
#
# CONTAINER ONLY (Boss 11-02): the recurring probe makes NO host-side connection. Every attempt is
# dropped inside this host (FORWARD for other machines, INPUT for this host's own IPs), so no packet
# reaches another machine and no fleet log sees anything. "Closed" alone could just be a shut port,
# so the proof is the packet COUNTERS of our own DROP rules: each target family's counter must go UP
# during the probe. --with-host-check adds a host-side reachability check (it connects to fleet
# sshd and is logged there): by hand only, never from the timer.
#
# Targets are an EXPLICIT FLEET LIST, never "whatever answers" (11-02: picking any online tailnet
# peer touched a person's Mac and Grant's PC). Never Kit 0, Windy 0, a personal device or a phone:
#   * tailnet: CI_PROBE_TAILNET host names (default null-zero kit-0c3-dell kit-0c4-lenovo
#     kit-0c5-imac), resolved locally from tailscale status, port 22;
#   * WireGuard: CI_PROBE_WG IPs (default 10.10.0.3 = OC3, 10.10.0.4 = OC4), port 22. Never
#     10.10.0.1 (Kit 0) or Veron's own 10.10.0.6 (that one is covered as a host IP below);
#   * LAN: the default gateway, port 80 (never 53: egress.sh allows DNS on purpose, Docker's
#     embedded resolver forwards to the LAN router);
#   * this host's own LAN, WireGuard and tailnet IPs, port 22 (the INPUT drop).
# Controls that must stay OPEN: 1.1.1.1:443 and https://app.windygit.com (jobs fetch the forge).
# Output for windy-job --expect: "egress probe: PASS ..." or "egress probe: FAIL ...". Exit 1 on FAIL.
set -uo pipefail

DIND="${CI_DIND:-windy-git-runner-dind-1}"
IMAGE="${CI_PROBE_IMAGE:-localhost/windy-git-ci/ubuntu:22.04-1}"
D=(docker exec -i "$DIND" docker -H tcp://127.0.0.1:2375)
HOST_CHECK=0
[ "${1:-}" = "--with-host-check" ] && HOST_CHECK=1

host_open() { timeout 3 bash -c "</dev/tcp/$1/$2" 2>/dev/null; }

targets=()   # "ip port family:label"
add() {      # ip port label; --with-host-check: only targets the host itself reaches count
  if [ "$HOST_CHECK" = 1 ] && ! host_open "$1" "$2"; then return; fi
  targets+=("$1 $2 $3")
}
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
    if p.get("HostName") == want and ips:
        print(ips[0]); break' "$name")
  [ -n "$ip" ] && add "$ip" 22 "tailnet:$name"
done
for ip in $WG; do
  case "$ip" in 10.10.0.1) continue;; esac                       # Kit 0 on WireGuard: never
  add "$ip" 22 "wireguard:$ip"
done
gw=$(ip -4 route show default | awk '{print $3; exit}')
[ -n "$gw" ] && add "$gw" 80 "lan:gateway"
for ip in $(ip -4 -o addr show scope global | awk '{split($4, a, "/"); print a[1]}'); do
  case "$ip" in 172.*) continue;; esac          # docker bridges: not a route a job has
  add "$ip" 22 "host:$ip"
done

if [ "${#targets[@]}" -eq 0 ]; then
  echo "egress probe: FAIL no target to test (nothing proved)"
  exit 1
fi

# Packet counters of our DROP rules: the current generation of WG-CI-EGRESS (per range) and of
# WG-CI-INPUT (this host). Printed as "<key> <packets>", keys: 100.64.0.0/10 10.0.0.0/8 192.168.0.0/16 input.
gen_of() {   # the chain holding the rules: <entry>-A/-B (egress.sh since 11-02), else the entry itself
  local g
  g=$(iptables -S "$1" 2>/dev/null | awk -v a="$1-A" -v b="$1-B" '$1 == "-A" && ($NF == a || $NF == b) {print $NF; exit}')
  echo "${g:-$1}"
}
counters() {
  iptables -L "$(gen_of WG-CI-EGRESS)" -n -v -x 2>/dev/null | awk '$3 == "DROP" {print $9, $1}'
  iptables -L "$(gen_of WG-CI-INPUT)" -n -v -x 2>/dev/null | awk '$3 == "DROP" {print "input", $1}'
}
family_key() {   # target label -> counter key
  case "$1" in
    tailnet:*) echo 100.64.0.0/10;; wireguard:*) echo 10.0.0.0/8;; lan:*) echo 192.168.0.0/16;; host:*) echo input;;
  esac
}
before=$(counters)

script='p(){ if timeout 5 bash -c "</dev/tcp/$1/$2" 2>/dev/null; then echo "OPEN $1:$2 $3"; else echo "closed $1:$2 $3"; fi; }'
for t in "${targets[@]}"; do script+="; p $t"; done
script+='; p 1.1.1.1 443 control:public'
script+='; c=$(curl -s -o /dev/null -m 15 -w "%{http_code}" https://app.windygit.com/api/healthz); [ "$c" = 200 ] && echo "OPEN forge control:forge" || echo "closed forge control:forge($c)"'

out=$("${D[@]}" run --rm --network bridge "$IMAGE" bash -c "$script" 2>&1)
rc=$?
after=$(counters)
echo "$out"
if [ $rc -ne 0 ]; then
  echo "egress probe: FAIL the probe container did not run (exit $rc)"
  exit 1
fi
leaks=$(grep -E '^OPEN ' <<< "$out" | grep -v 'control:' || true)
dead=$(grep -E '^closed .*control:' <<< "$out" || true)
unproved=""
for t in "${targets[@]}"; do
  key=$(family_key "${t##* }")
  b=$(awk -v k="$key" '$1 == k {print $2}' <<< "$before"); a=$(awk -v k="$key" '$1 == k {print $2}' <<< "$after")
  if [ -z "$a" ] || [ "${a:-0}" -le "${b:-0}" ]; then unproved+=" ${t##* }($key ${b:-?}->${a:-?})"; fi
done
if [ -n "$leaks" ] || [ -n "$dead" ] || [ -n "$unproved" ]; then
  echo "egress probe: FAIL private reachable: ${leaks:-none} | controls closed: ${dead:-none} | not dropped by our filter:${unproved:- none}" | tr '\n' ' '
  echo
  exit 1
fi
echo "egress probe: PASS (${#targets[@]} private targets closed BY our drop rules, counters rose; controls open; $([ "$HOST_CHECK" = 1 ] && echo with || echo no) host-side check)"
