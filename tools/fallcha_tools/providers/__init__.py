"""Built-in providers. Add a module here and list it in ``build_registry``."""

from __future__ import annotations

from fallcha_tools.config import Settings
from fallcha_tools.core.platform_apps import PlatformClient
from fallcha_tools.core.provider import Provider, ProviderRegistry
from fallcha_tools.providers.calendly import CalendlyProvider
from fallcha_tools.providers.google_calendar import (
    GoogleCalendarProvider,
    booking_id_key_from,
)
from fallcha_tools.providers.google_common.connection import GOOGLE_FAMILY
from fallcha_tools.providers.google_sheets import GoogleSheetsProvider
from fallcha_tools.providers.outlook_calendar import (
    MICROSOFT_FAMILY,
    OutlookCalendarProvider,
)
from fallcha_tools.providers.website_catalogue import WebsiteCatalogueProvider


def build_registry(settings: Settings) -> ProviderRegistry:
    """The providers this deployment serves. Outlook Calendar is only
    served with a platform Microsoft client (``TOOLS_MICROSOFT_CLIENT_ID``):
    without one there is no way to connect it."""
    secret = settings.internal_secret.get_secret_value()
    booking_id_key = booking_id_key_from(secret)
    providers: list[Provider] = [
        GoogleCalendarProvider(booking_id_key=booking_id_key),
        GoogleSheetsProvider(),
        WebsiteCatalogueProvider(),
        CalendlyProvider(),
    ]
    if microsoft_client(settings) is not None:
        providers.insert(
            1,
            OutlookCalendarProvider(
                booking_id_key=booking_id_key, tenant=settings.microsoft_tenant
            ),
        )
    return ProviderRegistry(providers)


def platform_client(settings: Settings) -> PlatformClient | None:
    """The platform Google OAuth client every workspace may use, if configured."""
    if settings.google_client_id is None or settings.google_client_secret is None:
        return None
    return PlatformClient(
        family=GOOGLE_FAMILY,
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret.get_secret_value(),
    )


def microsoft_client(settings: Settings) -> PlatformClient | None:
    """The platform Microsoft OAuth client (Outlook Calendar), if configured."""
    if settings.microsoft_client_id is None or settings.microsoft_client_secret is None:
        return None
    return PlatformClient(
        family=MICROSOFT_FAMILY,
        client_id=settings.microsoft_client_id,
        client_secret=settings.microsoft_client_secret.get_secret_value(),
    )


def platform_clients(settings: Settings) -> list[PlatformClient]:
    """Every platform OAuth client this deployment offers (one per family)."""
    return [
        client
        for client in (platform_client(settings), microsoft_client(settings))
        if client is not None
    ]
