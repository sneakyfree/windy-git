# Windy Git's CI job image (runs-on: self-hosted / linux / x64 / veron-1 / linux-x64).
# = catthehacker/ubuntu:act-22.04 pinned BY DIGEST (the copy every job ran on until 10-22)
# + the few distro tools lanes' tests need, each pinned to an exact version.
# Built INSIDE the CI dind by deploy/runner/build-ci-image.sh; never pushed to a registry,
# so prune.sh must keep it (label windy-git.keep=1): a pruned local image can't be re-pulled.
FROM catthehacker/ubuntu@sha256:3488f78aa97770c8d5d835f2913c1a782d3121ad3f2aafb17054fb1d554ea4e1

# gettext-base = envsubst. windy-chat's render tests (render-synapse-*) need it; without it
# they skipped silently on every green run (Chat, run 1683, 10-22).
# zsh: windy-pro-mobile's mobile-round-posts-every-job.test.ts spawns scripts/bench/mobile-round.sh
# directly via zsh (the script's own shebang is #!/bin/zsh); without it those 3 cases could only
# skip-with-a-reason, never run for real (Mobile, run 43/#370, 10-24).
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends gettext-base=0.21-4ubuntu4 zsh=5.8.1-1 \
 && rm -rf /var/lib/apt/lists/*

LABEL windy-git.keep="1" \
      windy-git.base="catthehacker/ubuntu:act-22.04@sha256:3488f78aa97770c8d5d835f2913c1a782d3121ad3f2aafb17054fb1d554ea4e1"
