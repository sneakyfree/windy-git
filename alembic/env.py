"""Alembic environment. Truth is this repo's migrations, not a hand-kept .sql file.

A sibling service names `postgres-schema.sql` as its source of truth in two
documents; that file omits the identity spine and ten tables, so a fresh deploy
from it produces a server that cannot register a user. Prod works only because
prod was built from migrations. We keep one source and it is `alembic/versions/`.
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from api.app.models.core import SCHEMA, Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    url = os.environ.get("DATABASE_URL", "postgresql://windygit:windygit@localhost:5432/windygit")
    return url.replace("+asyncpg", "")


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True,
                      include_schemas=True, version_table_schema=SCHEMA)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    config.set_main_option("sqlalchemy.url", _url())
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}),
                                     prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        connection.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata,
                          include_schemas=True, version_table_schema=SCHEMA)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
