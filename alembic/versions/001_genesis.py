"""001 genesis — the complete section 4 data model.

I-7: this migration creates `repo_type` NOT NULL and creates `model_cards`, even
though `repo_type=model` does not ship until v2. Shipping v1 with the v2 columns
absent is forbidden.

Every migration in this repo has a tested downgrade (G0.4). The sibling ecosystem
has a documented schema file that omits its own identity spine and ten tables; a
fresh deploy from it produces a server that cannot register a user. That happens
when migrations and documentation drift. Here the migration IS the truth.

Revision ID: 001_genesis
Revises:
Create Date: 2026-08-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "001_genesis"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = "windgit"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    bind = op.get_bind()

    # Create each type ONCE, explicitly, then reference it with create_type=False.
    #
    # Without create_type=False, `op.create_table` asks the Enum to emit its own
    # CREATE TYPE with no checkfirst, so the second reference to an already-created
    # type raises DuplicateObject and the migration dies halfway through. This bug
    # is invisible to review and to any test that does not run against real
    # Postgres -- it surfaced here only because `alembic upgrade head` was actually
    # executed. Every migration in this repo gets run before it gets committed.
    _DEFS = {
        "repo_type": ("code", "model", "dataset"),
        "visibility": ("private", "unlisted", "public"),
        "repo_state": ("active", "archived", "deleted-soft"),
        "created_via": ("portal", "agent", "import", "cloud-folder"),
        "grant_role": ("owner", "maintainer", "writer", "reader"),
        "mirror_health": ("healthy", "degraded", "failed"),
    }
    for name, labels in _DEFS.items():
        postgresql.ENUM(*labels, name=name, schema=SCHEMA).create(bind, checkfirst=True)

    def _ref(name: str) -> postgresql.ENUM:
        return postgresql.ENUM(*_DEFS[name], name=name, schema=SCHEMA, create_type=False)

    repo_type = _ref("repo_type")
    visibility = _ref("visibility")
    repo_state = _ref("repo_state")
    created_via = _ref("created_via")
    grant_role = _ref("grant_role")
    mirror_health = _ref("mirror_health")

    op.create_table(
        "repos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("identity_id", sa.String(64), nullable=False),
        sa.Column("passport", sa.String(32)),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        # I-7 — NOT NULL, from migration 001, forever.
        sa.Column("repo_type", repo_type, nullable=False),
        sa.Column("gitea_repo_id", sa.Integer),
        sa.Column("visibility", visibility, nullable=False, server_default="private"),
        sa.Column("cloud_folder_ref", sa.String(255)),
        sa.Column("default_branch", sa.String(128), server_default="main"),
        sa.Column("lfs_bytes", sa.BigInteger, server_default="0"),
        sa.Column("object_bytes", sa.BigInteger, server_default="0"),
        sa.Column("state", repo_state, server_default="active"),
        sa.Column("created_via", created_via, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("identity_id", "slug", name="uq_repos_identity_slug"),
        schema=SCHEMA,
    )
    op.create_index("ix_repos_repo_type", "repos", ["repo_type"], schema=SCHEMA)
    op.create_index("ix_repos_passport", "repos", ["passport"], schema=SCHEMA)

    op.create_table(
        "repo_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repo_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.repos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("grantee_identity_id", sa.String(64)),
        sa.Column("grantee_passport", sa.String(32)),
        sa.Column("role", grant_role, nullable=False),
        sa.Column("granted_by", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("confirm_ref", sa.String(128)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        # The invariant lives in the database, not in application code.
        sa.CheckConstraint(
            "(grantee_identity_id IS NULL) <> (grantee_passport IS NULL)",
            name="ck_grant_exactly_one_grantee",
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_grants_repo", "repo_grants", ["repo_id"], schema=SCHEMA)

    op.create_table(
        "repo_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repo_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.repos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("commit_sha", sa.String(64), nullable=False),
        sa.Column("tree_sha", sa.String(64)),
        sa.Column("author_identity_id", sa.String(64)),
        sa.Column("author_passport", sa.String(32)),
        sa.Column("signed", sa.Boolean, server_default=sa.false()),
        sa.Column("signature_verified", sa.Boolean, server_default=sa.false()),
        sa.Column("ei_at_action", sa.String(32)),
        sa.Column("message", sa.Text),
        sa.Column("bytes_added", sa.BigInteger, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("repo_id", "seq", name="uq_version_repo_seq"),
        schema=SCHEMA,
    )
    op.create_index("ix_versions_commit", "repo_versions", ["commit_sha"], schema=SCHEMA)

    op.create_table(
        "mirror_state",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repo_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.repos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("remote_url", sa.String(512), nullable=False),
        sa.Column("direction", sa.String(16), server_default="push"),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text),
        sa.Column("lag_seconds", sa.Integer),
        sa.Column("state", mirror_health, server_default="healthy"),
        schema=SCHEMA,
    )

    op.create_table(
        "agent_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("passport", sa.String(32), nullable=False),
        sa.Column("repo_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.repos.id", ondelete="CASCADE")),
        sa.Column("scopes", postgresql.ARRAY(sa.String(64)), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_reason", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("ix_agent_tokens_passport", "agent_tokens", ["passport"], schema=SCHEMA)

    op.create_table(
        "agent_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("passport", sa.String(32), nullable=False),
        sa.Column("repo_id", postgresql.UUID(as_uuid=True)),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("ei_at_action", sa.String(32)),
        sa.Column("confirm_ref", sa.String(128)),
        sa.Column("result", sa.String(32), nullable=False),
        sa.Column("cost_microcents", sa.BigInteger, server_default="0"),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("ix_agent_actions_passport_ts", "agent_actions", ["passport", "ts"], schema=SCHEMA)

    # v2 surface, v1 schema. I-7.
    op.create_table(
        "model_cards",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repo_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.repos.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("base_model", sa.String(255)),
        sa.Column("license", sa.String(64)),
        sa.Column("pipeline_tag", sa.String(64)),
        sa.Column("tags", postgresql.ARRAY(sa.String(64))),
        sa.Column("library", sa.String(64)),
        sa.Column("card_yaml", postgresql.JSONB),
        sa.Column("card_body", sa.Text),
        schema=SCHEMA,
    )

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("state", sa.String(32), server_default="pending"),
        sa.Column("attempts", sa.Integer, server_default="0"),
        sa.Column("last_error", sa.Text),
        sa.Column("run_after", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema=SCHEMA,
    )

    op.create_table(
        "webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("delivered", sa.Boolean, server_default=sa.false()),
        sa.Column("attempts", sa.Integer, server_default="0"),
        sa.Column("last_error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema=SCHEMA,
    )


def downgrade() -> None:
    for table in (
        "webhook_events", "jobs", "model_cards", "agent_actions",
        "agent_tokens", "mirror_state", "repo_versions", "repo_grants", "repos",
    ):
        op.drop_table(table, schema=SCHEMA)

    bind = op.get_bind()
    for name in ("mirror_health", "grant_role", "created_via", "repo_state", "visibility", "repo_type"):
        postgresql.ENUM(name=name, schema=SCHEMA).drop(bind, checkfirst=True)

    # Deliberately NOT dropping the schema. `alembic_version` lives inside
    # `windgit` (env.py sets version_table_schema), so a DROP SCHEMA CASCADE here
    # deletes alembic's own bookkeeping table out from under the migration that
    # is still running, and the final DELETE FROM alembic_version fails. The
    # schema is cheap to leave; the tables and types are what this reverses.
