"""Revenue against estimated provider cost, per organization and month."""

import csv
import io
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from api.db import db_client


@dataclass(slots=True)
class OrganizationMargin:
    organization_id: int
    organization_name: str | None
    calls: int = 0
    billed_seconds: int = 0
    revenue_eur: Decimal = field(default_factory=lambda: Decimal(0))
    # Revenue and cost of the calls whose provider cost could be estimated, so
    # the margin compares like with like.
    costed_revenue_eur: Decimal = field(default_factory=lambda: Decimal(0))
    provider_cost_eur: Decimal = field(default_factory=lambda: Decimal(0))
    uncosted_calls: int = 0

    @property
    def margin_eur(self) -> Decimal:
        return self.costed_revenue_eur - self.provider_cost_eur

    @property
    def margin_percent(self) -> Decimal | None:
        if self.costed_revenue_eur <= 0:
            return None
        return (self.margin_eur / self.costed_revenue_eur * 100).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )


def month_bounds(month: str) -> tuple[datetime, datetime]:
    """``"2026-10"`` -> [2026-10-01, 2026-11-01) in UTC."""
    start = datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


async def monthly_margins(month: str) -> list[OrganizationMargin]:
    start, end = month_bounds(month)
    margins: dict[int, OrganizationMargin] = {}
    for run in await db_client.list_charged_runs(start=start, end=end):
        margin = margins.setdefault(
            run.organization_id,
            OrganizationMargin(run.organization_id, run.organization_name),
        )
        margin.calls += 1
        margin.billed_seconds += int(run.cost_info.get("billed_seconds") or 0)
        margin.revenue_eur += run.charged_eur
        provider_cost = run.cost_info.get("provider_cost_eur")
        if provider_cost is None:
            margin.uncosted_calls += 1
        else:
            margin.costed_revenue_eur += run.charged_eur
            margin.provider_cost_eur += Decimal(provider_cost)
    return sorted(margins.values(), key=lambda m: m.revenue_eur, reverse=True)


def margins_csv(margins: list[OrganizationMargin]) -> io.StringIO:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Organization ID",
            "Organization",
            "Calls",
            "Billed minutes",
            "Revenue (EUR)",
            "Provider cost (EUR)",
            "Margin (EUR)",
            "Margin (%)",
            "Calls without cost estimate",
        ]
    )
    for m in margins:
        writer.writerow(
            [
                m.organization_id,
                m.organization_name or "",
                m.calls,
                f"{m.billed_seconds / 60:.1f}",
                f"{m.revenue_eur:.4f}",
                f"{m.provider_cost_eur:.4f}",
                f"{m.margin_eur:.4f}",
                "" if m.margin_percent is None else str(m.margin_percent),
                m.uncosted_calls,
            ]
        )
    output.seek(0)
    return output
