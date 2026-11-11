"""Bookkeeping for after-call notifications (``call_notifications``)."""

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert

from api.db.base_client import BaseDBClient
from api.db.models import CallNotificationModel

_MAX_ERROR = 500


class CallNotificationClient(BaseDBClient):
    async def claim_call_notification(
        self, workflow_run_id: int, channel: str, event: str
    ) -> bool:
        """Record that ``channel`` is about to be sent for this run.

        True for the first caller only. A retried job, or a second job for the
        same run, gets False and must not send: at most one email and one text
        per call, even if that means a send that failed half-way is not
        retried.
        """
        async with self.async_session() as session:
            result = await session.execute(
                insert(CallNotificationModel)
                .values(
                    workflow_run_id=workflow_run_id,
                    channel=channel,
                    event=event,
                    status="sending",
                )
                .on_conflict_do_nothing(constraint="uq_call_notifications_run_channel")
                .returning(CallNotificationModel.id)
            )
            claimed = result.scalar_one_or_none() is not None
            await session.commit()
            return claimed

    async def finish_call_notification(
        self,
        workflow_run_id: int,
        channel: str,
        *,
        status: str,
        recipient_count: int,
        error: str | None = None,
    ) -> None:
        async with self.async_session() as session:
            await session.execute(
                update(CallNotificationModel)
                .where(
                    CallNotificationModel.workflow_run_id == workflow_run_id,
                    CallNotificationModel.channel == channel,
                )
                .values(
                    status=status,
                    recipient_count=recipient_count,
                    error=error[:_MAX_ERROR] if error else None,
                )
            )
            await session.commit()
