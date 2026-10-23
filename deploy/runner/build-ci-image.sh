#!/usr/bin/env bash
# Build Windy Git's CI job image inside the CI dind (jobs run there, so that's where it must
# live) and prove the tools are in it. Run on Veron as root. Idempotent; prints the image id.
set -euo pipefail
TAG="${CI_IMAGE_TAG:-windy-git-ci/ubuntu:22.04-1}"
D=(docker exec -i windy-git-runner-dind-1 docker -H tcp://127.0.0.1:2375)  # dind listens on TCP only
cd "$(dirname "$0")/ci-image"
tar -c Dockerfile | "${D[@]}" build -q -t "$TAG" - >/dev/null
"${D[@]}" run --rm "$TAG" sh -c 'command -v envsubst && dpkg-query -W -f '"'"'${Package} ${Version}\n'"'"' gettext-base'
"${D[@]}" image inspect "$TAG" --format "built $TAG {{.Id}} keep={{index .Config.Labels \"windy-git.keep\"}}"
