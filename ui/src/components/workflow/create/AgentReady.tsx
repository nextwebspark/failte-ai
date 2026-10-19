'use client';

import { Check, Mic, Minus } from 'lucide-react';
import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { cn } from '@/lib/utils';

export interface ReadyItem {
    text: string;
    note?: string;
    done: boolean;
}

interface AgentReadyProps {
    agentId: number;
    items: ReadyItem[];
    onTalk: () => void;
}

/** After a ready-made agent is created: what it can do, then talk to it. */
export function AgentReady({ agentId, items, onTalk }: AgentReadyProps) {
    return (
        <div className="flex flex-col">
            <div className="flex flex-col items-center gap-3 px-8 pt-9 pb-6 text-center">
                <span className="flex size-14 items-center justify-center rounded-full bg-brand-dim text-brand">
                    <Check size={26} strokeWidth={2.2} aria-hidden />
                </span>
                <DialogTitle className="font-display text-[22px] tracking-[-0.02em] text-ink">
                    Your agent is ready
                </DialogTitle>
                <DialogDescription className="max-w-[420px] text-[14px] leading-[1.5] text-ink-2">
                    Talk to it now, in your browser. Nobody else hears it until you give it a phone number.
                </DialogDescription>
            </div>
            <ul className="mx-8 flex flex-col rounded-lg border border-line py-1">
                {items.map((item, index) => (
                    <li
                        key={item.text}
                        className={cn('flex items-center gap-3 px-4 py-3', index > 0 && 'border-t border-line-soft')}
                    >
                        <span
                            className={cn(
                                'flex size-[22px] shrink-0 items-center justify-center rounded-full',
                                item.done ? 'bg-brand text-brand-ink' : 'border border-line bg-panel-2 text-ink-3',
                            )}
                        >
                            {item.done ? (
                                <Check size={12} strokeWidth={3} aria-label="Done" />
                            ) : (
                                <Minus size={12} strokeWidth={3} aria-label="Not yet" />
                            )}
                        </span>
                        <span className="flex-1 text-[14px] text-ink">{item.text}</span>
                        {item.note && <span className="text-right text-[12.5px] text-ink-3">{item.note}</span>}
                    </li>
                ))}
            </ul>
            <div className="flex flex-col items-center gap-3.5 px-8 pt-7 pb-8">
                <Button size="lg" className="h-12 w-full text-[15px]" onClick={onTalk}>
                    <Mic size={18} aria-hidden />
                    Talk to your agent
                </Button>
                <div className="flex items-center gap-5 text-[13.5px]">
                    <Link href="/telephony-configurations" className="font-semibold text-brand hover:underline">
                        Give it a phone number
                    </Link>
                    <span aria-hidden className="text-line">
                        |
                    </span>
                    <Link href={`/workflow/${agentId}`} className="text-ink-3 hover:text-ink hover:underline">
                        Open the editor
                    </Link>
                </div>
            </div>
        </div>
    );
}
