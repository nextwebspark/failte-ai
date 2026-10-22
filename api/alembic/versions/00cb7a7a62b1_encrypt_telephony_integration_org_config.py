"""encrypt telephony, integration and organization configuration secrets at rest

Revision ID: 00cb7a7a62b1
Revises: b7c3e9a41d20
Create Date: 2026-10-20 12:00:00.000000

Data-only: the columns stay JSON; encrypted rows hold the same
{"_enc": "v1", "ct": "<Fernet token>"} envelope as
external_credentials.credential_data (see api/utils/credential_crypto.py and
6b0c8484ba5a). The envelope format below is a frozen copy so the migration
never imports application code. Columns:

    telephony_configurations.credentials
    integrations.connection_details
    organization_configurations.value

upgrade:   with CREDENTIALS_ENCRYPTION_KEYS set, seal every plaintext row with
           the first key; envelopes are left as they are (idempotent). Without
           keys it is a no-op (local development; production refuses to start
           without keys) and rows can be encrypted later with
           `python -m scripts.reencrypt_credentials`. Rows that are neither
           objects nor null are left untouched and their ids logged; null
           becomes an encrypted {}.
downgrade: decrypt every envelope back to plaintext (any configured key may
           open it). Refuses, changing nothing, if envelopes exist and cannot
           be decrypted, since the previous code cannot read them.
offline:   (`alembic upgrade --sql`) cannot encrypt: with keys set it refuses
           and points at `python -m scripts.reencrypt_credentials`; without
           keys it emits nothing.
Rows are read in id-ordered batches locked FOR UPDATE.
"""

import json
import logging
import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

revision: str = "00cb7a7a62b1"
down_revision: str | None = "b7c3e9a41d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENVELOPE_MARKER = "_enc"
ENVELOPE_VERSION = "v1"
CIPHERTEXT = "ct"
BATCH_SIZE = 500

COLUMNS: tuple[tuple[str, str], ...] = (
    ("telephony_configurations", "credentials"),
    ("integrations", "connection_details"),
    ("organization_configurations", "value"),
)

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
