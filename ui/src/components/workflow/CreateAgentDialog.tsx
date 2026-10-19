'use client';

import { ChevronLeft, Loader2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { type ReactNode, useEffect, useState } from 'react';

import {
    createWorkflowApiV1WorkflowCreateDefinitionPost,
    createWorkflowFromTemplateApiV1WorkflowCreateTemplatePost,
    duplicateWorkflowTemplateApiV1WorkflowTemplatesDuplicatePost,
    getWorkflowTemplatesApiV1WorkflowTemplatesGet,
} from '@/client/sdk.gen';
import type { WorkflowTemplateResponse } from '@/client/types.gen';
import { Button } from '@/components/ui/button';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { AgentReady, type ReadyItem } from '@/components/workflow/create/AgentReady';
import { TemplateGallery, TemplateIcon } from '@/components/workflow/create/TemplateGallery';
import { TemplateSetup } from '@/components/workflow/create/TemplateSetup';
import { useIntegrationConnect } from '@/components/workflow/create/useIntegrationConnect';
import { agentNameFor, emptyAnswers, GOOGLE_CALENDAR, missingAnswer } from '@/lib/agentTemplates';
import { detailFromError } from '@/lib/apiError';
import { useAuth } from '@/lib/auth';
import logger from '@/lib/logger';
import { cn } from '@/lib/utils';

/** Where the dialog opens: the ready-made agents, or one of the other two ways. */
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
            id: "1",
            type: "startCall",
            position: { x: 175, y: 60 },
            data: {
                prompt: "# Goal\nYou are a helpful agent who is handing a conversation over voice with a human. This is a voice conversation, so transcripts can be error prone.\n\n## Rules\n- Language: UK English but does not have to be correct english\n- Keep responses short and 2-3 sentences max\n- If you have to repeat something that you said in your previous two turns, then rephrase a bit while keeping the same meaning. Never repeat the exact same words as in your previous 2 responses.\n\n## Speech Handling\n- There could be multiple transcription errors. \n- Accept variations: yes/yeah/yep/aye, no/nah/nope\n- If user says \"sorry?\" or \"pardon me\" or \"can you repeat\"  or \"what?\", they might not have heard you- so just repeat what you just said.\n\n### Flow\nStart by saying \"Hi\". Be polite and courteous. ",
                name: "start call",
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

const WIDTH: Record<View, string> = {
    gallery: 'sm:max-w-[800px]',
    setup: 'sm:max-w-[640px] md:max-w-[880px]',
    ready: 'sm:max-w-[560px]',
    describe: 'sm:max-w-[680px]',
    blank: 'sm:max-w-[560px]',
};

/** The short name the agent builder needs: the description's first sentence. */
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

function Footer({ hint, children }: { hint?: ReactNode; children: ReactNode }) {
    return (
        <div className="flex flex-col gap-3 border-t border-line-soft bg-panel-2 px-6 py-4 sm:flex-row sm:items-center">
            <div className="flex-1 text-[13px] text-ink-3">{hint}</div>
            <div className="flex justify-end gap-2">{children}</div>
        </div>
    );
}

interface CreateAgentDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    initialMode?: CreateMode;
}

/**
 * Creating an agent. It opens on the ready-made agents: pick one, answer its
 * questions about the business (and connect a calendar where it books), and
 * it is ready to talk to. Describing an agent in your own words, or starting
 * from scratch, are the quieter ways in.
 */
export function CreateAgentDialog({ open, onOpenChange, initialMode = 'template' }: CreateAgentDialogProps) {
    const router = useRouter();
    const { user } = useAuth();

    const [view, setView] = useState<View>('gallery');
    const [templates, setTemplates] = useState<WorkflowTemplateResponse[] | null>(null);
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
    const calendar = useIntegrationConnect(GOOGLE_CALENDAR, open && wantsCalendar && !!user);

    useEffect(() => {
        if (!open) return;
        setView(initialMode === 'template' ? 'gallery' : initialMode);
        setCreated(null);
        setError(null);
    }, [open, initialMode]);

    // The ready-made agents load once, the first time the dialog opens.
    useEffect(() => {
        if (!open || templates !== null || !user) return;
        let cancelled = false;
        (async () => {
            const response = await getWorkflowTemplatesApiV1WorkflowTemplatesGet();
            if (cancelled) return;
            if (response.error) {
                logger.error(`Error loading templates: ${JSON.stringify(response.error)}`);
                setTemplates([]);
                return;
            }
            setTemplates(response.data ?? []);
        })();
        return () => {
            cancelled = true;
        };
    }, [open, templates, user]);

    const go = (next: View) => {
        setView(next);
        setError(null);
    };

    const pickTemplate = (picked: WorkflowTemplateResponse) => {
        if (picked.id !== template?.id) {
            setTemplate(picked);
            setAnswers(emptyAnswers(picked.setup_fields ?? []));
            setUseCalendar(true);
        }
        setAnswerErrors({});
        go('setup');
    };

    const handleOpenChange = (next: boolean) => {
        // Keep the dialog up while an agent is being created.
        if (!next && submitting) return;
        // The new agent belongs in the list behind the dialog.
        if (!next && created) router.refresh();
        onOpenChange(next);
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
        setAnswerErrors({});
        const calendarTool =
            wantsCalendar && useCalendar && calendar.status === 'connected'
                ? calendar.connection?.tool_uuids?.[0]
                : undefined;
        setSubmitting(true);
        setError(null);
        try {
            const response = await duplicateWorkflowTemplateApiV1WorkflowTemplatesDuplicatePost({
                body: {
                    template_id: template.id,
                    workflow_name: agentNameFor(template, answers),
                    values: Object.fromEntries(Object.entries(answers).map(([k, v]) => [k, v.trim()])),
                    integration_tools: calendarTool ? { [GOOGLE_CALENDAR]: calendarTool } : {},
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
            // Stay in the submitting state: the dialog unmounts on navigation.
            router.push(`/workflow/${response.data.id}?onboarding=web_call`);
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
        <p className="px-6 pb-4 text-[13px] text-danger" role="alert">
            {error}
        </p>
    );

    let content: ReactNode;
    if (view === 'gallery') {
        content = (
            <>
                <DialogHeader className="px-6 pt-6 pr-14">
                    <DialogTitle className="font-display text-[22px] tracking-[-0.02em]">
                        What should your agent do?
                    </DialogTitle>
                    <DialogDescription className="text-[14px] text-ink-2">
                        Pick a ready-made agent. Next you add your business details, and it&apos;s ready to take calls.
                    </DialogDescription>
                </DialogHeader>
                <div className="min-h-0 flex-1 overflow-y-auto px-6 pt-5 pb-6">
                    <TemplateGallery templates={templates} onPick={pickTemplate} onDescribe={() => go('describe')} />
                </div>
                <Footer
                    hint={
                        <>
                            Need something else?{' '}
                            <button
                                type="button"
                                onClick={() => go('describe')}
                                className="font-semibold text-brand hover:underline focus-visible:outline-2 focus-visible:outline-ring"
                            >
                                Describe it in your own words →
                            </button>
                        </>
                    }
                >
                    <button
                        type="button"
                        onClick={() => go('blank')}
                        className="text-[13px] text-ink-3 hover:text-ink hover:underline focus-visible:outline-2 focus-visible:outline-ring"
                    >
                        Start from scratch
                    </button>
                </Footer>
            </>
        );
    } else if (view === 'setup' && template) {
        content = (
            <>
                <DialogHeader className="flex-row items-center gap-3.5 border-b border-line-soft px-6 py-4 pr-14 text-left">
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
                        <DialogTitle className="font-display text-[19px] tracking-[-0.02em]">
                            Set up your {template.template_name}
                        </DialogTitle>
                        <DialogDescription className="text-[13px] text-ink-3">
                            Step 2 of 3 · Tell it about your business
                        </DialogDescription>
                    </div>
                    <div aria-hidden className="hidden gap-1.5 sm:flex">
                        <span className="h-1 w-7 rounded-full bg-brand" />
                        <span className="h-1 w-7 rounded-full bg-brand" />
                        <span className="h-1 w-7 rounded-full bg-line" />
                    </div>
                </DialogHeader>
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
                    />
                    {errorLine}
                </div>
                <Footer hint="You can change any of this later.">
                    <Button variant="outline" onClick={() => go('gallery')} disabled={submitting}>
                        Back
                    </Button>
                    <Button onClick={createFromTemplate} disabled={submitting}>
                        {submitting && <Loader2 size={15} className="animate-spin" aria-hidden />}
                        {submitting ? 'Creating…' : 'Create agent'}
                    </Button>
                </Footer>
            </>
        );
    } else if (view === 'ready' && created) {
        content = (
            <>
                <div className="min-h-0 overflow-y-auto">
                    <AgentReady
                        agentId={created.id}
                        items={created.items}
                        onTalk={() => router.push(`/workflow/${created.id}?onboarding=web_call`)}
                    />
                </div>
            </>
        );
    } else if (view === 'describe') {
        content =
            submitting ? (
                <div className="flex flex-col items-center px-6 py-16 text-center" role="status">
                    <DialogTitle className="sr-only">Building your agent</DialogTitle>
                    <DialogDescription className="sr-only">This takes about 20 seconds.</DialogDescription>
                    <Loader2 size={28} className="animate-spin text-brand" aria-hidden />
                    <p className="mt-4 text-[15px] font-semibold text-ink">Building your agent</p>
                    <p className="mt-1 max-w-sm text-[13.5px] text-ink-2">
                        Writing what it says and how it handles each step. This takes about 20 seconds.
                    </p>
                </div>
            ) : (
                <>
                    <DialogHeader className="gap-3.5 px-6 pt-5 pr-14">
                        <BackLink onClick={() => go('gallery')}>Ready-made agents</BackLink>
                        <div className="flex flex-col gap-1.5">
                            <DialogTitle className="font-display text-[22px] tracking-[-0.02em]">
                                Tell us what your agent should do
                            </DialogTitle>
                            <DialogDescription className="text-[14px] text-ink-2">
                                Write it like you would explain it to a new employee. We build the agent for you.
                            </DialogDescription>
                        </div>
                    </DialogHeader>
                    <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 pt-5 pb-5">
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
                    </div>
                    {errorLine}
                    <Footer hint="Takes about 20 seconds.">
                        <Button onClick={createFromDescription} disabled={!description.trim()}>
                            Build my agent
                        </Button>
                    </Footer>
                </>
            );
    } else {
        content = (
            <>
                <DialogHeader className="gap-3.5 px-6 pt-5 pr-14">
                    <BackLink onClick={() => go('gallery')}>Ready-made agents</BackLink>
                    <div className="flex flex-col gap-1.5">
                        <DialogTitle className="font-display text-[22px] tracking-[-0.02em]">Start from scratch</DialogTitle>
                        <DialogDescription className="text-[14px] text-ink-2">
                            An empty agent with one step, for building the conversation yourself in the editor.
                        </DialogDescription>
                    </div>
                </DialogHeader>
                <div className="space-y-1.5 px-6 pt-5 pb-6">
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
                <Footer>
                    <Button onClick={createBlank} disabled={submitting}>
                        {submitting ? 'Creating…' : 'Create and open'}
                    </Button>
                </Footer>
            </>
        );
    }

    return (
        <Dialog open={open} onOpenChange={handleOpenChange}>
            <DialogContent
                className={cn(
                    'flex max-h-[calc(100dvh-2rem)] flex-col gap-0 overflow-hidden bg-card p-0 outline-none',
                    WIDTH[view],
                )}
            >
                {content}
            </DialogContent>
        </Dialog>
    );
}
