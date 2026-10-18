'use client';

import { LayoutTemplate, Loader2, Sparkles, SquareDashed } from 'lucide-react';
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
import { detailFromError } from '@/lib/apiError';
import { useAuth } from '@/lib/auth';
import logger from '@/lib/logger';
import { cn } from '@/lib/utils';

export type CreateMode = 'describe' | 'template' | 'blank';
type CallType = 'inbound' | 'outbound';

const USE_CASE_MAX = 200;
const DESCRIPTION_MAX = 4000;

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

const MODES: { value: CreateMode; title: string; body: string; icon: ReactNode }[] = [
    {
        value: 'describe',
        title: 'Describe it',
        body: 'Tell us the job. We draft the whole conversation for you.',
        icon: <Sparkles size={16} aria-hidden />,
    },
    {
        value: 'template',
        title: 'Start from a template',
        body: 'A ready-made agent to adapt.',
        icon: <LayoutTemplate size={16} aria-hidden />,
    },
    {
        value: 'blank',
        title: 'Blank canvas',
        body: 'One start node. Build the flow yourself.',
        icon: <SquareDashed size={16} aria-hidden />,
    },
];

const FOOTER_HINT: Record<CreateMode, string> = {
    describe: 'Drafting takes about 20 seconds. You land in the editor with the test panel open.',
    template: 'You get your own copy of the template, open in the editor.',
    blank: 'You land in the editor with one start node.',
};

interface CreateAgentDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    initialMode?: CreateMode;
}

/**
 * The one way to create an agent: describe it, copy a template, or start blank.
 * Generation runs inside the dialog, and every path lands in the editor with
 * the test panel open.
 */
export function CreateAgentDialog({ open, onOpenChange, initialMode = 'describe' }: CreateAgentDialogProps) {
    const router = useRouter();
    const { user, getAccessToken } = useAuth();

    const [mode, setMode] = useState<CreateMode>(initialMode);
    const [callType, setCallType] = useState<CallType>('inbound');
    const [useCase, setUseCase] = useState('');
    const [description, setDescription] = useState('');
    const [blankName, setBlankName] = useState('');
    const [templates, setTemplates] = useState<WorkflowTemplateResponse[] | null>(null);
    const [templateId, setTemplateId] = useState<number | null>(null);
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (open) {
            setMode(initialMode);
            setError(null);
        }
    }, [open, initialMode]);

    // Templates load the first time someone opens that option.
    useEffect(() => {
        if (!open || mode !== 'template' || templates !== null || !user) return;
        let cancelled = false;
        (async () => {
            const response = await getWorkflowTemplatesApiV1WorkflowTemplatesGet();
            if (cancelled) return;
            if (response.error) {
                logger.error(`Error loading templates: ${JSON.stringify(response.error)}`);
                setTemplates([]);
                setError(detailFromError(response.error, 'Couldn’t load templates.'));
                return;
            }
            setTemplates(response.data ?? []);
        })();
        return () => {
            cancelled = true;
        };
    }, [open, mode, templates, user]);

    const canSubmit =
        !submitting &&
        (mode === 'describe'
            ? useCase.trim() !== '' && description.trim() !== ''
            : mode === 'template'
              ? templateId !== null
              : true);

    const handleOpenChange = (next: boolean) => {
        // Keep the dialog up while an agent is being drafted.
        if (!next && submitting) return;
        onOpenChange(next);
    };

    const create = async () => {
        if (!canSubmit || !user) return;
        setSubmitting(true);
        setError(null);
        try {
            const accessToken = await getAccessToken();
            const headers = { Authorization: `Bearer ${accessToken}` };
            let response;
            if (mode === 'describe') {
                response = await createWorkflowFromTemplateApiV1WorkflowCreateTemplatePost({
                    body: {
                        call_type: callType,
                        use_case: useCase.trim(),
                        activity_description: description.trim(),
                    },
                    headers,
                });
            } else if (mode === 'template') {
                const template = templates?.find((t) => t.id === templateId);
                response = await duplicateWorkflowTemplateApiV1WorkflowTemplatesDuplicatePost({
                    body: { template_id: templateId!, workflow_name: template?.template_name ?? 'Untitled agent' },
                    headers,
                });
            } else {
                response = await createWorkflowApiV1WorkflowCreateDefinitionPost({
                    body: {
                        name: blankName.trim() || 'Untitled agent',
                        workflow_definition: BLANK_WORKFLOW_DEFINITION as unknown as { [key: string]: unknown },
                    },
                    headers,
                });
            }

            if (response.error || !response.data?.id) {
                logger.error(`Error creating agent (${mode}): ${JSON.stringify(response.error)}`);
                setError(detailFromError(response.error, 'Couldn’t create the agent. Please try again.'));
                setSubmitting(false);
                return;
            }
            // Stay in the submitting state: the dialog unmounts on navigation.
            router.push(`/workflow/${response.data.id}?onboarding=web_call`);
        } catch (err) {
            logger.error(`Error creating agent (${mode}): ${err}`);
            setError('Couldn’t create the agent. Please try again.');
            setSubmitting(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={handleOpenChange}>
            <DialogContent className="gap-0 overflow-hidden bg-card p-0 sm:max-w-[640px]">
                <DialogHeader className="px-6 pt-6">
                    <DialogTitle className="text-[18px]">Create agent</DialogTitle>
                    <DialogDescription>
                        Pick how you want to start. You can change everything later in the editor.
                    </DialogDescription>
                </DialogHeader>

                {submitting && mode === 'describe' ? (
                    <div className="flex flex-col items-center px-6 py-14 text-center" role="status">
                        <Loader2 size={28} className="animate-spin text-brand" aria-hidden />
                        <p className="mt-4 text-[15px] font-semibold text-ink">Drafting your agent</p>
                        <p className="mt-1 max-w-sm text-[13.5px] text-ink-2">
                            Writing the conversation, the prompts and the first test data. This takes about 20 seconds.
                        </p>
                    </div>
                ) : (
                    <>
                        <div
                            role="radiogroup"
                            aria-label="How to start"
                            className="grid grid-cols-1 gap-2.5 px-6 pt-5 sm:grid-cols-3"
                        >
                            {MODES.map((option) => {
                                const selected = mode === option.value;
                                return (
                                    <button
                                        key={option.value}
                                        type="button"
                                        role="radio"
                                        aria-checked={selected}
                                        onClick={() => {
                                            setMode(option.value);
                                            setError(null);
                                        }}
                                        className={cn(
                                            'flex flex-col gap-1.5 rounded-lg border p-3.5 text-left transition-colors focus-visible:outline-2 focus-visible:outline-ring',
                                            selected
                                                ? 'border-brand bg-brand-dim'
                                                : 'border-line bg-card hover:bg-panel-2',
                                        )}
                                    >
                                        <span
                                            className={cn(
                                                'flex items-center gap-2 text-[13.5px] font-semibold',
                                                selected ? 'text-brand' : 'text-ink',
                                            )}
                                        >
                                            {option.icon}
                                            {option.title}
                                        </span>
                                        <span className="text-[12.5px] leading-snug text-ink-2">{option.body}</span>
                                    </button>
                                );
                            })}
                        </div>

                        <div className="max-h-[52vh] space-y-5 overflow-y-auto px-6 py-5">
                            {mode === 'describe' && (
                                <>
                                    <div className="space-y-2">
                                        <span id="call-direction-label" className="text-sm font-medium text-ink">
                                            Call direction
                                        </span>
                                        <div
                                            role="radiogroup"
                                            aria-labelledby="call-direction-label"
                                            className="flex h-9 w-fit rounded-md border border-line bg-panel-2 p-0.5"
                                        >
                                            {(
                                                [
                                                    ['inbound', 'Inbound'],
                                                    ['outbound', 'Outbound'],
                                                ] as const
                                            ).map(([value, label]) => (
                                                <button
                                                    key={value}
                                                    type="button"
                                                    role="radio"
                                                    aria-checked={callType === value}
                                                    onClick={() => setCallType(value)}
                                                    className={cn(
                                                        'rounded-sm px-3 text-[13px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-ring',
                                                        callType === value
                                                            ? 'bg-card text-ink shadow-xs'
                                                            : 'text-ink-3 hover:text-ink',
                                                    )}
                                                >
                                                    {label}
                                                </button>
                                            ))}
                                        </div>
                                        <p className="text-[12px] text-ink-3">
                                            {callType === 'inbound'
                                                ? 'People call the agent on your number or website.'
                                                : 'The agent calls people, one by one or from a campaign.'}
                                        </p>
                                    </div>

                                    <div className="space-y-2">
                                        <Label htmlFor="agent-use-case">What kind of agent is it?</Label>
                                        <Input
                                            id="agent-use-case"
                                            placeholder="Dental reception, lead qualification, appointment reminders"
                                            value={useCase}
                                            maxLength={USE_CASE_MAX}
                                            onChange={(event) => setUseCase(event.target.value)}
                                        />
                                    </div>

                                    <div className="space-y-2">
                                        <Label htmlFor="agent-description">What should it do?</Label>
                                        <Textarea
                                            id="agent-description"
                                            placeholder="Answer calls for a dental practice. Book, move and cancel appointments. Take a message for anything else. Be warm and brief."
                                            value={description}
                                            maxLength={DESCRIPTION_MAX}
                                            onChange={(event) => setDescription(event.target.value)}
                                            className="min-h-[120px]"
                                        />
                                        <div className="flex justify-between gap-4 text-[12px] text-ink-3">
                                            <span>Mention the tools it should use, when to hand over, and the tone.</span>
                                            <span className="shrink-0 font-mono">
                                                {description.length} / {DESCRIPTION_MAX}
                                            </span>
                                        </div>
                                    </div>
                                </>
                            )}

                            {mode === 'template' &&
                                (templates === null ? (
                                    <div className="flex items-center gap-2 py-6 text-[13.5px] text-ink-2">
                                        <Loader2 size={16} className="animate-spin" aria-hidden />
                                        Loading templates
                                    </div>
                                ) : templates.length === 0 ? (
                                    <div className="rounded-lg border border-dashed border-line bg-panel-2 p-6 text-center text-[13.5px] text-ink-2">
                                        No templates yet. Describe the agent instead and we&apos;ll draft it for you.
                                    </div>
                                ) : (
                                    <div role="radiogroup" aria-label="Templates" className="grid gap-2 sm:grid-cols-2">
                                        {templates.map((template) => {
                                            const selected = templateId === template.id;
                                            return (
                                                <button
                                                    key={template.id}
                                                    type="button"
                                                    role="radio"
                                                    aria-checked={selected}
                                                    onClick={() => setTemplateId(template.id)}
                                                    className={cn(
                                                        'rounded-lg border p-3.5 text-left transition-colors focus-visible:outline-2 focus-visible:outline-ring',
                                                        selected
                                                            ? 'border-brand bg-brand-dim'
                                                            : 'border-line bg-card hover:bg-panel-2',
                                                    )}
                                                >
                                                    <span className="block text-[13.5px] font-semibold text-ink">
                                                        {template.template_name}
                                                    </span>
                                                    <span className="mt-1 line-clamp-2 block text-[12.5px] text-ink-2">
                                                        {template.template_description}
                                                    </span>
                                                </button>
                                            );
                                        })}
                                    </div>
                                ))}

                            {mode === 'blank' && (
                                <div className="space-y-2">
                                    <Label htmlFor="agent-name">Name</Label>
                                    <Input
                                        id="agent-name"
                                        placeholder="Untitled agent"
                                        value={blankName}
                                        maxLength={USE_CASE_MAX}
                                        onChange={(event) => setBlankName(event.target.value)}
                                        onKeyDown={(event) => {
                                            if (event.key === 'Enter') create();
                                        }}
                                    />
                                </div>
                            )}

                            {error && (
                                <p className="text-[13px] text-danger" role="alert">
                                    {error}
                                </p>
                            )}
                        </div>
                    </>
                )}

                <div className="flex flex-col gap-3 border-t border-line-soft bg-panel-2 px-6 py-4 sm:flex-row sm:items-center">
                    <p className="flex-1 text-[12.5px] text-ink-3">{FOOTER_HINT[mode]}</p>
                    <div className="flex justify-end gap-2">
                        <Button variant="outline" onClick={() => handleOpenChange(false)} disabled={submitting}>
                            Cancel
                        </Button>
                        <Button onClick={create} disabled={!canSubmit}>
                            {submitting ? 'Creating…' : 'Create and open'}
                        </Button>
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    );
}
