'use client';

import { useMemo } from 'react';

import type { TemplateSetupField, Weekday } from '@/client/types.gen';
import {
    type BookingHours,
    bookingHoursProblem,
    CLOSE_HOURS,
    hourLabel,
    OPEN_HOURS,
    SLOT_MINUTES,
    slotLabel,
    timeZoneOptions,
    WEEKDAYS,
} from '@/lib/appointmentHours';
import { cn } from '@/lib/utils';

const SELECT_CLASS =
    'h-9 w-full min-w-0 rounded-md border border-line bg-card px-2.5 text-[13.5px] text-ink outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/40';

/** Where the hours go, which the user should know before saving them. */
export type HoursTarget = 'calendar' | 'calendar_admin_only' | 'prompt';

const TARGET_NOTE: Record<HoursTarget, string> = {
    calendar:
        'These become the booking hours of your Google Calendar connection, shared by every agent in this workspace that books with it.',
    calendar_admin_only:
        'Your agent tells callers these hours. Only a workspace admin can change the booking hours of your Google Calendar connection (Integrations → Google Calendar → Settings).',
    prompt: 'Your agent tells callers these hours.',
};

function SelectField({
    id,
    label,
    value,
    options,
    onChange,
}: {
    id: string;
    label: string;
    value: string;
    options: { value: string; label: string }[];
    onChange: (value: string) => void;
}) {
    return (
        <div className="flex min-w-0 flex-col gap-1">
            <label htmlFor={id} className="text-[12px] font-medium text-ink-2">
                {label}
            </label>
            <select id={id} className={SELECT_CLASS} value={value} onChange={(e) => onChange(e.target.value)}>
                {options.map((option) => (
                    <option key={option.value} value={option.value}>
                        {option.label}
                    </option>
                ))}
            </select>
        </div>
    );
}

interface AppointmentHoursInputProps {
    field: TemplateSetupField;
    value: BookingHours;
    onChange: (value: BookingHours) => void;
    target: HoursTarget;
}

/**
 * When callers can book: the days, one opening window in whole hours, the
 * length of an appointment and the time zone (the Google Calendar
 * connection's booking settings).
 */
export function AppointmentHoursInput({ field, value, onChange, target }: AppointmentHoursInputProps) {
    const id = `setup-${field.key}`;
    const problem = bookingHoursProblem(value);
    const zones = useMemo(() => timeZoneOptions(value.timezone), [value.timezone]);
    const slots = SLOT_MINUTES.includes(value.slot_minutes)
        ? SLOT_MINUTES
        : [...SLOT_MINUTES, value.slot_minutes].sort((a, b) => a - b);

    const set = (patch: Partial<BookingHours>) => onChange({ ...value, ...patch });
    const toggleDay = (day: Weekday) =>
        set({
            booking_days: value.booking_days.includes(day)
                ? value.booking_days.filter((d) => d !== day)
                : [...value.booking_days, day].sort((a, b) => a - b),
        });

    return (
        <div
            role="group"
            aria-labelledby={`${id}-label`}
            aria-describedby={`${id}-hint`}
            className="flex flex-col gap-3 rounded-lg border border-line p-3.5"
        >
            <div className="flex flex-col gap-0.5">
                <span id={`${id}-label`} className="text-[14px] font-semibold text-ink">
                    {field.label}
                </span>
                {field.help && <span className="text-[12.5px] text-ink-2">{field.help}</span>}
            </div>
            <div role="group" aria-label="Days" className="flex flex-wrap gap-1.5">
                {WEEKDAYS.map((day) => {
                    const on = value.booking_days.includes(day.value);
                    return (
                        <button
                            key={day.value}
                            type="button"
                            aria-pressed={on}
                            aria-label={day.long}
                            onClick={() => toggleDay(day.value)}
                            className={cn(
                                'h-8 min-w-[44px] rounded-md border px-2 text-[12.5px] font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-ring',
                                on
                                    ? 'border-brand bg-brand-dim text-brand'
                                    : 'border-line bg-card text-ink-3 hover:bg-panel-2',
                            )}
                        >
                            {day.short}
                        </button>
                    );
                })}
            </div>
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                <SelectField
                    id={`${id}-open`}
                    label="From"
                    value={String(value.open_hour)}
                    options={OPEN_HOURS.map((hour) => ({ value: String(hour), label: hourLabel(hour) }))}
                    onChange={(hour) => set({ open_hour: Number(hour) })}
                />
                <SelectField
                    id={`${id}-close`}
                    label="To"
                    value={String(value.close_hour)}
                    options={CLOSE_HOURS.map((hour) => ({ value: String(hour), label: hourLabel(hour) }))}
                    onChange={(hour) => set({ close_hour: Number(hour) })}
                />
                <div className="col-span-2">
                    <SelectField
                        id={`${id}-length`}
                        label="Appointment length"
                        value={String(value.slot_minutes)}
                        options={slots.map((minutes) => ({ value: String(minutes), label: slotLabel(minutes) }))}
                        onChange={(minutes) => set({ slot_minutes: Number(minutes) })}
                    />
                </div>
            </div>
            <SelectField
                id={`${id}-timezone`}
                label="Time zone"
                value={value.timezone}
                options={zones.map((zone) => ({ value: zone, label: zone.replaceAll('_', ' ') }))}
                onChange={(timezone) => set({ timezone })}
            />
            {problem && (
                <p role="alert" className="text-[12.5px] text-danger">
                    {problem}
                </p>
            )}
            <p id={`${id}-hint`} className="text-[12.5px] text-ink-3">
                {TARGET_NOTE[target]}
            </p>
        </div>
    );
}
