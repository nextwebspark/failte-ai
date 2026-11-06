"""Reads for Home (the dashboard) and Follow-ups: inbound phone calls, the
phone numbers that answer them, and the follow-up mark stored on a call."""

from datetime import datetime
from typing import Any

from sqlalchemy import String, and_, func, select
from sqlalchemy.orm import selectinload

from api.db.base_client import BaseDBClient
from api.db.models import (
    TelephonyConfigurationModel,
    TelephonyPhoneNumberModel,
    WorkflowModel,
    WorkflowRunModel,
)
from api.enums import WORKFLOW_RUN_MODES_BY_CHANNEL, CallType, WorkflowRunChannel

_TELEPHONY_MODES = tuple(
    WORKFLOW_RUN_MODES_BY_CHANNEL[WorkflowRunChannel.TELEPHONY.value]
)

# The key under a run's ``annotations`` that holds its follow-up mark.
FOLLOW_UP_ANNOTATION = "follow_up"
# Marks for the call-review follow-up kinds, by kind.
FOLLOW_UP_KINDS_ANNOTATION = "follow_up_kinds"
# The call review (api/services/call_review).
CALL_REVIEW_ANNOTATION = "call_review"


def _inbound_phone_call(organization_id: int, workflow_id: int | None):
    conditions = [
        WorkflowModel.organization_id == organization_id,
        WorkflowRunModel.mode.in_(_TELEPHONY_MODES),
        WorkflowRunModel.call_type == CallType.INBOUND.value,
    ]
    if workflow_id is not None:
        conditions.append(WorkflowRunModel.workflow_id == workflow_id)
    return and_(*conditions)


class DashboardClient(BaseDBClient):
    async def get_inbound_calls_for_dashboard(
        self,
        organization_id: int,
        start_utc: datetime,
        end_utc: datetime,
        workflow_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Inbound phone calls created in ``[start_utc, end_utc)``, newest
        first. Browser test calls, text chats and outbound calls are left out.

        The call log is not loaded (it holds the whole transcript); instead
        ``transfer_hint`` says whether it mentions a failed transfer, and
        ``get_call_logs`` loads the log for those calls only.
        """
        async with self.async_session() as session:
            query = (
                select(
                    WorkflowRunModel.id,
                    WorkflowRunModel.workflow_id,
                    WorkflowModel.name.label("workflow_name"),
                    WorkflowRunModel.created_at,
                    WorkflowRunModel.mode,
                    WorkflowRunModel.call_type,
                    WorkflowRunModel.is_completed,
                    WorkflowRunModel.recording_url,
                    WorkflowRunModel.gathered_context,
                    WorkflowRunModel.usage_info,
                    WorkflowRunModel.initial_context,
                    WorkflowRunModel.annotations,
                    func.cast(WorkflowRunModel.logs, String)
                    .like("%transfer_failed%")
                    .label("transfer_hint"),
                )
                .select_from(WorkflowRunModel)
                .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
                .where(
                    _inbound_phone_call(organization_id, workflow_id),
                    WorkflowRunModel.created_at >= start_utc,
                    WorkflowRunModel.created_at < end_utc,
                )
                .order_by(
                    WorkflowRunModel.created_at.desc(), WorkflowRunModel.id.desc()
                )
            )
            rows = (await session.execute(query)).all()
            return [
                {
                    "id": row.id,
                    "workflow_id": row.workflow_id,
                    "workflow_name": row.workflow_name,
                    "created_at": row.created_at,
                    "mode": row.mode,
                    "call_type": row.call_type,
                    "is_completed": bool(row.is_completed),
                    "has_recording": bool(row.recording_url),
                    "gathered_context": row.gathered_context or {},
                    "usage_info": row.usage_info or {},
                    "initial_context": row.initial_context or {},
                    "annotations": row.annotations or {},
                    "transfer_hint": bool(row.transfer_hint),
                }
                for row in rows
            ]

    async def get_call_logs(self, run_ids: list[int]) -> dict[int, dict[str, Any]]:
        """The stored call log of each run, by run id."""
        if not run_ids:
            return {}
        async with self.async_session() as session:
            result = await session.execute(
                select(WorkflowRunModel.id, WorkflowRunModel.logs).where(
                    WorkflowRunModel.id.in_(run_ids)
                )
            )
            return {row.id: row.logs or {} for row in result.all()}

    async def count_inbound_calls(
        self,
        organization_id: int,
        start_utc: datetime,
        end_utc: datetime,
        workflow_id: int | None = None,
    ) -> int:
        """How many calls ``get_inbound_calls_for_dashboard`` would return."""
        async with self.async_session() as session:
            count = await session.scalar(
                select(func.count(WorkflowRunModel.id))
                .select_from(WorkflowRunModel)
                .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
                .where(
                    _inbound_phone_call(organization_id, workflow_id),
                    WorkflowRunModel.created_at >= start_utc,
                    WorkflowRunModel.created_at < end_utc,
                )
            )
            return int(count or 0)

    async def get_last_inbound_call_at(
        self, organization_id: int, workflow_id: int | None = None
    ) -> datetime | None:
        async with self.async_session() as session:
            return await session.scalar(
                select(func.max(WorkflowRunModel.created_at))
                .select_from(WorkflowRunModel)
                .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
                .where(_inbound_phone_call(organization_id, workflow_id))
            )

    async def get_dashboard_agents(self, organization_id: int) -> list[dict[str, Any]]:
        """The organization's agents: id, name, status and the timezone
        saved with their opening hours."""
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    WorkflowModel.id,
                    WorkflowModel.name,
                    WorkflowModel.status,
                    WorkflowModel.template_context_variables,
                )
                .where(WorkflowModel.organization_id == organization_id)
                .order_by(WorkflowModel.created_at, WorkflowModel.id)
            )
            agents = []
            for row in result.all():
                variables = row.template_context_variables or {}
                timezone = (
                    variables.get("timezone") if isinstance(variables, dict) else None
                )
                agents.append(
                    {
                        "id": row.id,
                        "name": row.name,
                        "status": row.status,
                        "timezone": timezone if isinstance(timezone, str) else None,
                    }
                )
            return agents

    async def get_answering_numbers(self, organization_id: int) -> list[dict[str, Any]]:
        """Every phone number of the organization with what it is linked to.

        Read without the configuration's credentials, so it is safe to serve
        to members who may not read telephony settings.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    TelephonyPhoneNumberModel.id,
                    TelephonyPhoneNumberModel.address,
                    TelephonyPhoneNumberModel.is_active,
                    TelephonyPhoneNumberModel.inbound_workflow_id,
                    TelephonyConfigurationModel.inactive.label("config_inactive"),
                )
                .select_from(TelephonyPhoneNumberModel)
                .join(
                    TelephonyConfigurationModel,
                    TelephonyPhoneNumberModel.telephony_configuration_id
                    == TelephonyConfigurationModel.id,
                )
                .where(TelephonyPhoneNumberModel.organization_id == organization_id)
                .order_by(TelephonyPhoneNumberModel.id)
            )
            return [
                {
                    "id": row.id,
                    "address": row.address,
                    "is_active": bool(row.is_active),
                    "config_inactive": bool(row.config_inactive),
                    "inbound_workflow_id": row.inbound_workflow_id,
                }
                for row in result.all()
            ]

    async def get_agent_template_source(
        self, organization_id: int, workflow_id: int
    ) -> dict[str, Any] | None:
        """What tells which starter an agent came from: its live definition
        (else its working one) and its business facts."""
        async with self.async_session() as session:
            workflow = await session.scalar(
                select(WorkflowModel)
                .options(selectinload(WorkflowModel.released_definition))
                .where(
                    WorkflowModel.organization_id == organization_id,
                    WorkflowModel.id == workflow_id,
                )
            )
            if workflow is None:
                return None
            released = workflow.released_definition
            return {
                "definition": released.workflow_json
                if released is not None
                else workflow.workflow_definition,
                "facts": workflow.template_context_variables or {},
            }

    async def get_calls_to_review(
        self, organization_id: int, limit: int, *, include_reviewed: bool = False
    ) -> list[int]:
        """Finished inbound phone calls of the organization, newest first,
        that have no call review yet (or any, with ``include_reviewed``)."""
        async with self.async_session() as session:
            query = (
                select(WorkflowRunModel.id)
                .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
                .where(
                    _inbound_phone_call(organization_id, None),
                    WorkflowRunModel.is_completed.is_(True),
                )
                .order_by(
                    WorkflowRunModel.created_at.desc(), WorkflowRunModel.id.desc()
                )
                .limit(limit)
            )
            if not include_reviewed:
                query = query.where(
                    WorkflowRunModel.annotations[CALL_REVIEW_ANNOTATION]
                    .as_string()
                    .is_(None)
                )
            return list((await session.scalars(query)).all())

    async def set_follow_up_mark(
        self,
        organization_id: int,
        run_id: int,
        mark: dict[str, Any] | None,
        kind: str | None = None,
    ) -> dict[str, Any] | None:
        """Store (or with None, clear) the follow-up mark on one of the
        organization's inbound phone calls: the call's own, or with ``kind``
        that call-review kind's. Returns the run's fields as
        ``get_inbound_calls_for_dashboard`` does, or None when the call is not
        the organization's."""
        async with self.async_session() as session:
            run = await session.scalar(
                select(WorkflowRunModel)
                .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
                .where(
                    _inbound_phone_call(organization_id, None),
                    WorkflowRunModel.id == run_id,
                )
                .with_for_update(of=WorkflowRunModel)
            )
            if run is None:
                return None
            annotations = dict(run.annotations or {})
            if kind is not None:
                marks = annotations.get(FOLLOW_UP_KINDS_ANNOTATION)
                marks = dict(marks) if isinstance(marks, dict) else {}
                if mark is None:
                    marks.pop(kind, None)
                else:
                    marks[kind] = mark
                if marks:
                    annotations[FOLLOW_UP_KINDS_ANNOTATION] = marks
                else:
                    annotations.pop(FOLLOW_UP_KINDS_ANNOTATION, None)
            elif mark is None:
                annotations.pop(FOLLOW_UP_ANNOTATION, None)
            else:
                annotations[FOLLOW_UP_ANNOTATION] = mark
            run.annotations = annotations
            await session.commit()
            return {"id": run.id, "annotations": annotations}
