"""I-4 — never a one-way door (strand G11).

Every repo push-mirrors to GitHub, continuously, from the first save. This is
not a nicety and it is not a migration step: it is the thing that makes moving
off GitHub a reversible decision rather than a bet.

Today GitHub's durability is free to Grant. The moment repos live only here,
backups, restore rehearsal and a second copy stop being someone else's job — and
the August audits found **no rehearsed restore anywhere in the ecosystem**, for
anything. A continuous mirror buys back that safety for zero dollars.

Mirror health is a monitored, alerting signal. A mirror nobody checks is a
belief, not a backup — and this ecosystem has already learned that lesson the
expensive way with a fleet canary that sat dead for 37 days while everything
downstream assumed it was fine.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

from api.app.config import Settings
from api.app.errors import RepairPointer

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class MirrorService:
    """Creates the GitHub counterpart and asks Gitea to keep it in step.

    Gitea owns the actual replication (`push_mirrors`), because a hand-rolled
    mirror loop is a background job that fails silently — which is precisely how
    the registry's integrity refresh went its entire life calling a 404 and
    incrementing a counter instead of raising.
    """

    def __init__(self, settings: Settings) -> None:
        self._s = settings

    @property
    def configured(self) -> bool:
        return bool(self._s.github_token and self._s.github_owner)

    def _require(self) -> None:
        if not self.configured:
            raise RepairPointer(
                status_code=503,
                code="mirror_unconfigured",
                speak="The off-site copy isn't switched on yet.",
                machine_cause="GITHUB_TOKEN or GITHUB_OWNER is unset; refusing to claim a mirror",
                remediation_tool=None,
            )

    async def ensure_github_repo(self, name: str, description: str, private: bool) -> str:
        """Idempotent. Returns the clone URL of the off-site copy."""
        self._require()
        headers = {
            "Authorization": f"Bearer {self._s.github_token}",
            "Accept": "application/vnd.github+json",
        }
        owner = self._s.github_owner
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            existing = await client.get(
                f"https://api.github.com/repos/{owner}/{name}", headers=headers
            )
            if existing.status_code == 200:
                return existing.json()["clone_url"]

            created = await client.post(
                "https://api.github.com/user/repos",
                headers=headers,
                json={
                    "name": name,
                    "description": f"{description} (Windy Git mirror)".strip(),
                    "private": private,
                    "auto_init": False,
                },
            )
        if created.status_code not in (200, 201):
            raise RepairPointer(
                status_code=502,
                code="mirror_target_failed",
                speak="We couldn't set up the off-site copy. Your work here is safe.",
                machine_cause=f"POST /user/repos -> {created.status_code}: {created.text[:200]}",
                remediation_tool="windy_git.repair.resync_mirror",
            )
        return created.json()["clone_url"]

    async def attach_push_mirror(self, owner: str, repo: str, remote_url: str) -> None:
        """Ask Gitea to keep the off-site copy in step on every save."""
        self._require()
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(
                f"{self._s.gitea_base_url}/api/v1/repos/{owner}/{repo}/push_mirrors",
                headers={
                    "Authorization": f"token {self._s.gitea_admin_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "remote_address": remote_url,
                    "remote_username": self._s.github_owner,
                    "remote_password": self._s.github_token,
                    "interval": self._s.mirror_interval,
                    # The important one: mirror on every save, not just on a timer.
                    # An hourly timer means an hour of work can be the thing you
                    # lose, and the window is invisible until it costs you.
                    "sync_on_commit": True,
                },
            )
        if r.status_code not in (200, 201):
            raise RepairPointer(
                status_code=502,
                code="mirror_attach_failed",
                speak="We couldn't keep the off-site copy in step. Your work here is safe.",
                machine_cause=f"POST push_mirrors -> {r.status_code}: {r.text[:200]}",
                remediation_tool="windy_git.repair.resync_mirror",
            )

    async def status(self, owner: str, repo: str) -> dict:
        """Report what is TRUE, including 'we do not know'.

        `me-fleet.ts:22-25` in a sibling service refuses to say "online" when it
        only knows "registered". Same posture here: an unconfigured mirror is
        reported as unknown, never as healthy.
        """
        if not self.configured:
            return {"state": "unconfigured", "lag_seconds": None, "last_success_at": None}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(
                f"{self._s.gitea_base_url}/api/v1/repos/{owner}/{repo}/push_mirrors",
                headers={"Authorization": f"token {self._s.gitea_admin_token}"},
            )
        if r.status_code != 200:
            return {"state": "unknown", "detail": f"gitea -> {r.status_code}"}

        mirrors = r.json()
        if not mirrors:
            return {"state": "absent", "lag_seconds": None, "last_success_at": None}

        m = mirrors[0]
        last = m.get("last_update") or m.get("last_updated")
        lag = None
        if last:
            try:
                lag = int(
                    (datetime.now(UTC) - datetime.fromisoformat(last.replace("Z", "+00:00")))
                    .total_seconds()
                )
            except ValueError:
                lag = None

        # A mirror that has NEVER run is not the same thing as one that is
        # behind, and collapsing the two is how a backup that was never made
        # gets read as a backup that is merely stale. Gitea reports the epoch
        # for "not yet", which arithmetic turns into a 56-year lag and a
        # confident "degraded".
        never_synced = not last or last.startswith("1970-01-01")

        # I-4: lag over the threshold is a P2, not a shrug.
        if never_synced:
            state = "pending"
            lag = None
        elif lag is None:
            state = "unknown"
        elif lag > self._s.mirror_lag_p2_seconds:
            state = "degraded"
        else:
            state = "healthy"
        return {
            "state": state,
            "lag_seconds": lag,
            "last_success_at": None if never_synced else last,
            "remote": m.get("remote_address"),
        }
