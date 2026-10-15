from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from tests.conftest import TEST_DATABASE_URL, alembic_config

TABLES = {
    "provider_apps",
    "connections",
    "connection_keys",
    "oauth_states",
    "connection_syncs",
    "catalogue_products",
}


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


def test_calendar_configs_lose_retired_order_keys() -> None:
    import uuid

    async def run(sql: str) -> list[object]:
        engine = create_async_engine(TEST_DATABASE_URL)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(sql))
                return list(result.scalars().all()) if result.returns_rows else []
        finally:
            await engine.dispose()

    cfg = alembic_config()
    command.downgrade(cfg, "0005")
    try:
        cal, sheet = uuid.uuid4(), uuid.uuid4()
        asyncio.run(
            run(
                "INSERT INTO fallcha_tools.connections (id, org_id, provider,"
                " auth_mode, config) VALUES"
                f" ('{cal}', 1, 'google-calendar', 'service_account',"
                ' \'{"calendar_id": "c", "orders_sheet_id": "s", "orders_tab": "O"}\'),'
                f" ('{sheet}', 1, 'google-sheets', 'service_account',"
                ' \'{"spreadsheet_id": "x", "orders_tab": "O"}\')'
            )
        )
        command.upgrade(cfg, "head")
        configs = asyncio.run(
            run("SELECT config FROM fallcha_tools.connections ORDER BY provider")
        )
        assert configs == [
            {"calendar_id": "c"},
            {"spreadsheet_id": "x", "orders_tab": "O"},
        ]
    finally:
        command.upgrade(cfg, "head")
        asyncio.run(run("DELETE FROM fallcha_tools.connections"))
