"""Both post-call jobs reach the notifications, after the steps they depend on."""

from unittest.mock import AsyncMock

import pytest

from api.tasks import run_integrations, workflow_completion


@pytest.fixture
def completion(monkeypatch):
    order = []

    def step(name, side_effect=None):
        async def record(*args, **kwargs):
            order.append(name)
            if side_effect:
                raise side_effect

        return AsyncMock(side_effect=record)

    notify = step("notify")
    monkeypatch.setattr(
        workflow_completion, "run_integrations_post_workflow_run", step("integrations")
    )
    monkeypatch.setattr(
        workflow_completion,
        "report_completed_workflow_run_platform_usage",
        step("usage", RuntimeError("MPS down")),
    )
    monkeypatch.setattr(
        workflow_completion, "sync_external_pbx_call_record", step("write_back")
    )
    monkeypatch.setattr(workflow_completion, "send_call_notifications", notify)
    monkeypatch.setattr(workflow_completion, "mark_post_call_done", step("done"))
    return order, notify


async def test_the_completion_job_notifies_last_before_marking_done(completion):
    order, notify = completion

    await workflow_completion.process_workflow_completion(None, 11)

    notify.assert_awaited_once_with(11)
    # After the write-back (which waits for the final extraction), and before
    # erasure is allowed to start.
    assert order == ["integrations", "usage", "write_back", "notify", "done"]


async def test_a_standalone_integrations_job_notifies(monkeypatch):
    notify = AsyncMock()
    monkeypatch.setattr(run_integrations, "send_call_notifications", notify)
    monkeypatch.setattr(run_integrations, "mark_post_call_done", AsyncMock())
    monkeypatch.setattr(
        run_integrations, "_run_integrations_post_workflow_run", AsyncMock()
    )

    await run_integrations.run_integrations_post_workflow_run(None, 5)

    notify.assert_awaited_once_with(5)


async def test_failed_integrations_still_notify(monkeypatch):
    notify = AsyncMock()
    monkeypatch.setattr(run_integrations, "send_call_notifications", notify)
    monkeypatch.setattr(run_integrations, "mark_post_call_done", AsyncMock())
    monkeypatch.setattr(
        run_integrations,
        "_run_integrations_post_workflow_run",
        AsyncMock(side_effect=RuntimeError("webhook down")),
    )

    with pytest.raises(RuntimeError):
        await run_integrations.run_integrations_post_workflow_run(None, 5)

    notify.assert_awaited_once_with(5)


async def test_inside_the_completion_job_integrations_leave_it_to_the_job(
    monkeypatch,
):
    notify = AsyncMock()
    monkeypatch.setattr(run_integrations, "send_call_notifications", notify)
    monkeypatch.setattr(
        run_integrations, "_run_integrations_post_workflow_run", AsyncMock()
    )

    await run_integrations.run_integrations_post_workflow_run(None, 5, mark_done=False)

    notify.assert_not_awaited()
