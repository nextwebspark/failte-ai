"""Bulk (re-)encryption of every ``EncryptedJSON`` column, and the startup
canary lookup.

Used by ``scripts/reencrypt_credentials.py`` after a key is added or to encrypt
rows written before encryption was enabled. Works on the raw stored JSON (not
through ``EncryptedJSON``): envelopes are rotated opaquely with
``MultiFernet.rotate`` and plaintext rows are sealed, so nothing is decrypted
into a Python dict except legacy plaintext that is already in the clear.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import JsonValue
from sqlalchemy import JSON, Integer, cast, column, select, table, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, async_sessionmaker

from api.utils.credential_crypto import (
    CredentialCipher,
    CredentialDecryptionError,
    is_envelope,
)

# Every column stored through ``EncryptedJSON`` (api/db/models.py), as
# (table, column). Keep in step with the models and with the alembic
# migrations that encrypt them in place.
ENCRYPTED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("external_credentials", "credential_data"),
    ("telephony_configurations", "credentials"),
    ("integrations", "connection_details"),
    ("organization_configurations", "value"),
    ("user_configurations", "configuration"),
)


def _raw_table(table_name: str, column_name: str):
    """Raw view of the table: plain JSON, bypassing EncryptedJSON's
    transparent decryption."""
    return table(table_name, column("id", Integer), column(column_name, JSON))


@dataclass(frozen=True, slots=True)
class ReencryptionReport:
    scanned: int = 0
    encrypted: int = 0  # plaintext rows sealed
    rotated: int = 0  # envelopes re-encrypted under the primary key
    # (table, id) of envelopes no configured key opens, or of non-object rows
    failed: tuple[tuple[str, int], ...] = ()


# Rows carrying the envelope marker; ``is_envelope`` then checks the exact shape.
_SAMPLE_CANDIDATES = 20


class CredentialEncryptionClient:
    """Maintenance and startup access; not part of the runtime ``DBClient``."""

    def __init__(self, bind: AsyncEngine | AsyncConnection) -> None:
        # Bound to a connection (tests), each batch commit is a savepoint of
        # the caller's transaction.
        self._sessions = async_sessionmaker(
            bind=bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )

    async def sample_envelope(self) -> dict[str, str] | None:
        """Any one stored encrypted envelope, or ``None`` if there is none."""
        async with self._sessions() as session:
            for table_name, column_name in ENCRYPTED_COLUMNS:
                data = _raw_table(table_name, column_name).c[column_name]
                values = (
                    await session.scalars(
                        select(data)
                        .where(cast(data, JSONB).has_key("_enc"))
                        .limit(_SAMPLE_CANDIDATES)
                    )
                ).all()
                for value in values:
                    if is_envelope(value):
                        assert isinstance(value, dict)
                        return value
        return None

    async def reencrypt_all(
        self,
        cipher: CredentialCipher,
        *,
        batch_size: int = 200,
        dry_run: bool = False,
    ) -> ReencryptionReport:
        """Seal every plaintext row and rotate every envelope to the primary
        key in every encrypted column, in id-ordered batches committed one at
        a time. Idempotent and safe to re-run after an interruption."""
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        scanned = encrypted = rotated = 0
        failed: list[tuple[str, int]] = []
        for table_name, column_name in ENCRYPTED_COLUMNS:
            raw = _raw_table(table_name, column_name)
            data = raw.c[column_name]
            last_id = 0
            while True:
                async with self._sessions() as session:
                    rows = (
                        await session.execute(
                            select(raw.c.id, data)
                            .where(raw.c.id > last_id)
                            .order_by(raw.c.id)
                            .limit(batch_size)
                            .with_for_update()
                        )
                    ).all()
                    if not rows:
                        break
                    for row_id, stored in rows:
                        scanned += 1
                        last_id = row_id
                        new_value = _reencrypted(cipher, stored)
                        if new_value is None:
                            failed.append((table_name, row_id))
                            continue
                        if is_envelope(stored):
                            rotated += 1
                        else:
                            encrypted += 1
                        if not dry_run:
                            await session.execute(
                                update(raw)
                                .where(raw.c.id == row_id)
                                .values({column_name: new_value})
                            )
                    if dry_run:
                        await session.rollback()
                    else:
                        await session.commit()
        return ReencryptionReport(
            scanned=scanned,
            encrypted=encrypted,
            rotated=rotated,
            failed=tuple(failed),
        )


def _reencrypted(cipher: CredentialCipher, stored: object) -> dict[str, str] | None:
    if is_envelope(stored):
        assert isinstance(stored, dict)
        try:
            return cipher.rotate(stored)
        except CredentialDecryptionError:
            return None
    if isinstance(stored, dict):
        plaintext: dict[str, JsonValue] = stored
        return cipher.seal(plaintext)
    if stored is None:
        return cipher.seal({})
    return None
