# MEMBRANE.v1 — windy-git

**This file mirrors invariant I-2 and is the complete surface.** Adding a call
means editing I-2 in `DNA_STRAND_MASTER_PLAN.md` **first**, then this file, then
the code. Not the other way round.

Mirrored into `windy-cloud` and `eternitas` on change.

## Calls OUT

| Target | Route | Why |
|---|---|---|
| windy-cloud kernel | `GET /api/v1/storage/objects`, `HEAD` | read user objects in order to version them (D-8) |
| windy-cloud kernel | `POST /api/v1/storage/quota/check` | G4.6 — we ask, the kernel decides and owns the price (I-11) |
| eternitas | `GET /api/v1/trust/{passport}` | band + allowed_actions |
| eternitas | `GET /api/v1/registry/{passport}/integrity` | ⚠️ note the path — `windy-registry` calls `/api/v1/passports/{p}/status`, which 404s, which is why the integrity index has never been populated |
| account-server | OIDC discovery + JWKS | human identity (G3.1) |
| windy-cloud-sites | `POST /api/v1/sites/{id}/versions` | publish docs from a repo |

## Calls IN

| Route | Caller | Why |
|---|---|---|
| `POST /internal/repo-from-folder` | Cloud portal | git-enable a Windy Cloud folder (G5.1) |
| `POST /internal/mirror-status` | ops | I-4 mirror health |

## Events OUT

`repo.created` · `repo.pushed` · `release.published` · `model.published` · `ci.completed`

## Events IN

`passport.revoked` (**fail-closed**, G3.5) · `storage.quota.exceeded` · `identity.created`

## Webhook contract

⚠️ Four consumers in this ecosystem currently disagree in four ways on the
webhook contract, and two integrations have **never once delivered successfully**
— account-server sends `X-Windy-Signature` while Windy-Clone requires
`X-Windy-Pro-Signature` plus a timestamp header the producer never sends at all,
and the payload field names differ too.

**This cell adopts the `windy-contracts` shape and does not invent a fifth.**
One header name, one timestamp header, one payload field name, HMAC both
directions, and a producer→consumer conformance test in the shared suite.
