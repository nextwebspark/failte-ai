"""Outlook Calendar provider (Microsoft 365 / Outlook.com, via Microsoft Graph)."""

from fallcha_tools.providers.outlook_calendar.auth import MICROSOFT_FAMILY
from fallcha_tools.providers.outlook_calendar.provider import OutlookCalendarProvider

__all__ = ["MICROSOFT_FAMILY", "OutlookCalendarProvider"]
