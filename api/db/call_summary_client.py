"""Data access for the call summary emailed to the business after a call."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import WorkflowDefinitionModel, WorkflowModel, WorkflowRunModel

# Marker stamped into ``workflow_runs.extra`` when a run's summary is claimed
# for sending, so a re-run completion job never emails it twice.
WORKFLOW_RUN_CALL_SUMMARY_EMAILED_KEY = "call_summary_emailed_at"


@dataclass(frozen=True, slots=True)
class CallSummaryRun:
    """What a finished run's summary is built from."""

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
    realtime_events: Sequence[Mapping[str, Any]]


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
                        WorkflowRunModel.logs,
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
        events = _mapping(row.logs).get("realtime_feedback_events")
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
            realtime_events=[e for e in events if isinstance(e, dict)]
            if isinstance(events, list)
            else [],
        )

    async def claim_call_summary_email(self, run_id: int, claimed_at: datetime) -> bool:
        """Claim the run's summary for sending; False if it already was.

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
            if WORKFLOW_RUN_CALL_SUMMARY_EMAILED_KEY in extra:
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
