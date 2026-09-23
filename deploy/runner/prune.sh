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
"${D[@]}" volume prune -af >/dev/null            # job workspaces of finished jobs
"${D[@]}" image prune -af --filter until=168h >/dev/null
"${D[@]}" builder prune -af --filter until=168h >/dev/null 2>&1 || true

used_gb=$(du -s --block-size=1G /var/lib/docker/volumes/windy-git-runner_dind-storage | cut -f1)
if (( used_gb > CAP_GB )); then
  # Over the cap even after the age-based pass: drop every unused image. The
  # next jobs re-pull (the act image is ~2 GB) — slower, never wrong.
  "${D[@]}" image prune -af >/dev/null
  used_gb=$(du -s --block-size=1G /var/lib/docker/volumes/windy-git-runner_dind-storage | cut -f1)
fi
echo "ci storage ${used_gb}G (cap ${CAP_GB}G)"
(( used_gb <= CAP_GB )) || { echo "STILL OVER CAP"; exit 1; }
