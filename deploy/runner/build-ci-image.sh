#!/usr/bin/env bash
# Build Windy Git's CI job images inside the CI dind (jobs run there, so that's where they
# must live) and prove them. Run on Veron as root. Idempotent.
#   localhost/windy-git-ci/ubuntu:22.04-0  rollback: the old job image by digest + keep label
#   localhost/windy-git-ci/ubuntu:22.04-1  the job image: + pinned tools (gettext-base/envsubst, zsh, pwsh 7.4)
# The localhost/ prefix makes a pull from Docker Hub impossible: a missing image fails loudly.
# After switching dind storage (e.g. the privileged-compose rollback volume), re-run this:
# local images live in the dind volume.
set -euo pipefail
BASE="${CI_IMAGE_BASE_TAG:-localhost/windy-git-ci/ubuntu:22.04-0}"
TAG="${CI_IMAGE_TAG:-localhost/windy-git-ci/ubuntu:22.04-1}"
D=(docker exec -i windy-git-runner-dind-1 docker -H tcp://127.0.0.1:2375)  # dind listens on TCP only
cd "$(dirname "$0")/ci-image"
tar -c --transform 's/Dockerfile.base/Dockerfile/' Dockerfile.base | "${D[@]}" build -q -t "$BASE" - >/dev/null
tar -c Dockerfile | "${D[@]}" build -q -t "$TAG" - >/dev/null
# Prove EVERY pinned tool, not just the first one (Boss 10-27: zsh was added in #69 but never
# proved here). `set -e` inside: any missing tool fails the build script.
"${D[@]}" run --rm "$TAG" sh -ec '
  command -v envsubst; dpkg-query -W -f '"'"'${Package} ${Version}\n'"'"' gettext-base
  zsh --version
  pwsh -NoProfile -NoLogo -Command "\$PSVersionTable.PSVersion.ToString()"'
for t in "$BASE" "$TAG"; do
  "${D[@]}" image inspect "$t" --format "built $t {{.Id}} keep={{index .Config.Labels \"windy-git.keep\"}}"
done
