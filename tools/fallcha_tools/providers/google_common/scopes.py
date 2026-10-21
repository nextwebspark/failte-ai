"""Google OAuth scopes and API roots used by the Google providers."""

from __future__ import annotations

CALENDAR_API = "https://www.googleapis.com/calendar/v3"
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"
# OAuth2 calendar connections ask for these narrower scopes instead of
# CALENDAR_SCOPE: events covers insert/get/patch/delete; readonly covers
# freeBusy and the calendar's metadata (connection test).
CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
CALENDAR_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
# Read and write: needed to append rows. There is no narrower Google scope
# that allows appending to one sheet only.
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
# Offline access (a refresh token), re-consented on every connect so a
# reconnect always yields a fresh refresh token. No include_granted_scopes:
# one platform client serves every workspace, and merging grants would hand a
# connection in one workspace the scopes the same Google account granted to
# another integration or workspace.
GOOGLE_AUTHORIZE_PARAMS = {
    "access_type": "offline",
    "prompt": "consent",
    "include_granted_scopes": "false",
}
GOOGLE_IDENTITY_SCOPES = ("openid", "email")
