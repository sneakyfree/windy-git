"""The shelter — repos, grants and version history (strand G5, D-8).

Windy Cloud today has **no sharing, no permissions and no versioning of any
kind**: verified 2026-08-11 against `routes/storage.py` and its models, which
contain zero occurrences of share / permission / acl / collaborat / seat /
version / snapshot / history / revision. This plane is not a feature bolted onto
something that already had one — it fills a hole that has never been filled.

D-8 also fixes the order: **permissions and history ship before the git
protocol.** "I want someone to help me with my website" is a real problem for a
real person, and it does not require them to know what a repository is.

Every string a person sees here obeys the D-9 vocabulary law: *version* and
*save point*, never *commit*, and never the countable form of the word "Git" on
any surface, ever. See `scripts/vocab_audit.py`, which enforces this.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.app import throttle
from api.app.auth import ActorType, Caller, get_caller
from api.app.errors import RepairPointer
from api.app.models.core import (
    CreatedVia,
    GrantRole,
    Mirror,
    MirrorState,
    Repo,
    RepoGrant,
    RepoState,
    RepoType,
    RepoVersion,
    Visibility,
)
from api.app.services.gitea_client import GiteaClient
from api.app.services.mirror import MirrorService

router = APIRouter(prefix="/api/v1/repos", tags=["repos"])

# Gitea's permission vocabulary, mapped from ours. Ours is the one users see.
_ROLE_TO_GITEA = {
    GrantRole.owner: "admin",
    GrantRole.maintainer: "admin",
    GrantRole.writer: "write",
    GrantRole.reader: "read",
}

_RESERVED_SLUGS = {
    "api", "admin", "login", "logout", "signup", "settings", "explore",
    "new", "user", "org", "repo", "assets", "static", "help", "about",
}


# --------------------------------------------------------------------------
# schemas
# --------------------------------------------------------------------------
class CreateRepo(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    display_name: str | None = None
    description: str = ""
    # I-7 — required, never defaulted at read time, never inferred.
    repo_type: RepoType
    visibility: Visibility = Visibility.private

    @field_validator("name")
    @classmethod
    def _slug(cls, v: str) -> str:
        slug = "".join(c if (c.isalnum() or c in "-_") else "-" for c in v.strip().lower())
        slug = "-".join(filter(None, slug.split("-")))
        if not slug:
            raise ValueError("name must contain at least one letter or number")
        if slug in _RESERVED_SLUGS:
            raise ValueError(f"'{slug}' is reserved")
        return slug


class CreateGrant(BaseModel):
    role: GrantRole
    identity_id: str | None = None
    passport: str | None = None

    @field_validator("passport")
    @classmethod
    def _one_of(cls, v: str | None, info) -> str | None:
        if bool(info.data.get("identity_id")) == bool(v):
            # Mirrors the database CHECK constraint. Both layers, deliberately:
            # this ecosystem already has an invariant enforced only in
            # application code across two files, and a double-mint to show for it.
            raise ValueError("give exactly one of identity_id or passport")
        return v


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _sessionmaker(request: Request) -> async_sessionmaker[AsyncSession]:
    maker = getattr(request.app.state, "sessionmaker", None)
    if maker is None:
        raise RepairPointer(
            status_code=503,
            code="database_unavailable",
            speak="We can't reach your projects right now. Nothing has been lost.",
            machine_cause="no database sessionmaker on app.state",
            remediation_tool=None,
        )
    return maker


def _repo_owner_login(repo: Repo) -> str:
    """The owning login for a repo as STORED, not as inferred from the caller.

    Deriving this from the caller works only while the caller is the owner, and
    silently addresses the wrong namespace the moment a collaborator calls. That
    class of bug reads as "not found" and is very hard to see.
    """
    if repo.passport:
        return f"agent-{repo.passport.lower().replace('-', '')}"
    return f"u-{repo.identity_id[:24]}"


def _owner_login(caller: Caller) -> str:
    """One namespace rule for humans and agents alike (I-6)."""
    if caller.actor_type == ActorType.agent and caller.passport:
        return f"agent-{caller.passport.lower().replace('-', '')}"
    return f"u-{(caller.identity_id or 'unknown')[:24]}"


async def _load_repo(session: AsyncSession, repo_id: uuid.UUID, caller: Caller) -> Repo:
    repo = (await session.execute(select(Repo).where(Repo.id == repo_id))).scalar_one_or_none()
    if repo is None or repo.state == RepoState.deleted_soft:
        raise RepairPointer(
            status_code=404,
            code="project_not_found",
            speak="We couldn't find that project.",
            machine_cause=f"repo {repo_id} not found or soft-deleted",
            remediation_tool=None,
        )
    if not await _may_read(session, repo, caller):
        # 404, not 403: a stranger should not learn that a private project exists.
        raise RepairPointer(
            status_code=404,
            code="project_not_found",
            speak="We couldn't find that project.",
            machine_cause=f"caller {caller.subject} has no grant on repo {repo_id}",
            remediation_tool=None,
        )
    return repo


async def _may_read(session: AsyncSession, repo: Repo, caller: Caller) -> bool:
    if caller.actor_type == ActorType.system:
        return True
    if repo.visibility == Visibility.public:
        return True
    if caller.identity_id and repo.identity_id == caller.identity_id:
        return True
    if caller.passport and repo.passport == caller.passport:
        return True
    return await _active_grant(session, repo, caller) is not None


async def _active_grant(session: AsyncSession, repo: Repo, caller: Caller) -> RepoGrant | None:
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            select(RepoGrant).where(
                RepoGrant.repo_id == repo.id, RepoGrant.revoked_at.is_(None)
            )
        )
    ).scalars()
    for g in rows:
        if g.expires_at is not None and g.expires_at <= now:
            continue  # expired grants are not grants
        if caller.identity_id and g.grantee_identity_id == caller.identity_id:
            return g
        if caller.passport and g.grantee_passport == caller.passport:
            return g
    return None


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------
@router.post("", status_code=201)
async def create_repo(
    body: CreateRepo,
    request: Request,
    caller: Annotated[Caller, Depends(get_caller)],
) -> dict:
    settings = request.app.state.settings
    if body.repo_type.value not in settings.repo_types_enabled:
        raise RepairPointer(
            status_code=409,
            code="repo_type_not_enabled",
            speak="That kind of project isn't available yet.",
            machine_cause=(
                f"repo_type={body.repo_type.value} is not in "
                f"repo_types_enabled={list(settings.repo_types_enabled)}"
            ),
            remediation_tool=None,
        )

    # Throttle before any side effect. Checking after would let a rate-limited
    # agent still create the Gitea repo and only then be told no.
    async with _sessionmaker(request)() as session:
        await throttle.enforce(session, settings, caller, "repo.create")

    gitea = GiteaClient(settings)
    owner = _owner_login(caller)
    await gitea.ensure_user(owner, f"{owner}@windygit.com")
    created = await gitea.create_repo(
        owner=owner,
        name=body.name,
        description=body.description,
        private=body.visibility != Visibility.public,
        default_branch="main",
    )

    async with _sessionmaker(request)() as session:
        repo = Repo(
            identity_id=caller.identity_id or f"passport:{caller.passport}",
            passport=caller.passport,
            slug=body.name,
            display_name=body.display_name or body.name,
            repo_type=body.repo_type,
            gitea_repo_id=created.get("id"),
            visibility=body.visibility,
            default_branch="main",
            created_via=(
                CreatedVia.agent if caller.actor_type == ActorType.agent else CreatedVia.portal
            ),
        )
        session.add(repo)
        await session.flush()
        await throttle.record(session, caller, "repo.create", repo_id=repo.id)
        await session.commit()
        await session.refresh(repo)

    return {
        "id": str(repo.id),
        "name": repo.slug,
        "repo_type": repo.repo_type.value,
        "visibility": repo.visibility.value,
        "clone_url": created.get("clone_url"),
        "speak": f"'{repo.display_name}' is ready. Everything you save is kept.",
        "state_proof": {"gitea_repo_id": repo.gitea_repo_id, "owner": owner},
        "next_actions": ["windy_git.grant_access", "windy_git.list_versions"],
    }


@router.get("")
async def list_repos(request: Request, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    async with _sessionmaker(request)() as session:
        rows = (
            await session.execute(
                select(Repo).where(Repo.state != RepoState.deleted_soft)
            )
        ).scalars().all()
        mine = [r for r in rows if await _may_read(session, r, caller)]
    return {
        "repos": [
            {
                "id": str(r.id),
                "name": r.slug,
                "display_name": r.display_name,
                "repo_type": r.repo_type.value,
                "visibility": r.visibility.value,
            }
            for r in mine
        ],
        "count": len(mine),
    }


@router.get("/{repo_id}/versions")
async def list_versions(
    repo_id: uuid.UUID,
    request: Request,
    caller: Annotated[Caller, Depends(get_caller)],
) -> dict:
    """G5.5 — history in words a person recognises.

    Note what is absent from every user-facing string below: 'commit', 'branch',
    'repository'. A person restoring last Tuesday's work should not have to learn
    a vocabulary first (I-9, D-9).
    """
    async with _sessionmaker(request)() as session:
        repo = await _load_repo(session, repo_id, caller)
        # Derive the namespace from the REPO, never from the caller: the
        # caller-derived form is right only while the caller is the owner, and
        # addresses the wrong namespace the moment a collaborator asks. It then
        # surfaces as "not found", which is about the hardest bug to see.
        owner, slug, display = _repo_owner_login(repo), repo.slug, repo.display_name

    gitea = GiteaClient(request.app.state.settings)
    commits = await gitea.list_commits(owner, slug)

    versions = [
        {
            "version": len(commits) - i,
            "id": c.get("sha"),
            "saved_at": (c.get("commit") or {}).get("author", {}).get("date"),
            "note": ((c.get("commit") or {}).get("message") or "").strip().split("\n")[0],
            "saved_by": (c.get("commit") or {}).get("author", {}).get("name"),
        }
        for i, c in enumerate(commits)
    ]
    return {
        "versions": versions,
        "count": len(versions),
        # "There are 1 saved versions" is the kind of sloppiness the vocabulary
        # law exists to catch. Copy is design material, not decoration (I-9).
        "speak": (
            f"'{display}' has 1 saved version. You can go back to it."
            if len(versions) == 1
            else f"'{display}' has {len(versions)} saved versions. "
            "You can go back to any of them."
            if versions
            else f"'{display}' is empty so far."
        ),
    }


@router.post("/{repo_id}/grants", status_code=201)
async def create_grant(
    repo_id: uuid.UUID,
    body: CreateGrant,
    request: Request,
    caller: Annotated[Caller, Depends(get_caller)],
) -> dict:
    """G5.3 — the thing Windy Cloud cannot do at all today.

    A grant may name a human OR an agent passport, and agent grants expire by
    default (env: 90 days). A permanent agent credential is a standing liability
    nobody consciously chose.
    """
    settings = request.app.state.settings
    async with _sessionmaker(request)() as session:
        await throttle.enforce(session, settings, caller, "grant.create")
        repo = await _load_repo(session, repo_id, caller)
        is_owner = (caller.identity_id and repo.identity_id == caller.identity_id) or (
            caller.passport and repo.passport == caller.passport
        )
        if not is_owner and caller.actor_type != ActorType.system:
            raise RepairPointer(
                status_code=403,
                code="not_your_project",
                speak="Only the owner can share this project.",
                machine_cause=f"{caller.subject} is not the owner of {repo_id}",
                remediation_tool=None,
            )

        expires = (
            datetime.now(UTC) + timedelta(days=settings.agent_grant_default_days)
            if body.passport
            else None
        )
        grant = RepoGrant(
            repo_id=repo.id,
            grantee_identity_id=body.identity_id,
            grantee_passport=body.passport,
            role=body.role,
            granted_by=caller.subject,
            expires_at=expires,
        )
        session.add(grant)
        await session.flush()
        await throttle.record(session, caller, "grant.create", repo_id=repo.id)
        await session.commit()
        await session.refresh(grant)
        grant_id, role = grant.id, grant.role

    who = body.identity_id or body.passport
    return {
        "id": str(grant_id),
        "role": role.value,
        "grantee": who,
        "expires_at": expires.isoformat() if expires else None,
        "speak": (
            f"They can now help with '{repo.display_name}'."
            + (" Access ends automatically in 90 days." if expires else "")
        ),
        "next_actions": ["windy_git.list_grants", "windy_git.revoke_access"],
    }


@router.get("/{repo_id}/grants")
async def list_grants(
    repo_id: uuid.UUID,
    request: Request,
    caller: Annotated[Caller, Depends(get_caller)],
) -> dict:
    now = datetime.now(UTC)
    async with _sessionmaker(request)() as session:
        repo = await _load_repo(session, repo_id, caller)
        rows = (
            await session.execute(select(RepoGrant).where(RepoGrant.repo_id == repo.id))
        ).scalars().all()
    return {
        "grants": [
            {
                "id": str(g.id),
                "grantee": g.grantee_identity_id or g.grantee_passport,
                "kind": "person" if g.grantee_identity_id else "helper",
                "role": g.role.value,
                "expires_at": g.expires_at.isoformat() if g.expires_at else None,
                "active": g.revoked_at is None
                and (g.expires_at is None or g.expires_at > now),
            }
            for g in rows
        ]
    }


@router.delete("/{repo_id}/grants/{grant_id}")
async def revoke_grant(
    repo_id: uuid.UUID,
    grant_id: uuid.UUID,
    request: Request,
    caller: Annotated[Caller, Depends(get_caller)],
) -> dict:
    async with _sessionmaker(request)() as session:
        repo = await _load_repo(session, repo_id, caller)
        grant = (
            await session.execute(select(RepoGrant).where(RepoGrant.id == grant_id))
        ).scalar_one_or_none()
        if grant is None or grant.repo_id != repo.id:
            raise RepairPointer(
                status_code=404,
                code="grant_not_found",
                speak="We couldn't find that access to remove.",
                machine_cause=f"grant {grant_id} not on repo {repo_id}",
                remediation_tool=None,
            )
        grant.revoked_at = datetime.now(UTC)
        await session.commit()
    return {"revoked": True, "speak": "That access has been removed."}


@router.get("/{repo_id}")
async def get_repo(
    repo_id: uuid.UUID,
    request: Request,
    caller: Annotated[Caller, Depends(get_caller)],
) -> dict:
    async with _sessionmaker(request)() as session:
        repo = await _load_repo(session, repo_id, caller)
        versions = (
            await session.execute(select(RepoVersion).where(RepoVersion.repo_id == repo.id))
        ).scalars().all()
    return {
        "id": str(repo.id),
        "name": repo.slug,
        "display_name": repo.display_name,
        "repo_type": repo.repo_type.value,
        "visibility": repo.visibility.value,
        "cloud_folder_ref": repo.cloud_folder_ref,
        "recorded_versions": len(versions),
        "state": repo.state.value,
    }


# --------------------------------------------------------------------------
# I-4 / G11 — the off-site copy
# --------------------------------------------------------------------------
@router.post("/{repo_id}/mirror", status_code=201)
async def enable_mirror(
    repo_id: uuid.UUID,
    request: Request,
    caller: Annotated[Caller, Depends(get_caller)],
) -> dict:
    """Turn on the continuous off-site copy.

    Deliberately idempotent and deliberately loud on failure: a mirror that
    quietly stopped working is worse than no mirror, because it is a backup you
    believe in.
    """
    settings = request.app.state.settings
    async with _sessionmaker(request)() as session:
        repo = await _load_repo(session, repo_id, caller)
        owner = _repo_owner_login(repo)
        display, slug = repo.display_name, repo.slug
        private = repo.visibility != Visibility.public

    mirror = MirrorService(settings)
    remote = await mirror.ensure_github_repo(slug, display, private)
    await mirror.attach_push_mirror(owner, slug, remote)

    async with _sessionmaker(request)() as session:
        session.add(
            Mirror(repo_id=repo_id, remote_url=remote, direction="push", state=MirrorState.healthy)
        )
        await session.commit()

    return {
        "remote": remote,
        "sync_on_commit": True,
        "speak": "A second copy of this project is now kept somewhere else, automatically.",
        "state_proof": {"remote": remote},
        "next_actions": ["windy_git.mirror_status"],
    }


@router.get("/{repo_id}/mirror")
async def mirror_status(
    repo_id: uuid.UUID,
    request: Request,
    caller: Annotated[Caller, Depends(get_caller)],
) -> dict:
    async with _sessionmaker(request)() as session:
        repo = await _load_repo(session, repo_id, caller)
        owner, slug = _repo_owner_login(repo), repo.slug

    status = await MirrorService(request.app.state.settings).status(owner, slug)
    speak = {
        "healthy": "A second copy of this project is up to date.",
        "degraded": "The second copy is behind. Your work here is safe.",
        "absent": "There is no second copy of this project yet.",
        "pending": "The second copy is set up and hasn't run yet.",
        "unconfigured": "Off-site copies aren't switched on yet.",
        "unknown": "We can't tell how the second copy is doing right now.",
    }[status["state"]]
    return {**status, "speak": speak}
