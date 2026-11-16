"""platform settings: platform-wide values a platform admin sets

Revision ID: d6b3e8f2a9c4
Revises: c8e2f1a4b6d3
Create Date: 2026-11-13 16:00:00.000000

See api/db/platform_admin_models.py:

    platform_settings   one JSON value per key, set in the platform admin
                        area. The first is ``home_layout``: the Home cards a
                        workspace without a default of its own starts with.

Starts empty: with no row every key keeps its default in code, so nothing
changes for anyone until a platform admin saves a value.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d6b3e8f2a9c4"
down_revision: str | None = "c8e2f1a4b6d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("platform_settings")
