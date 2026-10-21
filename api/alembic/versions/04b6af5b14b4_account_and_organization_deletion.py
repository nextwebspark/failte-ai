"""account and organisation deletion (GDPR Art. 17)

Revision ID: 04b6af5b14b4
Revises: 17450c2f9b60
Create Date: 2026-10-21 12:00:00.000000

Organisation deletion is requested, then carried out by the erasure cron once
the grace period ends:

    organizations.deletion_requested_at   when an admin asked for deletion
    organizations.deletion_scheduled_for  when the erasure cron may erase it
    organizations.deletion_suspended      what the request switched off (API
                                          keys, widget tokens, triggers,
                                          campaigns), so cancelling restores
                                          exactly that
    organizations.erased_at               set on the tombstone once erased
    organizations.erased_provider_id      the provider id the organisation had,
                                          so auth never re-creates it

A user can now be deleted while what they created stays with the
organisation: every "created by" reference to users becomes nullable and
ON DELETE SET NULL (embed_tokens.created_by used to CASCADE, which deleted the
organisation's widget tokens with their creator), and the user's own rows
(user_configurations, organization_users) are deleted with them.

downgrade: restores the previous constraints. It refuses while any of the
previously NOT NULL columns holds a NULL (a deleted creator), since putting
NOT NULL back would need data this migration cannot invent.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "04b6af5b14b4"
down_revision: str | None = "17450c2f9b60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column, constraint name, was NOT NULL, previous ondelete)
CREATOR_FOREIGN_KEYS: tuple[tuple[str, str, str, bool, str | None], ...] = (
    ("campaigns", "created_by", "campaigns_created_by_fkey", True, None),
    (
        "external_credentials",
        "created_by",
        "external_credentials_created_by_fkey",
        True,
        None,
    ),
    ("tools", "created_by", "tools_created_by_fkey", True, None),
    (
        "knowledge_base_documents",
        "created_by",
        "knowledge_base_documents_created_by_fkey",
        True,
        None,
    ),
    (
        "workflow_recordings",
        "created_by",
        "workflow_recordings_created_by_fkey",
        True,
        None,
    ),
    ("api_keys", "created_by", "api_keys_created_by_fkey", False, None),
    ("integrations", "created_by", "integrations_created_by_fkey", False, None),
    ("workflows", "user_id", "workflows_user_id_fkey", False, None),
    ("embed_tokens", "created_by", "embed_tokens_created_by_fkey", True, "CASCADE"),
)

# The user's own rows go with them.
OWNED_BY_USER: tuple[tuple[str, str, str], ...] = (
    ("user_configurations", "user_id", "user_configurations_user_id_fkey"),
    ("organization_users", "user_id", "organization_users_user_id_fkey"),
)


def _replace_user_fk(table: str, column: str, name: str, ondelete: str | None):
    op.drop_constraint(name, table, type_="foreignkey")
    op.create_foreign_key(name, table, "users", [column], ["id"], ondelete=ondelete)


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("deletion_scheduled_for", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("deletion_suspended", sa.JSON(), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("erased_provider_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_organizations_deletion_scheduled_for",
        "organizations",
        ["deletion_scheduled_for"],
    )
    op.create_index(
        "ix_organizations_erased_provider_id",
        "organizations",
        ["erased_provider_id"],
    )

    for table, column, name, was_not_null, _ in CREATOR_FOREIGN_KEYS:
        if was_not_null:
            op.alter_column(table, column, existing_type=sa.Integer(), nullable=True)
        _replace_user_fk(table, column, name, "SET NULL")

    for table, column, name in OWNED_BY_USER:
        _replace_user_fk(table, column, name, "CASCADE")


def downgrade() -> None:
    bind = op.get_bind()
    for table, column, _, was_not_null, _ in CREATOR_FOREIGN_KEYS:
        if not was_not_null:
            continue
        nulls = bind.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE {column} IS NULL")
        ).scalar()
        if nulls:
            raise RuntimeError(
                f"Cannot downgrade: {nulls} rows of {table}.{column} lost their "
                "creator to a deleted account and cannot be made NOT NULL again."
            )

    for table, column, name in OWNED_BY_USER:
        _replace_user_fk(table, column, name, None)

    for table, column, name, was_not_null, ondelete in CREATOR_FOREIGN_KEYS:
        _replace_user_fk(table, column, name, ondelete)
        if was_not_null:
            op.alter_column(table, column, existing_type=sa.Integer(), nullable=False)

    op.drop_index("ix_organizations_erased_provider_id", table_name="organizations")
    op.drop_index("ix_organizations_deletion_scheduled_for", table_name="organizations")
    op.drop_column("organizations", "erased_provider_id")
    op.drop_column("organizations", "erased_at")
    op.drop_column("organizations", "deletion_suspended")
    op.drop_column("organizations", "deletion_scheduled_for")
    op.drop_column("organizations", "deletion_requested_at")
