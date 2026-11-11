"""Reads and writes for shared recording links, stored on the call in
``workflow_runs.annotations["shares"]`` (see api/services/calls/recording_shares)."""

from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from api.db.base_client import BaseDBClient
from api.db.models import OrganizationModel, WorkflowModel, WorkflowRunModel
from api.services.calls.recording_shares import SHARES_ANNOTATION, stored_shares


class RecordingShareClient(BaseDBClient):
    async def change_recording_shares(
        self,
        organization_id: int,
        run_id: int,
        change: Callable[
            [dict[str, Any], list[dict[str, Any]]], list[dict[str, Any]] | None
        ],
    ) -> list[dict[str, Any]] | None:
        """Apply ``change(call, shares)`` to one of the organization's calls,
        under a row lock, and store the list it returns. ``call`` has the
        call's ``recording_url``. Returns the stored list, or None when the
        call isn't the organization's or ``change`` returned None (nothing is
        written then)."""
        async with self.async_session() as session:
            run = await session.scalar(
                select(WorkflowRunModel)
                .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
                .where(
                    WorkflowModel.organization_id == organization_id,
                    WorkflowRunModel.id == run_id,
                )
                .with_for_update(of=WorkflowRunModel)
            )
            if run is None:
                return None
            annotations = dict(run.annotations or {})
            shares = change(
                {"recording_url": run.recording_url}, stored_shares(annotations)
            )
            if shares is None:
                return None
            annotations[SHARES_ANNOTATION] = shares
            run.annotations = annotations
            await session.commit()
            return shares

    async def get_recording_shares(
        self, organization_id: int, run_id: int
    ) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
        """(call, its stored links) for one of the organization's calls."""
        async with self.async_session() as session:
            row = (
                await session.execute(
                    select(WorkflowRunModel.recording_url, WorkflowRunModel.annotations)
                    .join(
                        WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id
                    )
                    .where(
                        WorkflowModel.organization_id == organization_id,
                        WorkflowRunModel.id == run_id,
                    )
                )
            ).first()
            if row is None:
                return None
            return {"recording_url": row.recording_url}, stored_shares(row.annotations)

    async def get_shared_call(self, run_id: int) -> dict[str, Any] | None:
        """What the public listening page needs about a call: its links, the
        recording's location and the business's name. Never the caller."""
        async with self.async_session() as session:
            row = (
                await session.execute(
                    select(
                        WorkflowRunModel.id,
                        WorkflowRunModel.created_at,
                        WorkflowRunModel.recording_url,
                        WorkflowRunModel.storage_backend,
                        WorkflowRunModel.annotations,
                        WorkflowRunModel.usage_info,
                        WorkflowRunModel.initial_context,
                        WorkflowRunModel.extra,
                        WorkflowModel.organization_id,
                        WorkflowModel.template_context_variables,
                        OrganizationModel.name.label("organization_name"),
                    )
                    .join(
                        WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id
                    )
                    .join(
                        OrganizationModel,
                        WorkflowModel.organization_id == OrganizationModel.id,
                    )
                    .where(WorkflowRunModel.id == run_id)
                )
            ).first()
            return dict(row._mapping) if row is not None else None
