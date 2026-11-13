"""Appointment hours of an agent created from a template.

A template asks for them with an ``appointment_hours`` setup field, answered
only when the agent books with Google or Outlook Calendar. The answer
(``AppointmentHours``) becomes a sentence in the agent's prompt and, when the
request says so (``apply_to_calendar``), the booking hours of that calendar
connection, so the agent and the calendar offer the same times.

The calendar keeps them as one ``service_periods`` entry, the form the
Bookings page's Booking rules edit (see ``calendar_config_patch``).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from loguru import logger
from pydantic import JsonValue

from api.errors.integrations import IntegrationError
from api.schemas.appointment_hours import (
    AppointmentHours,
    CalendarHoursStatus,
    Weekday,
)
from api.schemas.integrations import IntegrationConnectionResponse
from api.schemas.workflow_template import (
    DuplicateTemplateRequest,
    SetupFieldType,
    TemplateSetupField,
)
from api.services.tool_integrations import Actor, get_integration_service
from api.services.workflow.template_setup import (
    RULES_CALENDARS,
    TemplateSetupError,
)


def _join(items: Sequence[str]) -> str:
    """Join as in "A", "A and B", "A, B and C"."""
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _day_name(day: Weekday) -> str:
    return day.name.capitalize()


def _days_phrase(days: Sequence[Weekday]) -> str:
    """The days as in "every day", "Monday to Friday" or "Monday, Wednesday
    and Friday": three or more consecutive days read as a range."""
    if set(days) == set(Weekday):
        return "every day"
    runs: list[list[Weekday]] = []
    for day in sorted(set(days)):
        if runs and day == runs[-1][-1] + 1:
            runs[-1].append(day)
        else:
            runs.append([day])
    parts: list[str] = []
    for run in runs:
        if len(run) >= 3:
            parts.append(f"{_day_name(run[0])} to {_day_name(run[-1])}")
        else:
            parts.extend(_day_name(day) for day in run)
    return _join(parts)


def _clock(hour: int) -> str:
    return "midnight" if hour == 24 else f"{hour}:00"


def _window(open_hour: int, close_hour: int) -> str:
    if (open_hour, close_hour) == (0, 24):
        return "all day"
    return f"{_clock(open_hour)}–{_clock(close_hour)}"


def _length(minutes: int) -> str:
    if minutes % 60 == 0:
        hours = minutes // 60
        return "1 hour" if hours == 1 else f"{hours} hours"
    return f"{minutes} minutes"


def describe_appointment_hours(hours: AppointmentHours) -> str:
    """The sentence the agent's prompt gets, e.g. "Appointments can be booked
    Monday to Friday, 9:00–17:00 (Europe/Dublin time), 30 minutes each."."""
    return (
        f"Appointments can be booked {_days_phrase(hours.booking_days)}, "
        f"{_window(hours.open_hour, hours.close_hour)} ({hours.timezone} time), "
        f"{_length(hours.slot_minutes)} each."
    )


def appointment_hours_answers(
    fields: Sequence[TemplateSetupField], request: DuplicateTemplateRequest
) -> dict[str, str]:
    """The answer to each ``appointment_hours`` field: a line with the
    request's hours, or nothing when none were given. For
    ``fill_template_values``'s *rendered*: the line ends with its own newline,
    so a placeholder with no hours leaves no blank line.

    Raises TemplateSetupError for hours the template doesn't ask for, hours
    without Google or Outlook Calendar attached (only bookings use them), or such a
    field answered as text.
    """
    hours = request.appointment_hours
    keys = [f.key for f in fields if f.type == SetupFieldType.APPOINTMENT_HOURS]
    if hours is not None and not keys:
        raise TemplateSetupError("This template doesn't ask for appointment hours.")
    if hours is not None and _rules_tool(request) is None:
        raise TemplateSetupError(
            "Appointment hours need Google Calendar or Outlook Calendar attached."
        )
    if any(request.values.get(key, "").strip() for key in keys):
        raise TemplateSetupError(
            "Send appointment hours as appointment_hours, not as text."
        )
    line = f"{describe_appointment_hours(hours)}\n" if hours else ""
    return dict.fromkeys(keys, line)


def _books_in(
    connection: IntegrationConnectionResponse, hours: AppointmentHours
) -> bool:
    """Whether the connection's stored settings already are *hours*."""
    return all(
        connection.config.get(key) == value
        for key, value in calendar_config_patch(hours).items()
    )


def _clock_time(minutes: int) -> str:
    """ "09:00", "16:30" (minutes after midnight, below 24 hours)."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def service_period(hours: AppointmentHours) -> dict[str, JsonValue]:
    """The hours as one calendar service period: bookings start from the
    opening hour, the last one so it ends by the closing hour."""
    return {
        "days": [int(day) for day in hours.booking_days],
        "first_start": _clock_time(hours.open_hour * 60),
        "last_start": _clock_time(hours.close_hour * 60 - hours.slot_minutes),
    }


def calendar_config_patch(hours: AppointmentHours) -> dict[str, JsonValue]:
    """The Google Calendar connection settings these hours replace. The
    tools service merges them, keeping the calendar and its other settings.

    The days and hours are written as ``service_periods``, which the calendar
    uses in place of the older ``booking_days``/``open_hour``/``close_hour``
    whenever it is set, and which the Bookings page shows and edits. Those
    older keys are left as they are: they no longer decide anything."""
    return {
        "service_periods": [service_period(hours)],
        "slot_minutes": hours.slot_minutes,
        "timezone": hours.timezone,
    }


class CalendarSettings(Protocol):
    """The part of ``IntegrationService`` that saves connection settings."""

    async def list_connections(
        self, actor: Actor
    ) -> list[IntegrationConnectionResponse]: ...

    async def update_config(
        self,
        actor: Actor,
        connection_id: uuid.UUID,
        config: Mapping[str, JsonValue],
    ) -> IntegrationConnectionResponse: ...


def _rules_tool(request: DuplicateTemplateRequest) -> str | None:
    """The tool of the calendar that keeps the booking hours (Google or
    Outlook Calendar), if the request attaches one."""
    for provider in RULES_CALENDARS:
        if tool := request.integration_tools.get(provider):
            return tool
    return None


async def _connection_of_tool(
    settings: CalendarSettings, actor: Actor, tool_uuid: str
) -> IntegrationConnectionResponse | None:
    """The org's Google or Outlook Calendar connection that *tool_uuid*
    books with."""
    # Org-scoped by the tools service and the workspace's own tools.
    for connection in await settings.list_connections(actor):
        if (
            connection.provider in RULES_CALENDARS
            and tool_uuid in connection.tool_uuids
        ):
            return connection
    return None


async def update_calendar_booking_hours(
    request: DuplicateTemplateRequest,
    actor: Actor,
    *,
    may_change_settings: bool,
    calendar_settings: Callable[[], CalendarSettings] | None = None,
) -> CalendarHoursStatus | None:
    """Make the request's appointment hours the booking hours of the Google
    Calendar connection whose tool the new agent uses, when it asks to
    (``apply_to_calendar``).

    Returns None when there is nothing to do. Best-effort: the agent already
    exists, so any failure is reported as ``FAILED`` (for the caller to point
    the user at Integrations), never raised. *may_change_settings* is whether
    the member's role allows changing integration settings (as
    ``PATCH /integrations/connections/{id}`` does).
    """
    hours = request.appointment_hours
    tool_uuid = _rules_tool(request)
    if not request.apply_to_calendar or hours is None or not tool_uuid:
        return None
    if not may_change_settings:
        return CalendarHoursStatus.NOT_ALLOWED
    org = actor.organization_id
    try:
        settings = (calendar_settings or get_integration_service)()
        connection = await _connection_of_tool(settings, actor, tool_uuid)
        if connection is None:
            logger.warning(
                f"No Google or Outlook Calendar connection uses tool {tool_uuid} in org "
                f"{org}; booking hours not saved"
            )
            return CalendarHoursStatus.FAILED
        if _books_in(connection, hours):
            return CalendarHoursStatus.UPDATED
        await settings.update_config(actor, connection.id, calendar_config_patch(hours))
    except IntegrationError as exc:
        logger.warning(
            f"Saving booking hours for org {org} failed: {type(exc).__name__}: {exc}"
        )
        return CalendarHoursStatus.FAILED
    except Exception:  # noqa: BLE001 - best-effort: the agent is already created
        logger.exception(f"Saving booking hours for org {org} failed unexpectedly")
        return CalendarHoursStatus.FAILED
    logger.info(f"Saved booking hours of connection {connection.id} for org {org}")
    return CalendarHoursStatus.UPDATED
