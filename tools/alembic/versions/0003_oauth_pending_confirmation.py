"""oauth: pending connections, browser nonce, error codes

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-10 09:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = 'fallcha_tools'
STATUS_CK = 'ck_connections_connection_status'


def upgrade() -> None:
    op.drop_constraint(op.f(STATUS_CK), 'connections', schema=SCHEMA, type_='check')
    op.create_check_constraint(
        op.f(STATUS_CK),
        'connections',
        "status IN ('pending', 'active', 'error', 'revoked')",
        schema=SCHEMA,
    )
    op.add_column(
        'connections',
        sa.Column(
            'error_code',
            sa.Enum(
                'grant_revoked',
                'client_rejected',
                'client_missing',
                name='connection_error_code',
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        schema=SCHEMA,
    )
    op.add_column(
        'connections',
        sa.Column('pending_user_id', sa.BigInteger(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        'connections',
        sa.Column('pending_nonce_hash', sa.String(length=64), nullable=True),
        schema=SCHEMA,
    )
    # States live 10 minutes; any in flight predate the browser binding.
    op.execute(f'DELETE FROM {SCHEMA}.oauth_states')
    op.add_column(
        'oauth_states',
        sa.Column('browser_nonce_hash', sa.String(length=64), nullable=False),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column('oauth_states', 'browser_nonce_hash', schema=SCHEMA)
    op.drop_column('connections', 'pending_nonce_hash', schema=SCHEMA)
    op.drop_column('connections', 'pending_user_id', schema=SCHEMA)
    op.drop_column('connections', 'error_code', schema=SCHEMA)
    # Pending connections cannot exist under the old constraint.
    op.execute(
        f"UPDATE {SCHEMA}.connections SET status = 'revoked',"
        " secret_enc = NULL, access_token_enc = NULL WHERE status = 'pending'"
    )
    op.drop_constraint(op.f(STATUS_CK), 'connections', schema=SCHEMA, type_='check')
    op.create_check_constraint(
        op.f(STATUS_CK),
        'connections',
        "status IN ('active', 'error', 'revoked')",
        schema=SCHEMA,
    )
