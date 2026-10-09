"""Built-in providers. Add a module here and list it in ``build_registry``."""

from __future__ import annotations

from fallcha_tools.config import Settings
from fallcha_tools.core.provider import ProviderRegistry
from fallcha_tools.providers.google_calendar import (
    GoogleCalendarProvider,
    booking_id_key_from,
)


def build_registry(settings: Settings) -> ProviderRegistry:
    """The providers this deployment serves."""
    secret = settings.internal_secret.get_secret_value()
    return ProviderRegistry(
        [GoogleCalendarProvider(booking_id_key=booking_id_key_from(secret))]
    )
