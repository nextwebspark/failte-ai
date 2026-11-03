"""saas_add workflow template category

Revision ID: a8f3c2e19b47
Revises: 04b6af5b14b4
Create Date: 2026-10-31 01:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a8f3c2e19b47"
down_revision: Union[str, None] = "04b6af5b14b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflow_templates",
        sa.Column("category", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_templates", "category")
