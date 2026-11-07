"use client";

import { Clock, Plus, X } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { timeZoneOptions } from "@/lib/appointmentHours";
import { cn } from "@/lib/utils";

import {
    DAY_LONG,
    dayChips,
    defaultOpeningHours,
    describeOpeningHours,
    isOvernight,
    MAX_NOTE_LENGTH,
    MAX_RANGES_PER_DAY,
    nextRange,
    type OpeningHours,
    openingHoursProblem,
    type OpenRange,
    TIME_OPTIONS,
    timeLabel,
    weekOf,
} from "./openingHours";

const SELECT_CLASS =
    "h-9 w-full min-w-0 rounded-md border border-line bg-card px-2.5 text-sm text-ink outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:opacity-60";

/**
 * The "Opening hours" answer. With times set: seven day chips (the mock's
 * "Tue / 5–10 pm", a greyed "Mon / Closed"); a chip opens that day's
 * editor. Without: the owner's own words (*textField*) as before, with an
 * offer to set them as times. Their text is never read into times.
 */
export function OpeningHoursField({
    hours,
    onChange,
    textField,
    savedText,
    disabled,
}: {
    hours: OpeningHours | null;
    onChange: (hours: OpeningHours | null) => void;
    /** The free-text field, shown while no times are set. */
    textField: ReactNode;
    /** What the agent says now (the saved text). */
    savedText: string;
    disabled: boolean;
}) {
    if (!hours) {
        return (
            <div className="flex flex-col gap-2">
                {textField}
                {!disabled && (
                    <div className="flex flex-col gap-2 rounded-[10px] border border-sky/50 bg-sky-dim px-3.5 py-2.5 sm:flex-row sm:items-center">
                        <p className="min-w-0 flex-1 text-caption text-sky">
                            Set your hours as times so your agent knows when you&apos;re open and doesn&apos;t pass
                            calls to your team when you&apos;re closed.
                        </p>
                        <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="self-start sm:self-auto"
                            onClick={() => onChange(defaultOpeningHours())}
                        >
                            <Clock aria-hidden />
                            Set your hours as times
                        </Button>
                    </div>
                )}
            </div>
        );
    }
    return <TimesEditor hours={hours} onChange={onChange} savedText={savedText} disabled={disabled} />;
}

function TimesEditor({
    hours,
    onChange,
    savedText,
    disabled,
}: {
    hours: OpeningHours;
    onChange: (hours: OpeningHours | null) => void;
    savedText: string;
    disabled: boolean;
}) {
    const [selected, setSelected] = useState<number | null>(null);
    const week = weekOf(hours);
    const chips = dayChips(hours);
    const problem = openingHoursProblem(hours);
    const zones = useMemo(() => timeZoneOptions(hours.timezone ?? "Europe/Dublin"), [hours.timezone]);

    const setDay = (day: number, ranges: OpenRange[]) =>
        onChange({ ...hours, days: week.map((r, i) => (i === day ? ranges : r)) as OpeningHours["days"] });
    const copyToOpenDays = (day: number) =>
        onChange({
            ...hours,
            days: week.map((r, i) => (i === day || r.length === 0 ? r : week[day])) as OpeningHours["days"],
        });

    return (
        <div className="flex flex-col gap-3">
            <ul className="grid grid-cols-4 gap-1.5 @md/card:grid-cols-7" aria-label="Opening hours by day">
                {chips.map((chip, day) => (
                    <li key={chip.short} className="min-w-0">
                        <button
                            type="button"
                            disabled={disabled}
                            aria-pressed={selected === day}
                            aria-label={`${chip.long}: ${chip.lines ? chip.lines.join(" and ") : "Closed"}. Change`}
                            onClick={() => setSelected(selected === day ? null : day)}
                            className={cn(
                                "h-full w-full rounded-[9px] border px-1.5 py-1.5 text-center text-[12px] leading-snug outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/40 disabled:cursor-default",
                                chip.lines ? "border-line bg-card text-foreground" : "border-line bg-panel-2 text-ink-3",
                                selected === day && "border-brand ring-1 ring-brand",
                                !disabled && "hover:border-brand",
                            )}
                        >
                            <span className="block text-caption font-semibold">{chip.short}</span>
                            {chip.lines ? chip.lines.map((line) => <span key={line} className="block">{line}</span>) : "Closed"}
                        </button>
                    </li>
                ))}
            </ul>

            {selected !== null && !disabled && (
                <DayEditor
                    day={selected}
                    ranges={week[selected]}
                    onChange={(ranges) => setDay(selected, ranges)}
                    onCopy={() => copyToOpenDays(selected)}
                    onDone={() => setSelected(null)}
                />
            )}

            {problem && (
                <p role="alert" className="text-caption text-danger">
                    {problem}
                </p>
            )}

            <div className="grid gap-2.5 @md/card:grid-cols-2">
                <div className="flex min-w-0 flex-col gap-1">
                    <label htmlFor="opening-hours-timezone" className="text-[12px] font-medium text-ink-2">
                        Time zone
                    </label>
                    <select
                        id="opening-hours-timezone"
                        className={SELECT_CLASS}
                        value={hours.timezone ?? "Europe/Dublin"}
                        disabled={disabled}
                        onChange={(e) => onChange({ ...hours, timezone: e.target.value })}
                    >
                        {zones.map((zone) => (
                            <option key={zone} value={zone}>
                                {zone.replaceAll("_", " ")}
                            </option>
                        ))}
                    </select>
                </div>
                <div className="flex min-w-0 flex-col gap-1">
                    <label htmlFor="opening-hours-note" className="text-[12px] font-medium text-ink-2">
                        Anything to add? <span className="font-normal text-ink-3">Optional</span>
                    </label>
                    <Input
                        id="opening-hours-note"
                        className="h-9 text-sm"
                        value={hours.note ?? ""}
                        maxLength={MAX_NOTE_LENGTH}
                        disabled={disabled}
                        placeholder="e.g. Closed on bank holidays"
                        onChange={(e) => onChange({ ...hours, note: e.target.value })}
                    />
                </div>
            </div>

            <p className="text-caption text-ink-3">
                <span className="font-medium text-ink-2">Your agent says: </span>
                {problem ? savedText : describeOpeningHours(hours)}
            </p>
            {!disabled && (
                <button
                    type="button"
                    className="self-start text-caption font-medium text-brand underline-offset-2 hover:underline"
                    onClick={() => onChange(null)}
                >
                    Write your hours out instead
                </button>
            )}
        </div>
    );
}

function TimeSelect({
    id,
    label,
    value,
    onChange,
}: {
    id: string;
    label: string;
    value: string;
    onChange: (value: string) => void;
}) {
    const options = TIME_OPTIONS.includes(value) ? TIME_OPTIONS : [...TIME_OPTIONS, value].sort();
    return (
        <div className="flex min-w-0 flex-col gap-1">
            <label htmlFor={id} className="text-[12px] font-medium text-ink-2">
                {label}
            </label>
            <select id={id} className={SELECT_CLASS} value={value} onChange={(e) => onChange(e.target.value)}>
                {options.map((option) => (
                    <option key={option} value={option}>
                        {timeLabel(option)}
                    </option>
                ))}
            </select>
        </div>
    );
}

function DayEditor({
    day,
    ranges,
    onChange,
    onCopy,
    onDone,
}: {
    day: number;
    ranges: OpenRange[];
    onChange: (ranges: OpenRange[]) => void;
    onCopy: () => void;
    onDone: () => void;
}) {
    const name = DAY_LONG[day];
    const open = ranges.length > 0;
    const next = nextRange(ranges);
    const switchId = `opening-hours-open-${day}`;
    const setRange = (index: number, patch: Partial<OpenRange>) =>
        onChange(ranges.map((r, i) => (i === index ? { ...r, ...patch } : r)));

    return (
        <div role="group" aria-label={`${name} opening hours`} className="flex flex-col gap-2.5 rounded-[10px] border border-line p-3">
            <div className="flex items-center justify-between gap-3">
                <label htmlFor={switchId} className="text-sm font-semibold text-foreground">
                    Open on {name}
                </label>
                <Switch
                    id={switchId}
                    checked={open}
                    onCheckedChange={(checked) => onChange(checked ? [{ open: "09:00", close: "17:00" }] : [])}
                />
            </div>
            {ranges.map((range, index) => (
                <div key={index} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] items-end gap-2">
                    <TimeSelect
                        id={`opening-hours-${day}-${index}-open`}
                        label={index === 0 ? "Opens" : "Opens again"}
                        value={range.open}
                        onChange={(value) => setRange(index, { open: value })}
                    />
                    <TimeSelect
                        id={`opening-hours-${day}-${index}-close`}
                        label={isOvernight(range) ? "Closes (next day)" : "Closes"}
                        value={range.close}
                        onChange={(value) => setRange(index, { close: value })}
                    />
                    <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="size-9"
                        aria-label={`Remove ${name} ${timeLabel(range.open)} to ${timeLabel(range.close)}`}
                        onClick={() => onChange(ranges.filter((_, i) => i !== index))}
                    >
                        <X aria-hidden />
                    </Button>
                </div>
            ))}
            <div className="flex flex-wrap items-center gap-2">
                {open && ranges.length < MAX_RANGES_PER_DAY && next && (
                    <Button type="button" size="sm" variant="outline" onClick={() => onChange([...ranges, next])}>
                        <Plus aria-hidden />
                        Add opening time
                    </Button>
                )}
                {open && (
                    <Button type="button" size="sm" variant="ghost" onClick={onCopy}>
                        Same hours on every open day
                    </Button>
                )}
                <Button type="button" size="sm" variant="ghost" className="ml-auto" onClick={onDone}>
                    Done
                </Button>
            </div>
            <p className="text-[12px] text-ink-3">
                Split lunch and dinner with Add opening time. A closing time before the opening time is on the next day.
            </p>
        </div>
    );
}
