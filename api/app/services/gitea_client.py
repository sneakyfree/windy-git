"""The Gitea membrane (I-1 / D-2).

Everything this cell needs from Gitea goes through this file and through Gitea's
REST API. Nothing else in the codebase imports Gitea concepts, and nothing
anywhere writes Gitea's database directly — it has its own role and its own
database precisely so that boundary is a permission rather than a promise.

Keeping the dependency here is what makes D-2 affordable: Gitea ships every two
or three months including security fixes, and a diverged fork becomes the whole
job within a year for a small team. One file is a seam. A merged source tree is
a marriage.
"""

from __future__ import annotations

import secrets
from typing import Any

import httpx

from api.app.config import Settings
from api.app.errors import RepairPointer, provider_unconfigured

_TIMEOUT = httpx.Timeout(20.0, connect=5.0)


class GiteaClient:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def _require(self) -> None:
        if not self._s.gitea_configured:
            raise provider_unconfigured("gitea", "GITEA_ADMIN_TOKEN")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"token {self._s.gitea_admin_token}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        self._require()
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            return await client.request(
                method,
                f"{self._s.gitea_base_url}/api/v1{path}",
                headers=self._headers(),
                **kw,
            )

    # ---- users ------------------------------------------------------------
    async def ensure_user(self, username: str, email: str) -> dict:
        """Idempotent. Gitea is the component; our `repos` table is the truth."""
        r = await self._request("GET", f"/users/{username}")
        if r.status_code == 200:
            return r.json()
        # Gitea requires a password field on admin user-create and rejects null
        # with a bare 400. Nobody ever uses this one: humans arrive through OIDC
        # and agents through scoped passport-bound tokens, and local password
        # sign-in is disabled server-wide. So we generate a credential that is
        # never stored, never returned and never recoverable — an unusable
        # password is safer than a blank one or a shared default.
        r = await self._request(
            "POST",
            "/admin/users",
            json={
                "username": username,
                "email": email,
                "password": secrets.token_urlsafe(48),
                "must_change_password": False,
            },
        )
        if r.status_code not in (200, 201):
            raise RepairPointer(
                status_code=502,
                code="gitea_user_create_failed",
                speak="We couldn't finish setting up that account. Nothing was lost.",
                machine_cause=f"POST /admin/users -> {r.status_code}: {r.text[:200]}",
                remediation_tool="windy_git.repair.retry_user_create",
            )
        return r.json()

    # ---- repos ------------------------------------------------------------
    async def create_repo(
        self, owner: str, name: str, description: str, private: bool, default_branch: str
    ) -> dict:
        r = await self._request(
            "POST",
            f"/admin/users/{owner}/repos",
            json={
                "name": name,
                "description": description,
                "private": private,
                "auto_init": True,
                "default_branch": default_branch,
                # G4.5 — the LFS threshold is load-bearing, not tidiness. A large
                # blob inside a git pack cannot be resumed or offloaded, and a
                # plain push of one dies at Cloudflare's ~100s ceiling (G4A.5).
                "gitignores": "",
            },
        )
        if r.status_code not in (200, 201):
            raise RepairPointer(
                status_code=502 if r.status_code >= 500 else 409,
                code="repo_create_failed",
                speak="We couldn't create that project. Try a different name.",
                machine_cause=f"POST /admin/users/{owner}/repos -> {r.status_code}: {r.text[:200]}",
                remediation_tool=None,
            )
        return r.json()

    async def delete_repo(self, owner: str, name: str) -> None:
        r = await self._request("DELETE", f"/repos/{owner}/{name}")
        if r.status_code not in (204, 404):
            raise RepairPointer(
                status_code=502,
                code="repo_delete_failed",
                speak="We couldn't remove that project. It is still there and still yours.",
                machine_cause=f"DELETE /repos/{owner}/{name} -> {r.status_code}",
                remediation_tool="windy_git.repair.retry_delete",
            )

    async def get_repo(self, owner: str, name: str) -> dict | None:
        r = await self._request("GET", f"/repos/{owner}/{name}")
        return r.json() if r.status_code == 200 else None

    # ---- history (G5.5 / G5.6) -------------------------------------------
    async def list_commits(self, owner: str, name: str, limit: int = 50) -> list[dict]:
        r = await self._request(
            "GET", f"/repos/{owner}/{name}/commits", params={"limit": limit}
        )
        if r.status_code == 409:
            return []  # empty repo — a real state, not an error
        if r.status_code != 200:
            raise RepairPointer(
                status_code=502,
                code="history_unavailable",
                speak="We couldn't load the history for that project just now.",
                machine_cause=f"GET commits -> {r.status_code}",
                remediation_tool="windy_git.repair.rebuild_index",
            )
        return r.json()

    # ---- collaborators (the shelter's enforcement half, G5.3) ------------
    async def put_collaborator(self, owner: str, name: str, user: str, permission: str) -> None:
        r = await self._request(
            "PUT",
            f"/repos/{owner}/{name}/collaborators/{user}",
            json={"permission": permission},
        )
        if r.status_code not in (204, 201, 200):
            raise RepairPointer(
                status_code=502,
                code="grant_apply_failed",
                speak="We couldn't share that project yet. Nobody was given access.",
                machine_cause=f"PUT collaborator -> {r.status_code}: {r.text[:200]}",
                remediation_tool="windy_git.repair.resync_grants",
            )

    async def delete_collaborator(self, owner: str, name: str, user: str) -> None:
        r = await self._request("DELETE", f"/repos/{owner}/{name}/collaborators/{user}")
        if r.status_code not in (204, 404):
            raise RepairPointer(
                status_code=502,
                code="grant_revoke_failed",
                # The honest failure: we could not take access away. That is the
                # scarier direction, so it is stated plainly rather than softened.
                speak="We could not remove that person's access. Please try again.",
                machine_cause=f"DELETE collaborator -> {r.status_code}",
                remediation_tool="windy_git.repair.resync_grants",
            )

    async def version(self) -> str:
        r = await self._request("GET", "/version")
        return r.json().get("version", "unknown")
