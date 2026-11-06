"""Runtime switches for product areas that are built but not offered to
everyone (Campaigns, Skills).

The switches only decide what the app shows (nav rows, pages, pickers). The
API behind each area is unaffected, as it was with the build-time switch in
ui/src/config/features.ts, whose values are the defaults here.

Resolution, per feature: an organisation's override if it has one, else the
platform-wide value if a platform admin set one, else the default below.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    key: str
    label: str
    description: str
    default: bool


# Keep in step with FEATURES in ui/src/config/features.ts (the UI's fallback
# when the API can't be reached).
FEATURES: dict[str, FeatureDefinition] = {
    definition.key: definition
    for definition in (
        FeatureDefinition(
            key="campaigns",
            label="Campaigns",
            description="Outbound calls in bulk to a contact list (/campaigns).",
            default=False,
        ),
        FeatureDefinition(
            key="skills",
            label="Skills",
            description=(
                "Playbooks agents load mid-call (/skills, and the pickers on "
                "agent steps)."
            ),
            default=False,
        ),
    )
}


def defaults() -> dict[str, bool]:
    return {key: definition.default for key, definition in FEATURES.items()}


def platform_values(platform: Mapping[str, bool]) -> dict[str, bool]:
    """Platform-wide value of every feature: what a platform admin set, else
    the default. Unknown keys (a feature removed from code) are ignored."""
    values = defaults()
    for key, enabled in platform.items():
        if key in values:
            values[key] = bool(enabled)
    return values


def effective_flags(
    platform: Mapping[str, bool], organization: Mapping[str, bool]
) -> dict[str, bool]:
    """What one organisation sees: its overrides on top of the platform-wide
    values."""
    values = platform_values(platform)
    for key, enabled in organization.items():
        if key in values:
            values[key] = bool(enabled)
    return values


def available_somewhere(
    platform: Mapping[str, bool], enabled_for_some_organization: Iterable[str]
) -> dict[str, bool]:
    """Whether each feature is on for at least one organisation.

    The UI middleware runs before it knows who is signed in, so it only sends
    a page of a feature to Overview when no organisation can have it; the
    app then applies the organisation's own value."""
    values = platform_values(platform)
    for key in enabled_for_some_organization:
        if key in values:
            values[key] = True
    return values
