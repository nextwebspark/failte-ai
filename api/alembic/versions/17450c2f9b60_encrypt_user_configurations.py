"""encrypt user configurations at rest

Revision ID: 17450c2f9b60
Revises: 00cb7a7a62b1
Create Date: 2026-10-21 09:00:00.000000

Data-only, the same as 00cb7a7a62b1 (read it for the full behaviour): the
column stays JSON and rows hold the {"_enc": "v1", "ct": "<Fernet token>"}
envelope. The legacy v1 MODEL_CONFIGURATION rows carry provider API keys.

    user_configurations.configuration

upgrade:   with CREDENTIALS_ENCRYPTION_KEYS set, seal every plaintext row;
           without keys it is a no-op. Envelopes are left alone.
downgrade: decrypt every envelope back to plaintext; refuses if any cannot be
           decrypted.
offline:   refuses with keys set, emits nothing without them.
"""

import json
import logging
import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

revision: str = "17450c2f9b60"
down_revision: str | None = "00cb7a7a62b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENVELOPE_MARKER = "_enc"
ENVELOPE_VERSION = "v1"
CIPHERTEXT = "ct"
BATCH_SIZE = 500

COLUMNS: tuple[tuple[str, str], ...] = (("user_configurations", "configuration"),)

log = logging.getLogger("alembic.runtime.migration")


def _offline() -> bool:
    return context.is_offline_mode()


def _fernet() -> MultiFernet | None:
    keys = [
        k.strip()
        for k in os.getenv("CREDENTIALS_ENCRYPTION_KEYS", "").split(",")
        if k.strip()
    ]
    if not keys:
        return None
    try:
        return MultiFernet([Fernet(k.encode()) for k in keys])
    except ValueError as exc:
        raise RuntimeError(
            "CREDENTIALS_ENCRYPTION_KEYS contains an invalid Fernet key"
        ) from exc


def _is_envelope(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {ENVELOPE_MARKER, CIPHERTEXT}
        and isinstance(value[ENVELOPE_MARKER], str)
        and isinstance(value[CIPHERTEXT], str)
    )


def _load(value: object) -> object:
    # Some drivers hand back JSON as text.
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _raw(table: str, column: str) -> sa.TableClause:
    return sa.table(table, sa.column("id", sa.Integer), sa.column(column, sa.JSON))


def _batches(connection: sa.engine.Connection, raw: sa.TableClause, column: str):
    last_id = 0
    while True:
        rows = connection.execute(
            sa.select(raw.c.id, raw.c[column])
            .where(raw.c.id > last_id)
            .order_by(raw.c.id)
            .limit(BATCH_SIZE)
            .with_for_update()
        ).all()
        if not rows:
            return
        last_id = rows[-1][0]
        yield [(row_id, _load(data)) for row_id, data in rows]


def _write(
    connection: sa.engine.Connection,
    raw: sa.TableClause,
    column: str,
    row_id: int,
    value: dict,
) -> None:
    connection.execute(sa.update(raw).where(raw.c.id == row_id).values({column: value}))


def _refuse_offline(fernet: MultiFernet | None, step: str) -> bool:
    """True when running offline (the caller must then do nothing)."""
    if not _offline():
        return False
    if fernet is not None:
        raise RuntimeError(
            f"{revision} cannot {step} secrets in offline (--sql) mode. Run it "
            "online, or apply the SQL without CREDENTIALS_ENCRYPTION_KEYS and "
            "then run `python -m scripts.reencrypt_credentials`."
        )
    log.info("%s: offline mode without keys; rows unchanged", revision)
    return True


def upgrade() -> None:
    fernet = _fernet()
    if _refuse_offline(fernet, "encrypt") or fernet is None:
        return
    connection = op.get_bind()
    for table, column in COLUMNS:
        raw = _raw(table, column)
        skipped: list[int] = []
        for batch in _batches(connection, raw, column):
            for row_id, data in batch:
                if _is_envelope(data):
                    continue
                if data is None:
                    data = {}
                if not isinstance(data, dict):
                    skipped.append(row_id)
                    continue
                token = fernet.encrypt(
                    json.dumps(data, separators=(",", ":"), sort_keys=True).encode()
                ).decode()
                _write(
                    connection,
                    raw,
                    column,
                    row_id,
                    {ENVELOPE_MARKER: ENVELOPE_VERSION, CIPHERTEXT: token},
                )
        if skipped:
            log.warning(
                "%s: left %d non-object %s rows unencrypted (ids: %s)",
                revision,
                len(skipped),
                table,
                ", ".join(map(str, skipped)),
            )


def downgrade() -> None:
    fernet = _fernet()
    if _refuse_offline(fernet, "decrypt"):
        return
    connection = op.get_bind()
    undecryptable: list[str] = []
    for table, column in COLUMNS:
        raw = _raw(table, column)
        for batch in _batches(connection, raw, column):
            for row_id, data in batch:
                if not _is_envelope(data):
                    continue
                if fernet is None or data[ENVELOPE_MARKER] != ENVELOPE_VERSION:
                    undecryptable.append(f"{table}#{row_id}")
                    continue
                try:
                    plaintext = json.loads(fernet.decrypt(data[CIPHERTEXT].encode()))
                except InvalidToken:
                    undecryptable.append(f"{table}#{row_id}")
                    continue
                _write(connection, raw, column, row_id, plaintext)
    if undecryptable:
        # Raising aborts the migration transaction, undoing the writes above.
        raise RuntimeError(
            f"{len(undecryptable)} rows are encrypted and cannot be decrypted "
            "with CREDENTIALS_ENCRYPTION_KEYS; set the keys that wrote them "
            "before downgrading."
        )
