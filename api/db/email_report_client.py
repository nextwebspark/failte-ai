"""Storage for emailed reports: two organization configuration rows per
workspace (``EMAIL_REPORTS`` settings, ``EMAIL_REPORTS_SENT`` bookkeeping).

``value`` is encrypted at rest, so nothing can be read inside it in SQL; every
change happens in Python under a row lock (``SELECT ... FOR UPDATE``), which
makes concurrent writers (two workers, a save racing a confirm link) queue
instead of overwriting each other.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from api.db.base_client import BaseDBClient
from api.db.models import OrganizationConfigurationModel, OrganizationModel

T = TypeVar("T")


class EmailReportClient(BaseDBClient):
    async def update_configuration_locked(
        self,
        organization_id: int,
        key: str,
        mutate: Callable[[dict[str, Any]], tuple[dict[str, Any] | None, T]],
    ) -> T:
        """Run ``mutate`` on the row's current value (``{}`` if none) while
        holding its row lock. ``mutate`` returns ``(new_value, result)``;
        a ``None`` new value leaves the row as it was. Returns ``result``."""
        now = datetime.now(UTC)
        async with self.async_session() as session:
            try:
                await session.execute(
                    insert(OrganizationConfigurationModel.__table__)
                    .values(
                        organization_id=organization_id,
                        key=key,
                        value={},
                        created_at=now,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing(constraint="_organization_key_uc")
                )
                row = (
                    await session.execute(
                        select(OrganizationConfigurationModel)
                        .where(
                            OrganizationConfigurationModel.organization_id
                            == organization_id,
                            OrganizationConfigurationModel.key == key,
                        )
                        .with_for_update()
                    )
                ).scalar_one()
                current = row.value if isinstance(row.value, dict) else {}
                new_value, result = mutate(dict(current))
                if new_value is not None:
                    row.value = new_value
                    row.updated_at = now
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise

    async def list_report_configurations(
        self, key: str
    ) -> list[tuple[int, str, dict[str, Any]]]:
        """``(organization_id, organization name, value)`` for every open
        workspace holding ``key``: not erased, and not asked to be deleted
        (deletion suspends everything that reaches out, emails included)."""
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    OrganizationConfigurationModel.organization_id,
                    OrganizationModel.name,
                    OrganizationConfigurationModel.value,
                )
                .join(
                    OrganizationModel,
                    OrganizationModel.id
                    == OrganizationConfigurationModel.organization_id,
                )
                .where(
                    OrganizationConfigurationModel.key == key,
                    OrganizationModel.erased_at.is_(None),
                    OrganizationModel.deletion_requested_at.is_(None),
                )
                .order_by(OrganizationConfigurationModel.organization_id)
            )
            return [
                (row.organization_id, row.name or "", row.value or {})
                for row in result.all()
            ]
