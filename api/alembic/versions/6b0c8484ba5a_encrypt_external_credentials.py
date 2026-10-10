"""encrypt external_credentials.credential_data at rest

Revision ID: 6b0c8484ba5a
Revises: c3f1a8e92d47
Create Date: 2026-10-10 12:00:00.000000

Data-only: the column stays JSON; encrypted rows hold a
{"_enc": "v1", "ct": "<Fernet token>"} envelope (see
api/utils/credential_crypto.py). The envelope format below is a frozen copy so
the migration never imports application code.

upgrade:   with CREDENTIALS_ENCRYPTION_KEYS set, seal every plaintext row with
           the first key; envelopes are left as they are (idempotent). Without
           keys it is a no-op: the app keeps storing plaintext and the rows can
           be encrypted later with `python -m scripts.reencrypt_credentials`.
downgrade: decrypt every envelope back to plaintext (any configured key may
           open it). Refuses, changing nothing, if envelopes exist and cannot
           be decrypted, since the previous code cannot read them.
"""

import json
import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

revision: str = "6b0c8484ba5a"
down_revision: str | None = "c3f1a8e92d47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENVELOPE_MARKER = "_enc"
ENVELOPE_VERSION = "v1"
CIPHERTEXT = "ct"
BATCH_SIZE = 500

_raw = sa.table(
    "external_credentials",
    sa.column("id", sa.Integer),
    sa.column("credential_data", sa.JSON),
)


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


def _batches(connection: sa.engine.Connection):
    last_id = 0
    while True:
        rows = connection.execute(
            sa.select(_raw.c.id, _raw.c.credential_data)
            .where(_raw.c.id > last_id)
            .order_by(_raw.c.id)
            .limit(BATCH_SIZE)
        ).all()
        if not rows:
            return
        last_id = rows[-1][0]
        yield [(row_id, _load(data)) for row_id, data in rows]


def _write(connection: sa.engine.Connection, row_id: int, value: dict) -> None:
    connection.execute(
        sa.update(_raw).where(_raw.c.id == row_id).values(credential_data=value)
    )


def upgrade() -> None:
    fernet = _fernet()
    if fernet is None:
        return
    connection = op.get_bind()
    for batch in _batches(connection):
        for row_id, data in batch:
            if _is_envelope(data):
                continue
            plaintext = data if isinstance(data, dict) else {}
            token = fernet.encrypt(
                json.dumps(plaintext, separators=(",", ":"), sort_keys=True).encode()
            ).decode()
            _write(
                connection,
                row_id,
                {ENVELOPE_MARKER: ENVELOPE_VERSION, CIPHERTEXT: token},
            )


def downgrade() -> None:
    connection = op.get_bind()
    fernet = _fernet()
    undecryptable: list[int] = []
    for batch in _batches(connection):
        for row_id, data in batch:
            if not _is_envelope(data):
                continue
            if fernet is None or data[ENVELOPE_MARKER] != ENVELOPE_VERSION:
                undecryptable.append(row_id)
                continue
            try:
                plaintext = json.loads(fernet.decrypt(data[CIPHERTEXT].encode()))
            except InvalidToken:
                undecryptable.append(row_id)
                continue
            _write(connection, row_id, plaintext)
    if undecryptable:
        # Raising aborts the migration transaction, undoing the writes above.
        raise RuntimeError(
            f"{len(undecryptable)} external_credentials rows are encrypted and "
            "cannot be decrypted with CREDENTIALS_ENCRYPTION_KEYS; set the keys "
            "that wrote them before downgrading."
        )
