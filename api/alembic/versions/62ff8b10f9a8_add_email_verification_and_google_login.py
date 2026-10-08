"""Add email verification, Google login identity and single-use user tokens.

Every existing user is marked verified so turning verification on does not
lock anyone out.

Revision ID: 62ff8b10f9a8
Revises: b0a08a90d2a6
"""

import sqlalchemy as sa
from alembic import op

revision = "62ff8b10f9a8"
down_revision = "b0a08a90d2a6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("users", sa.Column("google_sub", sa.String(), nullable=True))
    op.add_column("users", sa.Column("avatar_url", sa.String(), nullable=True))
    op.create_unique_constraint("uq_users_google_sub", "users", ["google_sub"])
    op.execute(
        "UPDATE users SET email_verified_at = COALESCE(created_at, now()) "
        "WHERE email_verified_at IS NULL"
    )

    op.create_table(
        "user_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_user_tokens_user_id", "user_tokens", ["user_id"])


def downgrade():
    op.drop_index("ix_user_tokens_user_id", table_name="user_tokens")
    op.drop_table("user_tokens")
    op.drop_constraint("uq_users_google_sub", "users", type_="unique")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "google_sub")
    op.drop_column("users", "email_verified_at")
