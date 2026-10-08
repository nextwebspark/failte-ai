"""Add billing accounts and credit ledger.

Revision ID: a7c3e9d41b20
Revises: 62ff8b10f9a8
"""

import sqlalchemy as sa
from alembic import op

revision = "a7c3e9d41b20"
down_revision = "62ff8b10f9a8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "billing_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("plan", sa.String(length=32), nullable=False, server_default="payg"),
        sa.Column(
            "balance_eur",
            sa.Numeric(14, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "credit_limit_eur",
            sa.Numeric(14, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("price_per_minute_eur", sa.Numeric(10, 4), nullable=True),
        sa.Column("stripe_customer_id", sa.String(), nullable=True, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "plan IN ('payg', 'done_for_you', 'enterprise')",
            name="ck_billing_accounts_plan",
        ),
        sa.CheckConstraint(
            "credit_limit_eur >= 0", name="ck_billing_accounts_credit_limit"
        ),
    )

    op.create_table(
        "billing_ledger_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entry_type", sa.String(length=32), nullable=False),
        sa.Column("amount_eur", sa.Numeric(14, 4), nullable=False),
        sa.Column("balance_after_eur", sa.Numeric(14, 4), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "workflow_run_id",
            sa.Integer(),
            sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("stripe_checkout_session_id", sa.String(), nullable=True),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "entry_type IN ('topup', 'usage', 'setup_fee', 'trial_credit', "
            "'adjustment', 'refund')",
            name="ck_billing_ledger_entries_entry_type",
        ),
    )
    op.create_index(
        "uq_billing_ledger_entries_usage_run",
        "billing_ledger_entries",
        ["workflow_run_id"],
        unique=True,
        postgresql_where=sa.text("entry_type = 'usage'"),
    )
    op.create_index(
        "uq_billing_ledger_entries_checkout_session",
        "billing_ledger_entries",
        ["stripe_checkout_session_id"],
        unique=True,
        postgresql_where=sa.text("stripe_checkout_session_id IS NOT NULL"),
    )
    op.create_index(
        "ix_billing_ledger_entries_org_created",
        "billing_ledger_entries",
        ["organization_id", "created_at"],
    )


def downgrade():
    op.drop_index(
        "ix_billing_ledger_entries_org_created", table_name="billing_ledger_entries"
    )
    op.drop_index(
        "uq_billing_ledger_entries_checkout_session",
        table_name="billing_ledger_entries",
    )
    op.drop_index(
        "uq_billing_ledger_entries_usage_run", table_name="billing_ledger_entries"
    )
    op.drop_table("billing_ledger_entries")
    op.drop_table("billing_accounts")
