from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import OrganizationConfigurationModel

# Lease states stored under an organization configuration key used as a lock.
LEASE_PENDING = "pending"
LEASE_COMPLETED = "completed"


class OrganizationConfigurationClient(BaseDBClient):
    async def get_configuration(
        self, organization_id: int, key: str
    ) -> Optional[OrganizationConfigurationModel]:
        """Get a specific configuration for an organization by key."""
        async with self.async_session() as session:
            result = await session.execute(
                select(OrganizationConfigurationModel).where(
                    OrganizationConfigurationModel.organization_id == organization_id,
                    OrganizationConfigurationModel.key == key,
                )
            )
            return result.scalars().first()

    async def get_all_configurations(
        self, organization_id: int
    ) -> list[OrganizationConfigurationModel]:
        """Get all configurations for an organization."""
        async with self.async_session() as session:
            result = await session.execute(
                select(OrganizationConfigurationModel).where(
                    OrganizationConfigurationModel.organization_id == organization_id
                )
            )
            return result.scalars().all()

    async def upsert_configuration(
        self,
        organization_id: int,
        key: str,
        value: Any,
        last_validated_at: datetime | None = None,
    ) -> OrganizationConfigurationModel:
        """Create or update a configuration for an organization."""
        async with self.async_session() as session:
            now = datetime.now(UTC)
            # First try to get existing configuration
            result = await session.execute(
                select(OrganizationConfigurationModel).where(
                    OrganizationConfigurationModel.organization_id == organization_id,
                    OrganizationConfigurationModel.key == key,
                )
            )
            config = result.scalars().first()

            if config:
                # Update existing configuration
                config.value = value
                config.updated_at = now
                config.last_validated_at = last_validated_at
            else:
                # Create new configuration
                config = OrganizationConfigurationModel(
                    organization_id=organization_id,
                    key=key,
                    value=value,
                    updated_at=now,
                    last_validated_at=last_validated_at,
                )
                session.add(config)

            try:
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise e
            await session.refresh(config)
            return config

    async def mark_configuration_validated(
        self, organization_id: int, key: str
    ) -> Optional[OrganizationConfigurationModel]:
        """Update the validation timestamp for an existing organization configuration."""
        async with self.async_session() as session:
            result = await session.execute(
                select(OrganizationConfigurationModel).where(
                    OrganizationConfigurationModel.organization_id == organization_id,
                    OrganizationConfigurationModel.key == key,
                )
            )
            config = result.scalars().first()
            if not config:
                return None

            config.last_validated_at = datetime.now(UTC)
            try:
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise e
            await session.refresh(config)
            return config

    async def claim_configuration_lease(
        self,
        organization_id: int,
        key: str,
        stale_after: timedelta,
    ) -> str | None:
        """Atomically take a single-winner lease over one organization config key.

        Returns a unique owner token for exactly one concurrent caller; every
        other caller gets ``None`` and must not perform the leased work. The
        lease survives process death: a holder that never reached
        ``complete``/``release`` leaves the row ``pending``, and a later caller
        takes it over once it is older than ``stale_after``. A ``completed``
        lease is terminal and never re-taken.
        """
        now = datetime.now(UTC)
        owner_token = str(uuid4())
        pending_value = {
            "status": LEASE_PENDING,
            "owner_token": owner_token,
        }
        async with self.async_session() as session:
            claim = (
                insert(OrganizationConfigurationModel.__table__)
                .values(
                    organization_id=organization_id,
                    key=key,
                    value=pending_value,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(constraint="_organization_key_uc")
            )
            try:
                result = await session.execute(claim)
                await session.commit()
            except Exception:
                await session.rollback()
                raise

            if result.rowcount > 0:
                return owner_token

            # A lease row already exists. Take it over only if the previous
            # holder died mid-work and left it pending past `stale_after`;
            # replacing the owner token fences the expired holder out of any
            # later completion/release, while updated_at re-starts the window.
            # ``value`` is encrypted at rest, so the state is checked in Python
            # under a row lock: a concurrent claimer blocks here and then sees
            # the fresh updated_at.
            lease = await self._lock_lease(session, organization_id, key)
            if (
                lease is None
                or not isinstance(lease.value, dict)
                or lease.value.get("status") != LEASE_PENDING
                or lease.updated_at is None
                or lease.updated_at >= now - stale_after
            ):
                return None  # closing the session releases the row lock
            lease.value = pending_value
            lease.updated_at = now
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            return owner_token

    async def complete_configuration_lease(
        self, organization_id: int, key: str, owner_token: str
    ) -> None:
        """Mark the caller's held lease terminal so the work is never repeated."""
        async with self.async_session() as session:
            lease = await self._lock_lease(session, organization_id, key)
            if not _holds_lease(lease, owner_token):
                return
            lease.value = {"status": LEASE_COMPLETED}
            lease.updated_at = datetime.now(UTC)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def release_configuration_lease(
        self, organization_id: int, key: str, owner_token: str
    ) -> None:
        """Drop the caller's held lease so the next caller retries at once."""
        async with self.async_session() as session:
            lease = await self._lock_lease(session, organization_id, key)
            if not _holds_lease(lease, owner_token):
                return
            await session.delete(lease)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    @staticmethod
    async def _lock_lease(
        session, organization_id: int, key: str
    ) -> OrganizationConfigurationModel | None:
        result = await session.execute(
            select(OrganizationConfigurationModel)
            .where(
                OrganizationConfigurationModel.organization_id == organization_id,
                OrganizationConfigurationModel.key == key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalars().first()

    async def delete_configuration(self, organization_id: int, key: str) -> bool:
        """Delete a configuration for an organization."""
        async with self.async_session() as session:
            result = await session.execute(
                select(OrganizationConfigurationModel).where(
                    OrganizationConfigurationModel.organization_id == organization_id,
                    OrganizationConfigurationModel.key == key,
                )
            )
            config = result.scalars().first()

            if not config:
                return False

            await session.delete(config)
            try:
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise e
            return True

    async def get_configuration_value(
        self, organization_id: int, key: str, default: Any = None
    ) -> Any:
        """Get the value of a configuration, returning default if not found."""
        config = await self.get_configuration(organization_id, key)
        return config.value if config else default

    async def get_all_configurations_by_key(self, key: str) -> list[dict[str, Any]]:
        """Get all organization configurations for a given key.

        Returns a list of dicts with organization_id and the config value.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(OrganizationConfigurationModel).where(
                    OrganizationConfigurationModel.key == key,
                )
            )
            return [
                {
                    "organization_id": config.organization_id,
                    "value": config.value,
                }
                for config in result.scalars().all()
                if config.value
            ]

    async def get_configurations_by_provider(
        self, key: str, provider: str
    ) -> List[Dict[str, Any]]:
        """Get all organization configurations for a given key filtered by provider.

        Returns a list of dicts with organization_id and the config value.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(OrganizationConfigurationModel).where(
                    OrganizationConfigurationModel.key == key,
                )
            )
            configs = result.scalars().all()

            return [
                {
                    "organization_id": config.organization_id,
                    "value": config.value,
                }
                for config in configs
                if isinstance(config.value, dict)
                and config.value.get("provider") == provider
            ]


def _holds_lease(
    lease: OrganizationConfigurationModel | None, owner_token: str
) -> bool:
    value = lease.value if lease is not None else None
    if not isinstance(value, dict):
        value = {}
    return (
        value.get("status") == LEASE_PENDING and value.get("owner_token") == owner_token
    )
