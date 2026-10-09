"""Built-in providers. Add a module here and list it in ``build_registry``."""

from __future__ import annotations

from fallcha_tools.core.provider import ProviderRegistry
from fallcha_tools.providers.google_calendar import GoogleCalendarProvider


def build_registry() -> ProviderRegistry:
    """The providers this deployment serves."""
    return ProviderRegistry([GoogleCalendarProvider()])
