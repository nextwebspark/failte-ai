"""Reports: the transfer count and the CSV phone column."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from api.services.reports.daily_report import DailyReportService, is_transferred


def _run(run_id, *, call_status="", disposition="UNKNOWN", phone=""):
    # Same shape as ReportsClient.get_workflow_runs_for_daily_report rows.
    return {
        "id": run_id,
        "workflow_id": 1,
        "workflow_name": "Receptionist",
        "created_at": datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc),
        "gathered_context": {
            "mapped_call_disposition": disposition,
            "call_status": call_status,
            "customer_phone_number": phone,
        },
        "usage_info": {"call_duration_seconds": "42"},
        "initial_context": {"phone_number": phone},
    }


@pytest.mark.parametrize(
    "context, expected",
    [
        ({"call_status": "transfer_call"}, True),
        ({"call_status": "call_transferred"}, True),
        # A transfer tool may stamp its own disposition; call_status still counts.
        ({"call_status": "transfer_call", "mapped_call_disposition": "booked"}, True),
        # Organizations with an XFER mapping keep being counted.
        ({"call_status": "user_hangup", "mapped_call_disposition": "XFER"}, True),
        ({"call_status": "user_hangup", "mapped_call_disposition": "UNKNOWN"}, False),
        ({"call_status": "", "mapped_call_disposition": "UNKNOWN"}, False),
        ({}, False),
        (None, False),
    ],
)
def test_is_transferred(context, expected):
    assert is_transferred(context) is expected


@pytest.mark.asyncio
async def test_daily_report_counts_transfers_without_disposition_mapping():
    runs = [
        _run(1, call_status="transfer_call"),
        _run(2, call_status="call_transferred"),
        _run(3, call_status="user_hangup"),
        _run(4, call_status="end_call_tool", disposition="XFER"),
    ]
    with patch(
        "api.services.reports.daily_report.db_client.get_workflow_runs_for_daily_report",
        new=AsyncMock(return_value=runs),
    ):
        report = await DailyReportService().get_daily_report(
            organization_id=1, date="2026-11-05", timezone="Europe/Dublin"
        )

    assert report["metrics"] == {"total_runs": 4, "xfer_count": 3}


@pytest.mark.asyncio
async def test_csv_rows_carry_the_number_the_query_resolved():
    # The query coalesces dialled number, then the inbound caller's number.
    runs = [_run(7, phone="+353861234567")]
    with patch(
        "api.services.reports.daily_report.db_client.get_workflow_runs_for_daily_report",
        new=AsyncMock(return_value=runs),
    ):
        rows = await DailyReportService().get_daily_runs_detail(
            organization_id=1, date="2026-11-05", timezone="Europe/Dublin"
        )

    assert rows[0]["phone_number"] == "+353861234567"


@pytest.mark.asyncio
async def test_report_query_reads_call_status_and_inbound_caller_number():
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock

    from sqlalchemy.dialects import postgresql

    from api.db.reports_client import ReportsClient

    captured = {}

    class _Session:
        async def execute(self, query):
            captured["sql"] = str(
                query.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            )
            result = MagicMock()
            result.all.return_value = []
            return result

    @asynccontextmanager
    async def _session():
        yield _Session()

    client = ReportsClient.__new__(ReportsClient)
    client.async_session = _session
    await client.get_workflow_runs_for_daily_report(
        organization_id=1,
        start_utc=datetime(2026, 11, 5, tzinfo=timezone.utc),
        end_utc=datetime(2026, 11, 6, tzinfo=timezone.utc),
    )

    sql = captured["sql"]
    assert "call_status" in sql
    # Inbound calls only have caller_number; it must be the last fallback.
    phone = sql[sql.index("customer_phone_number") : sql.index("AS phone_number")]
    assert phone.index("phone_number") < phone.index("caller_number")
