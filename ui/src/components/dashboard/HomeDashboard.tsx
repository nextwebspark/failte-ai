"use client";

import {
    AlertTriangle,
    ArrowDownRight,
    ArrowRight,
    ArrowUpRight,
    CalendarRange,
    Check,
    CheckCircle2,
    Clock,
    FileText,
    Headphones,
    type LucideIcon,
    Mic,
    Moon,
    Phone,
    PhoneCall,
    PhoneForwarded,
    Play,
    RefreshCw,
} from "lucide-react";
import Link from "next/link";
import { type ReactNode, useState } from "react";

import { formatPhone } from "@/app/usage/callsView";
import type {
    DashboardAfterHours,
    DashboardRange,
    DashboardRecentCall,
    DashboardSummaryResponse,
    FollowUpItem,
} from "@/client/types.gen";
import { useOwnsPageHeading } from "@/components/layout/pageHeading";
import { runDetailHref } from "@/components/layout/shellContext";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { agentFactsHref, agentTalkHref } from "@/components/workflow/agentLinks";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { cn } from "@/lib/utils";

import { AddAnswerDialog } from "./AddAnswerDialog";
import { CallersWantedChart } from "./CallersWantedChart";
import {
    afterHoursWords,
    busiestHour,
    callerWords,
    callLength,
    callsTileLabel,
    callWhen,
    changeWords,
    euros,
    followUpKey,
    hourSpan,
    lastCallWords,
    markKind,
    notAnsweringWords,
    RANGE_OPTIONS,
    rangeSentence,
    RESULT_WORDS,
    telHref,
    todayLine,
} from "./dashboardView";
import { Chip, FollowUpRow } from "./FollowUpRow";
import { HomeSkeleton } from "./HomeSkeleton";
import { HourlyCallsChart } from "./HourlyCallsChart";
import { useDashboardSummary, useFollowUpMarking, useFollowUps } from "./useDashboardData";

const ATTENTION_LIMIT = 4;

/** A card in the design's style: white panel, 14px corners, a header row. */
function Card({
    title,
    titleId,
    action,
    children,
    className,
}: {
    title: ReactNode;
    titleId: string;
    action?: ReactNode;
    children: ReactNode;
    className?: string;
}) {
    return (
        <section
            aria-labelledby={titleId}
            className={cn("min-w-0 rounded-[14px] border border-line bg-panel shadow-xs", className)}
        >
            <header className="flex items-center justify-between gap-3 px-[18px] pt-[18px] sm:px-5">
                <h2 id={titleId} className="flex items-center gap-2 font-display text-title font-semibold text-foreground">
                    {title}
                </h2>
                {action}
            </header>
            <div className="@container px-[18px] pb-5 pt-4 sm:px-5">{children}</div>
        </section>
    );
}

function CardLink({ href, children }: { href: string; children: ReactNode }) {
    return (
        <Link href={href} className="whitespace-nowrap text-sm font-semibold text-brand hover:underline">
            {children}
        </Link>
    );
}

/** The quiet note in a card's header slot ("Today", "Calls per hour, today"). */
function CardHint({ children }: { children: ReactNode }) {
    return <span className="text-right text-caption text-ink-3">{children}</span>;
}

function RangeSwitch({ value, onChange }: { value: DashboardRange; onChange: (v: DashboardRange) => void }) {
    return (
        <div
            role="group"
            aria-label="Show calls for"
            className="flex w-full rounded-[10px] border border-line bg-panel p-[3px] sm:inline-flex sm:w-auto"
        >
            {RANGE_OPTIONS.map((option) => (
                <button
                    key={option.value}
                    type="button"
                    aria-pressed={value === option.value}
                    onClick={() => onChange(option.value)}
                    className={cn(
                        "flex-1 rounded-[7px] px-3.5 py-1.5 text-sm font-medium outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/40 sm:flex-none",
                        value === option.value ? "bg-foreground text-background" : "text-ink-2 hover:text-foreground",
                    )}
                >
                    {option.label}
                </button>
            ))}
        </div>
    );
}

function StatusPill({ summary }: { summary: DashboardSummaryResponse }) {
    const status = summary.agent_status;
    const number = status.phone_numbers[0];
    return (
        <span className="inline-flex max-w-full items-center gap-2 rounded-full border border-line bg-panel py-1.5 pl-3 pr-3.5 text-sm text-ink-2">
            <span
                className={cn(
                    "size-2 flex-none rounded-full",
                    status.answering ? "bg-brand ring-[3px] ring-brand-dim" : "bg-danger ring-[3px] ring-danger-dim",
                )}
                aria-hidden
            />
            <span className="truncate">
                {status.answering ? "Answering calls" : "Not answering"}
                {status.answering && number ? <span className="tabular-nums"> · {formatPhone(number)}</span> : null}
            </span>
        </span>
    );
}

/**
 * "6 calls · 4 handled by your agent · 3 bookings taken · 1 asked for a call
 * back": the range's headline counts in one line, straight from the tiles.
 */
function TodayLine({ summary }: { summary: DashboardSummaryResponse }) {
    const parts = todayLine(summary.tiles, summary.wording.bookings_label);
    if (parts.length === 0) return null;
    return (
        <ul className="mt-3 flex flex-wrap gap-2" aria-label="At a glance" data-testid="today-line">
            {parts.map((part) => (
                <li
                    key={part.words}
                    className="whitespace-nowrap rounded-full border border-line-soft bg-panel-2 px-3 py-1 text-sm text-ink-2"
                >
                    <b className="font-semibold tabular-nums text-foreground">{part.value}</b> {part.words}
                </li>
            ))}
        </ul>
    );
}

function NotAnsweringBanner({ summary, now }: { summary: DashboardSummaryResponse; now: Date }) {
    const { can } = useOrgConfig();
    const reason = summary.agent_status.reason;
    if (summary.agent_status.answering || !reason) return null;
    const words = notAnsweringWords(reason);
    return (
        <div
            role="alert"
            className="flex flex-col gap-3 rounded-[14px] border border-danger/40 border-l-[4px] border-l-danger bg-danger-dim px-[18px] py-4 sm:flex-row sm:items-center"
        >
            <AlertTriangle className="hidden size-5 flex-none text-danger sm:block" aria-hidden />
            <div className="min-w-0 flex-1">
                <p className="text-body font-semibold text-foreground">{words.title}</p>
                <p className="mt-0.5 text-sm text-ink-2">
                    {words.detail}
                    {reason !== "no_agent" && <> {lastCallWords(summary.agent_status.last_call_at, now)}.</>}
                </p>
            </div>
            {can(words.fix.requires) ? (
                <Button asChild size="sm" variant="destructive" className="self-start sm:self-auto">
                    <Link href={words.fix.href}>{words.fix.label}</Link>
                </Button>
            ) : (
                <p className="text-caption text-ink-2">Ask the owner of your account to fix this.</p>
            )}
        </div>
    );
}

/** "+4 on last Saturday": the change as a small pill, then what it's compared with. */
function Trend({ change }: { change: NonNullable<ReturnType<typeof changeWords>> }) {
    if (change.sign === "same") return <span className="text-ink-3">{change.rest}</span>;
    const Icon = change.sign === "up" ? ArrowUpRight : ArrowDownRight;
    return (
        <span className="inline-flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
            <span
                className={cn(
                    "inline-flex items-center gap-0.5 rounded-full px-1.5 py-px text-meta font-semibold tabular-nums",
                    change.sign === "up" ? "bg-brand-dim text-brand" : "bg-panel-2 text-ink-2",
                )}
            >
                <Icon className="size-3.5" aria-hidden />
                {change.amount}
            </span>
            <span className="text-ink-3">{change.rest.trim()}</span>
        </span>
    );
}

interface TileProps {
    icon: LucideIcon;
    tone: string;
    label: string;
    /** The label on a phone, where four tiles share 390px. */
    shortLabel?: string;
    value: ReactNode;
    caption?: ReactNode;
    /** What a phone shows under the number (nothing when omitted). */
    phoneCaption?: ReactNode;
}

function Tile({ icon: Icon, tone, label, shortLabel, value, caption, phoneCaption }: TileProps) {
    return (
        <div className="flex min-w-0 flex-col gap-2 rounded-[14px] border border-line bg-panel px-4 py-4 shadow-xs sm:gap-2.5 sm:px-5 sm:py-[18px]">
            <div className="flex items-start justify-between gap-2">
                <span className="min-w-0 pt-0.5 text-sm font-medium leading-snug text-ink-2 sm:text-body">
                    {shortLabel ? (
                        <>
                            <span className="sm:hidden">{shortLabel}</span>
                            <span className="hidden sm:inline">{label}</span>
                        </>
                    ) : (
                        label
                    )}
                </span>
                <span className={cn("grid size-8 flex-none place-items-center rounded-[10px] sm:size-9", tone)} aria-hidden>
                    <Icon className="size-4 sm:size-[18px]" />
                </span>
            </div>
            <div className="font-display text-[30px] font-semibold leading-none tracking-[-0.02em] tabular-nums text-foreground sm:text-kpi sm:leading-none">
                {value}
            </div>
            {phoneCaption && <div className="text-caption leading-snug text-ink-2 sm:hidden">{phoneCaption}</div>}
            {caption && <div className="hidden text-caption leading-snug text-ink-2 sm:block">{caption}</div>}
        </div>
    );
}

function Tiles({ summary, now }: { summary: DashboardSummaryResponse; now: Date }) {
    const t = summary.tiles;
    const change = changeWords(summary.range, summary.calls_change, now, summary.timezone);
    const average = callLength(t.average_call_seconds);
    // The three tiles after "Calls" plus this line account for every call,
    // so the numbers on Home always add up to the total.
    const noConversation = t.no_conversation ?? t.hung_up_silent;
    const rest = [
        noConversation > 0 ? `${noConversation} hung up or didn't connect` : null,
        t.in_progress > 0 ? `${t.in_progress} in progress` : null,
    ].filter(Boolean).join(" · ");
    const callsCaption = (
        <>
            {change ? <Trend change={change} /> : average ? `Average call ${average}` : null}
            {rest && <span className="mt-1 block text-ink-3">{rest}</span>}
        </>
    );
    return (
        <div className="grid grid-cols-2 gap-3 @3xl:grid-cols-4 @3xl:gap-4">
            <Tile
                icon={Phone}
                tone="bg-sky-dim text-sky"
                label={callsTileLabel(summary.range)}
                shortLabel="Calls"
                value={t.calls}
                phoneCaption={change ? <Trend change={change} /> : null}
                caption={callsCaption}
            />
            <Tile
                icon={Check}
                tone="bg-brand-dim text-brand"
                label="Handled by your agent"
                shortLabel="Handled by agent"
                value={
                    <>
                        {t.handled}
                        {t.handled_percent != null && (
                            <small className="ml-1.5 text-[17px] font-semibold tracking-normal text-ink-3">{t.handled_percent}%</small>
                        )}
                    </>
                }
                caption="Answered start to finish, no staff needed"
            />
            <Tile
                icon={PhoneCall}
                tone="bg-amber-dim text-amber"
                label="Need a call back"
                shortLabel="Call backs"
                value={t.callbacks_requested}
                caption="Your agent took their details; someone needs to ring them"
            />
            <Tile
                icon={PhoneForwarded}
                tone="bg-sky-dim text-sky"
                label="Passed to your team"
                shortLabel="Passed to team"
                value={t.passed_to_team}
                phoneCaption={
                    t.transfer_not_answered > 0 ? (
                        <b className="font-semibold text-amber">{t.transfer_not_answered} not answered</b>
                    ) : null
                }
                caption={
                    t.passed_to_team > 0 ? (
                        <>
                            {t.transfer_picked_up} picked up
                            {t.transfer_not_answered > 0 && (
                                <>
                                    {" · "}
                                    <b className="font-semibold text-amber">{t.transfer_not_answered} not answered</b>
                                </>
                            )}
                        </>
                    ) : (
                        "Calls your agent put through to a person"
                    )
                }
            />
        </div>
    );
}

function Attention({
    items,
    openCount,
    timezone,
    now,
    followUpsHref,
    onAddAnswer,
}: {
    items: FollowUpItem[] | null;
    openCount: number | null;
    timezone: string;
    now: Date;
    followUpsHref: string;
    onAddAnswer: (item: FollowUpItem) => void;
}) {
    const { can } = useOrgConfig();
    const { busy, change } = useFollowUpMarking();
    const canMark = can("followups:manage");
    return (
        <Card
            titleId="home-attention"
            title={
                <>
                    Needs your attention
                    {openCount ? <Chip tone="amber" className="text-meta">{openCount}</Chip> : null}
                </>
            }
            action={<CardLink href={followUpsHref}>All follow-ups</CardLink>}
        >
            {items === null ? (
                <p className="py-4 text-sm text-ink-3">Couldn&apos;t load follow-ups. They&apos;re on the Follow-ups page.</p>
            ) : items.length === 0 ? (
                <div className="flex items-center gap-3.5 py-2">
                    <span className="grid size-10 flex-none place-items-center rounded-full bg-brand-dim text-brand" aria-hidden>
                        <CheckCircle2 className="size-5" />
                    </span>
                    <div>
                        <p className="text-body font-semibold text-foreground">All caught up</p>
                        <p className="text-sm text-ink-3">No callers are waiting on you.</p>
                    </div>
                </div>
            ) : (
                <ul className="flex flex-col">
                    {items.slice(0, ATTENTION_LIMIT).map((item) => (
                        <FollowUpRow
                            key={followUpKey(item)}
                            item={item}
                            timezone={timezone}
                            now={now}
                            returnTo="/overview"
                            busy={busy === followUpKey(item)}
                            // Done here only for the review kinds (no call to return).
                            onMarkDone={
                                canMark && markKind(item.kind) !== null
                                    ? (i) => void change(i, true)
                                    : undefined
                            }
                            onAddAnswer={canMark && can("agents:facts") ? onAddAnswer : undefined}
                        />
                    ))}
                </ul>
            )}
        </Card>
    );
}

function PlayLink({ call, returnTo }: { call: DashboardRecentCall; returnTo: string }) {
    if (!call.has_recording) {
        return <span className="block size-8" aria-hidden />;
    }
    return (
        <Link
            href={runDetailHref(call.workflow_id, call.run_id, returnTo)}
            className="grid size-8 place-items-center rounded-full bg-brand-dim text-brand outline-none hover:bg-brand hover:text-white focus-visible:ring-[3px] focus-visible:ring-ring/40"
            aria-label={`Listen to the call from ${callerWords(call)}`}
        >
            <Play className="size-3.5 fill-current" aria-hidden />
        </Link>
    );
}

/**
 * What an empty card offers instead of a blank: on Today, the last 7 days;
 * otherwise a test call to the agent.
 */
function NoCallsYet({
    range,
    onRange,
    tryHref,
    onTryAgent,
}: {
    range: DashboardRange;
    onRange: (range: DashboardRange) => void;
    tryHref: string | null;
    onTryAgent?: () => void;
}) {
    return (
        <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed border-line px-4 py-4">
            <p className="text-sm text-ink-2">
                {range === "today"
                    ? "No calls yet today. They show up here as they come in."
                    : `No calls in the last ${range === "7d" ? "7" : "30"} days.`}
            </p>
            {range !== "30d" ? (
                <Button size="sm" variant="outline" onClick={() => onRange(range === "today" ? "7d" : "30d")}>
                    <CalendarRange aria-hidden />
                    {range === "today" ? "See the last 7 days" : "See the last 30 days"}
                </Button>
            ) : onTryAgent ? (
                <Button size="sm" variant="outline" onClick={onTryAgent}>
                    <Mic aria-hidden />
                    Try your agent
                </Button>
            ) : tryHref ? (
                <Button asChild size="sm" variant="outline">
                    <Link href={tryHref}>
                        <Mic aria-hidden />
                        Try your agent
                    </Link>
                </Button>
            ) : null}
        </div>
    );
}

function RecentCalls({ summary, now, empty }: { summary: DashboardSummaryResponse; now: Date; empty: ReactNode }) {
    const calls = summary.recent_calls;
    const returnTo = "/overview";
    const chipFor = (call: DashboardRecentCall) => RESULT_WORDS[call.result];
    const CallerLink = ({ call, className, children }: { call: DashboardRecentCall; className: string; children: ReactNode }) => (
        <Link href={runDetailHref(call.workflow_id, call.run_id, returnTo)} className={className}>
            {children}
        </Link>
    );
    return (
        <Card titleId="home-recent" title="Recent calls" action={<CardLink href="/usage">All calls</CardLink>}>
            {calls.length === 0 ? (
                empty
            ) : (
                <>
                    {/* Phone: a simple list */}
                    <ul className="flex flex-col @3xl:hidden">
                        {calls.map((call) => (
                            <li key={call.run_id} className="flex items-start gap-3 border-t border-line-soft py-3 first:border-t-0">
                                <PlayLink call={call} returnTo={returnTo} />
                                <CallerLink call={call} className="min-w-0 flex-1 outline-none focus-visible:underline">
                                    <span className="block truncate text-body font-semibold text-foreground">{callerWords(call)}</span>
                                    {call.summary && <span className="mt-0.5 block text-sm leading-snug text-ink-2">{call.summary}</span>}
                                    <span className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-meta tabular-nums text-ink-3">
                                        <Chip tone={chipFor(call).tone} className="text-meta">{chipFor(call).label}</Chip>
                                        {callWhen(call.created_at, summary.timezone, now)}
                                    </span>
                                </CallerLink>
                            </li>
                        ))}
                    </ul>
                    {/* Computer: the table from the design */}
                    <table className="hidden w-full text-left text-sm @3xl:table">
                        <thead>
                            <tr className="border-b border-line text-meta font-semibold uppercase tracking-[0.06em] text-ink-3">
                                <th className="w-11 pb-2.5" scope="col">
                                    <span className="sr-only">Listen</span>
                                </th>
                                <th className="pb-2.5" scope="col">Caller</th>
                                <th className="pb-2.5" scope="col">What happened</th>
                                <th className="pb-2.5" scope="col">Outcome</th>
                                <th className="pb-2.5 text-right" scope="col">Time</th>
                            </tr>
                        </thead>
                        <tbody>
                            {calls.map((call) => (
                                <tr key={call.run_id} className="border-b border-line-soft last:border-b-0">
                                    <td className="py-3 align-top">
                                        <PlayLink call={call} returnTo={returnTo} />
                                    </td>
                                    <td className="w-[26%] py-3 pr-3 align-top">
                                        <CallerLink call={call} className="font-semibold text-foreground hover:underline">
                                            {callerWords(call)}
                                        </CallerLink>
                                        {call.caller_name && call.caller_number && (
                                            <div className="mt-0.5 text-caption tabular-nums text-ink-3">{formatPhone(call.caller_number)}</div>
                                        )}
                                    </td>
                                    <td className="py-3 pr-3 align-top leading-relaxed text-ink-2">
                                        {call.summary ?? (
                                            <span className="text-ink-3">
                                                {callLength(call.duration_seconds) ? `${callLength(call.duration_seconds)} call` : "—"}
                                            </span>
                                        )}
                                    </td>
                                    <td className="py-3 pr-3 align-top">
                                        <Chip tone={chipFor(call).tone} className="text-meta">{chipFor(call).label}</Chip>
                                    </td>
                                    <td className="whitespace-nowrap py-3 text-right align-top tabular-nums text-ink-2">
                                        {callWhen(call.created_at, summary.timezone, now)}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </>
            )}
        </Card>
    );
}

function WhenPeopleCalled({ summary, empty }: { summary: DashboardSummaryResponse; empty: ReactNode }) {
    const sub =
        summary.range === "today"
            ? "Calls per hour, today"
            : `Calls per hour, last ${summary.range === "7d" ? "7" : "30"} days`;
    const peak = busiestHour(summary.calls_by_hour);
    return (
        <Card titleId="home-hours" title="When people called" action={<CardHint>{sub}</CardHint>}>
            {summary.tiles.calls === 0 ? (
                empty
            ) : (
                <>
                    {peak !== null && (
                        <p className="mb-6 flex flex-wrap items-baseline gap-x-2 text-sm text-ink-2">
                            <span className="text-ink-3">Busiest hour</span>
                            <b className="font-display text-title font-semibold tabular-nums text-foreground">{hourSpan(peak)}</b>
                            <span className="tabular-nums">
                                {summary.calls_by_hour[peak]} {summary.calls_by_hour[peak] === 1 ? "call" : "calls"}
                            </span>
                        </p>
                    )}
                    <HourlyCallsChart hours={summary.calls_by_hour} caption={sub} />
                </>
            )}
            <AfterHours afterHours={summary.after_hours} />
        </Card>
    );
}

/**
 * Calls that came in while the business was closed, by each agent's opening
 * hours set as times. Agents without them are named, not guessed.
 */
function AfterHours({ afterHours }: { afterHours: DashboardAfterHours | undefined }) {
    const { can } = useOrgConfig();
    if (!afterHours) return null;
    const words = afterHoursWords(afterHours);
    if (!words.count && !words.note) return null;
    const missing = afterHours.agents_without_hours;
    return (
        <div className="mt-5 flex items-start gap-3 rounded-xl border border-line-soft bg-panel-2 px-4 py-3.5">
            <span className="grid size-9 flex-none place-items-center rounded-[10px] bg-sky-dim text-sky" aria-hidden>
                <Moon className="size-[18px]" />
            </span>
            <div className="min-w-0 pt-0.5">
                {words.count && <p className="text-body font-semibold tabular-nums text-foreground">{words.count}</p>}
                {words.note && (
                    <p className={cn("text-caption text-ink-3", words.count && "mt-0.5")}>
                        {words.note}
                        {can("agents:facts") && missing.length === 1 && (
                            <>
                                {" "}
                                <Link href={agentFactsHref(missing[0].id)} className="font-medium text-brand hover:underline">
                                    Set the hours
                                </Link>
                            </>
                        )}
                    </p>
                )}
            </div>
        </div>
    );
}

function rangeWords(range: DashboardRange): string {
    return range === "today" ? "Today" : range === "7d" ? "Last 7 days" : "Last 30 days";
}

/** The doc's small figures under the ring: real counts only. */
function StatChip({ value, label, tone }: { value: ReactNode; label: ReactNode; tone?: "amber" }) {
    return (
        <div className="min-w-0 rounded-xl bg-panel-2 px-4 py-3">
            <div
                className={cn(
                    "font-display text-[22px] font-semibold leading-tight tabular-nums",
                    tone === "amber" ? "text-amber" : "text-foreground",
                )}
            >
                {value}
            </div>
            <div className="mt-0.5 text-caption text-ink-3">{label}</div>
        </div>
    );
}

function CallersWanted({ summary, empty }: { summary: DashboardSummaryResponse; empty: ReactNode }) {
    const reasons = summary.callers_wanted;
    const bookings = summary.wording.bookings_label;
    const average = callLength(summary.tiles.average_call_seconds);
    const when = rangeWords(summary.range);
    return (
        <Card titleId="home-wanted" title="What callers wanted" action={<CardHint>{when}</CardHint>}>
            {reasons.length === 0 ? (
                empty
            ) : (
                <CallersWantedChart reasons={reasons} caption={`What callers wanted, ${when.toLowerCase()}`} />
            )}
            {(bookings || average) && summary.tiles.calls > 0 && (
                <div className="mt-5 grid grid-cols-2 gap-3">
                    {bookings && <StatChip value={summary.tiles.bookings_taken} label={bookings} />}
                    {average && <StatChip value={average} label="average call" />}
                </div>
            )}
        </Card>
    );
}

/** The agent the "Try your agent" and "Opening hours" links open. */
function primaryAgentId(summary: DashboardSummaryResponse): number | null {
    return (summary.agents.find((a) => a.active) ?? summary.agents[0])?.id ?? null;
}

function AgentCard({
    summary,
    now,
    onTryAgent,
}: {
    summary: DashboardSummaryResponse;
    now: Date;
    onTryAgent?: () => void;
}) {
    const status = summary.agent_status;
    const agentId = primaryAgentId(summary);
    const credit = summary.credit;
    return (
        <Card titleId="home-agent" title="Your agent">
            {/* At a glance: is it working, on which number, when it last
                answered and how much credit is left. One row on a wide card. */}
            <div className={cn("grid gap-3", credit ? "@2xl:grid-cols-3" : "@2xl:grid-cols-2")}>
                <div
                    className={cn(
                        "flex flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-xl px-4 py-3 @2xl:flex-col @2xl:items-start @2xl:justify-center",
                        status.answering ? "bg-brand-dim" : "bg-danger-dim",
                    )}
                >
                    <p className="flex items-center gap-2.5 text-body font-semibold text-foreground">
                        <span className="relative flex size-2.5" aria-hidden>
                            {status.answering && (
                                <span className="absolute inset-0 animate-ping rounded-full bg-brand opacity-60 motion-reduce:hidden" />
                            )}
                            <span className={cn("relative size-2.5 rounded-full", status.answering ? "bg-brand" : "bg-danger")} />
                        </span>
                        {status.answering ? "Answering calls" : "Not answering"}
                    </p>
                    <div className="text-right @2xl:text-left">
                        <span className="sr-only">{status.phone_numbers.length > 1 ? "Phone numbers: " : "Phone number: "}</span>
                        {status.phone_numbers.length ? (
                            status.phone_numbers.map((n) => (
                                <div key={n} className="font-display text-title font-semibold tabular-nums text-foreground">
                                    {n}
                                </div>
                            ))
                        ) : (
                            <span className="text-sm text-ink-2">No number linked</span>
                        )}
                    </div>
                </div>
                <div className={cn("grid gap-3", credit ? "grid-cols-2 @2xl:col-span-2" : "grid-cols-1")}>
                    <StatChip
                        value={
                            <span className="text-[17px]">
                                {status.last_call_at ? callWhen(status.last_call_at, summary.timezone, now) : "No calls yet"}
                            </span>
                        }
                        label="Last call"
                    />
                    {credit && (
                        <StatChip
                            value={<span className="text-[17px]">{euros(credit.spendable_eur)}</span>}
                            tone={credit.running_low ? "amber" : undefined}
                            label={
                                credit.minutes_left != null
                                    ? `Credit left · about ${credit.minutes_left} min of calls`
                                    : "Credit left"
                            }
                        />
                    )}
                </div>
            </div>
            {credit?.running_low && !credit.too_low && (
                <p className="mt-3 rounded-lg bg-amber-dim px-3.5 py-2.5 text-sm text-ink-2">
                    Credit is running low. Calls stop when it runs out.{" "}
                    <Link href="/billing" className="font-semibold text-foreground underline">
                        Top up
                    </Link>
                </p>
            )}
            {agentId != null &&
                (onTryAgent ? (
                    <Button variant="soft" className="mt-4 w-full" onClick={onTryAgent}>
                        <Mic aria-hidden />
                        Try your agent
                    </Button>
                ) : (
                    <Button asChild variant="soft" className="mt-4 w-full">
                        <Link href={agentTalkHref(agentId)}>
                            <Mic aria-hidden />
                            Try your agent
                        </Link>
                    </Button>
                ))}
        </Card>
    );
}

interface QuickLink {
    title: string;
    hint: string;
    icon: LucideIcon;
    tone: string;
    href?: string;
    onClick?: () => void;
}

function QuickLinks({ summary, onTryAgent }: { summary: DashboardSummaryResponse; onTryAgent?: () => void }) {
    const { can } = useOrgConfig();
    const agentId = primaryAgentId(summary);
    const links: QuickLink[] = [];
    if (can("reports:read")) {
        links.push(
            { title: "Listen to calls", hint: "Every recording, newest first", icon: Headphones, tone: "bg-sky-dim text-sky", href: "/usage" },
            { title: "Read transcripts", hint: "What callers said, word for word", icon: FileText, tone: "bg-brand-dim text-brand", href: "/usage" },
        );
    }
    if (agentId != null) {
        links.push(
            {
                title: "Opening hours & what it says",
                hint: "Change what your agent tells callers",
                icon: Clock,
                tone: "bg-amber-dim text-amber",
                href: agentFactsHref(agentId),
            },
            onTryAgent
                ? { title: "Try your agent", hint: "Talk to it in your browser", icon: Mic, tone: "bg-panel-2 text-ink-2", onClick: onTryAgent }
                : { title: "Try your agent", hint: "Talk to it in your browser", icon: Mic, tone: "bg-panel-2 text-ink-2", href: agentTalkHref(agentId) },
        );
    }
    if (links.length === 0) return null;
    const className =
        "group flex h-full min-w-0 items-center gap-3.5 rounded-[14px] border border-line bg-panel px-4 py-3.5 text-left shadow-xs outline-none transition-colors hover:border-brand/50 focus-visible:ring-[3px] focus-visible:ring-ring/40";
    return (
        <nav aria-label="Quick links">
            <ul className="grid grid-cols-1 gap-3 @lg:grid-cols-2 @4xl:grid-cols-4 @4xl:gap-4">
                {links.map((link) => {
                    const body = (
                        <>
                            <span className={cn("grid size-10 flex-none place-items-center rounded-[10px]", link.tone)} aria-hidden>
                                <link.icon className="size-5" />
                            </span>
                            <span className="min-w-0 flex-1">
                                <b className="block text-body font-semibold text-foreground">{link.title}</b>
                                <span className="block text-caption text-ink-3">{link.hint}</span>
                            </span>
                            <ArrowRight
                                className="size-4 flex-none text-ink-3 transition-transform group-hover:translate-x-0.5 group-hover:text-brand motion-reduce:transition-none"
                                aria-hidden
                            />
                        </>
                    );
                    return (
                        <li key={link.title}>
                            {link.href ? (
                                <Link href={link.href} className={className}>
                                    {body}
                                </Link>
                            ) : (
                                <button type="button" onClick={link.onClick} className={cn(className, "w-full")}>
                                    {body}
                                </button>
                            )}
                        </li>
                    );
                })}
            </ul>
        </nav>
    );
}

/** A brand-new business: what's set up, and a first call to make. */
function GetStarted({ summary, onTryAgent }: { summary: DashboardSummaryResponse; onTryAgent?: () => void }) {
    const status = summary.agent_status;
    const agentId = primaryAgentId(summary);
    const number = status.phone_numbers[0];
    const steps = [
        { label: "Create your phone agent", done: summary.agents.length > 0, href: "/workflow/create" },
        {
            label: "Link your phone number",
            done: status.phone_numbers.length > 0 && status.reason !== "no_number",
            href: "/telephony-configurations",
        },
        { label: "Take your first call", done: Boolean(status.last_call_at), href: null },
    ];
    return (
        <Card titleId="home-start" title="Let's get your first call in">
            <p className="text-body text-ink-2">
                Your numbers appear here after your agent answers its first call. Three steps get you there:
            </p>
            <ol className="mt-4 flex flex-col gap-3">
                {steps.map((step, i) => (
                    <li key={step.label} className="flex items-center gap-3 text-body">
                        <span
                            className={cn(
                                "grid size-7 flex-none place-items-center rounded-full text-caption font-semibold",
                                step.done ? "bg-brand text-white" : "border border-line bg-panel-2 text-ink-2",
                            )}
                            aria-hidden
                        >
                            {step.done ? <Check className="size-4" /> : i + 1}
                        </span>
                        <span className={cn(step.done ? "text-ink-3 line-through" : "font-medium text-foreground")}>
                            {step.label}
                        </span>
                        <span className="sr-only">{step.done ? "(done)" : "(to do)"}</span>
                    </li>
                ))}
            </ol>
            <div className="mt-5 rounded-xl border border-line bg-panel-2 px-4 py-4">
                {number && status.answering ? (
                    <>
                        <p className="text-body font-semibold text-foreground">Ring your number now</p>
                        <p className="mt-0.5 text-sm text-ink-2">
                            Call <span className="font-semibold tabular-nums text-foreground">{formatPhone(number)}</span> from your mobile
                            and talk to your agent like a customer would. The call shows up here straight away.
                        </p>
                        <Button asChild size="sm" className="mt-3 md:hidden">
                            <a href={telHref(number)}>
                                <Phone aria-hidden />
                                Ring {formatPhone(number)}
                            </a>
                        </Button>
                    </>
                ) : agentId != null ? (
                    <>
                        <p className="text-body font-semibold text-foreground">Try your agent</p>
                        <p className="mt-0.5 text-sm text-ink-2">
                            Talk to it in your browser to hear how it answers. Test calls don&apos;t count on this page.
                        </p>
                        {onTryAgent ? (
                            <Button size="sm" className="mt-3" onClick={onTryAgent}>
                                <Mic aria-hidden />
                                Try your agent
                            </Button>
                        ) : (
                            <Button asChild size="sm" className="mt-3">
                                <Link href={agentTalkHref(agentId)}>
                                    <Mic aria-hidden />
                                    Try your agent
                                </Link>
                            </Button>
                        )}
                    </>
                ) : (
                    <>
                        <p className="text-body font-semibold text-foreground">Start with your agent</p>
                        <p className="mt-0.5 text-sm text-ink-2">Pick a ready-made agent for your kind of business.</p>
                        <Button asChild size="sm" className="mt-3">
                            <Link href="/workflow/create">
                                Create your agent
                                <ArrowRight aria-hidden />
                            </Link>
                        </Button>
                    </>
                )}
            </div>
        </Card>
    );
}

export interface HomeDashboardProps {
    /** The page's one h1: the greeting on Home, the agent's name on an agent. */
    heading: string;
    /** Only this agent's calls. */
    workflowId?: number;
    /** On an agent's own page: open its test panel in place. */
    onTryAgent?: () => void;
}

/**
 * Home: how the phone agent did, what needs the owner, and when people
 * called. Every number is counted from stored calls by the dashboard API.
 */
export function HomeDashboard({ heading, workflowId, onTryAgent }: HomeDashboardProps) {
    useOwnsPageHeading();
    const [range, setRange] = useState<DashboardRange>("today");
    const { result, reload } = useDashboardSummary(range, workflowId);
    const followUps = useFollowUps("open", workflowId);
    const [answering, setAnswering] = useState<FollowUpItem | null>(null);
    // One clock per render, so every relative time agrees.
    const now = new Date();

    const followUpsHref = "/follow-ups";
    const summary = result.state === "ready" ? result.data : null;
    const timezone = summary?.timezone ?? null;

    const header = (
        <header className="flex flex-col gap-3 @4xl:flex-row @4xl:items-end @4xl:justify-between @4xl:gap-6">
            <div className="min-w-0">
                <h1 className="font-display text-[26px] font-semibold leading-tight tracking-[-0.015em] text-foreground sm:text-page">
                    {heading}
                </h1>
                <p className="mt-1 text-body text-ink-3">{rangeSentence(range, now, timezone)}</p>
                {summary && <TodayLine summary={summary} />}
            </div>
            <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center @4xl:flex-nowrap">
                {summary && (
                    <div>
                        <StatusPill summary={summary} />
                    </div>
                )}
                <RangeSwitch value={range} onChange={setRange} />
            </div>
        </header>
    );

    if (result.state === "loading") {
        return (
            <div className="page-body @container flex flex-col gap-5">
                {header}
                <HomeSkeleton withHeader={false} />
            </div>
        );
    }

    if (result.state === "error" || !summary) {
        return (
            <div className="page-body @container flex flex-col gap-5">
                {header}
                <div className="rounded-[14px] border border-line bg-panel">
                    <EmptyState
                        tone="danger"
                        icon={AlertTriangle}
                        title="We couldn't load your calls"
                        description="Check your connection and try again. Your agent keeps answering calls in the meantime."
                        action={
                            <Button variant="soft" onClick={() => void reload()}>
                                <RefreshCw aria-hidden />
                                Try again
                            </Button>
                        }
                    />
                </div>
            </div>
        );
    }

    const attentionItems =
        followUps.result.state === "ready" ? followUps.result.data.items : followUps.result.state === "error" ? null : [];
    const openCount = followUps.result.state === "ready" ? followUps.result.data.open_count : null;
    // Calls: the dashboard. No call yet: the setup steps and the agent
    // instead of empty tiles and charts.
    const setUp = !summary.agent_status.last_call_at;
    const agentId = primaryAgentId(summary);
    const empty = (
        <NoCallsYet
            range={range}
            onRange={setRange}
            tryHref={agentId != null ? agentTalkHref(agentId) : null}
            onTryAgent={onTryAgent}
        />
    );

    return (
        <div className="page-body @container flex min-w-0 flex-col gap-5 @4xl:gap-6">
            {header}
            <NotAnsweringBanner summary={summary} now={now} />

            {setUp && (
                <div className="grid grid-cols-1 gap-4 @4xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] @4xl:gap-5">
                    <GetStarted summary={summary} onTryAgent={onTryAgent} />
                    <AgentCard summary={summary} now={now} onTryAgent={onTryAgent} />
                </div>
            )}

            {!setUp && (
                <>
                    <Tiles summary={summary} now={now} />
                    {/* Two columns on a computer, the right one (the charts)
                        growing with the screen and the agent card under the
                        calls so the columns end level; on a phone one list in
                        the design's order: attention, what callers wanted,
                        hours, recent calls, agent. */}
                    <div className="flex flex-col gap-4 @4xl:grid @4xl:grid-cols-[minmax(0,1.5fr)_minmax(400px,1fr)] @4xl:items-start @4xl:gap-5">
                        <div className="contents @4xl:flex @4xl:min-w-0 @4xl:flex-col @4xl:gap-5">
                            <div className="order-1 min-w-0 @4xl:order-none">
                                <Attention
                                    items={attentionItems}
                                    openCount={openCount}
                                    timezone={summary.timezone}
                                    now={now}
                                    followUpsHref={followUpsHref}
                                    onAddAnswer={setAnswering}
                                />
                            </div>
                            <div className="order-4 min-w-0 @4xl:order-none">
                                <RecentCalls summary={summary} now={now} empty={empty} />
                            </div>
                            <div className="order-5 min-w-0 @4xl:order-none">
                                <AgentCard summary={summary} now={now} onTryAgent={onTryAgent} />
                            </div>
                        </div>
                        <div className="contents @4xl:flex @4xl:min-w-0 @4xl:flex-col @4xl:gap-5">
                            <div className="order-2 min-w-0 @4xl:order-none">
                                <CallersWanted summary={summary} empty={empty} />
                            </div>
                            <div className="order-3 min-w-0 @4xl:order-none">
                                <WhenPeopleCalled summary={summary} empty={empty} />
                            </div>
                        </div>
                    </div>
                </>
            )}

            <QuickLinks summary={summary} onTryAgent={onTryAgent} />
            <AddAnswerDialog item={answering} onClose={() => setAnswering(null)} />
        </div>
    );
}
