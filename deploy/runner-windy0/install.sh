#!/usr/bin/env bash
# Install the Windy 0 CI runner host config (idempotent). Run ON WINDY 0 AS ROOT from this directory:
#   sudo bash install.sh
# Needs: user windygit-ci (uid 1002, rootless podman, linger on), act_runner at /usr/local/bin/act_runner.
# Does NOT register or start a runner (register.sh on Veron does, per repo) and does NOT build the CI image.
set -euo pipefail
cd "$(dirname "$0")"
CI=windygit-ci; UID_CI=$(id -u "$CI"); HOME_CI=/var/lib/windygit-ci
[ "$UID_CI" = 1002 ] || { echo "windygit-ci must be uid 1002 (the nft file matches that uid), it is $UID_CI"; exit 1; }
DNS4=$(resolvectl dns 2>/dev/null | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' | head -1 || true)
DNS6=$(resolvectl dns 2>/dev/null | grep -oE '[0-9a-f]*:[0-9a-f:]+' | head -1 || true)
[ -n "${DNS4:-}" ] || { echo "no IPv4 resolver found; set DNS4=... and rerun"; exit 1; }
install -d /etc/systemd/system/user-1002.slice.d /etc/nftables.d
install -m 644 windygit-cap.conf /etc/systemd/system/user-1002.slice.d/windygit-cap.conf
sed -e "s/@DNS4@/$DNS4/g" -e "s/@DNS6@/${DNS6:-::1}/g" windygit-ci.nft.in > /etc/nftables.d/windygit-ci.nft
nft -c -f /etc/nftables.d/windygit-ci.nft
install -m 644 windygit-ci-egress.service /etc/systemd/system/windygit-ci-egress.service
install -d -o "$CI" -g "$CI" "$HOME_CI/.config/systemd/user" "$HOME_CI/.config/containers/registries.conf.d"
install -m 644 -o "$CI" -g "$CI" act-runner@.service "$HOME_CI/.config/systemd/user/act-runner@.service"
install -m 644 -o "$CI" -g "$CI" registries-docker-io.conf "$HOME_CI/.config/containers/registries.conf.d/10-docker-io.conf"
systemctl daemon-reload
systemctl enable --now windygit-ci-egress.service
echo "installed. Per runner N: mkdir $HOME_CI/runner-N/cache as $CI, render config.yaml.in (@N@ -> N) to runner-N/config.yaml,"
echo "register from Veron: bash deploy/runner-windy0/register.sh N <repo>; then (as $CI) systemctl --user enable --now act-runner@N."
echo "prove the block: sudo bash egress-probe.sh"
