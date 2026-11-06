from datetime import datetime, time
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from api.db import db_client

# How the engine records a call that was handed to a person: "transfer_call"
# once the destination answers a bridged transfer, "call_transferred" when an
# external PBX takes the caller. Read from call_status, not the disposition,
# because a transfer tool may set its own disposition on success.
TRANSFERRED_CALL_STATUSES = frozenset({"transfer_call", "call_transferred"})


def is_transferred(gathered_context: Optional[Dict[str, Any]]) -> bool:
    """Whether a call ended by being passed to a person.

    Organizations that map dispositions to "XFER" keep being counted that way.
    """
    if not gathered_context:
        return False
    return (
        gathered_context.get("call_status") in TRANSFERRED_CALL_STATUSES
        or gathered_context.get("mapped_call_disposition") == "XFER"
    )


class DailyReportService:
    async def get_daily_report(
        self,
        organization_id: int,
        date: str,
        timezone: str,
        workflow_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get daily report for a specific date and timezone.

        Args:
            organization_id: The organization ID to filter by
            date: Date in YYYY-MM-DD format
            timezone: IANA timezone string (e.g., "America/New_York")
            workflow_id: Optional workflow ID to filter by (None means all workflows)
        """
        # Parse date and timezone
        tz = ZoneInfo(timezone)
        date_obj = datetime.strptime(date, "%Y-%m-%d")

        # Create start and end datetime in the specified timezone
        start_dt = datetime.combine(date_obj, time.min, tzinfo=tz)
        end_dt = datetime.combine(date_obj, time.max, tzinfo=tz)

        # Convert to UTC for database queries
        start_utc = start_dt.astimezone(ZoneInfo("UTC"))
        end_utc = end_dt.astimezone(ZoneInfo("UTC"))

        # Get workflow runs from database (optimized - only required fields)
        runs = await db_client.get_workflow_runs_for_daily_report(
            organization_id=organization_id,
            start_utc=start_utc,
            end_utc=end_utc,
            workflow_id=workflow_id,
        )

        # Calculate metrics
        total_runs = len(runs)
        xfer_count = sum(1 for run in runs if is_transferred(run["gathered_context"]))

        # Calculate disposition distribution
        disposition_counts = {}
        for run in runs:
            if run["gathered_context"]:
                disposition = run["gathered_context"].get(
                    "mapped_call_disposition", "UNKNOWN"
                )
                disposition_counts[disposition] = (
                    disposition_counts.get(disposition, 0) + 1
                )

        # Sort dispositions by count and get top 5
        sorted_dispositions = sorted(
            disposition_counts.items(), key=lambda x: x[1], reverse=True
        )

        disposition_distribution = []
        other_count = 0

        for i, (disposition, count) in enumerate(sorted_dispositions):
            if i < 5:
                disposition_distribution.append(
                    {
                        "disposition": disposition,
                        "count": count,
                        "percentage": round(
                            (count / total_runs * 100) if total_runs > 0 else 0, 2
                        ),
                    }
                )
            else:
                other_count += count

        # Add "Other" category if there are more than 5 dispositions
        if other_count > 0:
            disposition_distribution.append(
                {
                    "disposition": "Other",
                    "count": other_count,
                    "percentage": round(
                        (other_count / total_runs * 100) if total_runs > 0 else 0, 2
                    ),
                }
            )

        # Calculate call duration distribution
        duration_buckets = {
            "0-10": {"range_start": 0, "range_end": 10, "count": 0},
            "10-30": {"range_start": 10, "range_end": 30, "count": 0},
            "30-60": {"range_start": 30, "range_end": 60, "count": 0},
            "60-120": {"range_start": 60, "range_end": 120, "count": 0},
            "120-180": {"range_start": 120, "range_end": 180, "count": 0},
            ">180": {"range_start": 180, "range_end": None, "count": 0},
        }

        for run in runs:
            if run["usage_info"]:
                duration_str = run["usage_info"].get("call_duration_seconds")
                if duration_str:
                    try:
                        duration = float(duration_str)
                        if duration < 10:
                            duration_buckets["0-10"]["count"] += 1
                        elif duration < 30:
                            duration_buckets["10-30"]["count"] += 1
                        elif duration < 60:
                            duration_buckets["30-60"]["count"] += 1
                        elif duration < 120:
                            duration_buckets["60-120"]["count"] += 1
                        elif duration < 180:
                            duration_buckets["120-180"]["count"] += 1
                        else:
                            duration_buckets[">180"]["count"] += 1
                    except (ValueError, TypeError):
                        pass

        # Format duration distribution
        call_duration_distribution = []
        total_calls_with_duration = sum(b["count"] for b in duration_buckets.values())

        for bucket_name, bucket_data in duration_buckets.items():
            call_duration_distribution.append(
                {
                    "bucket": bucket_name,
                    "range_start": bucket_data["range_start"],
                    "range_end": bucket_data["range_end"],
                    "count": bucket_data["count"],
                    "percentage": round(
                        (bucket_data["count"] / total_calls_with_duration * 100)
                        if total_calls_with_duration > 0
                        else 0,
                        2,
                    ),
                }
            )

        return {
            "date": date,
            "timezone": timezone,
            "workflow_id": workflow_id,
            "metrics": {"total_runs": total_runs, "xfer_count": xfer_count},
            "disposition_distribution": disposition_distribution,
            "call_duration_distribution": call_duration_distribution,
        }

    async def get_workflows_for_organization(
        self, organization_id: int
    ) -> List[Dict[str, Any]]:
        """
        Get all workflows for an organization.
        """
        workflows = await db_client.get_workflows_for_organization(organization_id)

        return [{"id": workflow.id, "name": workflow.name} for workflow in workflows]

    async def get_daily_runs_detail(
        self,
        organization_id: int,
        date: str,
        timezone: str,
        workflow_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get detailed workflow runs for CSV export.

        Args:
            organization_id: The organization ID to filter by
            date: Date in YYYY-MM-DD format
            timezone: IANA timezone string (e.g., "America/New_York")
            workflow_id: Optional workflow ID to filter by
        """
        # Parse date and timezone
        tz = ZoneInfo(timezone)
        date_obj = datetime.strptime(date, "%Y-%m-%d")

        # Create start and end datetime in the specified timezone
        start_dt = datetime.combine(date_obj, time.min, tzinfo=tz)
        end_dt = datetime.combine(date_obj, time.max, tzinfo=tz)

        # Convert to UTC for database queries
        start_utc = start_dt.astimezone(ZoneInfo("UTC"))
        end_utc = end_dt.astimezone(ZoneInfo("UTC"))

        # Get workflow runs from database (optimized - only required fields)
        runs = await db_client.get_workflow_runs_for_daily_report(
            organization_id=organization_id,
            start_utc=start_utc,
            end_utc=end_utc,
            workflow_id=workflow_id,
        )

        # Format runs for CSV export
        detailed_runs = []
        for run in runs:
            # Phone number is already extracted at the database level
            # Try customer_phone_number first, then fall back to initial_context
            phone_number = run["gathered_context"].get(
                "customer_phone_number", ""
            ) or run["initial_context"].get("phone_number", "")

            # Disposition is already extracted at the database level
            disposition = run["gathered_context"].get("mapped_call_disposition", "")

            # Duration is already extracted at the database level
            duration_seconds = 0
            duration_str = run["usage_info"].get("call_duration_seconds", "0")
            try:
                duration_seconds = float(duration_str)
            except (ValueError, TypeError):
                duration_seconds = 0

            detailed_runs.append(
                {
                    "phone_number": phone_number,
                    "disposition": disposition,
                    "duration_seconds": duration_seconds,
                    "workflow_id": run["workflow_id"],
                    "run_id": run["id"],
                    "workflow_name": run["workflow_name"],
                    "created_at": run["created_at"].isoformat(),
                }
            )

        return detailed_runs
