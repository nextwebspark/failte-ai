"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { AdminError, AdminLoading } from "@/components/platform-admin/AdminStates";
import { AUDIT_ACTION_LABELS, formatWhen } from "@/components/platform-admin/format";
import { Pager } from "@/components/platform-admin/Pager";
import { useAdminData } from "@/components/platform-admin/useAdminData";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { platformAdminApi } from "@/lib/platformAdminApi";

const LIMIT = 50;
const ACTION_FILTERS = [
    { value: "all", label: "Every change" },
    { value: "feature.", label: "Feature switches" },
    { value: "billing.", label: "Billing" },
    { value: "organization.", label: "Workspace limits" },
    { value: "user.", label: "Admin grants and impersonation" },
];

function describe(details: Record<string, unknown>): string {
    const parts: string[] = [];
    if (typeof details.feature === "string") parts.push(details.feature);
    if ("before" in details || "after" in details) {
        const show = (value: unknown) => (value === null || value === undefined ? "default" : typeof value === "object" ? JSON.stringify(value) : String(value));
        parts.push(`${show(details.before)} → ${show(details.after)}`);
    }
    if (details.amount_eur !== undefined) parts.push(`${String(details.entry_type ?? "")} €${String(details.amount_eur)}`);
    if (typeof details.reason === "string") parts.push(`“${details.reason}”`);
    return parts.join(" · ") || "—";
}

/** Platform admin > Audit log: every change made in this area. */
export default function PlatformAdminAuditPage() {
    const searchParams = useSearchParams();
    const organizationParam = searchParams.get("organization_id");
    const organizationId = organizationParam && /^\d+$/.test(organizationParam) ? Number(organizationParam) : undefined;
    const [action, setAction] = useState("all");
    const [page, setPage] = useState(1);
    const { data, error, loading } = useAdminData(
        () =>
            platformAdminApi.auditLog({
                organization_id: organizationId,
                action: action === "all" ? undefined : action,
                page,
                limit: LIMIT,
            }),
        [organizationId, action, page],
    );

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
                <div className="w-72">
                    <Select
                        value={action}
                        onValueChange={(value) => {
                            setPage(1);
                            setAction(value);
                        }}
                    >
                        <SelectTrigger aria-label="Kind of change">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {ACTION_FILTERS.map((filter) => (
                                <SelectItem key={filter.value} value={filter.value}>
                                    {filter.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>
                {organizationId !== undefined ? (
                    <span className="text-xs text-ink-3">
                        Workspace #{organizationId} only ·{" "}
                        <Link className="hover:underline" href="/superadmin/audit">
                            show all
                        </Link>
                    </span>
                ) : null}
            </div>
            {error ? <AdminError message={error} /> : null}
            {!data && loading ? <AdminLoading /> : null}
            {data ? (
                <>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>When</TableHead>
                                <TableHead>Who</TableHead>
                                <TableHead>What</TableHead>
                                <TableHead>Workspace or user</TableHead>
                                <TableHead>Change</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {data.entries.map((entry) => (
                                <TableRow key={entry.id}>
                                    <TableCell className="whitespace-nowrap text-xs">{formatWhen(entry.created_at)}</TableCell>
                                    <TableCell className="text-xs">{entry.actor_email ?? (entry.actor_user_id ? `User #${entry.actor_user_id}` : "Deleted user")}</TableCell>
                                    <TableCell className="text-xs">{AUDIT_ACTION_LABELS[entry.action] ?? entry.action}</TableCell>
                                    <TableCell className="text-xs">
                                        {entry.organization_id ? (
                                            <Link className="hover:underline" href={`/superadmin/organizations/${entry.organization_id}`}>
                                                {entry.organization_name || `Workspace #${entry.organization_id}`}
                                            </Link>
                                        ) : entry.target_user_id ? (
                                            entry.target_user_email ?? `User #${entry.target_user_id}`
                                        ) : (
                                            "All workspaces"
                                        )}
                                    </TableCell>
                                    <TableCell className="break-words text-xs">{describe(entry.details)}</TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                    {data.entries.length === 0 ? <p className="text-sm text-ink-3">No changes recorded.</p> : null}
                    <Pager page={page} limit={LIMIT} total={data.total} onPage={setPage} />
                </>
            ) : null}
        </div>
    );
}
