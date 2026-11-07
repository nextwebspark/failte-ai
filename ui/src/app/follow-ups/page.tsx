"use client";

import { AlertTriangle, CheckCircle2, PhoneIncoming, RefreshCw, Search } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import type { FollowUpItem, FollowUpListResponse } from "@/client/types.gen";
import { AddAnswerDialog } from "@/components/dashboard/AddAnswerDialog";
import { FOLLOW_UP_WORDS, followUpKey, waitWords } from "@/components/dashboard/dashboardView";
import { FollowUpTodo } from "@/components/dashboard/FollowUpRow";
import { useFollowUpMarking, useFollowUps } from "@/components/dashboard/useDashboardData";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useOrganizationTimezone } from "@/hooks/useOrganizationTimezone";
import { cn } from "@/lib/utils";

import { FollowUpsFilterBar, KindChips, StatusTabs } from "./FollowUpsFilters";
import {
    apiFilters,
    DEFAULT_FOLLOW_UPS_QUERY,
    type FollowUpsQuery,
    followUpsQueryFromParams,
    followUpsQueryToParams,
    isNarrowed,
    whenPhrase,
} from "./followUpsQuery";
import { groupByCaller } from "./groups";

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
        <aside aria-labelledby="week-title" className="rounded-xl border border-line bg-panel px-5 py-5">
            <h2 id="week-title" className="font-display text-[16px] font-semibold text-foreground">
                This week
            </h2>
            {data ? (
                <dl className="mt-2">
                    {rows.map((row) => (
                        <div key={row.label} className="flex items-baseline justify-between gap-3 border-b border-line-soft py-3 last:border-b-0">
                            <dt className="text-[14.5px] text-ink-2">{row.label}</dt>
                            <dd className="whitespace-nowrap font-display text-[19px] font-semibold tabular-nums text-foreground">{row.value}</dd>
                        </div>
                    ))}
                </dl>
            ) : (
                <div className="mt-3 space-y-2.5">
                    <Skeleton className="h-5 w-full" />
                    <Skeleton className="h-5 w-full" />
                </div>
            )}
            <p className="mt-2 text-[13px] text-ink-3">Counted from your calls in the last 7 days, whatever the filters.</p>
        </aside>
    );
}

function ListSkeleton() {
    return (
        <div role="status" aria-label="Loading" className="flex flex-col divide-y divide-line-soft">
            {Array.from({ length: 3 }, (_, i) => (
                <div key={i} className="flex gap-4 px-5 py-4">
                    <Skeleton className="size-7 rounded-full" />
                    <div className="flex-1 space-y-2">
                        <Skeleton className="h-4 w-1/3" />
                        <Skeleton className="h-3.5 w-2/3" />
                        <Skeleton className="h-3 w-1/4" />
                    </div>
                </div>
            ))}
        </div>
    );
}

/** "Showing 2 of 5 open follow-ups": said only when the filters hide some. */
function MatchLine({ data, query }: { data: FollowUpListResponse; query: FollowUpsQuery }) {
    if (!isNarrowed(query)) return null;
    const shown = data.items.length;
    const what = query.status === "open" ? "open " : query.status === "done" ? "done " : "";
    const filters = [
        query.kind ? FOLLOW_UP_WORDS[query.kind].filter : null,
        query.q.trim() ? `matching “${query.q.trim()}”` : null,
    ].filter(Boolean);
    return (
        <p className="border-t border-line-soft px-5 py-2.5 text-[13px] text-ink-3" role="status">
            {shown.toLocaleString("en-IE")} {what}
            {shown === 1 ? "follow-up" : "follow-ups"} {whenPhrase(query)}
            {filters.map((f) => ` · ${f}`).join("")}
            {query.status === "open" && data.open_total !== shown && (
                <> · {data.open_total.toLocaleString("en-IE")} open in all</>
            )}
        </p>
    );
}

export default function FollowUpsPage() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const { can } = useOrgConfig();
    const timezone = useOrganizationTimezone();

    // The URL holds the controls, so refresh, Back and a shared link keep them.
    const paramsKey = searchParams.toString();
    const query = useMemo(() => followUpsQueryFromParams(new URLSearchParams(paramsKey)), [paramsKey]);
    const filters = useMemo(() => apiFilters(query), [query]);

    const [answering, setAnswering] = useState<FollowUpItem | null>(null);
    const { result, updating, reload } = useFollowUps(query.status, undefined, filters);
    const { busy, change } = useFollowUpMarking();
    const canMark = can("followups:manage");
    const canAnswer = can("agents:facts") && canMark;
    const now = new Date();

    const navigate = useCallback(
        (next: Partial<FollowUpsQuery>, options: { replace?: boolean } = {}) => {
            const params = followUpsQueryToParams({ ...query, ...next });
            const href = `/follow-ups${params.toString() ? `?${params}` : ""}`;
            if (options.replace) router.replace(href, { scroll: false });
            else router.push(href, { scroll: false });
        },
        [query, router],
    );
    const clearFilters = () => navigate({ ...DEFAULT_FOLLOW_UPS_QUERY, status: query.status });

    const data: FollowUpListResponse | null = result.state === "ready" ? result.data : null;
    // The list for another tab is still on screen while this one loads.
    const current = data && data.status === query.status ? data : null;
    const groups = groupByCaller(current?.items ?? []);
    const narrowed = isNarrowed(query);

    const empty = (list: FollowUpListResponse) =>
        !list.has_calls ? (
            <EmptyState
                icon={PhoneIncoming}
                title="No calls yet"
                description="Callers who need a person show up here: callback requests, transfers nobody answered and questions your agent couldn't answer. Try your agent or link a phone number to get your first calls."
                action={
                    <Button asChild variant="soft">
                        <Link href="/overview">Go to Home</Link>
                    </Button>
                }
            />
        ) : narrowed ? (
            <EmptyState
                icon={Search}
                title="Nothing matches"
                description={`No ${query.status === "open" ? "open " : query.status === "done" ? "done " : ""}follow-ups ${query.q.trim() ? `for “${query.q.trim()}” ` : ""}${whenPhrase(query)}${query.kind ? ` of this kind` : ""}.`}
                action={
                    <Button variant="outline" onClick={clearFilters}>
                        Clear filters
                    </Button>
                }
            />
        ) : query.status === "done" ? (
            <EmptyState
                icon={CheckCircle2}
                title="Nothing marked done yet"
                description="Follow-ups you mark done in the last 30 days show here, with who sorted them."
            />
        ) : (
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
        );

    return (
        <div className="page-body">
            <PageHeader
                title="Follow-ups"
                description="Calls that need a person. Ring them back, then mark each one done."
            />
            <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[minmax(0,1fr)_320px] 2xl:grid-cols-[minmax(0,1fr)_360px]">
                <section aria-label="Follow-ups list" className="min-w-0 overflow-hidden rounded-xl border border-line bg-panel">
                    <div className="border-b border-line-soft pt-1">
                        <StatusTabs status={query.status} data={data} onChange={(status) => navigate({ status })} />
                    </div>
                    <FollowUpsFilterBar query={query} onChange={navigate} />
                    {current && (
                        <KindChips value={query.kind} counts={current.kind_counts} onChange={(kind) => navigate({ kind })} />
                    )}
                    {result.state === "error" ? (
                        <div className="border-t border-line-soft">
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
                        </div>
                    ) : !current ? (
                        <div className="border-t border-line-soft">
                            <ListSkeleton />
                        </div>
                    ) : (
                        <div aria-busy={updating} className={cn("border-t border-line-soft transition-opacity", updating && "opacity-60")}>
                            {current.items.length === 0 ? (
                                empty(current)
                            ) : (
                                <div className="@container">
                                    {groups.map((group) => (
                                        <div key={group.id} className="border-t border-line-soft first:border-t-0">
                                            {group.items.length > 1 && (
                                                <p className="px-5 pt-3.5 text-[12px] font-semibold uppercase tracking-[0.06em] text-ink-3">
                                                    {group.label} · {group.items.length} follow-ups
                                                </p>
                                            )}
                                            <ul className="flex flex-col divide-y divide-line-soft">
                                                {group.items.map((item) => (
                                                    <FollowUpTodo
                                                        key={followUpKey(item)}
                                                        item={item}
                                                        timezone={timezone}
                                                        now={now}
                                                        returnTo={`/follow-ups${paramsKey ? `?${paramsKey}` : ""}`}
                                                        busy={busy === followUpKey(item)}
                                                        onMarkDone={canMark ? (i) => void change(i, true) : undefined}
                                                        onUndo={canMark ? (i) => void change(i, false) : undefined}
                                                        onAddAnswer={canAnswer ? setAnswering : undefined}
                                                    />
                                                ))}
                                            </ul>
                                        </div>
                                    ))}
                                </div>
                            )}
                            <MatchLine data={current} query={query} />
                        </div>
                    )}
                </section>
                <WeekPanel data={data} />
            </div>
            <AddAnswerDialog item={answering} onClose={() => setAnswering(null)} />
        </div>
    );
}
