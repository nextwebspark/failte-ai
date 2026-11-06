"use client";

import Link from "next/link";
import { useState } from "react";

import { AdminError, AdminLoading } from "@/components/platform-admin/AdminStates";
import { formatEur, formatWhen, PLAN_LABELS } from "@/components/platform-admin/format";
import { OrganizationStatus } from "@/components/platform-admin/OrganizationStatus";
import { Pager } from "@/components/platform-admin/Pager";
import { useAdminData } from "@/components/platform-admin/useAdminData";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { platformAdminApi } from "@/lib/platformAdminApi";

const LIMIT = 50;

/** Platform admin > Organisations: every workspace, searchable by name, id or
 *  a member's email. */
export default function PlatformAdminOrganizationsPage() {
    const [search, setSearch] = useState("");
    const [query, setQuery] = useState("");
    const [page, setPage] = useState(1);
    const { data, error, loading } = useAdminData(
        () => platformAdminApi.organizations({ search: query, page, limit: LIMIT }),
        [query, page],
    );

    return (
        <div className="space-y-4">
            <form
                className="flex max-w-md gap-2"
                onSubmit={(event) => {
                    event.preventDefault();
                    setPage(1);
                    setQuery(search.trim());
                }}
            >
                <Input
                    aria-label="Search workspaces"
                    placeholder="Name, id or a member's email"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                />
            </form>
            {error ? <AdminError message={error} /> : null}
            {!data && loading ? <AdminLoading /> : null}
            {data ? (
                <>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>Workspace</TableHead>
                                <TableHead>Status</TableHead>
                                <TableHead className="text-right">Members</TableHead>
                                <TableHead>Plan</TableHead>
                                <TableHead className="text-right">Balance</TableHead>
                                <TableHead className="text-right">Per minute</TableHead>
                                <TableHead className="text-right">Credit limit</TableHead>
                                <TableHead className="text-right">Calls at once</TableHead>
                                <TableHead>Created</TableHead>
                                <TableHead>Last call</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {data.organizations.map((org) => (
                                <TableRow key={org.id}>
                                    <TableCell>
                                        <Link className="font-medium hover:underline" href={`/superadmin/organizations/${org.id}`}>
                                            {org.name || "Unnamed"}
                                        </Link>
                                        <span className="ml-1.5 font-mono text-[11px] text-ink-3">#{org.id}</span>
                                    </TableCell>
                                    <TableCell>
                                        <OrganizationStatus status={org.status} />
                                    </TableCell>
                                    <TableCell className="text-right tabular-nums">{org.members_count}</TableCell>
                                    <TableCell>{org.plan ? PLAN_LABELS[org.plan] ?? org.plan : "—"}</TableCell>
                                    <TableCell className="text-right tabular-nums">{formatEur(org.balance_eur)}</TableCell>
                                    <TableCell className="text-right tabular-nums">
                                        {formatEur(org.effective_price_per_minute_eur, 2)}
                                        {org.price_per_minute_override_eur !== null ? (
                                            <span className="ml-1 text-[11px] text-ink-3">custom</span>
                                        ) : null}
                                    </TableCell>
                                    <TableCell className="text-right tabular-nums">{formatEur(org.credit_limit_eur)}</TableCell>
                                    <TableCell className="text-right tabular-nums">
                                        {org.effective_concurrency_limit}
                                        {org.concurrency_limit === null ? (
                                            <span className="ml-1 text-[11px] text-ink-3">default</span>
                                        ) : null}
                                    </TableCell>
                                    <TableCell className="whitespace-nowrap text-xs">{formatWhen(org.created_at)}</TableCell>
                                    <TableCell className="whitespace-nowrap text-xs">{formatWhen(org.last_call_at)}</TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                    {data.organizations.length === 0 ? <p className="text-sm text-ink-3">No workspace matches.</p> : null}
                    <p className="text-xs text-ink-3">
                        Plan, balance and credit limit show &ldquo;—&rdquo; for a workspace that has no billing account yet
                        (one is created the first time billing is used).
                    </p>
                    <Pager page={page} limit={LIMIT} total={data.total} onPage={setPage} />
                </>
            ) : null}
        </div>
    );
}
