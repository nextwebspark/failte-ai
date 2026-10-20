'use client';

import { AppWindow, Check, Phone, PhoneCall, X } from 'lucide-react';
import Link from 'next/link';
import type { ReactNode } from 'react';

import type { WorkflowListResponse } from '@/client/types.gen';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface Step {
    title: string;
    body: string;
    done: boolean;
    actions?: ReactNode;
}

interface AgentSetupChecklistProps {
    agent: WorkflowListResponse;
    tested: boolean;
    connected: boolean;
    onHide: () => void;
}

/**
 * Shown on Voice agents until the workspace has tried an agent and connected
 * one: the steps left between "I made an agent" and "it takes real calls",
 * each with the button that does it. The newest agent is the one it opens.
 */
export function AgentSetupChecklist({ agent, tested, connected, onHide }: AgentSetupChecklistProps) {
    const steps: Step[] = [
        {
            title: 'Create an agent',
            body: `${agent.name} is ready.`,
            done: true,
        },
        {
            title: 'Test it in your browser',
            body: 'Have a conversation with your agent and check it answers the way you want.',
            done: tested,
            actions: (
                <Button asChild size="sm">
                    <Link href={`/workflow/${agent.id}`}>
                        <PhoneCall />
                        Talk to your agent
                    </Link>
                </Button>
            ),
        },
        {
            title: 'Let callers reach it',
            body: 'Put it on a phone number, or add it to your website as a call button.',
            done: connected,
            actions: (
                <>
                    <Button asChild size="sm" variant="outline">
                        <Link href={`/workflow/${agent.id}/deployment#phone`}>
                            <Phone />
                            Add a phone number
                        </Link>
                    </Button>
                    <Button asChild size="sm" variant="outline">
                        <Link href={`/workflow/${agent.id}/deployment#website`}>
                            <AppWindow />
                            Add to your website
                        </Link>
                    </Button>
                </>
            ),
        },
    ];
    const doneCount = steps.filter((step) => step.done).length;
    // The first step not done yet is the one to do now; later ones wait their turn.
    const current = steps.findIndex((step) => !step.done);

    return (
        <section aria-labelledby="agent-setup-title" className="rounded-lg border border-line bg-card">
            <header className="flex items-center gap-3 border-b border-line-soft px-4 py-3.5">
                <div className="min-w-0 flex-1">
                    <h2 id="agent-setup-title" className="text-[15px] font-semibold text-ink">
                        Get your agent ready for calls
                    </h2>
                    <p className="mt-0.5 text-[12.5px] text-ink-3">
                        {doneCount} of {steps.length} done
                    </p>
                </div>
                <div
                    role="progressbar"
                    aria-label="Setup progress"
                    aria-valuemin={0}
                    aria-valuemax={steps.length}
                    aria-valuenow={doneCount}
                    className="hidden h-1.5 w-28 overflow-hidden rounded-full bg-panel-2 sm:block"
                >
                    <div className="h-full rounded-full bg-brand" style={{ width: `${(doneCount / steps.length) * 100}%` }} />
                </div>
                <Button variant="ghost" size="icon" className="size-8 text-ink-3" aria-label="Hide setup steps" onClick={onHide}>
                    <X />
                </Button>
            </header>
            <ol className="divide-y divide-line-soft">
                {steps.map((step, index) => (
                    <li
                        key={step.title}
                        aria-current={index === current ? 'step' : undefined}
                        className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center"
                    >
                        <div className="flex min-w-0 flex-1 items-start gap-3">
                            <span
                                className={cn(
                                    'mt-px flex size-6 shrink-0 items-center justify-center rounded-full font-mono text-[11px] font-semibold',
                                    step.done
                                        ? 'bg-ok-dim text-ok'
                                        : index === current
                                          ? 'bg-brand text-brand-ink'
                                          : 'border border-line text-ink-3',
                                )}
                            >
                                {step.done ? <Check className="size-3.5" role="img" aria-label="Done" /> : index + 1}
                            </span>
                            <div className="min-w-0">
                                <p className={cn('text-[14px] font-medium', step.done ? 'text-ink-2' : 'text-ink')}>
                                    {step.title}
                                </p>
                                <p className="mt-0.5 text-[13px] text-ink-3">{step.body}</p>
                            </div>
                        </div>
                        {!step.done && step.actions && (
                            <div className="flex flex-wrap gap-2 pl-9 sm:pl-0">{step.actions}</div>
                        )}
                    </li>
                ))}
            </ol>
        </section>
    );
}
