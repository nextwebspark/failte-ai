"use client";

import { CalendarCheck, Phone } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import {
    integrationErrorMessage,
    isUnavailableError,
} from "@/app/integrations/messages";
import {
    listBookingsApiV1IntegrationsBookingsGet,
    setAiBookingApiV1IntegrationsBookingsCalendarsConnectionIdPut,
} from "@/client/sdk.gen";
import type { BookingCalendar, BookingListResponse, CalendarBooking } from "@/client/types.gen";
import { NoAccess } from "@/components/auth/NoAccess";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Panel, PanelDescription, PanelTitle } from "@/components/ui/panel";
import { SectionHeading } from "@/components/ui/section-heading";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { Switch } from "@/components/ui/switch";
import { useOrgConfig } from "@/context/OrgConfigContext";

import {
    groupByDay,
    isoWithOffset,
    partyLabel,
    RANGE_OPTIONS,
    rangeFor,
    type RangeKey,
    timeRange,
    totals,
} from "./bookingsView";

const LOAD_FAILED = "Couldn't load bookings. Please try again.";

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

    const [range, setRange] = useState<RangeKey>("next7");
    const [showCancelled, setShowCancelled] = useState(false);
    const [data, setData] = useState<BookingListResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
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
                setError(
                    isUnavailableError(response.error)
                        ? "Calendar bookings aren't available on this deployment."
                        : integrationErrorMessage(response.error, LOAD_FAILED),
                );
                setData(null);
                return;
            }
            setData(response.data);
        } catch {
            setError(LOAD_FAILED);
            setData(null);
        } finally {
            setLoading(false);
        }
    }, [range]);

    useEffect(() => {
        void load();
    }, [load]);

    const setBookingOn = async (calendar: BookingCalendar, enabled: boolean) => {
        setSaving(calendar.connection_id);
        try {
            const response = await setAiBookingApiV1IntegrationsBookingsCalendarsConnectionIdPut({
                path: { connection_id: calendar.connection_id },
                body: { ai_booking_enabled: enabled },
            });
            if (response.error || !response.data) {
                toast.error(integrationErrorMessage(response.error, "Couldn't change the setting"));
                return;
            }
            setData((current) =>
                current && {
                    ...current,
                    calendars: current.calendars.map((c) =>
                        c.connection_id === calendar.connection_id ? { ...c, ai_booking_enabled: enabled } : c,
                    ),
                },
            );
            toast.success(
                enabled
                    ? "Your agent can take bookings again"
                    : "Booking is off: your agent will take details for your team instead",
            );
        } catch {
            toast.error("Couldn't change the setting. Please try again.");
        } finally {
            setSaving(null);
        }
    };

    const now = useMemo(() => new Date(), [data]); // eslint-disable-line react-hooks/exhaustive-deps
    const bookings = data?.bookings ?? [];
    const calendars = data?.calendars ?? [];
    const groups = groupByDay(bookings, now, showCancelled);
    const sums = totals(bookings);
    const names = new Map(calendars.map((c) => [c.connection_id, calendarName(c)]));
    const showCalendarName = calendars.length > 1;

    return (
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap gap-2" role="group" aria-label="Which bookings">
                    {RANGE_OPTIONS.map((option) => (
                        <Button
                            key={option.value}
                            size="sm"
                            variant={range === option.value ? "default" : "outline"}
                            aria-pressed={range === option.value}
                            onClick={() => setRange(option.value)}
                        >
                            {option.label}
                        </Button>
                    ))}
                </div>
                <div className="flex items-center gap-2">
                    <Switch id="show-cancelled" checked={showCancelled} onCheckedChange={setShowCancelled} />
                    <Label htmlFor="show-cancelled">Show cancelled</Label>
                </div>
            </div>

            {loading && !data ? (
                <div className="flex flex-col gap-3" aria-busy="true">
                    <Skeleton className="h-16 w-full" />
                    <Skeleton className="h-24 w-full" />
                    <Skeleton className="h-24 w-full" />
                </div>
            ) : error ? (
                <Panel accent="danger" role="alert">
                    <PanelTitle>{error}</PanelTitle>
                    <Button className="mt-3" size="sm" variant="outline" onClick={() => void load()}>
                        Try again
                    </Button>
                </Panel>
            ) : calendars.length === 0 ? (
                <NoCalendar canManage={canManage} />
            ) : (
                <>
                    <section aria-label="Calendars" className="flex flex-col gap-3">
                        <SectionHeading>Calendars</SectionHeading>
                        {calendars.map((calendar) => (
                            <CalendarRow
                                key={calendar.connection_id}
                                calendar={calendar}
                                canManage={canManage}
                                canSeeIntegrations={canSeeIntegrations}
                                saving={saving === calendar.connection_id}
                                onChange={(enabled) => void setBookingOn(calendar, enabled)}
                            />
                        ))}
                    </section>

                    <section aria-label="Bookings" className="flex flex-col gap-3">
                        <SectionHeading
                            action={
                                <span className="font-mono text-[11.5px] text-ink-3">
                                    {sums.confirmed} {sums.confirmed === 1 ? "booking" : "bookings"} ·{" "}
                                    {sums.guests} guests
                                    {sums.noPartySize > 0 && ` · ${sums.noPartySize} without a party size`}
                                    {sums.cancelled > 0 && ` · ${sums.cancelled} cancelled`}
                                </span>
                            }
                        >
                            Bookings
                        </SectionHeading>
                        {groups.length === 0 ? (
                            <Panel>
                                <PanelTitle>
                                    {range === "past7" ? "No bookings in the last 7 days." : "No bookings yet in this range."}
                                </PanelTitle>
                                <PanelDescription>
                                    Bookings your agent makes on a connected calendar show here.
                                </PanelDescription>
                            </Panel>
                        ) : (
                            groups.map((group) => (
                                <div key={group.key} className="flex flex-col gap-2">
                                    <h3 className="flex items-baseline justify-between text-sm font-semibold">
                                        <span>{group.label}</span>
                                        <span className="font-mono text-[11.5px] font-normal text-ink-3">
                                            {group.confirmed} {group.confirmed === 1 ? "booking" : "bookings"}
                                            {group.guests > 0 && ` · ${group.guests} guests`}
                                        </span>
                                    </h3>
                                    <ul className="flex flex-col gap-2">
                                        {group.bookings.map((booking) => (
                                            <BookingRow
                                                key={`${booking.connection_id}-${booking.event_id}`}
                                                booking={booking}
                                                calendarName={
                                                    showCalendarName ? names.get(booking.connection_id) : undefined
                                                }
                                            />
                                        ))}
                                    </ul>
                                </div>
                            ))
                        )}
                    </section>
                </>
            )}
        </div>
    );
}

function NoCalendar({ canManage }: { canManage: boolean }) {
    return (
        <Panel accent="sky">
            <PanelTitle as="h2">No calendar connected yet</PanelTitle>
            <p className="mt-2 text-sm text-ink-2">
                Connect a Google Calendar and your agent can offer real free times and book them while the
                caller is on the line. Bookings then show here.
            </p>
            {canManage ? (
                <Button asChild className="mt-4" size="sm">
                    <Link href="/integrations">Connect a calendar</Link>
                </Button>
            ) : (
                <p className="mt-3 text-sm text-ink-3">Ask an admin on your team to connect one.</p>
            )}
        </Panel>
    );
}

function CalendarRow({
    calendar,
    canManage,
    canSeeIntegrations,
    saving,
    onChange,
}: {
    calendar: BookingCalendar;
    canManage: boolean;
    canSeeIntegrations: boolean;
    saving: boolean;
    onChange: (enabled: boolean) => void;
}) {
    const name = calendarName(calendar);
    const switchId = `booking-on-${calendar.connection_id}`;
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
                                checked={calendar.ai_booking_enabled}
                                disabled={saving}
                                onCheckedChange={onChange}
                            />
                            <Label htmlFor={switchId} className="text-sm">
                                Let the agent book
                            </Label>
                        </div>
                    )}
                </div>
            </div>
            {!calendar.ai_booking_enabled && (
                <p className="mt-2 text-sm text-ink-2">
                    Your agent won&apos;t book on this calendar. Callers who want a booking are passed to your team,
                    or their details are taken for a call back.
                </p>
            )}
            {!calendar.ok && (
                <p className="mt-2 text-sm text-danger" role="alert">
                    Couldn&apos;t read this calendar: {calendar.error ?? "unknown error"}.{" "}
                    {canSeeIntegrations && (
                        <Link className="underline" href="/integrations">
                            Check the connection
                        </Link>
                    )}
                </p>
            )}
        </Panel>
    );
}

function BookingRow({ booking, calendarName }: { booking: CalendarBooking; calendarName?: string }) {
    const cancelled = booking.status === "cancelled";
    const party = partyLabel(booking);
    return (
        <li>
            <Panel padding="sm" className={cancelled ? "opacity-60" : undefined}>
                <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
                    <span className={`w-28 font-mono text-sm ${cancelled ? "line-through" : ""}`}>
                        {timeRange(booking)}
                    </span>
                    <span className="min-w-40 flex-1 font-medium">{booking.caller_name || "Name not given"}</span>
                    <span className={party === "Not asked" ? "text-sm text-ink-3" : "text-sm"}>{party}</span>
                    {booking.caller_phone ? (
                        <a
                            className="inline-flex items-center gap-1 font-mono text-sm underline-offset-2 hover:underline"
                            href={`tel:${booking.caller_phone.replace(/[^\d+]/g, "")}`}
                        >
                            <Phone className="size-3.5" aria-hidden />
                            {booking.caller_phone}
                        </a>
                    ) : null}
                    {cancelled && <StatusPill tone="mute">Cancelled</StatusPill>}
                </div>
                {(booking.reason || calendarName) && (
                    <p className="mt-1 text-sm text-ink-3">
                        {booking.reason}
                        {booking.reason && calendarName ? " · " : ""}
                        {calendarName}
                    </p>
                )}
            </Panel>
        </li>
    );
}
