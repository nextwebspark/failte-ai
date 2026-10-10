"""Bulk (re-)encryption of ``external_credentials.credential_data``.

Used by ``scripts/reencrypt_credentials.py`` after a key is added or to encrypt
rows written before encryption was enabled. Works on the raw stored JSON (not
through ``EncryptedJSON``): envelopes are rotated opaquely with
``MultiFernet.rotate`` and plaintext rows are sealed, so nothing is decrypted
into a Python dict except legacy plaintext that is already in the clear.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import JsonValue
from sqlalchemy import JSON, Integer, column, select, table, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, async_sessionmaker

from api.utils.credential_crypto import (
    CredentialCipher,
    CredentialDecryptionError,
    is_envelope,
)

# Raw view of the table: plain JSON, bypassing EncryptedJSON's transparent
# decryption.
_raw_credentials = table(
    "external_credentials",
    column("id", Integer),
    column("credential_data", JSON),
)


@dataclass(frozen=True, slots=True)
class ReencryptionReport:
    scanned: int = 0
    encrypted: int = 0  # plaintext rows sealed
    rotated: int = 0  # envelopes re-encrypted under the primary key
    failed_ids: tuple[int, ...] = ()  # envelopes no configured key opens


class CredentialEncryptionClient:
    """Maintenance-only access; not part of the runtime ``DBClient``."""

    def __init__(self, bind: AsyncEngine | AsyncConnection) -> None:
        # Bound to a connection (tests), each batch commit is a savepoint of
        # the caller's transaction.
        self._sessions = async_sessionmaker(
            bind=bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )

    async def reencrypt_all(
        self,
        cipher: CredentialCipher,
        *,
        batch_size: int = 200,
        dry_run: bool = False,
    ) -> ReencryptionReport:
        """Seal every plaintext row and rotate every envelope to the primary
        key, in id-ordered batches committed one at a time. Idempotent and
        safe to re-run after an interruption."""
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        scanned = encrypted = rotated = 0
        failed: list[int] = []
        last_id = 0
        while True:
            async with self._sessions() as session:
                rows = (
                    await session.execute(
                        select(
                            _raw_credentials.c.id, _raw_credentials.c.credential_data
                        )
                        .where(_raw_credentials.c.id > last_id)
                        .order_by(_raw_credentials.c.id)
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
                        failed.append(row_id)
                        continue
                    if is_envelope(stored):
                        rotated += 1
                    else:
                        encrypted += 1
                    if not dry_run:
                        await session.execute(
                            update(_raw_credentials)
                            .where(_raw_credentials.c.id == row_id)
                            .values(credential_data=new_value)
                        )
                if dry_run:
                    await session.rollback()
                else:
                    await session.commit()
        return ReencryptionReport(
            scanned=scanned,
            encrypted=encrypted,
            rotated=rotated,
            failed_ids=tuple(failed),
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
