"""add workflow template setup fields

Revision ID: b7c3e9a41d20
Revises: ea7d85c1bebb
Create Date: 2026-10-19 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c3e9a41d20"
down_revision: Union[str, None] = "ea7d85c1bebb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflow_templates",
        sa.Column("setup_fields", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("workflow_templates", "setup_fields")
