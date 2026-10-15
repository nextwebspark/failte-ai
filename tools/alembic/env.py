"""Alembic environment for fallcha-tools.

Only the ``fallcha_tools`` schema is ever inspected or changed; the version
table lives there too, so this never touches ``public`` (owned by the
Fallcha API's own migrations).
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Literal

from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from fallcha_tools.config import DatabaseSettings, normalize_database_url
from fallcha_tools.core.models import SCHEMA, Base
from fallcha_tools.providers.website_catalogue import models as _catalogue  # noqa: F401

config = context.config
if config.config_file_name is not None and config.attributes.get(
    "configure_logger", True
):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    explicit = config.get_main_option("sqlalchemy.url")
    if explicit:
        return normalize_database_url(explicit)
    return DatabaseSettings().database_url  # type: ignore[call-arg]


def _include_name(
    name: str | None,
    type_: Literal[
        "schema",
        "table",
        "column",
        "index",
        "unique_constraint",
        "foreign_key_constraint",
    ],
    parent_names: object,
) -> bool:
    if type_ == "schema":
        return name == SCHEMA
    return True


def _configure(connection: Connection | None = None, url: str | None = None) -> None:
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        version_table_schema=SCHEMA,
        include_schemas=True,
        include_name=_include_name,
        compare_type=True,
        literal_binds=connection is None,
    )


def run_migrations_offline() -> None:
    _configure(url=_database_url())
    with context.begin_transaction():
        context.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        context.run_migrations()


# Arbitrary constant ("ftools") identifying this service's migration lock.
_MIGRATION_LOCK_ID = 0x66746F6F6C73


def _run_sync(connection: Connection) -> None:
    # Replicas starting together would race on the same migrations; the
    # transaction-scoped lock serializes them and releases on commit.
    connection.execute(text(f"SELECT pg_advisory_xact_lock({_MIGRATION_LOCK_ID})"))
    # The version table lives in our schema, so it must exist first.
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    engine = async_engine_from_config(section, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync)
        await connection.commit()
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
