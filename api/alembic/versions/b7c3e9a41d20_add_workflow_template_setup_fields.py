"""add workflow template setup fields and card details

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
    op.add_column(
        "workflow_templates", sa.Column("call_type", sa.String(), nullable=True)
    )
    op.add_column("workflow_templates", sa.Column("icon", sa.String(), nullable=True))
    op.add_column(
        "workflow_templates",
        sa.Column("featured", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "workflow_templates", sa.Column("sample_audio_url", sa.String(), nullable=True)
    )
    op.add_column(
        "workflow_templates",
        sa.Column("integrations", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    for column in (
        "integrations",
        "sample_audio_url",
        "featured",
        "icon",
        "call_type",
        "setup_fields",
    ):
        op.drop_column("workflow_templates", column)
