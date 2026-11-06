"use client";

import { AdminError, AdminLoading, StatTile } from "@/components/platform-admin/AdminStates";
import { formatEur, formatWhen } from "@/components/platform-admin/format";
import { useAdminData } from "@/components/platform-admin/useAdminData";
import { SectionHeading } from "@/components/ui/section-heading";
import { platformAdminApi } from "@/lib/platformAdminApi";

/** Platform admin > Overview: sign-ups, active workspaces, calls, revenue. */
export default function PlatformAdminOverviewPage() {
    const { data, error, loading } = useAdminData(platformAdminApi.overview);

    if (error) return <AdminError message={error} />;
    if (loading && !data) return <AdminLoading />;
    if (!data) return null;
    const revenue = data.revenue;

    return (
        <div className="space-y-6">
            <section className="space-y-3">
                <SectionHeading action={<span className="font-mono text-xs text-ink-3">as of {formatWhen(data.generated_at)}</span>}>
                    People and workspaces
                </SectionHeading>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                    <StatTile label="Users" value={data.users_total} hint={`${data.users_new_month} new this month`} />
                    <StatTile label="Sign-ups, 7 days" value={data.users_new_7d} hint={`${data.users_new_30d} in 30 days`} />
                    <StatTile label="Workspaces" value={data.organizations_total} hint={`${data.organizations_new_month} new this month`} />
                    <StatTile
                        label="Active workspaces"
                        value={data.active_organizations_7d}
                        hint={`made a call in 7 days; ${data.active_organizations_30d} in 30 days`}
                    />
                </div>
            </section>

            <section className="space-y-3">
                <SectionHeading>Calls</SectionHeading>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                    <StatTile label="Calls, 7 days" value={data.calls_7d} />
                    <StatTile label="Calls this month" value={data.calls_month} />
                    <StatTile label="Minutes this month" value={data.minutes_month.toLocaleString("en-IE")} />
                </div>
                <p className="text-xs text-ink-3">
                    Calls are voice runs of every kind (phone and browser tests); text chats are left out. Months are UTC.
                </p>
            </section>

            <section className="space-y-3">
                <SectionHeading>Revenue, {revenue.month}</SectionHeading>
                {revenue.available ? (
                    <>
                        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                            <StatTile label="Revenue" value={formatEur(revenue.revenue_eur)} hint={`${revenue.charged_calls} charged calls`} />
                            <StatTile label="Provider cost (est.)" value={formatEur(revenue.provider_cost_eur)} />
                            <StatTile
                                label="Margin (est.)"
                                value={formatEur(revenue.margin_eur)}
                                hint={revenue.margin_percent ? `${revenue.margin_percent}%` : "no costed calls yet"}
                            />
                            <StatTile label="Calls without a cost" value={revenue.uncosted_calls} />
                        </div>
                        {revenue.note ? <p className="text-xs text-ink-3">{revenue.note}</p> : null}
                    </>
                ) : (
                    <p className="text-sm text-ink-2">{revenue.note}</p>
                )}
            </section>
        </div>
    );
}
