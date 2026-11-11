"""staff role and per-member bookings access

Revision ID: b7c1d2e3f4a5
Revises: a8f3c2e19b47
Create Date: 2026-11-05 23:00:00.000000

- A "staff" role: view-only (calls, bookings, reports), for a business's
  team. The existing "viewer" role is the business owner (shown as Owner).
- organization_users.can_manage_bookings: the owner or an admin may let one
  staff member switch AI booking on and off. Other roles ignore it.

downgrade: refuses while any member or invitation is "staff", since there is
no older role with the same rights to move them to.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c1d2e3f4a5"
down_revision: str | None = "a8f3c2e19b47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES_WITH_STAFF = "role IN ('admin', 'developer', 'viewer', 'staff')"
ROLES_WITHOUT_STAFF = "role IN ('admin', 'developer', 'viewer')"


def upgrade() -> None:
    op.drop_constraint(
        "ck_organization_users_role", "organization_users", type_="check"
    )
    op.create_check_constraint(
        "ck_organization_users_role", "organization_users", ROLES_WITH_STAFF
    )
    op.drop_constraint(
        "ck_organization_invitations_role", "organization_invitations", type_="check"
    )
    op.create_check_constraint(
        "ck_organization_invitations_role", "organization_invitations", ROLES_WITH_STAFF
    )
    op.add_column(
        "organization_users",
        sa.Column(
            "can_manage_bookings",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    conn = op.get_bind()
    for table in ("organization_users", "organization_invitations"):
        staff = conn.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE role = 'staff'")
        ).scalar_one()
        if staff:
            raise RuntimeError(
                f"{table} has {staff} staff row(s); change their role before downgrading"
            )
    op.drop_column("organization_users", "can_manage_bookings")
    op.drop_constraint(
        "ck_organization_invitations_role", "organization_invitations", type_="check"
    )
    op.create_check_constraint(
        "ck_organization_invitations_role",
        "organization_invitations",
        ROLES_WITHOUT_STAFF,
    )
    op.drop_constraint(
        "ck_organization_users_role", "organization_users", type_="check"
    )
    op.create_check_constraint(
        "ck_organization_users_role", "organization_users", ROLES_WITHOUT_STAFF
    )
