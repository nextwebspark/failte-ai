'use client';

import { CalendarDays, Check, Loader2 } from 'lucide-react';

import type { TemplateSetupField, WorkflowTemplateResponse } from '@/client/types.gen';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { previewParts, templateGreeting } from '@/lib/agentTemplates';
import { cn } from '@/lib/utils';

import type { IntegrationConnect } from './useIntegrationConnect';

const INPUT_TYPE: Record<string, string> = { url: 'url', email: 'email', phone: 'tel', text: 'text' };

function GoogleMark() {
    return (
        <svg width="15" height="15" viewBox="0 0 24 24" aria-hidden>
            <path fill="#4285F4" d="M22 12.2c0-.7-.1-1.4-.2-2H12v3.8h5.6a4.8 4.8 0 0 1-2.1 3.1v2.6h3.4c2-1.8 3.1-4.5 3.1-7.5z" />
            <path fill="#34A853" d="M12 22c2.8 0 5.2-.9 6.9-2.5l-3.4-2.6c-.9.6-2.1 1-3.5 1-2.7 0-5-1.8-5.8-4.3H2.7v2.7A10 10 0 0 0 12 22z" />
            <path fill="#FBBC05" d="M6.2 13.6a6 6 0 0 1 0-3.8V7.1H2.7a10 10 0 0 0 0 9.2z" />
            <path fill="#EA4335" d="M12 6c1.5 0 2.9.5 4 1.5l3-3A10 10 0 0 0 2.7 7.1l3.5 2.7C7 7.8 9.3 6 12 6z" />
        </svg>
    );
}

function SetupInput({
    field,
    value,
    error,
    onChange,
}: {
    field: TemplateSetupField;
    value: string;
    error?: string;
    onChange: (value: string) => void;
}) {
    const id = `setup-${field.key}`;
    const hintId = `${id}-hint`;
    const common = {
        id,
        value,
        maxLength: field.max_length ?? 500,
        // "e.g." so an example never reads as an answer already given.
        placeholder: field.placeholder ? `e.g. ${field.placeholder}` : undefined,
        'aria-invalid': error ? true : undefined,
        'aria-describedby': error || field.help ? hintId : undefined,
    };
    return (
        <div className="flex flex-col gap-1.5">
            <Label htmlFor={id}>
                {field.label}
                {field.required === false && <span className="font-normal text-ink-3">Optional</span>}
            </Label>
            {field.type === 'textarea' ? (
                <Textarea {...common} rows={2} className="min-h-[64px]" onChange={(e) => onChange(e.target.value)} />
            ) : (
                <Input {...common} type={INPUT_TYPE[field.type ?? 'text'] ?? 'text'} onChange={(e) => onChange(e.target.value)} />
            )}
            {(error || field.help) && (
                <p id={hintId} className={cn('text-[12.5px]', error ? 'text-danger' : 'text-ink-3')}>
                    {error ?? field.help}
                </p>
            )}
        </div>
    );
}

function CalendarCard({
    calendar,
    useCalendar,
    onUseCalendarChange,
}: {
    calendar: IntegrationConnect;
    useCalendar: boolean;
    onUseCalendarChange: (value: boolean) => void;
}) {
    if (calendar.status === 'loading') return <Skeleton className="h-[74px] rounded-lg" />;

    const connected = calendar.status === 'connected';
    return (
        <div className="flex flex-col gap-2">
            <span className="text-[13px] font-semibold text-ink">Bookings</span>
            <div className="flex flex-col gap-3 rounded-lg border border-line p-3.5 sm:flex-row sm:items-center">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-[10px] border border-line bg-panel-2 text-ink-2">
                    <CalendarDays size={20} strokeWidth={1.8} aria-hidden />
                </span>
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="text-[14px] font-semibold text-ink">
                        {connected ? 'Google Calendar connected' : 'Let callers book appointments'}
                    </span>
                    <span className="text-[12.5px] text-ink-2">
                        {connected
                            ? calendar.connection?.account_label
                                ? `Bookings go into ${calendar.connection.account_label}’s calendar.`
                                : 'Bookings go straight into your calendar.'
                            : 'Your agent checks free times and books straight into your calendar.'}
                    </span>
                </div>
                {connected ? (
                    <label className="flex shrink-0 cursor-pointer items-center gap-2 text-[13px] font-medium text-ink">
                        <Checkbox
                            checked={useCalendar}
                            onCheckedChange={(value) => onUseCalendarChange(value === true)}
                        />
                        Use for bookings
                    </label>
                ) : calendar.status === 'unavailable' ? null : (
                    <Button
                        type="button"
                        variant="outline"
                        className="shrink-0"
                        onClick={calendar.connect}
                        disabled={calendar.status === 'connecting'}
                    >
                        {calendar.status === 'connecting' ? (
                            <Loader2 size={15} className="animate-spin" aria-hidden />
                        ) : (
                            <GoogleMark />
                        )}
                        {calendar.status === 'connecting' ? 'Waiting for Google…' : 'Connect Google Calendar'}
                    </Button>
                )}
            </div>
            {calendar.error && (
                <p className="text-[12.5px] text-danger" role="alert">
                    {calendar.error}
                </p>
            )}
            {calendar.status === 'connecting' && (
                <p className="text-[12.5px] text-ink-3">
                    Finish signing in to Google in the window that opened.{' '}
                    <button
                        type="button"
                        onClick={calendar.cancel}
                        className="font-semibold text-brand hover:underline focus-visible:outline-2 focus-visible:outline-ring"
                    >
                        Cancel
                    </button>
                </p>
            )}
            {!connected && calendar.status !== 'connecting' && (
                <p className="text-[12.5px] text-ink-3">
                    {calendar.status === 'unavailable'
                        ? 'For now your agent takes a message when someone wants to book. A workspace admin can connect Google Calendar in Integrations.'
                        : 'Not ready? Skip it. Your agent takes a message instead, and you can connect later.'}
                </p>
            )}
        </div>
    );
}

interface TemplateSetupProps {
    template: WorkflowTemplateResponse;
    answers: Record<string, string>;
    errors: Record<string, string>;
    onAnswer: (key: string, value: string) => void;
    calendar: IntegrationConnect | null;
    useCalendar: boolean;
    onUseCalendarChange: (value: boolean) => void;
}

/** The template's questions, its calendar, and how the greeting will sound. */
export function TemplateSetup({
    template,
    answers,
    errors,
    onAnswer,
    calendar,
    useCalendar,
    onUseCalendarChange,
}: TemplateSetupProps) {
    const fields = template.setup_fields ?? [];
    const greeting = templateGreeting(template);

    return (
        <div className="flex min-h-0 flex-1 flex-col md:flex-row">
            <div className="flex min-w-0 flex-1 flex-col gap-4 px-6 py-5">
                {fields.map((field) => (
                    <SetupInput
                        key={field.key}
                        field={field}
                        value={answers[field.key] ?? ''}
                        error={errors[field.key]}
                        onChange={(value) => onAnswer(field.key, value)}
                    />
                ))}
                {calendar && (
                    <CalendarCard calendar={calendar} useCalendar={useCalendar} onUseCalendarChange={onUseCalendarChange} />
                )}
            </div>
            {greeting && (
                <aside
                    aria-label="Preview"
                    className="hidden w-[280px] shrink-0 flex-col gap-3 border-l border-line-soft bg-panel-2 p-5 md:flex"
                >
                    <span className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-ink-3">
                        How it will sound
                    </span>
                    <p className="rounded-[12px_12px_12px_4px] border border-line bg-card px-3 py-2.5 text-[13.5px] leading-[1.45] text-ink">
                        {previewParts(greeting, fields, answers).map((part, index) =>
                            part.answer ? (
                                <strong key={index} className="font-semibold text-brand">
                                    {part.text}
                                </strong>
                            ) : (
                                <span key={index}>{part.text}</span>
                            ),
                        )}
                    </p>
                    <span className="text-[12px] text-ink-3">The first thing callers hear.</span>
                    {calendar?.status === 'connected' && useCalendar && (
                        <span className="mt-auto flex items-center gap-1.5 text-[12.5px] text-ink-2">
                            <Check size={14} className="text-brand" aria-hidden />
                            Books into your calendar
                        </span>
                    )}
                </aside>
            )}
        </div>
    );
}
