"use client";

import { Check, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

/** One stretch of the week when bookings may start (the tools service's ServicePeriod). */
export interface ServicePeriod {
    days: number[];
    first_start: string;
    last_start: string;
}

/** The booking rules an owner sets; every field optional (defaults apply). */
export interface Rules {
    service_periods?: ServicePeriod[];
    slot_minutes?: number;
    booking_minutes?: number;
    buffer_minutes?: number;
    max_bookings_at_once?: number;
    max_guests_at_once?: number;
    max_party_size?: number;
    min_lead_hours?: number;
    horizon_days?: number;
}

export const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Starting points an owner picks with one tap, then adjusts. */
export const PRESETS: { id: string; label: string; help: string; rules: Rules }[] = [
    {
        id: "appointments",
        label: "Appointments",
        help: "One booking at a time, e.g. a clinic, salon chair or viewing.",
        rules: {
            service_periods: [{ days: [0, 1, 2, 3, 4], first_start: "09:00", last_start: "16:30" }],
            slot_minutes: 30,
            booking_minutes: 30,
            buffer_minutes: 0,
            max_bookings_at_once: 1,
            min_lead_hours: 2,
            horizon_days: 14,
        },
    },
    {
        id: "restaurant",
        label: "Restaurant tables",
        help: "Several tables at once, held for a sitting; walk-ins keep the rest.",
        rules: {
            service_periods: [
                { days: [1, 2, 3, 4, 5, 6], first_start: "12:00", last_start: "14:30" },
                { days: [1, 2, 3, 4, 5, 6], first_start: "17:00", last_start: "21:00" },
            ],
            slot_minutes: 15,
            booking_minutes: 90,
            buffer_minutes: 15,
            max_bookings_at_once: 5,
            max_party_size: 8,
            min_lead_hours: 1,
            horizon_days: 30,
        },
    },
];

/** The defaults the calendar uses for anything not set (tools CalendarConfig). */
export const DEFAULTS: Required<Omit<Rules, "service_periods" | "max_guests_at_once" | "max_party_size">> = {
    slot_minutes: 30,
    booking_minutes: 30,
    buffer_minutes: 15,
    max_bookings_at_once: 1,
    min_lead_hours: 2,
    horizon_days: 14,
};

type NumberKey = Exclude<keyof Rules, "service_periods">;

const NUMBER_FIELDS: { key: NumberKey; label: string; help: string; optional?: boolean; min: number }[] = [
    { key: "max_bookings_at_once", label: "Bookings at the same time", help: "e.g. the tables you keep for phone bookings. 1 for a one-person diary.", min: 1 },
    { key: "max_party_size", label: "Largest group the agent may book", help: "Bigger groups are passed to your team.", optional: true, min: 1 },
    { key: "max_guests_at_once", label: "Most guests at the same time", help: "Seats in use at once, across bookings.", optional: true, min: 1 },
    { key: "booking_minutes", label: "How long a booking lasts (minutes)", help: "e.g. 90 for a dinner table.", min: 1 },
    { key: "slot_minutes", label: "Gap between start times (minutes)", help: "15 offers 7:00, 7:15, 7:30…", min: 1 },
    { key: "buffer_minutes", label: "Reset time between bookings (minutes)", help: "Clearing a table or tidying a room.", min: 0 },
    { key: "min_lead_hours", label: "Minimum notice (hours)", help: "No bookings sooner than this.", min: 0 },
    { key: "horizon_days", label: "Book up to (days ahead)", help: "How far ahead callers can book.", min: 1 },
];

export function describePeriod(period: ServicePeriod): string {
    const days = [...period.days].sort((a, b) => a - b);
    const contiguous = days.every((d, i) => i === 0 || d === days[i - 1] + 1);
    const dayText =
        days.length === 7
            ? "Every day"
            : contiguous && days.length > 2
              ? `${DAY_LABELS[days[0]]}–${DAY_LABELS[days[days.length - 1]]}`
              : days.map((d) => DAY_LABELS[d]).join(", ");
    return `${dayText}, first booking ${period.first_start}, last ${period.last_start}`;
}

/** A plain one-line summary of the rules, for people who can't edit them. */
export function summarize(rules: Rules): string {
    const parts: string[] = [];
    const atOnce = rules.max_bookings_at_once ?? DEFAULTS.max_bookings_at_once;
    parts.push(atOnce === 1 ? "One booking at a time" : `${atOnce} bookings at the same time`);
    parts.push(`${rules.booking_minutes ?? rules.slot_minutes ?? DEFAULTS.booking_minutes} min each`);
    if (rules.max_party_size) parts.push(`groups up to ${rules.max_party_size}`);
    parts.push(`up to ${rules.horizon_days ?? DEFAULTS.horizon_days} days ahead`);
    return parts.join(" · ");
}

/** Problems an owner can fix before saving; the calendar checks the rest. */
export function problems(rules: Rules): string[] {
    const found: string[] = [];
    (rules.service_periods ?? []).forEach((p, i) => {
        if (p.days.length === 0) found.push(`Opening times ${i + 1}: pick at least one day.`);
        if (p.first_start > p.last_start) found.push(`Opening times ${i + 1}: the first booking is after the last.`);
    });
    NUMBER_FIELDS.forEach((field) => {
        const value = rules[field.key];
        if (value === undefined) return;
        if (!Number.isInteger(value) || value < field.min) {
            found.push(
                field.min === 0
                    ? `${field.label}: use a whole number, 0 or more.`
                    : `${field.label}: use a whole number, 1 or more.`,
            );
        }
    });
    if (rules.max_party_size && rules.max_guests_at_once && rules.max_party_size > rules.max_guests_at_once) {
        found.push("The largest group can't be bigger than the most guests at the same time.");
    }
    return found;
}

export function BookingRulesEditor({
    idPrefix = "rules",
    initial,
    saving,
    onSave,
}: {
    /** Keeps input ids unique when several calendars show an editor. */
    idPrefix?: string;
    initial: Rules;
    saving: boolean;
    onSave: (rules: Rules) => void;
}) {
    const [rules, setRules] = useState<Rules>(initial);
    const issues = problems(rules);
    const periods = rules.service_periods ?? [];

    const setPeriod = (index: number, period: ServicePeriod) =>
        setRules((r) => ({ ...r, service_periods: periods.map((p, i) => (i === index ? period : p)) }));

    return (
        <div className="flex flex-col gap-5">
            <div className="flex flex-col gap-2">
                <span className="text-caption font-semibold">Start from</span>
                <div className="grid gap-2 sm:grid-cols-2">
                    {PRESETS.map((preset) => {
                        const helpId = `${idPrefix}-preset-${preset.id}-help`;
                        return (
                            <div key={preset.id} className="flex flex-col items-start gap-1">
                                <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    aria-describedby={helpId}
                                    onClick={() => setRules({ ...preset.rules })}
                                >
                                    {preset.label}
                                </Button>
                                <p id={helpId} className="text-[12px] text-ink-3">
                                    {preset.help}
                                </p>
                            </div>
                        );
                    })}
                </div>
                <p className="text-[12px] text-ink-3">Picking one replaces the rules below. You can change them after.</p>
            </div>

            <div className="flex flex-col gap-2">
                <span className="text-caption font-semibold">When bookings can start</span>
                {periods.length === 0 && (
                    <p className="text-sm text-ink-3">Weekdays, 9am to 5pm (the default).</p>
                )}
                {periods.map((period, index) => (
                    <div key={index} className="flex flex-wrap items-center gap-2 rounded-md border border-line p-2.5">
                        <div className="flex flex-wrap gap-1" role="group" aria-label={`Days for opening times ${index + 1}`}>
                            {DAY_LABELS.map((label, day) => {
                                const on = period.days.includes(day);
                                return (
                                    <button
                                        key={label}
                                        type="button"
                                        aria-pressed={on}
                                        onClick={() =>
                                            setPeriod(index, {
                                                ...period,
                                                days: on ? period.days.filter((d) => d !== day) : [...period.days, day].sort((a, b) => a - b),
                                            })
                                        }
                                        className={cn(
                                            "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1",
                                            on ? "border-brand bg-brand/10 font-medium" : "border-line text-ink-2",
                                        )}
                                    >
                                        {on && <Check size={12} aria-hidden />}
                                        {label}
                                    </button>
                                );
                            })}
                        </div>
                        <Label className="flex items-center gap-1 text-xs font-normal">
                            First
                            <Input
                                type="time"
                                className="h-8 w-[110px]"
                                value={period.first_start}
                                onChange={(e) => setPeriod(index, { ...period, first_start: e.target.value })}
                            />
                        </Label>
                        <Label className="flex items-center gap-1 text-xs font-normal">
                            Last
                            <Input
                                type="time"
                                className="h-8 w-[110px]"
                                value={period.last_start}
                                onChange={(e) => setPeriod(index, { ...period, last_start: e.target.value })}
                            />
                        </Label>
                        <Button
                            type="button"
                            size="icon"
                            variant="ghost"
                            aria-label={`Remove opening times ${index + 1}`}
                            onClick={() =>
                                setRules((r) => ({ ...r, service_periods: periods.filter((_, i) => i !== index) }))
                            }
                        >
                            <Trash2 className="size-4" aria-hidden />
                        </Button>
                    </div>
                ))}
                <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="self-start"
                    onClick={() =>
                        setRules((r) => ({
                            ...r,
                            service_periods: [...periods, { days: [0, 1, 2, 3, 4], first_start: "09:00", last_start: "17:00" }],
                        }))
                    }
                >
                    <Plus className="size-4" aria-hidden /> Add opening times
                </Button>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
                {NUMBER_FIELDS.map((field) => {
                    const id = `${idPrefix}-rule-${field.key}`;
                    const value = rules[field.key];
                    return (
                        <div key={field.key} className="flex flex-col gap-1">
                            <Label htmlFor={id} className="text-sm">
                                {field.label}
                                {field.optional && <span className="font-normal text-ink-3"> Optional</span>}
                            </Label>
                            <Input
                                id={id}
                                type="number"
                                min={field.min}
                                step={1}
                                inputMode="numeric"
                                value={value ?? ""}
                                placeholder={
                                    field.key in DEFAULTS ? String(DEFAULTS[field.key as keyof typeof DEFAULTS]) : "No limit"
                                }
                                onChange={(e) => {
                                    const raw = e.target.value;
                                    setRules((r) => ({ ...r, [field.key]: raw === "" ? undefined : Number(raw) }));
                                }}
                            />
                            <p className="text-[12px] text-ink-3">{field.help}</p>
                        </div>
                    );
                })}
            </div>

            {issues.length > 0 && (
                <ul className="list-disc pl-5 text-sm text-danger" role="alert">
                    {issues.map((issue) => (
                        <li key={issue}>{issue}</li>
                    ))}
                </ul>
            )}
            <div>
                <Button onClick={() => onSave(rules)} disabled={saving || issues.length > 0}>
                    {saving ? "Saving…" : "Save booking rules"}
                </Button>
            </div>
        </div>
    );
}
