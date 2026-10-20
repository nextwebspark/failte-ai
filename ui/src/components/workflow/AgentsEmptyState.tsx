'use client';

import { Bot, ClipboardList, PhoneCall, Sparkles } from 'lucide-react';

import { CreateWorkflowButton } from '@/components/workflow/CreateWorkflowButton';
import { UploadWorkflowButton } from '@/components/workflow/UploadWorkflowButton';

const STEPS = [
    {
        icon: Sparkles,
        title: 'Pick a ready-made agent',
        body: 'Start from an agent built for the job, like a receptionist. No technical setup.',
    },
    {
        icon: ClipboardList,
        title: 'Add your business details',
        body: 'Your name, opening hours, address and website. Connect your calendar for bookings.',
    },
    {
        icon: PhoneCall,
        title: 'Test it, then go live',
        body: 'Talk to it in your browser, then put it on a phone number or your website.',
    },
] as const;

/**
 * Voice agents before the first agent exists: one clear action, and the three
 * steps from here to taking calls, so a new user knows what they're starting.
 */
export function AgentsEmptyState() {
    return (
        <section
            aria-labelledby="agents-empty-title"
            className="flex min-h-[calc(100dvh-10rem)] flex-col items-center justify-center px-2 py-10 text-center"
        >
            <span className="mb-5 flex size-14 items-center justify-center rounded-lg bg-brand-dim text-brand">
                <Bot className="size-7" aria-hidden />
            </span>
            <h2 id="agents-empty-title" className="font-display text-[22px] font-semibold tracking-[-0.01em] text-ink">
                Create your first agent
            </h2>
            <p className="mt-2 max-w-md text-[14px] leading-relaxed text-ink-2">
                Your agent answers calls for your business, day and night. Most people are ready
                to test theirs in about five minutes.
            </p>
            <div className="mt-6 flex flex-wrap items-center justify-center gap-2.5">
                {/* The only create button on the page, so it also answers ?create=. */}
                <CreateWorkflowButton openFromUrl size="lg" />
                <UploadWorkflowButton size="lg" variant="ghost" label="Import an agent" />
            </div>

            <ol className="mt-12 grid w-full max-w-3xl gap-3 text-left sm:grid-cols-3">
                {STEPS.map(({ icon: Icon, title, body }, index) => (
                    <li key={title} className="flex flex-col gap-2 rounded-lg border border-line bg-panel p-4">
                        <span className="flex items-center gap-2.5">
                            <span className="flex size-7 items-center justify-center rounded-full bg-panel-2 font-mono text-[12px] font-semibold text-ink-2">
                                {index + 1}
                            </span>
                            <Icon className="size-4 text-ink-3" aria-hidden />
                        </span>
                        <span className="text-[14px] font-semibold text-ink">{title}</span>
                        <span className="text-[13px] leading-relaxed text-ink-2">{body}</span>
                    </li>
                ))}
            </ol>
        </section>
    );
}
