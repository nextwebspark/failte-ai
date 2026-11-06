"""Organization role → permission policy.

Pure data and functions, no I/O. Routes declare the permission they need
(``require_permission`` in ``api.services.auth.depends``); this module is the
single place that decides which roles grant it. Adding a role or permission
means editing ``ROLE_PERMISSIONS``, not the checks.
"""

from collections.abc import Mapping
from enum import StrEnum

from api.enums import OrgRole


class Permission(StrEnum):
    ORG_MANAGE = "org:manage"
    MEMBERS_READ = "members:read"
    MEMBERS_MANAGE = "members:manage"
    BILLING_READ = "billing:read"
    BILLING_MANAGE = "billing:manage"
    AGENTS_READ = "agents:read"
    AGENTS_WRITE = "agents:write"
    CAMPAIGNS_READ = "campaigns:read"
    CAMPAIGNS_WRITE = "campaigns:write"
    TELEPHONY_READ = "telephony:read"
    TELEPHONY_WRITE = "telephony:write"
    INTEGRATIONS_READ = "integrations:read"
    INTEGRATIONS_WRITE = "integrations:write"
    CREDENTIALS_WRITE = "credentials:write"
    API_KEYS_MANAGE = "api_keys:manage"
    CALLS_READ = "calls:read"
    REPORTS_READ = "reports:read"
    # Switch AI booking on or off on a calendar.
    BOOKINGS_MANAGE = "bookings:manage"
    # Let a staff member manage bookings too.
    BOOKINGS_GRANT = "bookings:grant"
    # Edit an agent's business facts (hours, address, FAQ) but nothing else.
    AGENTS_FACTS = "agents:facts"
    # Choose who is emailed or texted after calls.
    NOTIFICATIONS_MANAGE = "notifications:manage"
    # Mark a follow-up (a call that needs a person) done, or undo it.
    FOLLOWUPS_MANAGE = "followups:manage"
    # Choose which call reports are emailed (daily, weekly, monthly) and to whom.
    REPORTS_SCHEDULE = "reports:schedule"


# What every member of a business can see.
_STAFF: frozenset[Permission] = frozenset(
    {
        Permission.AGENTS_READ,
        Permission.CALLS_READ,
        Permission.REPORTS_READ,
        # Whoever rings the caller back marks it done, staff included.
        Permission.FOLLOWUPS_MANAGE,
    }
)

_READ: frozenset[Permission] = _STAFF | {
    Permission.MEMBERS_READ,
    Permission.BILLING_READ,
    Permission.CAMPAIGNS_READ,
}

# The business owner: reads everything and runs bookings, including who
# on their staff may switch AI booking, and decides who hears about calls.
_VIEWER: frozenset[Permission] = _READ | {
    Permission.BOOKINGS_MANAGE,
    Permission.BOOKINGS_GRANT,
    # The owner keeps what the agent says about the business up to date.
    Permission.AGENTS_FACTS,
    Permission.NOTIFICATIONS_MANAGE,
    Permission.REPORTS_SCHEDULE,
}

# Builds agents; booking decisions stay with the owner and admins.
_DEVELOPER: frozenset[Permission] = _READ | {
    Permission.AGENTS_FACTS,
    Permission.AGENTS_WRITE,
    Permission.CAMPAIGNS_WRITE,
    Permission.TELEPHONY_READ,
    Permission.TELEPHONY_WRITE,
    Permission.INTEGRATIONS_READ,
    Permission.INTEGRATIONS_WRITE,
    Permission.CREDENTIALS_WRITE,
    Permission.API_KEYS_MANAGE,
}

_ADMIN: frozenset[Permission] = frozenset(Permission)

ROLE_PERMISSIONS: Mapping[OrgRole, frozenset[Permission]] = {
    OrgRole.ADMIN: _ADMIN,
    OrgRole.DEVELOPER: _DEVELOPER,
    OrgRole.VIEWER: _VIEWER,
    OrgRole.STAFF: _STAFF,
}


def permissions_for(role: OrgRole) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[role]


def has_permissions(role: OrgRole, *required: Permission) -> bool:
    return permissions_for(role).issuperset(required)


def member_grants(role: OrgRole, can_manage_bookings: bool) -> frozenset[Permission]:
    """Extra permissions one member holds beyond their role: today only a
    staff member the owner or an admin let manage bookings."""
    if role == OrgRole.STAFF and can_manage_bookings:
        return frozenset({Permission.BOOKINGS_MANAGE})
    return frozenset()


# Display names; the stored values never change when these do.
ROLE_LABELS: Mapping[OrgRole, str] = {
    OrgRole.ADMIN: "Admin",
    OrgRole.DEVELOPER: "Developer",
    OrgRole.VIEWER: "Owner",
    OrgRole.STAFF: "Staff",
}
