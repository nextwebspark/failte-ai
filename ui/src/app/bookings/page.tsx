"use client";

import { ArrowRight, CalendarCheck, CalendarClock, CalendarPlus, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { integrationErrorMessage } from "@/app/integrations/messages";
import {
    listBookingsApiV1IntegrationsBookingsGet,
    setAiBookingApiV1IntegrationsBookingsCalendarsConnectionIdPut,
} from "@/client/sdk.gen";
import type { BookingCalendar, BookingListResponse } from "@/client/types.gen";
import { NoAccess } from "@/components/auth/NoAccess";
import { EmptyState } from "@/components/page-states/EmptyState";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Panel, PanelDescription, PanelTitle } from "@/components/ui/panel";
import { SectionHeading } from "@/components/ui/section-heading";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { Switch } from "@/components/ui/switch";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { errorCodeFromError } from "@/lib/apiError";
import { cn } from "@/lib/utils";

import { BookingDays } from "./BookingDays";
import { BookingRulesEditor, type Rules, summarize } from "./BookingRules";
import {
    bookingsLoadError,
    type BookingTotals,
    daysInRange,
    type FriendlyError,
    isoWithOffset,
    RANGE_OPTIONS,
    rangeFor,
    type RangeKey,
    totals,
} from "./bookingsView";

export default function BookingsPage() {
    const { can, role, loading } = useOrgConfig();
    if (!can("calls:read")) {
        // The role is still loading: render nothing rather than flash "no access".
        if (role === null && loading) return null;
        return <NoAccess role={role} />;
    }
    return <BookingsScreen />;
}

function calendarName(calendar: BookingCalendar): string {
    return calendar.account_label || calendar.title;
}

function BookingsScreen() {
    const { can } = useOrgConfig();
    // The owner, admins, and staff the owner allowed.
    const canManage = can("bookings:manage");
    const canSeeIntegrations = can("integrations:read");
    // Connecting a calendar happens on the Integrations page (admins only).
    const canConnect = can("integrations:write");

    const [range, setRange] = useState<RangeKey>("next7");
    const [showCancelled, setShowCancelled] = useState(false);
    const [data, setData] = useState<BookingListResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<FriendlyError | null>(null);
    const [saving, setSaving] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        const { start, end } = rangeFor(range, new Date());
        try {
            const response = await listBookingsApiV1IntegrationsBookingsGet({
                query: { start: isoWithOffset(start), end: isoWithOffset(end) },
            });
            if (response.error || !response.data) {
                setError(bookingsLoadError(errorCodeFromError(response.error)));
                setData(null);
                return;
            }
            setData(response.data);
        } catch {
            setError(bookingsLoadError(undefined));
            setData(null);
        } finally {
            setLoading(false);
        }
    }, [range]);

    useEffect(() => {
        void load();
    }, [load]);

    const setSwitch = async (calendar: BookingCalendar, key: OwnerSwitch, enabled: boolean) => {
        setSaving(calendar.connection_id);
        try {
            const response = await setAiBookingApiV1IntegrationsBookingsCalendarsConnectionIdPut({
                path: { connection_id: calendar.connection_id },
                body: { [key]: enabled },
            });
            if (response.error || !response.data) {
                toast.error(integrationErrorMessage(response.error, "Couldn't change the setting"));
                return;
            }
            setData((current) =>
                current && {
                    ...current,
                    calendars: current.calendars.map((c) =>
                        c.connection_id === calendar.connection_id ? { ...c, [key]: enabled } : c,
                    ),
                },
            );
            toast.success(SWITCH_TOASTS[key][enabled ? "on" : "off"]);
        } catch {
            toast.error("Couldn't change the setting. Please try again.");
        } finally {
            setSaving(null);
        }
    };

    const saveRules = async (calendar: BookingCalendar, rules: Rules) => {
        setSaving(calendar.connection_id);
        try {
            const response = await setAiBookingApiV1IntegrationsBookingsCalendarsConnectionIdPut({
                path: { connection_id: calendar.connection_id },
                body: { rules: rules as Record<string, unknown> },
            });
            if (response.error || !response.data) {
                toast.error(integrationErrorMessage(response.error, "Couldn't save the booking rules"));
                return;
            }
            const saved = response.data;
            setData((current) =>
                current && {
                    ...current,
                    calendars: current.calendars.map((c) =>
                        c.connection_id === calendar.connection_id ? { ...c, rules: saved.rules } : c,
                    ),
                },
            );
            toast.success("Booking rules saved. Your agent uses them from the next call.");
        } catch {
            toast.error("Couldn't save the booking rules. Please try again.");
        } finally {
            setSaving(null);
        }
    };

    const now = useMemo(() => new Date(), [data]); // eslint-disable-line react-hooks/exhaustive-deps
    const bookings = data?.bookings ?? [];
    const calendars = data?.calendars ?? [];
    const sums = totals(bookings);
    const days = daysInRange(bookings, rangeFor(range, now), now, showCancelled);
    const names =
        calendars.length > 1 ? new Map(calendars.map((c) => [c.connection_id, calendarName(c)])) : undefined;
    const rangeLabel = RANGE_OPTIONS.find((option) => option.value === range)?.label ?? "";

    if (loading && !data && !error) return <BookingsSkeleton />;

    if (error) {
        return (
            <div className="page-body">
                <div className="mx-auto max-w-4xl">
                    <EmptyState
                        tone="amber"
                        icon={CalendarClock}
                        title={error.title}
                        role="alert"
                        action={
                            error.retry ? (
                                <Button className="h-10 sm:h-9" onClick={() => void load()} disabled={loading}>
                                    <RefreshCw aria-hidden />
                                    {loading ? "Trying…" : "Try again"}
                                </Button>
                            ) : null
                        }
                    >
                        {error.body}
                    </EmptyState>
                </div>
            </div>
        );
    }

    if (calendars.length === 0) {
        return (
            <div className="page-body">
                <div className="mx-auto max-w-4xl">
                    <NoCalendar canConnect={canConnect} />
                </div>
            </div>
        );
    }

    const emptyRange = sums.confirmed === 0 && (sums.cancelled === 0 || !showCancelled);

    return (
        <div className="page-body">
            <div className="mx-auto flex max-w-4xl flex-col gap-8">
                <section
                    aria-labelledby="bookings-range"
                    className="rounded-xl border border-line bg-gradient-to-br from-brand-dim via-panel to-panel px-5 py-5 sm:px-6"
                >
                    <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
                        <div className="min-w-0">
                            <h2 id="bookings-range" className="text-[22px] font-bold tracking-tight">
                                {rangeLabel}
                            </h2>
                            <p className="mt-1 text-[15px] text-ink-2" aria-live="polite">
                                {loading ? "Checking your calendar…" : rangeSummary(sums)}
                            </p>
                        </div>
                        <div
                            className="grid grid-cols-3 gap-1 rounded-lg border border-line bg-panel p-1"
                            role="group"
                            aria-label="Which days"
                        >
                            {RANGE_OPTIONS.map((option) => (
                                <button
                                    key={option.value}
                                    type="button"
                                    aria-pressed={range === option.value}
                                    onClick={() => setRange(option.value)}
                                    className={cn(
                                        "min-h-10 whitespace-nowrap rounded-md px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40 motion-reduce:transition-none md:min-h-8",
                                        range === option.value
                                            ? "bg-brand text-primary-foreground"
                                            : "text-ink-2 hover:bg-brand-dim hover:text-brand",
                                    )}
                                >
                                    {option.label}
                                </button>
                            ))}
                        </div>
                    </div>
                    <div className="mt-4 flex flex-col gap-3 border-t border-line-soft pt-3 sm:flex-row sm:items-center sm:justify-between">
                        <p className="text-[13px] text-ink-3">
                            Bookings your agent took on the phone, read live from your calendar. Ones your team adds
                            straight into the calendar aren&apos;t listed here.
                        </p>
                        {sums.cancelled > 0 && (
                            <div className="flex min-h-10 flex-none items-center gap-2">
                                <Switch
                                    id="show-cancelled"
                                    className={SWITCH_HIT_AREA}
                                    checked={showCancelled}
                                    onCheckedChange={setShowCancelled}
                                />
                                <Label htmlFor="show-cancelled">Show cancelled</Label>
                            </div>
                        )}
                    </div>
                </section>

                <section aria-label="Bookings" aria-busy={loading} className={cn(loading && "opacity-60")}>
                    {emptyRange ? (
                        <EmptyState icon={CalendarCheck} title={emptyTitle(range)}>
                            {calendars.some((c) => c.ai_booking_enabled)
                                ? "When your agent books a table or appointment, it shows up here straight away."
                                : "Your agent isn't taking bookings at the moment. You can switch it on below."}
                        </EmptyState>
                    ) : (
                        <BookingDays days={days} calendarNames={names} />
                    )}
                </section>

                <section aria-labelledby="calendar-settings" className="flex flex-col gap-3">
                    <SectionHeading id="calendar-settings">
                        {calendars.length === 1 ? "Your calendar" : "Your calendars"}
                    </SectionHeading>
                    {calendars.map((calendar) => (
                        <CalendarRow
                            key={calendar.connection_id}
                            calendar={calendar}
                            canManage={canManage}
                            canSeeIntegrations={canSeeIntegrations}
                            saving={saving === calendar.connection_id}
                            onChange={(key, enabled) => void setSwitch(calendar, key, enabled)}
                            onSaveRules={(rules) => void saveRules(calendar, rules)}
                        />
                    ))}
                </section>
            </div>
        </div>
    );
}

function rangeSummary(sums: BookingTotals): string {
    if (sums.confirmed === 0) {
        return sums.cancelled > 0 ? `No bookings, ${sums.cancelled} cancelled` : "No bookings yet";
    }
    const parts = [`${sums.confirmed} ${sums.confirmed === 1 ? "booking" : "bookings"}`];
    if (sums.guests > 0) parts.push(`${sums.guests} ${sums.guests === 1 ? "guest" : "guests"}`);
    if (sums.noPartySize > 0) parts.push(`${sums.noPartySize} without a party size`);
    if (sums.cancelled > 0) parts.push(`${sums.cancelled} cancelled`);
    return parts.join(" · ");
}

function emptyTitle(range: RangeKey): string {
    if (range === "past7") return "No bookings in the last 7 days";
    return range === "next14" ? "No bookings in the next 14 days" : "No bookings in the next 7 days";
}

function BookingsSkeleton() {
    return (
        <div className="page-body" aria-busy="true" aria-label="Loading bookings">
            <div className="mx-auto flex max-w-4xl flex-col gap-8">
                <Skeleton className="h-[148px] w-full rounded-xl" />
                {[0, 1].map((day) => (
                    <div key={day} className="flex flex-col gap-2">
                        <Skeleton className="h-5 w-44" />
                        <Skeleton className="h-[68px] w-full rounded-lg" />
                        <Skeleton className="h-[68px] w-full rounded-lg" />
                    </div>
                ))}
            </div>
        </div>
    );
}

function NoCalendar({ canConnect }: { canConnect: boolean }) {
    return (
        <EmptyState
            icon={CalendarPlus}
            title="Connect your calendar to take bookings"
            action={
                canConnect ? (
                    <Button asChild className="h-10 sm:h-9">
                        <Link href="/integrations">
                            Connect a calendar
                            <ArrowRight aria-hidden />
                        </Link>
                    </Button>
                ) : null
            }
        >
            Link your Google Calendar and your agent can offer callers real free times and book them while
            they&apos;re still on the line. Every booking then shows up here, day by day.
            {!canConnect && <span className="mt-2 block">Ask an admin on your team to connect it.</span>}
        </EmptyState>
    );
}

/** A 40px tap area around the small switch, without changing how it looks. */
const SWITCH_HIT_AREA = "relative after:absolute after:-inset-[11px] after:content-['']";

type OwnerSwitch = "ai_booking_enabled" | "ai_changes_enabled";

const SWITCH_TOASTS: Record<OwnerSwitch, { on: string; off: string }> = {
    ai_booking_enabled: {
        on: "Your agent can take bookings again",
        off: "Booking is off: your agent will take details for your team instead",
    },
    ai_changes_enabled: {
        on: "Your agent can now cancel or move bookings after checking the caller",
        off: "Changes are off: your agent will take a message instead",
    },
};

function CalendarRow({
    calendar,
    canManage,
    canSeeIntegrations,
    saving,
    onChange,
    onSaveRules,
}: {
    calendar: BookingCalendar;
    canManage: boolean;
    canSeeIntegrations: boolean;
    saving: boolean;
    onChange: (key: OwnerSwitch, enabled: boolean) => void;
    onSaveRules: (rules: Rules) => void;
}) {
    const [editingRules, setEditingRules] = useState(false);
    const rules = (calendar.rules ?? {}) as Rules;
    const name = calendarName(calendar);
    const switchId = `booking-on-${calendar.connection_id}`;
    const changesId = `changes-on-${calendar.connection_id}`;
    const changesOn = calendar.ai_changes_enabled ?? false;
    return (
        <Panel accent={calendar.ok ? (calendar.ai_booking_enabled ? "brand" : "amber") : "danger"}>
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3">
                    <CalendarCheck className="size-5 flex-none text-ink-3" aria-hidden />
                    <div className="min-w-0">
                        <PanelTitle className="truncate">{name}</PanelTitle>
                        <PanelDescription>{calendar.title}</PanelDescription>
                    </div>
                </div>
                <div className="flex items-center gap-3">
                    <StatusPill tone={calendar.ai_booking_enabled ? "ok" : "warn"}>
                        {calendar.ai_booking_enabled ? "Agent books" : "Booking off"}
                    </StatusPill>
                    {canManage && (
                        <div className="flex items-center gap-2">
                            <Switch
                                id={switchId}
                                className={SWITCH_HIT_AREA}
                                checked={calendar.ai_booking_enabled}
                                disabled={saving}
                                onCheckedChange={(enabled) => onChange("ai_booking_enabled", enabled)}
                            />
                            <Label htmlFor={switchId} className="text-sm">
                                Let the agent book
                            </Label>
                        </div>
                    )}
                </div>
            </div>
            <div className="mt-3 flex flex-wrap items-start gap-2 border-t border-line-soft pt-3">
                {canManage ? (
                    <Switch
                        id={changesId}
                        className={SWITCH_HIT_AREA}
                        checked={changesOn}
                        disabled={saving}
                        onCheckedChange={(enabled) => onChange("ai_changes_enabled", enabled)}
                    />
                ) : (
                    <StatusPill tone={changesOn ? "ok" : "mute"}>{changesOn ? "On" : "Off"}</StatusPill>
                )}
                <div className="min-w-0 flex-1">
                    <Label htmlFor={canManage ? changesId : undefined} className="text-sm">
                        Let the agent cancel or move bookings
                    </Label>
                    <p className="text-[12.5px] text-ink-3">
                        Only after the caller gives the phone number the booking was made under, plus their name or
                        the day of the booking. If anything doesn&apos;t match, or this is off, the caller is passed to
                        your team or a message is taken.
                    </p>
                </div>
            </div>
            <div className="mt-3 border-t border-line-soft pt-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                        <span className="text-sm font-medium">Booking rules</span>
                        <p className="text-[12.5px] text-ink-3">{summarize(rules)}</p>
                    </div>
                    {canManage && (
                        <Button size="sm" variant="outline" className="h-10 sm:h-8" onClick={() => setEditingRules((v) => !v)}>
                            {editingRules ? "Close" : "Edit booking rules"}
                        </Button>
                    )}
                </div>
                {canManage && editingRules && (
                    <div className="mt-3">
                        <BookingRulesEditor
                            idPrefix={calendar.connection_id}
                            initial={rules}
                            saving={saving}
                            onSave={(next) => {
                                onSaveRules(next);
                            }}
                        />
                    </div>
                )}
            </div>
            {!calendar.ai_booking_enabled && (
                <p className="mt-2 text-sm text-ink-2">
                    Your agent won&apos;t book on this calendar. Callers who want a booking are passed to your team,
                    or their details are taken for a call back.
                </p>
            )}
            {!calendar.ok && (
                <p className="mt-2 text-sm text-danger" role="alert">
                    {canSeeIntegrations ? (
                        <>
                            Couldn&apos;t read this calendar
                            {calendar.error ? `: ${calendar.error}` : ""}. Your agent can&apos;t offer times from it
                            until this is fixed.{" "}
                            <Link className="underline" href="/integrations">
                                Check the connection
                            </Link>
                        </>
                    ) : (
                        <>
                            We couldn&apos;t read this calendar, so your agent can&apos;t offer times from it right
                            now. Ask an admin on your team to check the calendar connection.
                        </>
                    )}
                </p>
            )}
        </Panel>
    );
}
