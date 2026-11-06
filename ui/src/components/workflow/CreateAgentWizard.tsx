'use client';

import { ArrowLeft, ChevronLeft, Loader2 } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { type ReactNode, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import {
    createWorkflowApiV1WorkflowCreateDefinitionPost,
    createWorkflowFromTemplateApiV1WorkflowCreateTemplatePost,
    duplicateWorkflowTemplateApiV1WorkflowTemplatesDuplicatePost,
    getWorkflowTemplatesApiV1WorkflowTemplatesGet,
} from '@/client/sdk.gen';
import type { CalendarHoursStatus, WorkflowTemplateResponse } from '@/client/types.gen';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { agentTalkHref } from '@/components/workflow/agentLinks';
import { AgentReady, type ReadyItem } from '@/components/workflow/create/AgentReady';
import { TemplateGallery, TemplateIcon } from '@/components/workflow/create/TemplateGallery';
import { TemplateSetup } from '@/components/workflow/create/TemplateSetup';
import { useAppointmentHours } from '@/components/workflow/create/useAppointmentHours';
import { useIntegrationConnect } from '@/components/workflow/create/useIntegrationConnect';
import { useOrgConfig } from '@/context/OrgConfigContext';
import {
    agentNameFor,
    emptyAnswers,
    GOOGLE_CALENDAR,
    missingAnswer,
    sortTemplates,
} from '@/lib/agentTemplates';
import { detailFromError } from '@/lib/apiError';
import { useAuth } from '@/lib/auth';
import logger from '@/lib/logger';
import { cn } from '@/lib/utils';

/** What happened to the Google Calendar connection's booking hours. */
const CALENDAR_HOURS_ITEM: Record<CalendarHoursStatus, ReadyItem> = {
    updated: { text: 'Books only in your appointment hours', done: true },
    not_allowed: { text: 'Calendar booking hours', note: 'An owner or admin sets them on Bookings', done: false },
    failed: { text: 'Calendar booking hours', note: 'Not saved: set them on Bookings', done: false },
};

/** The agent exists; only saving the hours to the calendar failed. */
function warnHoursNotSaved() {
    toast.warning('Your agent is ready, but its appointment hours weren’t saved to Google Calendar.', {
        description: 'Set them on the Bookings page, under Booking rules.',
        action: {
            label: 'Open Bookings',
            onClick: () => window.open('/bookings', '_blank', 'noopener'),
        },
    });
}

/** Where the wizard opens: ready-made agents, or one of the other two ways. */
export type CreateMode = 'template' | 'describe' | 'blank';
type View = 'gallery' | 'setup' | 'ready' | 'describe' | 'blank';
type CallType = 'inbound' | 'outbound';

const NAME_MAX = 200;
const DESCRIPTION_MAX = 4000;

const DESCRIBE_EXAMPLES: { label: string; callType: CallType; text: string }[] = [
    {
        label: 'Book tables for my restaurant',
        callType: 'inbound',
        text: 'Answer calls for my restaurant. Tell people our opening hours and menu, book tables, and take a message for anything else. Be friendly and keep it short.',
    },
    {
        label: 'Ask customers for feedback',
        callType: 'outbound',
        text: 'Call customers a day after their visit. Ask how it went, ask them to rate it from 1 to 5, and note any complaints for the team. Keep it under two minutes.',
    },
    {
        label: 'Remind people of their visit',
        callType: 'outbound',
        text: 'Call customers the day before their appointment. Confirm the time, and if they can’t make it, offer to move it or take a message for the team.',
    },
];

const BLANK_WORKFLOW_DEFINITION = {
    nodes: [
        {
            id: '1',
            type: 'startCall',
            position: { x: 175, y: 60 },
            data: {
                prompt:
                    "# Goal\nYou are a helpful agent who is handing a conversation over voice with a human. This is a voice conversation, so transcripts can be error prone.\n\n## Rules\n- Language: UK English but does not have to be correct english\n- Keep responses short and 2-3 sentences max\n- If you have to repeat something that you said in your previous two turns, then rephrase a bit while keeping the same meaning. Never repeat the exact same words as in your previous 2 responses.\n\n## Speech Handling\n- There could be multiple transcription errors. \n- Accept variations: yes/yeah/yep/aye, no/nah/nope\n- If user says \"sorry?\" or \"pardon me\" or \"can you repeat\"  or \"what?\", they might not have heard you- so just repeat what you just said.\n\n### Flow\nStart by saying \"Hi\". Be polite and courteous. ",
                name: 'start call',
                allow_interrupt: false,
                invalid: false,
                validationMessage: null,
                add_global_prompt: false,
                delayed_start: false,
                is_start: true,
                selected_through_edge: false,
                hovered_through_edge: false,
                extraction_enabled: false,
                selected: false,
                dragging: false,
            },
        },
    ],
    edges: [],
    viewport: { x: 808, y: 269, zoom: 0.75 },
};

function shortUseCase(description: string): string {
    const first = description.trim().split(/(?<=[.!?])\s/)[0] ?? '';
    return first.slice(0, 120).trim();
}

function BackLink({ onClick, children }: { onClick: () => void; children: ReactNode }) {
    return (
        <button
            type="button"
            onClick={onClick}
            className="flex w-fit items-center gap-1 text-[13px] font-semibold text-brand hover:underline focus-visible:outline-2 focus-visible:outline-ring"
        >
            <ChevronLeft size={14} aria-hidden />
            {children}
        </button>
    );
}

function StepRail({ step }: { step: 1 | 2 | 3 }) {
    const labels = ['Choose template', 'Personalise', 'Ready'] as const;
    return (
        <>
        {/* A phone has no room for three chips: one line says where you are. */}
        <p className="text-[12.5px] font-medium text-ink-2 sm:hidden">
            {`Step ${step} of 3 · ${labels[step - 1]}`}
        </p>
        <ol className="hidden flex-wrap items-center gap-2 sm:flex" aria-label="Progress">
            {labels.map((label, index) => {
                const n = (index + 1) as 1 | 2 | 3;
                const active = n === step;
                const done = n < step;
                return (
                    <li key={label} className="flex items-center gap-2">
                        {index > 0 && <span className="hidden h-px w-6 bg-line sm:block" aria-hidden />}
                        <span
                            className={cn(
                                'inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[12.5px] font-medium',
                                active && 'border-brand bg-brand-dim text-brand',
                                done && 'border-line bg-panel-2 text-ink-2',
                                !active && !done && 'border-line text-ink-3',
                            )}
                        >
                            <span className="font-mono text-[11px]">{n}</span>
                            {label}
                        </span>
                    </li>
                );
            })}
        </ol>
        </>
    );
}

interface CreateAgentWizardProps {
    initialMode?: CreateMode;
}

/**
 * Full-page create flow: pick a ready-made agent, answer its questions (and
 * optionally connect a calendar), then talk to it. Describe / blank are quieter
 * side paths.
 */
export function CreateAgentWizard({ initialMode = 'template' }: CreateAgentWizardProps) {
    const router = useRouter();
    const { user, loading: authLoading, redirectToLogin } = useAuth();
    const { can } = useOrgConfig();

    const [view, setView] = useState<View>(initialMode === 'template' ? 'gallery' : initialMode);
    const [templates, setTemplates] = useState<WorkflowTemplateResponse[] | null>(null);
    const [templatesFailed, setTemplatesFailed] = useState(false);
    const [template, setTemplate] = useState<WorkflowTemplateResponse | null>(null);
    const [answers, setAnswers] = useState<Record<string, string>>({});
    const [answerErrors, setAnswerErrors] = useState<Record<string, string>>({});
    const [useCalendar, setUseCalendar] = useState(true);
    const [created, setCreated] = useState<{ id: number; items: ReadyItem[] } | null>(null);
    const [callType, setCallType] = useState<CallType>('inbound');
    const [description, setDescription] = useState('');
    const [blankName, setBlankName] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const wantsCalendar = view === 'setup' && !!template?.integrations?.includes(GOOGLE_CALENDAR);
    const calendar = useIntegrationConnect(GOOGLE_CALENDAR, wantsCalendar && !!user);
    const calendarTool =
        wantsCalendar && useCalendar && calendar.status === 'connected'
            ? calendar.connection?.tool_uuids?.[0]
            : undefined;
    const hours = useAppointmentHours(template, calendar, !!calendarTool, can('integrations:write'));

    useEffect(() => {
        setView(initialMode === 'template' ? 'gallery' : initialMode);
        setCreated(null);
        setError(null);
    }, [initialMode]);

    // A full page, unlike the old dialog: nothing behind it sends a signed-out
    // visitor to sign in, and the templates would never load.
    useEffect(() => {
        if (!authLoading && !user) redirectToLogin();
    }, [authLoading, user, redirectToLogin]);

    useEffect(() => {
        if (templates !== null || templatesFailed || !user) return;
        let cancelled = false;
        (async () => {
            let failure: unknown = null;
            try {
                const response = await getWorkflowTemplatesApiV1WorkflowTemplatesGet();
                if (cancelled) return;
                if (!response.error) {
                    setTemplates(response.data ?? []);
                    return;
                }
                failure = response.error;
            } catch (err) {
                if (cancelled) return;
                failure = String(err);
            }
            logger.error(`Error loading templates: ${JSON.stringify(failure)}`);
            setTemplatesFailed(true);
        })();
        return () => {
            cancelled = true;
        };
    }, [templates, templatesFailed, user]);

    // Each step replaces the page, so move focus (and the scroll) to its heading
    // instead of leaving it on a button that no longer exists.
    // Compared with the last step rather than skipping the first run, which
    // Strict Mode runs twice.
    const pageRef = useRef<HTMLDivElement>(null);
    const shownView = useRef(view);
    useEffect(() => {
        if (shownView.current === view) return;
        shownView.current = view;
        const heading = pageRef.current?.querySelector<HTMLElement>('h1');
        if (!heading) return;
        heading.tabIndex = -1;
        // A heading isn't a control: no focus ring for it.
        heading.style.outline = 'none';
        heading.focus();
    }, [view]);

    // Preview a featured template as soon as the gallery loads.
    useEffect(() => {
        if (view !== 'gallery' || template || !templates?.length) return;
        const first = sortTemplates(templates)[0];
        setTemplate(first);
        setAnswers(emptyAnswers(first.setup_fields ?? []));
        setUseCalendar(true);
    }, [view, template, templates]);

    const go = (next: View) => {
        setView(next);
        setError(null);
    };

    const selectTemplate = (picked: WorkflowTemplateResponse) => {
        if (picked.id !== template?.id) {
            setTemplate(picked);
            setAnswers(emptyAnswers(picked.setup_fields ?? []));
            setUseCalendar(true);
            setAnswerErrors({});
        }
    };

    const continueWithTemplate = () => {
        if (!template) return;
        setAnswerErrors({});
        go('setup');
    };

    const fail = (mode: string, detail: unknown, fallback: string) => {
        logger.error(`Error creating agent (${mode}): ${JSON.stringify(detail)}`);
        setError(detailFromError(detail, fallback));
        setSubmitting(false);
    };

    const createFromTemplate = async () => {
        if (!template || submitting) return;
        const fields = template.setup_fields ?? [];
        const missing = missingAnswer(fields, answers);
        if (missing) {
            setAnswerErrors({ [missing.key]: `Please add ${missing.label.toLowerCase()}.` });
            document.getElementById(`setup-${missing.key}`)?.focus();
            return;
        }
        if (hours.field && hours.problem) {
            // The hours input already says what is wrong.
            document.getElementById(`setup-${hours.field.key}-open`)?.focus();
            return;
        }
        setAnswerErrors({});
        setSubmitting(true);
        setError(null);
        try {
            const response = await duplicateWorkflowTemplateApiV1WorkflowTemplatesDuplicatePost({
                body: {
                    template_id: template.id,
                    workflow_name: agentNameFor(template, answers),
                    values: Object.fromEntries(Object.entries(answers).map(([k, v]) => [k, v.trim()])),
                    integration_tools: calendarTool ? { [GOOGLE_CALENDAR]: calendarTool } : {},
                    ...hours.request,
                },
            });
            if (response.error || !response.data?.id) {
                fail('template', response.error, 'Couldn’t create the agent. Please try again.');
                return;
            }
            const items: ReadyItem[] = [{ text: 'Uses your business details', done: true }];
            if (wantsCalendar) {
                items.push(
                    calendarTool
                        ? { text: 'Books into Google Calendar', done: true }
                        : { text: 'Books appointments', note: 'Takes a message for now', done: false },
                );
            }
            const calendarHours = response.data.calendar_hours;
            if (calendarHours) {
                items.push(CALENDAR_HOURS_ITEM[calendarHours]);
                if (calendarHours === 'failed') warnHoursNotSaved();
            }
            items.push({ text: 'Ready for a test call', done: true });
            setCreated({ id: response.data.id, items });
            setSubmitting(false);
            go('ready');
        } catch (err) {
            fail('template', String(err), 'Couldn’t create the agent. Please try again.');
        }
    };

    const createFromDescription = async () => {
        if (!description.trim() || submitting) return;
        setSubmitting(true);
        setError(null);
        try {
            const response = await createWorkflowFromTemplateApiV1WorkflowCreateTemplatePost({
                body: {
                    call_type: callType,
                    use_case: shortUseCase(description),
                    activity_description: description.trim(),
                },
            });
            if (response.error || !response.data?.id) {
                fail('describe', response.error, 'Couldn’t build the agent. Please try again.');
                return;
            }
            router.push(agentTalkHref(response.data.id));
        } catch (err) {
            fail('describe', String(err), 'Couldn’t build the agent. Please try again.');
        }
    };

    const createBlank = async () => {
        if (submitting) return;
        setSubmitting(true);
        setError(null);
        try {
            const response = await createWorkflowApiV1WorkflowCreateDefinitionPost({
                body: {
                    name: blankName.trim() || 'Untitled agent',
                    workflow_definition: BLANK_WORKFLOW_DEFINITION as unknown as { [key: string]: unknown },
                },
            });
            if (response.error || !response.data?.id) {
                fail('blank', response.error, 'Couldn’t create the agent. Please try again.');
                return;
            }
            router.push(`/workflow/${response.data.id}?onboarding=web_call`);
        } catch (err) {
            fail('blank', String(err), 'Couldn’t create the agent. Please try again.');
        }
    };

    const errorLine = error && (
        <p className="text-[13px] text-danger" role="alert">
            {error}
        </p>
    );

    const step: 1 | 2 | 3 = view === 'ready' ? 3 : view === 'setup' ? 2 : 1;

    return (
        <div ref={pageRef} className="mx-auto flex w-full max-w-7xl flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="flex flex-col gap-2">
                    <Link
                        href="/workflow"
                        className="-ml-1 inline-flex min-h-10 w-fit items-center gap-1.5 rounded-md px-1 text-[13px] font-semibold text-ink-3 hover:text-ink hover:underline focus-visible:outline-2 focus-visible:outline-ring sm:min-h-0"
                    >
                        <ArrowLeft className="size-3.5" aria-hidden />
                        Back to agents
                    </Link>
                    {(view === 'gallery' || view === 'setup' || view === 'ready') && <StepRail step={step} />}
                </div>
            </div>

            {view === 'gallery' && (
                <section className="flex min-h-0 flex-1 flex-col gap-4">
                    <header className="flex flex-col gap-1.5 sm:flex-row sm:items-end sm:justify-between">
                        <div className="flex flex-col gap-1">
                            <h1 className="font-display text-[24px] tracking-[-0.02em] text-ink">
                                What should your agent do?
                            </h1>
                            <p className="max-w-2xl text-[14px] text-ink-2">
                                Pick a ready-made agent for phone or VoIP, preview it, then personalise.
                            </p>
                        </div>
                        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]">
                            <button
                                type="button"
                                onClick={() => go('describe')}
                                className="min-h-10 font-semibold text-brand hover:underline focus-visible:outline-2 focus-visible:outline-ring sm:min-h-0"
                            >
                                Describe it in your own words →
                            </button>
                            <button
                                type="button"
                                onClick={() => go('blank')}
                                className="min-h-10 text-ink-3 hover:text-ink hover:underline focus-visible:outline-2 focus-visible:outline-ring sm:min-h-0"
                            >
                                Start from scratch
                            </button>
                        </div>
                    </header>
                    <TemplateGallery
                        templates={templates}
                        loadFailed={templatesFailed}
                        onRetry={() => setTemplatesFailed(false)}
                        selectedId={template?.id ?? null}
                        onSelect={selectTemplate}
                        onContinue={continueWithTemplate}
                        onDescribe={() => go('describe')}
                    />
                </section>
            )}

            {view === 'setup' && template && (
                <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-line bg-card">
                    <header className="flex flex-row items-center gap-3.5 border-b border-line-soft px-5 py-4 sm:px-6">
                        <Button
                            variant="outline"
                            size="icon"
                            className="size-9 shrink-0"
                            onClick={() => go('gallery')}
                            disabled={submitting}
                            aria-label="Back to ready-made agents"
                        >
                            <ChevronLeft size={16} />
                        </Button>
                        <span className="hidden size-9 shrink-0 items-center justify-center rounded-[9px] bg-brand-dim text-brand sm:flex">
                            <TemplateIcon name={template.icon} size={18} />
                        </span>
                        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                            <h1 className="font-display text-[19px] tracking-[-0.02em] text-ink">
                                Personalise your {template.template_name}
                            </h1>
                            <p className="text-[13px] text-ink-3">
                                Tell it about your business
                                {wantsCalendar ? ' · Connect calendar (optional)' : ''}
                            </p>
                        </div>
                    </header>
                    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
                        <TemplateSetup
                            template={template}
                            answers={answers}
                            errors={answerErrors}
                            onAnswer={(key, value) => {
                                setAnswers((current) => ({ ...current, [key]: value }));
                                setAnswerErrors((current) => (current[key] ? {} : current));
                            }}
                            calendar={wantsCalendar ? calendar : null}
                            useCalendar={useCalendar}
                            onUseCalendarChange={setUseCalendar}
                            hours={hours}
                        />
                        {errorLine && <div className="px-6 pb-4">{errorLine}</div>}
                    </div>
                    <footer className="flex flex-col gap-3 border-t border-line-soft bg-panel-2 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
                        <p className="text-[13px] text-ink-3">You can change any of this later.</p>
                        <div className="flex justify-end gap-2">
                            <Button variant="outline" onClick={() => go('gallery')} disabled={submitting}>
                                Back
                            </Button>
                            <Button onClick={createFromTemplate} disabled={submitting}>
                                {submitting && <Loader2 size={15} className="animate-spin" aria-hidden />}
                                {submitting ? 'Creating…' : 'Create agent'}
                            </Button>
                        </div>
                    </footer>
                </section>
            )}

            {view === 'ready' && created && (
                <section className="mx-auto w-full max-w-lg overflow-hidden rounded-xl border border-line bg-card">
                    <AgentReady
                        agentId={created.id}
                        items={created.items}
                        onTalk={() => router.push(agentTalkHref(created.id))}
                    />
                </section>
            )}

            {view === 'describe' &&
                (submitting ? (
                    <section
                        className="flex flex-col items-center rounded-xl border border-line bg-card px-6 py-16 text-center"
                        role="status"
                    >
                        <h1 className="sr-only">Building your agent</h1>
                        <Loader2 size={28} className="animate-spin text-brand" aria-hidden />
                        <p className="mt-4 text-[15px] font-semibold text-ink">Building your agent</p>
                        <p className="mt-1 max-w-sm text-[13.5px] text-ink-2">
                            Writing what it says and how it handles each step. This takes about 20 seconds.
                        </p>
                    </section>
                ) : (
                    <section className="flex flex-col gap-5 rounded-xl border border-line bg-card p-5 sm:p-6">
                        <BackLink onClick={() => go('gallery')}>Ready-made agents</BackLink>
                        <header className="flex flex-col gap-1.5">
                            <h1 className="font-display text-[22px] tracking-[-0.02em] text-ink">
                                Tell us what your agent should do
                            </h1>
                            <p className="text-[14px] text-ink-2">
                                Write it like you would explain it to a new employee. We build the agent for you.
                            </p>
                        </header>
                        <div className="space-y-4">
                            <div role="radiogroup" aria-label="Who starts the call" className="grid gap-2.5 sm:grid-cols-2">
                                {(
                                    [
                                        ['inbound', 'It answers calls', 'People call your number or website.'],
                                        ['outbound', 'It makes calls', 'It calls your customers for you.'],
                                    ] as const
                                ).map(([value, title, body]) => (
                                    <button
                                        key={value}
                                        type="button"
                                        role="radio"
                                        aria-checked={callType === value}
                                        onClick={() => setCallType(value)}
                                        className={cn(
                                            'flex flex-col gap-0.5 rounded-lg border p-3.5 text-left transition-colors focus-visible:outline-2 focus-visible:outline-ring',
                                            callType === value
                                                ? 'border-brand bg-brand-dim'
                                                : 'border-line bg-card hover:bg-panel-2',
                                        )}
                                    >
                                        <span
                                            className={cn(
                                                'text-[14px] font-semibold',
                                                callType === value ? 'text-brand' : 'text-ink',
                                            )}
                                        >
                                            {title}
                                        </span>
                                        <span className="text-[12.5px] text-ink-2">{body}</span>
                                    </button>
                                ))}
                            </div>
                            <div className="space-y-1.5">
                                <Label htmlFor="agent-description">What should it do?</Label>
                                <Textarea
                                    id="agent-description"
                                    placeholder="Answer calls for my hair salon. Tell people our prices and opening hours, book appointments, and take a message if they want to speak to the owner. Be friendly and keep it short."
                                    value={description}
                                    maxLength={DESCRIPTION_MAX}
                                    onChange={(event) => setDescription(event.target.value)}
                                    className="min-h-[136px] text-[14.5px]"
                                />
                            </div>
                            <div className="flex flex-wrap items-center gap-2">
                                <span className="text-[12.5px] text-ink-3">Try:</span>
                                {DESCRIBE_EXAMPLES.map((example) => (
                                    <button
                                        key={example.label}
                                        type="button"
                                        onClick={() => {
                                            setCallType(example.callType);
                                            setDescription(example.text);
                                        }}
                                        className="h-[30px] rounded-full border border-line bg-panel-2 px-3 text-[12.5px] font-medium text-ink-2 hover:text-ink focus-visible:outline-2 focus-visible:outline-ring"
                                    >
                                        {example.label}
                                    </button>
                                ))}
                            </div>
                            {errorLine}
                        </div>
                        <footer className="flex items-center justify-between border-t border-line-soft pt-4">
                            <p className="text-[13px] text-ink-3">Takes about 20 seconds.</p>
                            <Button onClick={createFromDescription} disabled={!description.trim()}>
                                Build my agent
                            </Button>
                        </footer>
                    </section>
                ))}

            {view === 'blank' && (
                <section className="flex flex-col gap-5 rounded-xl border border-line bg-card p-5 sm:p-6">
                    <BackLink onClick={() => go('gallery')}>Ready-made agents</BackLink>
                    <header className="flex flex-col gap-1.5">
                        <h1 className="font-display text-[22px] tracking-[-0.02em] text-ink">Start from scratch</h1>
                        <p className="text-[14px] text-ink-2">
                            An empty agent with one step, for building the conversation yourself in the editor.
                        </p>
                    </header>
                    <div className="space-y-1.5">
                        <Label htmlFor="agent-name">Name</Label>
                        <Input
                            id="agent-name"
                            placeholder="Untitled agent"
                            value={blankName}
                            maxLength={NAME_MAX}
                            onChange={(event) => setBlankName(event.target.value)}
                            onKeyDown={(event) => {
                                if (event.key === 'Enter') createBlank();
                            }}
                        />
                    </div>
                    {errorLine}
                    <footer className="flex justify-end border-t border-line-soft pt-4">
                        <Button onClick={createBlank} disabled={submitting}>
                            {submitting ? 'Creating…' : 'Create and open'}
                        </Button>
                    </footer>
                </section>
            )}
        </div>
    );
}
