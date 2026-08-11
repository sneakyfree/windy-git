"""Data model, section 4 of the DNA plan.

I-7 is enforced here structurally: `repo_type` is NOT NULL from migration 001,
and `model_cards` exists in v1 even though `repo_type=model` does not ship until
v2. Shipping v1 with the v2 columns absent is forbidden — cheap now,
near-impossible to retrofit.

Postgres is truth. Gitea's own database is a component's private state and this
service never writes to it directly (I-1).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "windgit"


class Base(DeclarativeBase):
    pass


class RepoType(enum.StrEnum):
    """I-7 / D-6. A Hugging Face repo IS a git repo with LFS and a model card —
    the consolidation is metadata and UI, not infrastructure."""

    code = "code"
    model = "model"
    dataset = "dataset"


class Visibility(enum.StrEnum):
    private = "private"
    unlisted = "unlisted"
    public = "public"


class RepoState(enum.StrEnum):
    active = "active"
    archived = "archived"
    deleted_soft = "deleted-soft"


class CreatedVia(enum.StrEnum):
    portal = "portal"
    agent = "agent"
    imported = "import"
    cloud_folder = "cloud-folder"


class GrantRole(enum.StrEnum):
    owner = "owner"
    maintainer = "maintainer"
    writer = "writer"
    reader = "reader"


class MirrorState(enum.StrEnum):
    healthy = "healthy"
    degraded = "degraded"
    failed = "failed"



def _pg_enum(enum_cls, name: str):
    """SQLAlchemy's Enum persists `.name` by default, not `.value`.

    Three members here have a name that differs from its value
    (`deleted_soft`/"deleted-soft", `imported`/"import", `cloud_folder`/
    "cloud-folder"), so the default would write a label migration 001 does not
    declare and the insert would fail at runtime, not at review. Pin values
    explicitly.
    """
    return Enum(
        enum_cls,
        name=name,
        schema=SCHEMA,
        values_callable=lambda cls: [member.value for member in cls],
    )


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Repo(Base):
    __tablename__ = "repos"
    __table_args__ = (
        UniqueConstraint("identity_id", "slug", name="uq_repos_identity_slug"),
        Index("ix_repos_repo_type", "repo_type"),
        Index("ix_repos_passport", "passport"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = _pk()
    identity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Agent-owned repos. An agent is a citizen here, not a guest on a human's row.
    passport: Mapped[str | None] = mapped_column(String(32))
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # I-7: first-class, NOT NULL, never inferred, never defaulted at read time.
    repo_type: Mapped[RepoType] = mapped_column(
        _pg_enum(RepoType, "repo_type"), nullable=False
    )

    gitea_repo_id: Mapped[int | None] = mapped_column(Integer)
    visibility: Mapped[Visibility] = mapped_column(
        _pg_enum(Visibility, "visibility"),
        nullable=False,
        default=Visibility.private,
    )
    # D-8: set when this repo was git-enabled from a Windy Cloud folder. The
    # user's files stay first-class Cloud objects; we never take custody (I-13).
    cloud_folder_ref: Mapped[str | None] = mapped_column(String(255))
    default_branch: Mapped[str] = mapped_column(String(128), default="main")
    lfs_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    object_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    state: Mapped[RepoState] = mapped_column(
        _pg_enum(RepoState, "repo_state"), default=RepoState.active
    )
    created_via: Mapped[CreatedVia] = mapped_column(
        _pg_enum(CreatedVia, "created_via"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RepoGrant(Base):
    """The shelter (D-8/G5.3). Windy Cloud has no sharing of any kind today —
    verified 2026-08-11 against routes/storage.py and its models."""

    __tablename__ = "repo_grants"
    __table_args__ = (
        # Exactly one grantee. Enforced by the database, not by application code,
        # because application-enforced invariants are how this ecosystem got a
        # double-mint and a unique constraint living in two files.
        CheckConstraint(
            "(grantee_identity_id IS NULL) <> (grantee_passport IS NULL)",
            name="ck_grant_exactly_one_grantee",
        ),
        Index("ix_grants_repo", "repo_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = _pk()
    repo_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.repos.id", ondelete="CASCADE"), nullable=False
    )
    grantee_identity_id: Mapped[str | None] = mapped_column(String(64))
    grantee_passport: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[GrantRole] = mapped_column(
        _pg_enum(GrantRole, "grant_role"), nullable=False
    )
    granted_by: Mapped[str] = mapped_column(String(64), nullable=False)
    # Agent grants expire by default (env: 90 days). A permanent agent credential
    # is a standing liability nobody chose.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirm_ref: Mapped[str | None] = mapped_column(String(128))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RepoVersion(Base):
    """Our own view of history, independent of Gitea (I-1)."""

    __tablename__ = "repo_versions"
    __table_args__ = (
        UniqueConstraint("repo_id", "seq", name="uq_version_repo_seq"),
        Index("ix_versions_commit", "commit_sha"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = _pk()
    repo_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.repos.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    tree_sha: Mapped[str | None] = mapped_column(String(64))
    author_identity_id: Mapped[str | None] = mapped_column(String(64))
    author_passport: Mapped[str | None] = mapped_column(String(32))
    signed: Mapped[bool] = mapped_column(Boolean, default=False)
    signature_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    # G9.1: frozen at push time, NEVER recomputed. A band is a statement about
    # what was known then, not a live lookup.
    ei_at_action: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str | None] = mapped_column(Text)
    bytes_added: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Mirror(Base):
    """I-4: never a one-way door. This table is what the alerting reads."""

    __tablename__ = "mirror_state"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = _pk()
    repo_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.repos.id", ondelete="CASCADE"), nullable=False
    )
    remote_url: Mapped[str] = mapped_column(String(512), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), default="push")
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    lag_seconds: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[MirrorState] = mapped_column(
        _pg_enum(MirrorState, "mirror_health"), default=MirrorState.healthy
    )


class AgentToken(Base):
    """G6.3. Never a human's PAT wearing an agent's name — that is the entire
    GitHub grievance and the reason this product exists."""

    __tablename__ = "agent_tokens"
    __table_args__ = (
        Index("ix_agent_tokens_passport", "passport"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = _pk()
    passport: Mapped[str] = mapped_column(String(32), nullable=False)
    repo_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.repos.id", ondelete="CASCADE")
    )
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False)
    # We store a hash. Never the token.
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentAction(Base):
    __tablename__ = "agent_actions"
    __table_args__ = (
        Index("ix_agent_actions_passport_ts", "passport", "ts"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = _pk()
    passport: Mapped[str] = mapped_column(String(32), nullable=False)
    repo_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    ei_at_action: Mapped[str | None] = mapped_column(String(32))
    confirm_ref: Mapped[str | None] = mapped_column(String(128))
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    # G3.7: actually populated. windy-chat emits nothing here and contributes $0
    # to the cost dashboard despite real spend.
    cost_microcents: Mapped[int] = mapped_column(BigInteger, default=0)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelCard(Base):
    """v2 surface, v1 schema (I-7). Populated from README.md YAML frontmatter."""

    __tablename__ = "model_cards"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = _pk()
    repo_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.repos.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    base_model: Mapped[str | None] = mapped_column(String(255))
    license: Mapped[str | None] = mapped_column(String(64))
    pipeline_tag: Mapped[str | None] = mapped_column(String(64))
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String(64)))
    library: Mapped[str | None] = mapped_column(String(64))
    card_yaml: Mapped[dict | None] = mapped_column(JSONB)
    card_body: Mapped[str | None] = mapped_column(Text)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = _pk()
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    run_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = _pk()
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
