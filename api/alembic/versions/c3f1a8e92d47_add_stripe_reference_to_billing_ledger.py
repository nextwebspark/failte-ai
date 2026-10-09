"""Add stripe_reference to billing ledger entries.

Revision ID: c3f1a8e92d47
Revises: a7c3e9d41b20
"""

import sqlalchemy as sa
from alembic import op

revision = "c3f1a8e92d47"
down_revision = "a7c3e9d41b20"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "billing_ledger_entries",
        sa.Column("stripe_reference", sa.String(), nullable=True),
    )
    op.create_index(
        "uq_billing_ledger_entries_stripe_reference",
        "billing_ledger_entries",
        ["stripe_reference"],
        unique=True,
        postgresql_where=sa.text("stripe_reference IS NOT NULL"),
    )


def downgrade():
    op.drop_index(
        "uq_billing_ledger_entries_stripe_reference",
        table_name="billing_ledger_entries",
    )
    op.drop_column("billing_ledger_entries", "stripe_reference")
