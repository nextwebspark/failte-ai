"use client";

import { RefreshCw } from "lucide-react";
import Link from "next/link";

import { AdminError, AdminLoading, StatTile } from "@/components/platform-admin/AdminStates";
import { formatWhen } from "@/components/platform-admin/format";
import { RunsTable } from "@/components/platform-admin/RunsTable";
import { useAdminData } from "@/components/platform-admin/useAdminData";
import { Button } from "@/components/ui/button";
import { SectionHeading } from "@/components/ui/section-heading";
import { StatusPill, type StatusTone } from "@/components/ui/status-pill";
import { platformAdminApi } from "@/lib/platformAdminApi";

const CHECK_TONE: Record<string, StatusTone> = { ok: "ok", warning: "warn", problem: "bad" };

/** Platform admin > Health: configuration, failed and stuck calls, broken
 *  integration connections. */
export default function PlatformAdminHealthPage() {
    const { data, error, loading, reload } = useAdminData(platformAdminApi.health);

    if (error) return <AdminError message={error} />;
    if (!data) return <AdminLoading />;

    return (
        <div className="space-y-6">
            <section className="space-y-3">
                <SectionHeading
                    action={
                        <Button variant="outline" size="sm" onClick={() => void reload()} disabled={loading}>
                            <RefreshCw className="h-3.5 w-3.5" />
                            Check again
                        </Button>
                    }
                >
                    Configuration
                </SectionHeading>
                <ul className="divide-y divide-line rounded-lg border border-line">
                    {data.checks.map((check) => (
                        <li key={check.id} className="flex items-start gap-3 px-4 py-2.5">
                            <StatusPill tone={CHECK_TONE[check.status]} className="mt-0.5 w-20 justify-center">
                                {check.status}
                            </StatusPill>
                            <div className="min-w-0">
                                <div className="text-sm font-medium">{check.label}</div>
                                <div className="break-words text-xs text-ink-2">{check.detail}</div>
                            </div>
                        </li>
                    ))}
                </ul>
                <p className="text-xs text-ink-3">
                    Checked {formatWhen(data.generated_at)}, on the API server that answered.
                </p>
            </section>

            <section className="space-y-3">
                <SectionHeading>Calls, last 24 hours</SectionHeading>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                    <StatTile
                        label="Failed calls"
                        value={data.failed_calls_24h}
                        hint="telephony failures and pipeline errors"
                    />
                    <StatTile
                        label="Stuck runs"
                        value={data.stuck_runs_24h}
                        hint="still starting or running after 1 hour"
                    />
                </div>
                {data.stuck_runs.length > 0 ? (
                    <>
                        <p className="text-xs text-ink-3">
                            Newest {data.stuck_runs.length} stuck runs. A run left in initialized usually means the call
                            never connected; one left running usually means the worker stopped before it finished.
                        </p>
                        <RunsTable runs={data.stuck_runs} showOrganization />
                    </>
                ) : null}
            </section>

            <section className="space-y-3">
                <SectionHeading>Integration connections</SectionHeading>
                {!data.connections.checked ? (
                    <p className="text-sm text-ink-2">{data.connections.note ?? "Not checked."}</p>
                ) : data.connections.problems.length === 0 ? (
                    <p className="text-sm text-ink-2">
                        No connection in error across {data.connections.organizations_checked} workspace(s) with
                        integrations.
                    </p>
                ) : (
                    <ul className="divide-y divide-line rounded-lg border border-line">
                        {data.connections.problems.map((problem) => (
                            <li key={problem.connection_id} className="px-4 py-2.5 text-sm">
                                <Link
                                    className="font-medium hover:underline"
                                    href={`/superadmin/organizations/${problem.organization_id}`}
                                >
                                    {problem.organization_name || `Workspace #${problem.organization_id}`}
                                </Link>
                                <span className="text-ink-3">
                                    {" "}
                                    · {problem.provider}
                                    {problem.account_label ? ` (${problem.account_label})` : ""}
                                </span>
                                <div className="text-xs text-danger">
                                    {problem.last_error || "In error"}
                                    {problem.error_code ? ` [${problem.error_code}]` : ""}
                                </div>
                            </li>
                        ))}
                    </ul>
                )}
                {data.connections.checked && data.connections.note ? (
                    <p className="text-xs text-ink-3">{data.connections.note}</p>
                ) : null}
            </section>
        </div>
    );
}
