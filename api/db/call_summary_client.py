"""Data access for the call summary emailed to the business after a call."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import WorkflowDefinitionModel, WorkflowModel, WorkflowRunModel
from api.db.retention_client import (
    WORKFLOW_RUN_CALL_SUMMARY_EMAILED_KEY,
    WORKFLOW_RUN_PURGED_AT_KEY,
)


@dataclass(frozen=True, slots=True)
class CallSummaryRun:
    """What decides whether a finished run gets a summary, and its content
    apart from the recorded tool calls (loaded only when one is due)."""

    run_id: int
    workflow_id: int
    workflow_name: str
    organization_id: int | None
    mode: str
    is_completed: bool
    started_at: datetime | None
    # The configuration snapshot the run was pinned to.
    workflow_configurations: Mapping[str, Any]
    gathered_context: Mapping[str, Any]


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


class CallSummaryClient(BaseDBClient):
    async def get_call_summary_run(self, run_id: int) -> CallSummaryRun | None:
        async with self.async_session() as session:
            row = (
                await session.execute(
                    select(
                        WorkflowRunModel.id,
                        WorkflowRunModel.workflow_id,
                        WorkflowRunModel.mode,
                        WorkflowRunModel.is_completed,
                        WorkflowRunModel.created_at,
                        WorkflowRunModel.gathered_context,
                        WorkflowModel.name,
                        WorkflowModel.organization_id,
                        WorkflowDefinitionModel.workflow_configurations,
                    )
                    .join(
                        WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id
                    )
                    .outerjoin(
                        WorkflowDefinitionModel,
                        WorkflowRunModel.definition_id == WorkflowDefinitionModel.id,
                    )
                    .where(WorkflowRunModel.id == run_id)
                )
            ).first()
        if row is None:
            return None
        return CallSummaryRun(
            run_id=row.id,
            workflow_id=row.workflow_id,
            workflow_name=row.name,
            organization_id=row.organization_id,
            mode=row.mode,
            is_completed=bool(row.is_completed),
            started_at=row.created_at,
            workflow_configurations=_mapping(row.workflow_configurations),
            gathered_context=_mapping(row.gathered_context),
        )

    async def get_call_summary_events(self, run_id: int) -> list[dict[str, Any]]:
        """The run's recorded realtime events (transcript turns, tool calls)."""
        async with self.async_session() as session:
            events = (
                await session.execute(
                    select(WorkflowRunModel.logs["realtime_feedback_events"]).where(
                        WorkflowRunModel.id == run_id
                    )
                )
            ).scalar_one_or_none()
        if not isinstance(events, list):
            return []
        return [event for event in events if isinstance(event, dict)]

    async def claim_call_summary_email(self, run_id: int, claimed_at: datetime) -> bool:
        """Claim the run's summary for sending; False if it already was, or if
        the retention purge has already removed the call's content.

        The row lock makes concurrent claims for one run serialise, so exactly
        one of them wins.
        """
        async with self.async_session() as session:
            row = (
                await session.execute(
                    select(WorkflowRunModel.extra)
                    .where(WorkflowRunModel.id == run_id)
                    .with_for_update()
                )
            ).first()
            if row is None:
                return False
            extra = _mapping(row.extra)
            if (
                WORKFLOW_RUN_CALL_SUMMARY_EMAILED_KEY in extra
                or WORKFLOW_RUN_PURGED_AT_KEY in extra
            ):
                return False
            await session.execute(
                update(WorkflowRunModel)
                .where(WorkflowRunModel.id == run_id)
                .values(
                    extra={
                        **extra,
                        WORKFLOW_RUN_CALL_SUMMARY_EMAILED_KEY: claimed_at.isoformat(),
                    }
                )
            )
            await session.commit()
            return True
