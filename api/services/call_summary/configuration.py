"""Reading an agent's call summary setting from its stored configuration."""

from collections.abc import Mapping
from typing import Any

from loguru import logger
from pydantic import ValidationError

from api.schemas.call_summary_email import (
    CALL_SUMMARY_EMAIL_KEY,
    CallSummaryEmailConfiguration,
)


def resolve_call_summary_email(
    workflow_configurations: Mapping[str, Any] | None,
) -> CallSummaryEmailConfiguration:
    """Missing means off. A stored value that no longer validates also reads
    as off: a summary is a convenience, so it is skipped rather than sent to an
    address the agent's owner never confirmed.
    """
    raw = (workflow_configurations or {}).get(CALL_SUMMARY_EMAIL_KEY)
    if raw is None:
        return CallSummaryEmailConfiguration()
    try:
        return CallSummaryEmailConfiguration.model_validate(raw)
    except ValidationError:
        logger.warning("Invalid call_summary_email configuration; treating it as off")
        return CallSummaryEmailConfiguration()
