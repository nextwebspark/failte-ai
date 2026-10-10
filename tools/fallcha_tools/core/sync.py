"""Background syncs for providers that import data (see ``SyncableProvider``).

A sync runs as an asyncio task in the process that accepted the request.
One sync per connection, across replicas: the task holds a session-level
Postgres advisory lock on a dedicated database connection for its whole
run (released when it ends, or when the process dies and its connection
closes). Progress is recorded in ``connection_syncs``; a RUNNING row whose
heartbeat is older than :data:`STALE_AFTER` is reported as interrupted.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from fallcha_tools.core.context import ContextLoader
from fallcha_tools.core.db import Database
from fallcha_tools.core.errors import ConflictError, InvalidRequestError
from fallcha_tools.core.models import ConnectionStatus, ConnectionSync, SyncStatus
from fallcha_tools.core.provider import (
    ConnectionContext,
    ProviderRegistry,
    SyncableProvider,
    SyncFailed,
)
from fallcha_tools.core.repositories import ConnectionRepository

Clock = Callable[[], datetime]

STALE_AFTER = timedelta(minutes=5)
HEARTBEAT_EVERY = timedelta(seconds=20)
MAX_CONCURRENT_SYNCS = 4
INTERRUPTED = "the sync was interrupted; start it again"
UNEXPECTED = "the sync failed unexpectedly"


def utc_now() -> datetime:
    return datetime.now(UTC)


def sync_lock_id(connection_id: uuid.UUID) -> int:
    """The signed 64-bit advisory-lock id for syncing one connection."""
    digest = hashlib.sha256(b"fallcha_tools.sync:" + connection_id.bytes).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


class SyncConflictError(ConflictError):
    pass


@dataclass(frozen=True, slots=True)
class SyncInfo:
    status: SyncStatus
    started_at: datetime
    finished_at: datetime | None
    last_synced_at: datetime | None
    item_count: int
    last_error: str | None
    note: str | None


def _info(row: ConnectionSync, now: datetime) -> SyncInfo:
    status, error = row.status, row.last_error
    if status == SyncStatus.RUNNING and now - row.heartbeat_at > STALE_AFTER:
        status, error = SyncStatus.FAILED, INTERRUPTED
    return SyncInfo(
        status=status,
        started_at=row.started_at,
        finished_at=row.finished_at,
        last_synced_at=row.last_synced_at,
        item_count=row.item_count,
        last_error=error,
        note=row.note if status == SyncStatus.SUCCEEDED else None,
    )


class SyncRepository:
    """``connection_syncs`` rows; every method is scoped by ``org_id``."""

    def __init__(self, session: AsyncSession, clock: Clock = utc_now) -> None:
        self._session = session
        self._clock = clock

    async def get_many(
        self, org_id: int, connection_ids: Iterable[uuid.UUID]
    ) -> dict[uuid.UUID, SyncInfo]:
        ids = list(connection_ids)
        if not ids:
            return {}
        rows = await self._session.scalars(
            select(ConnectionSync).where(
                ConnectionSync.org_id == org_id,
                ConnectionSync.connection_id.in_(ids),
            )
        )
        now = self._clock()
        return {row.connection_id: _info(row, now) for row in rows}

    async def mark_running(
        self, org_id: int, connection_id: uuid.UUID, requested_by: int | None
    ) -> SyncInfo:
        now = self._clock()
        values = {
            "status": SyncStatus.RUNNING,
            "started_at": now,
            "heartbeat_at": now,
            "finished_at": None,
            "last_error": None,
            "note": None,
            "requested_by": requested_by,
        }
        statement = (
            insert(ConnectionSync)
            .values(connection_id=connection_id, org_id=org_id, **values)
            .on_conflict_do_update(
                index_elements=[ConnectionSync.connection_id],
                set_=values,
                where=ConnectionSync.org_id == org_id,
            )
            .returning(ConnectionSync)
        )
        row = (await self._session.scalars(statement)).one()
        await self._session.commit()
        return _info(row, now)

    async def heartbeat(
        self,
        org_id: int,
        connection_id: uuid.UUID,
        item_count: int,
        *,
        at: datetime | None = None,
    ) -> None:
        row = await self._row(org_id, connection_id)
        if row is not None:
            row.heartbeat_at = at or self._clock()
            row.item_count = item_count
            await self._session.commit()

    async def finish(
        self,
        org_id: int,
        connection_id: uuid.UUID,
        *,
        item_count: int | None,
        error: str | None,
        note: str | None = None,
    ) -> None:
        row = await self._row(org_id, connection_id)
        if row is None:
            return
        now = self._clock()
        row.status = SyncStatus.FAILED if error else SyncStatus.SUCCEEDED
        row.finished_at = now
        row.heartbeat_at = now
        row.last_error = error
        row.note = None if error else note
        if error is None:
            row.last_synced_at = now
        if item_count is not None:
            row.item_count = item_count
        await self._session.commit()

    async def _row(
        self, org_id: int, connection_id: uuid.UUID
    ) -> ConnectionSync | None:
        row: ConnectionSync | None = await self._session.scalar(
            select(ConnectionSync)
            .where(
                ConnectionSync.org_id == org_id,
                ConnectionSync.connection_id == connection_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return row


@dataclass(slots=True)
class _Progress:
    """Writes a heartbeat at most every :data:`HEARTBEAT_EVERY`."""

    runner: SyncRunner
    org_id: int
    connection_id: uuid.UUID
    last: datetime
    # Set when the sync ends: nothing is written after the final status.
    closed: bool = False

    async def heartbeat(self, items: int) -> None:
        if self.closed:
            return
        now = self.runner.clock()
        if now - self.last < HEARTBEAT_EVERY:
            return
        self.last = now
        async with self.runner.db.session() as session:
            await SyncRepository(session, self.runner.clock).heartbeat(
                self.org_id, self.connection_id, items, at=now
            )


@dataclass
class SyncRunner:
    db: Database
    contexts: ContextLoader
    registry: ProviderRegistry
    clock: Clock = utc_now
    max_concurrent: int = MAX_CONCURRENT_SYNCS
    _tasks: dict[uuid.UUID, asyncio.Task[None]] = field(default_factory=dict)

    async def start(
        self, org_id: int, user_id: int | None, connection_id: uuid.UUID
    ) -> SyncInfo:
        """Start a background sync; 409 if one is running for the connection
        (in any replica) or this process is busy with others."""
        async with self.db.session() as session:
            info = await ConnectionRepository(
                session, self.contexts.box
            ).get_connection(org_id, connection_id)
        provider = self.registry.get(info.provider)
        if not isinstance(provider, SyncableProvider):
            raise InvalidRequestError(
                f"provider {provider.id!r} does not support syncing"
            )
        if info.status != ConnectionStatus.ACTIVE:
            raise SyncConflictError("only an active connection can be synced")
        if connection_id in self._tasks:
            raise SyncConflictError("a sync is already running for this connection")
        if len(self._tasks) >= self.max_concurrent:
            raise SyncConflictError(
                "too many syncs are running right now; try again in a few minutes"
            )
        ctx = await self.contexts.load(org_id, connection_id, provider.id)
        lock = await self._try_lock(connection_id)
        if lock is None:
            raise SyncConflictError("a sync is already running for this connection")
        try:
            async with self.db.session() as session:
                started = await SyncRepository(session, self.clock).mark_running(
                    org_id, connection_id, user_id
                )
        except BaseException:
            await self._unlock(lock, connection_id)
            raise
        self._tasks[connection_id] = asyncio.create_task(
            self._run(provider, ctx, lock),
            name=f"sync-{connection_id}",
        )
        logger.info("sync started for connection {} (org {})", connection_id, org_id)
        return started

    async def wait(self, connection_id: uuid.UUID) -> None:
        """Wait for the connection's running sync, if any (tests, shutdown)."""
        task = self._tasks.get(connection_id)
        if task is not None:
            await asyncio.wait([task])

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks)

    @property
    def running(self) -> int:
        return len(self._tasks)

    async def _run(
        self,
        provider: SyncableProvider,
        ctx: ConnectionContext,
        lock: AsyncConnection,
    ) -> None:
        org_id, connection_id = ctx.org_id, ctx.connection_id
        progress = _Progress(self, org_id, connection_id, self.clock())
        count: int | None = None
        error: str | None = None
        note: str | None = None
        try:
            result = await provider.run_sync(ctx, progress)
            count, error, note = result.item_count, None, result.note
            logger.info(
                "sync of connection {} finished with {} items",
                connection_id,
                result.item_count,
            )
        except SyncFailed as exc:
            error = str(exc)[:500] or UNEXPECTED
            logger.warning("sync of connection {} failed: {}", connection_id, error)
        except asyncio.CancelledError:
            error = INTERRUPTED
            raise
        except Exception as exc:
            # Type only: a message could carry upstream content.
            error = UNEXPECTED
            logger.error(
                "sync of connection {} raised {}", connection_id, type(exc).__name__
            )
        finally:
            progress.closed = True
            try:
                async with self.db.session() as session:
                    await SyncRepository(session, self.clock).finish(
                        org_id, connection_id, item_count=count, error=error, note=note
                    )
            except Exception as exc:
                logger.error(
                    "could not record the end of sync {}: {}",
                    connection_id,
                    type(exc).__name__,
                )
            await self._unlock(lock, connection_id)
            self._tasks.pop(connection_id, None)

    async def _try_lock(self, connection_id: uuid.UUID) -> AsyncConnection | None:
        conn = await self.db.engine.connect()
        try:
            got = await conn.scalar(
                select(func.pg_try_advisory_lock(sync_lock_id(connection_id)))
            )
            await conn.commit()  # the session-level lock outlives the transaction
        except BaseException:
            await conn.close()
            raise
        if not got:
            await conn.close()
            return None
        return conn

    async def _unlock(self, conn: AsyncConnection, connection_id: uuid.UUID) -> None:
        try:
            await conn.scalar(
                select(func.pg_advisory_unlock(sync_lock_id(connection_id)))
            )
            await conn.commit()
        except Exception as exc:
            # Discard the database connection rather than return it to the
            # pool still holding the lock; closing it releases the lock.
            logger.warning("sync unlock failed: {}", type(exc).__name__)
            await conn.invalidate()
        finally:
            await conn.close()
