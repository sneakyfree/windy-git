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
# age: Windy Git's own test_backup_encryption.py (3 tests) skipped on every CI run without it, so
# the backup round-trip never gated (Boss 10-27: CI runs the WHOLE suite, no silent holes).
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends gettext-base=0.21-4ubuntu4 zsh=5.8.1-1 age=1.0.0-1ubuntu0.1 \
 && rm -rf /var/lib/apt/lists/*

# pwsh (PowerShell 7.4 LTS): windyword-site's scripts/j2-browser.test.mjs (#225, the J2 VM's
# browser cleanup) skips without it, so it never gated (Word, 10-27). Microsoft's own .deb from the
# PowerShell GitHub release, pinned by version AND sha256 (= the release's hashes.sha256), so no
# new apt source is trusted; its deps (libicu70, libssl3, libgssapi-krb5-2) come from Ubuntu's.
ARG PWSH_VERSION=7.4.22
ARG PWSH_SHA256=c9053b126a7b8a9872b9933ab3a64ce9d5b6e54d2dcb6fcc5243558e0bda4649
RUN curl -fsSL -o /tmp/pwsh.deb \
      "https://github.com/PowerShell/PowerShell/releases/download/v${PWSH_VERSION}/powershell_${PWSH_VERSION}-1.deb_amd64.deb" \
 && echo "${PWSH_SHA256}  /tmp/pwsh.deb" | sha256sum -c - \
 && apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends /tmp/pwsh.deb \
 && rm -f /tmp/pwsh.deb && rm -rf /var/lib/apt/lists/*

# rclone v1.60.1 (EXACT): WindyCloud's deploy/vault-b2-copy tests wrap the real rclone and parse its
# --use-json-log output, whose format changes between versions; prod (Veron) runs 1.60.1, so CI
# must too (Cloud, #201, 10-27). Without it 11 tests failed. Upstream .deb pinned by sha256 =
# SHA256SUMS on both github.com and downloads.rclone.org, whose PGP signature verifies with
# rclone's release key FBF737ECE9F8AB18604BD2AC93935E02FF3B54FA (checked 10-27). No apt source added.
ARG RCLONE_VERSION=1.60.1
ARG RCLONE_SHA256=1c89af499e9d81c3ee2af8fa74a88414c22657c3df439f4d812e803bff5671cd
RUN curl -fsSL -o /tmp/rclone.deb \
      "https://github.com/rclone/rclone/releases/download/v${RCLONE_VERSION}/rclone-v${RCLONE_VERSION}-linux-amd64.deb" \
 && echo "${RCLONE_SHA256}  /tmp/rclone.deb" | sha256sum -c - \
 && apt-get install -y -qq --no-install-recommends /tmp/rclone.deb \
 && rm -f /tmp/rclone.deb

LABEL windy-git.keep="1" \
      windy-git.base="catthehacker/ubuntu:act-22.04@sha256:3488f78aa97770c8d5d835f2913c1a782d3121ad3f2aafb17054fb1d554ea4e1"
