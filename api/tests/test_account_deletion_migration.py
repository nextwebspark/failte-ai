"""The 04b6af5b14b4 migration (account and organisation deletion) both ways.

Runs inside the test transaction, so the schema changes roll back with it.
"""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "04b6af5b14b4_account_and_organization_deletion.py"
)
_spec = importlib.util.spec_from_file_location("account_deletion_mig", _MIGRATION_PATH)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


async def _run(db_connection, monkeypatch, step: str) -> None:
    def run(sync_connection):
        operations = Operations(MigrationContext.configure(sync_connection))
        monkeypatch.setattr(migration, "op", operations)
        getattr(migration, step)()

    await db_connection.run_sync(run)


async def _fk(async_session, name: str) -> tuple[str, bool]:
    """(on-delete action, column NOT NULL) of a foreign key."""
    row = (
        await async_session.execute(
            text(
                "SELECT c.confdeltype::text, a.attnotnull FROM pg_constraint c "
                "JOIN pg_attribute a ON a.attrelid = c.conrelid "
                "AND a.attnum = c.conkey[1] WHERE c.conname = :name"
            ),
            {"name": name},
        )
    ).one()
    return row[0], row[1]


async def _has_column(async_session, table: str, column: str) -> bool:
    return bool(
        await async_session.scalar(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c"
            ),
            {"t": table, "c": column},
        )
    )


async def test_downgrade_and_upgrade(
    db_session, async_session, db_connection, monkeypatch
):
    # The test database is at head.
    assert await _fk(async_session, "embed_tokens_created_by_fkey") == ("n", False)
    assert await _fk(async_session, "campaigns_created_by_fkey") == ("n", False)
    assert await _fk(async_session, "organization_users_user_id_fkey") == ("c", True)
    assert await _has_column(async_session, "organizations", "deletion_scheduled_for")

    await _run(db_connection, monkeypatch, "downgrade")
    assert await _fk(async_session, "embed_tokens_created_by_fkey") == ("c", True)
    assert await _fk(async_session, "campaigns_created_by_fkey") == ("a", True)
    assert await _fk(async_session, "workflows_user_id_fkey") == ("a", False)
    assert await _fk(async_session, "organization_users_user_id_fkey") == ("a", True)
    assert not await _has_column(async_session, "organizations", "erased_at")

    await _run(db_connection, monkeypatch, "upgrade")
    assert await _fk(async_session, "embed_tokens_created_by_fkey") == ("n", False)
    assert await _fk(async_session, "tools_created_by_fkey") == ("n", False)
    assert await _fk(async_session, "user_configurations_user_id_fkey") == ("c", False)
    assert await _has_column(async_session, "organizations", "erased_provider_id")


async def test_downgrade_refuses_rows_whose_creator_was_deleted(
    db_session, async_session, db_connection, monkeypatch
):
    org_id = await async_session.scalar(
        text(
            "INSERT INTO organizations (provider_id, name) "
            "VALUES ('mig-org', 'Mig') RETURNING id"
        )
    )
    await async_session.execute(
        text(
            "INSERT INTO tools (tool_uuid, organization_id, name, category, status, "
            "definition) VALUES (gen_random_uuid()::text, :org, 'Orphan', "
            "'http_api', 'active', '{}') "
        ),
        {"org": org_id},
    )
    await async_session.flush()

    with pytest.raises(RuntimeError, match="tools.created_by"):
        await _run(db_connection, monkeypatch, "downgrade")
