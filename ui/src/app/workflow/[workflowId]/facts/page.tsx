"use client";

import { AlertCircle, BookOpenText, Check, CircleDashed, MessageSquarePlus, Mic, Play } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    getBusinessFactsApiV1WorkflowWorkflowIdBusinessFactsGet,
    setAiBookingApiV1IntegrationsBookingsCalendarsConnectionIdPut,
    updateBusinessFactsApiV1WorkflowWorkflowIdBusinessFactsPut,
} from "@/client/sdk.gen";
import type { BusinessFact, FollowUpItem } from "@/client/types.gen";
import { AddAnswerDialog } from "@/components/dashboard/AddAnswerDialog";
import { appendAnswer, callWhen } from "@/components/dashboard/dashboardView";
import { useFollowUps } from "@/components/dashboard/useDashboardData";
import { useOwnsPageHeading } from "@/components/layout/pageHeading";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { agentTalkHref } from "@/components/workflow/agentLinks";
import { useAgentShell } from "@/context/AgentShellContext";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { detailFromError } from "@/lib/apiError";
import { cn } from "@/lib/utils";

import { SectionError, SectionMessage } from "../components/SectionStates";
import { bookingLine, bookingTimesByDay, bookingTitle, fillGreeting, WEEK, WEEK_LONG } from "./knowledge";
import { TransferOptions } from "./TransferOptions";
import { type AgentKnowledge, type CalendarInfo, useAgentKnowledge } from "./useAgentKnowledge";
import { VoiceChips } from "./VoiceChips";

const LOAD_FAILED = "We couldn't load what your agent knows";
const SAVE_FAILED = "Couldn't save. Please try again.";

/** Facts with a place of their own on this page; any others join "Your business". */
const FAQ_KEY = "extra_info";
const TRANSFER_KEY = "transfer_number";
const BUSINESS_ORDER = ["business_name", "business_description", "address", "opening_hours", "website"];

/** Owner wording for a fact's row, where it differs from the template's question. */
const ROW_COPY: Record<string, { label?: string; help?: string }> = {
    address: { help: "Read out when callers ask" },
    opening_hours: { help: "What your agent tells callers" },
    website: { label: "Website or menu link" },
};

/**
 * "What your agent knows" (mocks/agent.png): the business details, answers
 * and switches an owner changes without the agent editor, beside how the
 * agent sounds and whether it is ready for calls. Only stored data is shown;
 * the full editor stays one click away under Advanced setup.
 */
export default function WhatYourAgentKnowsPage() {
    const params = useParams<{ workflowId: string }>();
    const workflowId = Number(params.workflowId);
    useOwnsPageHeading();
    useRoomForTheForm();
    useOpenTesterFromOnboarding();

    const { can } = useOrgConfig();
    const canEdit = can("agents:facts");
    const knowledge = useAgentKnowledge(workflowId);

    const [facts, setFacts] = useState<BusinessFact[] | null>(null);
    const [values, setValues] = useState<Record<string, string>>({});
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    // Set synchronously so a double click can't send two saves.
    const savingRef = useRef(false);
    // Required-field messages show once the owner has tried to save.
    const [triedSave, setTriedSave] = useState(false);
    const [answering, setAnswering] = useState<FollowUpItem | null>(null);

    const load = useCallback(async () => {
        setError(null);
        setFacts(null);
        try {
            const res = await getBusinessFactsApiV1WorkflowWorkflowIdBusinessFactsGet({
                path: { workflow_id: workflowId },
            });
            if (res.error || !res.data) {
                setError(LOAD_FAILED);
                return;
            }
            setFacts(res.data.facts);
            setValues(Object.fromEntries(res.data.facts.map((f) => [f.key, f.value])));
        } catch {
            setError(LOAD_FAILED);
        }
    }, [workflowId]);

    useEffect(() => {
        void load();
    }, [load]);

    const changed = (facts ?? []).filter((f) => (values[f.key] ?? "") !== f.value);
    const missing = new Set(
        (facts ?? []).filter((f) => f.required && !(values[f.key] ?? "").trim()).map((f) => f.key),
    );

    const save = async () => {
        if (savingRef.current || changed.length === 0) return;
        setTriedSave(true);
        if (missing.size > 0) {
            toast.error("Fill in the required answers before saving.");
            return;
        }
        savingRef.current = true;
        setSaving(true);
        try {
            const res = await updateBusinessFactsApiV1WorkflowWorkflowIdBusinessFactsPut({
                path: { workflow_id: workflowId },
                body: { facts: Object.fromEntries(changed.map((f) => [f.key, values[f.key] ?? ""])) },
            });
            if (res.error || !res.data) {
                toast.error(detailFromError(res.error, SAVE_FAILED));
                return;
            }
            setFacts(res.data.facts);
            setValues(Object.fromEntries(res.data.facts.map((f) => [f.key, f.value])));
            setTriedSave(false);
            toast.success("Saved. Your agent uses these from its next call.");
        } catch {
            toast.error(SAVE_FAILED);
        } finally {
            savingRef.current = false;
            setSaving(false);
        }
    };

    const discard = () => {
        if (!facts) return;
        setValues(Object.fromEntries(facts.map((f) => [f.key, f.value])));
        setTriedSave(false);
    };

    // An answer added from a caller's question is saved straight away; keep
    // any unsaved edits to the answers and add it to them too.
    const answerAdded = (answers: string, added: { question: string; answer: string }) => {
        const before = facts?.find((f) => f.key === FAQ_KEY)?.value ?? "";
        const local = values[FAQ_KEY] ?? "";
        setFacts((current) => current?.map((f) => (f.key === FAQ_KEY ? { ...f, value: answers } : f)) ?? current);
        setValues((v) => ({
            ...v,
            [FAQ_KEY]: local === before ? answers : appendAnswer(local, added.question, added.answer),
        }));
    };

    const field = (fact: BusinessFact, opts: { rows?: number; className?: string } = {}) => (
        <FactField
            fact={fact}
            value={values[fact.key] ?? ""}
            onChange={(value) => setValues((v) => ({ ...v, [fact.key]: value }))}
            disabled={!canEdit || saving}
            invalid={triedSave && missing.has(fact.key)}
            rows={opts.rows}
            className={opts.className}
        />
    );

    const byKey = new Map((facts ?? []).map((f) => [f.key, f]));
    const businessFacts = (facts ?? [])
        .filter((f) => f.key !== FAQ_KEY && f.key !== TRANSFER_KEY)
        .sort((a, b) => rank(a.key) - rank(b.key));
    const faq = byKey.get(FAQ_KEY);
    const transfer = byKey.get(TRANSFER_KEY);

    return (
        <div className="page-body @container">
            <header className="mb-5 flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
                <div className="min-w-0 max-w-2xl">
                    <h1 className="font-display text-[24px] font-semibold leading-tight tracking-[-0.02em] text-foreground">
                        What your agent knows
                    </h1>
                    <p className="mt-1.5 text-[14.5px] text-ink-2">
                        Change these any time. Your agent uses them on the next call.
                    </p>
                </div>
                {facts && facts.length > 0 && (
                    canEdit ? (
                        <div className="flex flex-wrap items-center gap-2.5">
                            {changed.length > 0 && !saving && (
                                <span className="text-[12.5px] text-ink-3" role="status">
                                    {changed.length === 1 ? "1 unsaved change" : `${changed.length} unsaved changes`}
                                </span>
                            )}
                            <Button
                                variant="outline"
                                className="h-9"
                                disabled={saving || changed.length === 0}
                                onClick={discard}
                            >
                                Discard
                            </Button>
                            <Button className="h-9" onClick={() => void save()} disabled={saving || changed.length === 0}>
                                {saving ? "Saving…" : "Save changes"}
                            </Button>
                        </div>
                    ) : (
                        <p className="text-sm text-ink-3">Only the owner or an admin can change these.</p>
                    )
                )}
            </header>

            {error ? (
                <SectionError title={error} onRetry={() => void load()} />
            ) : !facts ? (
                <div className="flex flex-col gap-5" aria-busy="true" aria-label="Loading what your agent knows">
                    {[0, 1, 2].map((i) => (
                        <div key={i} className="flex flex-col gap-1.5">
                            <Skeleton className="h-4 w-36" />
                            <Skeleton className="h-10 w-full" />
                        </div>
                    ))}
                </div>
            ) : facts.length === 0 ? (
                <SectionMessage icon={<BookOpenText />} title="This agent has no business details to edit here.">
                    Agents made from a ready-made template keep their opening hours, address and answers here.
                    This one was built differently, so its wording lives in the{" "}
                    <Link
                        href={`/workflow/${workflowId}`}
                        className="font-medium text-brand underline-offset-2 hover:underline"
                    >
                        conversation
                    </Link>{" "}
                    itself.
                </SectionMessage>
            ) : (
                <div className="grid items-start gap-4 @4xl:grid-cols-[minmax(0,1fr)_340px]">
                    <div className="flex min-w-0 flex-col gap-4">
                        <Card title="Your business" id="your-business">
                            {businessFacts.map((fact) => (
                                <FactRow key={fact.key} fact={fact}>
                                    {field(fact, { rows: 2 })}
                                </FactRow>
                            ))}
                            <BookingTimesRow calendar={knowledge.calendar} />
                        </Card>

                        {faq && (
                            <Card title="Answers to common questions" id="common-questions">
                                <div className="flex flex-col gap-1.5 py-3">
                                    <Label htmlFor={`fact-${faq.key}`} className="text-[13.5px] font-semibold">
                                        Anything else callers often ask?
                                    </Label>
                                    <p className="text-[12.5px] text-ink-3">
                                        {faq.help ?? "Parking, prices, payment options, languages you speak."} Write
                                        each answer in plain words; your agent reads them out as needed.
                                    </p>
                                    <UnansweredQuestions
                                        workflowId={workflowId}
                                        onAdd={canEdit ? setAnswering : undefined}
                                    />
                                    {field(faq, { rows: 5, className: "mt-1" })}
                                </div>
                            </Card>
                        )}

                        <CanDo
                            calendar={knowledge.calendar}
                            setCalendar={knowledge.setCalendar}
                            transfer={transfer}
                            transferField={
                                transfer ? (
                                    <>
                                        {field(transfer)}
                                        <TransferOptions
                                            workflowId={workflowId}
                                            value={values[transfer.key] ?? ""}
                                            disabled={!canEdit || saving}
                                        />
                                    </>
                                ) : null
                            }
                            transferValue={transfer ? (values[transfer.key] ?? "").trim() : ""}
                        />
                    </div>

                    <div className="flex min-w-0 flex-col gap-4">
                        <HowItSounds workflowId={workflowId} knowledge={knowledge} values={values} />
                        <ReadyForCalls workflowId={workflowId} facts={facts} knowledge={knowledge} />
                    </div>
                </div>
            )}
            <AddAnswerDialog item={answering} onClose={() => setAnswering(null)} onSaved={answerAdded} />
        </div>
    );
}

/**
 * Questions callers asked that the agent couldn't answer (from the call
 * reviews, still on the to-do list), each with Add answer.
 */
function UnansweredQuestions({ workflowId, onAdd }: { workflowId: number; onAdd?: (item: FollowUpItem) => void }) {
    const { result } = useFollowUps("open", workflowId);
    if (result.state !== "ready") return null;
    const items = result.data.items.filter((item) => item.kind === "unanswered_question" && item.questions.length > 0);
    if (items.length === 0) return null;
    return (
        <ul className="my-1.5 flex flex-col gap-2" aria-label="Questions without an answer">
            {items.map((item) => (
                <li
                    key={item.run_id}
                    className="flex flex-col gap-2 rounded-[10px] border border-sky/50 bg-sky-dim px-3.5 py-2.5 @md/card:flex-row @md/card:items-center"
                >
                    <div className="min-w-0 flex-1">
                        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13.5px] font-semibold text-foreground">
                            {item.questions.join(" ")}
                            <span className="rounded-full bg-panel px-2 py-px text-[11.5px] font-semibold text-sky">
                                Asked {callWhen(item.created_at, null)}
                            </span>
                        </p>
                        <p className="mt-0.5 text-[12.5px] text-sky">No answer yet. Add one so your agent can help next time.</p>
                    </div>
                    {onAdd && (
                        <Button type="button" size="sm" variant="outline" className="self-start @md/card:self-auto" onClick={() => onAdd(item)}>
                            <MessageSquarePlus aria-hidden />
                            Add answer
                        </Button>
                    )}
                </li>
            ))}
        </ul>
    );
}

function rank(key: string): number {
    const index = BUSINESS_ORDER.indexOf(key);
    return index === -1 ? BUSINESS_ORDER.length : index;
}

/**
 * This page is the mock's two columns: it starts with the test rail closed
 * (Try your agent opens it) and leaves it open again for the other screens.
 */
function useRoomForTheForm() {
    const { setRailOpen } = useAgentShell();
    useEffect(() => {
        setRailOpen(false);
        return () => setRailOpen(true);
    }, [setRailOpen]);
}

/**
 * Straight after creating an agent the wizard can send the owner here with
 * ?onboarding=web_call: open the test panel once, then drop the flag so a
 * refresh or Back doesn't open it again.
 */
function useOpenTesterFromOnboarding() {
    const searchParams = useSearchParams();
    const router = useRouter();
    const pathname = usePathname();
    const { openTester } = useAgentShell();
    const opened = useRef(false);

    useEffect(() => {
        if (opened.current || searchParams.get("onboarding") !== "web_call") return;
        opened.current = true;
        openTester();
        const next = new URLSearchParams(searchParams.toString());
        next.delete("onboarding");
        const query = next.toString();
        router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    }, [openTester, pathname, router, searchParams]);
}

/**
 * Open the test panel and move focus to its start button, so the click does
 * something visible even when the panel is already open beside the page.
 */
function talkToAgent(openTester: () => void) {
    openTester();
    // The sheet mounts on the next frames; the desktop rail is already there.
    window.setTimeout(() => {
        const buttons = document.querySelectorAll<HTMLButtonElement>("[data-test-call-start]");
        const visible = Array.from(buttons).find((b) => b.offsetParent !== null && !b.disabled);
        visible?.focus();
    }, 350);
}

function Card({
    title,
    id,
    action,
    children,
    className,
}: {
    title: string;
    id: string;
    action?: ReactNode;
    children: ReactNode;
    className?: string;
}) {
    return (
        <section
            aria-labelledby={`${id}-title`}
            className={cn("@container/card rounded-xl border border-line bg-panel px-5 pb-3 pt-4", className)}
        >
            <div className="mb-1 flex items-center justify-between gap-3">
                <h2 id={`${id}-title`} className="font-display text-[15.5px] font-semibold text-foreground">
                    {title}
                </h2>
                {action}
            </div>
            {children}
        </section>
    );
}

/** Label on the left, field on the right (stacked when the card is narrow). */
function Row({ label, help, htmlFor, children }: { label: ReactNode; help?: ReactNode; htmlFor?: string; children: ReactNode }) {
    return (
        <div className="grid gap-1.5 border-t border-line-soft py-3 first:border-t-0 @xl/card:grid-cols-[190px_minmax(0,1fr)] @xl/card:items-center @xl/card:gap-4">
            <div className="min-w-0">
                {htmlFor ? (
                    <Label htmlFor={htmlFor} className="text-[13.5px] font-semibold">
                        {label}
                    </Label>
                ) : (
                    <p className="text-[13.5px] font-semibold text-foreground">{label}</p>
                )}
                {help && <p className="mt-0.5 text-[12px] text-ink-3">{help}</p>}
            </div>
            <div className="min-w-0">{children}</div>
        </div>
    );
}

function FactRow({ fact, children }: { fact: BusinessFact; children: ReactNode }) {
    const copy = ROW_COPY[fact.key] ?? {};
    return (
        <Row
            htmlFor={`fact-${fact.key}`}
            label={copy.label ?? fact.label}
            help={[copy.help ?? fact.help, fact.required ? null : "Optional"].filter(Boolean).join(" · ") || undefined}
        >
            {children}
        </Row>
    );
}

function FactField({
    fact,
    value,
    onChange,
    disabled,
    invalid,
    rows = 3,
    className,
}: {
    fact: BusinessFact;
    value: string;
    onChange: (value: string) => void;
    disabled: boolean;
    invalid: boolean;
    rows?: number;
    className?: string;
}) {
    const id = `fact-${fact.key}`;
    const errorId = `${id}-error`;
    const common = {
        id,
        value,
        maxLength: fact.max_length,
        disabled,
        required: fact.required,
        "aria-invalid": invalid || undefined,
        "aria-describedby": invalid ? errorId : undefined,
        placeholder: fact.placeholder ? `e.g. ${fact.placeholder}` : undefined,
    };
    return (
        <>
            {fact.type === "textarea" ? (
                <Textarea
                    {...common}
                    rows={rows}
                    className={cn("min-h-0 text-[13.5px]", className)}
                    onChange={(e) => onChange(e.target.value)}
                />
            ) : (
                <Input
                    {...common}
                    type={fact.type === "phone" ? "tel" : fact.type === "url" ? "url" : "text"}
                    className={cn("h-9 text-[13.5px]", className)}
                    onChange={(e) => onChange(e.target.value)}
                />
            )}
            {invalid && (
                <p id={errorId} className="mt-1 text-[12.5px] text-danger">
                    Your agent needs this answer. Please fill it in.
                </p>
            )}
        </>
    );
}

/**
 * The calendar's booking times as day chips, only when the calendar this
 * agent books on has them stored. They are changed on Bookings.
 */
function BookingTimesRow({ calendar }: { calendar: CalendarInfo }) {
    if (calendar.state !== "ready") return null;
    const days = bookingTimesByDay(calendar.rules);
    if (!days) return null;
    return (
        <Row
            label="Booking times"
            help={
                <>
                    From your calendar.{" "}
                    <Link href="/bookings" className="font-medium text-brand underline-offset-2 hover:underline">
                        Change on Bookings
                    </Link>
                </>
            }
        >
            <ul className="grid grid-cols-2 gap-1.5 @md/card:grid-cols-4 @2xl/card:grid-cols-7" aria-label="Booking times by day">
                {days.map((windows, day) => (
                    <li
                        key={WEEK[day]}
                        className={cn(
                            "rounded-[9px] border border-line px-2 py-1.5 text-center text-[12px] leading-snug",
                            windows.length === 0 && "bg-panel-2 text-ink-3",
                        )}
                    >
                        <abbr title={WEEK_LONG[day]} className="block text-[12.5px] font-semibold no-underline">
                            {WEEK[day]}
                        </abbr>
                        {windows.length === 0 ? "No bookings" : windows.map((w) => <span key={w} className="block">{w}</span>)}
                    </li>
                ))}
            </ul>
        </Row>
    );
}

/** A status in words with an icon, never colour alone. */
function StatusText({ ok, children }: { ok: boolean | null; children: ReactNode }) {
    const Icon = ok ? Check : ok === false ? AlertCircle : CircleDashed;
    return (
        <span
            className={cn(
                "inline-flex items-center gap-1 rounded-full px-2 py-px text-[12px] font-semibold",
                ok ? "bg-ok-dim text-ok" : ok === false ? "bg-amber-dim text-amber" : "bg-panel-2 text-ink-3",
            )}
        >
            <Icon className="size-3" aria-hidden />
            {children}
        </span>
    );
}

/**
 * Only what the agent can really do: book on its calendar (Google Calendar
 * or Calendly) when it has one, and put callers through when its template
 * can. Nothing that isn't built (texts, emails to the kitchen) is offered.
 */
function CanDo({
    calendar,
    setCalendar,
    transfer,
    transferField,
    transferValue,
}: {
    calendar: CalendarInfo;
    setCalendar: AgentKnowledge["setCalendar"];
    transfer: BusinessFact | undefined;
    transferField: ReactNode;
    transferValue: string;
}) {
    const { can } = useOrgConfig();
    const [switching, setSwitching] = useState(false);
    const books = calendar.state === "ready";
    if (!books && !transfer) return null;

    const canSwitch = books && calendar.connectionId !== null && calendar.aiBooking !== null && can("bookings:manage");
    const setBooking = async (enabled: boolean) => {
        if (calendar.state !== "ready" || !calendar.connectionId) return;
        setSwitching(true);
        try {
            const res = await setAiBookingApiV1IntegrationsBookingsCalendarsConnectionIdPut({
                path: { connection_id: calendar.connectionId },
                body: { ai_booking_enabled: enabled },
            });
            if (res.error || !res.data) {
                toast.error(detailFromError(res.error, "Couldn't change the setting. Please try again."));
                return;
            }
            setCalendar((current) => (current.state === "ready" ? { ...current, aiBooking: enabled } : current));
            toast.success(enabled ? "Your agent takes bookings again." : "Your agent no longer books. It passes callers to your team.");
        } catch {
            toast.error("Couldn't change the setting. Please try again.");
        } finally {
            setSwitching(false);
        }
    };

    return (
        <Card title="What your agent can do" id="can-do">
            {books && (
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-t border-line-soft py-3 first:border-t-0">
                    <div className="min-w-0">
                        <p id="can-book" className="text-[13.5px] font-semibold text-foreground">
                            Take bookings
                        </p>
                        <p className="mt-0.5 text-[12.5px] leading-relaxed text-ink-3">
                            {bookingLine(calendar.provider)}{" "}
                            {calendar.eventName && <>Callers book &ldquo;{calendar.eventName}&rdquo;. </>}
                            {calendar.connected !== null && (
                                <StatusText ok={calendar.connected}>
                                    {calendar.connected ? "Connected" : "Not connected"}
                                </StatusText>
                            )}
                        </p>
                    </div>
                    {canSwitch ? (
                        <Switch
                            aria-labelledby="can-book"
                            checked={calendar.aiBooking === true}
                            disabled={switching}
                            onCheckedChange={(checked) => void setBooking(checked)}
                            className="h-[22px] w-[38px] [&_[data-slot=switch-thumb]]:size-4 [&_[data-slot=switch-thumb]]:data-[state=checked]:translate-x-[17px] [&_[data-slot=switch-thumb]]:data-[state=unchecked]:translate-x-[2px]"
                        />
                    ) : calendar.aiBooking !== null ? (
                        <StatusText ok={calendar.aiBooking}>{calendar.aiBooking ? "On" : "Off"}</StatusText>
                    ) : null}
                </div>
            )}
            {transfer && (
                <div className="grid gap-2 border-t border-line-soft py-3 first:border-t-0">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0">
                            <Label htmlFor={`fact-${transfer.key}`} className="text-[13.5px] font-semibold">
                                Pass calls to your team
                            </Label>
                            <p className="mt-0.5 text-[12.5px] leading-relaxed text-ink-3">
                                {transferValue
                                    ? `Puts callers through to ${transferValue} when they ask for a person.`
                                    : "Add your mobile or front desk number. Without one, your agent takes a message instead."}
                            </p>
                        </div>
                        <StatusText ok={transferValue ? true : null}>{transferValue ? "On" : "Off"}</StatusText>
                    </div>
                    <div className="max-w-sm">{transferField}</div>
                </div>
            )}
            {books && calendar.connected === false && can("integrations:read") && (
                <p className="pb-2 text-[12.5px] text-ink-2">
                    <Link href="/integrations" className="font-medium text-brand underline-offset-2 hover:underline">
                        Reconnect {bookingTitle(calendar.provider)}
                    </Link>{" "}
                    so your agent can see free times.
                </p>
            )}
            {books && calendar.connected !== false && calendar.needsEvent && (
                <p className="pb-2 text-[12.5px] text-ink-2">
                    {can("integrations:write") ? (
                        <>
                            <Link href="/integrations" className="font-medium text-brand underline-offset-2 hover:underline">
                                Choose which Calendly event callers book
                            </Link>
                            . Until then your agent takes their details instead.
                        </>
                    ) : (
                        "No Calendly event is chosen yet, so your agent takes callers' details instead. Ask an admin to choose one in Integrations."
                    )}
                </p>
            )}
        </Card>
    );
}

function HowItSounds({
    workflowId,
    knowledge,
    values,
}: {
    workflowId: number;
    knowledge: AgentKnowledge;
    values: Record<string, string>;
}) {
    const { openTester } = useAgentShell();
    const { can } = useOrgConfig();
    const { voice, greeting } = knowledge;
    const greetingText =
        greeting.state === "ready" && greeting.greeting?.kind === "text" ? fillGreeting(greeting.greeting.text, values) : null;

    return (
        <Card title="How it sounds" id="how-it-sounds" className="pb-4">
            <div className="flex flex-col gap-3.5 pt-2">
                {voice.state === "loading" ? (
                    <Skeleton className="h-9 w-40 rounded-full" />
                ) : voice.state === "ready" && voice.choices ? (
                    <>
                        <VoiceChips
                            workflowId={workflowId}
                            choices={voice.choices}
                            readsGreeting={greeting.state !== "ready" || greeting.greeting?.kind === "text"}
                            onSwitch={can("agents:write") ? knowledge.switchVoice : undefined}
                        />
                        {voice.language && <span className="-mt-1 text-[12.5px] text-ink-3">Speaks {voice.language}</span>}
                    </>
                ) : voice.state === "ready" && voice.voice ? (
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="inline-flex items-center gap-2 rounded-full border border-brand bg-brand-dim py-1.5 pl-1.5 pr-3 text-[13px] font-semibold text-brand">
                            <span aria-hidden className="grid size-[22px] place-items-center rounded-full bg-panel">
                                <Mic className="size-3" />
                            </span>
                            <span>
                                <span className="sr-only">Voice: </span>
                                {[voice.voice.name, voice.voice.gender].filter(Boolean).join(" · ")}
                            </span>
                        </span>
                        {voice.language && <span className="text-[12.5px] text-ink-3">Speaks {voice.language}</span>}
                    </div>
                ) : null}
                {can("agents:write") && (
                    <Link
                        href={`/workflow/${workflowId}/model`}
                        className="-mt-1 self-start text-[13px] font-medium text-brand underline-offset-2 hover:underline"
                    >
                        {voice.state === "ready" && voice.choices ? "See all voices" : "Change the voice"}
                    </Link>
                )}

                {greeting.state === "ready" && greeting.greeting && (
                    <div>
                        <p className="mb-1.5 text-[12.5px] text-ink-3">First thing callers hear</p>
                        <div className="rounded-[22px] bg-[#0b1220] p-4 text-white dark:bg-black/60 dark:ring-1 dark:ring-line">
                            <p className="rounded-xl bg-white/10 px-3 py-2 text-[13px] leading-relaxed">
                                {greeting.greeting.kind === "text" ? greetingText : "Plays your recorded greeting."}
                            </p>
                        </div>
                    </div>
                )}

                <Button asChild variant="outline" className="h-9 self-start">
                    <Link
                        href={agentTalkHref(workflowId)}
                        onClick={(event) => {
                            // Already on the agent: open the test panel here.
                            event.preventDefault();
                            talkToAgent(openTester);
                        }}
                    >
                        <Play className="size-3.5" aria-hidden />
                        Try your agent
                    </Link>
                </Button>
            </div>
        </Card>
    );
}

function ReadyForCalls({
    workflowId,
    facts,
    knowledge,
}: {
    workflowId: number;
    facts: BusinessFact[];
    knowledge: AgentKnowledge;
}) {
    const { can } = useOrgConfig();
    const { calendar, phone } = knowledge;
    // Saved answers, not the ones being typed.
    const missing = facts.filter((f) => f.required && !f.value.trim());
    const items: { ok: boolean | null; text: string }[] = [
        missing.length === 0
            ? { ok: true, text: "Business details added" }
            : { ok: false, text: `Add ${missing.map((f) => (ROW_COPY[f.key]?.label ?? f.label).toLowerCase()).join(", ")}` },
    ];
    if (calendar.state === "ready" && calendar.connected !== null) {
        items.push(
            !calendar.connected
                ? { ok: false, text: "Calendar not connected" }
                : calendar.needsEvent
                  ? { ok: false, text: "Choose your Calendly event" }
                  : { ok: true, text: "Calendar connected" },
        );
    }
    if (phone.state === "ready") {
        items.push(
            phone.numbers.length > 0
                ? { ok: true, text: `Phone number linked: ${phone.numbers[0]}` }
                : { ok: false, text: "No phone number linked yet" },
        );
    }

    return (
        <Card title="Ready to take calls" id="ready" className="pb-4">
            <ul className="flex flex-col gap-2.5 pt-2">
                {items.map((item) => (
                    <li key={item.text} className="flex items-center gap-2.5 text-[13px] text-foreground">
                        <span
                            className={cn(
                                "grid size-5 shrink-0 place-items-center rounded-full text-white",
                                item.ok ? "bg-brand" : "bg-amber",
                            )}
                        >
                            {item.ok ? (
                                <Check className="size-3" strokeWidth={3} aria-hidden />
                            ) : (
                                <AlertCircle className="size-3" strokeWidth={3} aria-hidden />
                            )}
                            <span className="sr-only">{item.ok ? "Done:" : "To do:"}</span>
                        </span>
                        <span className="min-w-0 break-words">{item.text}</span>
                    </li>
                ))}
                {phone.state === "loading" && <Skeleton className="h-5 w-48" />}
            </ul>
            {can("agents:write") && (
                <p className="mt-3.5 text-[12.5px] leading-relaxed text-ink-3">
                    Need to change how calls flow step by step?{" "}
                    <Link
                        href={`/workflow/${workflowId}`}
                        className="font-semibold text-brand underline-offset-2 hover:underline"
                    >
                        Open advanced setup
                    </Link>
                </p>
            )}
        </Card>
    );
}
