from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from tests.conftest import TEST_DATABASE_URL, alembic_config

TABLES = {"provider_apps", "connections", "connection_keys", "oauth_states"}


async def _tables(schema: str) -> set[str]:
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables"
                    " WHERE table_schema = :schema"
                ),
                {"schema": schema},
            )
            return {row[0] for row in rows}
    finally:
        await engine.dispose()


def test_upgrade_and_downgrade_stay_in_own_schema() -> None:
    public_before = asyncio.run(_tables("public"))
    cfg = alembic_config()

    command.downgrade(cfg, "base")
    assert asyncio.run(_tables("fallcha_tools")) == {"alembic_version"}

    command.upgrade(cfg, "head")
    assert asyncio.run(_tables("fallcha_tools")) == TABLES | {"alembic_version"}

    assert asyncio.run(_tables("public")) == public_before
