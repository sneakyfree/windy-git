# Windy 0 CI runners (Grant 11-04: build CI on Windy 0, capped 4 CPU / 24 GB)

Windy 0 (Fedora, SELinux enforcing) runs act_runner as the rootless-podman user `windygit-ci` (uid 1002, linger on) for
SECRET-FREE repos only. Today: w0-1 windy-text, w0-2 windy-connect, w0-3 windy-mail, w0-4 WindyCloud.

| file | goes to |
|---|---|
| `windygit-cap.conf` | `/etc/systemd/system/user-1002.slice.d/` (4 CPUs, 24 GB, no swap for everything uid 1002 runs) |
| `windygit-ci.nft.in` | rendered by `install.sh` to `/etc/nftables.d/windygit-ci.nft`: for uid 1002 only, DNS to the host's resolver, every private/loopback/CGNAT range dropped (counted). No address is committed here: this repo is public |
| `windygit-ci-egress.service` | loads that table at boot, before the network |
| `act-runner@.service` | `~windygit-ci/.config/systemd/user/`, one instance per runner number |
| `config.yaml.in` | `runner-N/config.yaml` (`@N@` -> N): 1 job, unprivileged, `--cpus=2 --memory=4g`, 150 min, image `localhost/windy-git-ci/ubuntu:22.04-1` |
| `registries-docker-io.conf` | podman short-name resolution (`docker.io`) |
| `register.sh` | ON VERON: `bash register.sh N repo`. Refuses a repo that sees ANY Actions secret (repo, owner, instance); the registration token goes Gitea -> ssh stdin -> the register command, never argv |
| `egress-probe.sh` | ON WINDY 0 as root: proves the block (6 private targets refused + drop counter rose + a public address still connects) |

Install: `sudo bash install.sh` on Windy 0 (checks the uid, renders and `nft -c`-validates the rules, enables the egress unit;
starts no runner). Then per runner N: `mkdir -p /var/lib/windygit-ci/runner-N/cache` as windygit-ci, render `config.yaml.in`,
`bash register.sh N repo` on Veron, `chmod 600 runner-N/.runner`, and as windygit-ci `systemctl --user enable --now act-runner@N`.
The CI image is built separately as windygit-ci with `podman build --format docker` (OCI format drops the Dockerfile `SHELL`).

The offsite guard (`scripts/offsite_secret_guard.py`, every 10 min on Veron) covers `w0-*` runners: a row that sees a secret, a
malformed row, or a failed egress unit stops the runners and soft-deletes the rows. The image's `python3` is 3.10 (Ubuntu 22.04).

Tests: `api/tests/test_runner_windy0.py`.
