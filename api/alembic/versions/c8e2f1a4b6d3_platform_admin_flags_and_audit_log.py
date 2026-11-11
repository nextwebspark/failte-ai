"""platform admin: feature switches and audit log

Revision ID: c8e2f1a4b6d3
Revises: c4e8f1a2b3d6
Create Date: 2026-11-06 09:00:00.000000

See api/db/platform_admin_models.py:

    platform_feature_flags     runtime switches for product areas (Campaigns,
                               Skills): one platform-wide row per feature
                               (organization_id NULL) plus optional
                               per-organisation overrides
    platform_admin_audit_log   who changed what, and when, in the platform
                               admin area (ids only, no personal data)

Both start empty: with no rows every feature keeps its default in code, so
nothing changes for anyone until a platform admin flips a switch.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8e2f1a4b6d3"
down_revision: str | None = "c4e8f1a2b3d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_feature_flags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("feature", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_platform_feature_flags_platform",
        "platform_feature_flags",
        ["feature"],
        unique=True,
        postgresql_where=sa.text("organization_id IS NULL"),
    )
    op.create_index(
        "uq_platform_feature_flags_organization",
        "platform_feature_flags",
        ["feature", "organization_id"],
        unique=True,
        postgresql_where=sa.text("organization_id IS NOT NULL"),
    )

    op.create_table(
        "platform_admin_audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("target_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "details",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_platform_admin_audit_log_created_at",
        "platform_admin_audit_log",
        ["created_at"],
    )
    op.create_index(
        "ix_platform_admin_audit_log_organization_id",
        "platform_admin_audit_log",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_platform_admin_audit_log_organization_id",
        table_name="platform_admin_audit_log",
    )
    op.drop_index(
        "ix_platform_admin_audit_log_created_at",
        table_name="platform_admin_audit_log",
    )
    op.drop_table("platform_admin_audit_log")
    op.drop_index(
        "uq_platform_feature_flags_organization",
        table_name="platform_feature_flags",
    )
    op.drop_index(
        "uq_platform_feature_flags_platform", table_name="platform_feature_flags"
    )
    op.drop_table("platform_feature_flags")
