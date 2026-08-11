# Third-party notices — Windy Git

Windy Git runs **stock Gitea** as an unforked component (D-2 / I-1). Gitea is
distributed under the MIT license, reproduced in `gitea-MIT.txt`.

MIT's only obligation is that the copyright notice and license text travel with
copies of the software that are **distributed**. Running Windy Git as a hosted
service is not distribution, so strictly this file is not required today — it is
here anyway, because it will be required the moment a self-host bundle ships, and
because shipping it costs nothing.

MIT does **not** require us to advertise the lineage, does not restrict
commercial use, and does not require publishing our modifications. That last
point is why Gitea (MIT) was chosen over Forgejo (GPLv3 from v9): GPLv3 does not
trigger on running a service — that is AGPL, and it is widely gotten wrong — but
it **does** trigger on distributing a binary, which the self-host line would do.

**Gitea's trademarks are not used.** The product is branded Windy Git throughout.

| Component | Version | License |
|---|---|---|
| Gitea | 1.24.6 (pinned) | MIT — `gitea-MIT.txt` |
| PostgreSQL | 16 | PostgreSQL License |
| cloudflared | 2026.1.2 | Apache-2.0 |
