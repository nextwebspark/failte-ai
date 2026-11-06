import Link from "next/link";

import { StatusPill, type StatusTone } from "@/components/ui/status-pill";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { AdminRun } from "@/lib/platformAdminApi";

import { formatSeconds, formatWhen } from "./format";

/** All runs, filtered to one run (the filter format of lib/filters.ts). */
function runHref(runId: number): string {
    const filters = JSON.stringify([{ id: "runId", value: { value: runId } }]);
    return `/superadmin/runs?${new URLSearchParams({ filters }).toString()}`;
}

const FAILED = new Set(["failed", "error", "pipeline_error", "unexpected_error"]);

function stateTone(run: AdminRun): StatusTone {
    if (run.call_status && FAILED.has(run.call_status)) return "bad";
    if (run.state === "running") return "live";
    if (run.state === "initialized") return "warn";
    return "mute";
}

/** Calls across workspaces; each row links to the run in All runs. */
export function RunsTable({ runs, showOrganization = false }: { runs: AdminRun[]; showOrganization?: boolean }) {
    if (runs.length === 0) return <p className="text-sm text-ink-3">No calls.</p>;
    return (
        <Table>
            <TableHeader>
                <TableRow>
                    <TableHead>Run</TableHead>
                    {showOrganization ? <TableHead>Workspace</TableHead> : null}
                    <TableHead>Agent</TableHead>
                    <TableHead>Channel</TableHead>
                    <TableHead>State</TableHead>
                    <TableHead>Outcome</TableHead>
                    <TableHead>Length</TableHead>
                    <TableHead>Started</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {runs.map((run) => (
                    <TableRow key={run.id}>
                        <TableCell className="font-mono text-xs">
                            <Link className="underline-offset-2 hover:underline" href={runHref(run.id)}>
                                #{run.id}
                            </Link>
                        </TableCell>
                        {showOrganization ? (
                            <TableCell>
                                {run.organization_id ? (
                                    <Link className="hover:underline" href={`/superadmin/organizations/${run.organization_id}`}>
                                        {run.organization_name || `#${run.organization_id}`}
                                    </Link>
                                ) : "—"}
                            </TableCell>
                        ) : null}
                        <TableCell>{run.workflow_name || `#${run.workflow_id}`}</TableCell>
                        <TableCell className="font-mono text-xs">{run.mode}{run.call_type ? ` · ${run.call_type}` : ""}</TableCell>
                        <TableCell><StatusPill tone={stateTone(run)}>{run.state}</StatusPill></TableCell>
                        <TableCell className="font-mono text-xs">{run.call_status || "—"}</TableCell>
                        <TableCell className="tabular-nums">{formatSeconds(run.duration_seconds)}</TableCell>
                        <TableCell className="whitespace-nowrap text-xs">{formatWhen(run.created_at)}</TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    );
}
