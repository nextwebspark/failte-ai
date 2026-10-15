"""drop retired calendar order keys; sync note

Order lookup moved from Google Calendar to Google Sheets: strip its keys
from calendar connections' config (the config model forbids unknown keys).
Also add connection_syncs.note.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-10 14:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = 'fallcha_tools'


def upgrade() -> None:
    op.execute(
        f"UPDATE {SCHEMA}.connections"
        " SET config = config - 'orders_sheet_id' - 'orders_tab'"
        " WHERE provider = 'google-calendar'"
        " AND (config ? 'orders_sheet_id' OR config ? 'orders_tab')"
    )
    op.add_column(
        'connection_syncs', sa.Column('note', sa.Text(), nullable=True), schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_column('connection_syncs', 'note', schema=SCHEMA)
    # The removed keys are not restored: their settings now live on Google
    # Sheets connections.
