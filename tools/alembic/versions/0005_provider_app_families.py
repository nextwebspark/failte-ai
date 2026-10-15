"""provider apps belong to an auth family

OAuth clients are stored under the provider's auth family (e.g. "google"),
so one client serves every provider of the family.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-10 12:00:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = 'fallcha_tools'
GOOGLE_PROVIDERS = ('google-calendar', 'google-sheets')


def upgrade() -> None:
    op.execute(
        f"UPDATE {SCHEMA}.provider_apps SET provider = 'google'"
        f" WHERE provider IN {GOOGLE_PROVIDERS!r}"
    )


def downgrade() -> None:
    # Before families every client belonged to one provider; Calendar was the
    # only Google provider with OAuth then.
    op.execute(
        f"UPDATE {SCHEMA}.provider_apps SET provider = 'google-calendar'"
        " WHERE provider = 'google'"
    )
