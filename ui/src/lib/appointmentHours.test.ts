import { afterEach, describe, expect, it, vi } from 'vitest';

import { emptyAnswers, missingAnswer } from './agentTemplates';
import {
    bookingHoursFromConfig,
    bookingHoursProblem,
    browserTimeZone,
    defaultBookingHours,
    hourLabel,
    slotLabel,
    timeZoneOptions,
} from './appointmentHours';

const FIELDS = [
    { key: 'business_name', label: 'Business name' },
    { key: 'appointment_hours', label: 'Appointment hours', type: 'appointment_hours' as const },
];

afterEach(() => {
    vi.restoreAllMocks();
});

function browserZone(zone: string | (() => never)) {
    vi.spyOn(Intl, 'DateTimeFormat').mockImplementation(
        () =>
            ({
                resolvedOptions: () => ({ timeZone: typeof zone === 'string' ? zone : zone() }),
            }) as unknown as Intl.DateTimeFormat,
    );
}

describe('default hours', () => {
    it('are Monday to Friday, 9 to 5, 30 minutes, in this browser’s time zone', () => {
        browserZone('America/New_York');
        expect(defaultBookingHours()).toEqual({
            booking_days: [0, 1, 2, 3, 4],
            open_hour: 9,
            close_hour: 17,
            slot_minutes: 30,
            timezone: 'America/New_York',
        });
    });

    it('fall back to Europe/Dublin when the browser can’t say', () => {
        browserZone('');
        expect(browserTimeZone()).toBe('Europe/Dublin');
        browserZone(() => {
            throw new RangeError('no Intl');
        });
        expect(browserTimeZone()).toBe('Europe/Dublin');
    });
});

describe('hours from a calendar connection', () => {
    it('keeps what the connection already books in', () => {
        expect(
            bookingHoursFromConfig({
                calendar_id: 'primary',
                booking_days: [6, 5, 5],
                open_hour: 8,
                close_hour: 12,
                slot_minutes: 20,
                timezone: 'Asia/Kolkata',
            }),
        ).toEqual({ booking_days: [5, 6], open_hour: 8, close_hour: 12, slot_minutes: 20, timezone: 'Asia/Kolkata' });
    });

    it('keeps this browser’s time zone over the calendar’s default one', () => {
        // A new connection saves every default, Europe/Dublin included.
        browserZone('America/Chicago');
        expect(bookingHoursFromConfig({ calendar_id: 'primary', timezone: 'Europe/Dublin' }).timezone).toBe(
            'America/Chicago',
        );
    });

    it('uses the defaults for settings it never saved or that make no sense', () => {
        browserZone('Europe/Berlin');
        expect(
            bookingHoursFromConfig({ calendar_id: 'primary', booking_days: [9, 'x'], open_hour: 9.5, close_hour: 30 }),
        ).toEqual(defaultBookingHours());
        expect(bookingHoursFromConfig(undefined).timezone).toBe('Europe/Berlin');
    });
});

describe('checking hours', () => {
    const ok = defaultBookingHours();

    it('accepts the defaults', () => {
        expect(bookingHoursProblem(ok)).toBeNull();
    });

    it.each([
        [{ booking_days: [] }, 'Pick at least one day.'],
        [{ open_hour: 17, close_hour: 9 }, 'The closing time must be after the opening time.'],
        [{ open_hour: 9, close_hour: 9 }, 'The closing time must be after the opening time.'],
        [{ open_hour: 9, close_hour: 10, slot_minutes: 90 }, 'An appointment is longer than these hours.'],
    ])('rejects %o', (patch, problem) => {
        expect(bookingHoursProblem({ ...ok, ...patch })).toBe(problem);
    });
});

describe('labels and choices', () => {
    it('labels hours and lengths', () => {
        expect(hourLabel(9)).toBe('09:00');
        expect(hourLabel(24)).toBe('24:00');
        expect(slotLabel(45)).toBe('45 min');
        expect(slotLabel(60)).toBe('1 h');
        expect(slotLabel(90)).toBe('1 h 30 min');
    });

    it('always offers the current time zone', () => {
        expect(timeZoneOptions('Europe/Dublin')).toContain('Europe/Dublin');
        expect(timeZoneOptions('Etc/Unlisted')[0]).toBe('Etc/Unlisted');
    });
});

describe('the appointment hours question', () => {
    it('is not a text answer', () => {
        expect(emptyAnswers(FIELDS)).toEqual({ business_name: '' });
        expect(missingAnswer(FIELDS, { business_name: 'Bloom' })).toBeNull();
    });
});
