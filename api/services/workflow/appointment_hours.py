"""Appointment hours of an agent created from a template.

A template asks for them with an ``appointment_hours`` setup field. The
answer (``AppointmentHours``) becomes a sentence in the agent's prompt and,
when the agent is created with Google Calendar attached, the booking hours of
that calendar connection, so the agent and the calendar offer the same times.
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
from api.schemas.workflow_template import SetupFieldType, TemplateSetupField
from api.services.tool_integrations import Actor, get_integration_service
from api.services.workflow.template_setup import GOOGLE_CALENDAR, TemplateSetupError


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
    return "midnight" if hour in (0, 24) else f"{hour}:00"


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


def with_appointment_hours(
    fields: Sequence[TemplateSetupField],
    values: Mapping[str, str],
    hours: AppointmentHours | None,
) -> dict[str, str]:
    """*values* plus the answer to each ``appointment_hours`` field: the
    sentence for *hours*, or nothing when none were given (old clients).

    Raises TemplateSetupError for hours the template doesn't ask for, or for
    such a field answered as text in *values*.
    """
    keys = [f.key for f in fields if f.type == SetupFieldType.APPOINTMENT_HOURS]
    if hours is not None and not keys:
        raise TemplateSetupError("This template doesn't ask for appointment hours.")
    answers = dict(values)
    for key in keys:
        if answers.get(key, "").strip():
            raise TemplateSetupError(
                "Send appointment hours as appointment_hours, not as text."
            )
        answers[key] = describe_appointment_hours(hours) if hours else ""
    return answers


def calendar_config_patch(hours: AppointmentHours) -> dict[str, JsonValue]:
    """The Google Calendar connection settings these hours replace. The
    tools service merges them, keeping the calendar and its other settings."""
    return {
        "booking_days": [int(day) for day in hours.booking_days],
        "open_hour": hours.open_hour,
        "close_hour": hours.close_hour,
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


async def _connection_of_tool(
    settings: CalendarSettings, actor: Actor, tool_uuid: str
) -> IntegrationConnectionResponse | None:
    """The org's Google Calendar connection that *tool_uuid* books with."""
    # Org-scoped by the tools service and the workspace's own tools.
    for connection in await settings.list_connections(actor):
        if (
            connection.provider == GOOGLE_CALENDAR
            and tool_uuid in connection.tool_uuids
        ):
            return connection
    return None


async def update_calendar_booking_hours(
    hours: AppointmentHours | None,
    integration_tools: Mapping[str, str],
    actor: Actor,
    *,
    may_change_settings: bool,
    calendar_settings: Callable[[], CalendarSettings] | None = None,
) -> CalendarHoursStatus | None:
    """Make *hours* the booking hours of the Google Calendar connection whose
    tool the new agent uses (``integration_tools``).

    Returns None when there is nothing to do (no hours, or no calendar
    attached). The agent already exists, so a tools-service failure is
    reported as ``FAILED`` (for the caller to point the user at
    Integrations), not raised.
    *may_change_settings* is whether the member's role allows changing
    integration settings (as ``PATCH /integrations/connections/{id}`` does).
    """
    tool_uuid = integration_tools.get(GOOGLE_CALENDAR)
    if hours is None or not tool_uuid:
        return None
    if not may_change_settings:
        return CalendarHoursStatus.NOT_ALLOWED
    try:
        settings = (calendar_settings or get_integration_service)()
        connection = await _connection_of_tool(settings, actor, tool_uuid)
        if connection is None:
            logger.warning(
                f"No Google Calendar connection uses tool {tool_uuid} in org "
                f"{actor.organization_id}; booking hours not saved"
            )
            return CalendarHoursStatus.FAILED
        await settings.update_config(actor, connection.id, calendar_config_patch(hours))
    except IntegrationError as exc:
        logger.warning(
            f"Saving booking hours for org {actor.organization_id} failed: "
            f"{type(exc).__name__}: {exc}"
        )
        return CalendarHoursStatus.FAILED
    logger.info(
        f"Saved booking hours of connection {connection.id} for org "
        f"{actor.organization_id}"
    )
    return CalendarHoursStatus.UPDATED
