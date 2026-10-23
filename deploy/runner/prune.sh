#!/usr/bin/env bash
# Keep CI storage bounded (2026-09-23).
#
# Kit 0's 09-01 wipe began with CI `_work` dirs (74 GB) + Docker filling the
# disk. Windy Git's runners have no host `_work` dir — every job runs in a
# container inside the CI-only dind — so the thing that grows here is dind's
# image/volume store (38 GB when this was written, never pruned). This prunes
# ONLY that daemon, over its own socket. It never touches the host's Docker.
#
# In-use images/volumes are never removed, so a running job is safe.
set -euo pipefail
CAP_GB="${CI_STORAGE_CAP_GB:-60}"
D=(docker exec windy-git-runner-dind-1 docker -H tcp://127.0.0.1:2375)  # dind listens on TCP only

"${D[@]}" container prune -f --filter until=6h >/dev/null
# Job workspaces of finished jobs. NOT `volume prune -a`: that also took act-toolcache
# (/opt/hostedtoolcache, shared by every job), so each prune left it empty and the
# next parallel batch all ran setup-node/python into the same path at once; one
# job deleted the node another was running ("No such file" / "Text file busy",
# windy-chat #377 runs 1107 + 1112, 10-16). Keep it, but cap it: over the cap it
# goes too (one racy batch, then warm again).
TOOLCACHE_CAP_GB="${CI_TOOLCACHE_CAP_GB:-8}"
# Measure the volume dind ACTUALLY uses (its mount at /var/lib/docker), never a hardcoded name:
# the sysbox move (dind-storage -> dind-storage-sysbox) left both caps measuring the idle old
# volume, so they never fired (Hub, 10-22). No mount found = refuse, never a silent "under cap".
STORE=$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/var/lib/docker"}}{{.Source}}{{end}}{{end}}' windy-git-runner-dind-1)
[[ -n "$STORE" && -d "$STORE" ]] || { echo "ci storage UNKNOWN: dind has no /var/lib/docker mount"; exit 1; }
TC="$STORE/volumes/act-toolcache"
tc_gb=$(du -s --block-size=1G "$TC" 2>/dev/null | cut -f1 || true)
keep=act-toolcache; (( ${tc_gb:-0} > TOOLCACHE_CAP_GB )) && keep=
# An empty $keep matches no volume name, so then nothing is kept.
"${D[@]}" volume ls -q --filter dangling=true | { grep -vxF "$keep" || true; } \
  | xargs -r "${D[@]}" volume rm >/dev/null 2>&1 || true   # in use since listing: skipped
# Idle job networks. A job that dies before its container attaches leaks its network (24 piled up
# over days, 10-06); dind has only ~31 address pools, so once they fill every new job fails in
# 0-1 s with "all predefined address pools have been fully subnetted" (looked like load flakes).
# until=1h: never touch the network of a job that is starting right now.
"${D[@]}" network prune -f --filter until=1h >/dev/null
"${D[@]}" image prune -af --filter until=168h --filter label!=windy-git.keep=1 >/dev/null
"${D[@]}" builder prune -af --filter until=168h >/dev/null 2>&1 || true

used_gb=$(du -s --block-size=1G "$STORE" | cut -f1)
if (( used_gb > CAP_GB )); then
  # Over the cap even after the age-based pass: drop every unused image. The
  # next jobs re-pull (the act image is ~2 GB) — slower, never wrong.
  "${D[@]}" image prune -af --filter label!=windy-git.keep=1 >/dev/null  # never the local CI image
  used_gb=$(du -s --block-size=1G "$STORE" | cut -f1)
fi
echo "ci storage ${used_gb}G (cap ${CAP_GB}G)"
(( used_gb <= CAP_GB )) || { echo "STILL OVER CAP"; exit 1; }
