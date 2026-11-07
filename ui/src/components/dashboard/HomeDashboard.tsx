"use client";

import {
    AlertTriangle,
    ArrowRight,
    Check,
    CheckCircle2,
    Clock,
    FileText,
    Headphones,
    type LucideIcon,
    Mic,
    Phone,
    PhoneForwarded,
    PhoneOff,
    Play,
    RefreshCw,
} from "lucide-react";
import Link from "next/link";
import { type ReactNode, useState } from "react";

import { formatPhone } from "@/app/usage/callsView";
import type {
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
    callerWords,
    callLength,
    callsTileLabel,
    callWhen,
    changeWords,
    euros,
    followUpKey,
    lastCallWords,
    notAnsweringWords,
    RANGE_OPTIONS,
    rangeSentence,
    RESULT_WORDS,
    telHref,
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
            <header className="flex items-center justify-between gap-3 px-[18px] pt-4">
                <h2 id={titleId} className="flex items-center gap-2 font-display text-[15px] font-semibold text-foreground">
                    {title}
                </h2>
                {action}
            </header>
            <div className="@container px-[18px] pb-[18px] pt-3.5">{children}</div>
        </section>
    );
}

function CardLink({ href, children }: { href: string; children: ReactNode }) {
    return (
        <Link href={href} className="whitespace-nowrap text-[13px] font-semibold text-brand hover:underline">
            {children}
        </Link>
    );
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
                        "flex-1 rounded-[7px] px-3 py-1.5 text-[13px] font-medium outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/40 sm:flex-none",
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
        <span className="inline-flex max-w-full items-center gap-2 rounded-full border border-line bg-panel py-[5px] pl-2.5 pr-3 text-[12.5px] text-ink-2">
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

function NotAnsweringBanner({ summary, now }: { summary: DashboardSummaryResponse; now: Date }) {
    const { can } = useOrgConfig();
    const reason = summary.agent_status.reason;
    if (summary.agent_status.answering || !reason) return null;
    const words = notAnsweringWords(reason);
    return (
        <div
            role="alert"
            className="flex flex-col gap-3 rounded-[14px] border border-danger/40 border-l-[4px] border-l-danger bg-danger-dim px-[18px] py-3.5 sm:flex-row sm:items-center"
        >
            <AlertTriangle className="hidden size-5 flex-none text-danger sm:block" aria-hidden />
            <div className="min-w-0 flex-1">
                <p className="text-[14px] font-semibold text-foreground">{words.title}</p>
                <p className="mt-0.5 text-[13px] text-ink-2">
                    {words.detail}
                    {reason !== "no_agent" && <> {lastCallWords(summary.agent_status.last_call_at, now)}.</>}
                </p>
            </div>
            {can(words.fix.requires) ? (
                <Button asChild size="sm" variant="destructive" className="self-start sm:self-auto">
                    <Link href={words.fix.href}>{words.fix.label}</Link>
                </Button>
            ) : (
                <p className="text-[12.5px] text-ink-2">Ask the owner of your account to fix this.</p>
            )}
        </div>
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
        <div className="flex min-w-0 flex-col gap-1.5 rounded-[14px] border border-line bg-panel px-4 py-4 shadow-xs sm:px-[18px]">
            <div className="flex items-center gap-2 text-[13px] font-medium text-ink-2">
                <span className={cn("hidden size-7 flex-none place-items-center rounded-lg sm:grid", tone)} aria-hidden>
                    <Icon className="size-4" />
                </span>
                {shortLabel ? (
                    <>
                        <span className="min-w-0 sm:hidden">{shortLabel}</span>
                        <span className="hidden min-w-0 sm:inline">{label}</span>
                    </>
                ) : (
                    <span className="min-w-0">{label}</span>
                )}
            </div>
            <div className="font-display text-[28px] font-semibold leading-tight tracking-[-0.02em] tabular-nums text-foreground sm:text-[32px]">
                {value}
            </div>
            {phoneCaption && <div className="text-[12.5px] leading-snug text-ink-3 sm:hidden">{phoneCaption}</div>}
            {caption && <div className="hidden text-[12.5px] leading-snug text-ink-3 sm:block">{caption}</div>}
        </div>
    );
}

function Tiles({ summary, now }: { summary: DashboardSummaryResponse; now: Date }) {
    const t = summary.tiles;
    const change = changeWords(summary.range, summary.calls_change, now, summary.timezone);
    const average = callLength(t.average_call_seconds);
    return (
        <div className="grid grid-cols-2 gap-3 @3xl:grid-cols-4 @3xl:gap-4">
            <Tile
                icon={Phone}
                tone="bg-sky-dim text-sky"
                label={callsTileLabel(summary.range)}
                shortLabel="Calls"
                value={t.calls}
                phoneCaption={change ? <>{change.amount && <span className={cn("font-semibold", change.sign === "up" ? "text-brand" : "text-ink-2")}>{change.amount}</span>}{change.rest}</> : null}
                caption={
                    change ? (
                        <>
                            {change.amount && (
                                <span className={cn("font-semibold", change.sign === "up" ? "text-brand" : "text-ink-2")}>
                                    {change.amount}
                                </span>
                            )}
                            {change.rest}
                        </>
                    ) : average ? (
                        `Average call ${average}`
                    ) : null
                }
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
                            <small className="ml-1 text-[15px] font-medium text-ink-3">{t.handled_percent}%</small>
                        )}
                    </>
                }
                caption="Answered start to finish, no staff needed"
            />
            <Tile
                icon={PhoneForwarded}
                tone="bg-amber-dim text-amber"
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
            <Tile
                icon={PhoneOff}
                tone="bg-danger-dim text-danger"
                label="Hung up without speaking"
                value={t.hung_up_silent}
                caption="Callers who rang off before saying anything"
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
                    {openCount ? <Chip tone="amber">{openCount}</Chip> : null}
                </>
            }
            action={<CardLink href={followUpsHref}>All follow-ups</CardLink>}
        >
            {items === null ? (
                <p className="py-4 text-[13px] text-ink-3">Couldn&apos;t load follow-ups. They&apos;re on the Follow-ups page.</p>
            ) : items.length === 0 ? (
                <div className="flex items-center gap-3 py-3">
                    <span className="grid size-9 flex-none place-items-center rounded-full bg-brand-dim text-brand" aria-hidden>
                        <CheckCircle2 className="size-5" />
                    </span>
                    <div>
                        <p className="text-[13.5px] font-semibold text-foreground">All caught up</p>
                        <p className="text-[12.5px] text-ink-3">No callers are waiting on you.</p>
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
                                canMark && (item.kind === "unanswered_question" || item.kind === "time_was_full")
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
        return <span className="block size-7" aria-hidden />;
    }
    return (
        <Link
            href={runDetailHref(call.workflow_id, call.run_id, returnTo)}
            className="grid size-7 place-items-center rounded-full bg-brand-dim text-brand outline-none hover:bg-brand hover:text-white focus-visible:ring-[3px] focus-visible:ring-ring/40"
            aria-label={`Listen to the call from ${callerWords(call)}`}
        >
            <Play className="size-3 fill-current" aria-hidden />
        </Link>
    );
}

function RecentCalls({ summary, now }: { summary: DashboardSummaryResponse; now: Date }) {
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
                <p className="py-4 text-[13px] text-ink-3">
                    No calls {summary.range === "today" ? "yet today" : `in the last ${summary.range === "7d" ? "7" : "30"} days`}.
                </p>
            ) : (
                <>
                    {/* Phone: a simple list */}
                    <ul className="flex flex-col @xl:hidden">
                        {calls.map((call) => (
                            <li key={call.run_id} className="flex items-start gap-3 border-t border-line-soft py-2.5 first:border-t-0">
                                <PlayLink call={call} returnTo={returnTo} />
                                <CallerLink call={call} className="min-w-0 flex-1 outline-none focus-visible:underline">
                                    <span className="block truncate text-[13.5px] font-semibold text-foreground">{callerWords(call)}</span>
                                    {call.summary && <span className="mt-0.5 block text-[12.5px] leading-snug text-ink-2">{call.summary}</span>}
                                    <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] tabular-nums text-ink-3">
                                        <Chip tone={chipFor(call).tone}>{chipFor(call).label}</Chip>
                                        {callWhen(call.created_at, summary.timezone, now)}
                                    </span>
                                </CallerLink>
                            </li>
                        ))}
                    </ul>
                    {/* Computer: the table from the design */}
                    <table className="hidden w-full text-left text-[13px] @xl:table">
                        <thead>
                            <tr className="border-b border-line text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">
                                <th className="w-10 pb-2.5" scope="col">
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
                                    <td className="py-2.5 align-top">
                                        <PlayLink call={call} returnTo={returnTo} />
                                    </td>
                                    <td className="w-[28%] py-2.5 pr-3 align-top">
                                        <CallerLink call={call} className="font-semibold text-foreground hover:underline">
                                            {callerWords(call)}
                                        </CallerLink>
                                        {call.caller_name && call.caller_number && (
                                            <div className="text-[12px] tabular-nums text-ink-3">{formatPhone(call.caller_number)}</div>
                                        )}
                                    </td>
                                    <td className="py-2.5 pr-3 align-top text-ink-2">
                                        {call.summary ?? (
                                            <span className="text-ink-3">
                                                {callLength(call.duration_seconds) ? `${callLength(call.duration_seconds)} call` : "—"}
                                            </span>
                                        )}
                                    </td>
                                    <td className="py-2.5 pr-3 align-top">
                                        <Chip tone={chipFor(call).tone}>{chipFor(call).label}</Chip>
                                    </td>
                                    <td className="whitespace-nowrap py-2.5 text-right align-top tabular-nums text-ink-2">
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

function WhenPeopleCalled({ summary }: { summary: DashboardSummaryResponse }) {
    const sub =
        summary.range === "today"
            ? "Calls per hour, today"
            : `Calls per hour, last ${summary.range === "7d" ? "7" : "30"} days`;
    return (
        <Card titleId="home-hours" title="When people called" action={<span className="text-[13px] text-ink-3">{sub}</span>}>
            {summary.tiles.calls === 0 ? (
                <p className="py-4 text-[13px] text-ink-3">No calls in this time yet.</p>
            ) : (
                <HourlyCallsChart hours={summary.calls_by_hour} caption={sub} />
            )}
        </Card>
    );
}

function rangeWords(range: DashboardRange): string {
    return range === "today" ? "Today" : range === "7d" ? "Last 7 days" : "Last 30 days";
}

/** The doc's small figures under the ring: real counts only. */
function StatChip({ value, label }: { value: ReactNode; label: string }) {
    return (
        <div className="min-w-0 rounded-[10px] bg-panel-2 px-3.5 py-2.5">
            <div className="font-display text-[17px] font-semibold tabular-nums text-foreground">{value}</div>
            <div className="text-[12px] text-ink-3">{label}</div>
        </div>
    );
}

function CallersWanted({ summary }: { summary: DashboardSummaryResponse }) {
    const reasons = summary.callers_wanted;
    const bookings = summary.wording.bookings_label;
    const average = callLength(summary.tiles.average_call_seconds);
    const when = rangeWords(summary.range);
    return (
        <Card
            titleId="home-wanted"
            title="What callers wanted"
            action={<span className="text-[13px] text-ink-3">{when}</span>}
        >
            {reasons.length === 0 ? (
                <p className="py-4 text-[13px] text-ink-3">No calls in this time yet.</p>
            ) : (
                <CallersWantedChart reasons={reasons} caption={`What callers wanted, ${when.toLowerCase()}`} />
            )}
            {(bookings || average) && summary.tiles.calls > 0 && (
                <div className="mt-4 grid grid-cols-2 gap-2.5">
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
            <dl className="flex flex-col gap-3 text-[13px]">
                <div className="flex items-center justify-between gap-3">
                    <dt className="text-ink-3">Status</dt>
                    <dd className="flex items-center gap-1.5 font-semibold text-foreground">
                        <span className={cn("size-2 rounded-full", status.answering ? "bg-brand" : "bg-danger")} aria-hidden />
                        {status.answering ? "Answering calls" : "Not answering"}
                    </dd>
                </div>
                <div className="flex items-start justify-between gap-3">
                    <dt className="text-ink-3">{status.phone_numbers.length > 1 ? "Phone numbers" : "Phone number"}</dt>
                    <dd className="text-right font-semibold tabular-nums text-foreground">
                        {status.phone_numbers.length ? (
                            status.phone_numbers.map((n) => <div key={n}>{n}</div>)
                        ) : (
                            <span className="font-normal text-ink-3">None linked</span>
                        )}
                    </dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                    <dt className="text-ink-3">Last call</dt>
                    <dd className="text-right text-foreground">
                        {status.last_call_at ? callWhen(status.last_call_at, summary.timezone, now) : "No calls yet"}
                    </dd>
                </div>
                {credit && (
                    <div className="flex items-start justify-between gap-3">
                        <dt className="text-ink-3">Credit left</dt>
                        <dd className="text-right">
                            <span className={cn("font-semibold tabular-nums", credit.running_low ? "text-amber" : "text-foreground")}>
                                {euros(credit.spendable_eur)}
                            </span>
                            {credit.minutes_left != null && (
                                <span className="block text-[12px] text-ink-3">about {credit.minutes_left} minutes of calls</span>
                            )}
                        </dd>
                    </div>
                )}
            </dl>
            {credit?.running_low && !credit.too_low && (
                <p className="mt-3 rounded-lg bg-amber-dim px-3 py-2 text-[12.5px] text-ink-2">
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
        "flex h-full min-w-0 items-center gap-3 rounded-xl border border-line bg-panel px-3.5 py-3 text-left shadow-xs outline-none transition-colors hover:border-brand/50 focus-visible:ring-[3px] focus-visible:ring-ring/40";
    return (
        <nav aria-label="Quick links">
            <ul className="grid grid-cols-1 gap-3 @lg:grid-cols-2 @4xl:grid-cols-4">
                {links.map((link) => {
                    const body = (
                        <>
                            <span className={cn("grid size-[34px] flex-none place-items-center rounded-[9px]", link.tone)} aria-hidden>
                                <link.icon className="size-[18px]" />
                            </span>
                            <span className="min-w-0">
                                <b className="block text-[13.5px] font-semibold text-foreground">{link.title}</b>
                                <span className="block text-[12px] text-ink-3">{link.hint}</span>
                            </span>
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
            <p className="text-[13px] text-ink-2">
                Your numbers appear here after your agent answers its first call. Three steps get you there:
            </p>
            <ol className="mt-4 flex flex-col gap-2.5">
                {steps.map((step, i) => (
                    <li key={step.label} className="flex items-center gap-3 text-[13.5px]">
                        <span
                            className={cn(
                                "grid size-6 flex-none place-items-center rounded-full text-[12px] font-semibold",
                                step.done ? "bg-brand text-white" : "border border-line bg-panel-2 text-ink-2",
                            )}
                            aria-hidden
                        >
                            {step.done ? <Check className="size-3.5" /> : i + 1}
                        </span>
                        <span className={cn(step.done ? "text-ink-3 line-through" : "font-medium text-foreground")}>
                            {step.label}
                        </span>
                        <span className="sr-only">{step.done ? "(done)" : "(to do)"}</span>
                    </li>
                ))}
            </ol>
            <div className="mt-5 rounded-xl border border-line bg-panel-2 px-4 py-3.5">
                {number && status.answering ? (
                    <>
                        <p className="text-[13.5px] font-semibold text-foreground">Ring your number now</p>
                        <p className="mt-0.5 text-[12.5px] text-ink-2">
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
                        <p className="text-[13.5px] font-semibold text-foreground">Try your agent</p>
                        <p className="mt-0.5 text-[12.5px] text-ink-2">
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
                        <p className="text-[13.5px] font-semibold text-foreground">Start with your agent</p>
                        <p className="mt-0.5 text-[12.5px] text-ink-2">Pick a ready-made agent for your kind of business.</p>
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
        <header className="flex flex-col gap-3 @4xl:flex-row @4xl:items-end @4xl:justify-between @4xl:gap-4">
            <div className="min-w-0">
                <h1 className="font-display text-[24px] font-semibold tracking-[-0.01em] text-foreground lg:text-[26px]">
                    {heading}
                </h1>
                <p className="mt-1 text-[14px] text-ink-3">{rangeSentence(range, now, timezone)}</p>
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

    return (
        <div className="page-body @container flex min-w-0 flex-col gap-5">
            {header}
            <NotAnsweringBanner summary={summary} now={now} />

            {setUp && (
                <div className="grid grid-cols-1 gap-4 @4xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
                    <GetStarted summary={summary} onTryAgent={onTryAgent} />
                    <AgentCard summary={summary} now={now} onTryAgent={onTryAgent} />
                </div>
            )}

            {!setUp && (
                <>
                    <Tiles summary={summary} now={now} />
                    {/* Two columns on a computer; on a phone one list in the
                        design's order: attention, what callers wanted, hours,
                        recent calls, agent. */}
                    <div className="flex flex-col gap-4 @4xl:flex-row @4xl:items-start">
                        <div className="contents @4xl:flex @4xl:w-[58%] @4xl:min-w-0 @4xl:flex-col @4xl:gap-4">
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
                                <RecentCalls summary={summary} now={now} />
                            </div>
                        </div>
                        <div className="contents @4xl:flex @4xl:min-w-0 @4xl:flex-1 @4xl:flex-col @4xl:gap-4">
                            <div className="order-2 min-w-0 @4xl:order-none">
                                <CallersWanted summary={summary} />
                            </div>
                            <div className="order-3 min-w-0 @4xl:order-none">
                                <WhenPeopleCalled summary={summary} />
                            </div>
                            <div className="order-5 min-w-0 @4xl:order-none">
                                <AgentCard summary={summary} now={now} onTryAgent={onTryAgent} />
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
