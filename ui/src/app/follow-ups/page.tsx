"use client";

import { AlertTriangle, CheckCircle2, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import {
    markFollowUpDoneApiV1FollowUpsRunIdDonePost,
    undoFollowUpDoneApiV1FollowUpsRunIdDoneDelete,
} from "@/client/sdk.gen";
import type { FollowUpItem, FollowUpKind, FollowUpListResponse, FollowUpStatus } from "@/client/types.gen";
import { FOLLOW_UP_KINDS, FOLLOW_UP_WORDS, waitWords } from "@/components/dashboard/dashboardView";
import { FollowUpRow } from "@/components/dashboard/FollowUpRow";
import { notifyFollowUpsChanged, useFollowUps } from "@/components/dashboard/useDashboardData";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useOrganizationTimezone } from "@/hooks/useOrganizationTimezone";
import { cn } from "@/lib/utils";

import { groupByCaller } from "./groups";

type KindFilter = "all" | FollowUpKind;

function Tabs({
    status,
    onChange,
    data,
}: {
    status: FollowUpStatus;
    onChange: (s: FollowUpStatus) => void;
    data: FollowUpListResponse | null;
}) {
    const tabs: { value: FollowUpStatus; label: string; count: number | null }[] = [
        { value: "open", label: "To do", count: data?.open_count ?? null },
        { value: "done", label: "Done", count: data?.done_count ?? null },
    ];
    return (
        <div role="tablist" aria-label="Follow-ups" className="flex gap-1 border-b border-line px-[18px]">
            {tabs.map((tab) => (
                <button
                    key={tab.value}
                    type="button"
                    role="tab"
                    aria-selected={status === tab.value}
                    onClick={() => onChange(tab.value)}
                    className={cn(
                        "-mb-px border-b-2 px-3 py-3 text-[14px] font-semibold outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/40",
                        status === tab.value
                            ? "border-brand text-foreground"
                            : "border-transparent text-ink-3 hover:text-foreground",
                    )}
                >
                    {tab.label}
                    {tab.count != null && <span className="ml-1.5 font-medium tabular-nums text-ink-3">{tab.count}</span>}
                </button>
            ))}
        </div>
    );
}

function KindChips({
    value,
    onChange,
    counts,
    total,
}: {
    value: KindFilter;
    onChange: (k: KindFilter) => void;
    counts: Record<string, number>;
    total: number;
}) {
    const options: { value: KindFilter; label: string; count: number }[] = [
        { value: "all", label: "All", count: total },
        ...FOLLOW_UP_KINDS.map((kind) => ({ value: kind, label: FOLLOW_UP_WORDS[kind].filter, count: counts[kind] ?? 0 })),
    ];
    return (
        <div role="group" aria-label="Show" className="flex flex-wrap gap-2 border-b border-line-soft px-[18px] py-3">
            {options.map((option) => (
                <button
                    key={option.value}
                    type="button"
                    aria-pressed={value === option.value}
                    onClick={() => onChange(option.value)}
                    disabled={option.value !== "all" && option.count === 0}
                    className={cn(
                        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[13px] font-medium outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/40 disabled:opacity-50",
                        value === option.value
                            ? "border-brand bg-brand-dim text-brand"
                            : "border-line bg-panel text-ink-2 hover:border-ink-3 hover:text-foreground",
                    )}
                >
                    {option.label}
                    <span className="font-semibold tabular-nums">{option.count}</span>
                </button>
            ))}
        </div>
    );
}

function WeekPanel({ data }: { data: FollowUpListResponse | null }) {
    const rows: { label: string; value: string }[] = data
        ? [
              { label: "Follow-ups raised", value: String(data.week.raised) },
              { label: "Sorted", value: String(data.week.sorted) },
              ...(data.week.median_wait_minutes != null
                  ? [{ label: "Usual wait before it's sorted", value: waitWords(data.week.median_wait_minutes) }]
                  : []),
          ]
        : [];
    return (
        <aside aria-labelledby="week-title" className="rounded-[14px] border border-line bg-panel px-[18px] py-4 shadow-xs">
            <h2 id="week-title" className="font-display text-[15px] font-semibold text-foreground">
                This week
            </h2>
            {data ? (
                <dl className="mt-2">
                    {rows.map((row) => (
                        <div key={row.label} className="flex items-center justify-between gap-3 border-b border-line-soft py-2.5 last:border-b-0">
                            <dt className="text-[13.5px] text-ink-2">{row.label}</dt>
                            <dd className="font-semibold tabular-nums text-foreground">{row.value}</dd>
                        </div>
                    ))}
                </dl>
            ) : (
                <div className="mt-3 space-y-2.5">
                    <Skeleton className="h-4 w-full" />
                    <Skeleton className="h-4 w-full" />
                </div>
            )}
            <p className="mt-2 text-[12px] text-ink-3">Counted from your calls in the last 7 days.</p>
        </aside>
    );
}

function ListSkeleton() {
    return (
        <div role="status" aria-label="Loading" className="flex flex-col gap-4 px-[18px] py-4">
            {Array.from({ length: 3 }, (_, i) => (
                <div key={i} className="flex gap-3">
                    <Skeleton className="h-14 w-1 rounded" />
                    <div className="flex-1 space-y-2">
                        <Skeleton className="h-4 w-1/3" />
                        <Skeleton className="h-3 w-2/3" />
                        <Skeleton className="h-3 w-1/4" />
                    </div>
                </div>
            ))}
        </div>
    );
}

export default function FollowUpsPage() {
    const { can } = useOrgConfig();
    const timezone = useOrganizationTimezone();
    const [status, setStatus] = useState<FollowUpStatus>("open");
    const [kind, setKind] = useState<KindFilter>("all");
    const [busy, setBusy] = useState<number | null>(null);
    const { result, reload } = useFollowUps(status);
    const canMark = can("followups:manage");
    const now = new Date();

    const data = result.state === "ready" ? result.data : null;
    const items = (data?.items ?? []).filter((item) => kind === "all" || item.kind === kind);
    const groups = groupByCaller(items);

    const change = async (item: FollowUpItem, done: boolean) => {
        setBusy(item.run_id);
        try {
            const path = { run_id: item.run_id };
            const res = done
                ? await markFollowUpDoneApiV1FollowUpsRunIdDonePost({ path })
                : await undoFollowUpDoneApiV1FollowUpsRunIdDoneDelete({ path });
            if (res.error) throw new Error("failed");
            notifyFollowUpsChanged();
            if (done) {
                toast.success("Marked done", {
                    action: { label: "Undo", onClick: () => void change(item, false) },
                });
            } else {
                toast.success("Back on the to-do list");
            }
        } catch {
            toast.error("Couldn't save that. Please try again.");
        } finally {
            setBusy(null);
        }
    };

    const switchStatus = (next: FollowUpStatus) => {
        setStatus(next);
        setKind("all");
    };

    return (
        <div className="page-body">
            <PageHeader
                title="Follow-ups"
                description="Calls that need a person. Mark each one done when it's sorted."
            />
            <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
                <section aria-label="Follow-ups list" className="min-w-0 overflow-hidden rounded-[14px] border border-line bg-panel shadow-xs">
                    <Tabs status={status} onChange={switchStatus} data={data} />
                    {result.state === "loading" && <ListSkeleton />}
                    {result.state === "error" && (
                        <EmptyState
                            tone="danger"
                            icon={AlertTriangle}
                            title="We couldn't load your follow-ups"
                            description="Check your connection and try again."
                            action={
                                <Button variant="soft" onClick={reload}>
                                    <RefreshCw aria-hidden />
                                    Try again
                                </Button>
                            }
                        />
                    )}
                    {data && (
                        <>
                            {data.items.length > 0 && (
                                <KindChips value={kind} onChange={setKind} counts={data.kind_counts} total={data.items.length} />
                            )}
                            {data.items.length === 0 ? (
                                status === "open" ? (
                                    <EmptyState
                                        icon={CheckCircle2}
                                        title="All caught up"
                                        description="Nobody is waiting on you. Your agent handled every call that came in."
                                        action={
                                            <Button asChild variant="soft">
                                                <Link href="/usage">See all calls</Link>
                                            </Button>
                                        }
                                    />
                                ) : (
                                    <EmptyState
                                        icon={CheckCircle2}
                                        title="Nothing marked done yet"
                                        description="Follow-ups you mark done in the last 30 days show here, with who sorted them."
                                    />
                                )
                            ) : (
                                <div className="px-[18px] pb-2">
                                    {groups.map((group) => (
                                        <div key={group.id} className="border-t border-line-soft first:border-t-0">
                                            {group.items.length > 1 && (
                                                <p className="pt-3 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">
                                                    {group.label} · {group.items.length} follow-ups
                                                </p>
                                            )}
                                            <ul className="flex flex-col">
                                                {group.items.map((item) => (
                                                    <FollowUpRow
                                                        key={item.run_id}
                                                        item={item}
                                                        timezone={timezone}
                                                        now={now}
                                                        returnTo="/follow-ups"
                                                        meta="waiting"
                                                        busy={busy === item.run_id}
                                                        onMarkDone={canMark ? (i) => void change(i, true) : undefined}
                                                        onUndo={canMark ? (i) => void change(i, false) : undefined}
                                                    />
                                                ))}
                                            </ul>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </>
                    )}
                </section>
                <WeekPanel data={data} />
            </div>
        </div>
    );
}
