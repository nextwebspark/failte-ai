"""Built-in providers. Add a module here and list it in ``build_registry``."""

from __future__ import annotations

from fallcha_tools.config import Settings
from fallcha_tools.core.platform_apps import PlatformClient
from fallcha_tools.core.provider import ProviderRegistry
from fallcha_tools.providers.google_calendar import (
    GoogleCalendarProvider,
    booking_id_key_from,
)
from fallcha_tools.providers.google_common.connection import GOOGLE_FAMILY
from fallcha_tools.providers.google_sheets import GoogleSheetsProvider
from fallcha_tools.providers.website_catalogue import WebsiteCatalogueProvider


def build_registry(settings: Settings) -> ProviderRegistry:
    """The providers this deployment serves."""
    secret = settings.internal_secret.get_secret_value()
    return ProviderRegistry(
        [
            GoogleCalendarProvider(booking_id_key=booking_id_key_from(secret)),
            GoogleSheetsProvider(),
            WebsiteCatalogueProvider(),
        ]
    )


def platform_client(settings: Settings) -> PlatformClient | None:
    """The platform OAuth client every workspace may use, if configured."""
    if settings.google_client_id is None or settings.google_client_secret is None:
        return None
    return PlatformClient(
        family=GOOGLE_FAMILY,
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret.get_secret_value(),
    )
