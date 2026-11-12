"use client";

import { Lightbulb, MessageSquarePlus } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import type { FollowUpKind, ReportCards, ReportOverviewResponse, WaitingCard } from "@/client/types.gen";
import { reasonColours } from "@/components/dashboard/CallersWantedChart";
import { callWhen, FOLLOW_UP_WORDS, waitWords } from "@/components/dashboard/dashboardView";
import { ContactSupportLink } from "@/components/help/ContactSupportLink";
import { cn } from "@/lib/utils";

import {
    changeChip,
    estimateFormula,
    money,
    mostlyWords,
    plural,
    shortDay,
    shortHour,
    tipWords,
    WEEKDAYS,
} from "../reportView";
import { BarRow, Columns, Heatmap, type Series, StackedColumns } from "./charts";

type Report = ReportOverviewResponse;

export type CardContext = {
    report: Report;
    now: Date;
    /** Opens "Add an answer"; undefined when the member can't change answers. */
    onAddAnswer?: (question: { run_id: number; workflow_id: number; question: string }) => void;
};

/** The design's card: white panel, 14px corners, a title and a quiet line under it. */
export function Panel({
    id,
    title,
    subtitle,
    children,
    className,
    badge,
}: {
    id: string;
    title: string;
    subtitle?: ReactNode;
    children: ReactNode;
    className?: string;
    badge?: ReactNode;
}) {
    return (
        <section
            aria-labelledby={`report-${id}`}
            className={cn("min-w-0 rounded-[14px] border border-line bg-panel shadow-xs", className)}
        >
            <header className="flex items-start justify-between gap-3 px-[18px] pt-[18px] sm:px-5">
                <div className="min-w-0">
                    <h2 id={`report-${id}`} className="font-display text-title font-semibold text-foreground">
                        {title}
                    </h2>
                    {subtitle ? <p className="mt-0.5 text-caption text-ink-3">{subtitle}</p> : null}
                </div>
                {badge}
            </header>
            <div className="@container px-[18px] pb-5 pt-4 sm:px-5">{children}</div>
        </section>
    );
}

function EstimateBadge() {
    return (
        <span className="flex-none rounded-full bg-amber-dim px-2 py-0.5 text-meta font-semibold text-amber">
            Estimate
        </span>
    );
}

function Chip({ change, unit }: { change: number | null | undefined; unit?: string }) {
    const chip = changeChip(change, unit);
    if (!chip) return null;
    return (
        <span
            className={cn(
                "inline-flex rounded-full px-2 py-0.5 text-caption font-semibold tabular-nums",
                chip.tone === "up" && "bg-brand-dim text-brand",
                chip.tone === "down" && "bg-panel-2 text-ink-2",
                chip.tone === "same" && "bg-panel-2 text-ink-2",
            )}
        >
            {chip.text}
        </span>
    );
}

/** A headline number. */
function Kpi({
    id,
    title,
    value,
    suffix,
    change,
    changeUnit,
    note,
    estimate,
}: {
    id: string;
    title: string;
    value: string | number;
    suffix?: string;
    change?: number | null;
    changeUnit?: string;
    note?: ReactNode;
    estimate?: boolean;
}) {
    return (
        <section
            aria-labelledby={`report-${id}`}
            className="flex min-w-0 flex-col rounded-[14px] border border-line bg-panel px-[18px] py-[18px] shadow-xs sm:px-5"
        >
            <div className="flex items-start justify-between gap-2">
                <h2 id={`report-${id}`} className="text-body font-medium text-ink-2">
                    {title}
                </h2>
                {estimate ? <EstimateBadge /> : null}
            </div>
            <p className="mt-2 font-display text-[30px] font-semibold leading-none tracking-[-0.02em] tabular-nums text-foreground sm:text-kpi">
                {typeof value === "number" ? value.toLocaleString("en-IE") : value}
                {suffix ? <span className="ml-1.5 text-body font-medium tracking-normal text-ink-2">{suffix}</span> : null}
            </p>
            {change !== undefined ? (
                <div className="mt-3 min-h-6">
                    <Chip change={change} unit={changeUnit} />
                </div>
            ) : null}
            {note ? <p className="mt-2 text-caption text-ink-3">{note}</p> : null}
        </section>
    );
}

function Empty({ children }: { children: ReactNode }) {
    return <p className="rounded-xl bg-panel-2 px-4 py-4 text-body text-ink-2">{children}</p>;
}

function Stat({ value, label }: { value: ReactNode; label: string }) {
    return (
        <div className="min-w-0 rounded-xl bg-panel-2 px-3.5 py-3">
            <div className="font-display text-[24px] font-semibold leading-tight tabular-nums text-foreground">{value}</div>
            <div className="mt-0.5 text-caption text-ink-3">{label}</div>
        </div>
    );
}

function Note({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "brand" | "amber" }) {
    return (
        <p
            className={cn(
                "mt-4 flex items-start gap-2 rounded-xl px-3.5 py-3 text-caption",
                tone === "brand" && "bg-brand-dim text-foreground",
                tone === "amber" && "bg-amber-dim text-foreground",
                tone === "neutral" && "bg-panel-2 text-ink-2",
            )}
        >
            {children}
        </p>
    );
}

function HoursMissing() {
    return (
        <Empty>
            Set your opening hours as times on{" "}
            <Link href="/workflow" className="font-semibold text-brand hover:underline">
                What your agent knows
            </Link>{" "}
            to see the calls that come in while you&apos;re closed.
        </Empty>
    );
}

const reasonSeries = (items: { key: string; label: string }[]): Series[] => {
    const colours = reasonColours(items);
    return items.map((s) => ({ key: s.key, label: s.label, swatch: colours[s.key].swatch }));
};

function WaitingList({ card, ctx, empty }: { card: WaitingCard; ctx: CardContext; empty: string }) {
    if (!card.count) return <Empty>{empty}</Empty>;
    return (
        <>
            <div className="grid grid-cols-2 gap-2">
                <Stat value={card.count} label="waiting" />
                <Stat value={card.oldest_minutes != null ? waitWords(card.oldest_minutes) : "–"} label="longest wait" />
            </div>
            <ul className="mt-3 divide-y divide-line-soft">
                {card.items.map((item) => (
                    <li key={`${item.run_id}-${item.kind}`} className="py-2.5">
                        <Link href={`/follow-ups`} className="block rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
                            <span className="block text-body font-medium text-foreground">
                                {item.caller_name || item.caller_number || "Unknown caller"}
                            </span>
                            <span className="block text-caption text-ink-3">
                                {[item.about, item.area, callWhen(item.created_at, ctx.report.timezone, ctx.now)].filter(Boolean).join(" · ")}
                            </span>
                        </Link>
                    </li>
                ))}
            </ul>
            {card.count > card.items.length ? (
                <Link href="/follow-ups" className="mt-2 inline-block text-caption font-semibold text-brand hover:underline">
                    See all {card.count} in Follow-ups
                </Link>
            ) : null}
        </>
    );
}

/** One card, by key. Null when the pack has no such card or its data doesn't exist. */
export function ReportCard({ cardKey, title, ctx }: { cardKey: string; title: string; ctx: CardContext }): ReactNode {
    const { report } = ctx;
    const cards: ReportCards = report.cards;
    const id = cardKey;
    switch (cardKey) {
        case "calls_answered": {
            const c = cards.calls_answered;
            if (!c) return null;
            return (
                <Kpi
                    id={id}
                    title={title}
                    value={c.calls}
                    change={c.change}
                    note={
                        c.after_hours != null ? `${c.after_hours.toLocaleString("en-IE")} came in while you were closed` : undefined
                    }
                />
            );
        }
        case "bookings_taken":
        case "appointments_booked": {
            const c = cards[cardKey];
            if (!c) return null;
            return (
                <Kpi
                    id={id}
                    title={title}
                    value={c.count}
                    change={c.change}
                    note={c.percent_of_calls != null ? `${c.percent_of_calls}% of calls ended in a booking` : undefined}
                />
            );
        }
        case "covers_booked": {
            const c = cards.covers_booked;
            if (!c) return null;
            const apart = c.not_given + c.unreadable;
            return (
                <Kpi
                    id={id}
                    title={title}
                    value={c.covers}
                    change={c.change}
                    note={
                        <>
                            {c.average_party != null ? `Average table of ${c.average_party}` : "No party sizes yet"}
                            {apart ? `. ${plural(apart, "booking")} without a clear party size, not counted` : ""}
                        </>
                    }
                />
            );
        }
        case "tables_full": {
            const c = cards.tables_full;
            if (!c) return null;
            return (
                <Kpi
                    id={id}
                    title={title}
                    value={c.count}
                    suffix={c.covers ? `· ${plural(c.covers, "cover")}` : undefined}
                    change={c.change}
                    note={mostlyWords(c.mostly_days, c.mostly_hour) ?? (c.count ? undefined : "Nobody was turned away")}
                />
            );
        }
        case "takeaway":
        case "emergencies":
        case "changes":
        case "jobs_quotes": {
            const c = cards[cardKey];
            if (!c) return null;
            const notes: Record<string, string> = {
                takeaway: `${plural(c.needed_person, "order")} passed to your team`,
                emergencies: `${c.passed_to_team} put through, ${c.callbacks} left a number`,
                changes: c.booked ? `${c.booked} done by your agent` : `${c.needed_person} waiting for your team`,
                jobs_quotes: `${c.callbacks} left a number for a call back`,
            };
            return <Kpi id={id} title={title} value={c.count} change={c.change} note={c.count ? notes[cardKey] : undefined} />;
        }
        case "product_enquiries":
        case "orders_delivery":
        case "returns":
        case "servicing_requests": {
            const c = cards[cardKey];
            if (!c) return null;
            const parts = [
                c.handled ? `${c.handled} answered by your agent` : null,
                c.needed_person ? `${c.needed_person} needed your team` : null,
            ].filter(Boolean);
            return (
                <Kpi id={id} title={title} value={c.count} change={c.change} note={c.count && parts.length ? parts.join(", ") : undefined} />
            );
        }
        case "after_hours_callouts": {
            const c = cards.after_hours_callouts;
            if (!c) return null;
            if (!c.hours_set) return <Kpi id={id} title={title} value="–" note="Set your opening hours as times to count these" />;
            return (
                <Kpi
                    id={id}
                    title={title}
                    value={c.count ?? 0}
                    change={c.change}
                    note={c.count ? `${c.passed_to_team} put through, ${c.callbacks} left a number` : "No urgent calls while closed"}
                />
            );
        }
        case "sorted_by_agent":
        case "passed_on": {
            const c = cards[cardKey];
            if (!c) return null;
            return (
                <Kpi
                    id={id}
                    title={title}
                    value={c.count}
                    change={c.change}
                    note={c.percent != null ? `${c.percent}% of calls` : undefined}
                />
            );
        }
        case "bookings_value":
        case "appointments_value":
        case "jobs_value": {
            const c = cards[cardKey];
            if (!c) return null;
            return (
                <Kpi
                    id={id}
                    title={title}
                    value={money(c.value)}
                    estimate
                    note={`Estimate: ${estimateFormula(c.units, c.unit, c.average)}`}
                />
            );
        }
        case "callers_wanted": {
            const c = cards.callers_wanted;
            if (!c) return null;
            const series = reasonSeries(c.series);
            const hourly = c.unit === "hour";
            return (
                <Panel
                    id={id}
                    title={hourly ? "What callers wanted, hour by hour" : title}
                    subtitle={hourly ? "Calls per hour, by reason" : "Calls per day, by reason"}
                >
                    {series.length ? (
                        <StackedColumns
                            series={series}
                            caption={hourly ? "Calls per hour, by reason" : "Calls per day, by reason"}
                            columns={c.buckets.map((b) => {
                                const label = hourly ? `${shortHour(b.hour ?? 0)}–${shortHour((b.hour ?? 0) + 1)}` : shortDay(b.date ?? "");
                                return {
                                    key: hourly ? String(b.hour) : (b.date ?? ""),
                                    label,
                                    tick: hourly ? shortHour(b.hour ?? 0) : shortDay(b.date ?? ""),
                                    counts: b.counts,
                                    total: b.total,
                                };
                            })}
                        />
                    ) : (
                        <Empty>No calls in this period yet. What callers wanted shows here once your agent takes some.</Empty>
                    )}
                </Panel>
            );
        }
        case "busiest_times": {
            const c = cards.busiest_times;
            if (!c) return null;
            const days = Math.round((new Date(report.end).getTime() - new Date(report.start).getTime()) / 86400000);
            return (
                <Panel id={id} title={title} subtitle="Calls by day and hour. Darker means busier.">
                    {c.calls ? (
                        <>
                            <Heatmap grid={c.grid} firstHour={c.first_hour} lastHour={c.last_hour} max={c.max} caption="Calls by weekday and hour" />
                            {c.tip ? (
                                <Note tone="amber">
                                    <Lightbulb className="mt-0.5 size-4 flex-none" aria-hidden />
                                    {tipWords(c.tip, days)}
                                </Note>
                            ) : null}
                        </>
                    ) : (
                        <Empty>No calls in this period yet.</Empty>
                    )}
                </Panel>
            );
        }
        case "unanswered_questions": {
            const c = cards.unanswered_questions;
            if (!c) return null;
            return (
                <Panel id={id} title={title} subtitle="Add an answer once and your agent knows it next time">
                    {c.groups.length ? (
                        <ul className="flex flex-col gap-2">
                            {c.groups.map((g) => (
                                <li
                                    key={`${g.run_id}-${g.question}`}
                                    className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-line-soft px-3.5 py-2.5"
                                >
                                    <span className="w-full min-w-0 text-body font-medium text-foreground @md:w-auto @md:flex-1">{g.question}</span>
                                    <span className="text-caption tabular-nums text-ink-3">{plural(g.count, "time")}</span>
                                    {ctx.onAddAnswer ? (
                                        <button
                                            type="button"
                                            onClick={() =>
                                                ctx.onAddAnswer?.({ run_id: g.run_id, workflow_id: g.workflow_id, question: g.question })
                                            }
                                            className="inline-flex items-center gap-1 rounded-md text-caption font-semibold text-brand outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring/50"
                                        >
                                            <MessageSquarePlus className="size-3.5" aria-hidden />
                                            Add an answer
                                        </button>
                                    ) : null}
                                </li>
                            ))}
                            {c.more ? <li className="text-caption text-ink-3">And {plural(c.more, "more question")}.</li> : null}
                        </ul>
                    ) : (
                        <Empty>Your agent answered every question in this period.</Empty>
                    )}
                </Panel>
            );
        }
        case "follow_ups": {
            const c = cards.follow_ups;
            if (!c) return null;
            const max = Math.max(0, ...c.kinds.map((k) => k.count));
            return (
                <Panel id={id} title={title} subtitle="Calls that needed a person">
                    {c.raised ? (
                        <>
                            <div className="grid grid-cols-3 gap-2">
                                <Stat value={c.raised} label="raised" />
                                <Stat value={c.sorted} label="sorted" />
                                <Stat value={c.median_wait_minutes != null ? waitWords(c.median_wait_minutes) : "–"} label="usual wait" />
                            </div>
                            <ul className="mt-4 flex flex-col gap-3">
                                {c.kinds.map((k) => (
                                    <BarRow
                                        key={k.kind}
                                        label={FOLLOW_UP_WORDS[k.kind as FollowUpKind].filter}
                                        value={k.count}
                                        max={max}
                                    />
                                ))}
                            </ul>
                            {c.open ? (
                                <Link href="/follow-ups" className="mt-3 inline-block text-caption font-semibold text-brand hover:underline">
                                    {plural(c.open, "follow-up")} still open
                                </Link>
                            ) : null}
                        </>
                    ) : (
                        <Empty>No calls needed a person in this period.</Empty>
                    )}
                </Panel>
            );
        }
        case "lines_busy": {
            const c = cards.lines_busy;
            if (!c) return null;
            const most = Math.max(0, ...c.busiest.map((b) => b.calls));
            return (
                <Panel id={id} title={title} subtitle="Rang while every line was in use">
                    {c.calls ? (
                        <>
                            <div className="grid grid-cols-3 gap-2">
                                <Stat value={c.calls} label="couldn't get through" />
                                <Stat value={c.answered} label="put through to your team" />
                                <Stat value={c.voicemails} label="left a voicemail" />
                            </div>
                            {c.busiest.length ? (
                                <>
                                    <h3 className="mt-4 text-caption font-semibold text-ink-2">When it happened most</h3>
                                    <ul className="mt-2 flex flex-col gap-3">
                                        {c.busiest.map((b) => (
                                            <BarRow
                                                key={`${b.weekday}-${b.hour}`}
                                                label={`${WEEKDAYS[b.weekday].slice(0, 3)} ${shortHour(b.hour)}–${shortHour(b.hour + 1)}`}
                                                value={b.calls}
                                                max={most}
                                            />
                                        ))}
                                    </ul>
                                </>
                            ) : null}
                            <Note tone="amber">
                                <span>
                                    {c.limit
                                        ? `Your agents take up to ${plural(c.limit, "call")} at once. `
                                        : "Your agents take a set number of calls at once. "}
                                    <ContactSupportLink>Need more? Contact us</ContactSupportLink>
                                </span>
                            </Note>
                            {c.calls - c.answered > 0 ? (
                                <Link
                                    href="/follow-ups?kind=lines_busy"
                                    className="mt-3 inline-block text-caption font-semibold text-brand hover:underline"
                                >
                                    Ring them back in Follow-ups
                                </Link>
                            ) : null}
                        </>
                    ) : (
                        <Empty>Every caller got through: your lines were never all busy.</Empty>
                    )}
                </Panel>
            );
        }
        case "after_hours": {
            const c = cards.after_hours;
            if (!c) return null;
            return (
                <Panel id={id} title={title} subtitle="What your agent handled outside opening hours">
                    {!c.hours_set ? (
                        <HoursMissing />
                    ) : (
                        <>
                            <div className="grid grid-cols-3 gap-2">
                                <Stat value={c.calls ?? 0} label="calls" />
                                <Stat value={c.bookings ?? 0} label="bookings" />
                                <Stat value={c.callbacks ?? 0} label="left a number" />
                            </div>
                            {c.calls ? (
                                <Note tone="brand">
                                    {c.bookings
                                        ? `${plural(c.bookings, "booking")} came in while you were closed, taken by your agent.`
                                        : `Your agent answered ${plural(c.calls ?? 0, "call")} while you were closed.`}
                                </Note>
                            ) : (
                                <Note>No calls came in while you were closed.</Note>
                            )}
                            {c.agents_without_hours.length ? (
                                <p className="mt-2 text-caption text-ink-3">Not counted: {c.agents_without_hours.join(", ")}, with no opening hours set as times.</p>
                            ) : null}
                        </>
                    )}
                </Panel>
            );
        }
        case "agent_performance": {
            const c = cards.agent_performance;
            if (!c) return null;
            const max = Math.max(c.handled, c.needed_person, c.no_conversation);
            return (
                <Panel id={id} title={title} subtitle="Calls handled start to finish, no staff needed">
                    {c.calls ? (
                        <>
                            <div className="grid grid-cols-3 gap-2">
                                <Stat value={c.handled_percent != null ? `${c.handled_percent}%` : "–"} label="handled" />
                                <Stat value={c.passed_to_team} label="passed to your team" />
                                <Stat value={c.hung_up_silent} label="hung up without speaking" />
                            </div>
                            <ul className="mt-4 flex flex-col gap-3">
                                <BarRow label="Handled by your agent" value={c.handled} max={max} />
                                <BarRow label="Needed a person" value={c.needed_person} max={max} swatch="bg-[#eda100] dark:bg-[#c98500]" />
                                <BarRow
                                    label="No conversation"
                                    value={c.no_conversation}
                                    max={max}
                                    swatch="bg-[#9aa1ad] dark:bg-[#6b7280]"
                                    detail="Hung up, didn't connect or dropped"
                                />
                            </ul>
                        </>
                    ) : (
                        <Empty>No calls in this period yet.</Empty>
                    )}
                </Panel>
            );
        }
        case "days_filling": {
            const c = cards.days_filling;
            if (!c) return null;
            const any = c.days.some((d) => d.bookings);
            return (
                <Panel id={id} title={title} subtitle="Covers booked by phone, by the day they're for">
                    {any ? (
                        <>
                            <Columns
                                caption="Covers booked by phone for the next two weeks"
                                unit={["cover", "covers"]}
                                showValues
                                columns={c.days.map((d) => ({
                                    key: d.date,
                                    tick: shortDay(d.date).replace(/^(\w{3}) \d+$/, "$1"),
                                    label: shortDay(d.date),
                                    value: d.covers,
                                    strong: d.covers >= Math.max(...c.days.map((x) => x.covers)) * 0.75,
                                    note: d.closed ? "Closed" : undefined,
                                }))}
                            />
                            {c.without_size || c.later ? (
                                <p className="mt-2 text-caption text-ink-3">
                                    {[
                                        c.without_size ? `${plural(c.without_size, "booking")} without a clear party size` : null,
                                        c.later ? `${plural(c.later, "booking")} further ahead` : null,
                                    ]
                                        .filter(Boolean)
                                        .join(" · ")}
                                </p>
                            ) : null}
                        </>
                    ) : (
                        <Empty>No bookings for the next two weeks from this period yet.</Empty>
                    )}
                </Panel>
            );
        }
        case "special_requests": {
            const c = cards.special_requests;
            if (!c) return null;
            const max = Math.max(0, ...c.tags.map((t) => t.count));
            return (
                <Panel id={id} title={title} subtitle="What guests asked for when booking">
                    {c.tags.length ? (
                        <ul className="flex flex-col gap-3">
                            {c.tags.map((t) => (
                                <BarRow key={t.key} label={t.label} value={t.count} max={max} swatch="bg-[#2a78d6] dark:bg-[#3987e5]" />
                            ))}
                        </ul>
                    ) : (
                        <Empty>No special requests tagged in this period.</Empty>
                    )}
                    {c.not_tagged ? (
                        <p className="mt-3 text-caption text-ink-3">
                            {plural(c.not_tagged, "call")} with a request {c.not_tagged === 1 ? "was" : "were"} reviewed before requests were
                            sorted, so {c.not_tagged === 1 ? "it isn't" : "they aren't"} counted here.
                        </p>
                    ) : null}
                </Panel>
            );
        }
        case "patient_status": {
            const c = cards.patient_status;
            if (!c) return null;
            const total = c.new + c.existing + c.other;
            const max = Math.max(c.new, c.existing, c.other);
            return (
                <Panel id={id} title={title} subtitle="As your agent wrote them down">
                    {total ? (
                        <ul className="flex flex-col gap-3">
                            <BarRow label="New patients" value={c.new} max={max} swatch="bg-[#2a78d6] dark:bg-[#3987e5]" />
                            <BarRow label="Existing patients" value={c.existing} max={max} swatch="bg-[#1baf7a] dark:bg-[#199e70]" />
                            {c.other ? <BarRow label="Something else" value={c.other} max={max} swatch="bg-[#9aa1ad] dark:bg-[#6b7280]" /> : null}
                        </ul>
                    ) : (
                        <Empty>No patients told your agent whether they&apos;re new in this period.</Empty>
                    )}
                    {c.booked_not_said ? (
                        <p className="mt-3 text-caption text-ink-3">{plural(c.booked_not_said, "booking")} without it written down.</p>
                    ) : null}
                </Panel>
            );
        }
        case "appointment_types": {
            const c = cards.appointment_types;
            if (!c) return null;
            const max = Math.max(0, ...c.types.map((t) => t.calls));
            return (
                <Panel id={id} title={title} subtitle="What callers wanted to come in for, and how many booked">
                    {c.types.length ? (
                        <ul className="flex flex-col gap-3">
                            {c.types.map((t) => (
                                <BarRow key={t.label} label={t.label} value={t.calls} max={max} detail={`${t.booked} booked`} />
                            ))}
                            {c.other_calls ? <li className="text-caption text-ink-3">Other types: {c.other_calls}</li> : null}
                        </ul>
                    ) : (
                        <Empty>No appointment types written down in this period.</Empty>
                    )}
                </Panel>
            );
        }
        case "emergencies_by_hour": {
            const c = cards.emergencies_by_hour;
            if (!c) return null;
            return (
                <Panel
                    id={id}
                    title={title}
                    subtitle={c.after_hours != null && c.count ? `${c.after_hours} of ${c.count} came in while you were closed` : "Calls your agent marked as an emergency"}
                >
                    {c.count ? (
                        <Columns
                            caption="Emergencies by hour of the day"
                            unit={["emergency", "emergencies"]}
                            tone="bg-[#eb6834] dark:bg-[#d95926]"
                            columns={c.hours.map((n, h) => ({
                                key: String(h),
                                tick: h % 6 === 0 ? shortHour(h) : "",
                                label: `${shortHour(h)}–${shortHour(h + 1)}`,
                                value: n,
                                strong: h === c.peak_hour,
                            }))}
                        />
                    ) : (
                        <Empty>No emergencies in this period.</Empty>
                    )}
                </Panel>
            );
        }
        case "areas": {
            const c = cards.areas;
            if (!c) return null;
            const max = Math.max(0, ...c.areas.map((a) => a.count));
            return (
                <Panel id={id} title={title} subtitle="Read from the address your agent wrote down">
                    {c.areas.length ? (
                        <ul className="flex flex-col gap-3">
                            {c.areas.map((a) => (
                                <BarRow key={a.label} label={a.label} value={a.count} max={max} />
                            ))}
                        </ul>
                    ) : (
                        <Empty>No job addresses in this period.</Empty>
                    )}
                    {c.other_areas || c.unclear ? (
                        <p className="mt-3 text-caption text-ink-3">
                            {[
                                c.other_areas ? `${plural(c.other_areas, "call")} from ${c.places - c.areas.length} other places` : null,
                                c.unclear ? `${plural(c.unclear, "address", "addresses")} we couldn't place` : null,
                            ]
                                .filter(Boolean)
                                .join(" · ")}
                        </p>
                    ) : null}
                </Panel>
            );
        }
        case "top_products": {
            const c = cards.top_products;
            if (!c) return null;
            const max = Math.max(0, ...c.products.map((p) => p.calls));
            return (
                <Panel id={id} title={title} subtitle="As your agent wrote them down">
                    {c.products.length ? (
                        <ul className="flex flex-col gap-3">
                            {c.products.map((p) => (
                                <BarRow key={p.label} label={p.label} value={p.calls} max={max} />
                            ))}
                            {c.other_products ? <li className="text-caption text-ink-3">Other products: {c.other_products}</li> : null}
                        </ul>
                    ) : (
                        <Empty>No products written down in this period.</Empty>
                    )}
                </Panel>
            );
        }
        case "callbacks_waiting":
        case "waiting_for_team": {
            const c = cards[cardKey];
            if (!c) return null;
            return (
                <Panel id={id} title={title} subtitle="People from this period still waiting to be rung back">
                    <WaitingList card={c} ctx={ctx} empty="Nobody from this period is waiting for a call back." />
                </Panel>
            );
        }
        case "issues_by_type": {
            const c = cards.issues_by_type;
            if (!c) return null;
            const colours = reasonColours(c.types);
            const max = Math.max(0, ...c.types.map((t) => t.count));
            return (
                <Panel id={id} title={title} subtitle="Sorted by your agent, or passed on to your team">
                    {c.types.length ? (
                        <ul className="flex flex-col gap-3">
                            {c.types.map((t) => (
                                <BarRow
                                    key={t.key}
                                    label={t.label}
                                    value={t.count}
                                    max={max}
                                    swatch={colours[t.key].swatch}
                                    detail={`${t.sorted} sorted · ${t.passed_on} passed on${t.no_conversation ? ` · ${t.no_conversation} no conversation` : ""}`}
                                />
                            ))}
                        </ul>
                    ) : (
                        <Empty>No calls in this period yet.</Empty>
                    )}
                </Panel>
            );
        }
        case "call_spikes": {
            const c = cards.call_spikes;
            if (!c) return null;
            const total = c.by_hour.reduce((a, b) => a + b, 0);
            return (
                <Panel id={id} title={title} subtitle="Hours with far more calls than usual, often an outage">
                    {total ? (
                        <>
                            <Columns
                                caption="Calls by hour of the day"
                                unit={["call", "calls"]}
                                columns={c.by_hour.map((n, h) => ({
                                    key: String(h),
                                    tick: h % 6 === 0 ? shortHour(h) : "",
                                    label: `${shortHour(h)}–${shortHour(h + 1)}`,
                                    value: n,
                                }))}
                            />
                            {c.spikes.length ? (
                                <ul className="mt-3 divide-y divide-line-soft">
                                    {c.spikes.map((s) => (
                                        <li key={s.at} className="flex justify-between gap-3 py-2 text-body">
                                            <span className="text-foreground">{callWhen(s.at, report.timezone, ctx.now)}</span>
                                            <span className="tabular-nums text-ink-2">
                                                {plural(s.calls, "call")} <span className="text-ink-3">(usually {s.usual})</span>
                                            </span>
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <Note>No hour had far more calls than usual.</Note>
                            )}
                        </>
                    ) : (
                        <Empty>No calls in this period yet.</Empty>
                    )}
                </Panel>
            );
        }
        case "repeat_callers": {
            const c = cards.repeat_callers;
            if (!c) return null;
            return (
                <Panel id={id} title={title} subtitle="The same number more than once in this period">
                    {c.callers ? (
                        <>
                            <div className="grid grid-cols-2 gap-2">
                                <Stat value={c.callers} label={c.callers === 1 ? "caller" : "callers"} />
                                <Stat value={c.calls} label="calls between them" />
                            </div>
                            <ul className="mt-3 divide-y divide-line-soft">
                                {c.items.map((i) => (
                                    <li key={i.last_run_id} className="flex items-center justify-between gap-3 py-2.5">
                                        <span className="min-w-0">
                                            <span className="block truncate text-body font-medium text-foreground">
                                                {i.caller_name || i.caller_number || "Unknown caller"}
                                            </span>
                                            <span className="block text-caption text-ink-3">
                                                Last {callWhen(i.last_at, report.timezone, ctx.now)}
                                                {i.reached ? "" : " · reached nobody"}
                                            </span>
                                        </span>
                                        <span className="flex-none text-body font-semibold tabular-nums text-foreground">{i.calls}×</span>
                                    </li>
                                ))}
                            </ul>
                        </>
                    ) : (
                        <Empty>Nobody rang more than once in this period.</Empty>
                    )}
                </Panel>
            );
        }
        default:
            return null;
    }
}
