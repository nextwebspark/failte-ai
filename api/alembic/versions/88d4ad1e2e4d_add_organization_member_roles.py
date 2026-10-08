"""Add organization member roles, organization name and user name.

Existing memberships are backfilled as ``admin`` so no current user loses
access when role enforcement is switched on.

Revision ID: 88d4ad1e2e4d
Revises: 3a7b91c5d402
"""

import sqlalchemy as sa
from alembic import op

revision = "88d4ad1e2e4d"
down_revision = "3a7b91c5d402"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "organization_users",
        sa.Column("role", sa.String(length=32), nullable=False, server_default="admin"),
    )
    # The backfill default is only for pre-existing rows; new rows set the
    # role explicitly.
    op.alter_column("organization_users", "role", server_default=None)
    op.create_check_constraint(
        "ck_organization_users_role",
        "organization_users",
        "role IN ('admin', 'developer', 'viewer')",
    )
    op.add_column(
        "organization_users",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "organization_users",
        sa.Column("invited_by", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_organization_users_invited_by_users",
        "organization_users",
        "users",
        ["invited_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_organization_users_organization_id_role",
        "organization_users",
        ["organization_id", "role"],
    )

    op.add_column("organizations", sa.Column("name", sa.String(), nullable=True))
    op.add_column("users", sa.Column("name", sa.String(), nullable=True))


def downgrade():
    op.drop_column("users", "name")
    op.drop_column("organizations", "name")
    op.drop_index(
        "ix_organization_users_organization_id_role",
        table_name="organization_users",
    )
    op.drop_constraint(
        "fk_organization_users_invited_by_users",
        "organization_users",
        type_="foreignkey",
    )
    op.drop_column("organization_users", "invited_by")
    op.drop_column("organization_users", "created_at")
    op.drop_constraint(
        "ck_organization_users_role", "organization_users", type_="check"
    )
    op.drop_column("organization_users", "role")
