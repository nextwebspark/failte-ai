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


_VIEWER: frozenset[Permission] = frozenset(
    {
        Permission.MEMBERS_READ,
        Permission.BILLING_READ,
        Permission.AGENTS_READ,
        Permission.CAMPAIGNS_READ,
        Permission.CALLS_READ,
        Permission.REPORTS_READ,
    }
)

_DEVELOPER: frozenset[Permission] = _VIEWER | {
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
}


def permissions_for(role: OrgRole) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[role]


def has_permissions(role: OrgRole, *required: Permission) -> bool:
    return permissions_for(role).issuperset(required)


# Display names; the stored values never change when these do.
ROLE_LABELS: Mapping[OrgRole, str] = {
    OrgRole.ADMIN: "Admin",
    OrgRole.DEVELOPER: "Developer",
    OrgRole.VIEWER: "Client",
}
