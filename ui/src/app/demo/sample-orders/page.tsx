"use client";

import { Package } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { SectionError, SectionMessage } from "@/app/workflow/[workflowId]/components/SectionStates";
import { listSampleOrdersApiV1DemoSampleOrdersGet } from "@/client/sdk.gen";
import type { SampleOrdersView } from "@/client/types.gen";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth";

import { orderRows } from "./sampleOrders";

const COLUMNS = ["Order", "Customer", "Delivering to", "Items", "Total", "Status", "Courier · tracking", "Test email / mobile"];

/**
 * "Sample orders (demo)": the made-up orders a demo workspace's order lookup
 * reads, so a presenter can pick one for a test call. Read-only, and shown
 * only to the owner or an admin of a demo workspace (the API answers
 * `available: false` to everyone else).
 */
export default function SampleOrdersPage() {
    const auth = useAuth();
    const [view, setView] = useState<SampleOrdersView | null>(null);
    const [error, setError] = useState(false);

    const load = useCallback(async () => {
        if (!auth.isAuthenticated) return;
        setError(false);
        try {
            const res = await listSampleOrdersApiV1DemoSampleOrdersGet();
            if (res.error || !res.data) setError(true);
            else setView(res.data);
        } catch {
            setError(true);
        }
    }, [auth.isAuthenticated]);

    useEffect(() => {
        void load();
    }, [load]);

    return (
        <div className="mx-auto w-full max-w-6xl px-4 py-6">
            <PageHeader
                title="Sample orders (demo)"
                description="Made-up orders the agent's order lookup reads in this demo workspace. On a test call, give an order number and its test email or mobile. Live, the lookup reads your shop's own orders."
            />
            {error ? (
                <SectionError title="We couldn't load the sample orders" onRetry={() => void load()} />
            ) : !view ? (
                <div className="flex flex-col gap-2" aria-busy="true" aria-label="Loading sample orders">
                    {[0, 1, 2, 3].map((i) => (
                        <Skeleton key={i} className="h-10 w-full" />
                    ))}
                </div>
            ) : !view.available ? (
                <SectionMessage icon={<Package />} title="No sample orders here.">
                    Sample orders exist only in demo workspaces, for their owner.
                </SectionMessage>
            ) : (
                <>
                    {view.note ? (
                        <p className="mb-4 rounded-xl border border-line bg-surface-2 px-4 py-3 text-caption text-ink-2">{view.note}</p>
                    ) : null}
                    <div className="overflow-x-auto rounded-2xl border border-line">
                        <table className="w-full min-w-[960px] text-left text-caption">
                            <thead className="bg-surface-2 text-ink-3">
                                <tr>
                                    {COLUMNS.map((h) => (
                                        <th key={h} scope="col" className="px-3 py-2 font-semibold">
                                            {h}
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-line-soft">
                                {orderRows(view.orders ?? []).map((o) => (
                                    <tr key={o.number} className="align-top">
                                        <td className="whitespace-nowrap px-3 py-2 font-mono text-foreground">{o.number}</td>
                                        <td className="px-3 py-2 text-foreground">
                                            {o.customer}
                                            <span className="block text-ink-3">ordered {o.ordered}</span>
                                        </td>
                                        <td className="px-3 py-2">{o.town}</td>
                                        <td className="px-3 py-2">
                                            <ul>
                                                {o.items.map((i) => (
                                                    <li key={i}>{i}</li>
                                                ))}
                                            </ul>
                                        </td>
                                        <td className="whitespace-nowrap px-3 py-2 tabular-nums">{o.total}</td>
                                        <td className="px-3 py-2 text-foreground">
                                            {o.status}
                                            <span className="block text-ink-3">{o.statusDate}</span>
                                        </td>
                                        <td className="whitespace-nowrap px-3 py-2">{o.tracking}</td>
                                        <td className="px-3 py-2 font-mono text-ink-2">
                                            {o.email}
                                            <span className="block">{o.mobile}</span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </>
            )}
        </div>
    );
}
