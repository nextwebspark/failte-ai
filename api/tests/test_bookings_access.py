"""Who may switch AI booking: the owner and admins, and a staff member the
owner or an admin allowed. Pure policy and the membership object; no database."""

from types import SimpleNamespace

import pytest

from api.enums import OrgRole
from api.services.auth.depends import OrgMembership
from api.services.auth.permissions import (
    ROLE_LABELS,
    Permission,
    has_permissions,
    member_grants,
)


@pytest.mark.parametrize(
    ("role", "manage", "grant"),
    [
        (OrgRole.ADMIN, True, True),
        (OrgRole.VIEWER, True, True),  # the business owner
        (OrgRole.DEVELOPER, False, False),
        (OrgRole.STAFF, False, False),
    ],
)
def test_who_runs_bookings_by_role(role, manage, grant):
    assert has_permissions(role, Permission.BOOKINGS_MANAGE) is manage
    assert has_permissions(role, Permission.BOOKINGS_GRANT) is grant


def test_staff_see_calls_and_reports_but_nothing_else():
    for permission in (
        Permission.CALLS_READ,
        Permission.REPORTS_READ,
        Permission.AGENTS_READ,
    ):
        assert has_permissions(OrgRole.STAFF, permission)
    for permission in (
        Permission.BILLING_READ,
        Permission.MEMBERS_READ,
        Permission.INTEGRATIONS_READ,
        Permission.AGENTS_WRITE,
    ):
        assert not has_permissions(OrgRole.STAFF, permission)


def test_the_bookings_switch_only_lifts_staff():
    assert member_grants(OrgRole.STAFF, True) == {Permission.BOOKINGS_MANAGE}
    assert member_grants(OrgRole.STAFF, False) == frozenset()
    # A developer never gets it, even if the flag was left on from before.
    assert member_grants(OrgRole.DEVELOPER, True) == frozenset()


def test_membership_combines_role_and_grants():
    user = SimpleNamespace(id=1)
    allowed = OrgMembership(
        user=user,
        organization_id=1,
        role=OrgRole.STAFF,
        grants=member_grants(OrgRole.STAFF, True),
    )
    plain = OrgMembership(user=user, organization_id=1, role=OrgRole.STAFF)
    assert allowed.can(Permission.BOOKINGS_MANAGE, Permission.CALLS_READ)
    assert not allowed.can(Permission.BOOKINGS_GRANT)
    assert not plain.can(Permission.BOOKINGS_MANAGE)


def test_role_names():
    assert ROLE_LABELS[OrgRole.VIEWER] == "Owner"
    assert ROLE_LABELS[OrgRole.STAFF] == "Staff"
