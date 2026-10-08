"""Add organization invitations.

Revision ID: b0a08a90d2a6
Revises: 88d4ad1e2e4d
"""

import sqlalchemy as sa
from alembic import op

revision = "b0a08a90d2a6"
down_revision = "88d4ad1e2e4d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "organization_invitations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column(
            "invited_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "accepted_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('admin', 'developer', 'viewer')",
            name="ck_organization_invitations_role",
        ),
    )
    op.create_index(
        "uq_organization_invitations_open_email",
        "organization_invitations",
        ["organization_id", "email"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
    )
    op.create_index(
        "ix_organization_invitations_email", "organization_invitations", ["email"]
    )


def downgrade():
    op.drop_index(
        "ix_organization_invitations_email", table_name="organization_invitations"
    )
    op.drop_index(
        "uq_organization_invitations_open_email",
        table_name="organization_invitations",
    )
    op.drop_table("organization_invitations")
