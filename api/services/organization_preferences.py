from inspect import isawaitable
from typing import Annotated

from loguru import logger
from pydantic import Field, TypeAdapter, ValidationError

from api.db import db_client
from api.enums import OrganizationConfigurationKey
from api.schemas.call_events import CallEventsSettings
from api.schemas.organization_preferences import (
    DEFAULT_CALL_DATA_RETENTION_DAYS,
    MAX_CALL_DATA_RETENTION_DAYS,
    MIN_CALL_DATA_RETENTION_DAYS,
    OrganizationPreferences,
    OrganizationPreferencesResponse,
)
from api.services.observability.call_events.configuration import (
    CONFIG_KEY,
    load_settings,
    masked_settings,
    resolve_settings,
)

# Strict: a stored ``true`` must not read as a one-day retention period.
_CALL_DATA_RETENTION_DAYS = TypeAdapter(
    Annotated[
        int,
        Field(
            strict=True,
            ge=MIN_CALL_DATA_RETENTION_DAYS,
            le=MAX_CALL_DATA_RETENTION_DAYS,
        ),
    ]
)


async def get_organization_preferences(
    organization_id: int | None,
    db=None,
) -> OrganizationPreferences:
    if organization_id is None:
        return OrganizationPreferences()

    row = await _get_preferences_row(db or db_client, organization_id)
    return _parse_preferences(row.value if row is not None else None, organization_id)


async def get_call_data_retention_days(organization_id: int, db=None) -> int | None:
    """The retention period the organization stored, read strictly for deletion.

    Unlike ``get_organization_preferences``, an invalid row never falls back to
    the default: an organization that chose 365 days must not lose data at 90
    because some unrelated preference no longer validates. Only this one field
    is validated. Returns the default when nothing was stored, and None when a
    stored value cannot be trusted (the caller should skip the organization).
    """
    row = await _get_preferences_row(db or db_client, organization_id)
    value = row.value if row is not None else None
    if not value:
        return DEFAULT_CALL_DATA_RETENTION_DAYS
    if not isinstance(value, dict):
        return None
    if "call_data_retention_days" not in value:
        return DEFAULT_CALL_DATA_RETENTION_DAYS
    try:
        return _CALL_DATA_RETENTION_DAYS.validate_python(
            value["call_data_retention_days"]
        )
    except ValidationError:
        return None


async def upsert_organization_preferences(
    organization_id: int,
    preferences: OrganizationPreferences,
) -> OrganizationPreferences:
    await db_client.upsert_configuration(
        organization_id,
        OrganizationConfigurationKey.ORGANIZATION_PREFERENCES.value,
        preferences.model_dump(mode="json", exclude_none=True, exclude={"call_events"}),
    )
    return preferences


async def external_pbx_integrations_enabled(
    organization_id: int | None,
    db=None,
) -> bool:
    """Return whether the organization opted into external-PBX integrations."""

    preferences = await get_organization_preferences(organization_id, db=db)
    return preferences.external_pbx_integrations_enabled


async def _get_preferences_row(db, organization_id: int):
    row = await _get_configuration(
        db,
        organization_id,
        OrganizationConfigurationKey.ORGANIZATION_PREFERENCES.value,
    )
    if row is None:
        row = await _get_configuration(
            db,
            organization_id,
            OrganizationConfigurationKey.MODEL_CONFIGURATION_PREFERENCES.value,
        )
    return row


async def _get_configuration(db, organization_id: int, key: str):
    row = db.get_configuration(organization_id, key)
    if isawaitable(row):
        row = await row
    return row


def _parse_preferences(value, organization_id: int) -> OrganizationPreferences:
    if not value or not isinstance(value, dict):
        return OrganizationPreferences()
    try:
        return OrganizationPreferences.model_validate(value)
    except ValidationError as exc:
        logger.warning(
            "Invalid organization preferences for organization "
            f"{organization_id}: {exc}. Returning defaults."
        )
        return OrganizationPreferences()


async def get_organization_preferences_response(
    organization_id: int,
) -> OrganizationPreferencesResponse:
    preferences = await get_organization_preferences(organization_id)
    settings = masked_settings(await load_settings(organization_id))
    return OrganizationPreferencesResponse(
        **preferences.model_dump(exclude={"call_events"}), call_events=settings
    )


async def update_organization_preferences(
    organization_id: int, request: OrganizationPreferences
) -> OrganizationPreferencesResponse:
    # Validate before writing either row. Omission leaves the sink untouched,
    # including for older clients that only know about general preferences.
    settings = None
    if "call_events" in request.model_fields_set:
        settings = await resolve_settings(
            organization_id, request.call_events or CallEventsSettings()
        )

    updates = request.model_dump(exclude_unset=True, exclude={"call_events"})
    if updates:
        previous = await get_organization_preferences(organization_id)
        preferences = OrganizationPreferences.model_validate(
            {**previous.model_dump(), **updates}
        )
        await upsert_organization_preferences(organization_id, preferences)

    if settings is not None:
        if settings.sink_type is None:
            await db_client.delete_configuration(organization_id, CONFIG_KEY)
        else:
            await db_client.upsert_configuration(
                organization_id, CONFIG_KEY, settings.model_dump(mode="json")
            )
    return await get_organization_preferences_response(organization_id)
