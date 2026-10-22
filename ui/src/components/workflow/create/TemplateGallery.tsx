'use client';

import {
    Activity,
    BellRing,
    Bot,
    CalendarCheck,
    type LucideIcon,
    MessageSquare,
    Moon,
    Phone,
    PhoneIncoming,
    PhoneOutgoing,
    Play,
    Square,
    Star,
    Utensils,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';

import type { WorkflowTemplateResponse } from '@/client/types.gen';
import { Skeleton } from '@/components/ui/skeleton';
import {
    filterTemplates,
    sortTemplates,
    TEMPLATE_FILTER_LABEL,
    type TemplateFilter,
    templateFilters,
    templateMeta,
} from '@/lib/agentTemplates';
import { cn } from '@/lib/utils';

const ICONS: Record<string, LucideIcon> = {
    phone: Phone,
    calendar: CalendarCheck,
    moon: Moon,
    'phone-incoming': PhoneIncoming,
    'phone-outgoing': PhoneOutgoing,
    bell: BellRing,
    activity: Activity,
    message: MessageSquare,
    utensils: Utensils,
    star: Star,
};

export function TemplateIcon({ name, size = 20 }: { name?: string | null; size?: number }) {
    const Icon = (name && ICONS[name]) || Bot;
    return <Icon size={size} strokeWidth={1.8} aria-hidden />;
}

interface TemplateGalleryProps {
    templates: WorkflowTemplateResponse[] | null;
    onPick: (template: WorkflowTemplateResponse) => void;
    onDescribe: () => void;
}

/** The ready-made agents, featured first, as cards that open their setup. */
export function TemplateGallery({ templates, onPick, onDescribe }: TemplateGalleryProps) {
    const [filter, setFilter] = useState<TemplateFilter>('all');
    const sorted = useMemo(() => sortTemplates(templates ?? []), [templates]);
    const filters = useMemo(() => templateFilters(sorted), [sorted]);
    const shown = filterTemplates(sorted, filter);

    const audioRef = useRef<HTMLAudioElement | null>(null);
    const [playing, setPlaying] = useState<number | null>(null);
    useEffect(() => () => audioRef.current?.pause(), []);
    const toggleSample = (template: WorkflowTemplateResponse) => {
        audioRef.current?.pause();
        if (playing === template.id || !template.sample_audio_url) {
            setPlaying(null);
            return;
        }
        const audio = new Audio(template.sample_audio_url);
        audio.onended = () => setPlaying(null);
        audioRef.current = audio;
        setPlaying(template.id);
        void audio.play().catch(() => setPlaying(null));
    };

    if (templates === null) {
        return (
            <div className="grid gap-3 sm:grid-cols-3" aria-busy="true" aria-label="Loading ready-made agents">
                {[0, 1, 2].map((i) => (
                    <Skeleton key={i} className="h-[196px] rounded-lg" />
                ))}
            </div>
        );
    }

    if (templates.length === 0) {
        return (
            <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-line bg-panel-2 px-6 py-10 text-center">
                <p className="max-w-sm text-[14px] text-ink-2">
                    Ready-made agents are on their way. For now, tell us what your agent should do and
                    we&apos;ll build it for you.
                </p>
                <button
                    type="button"
                    onClick={onDescribe}
                    className="text-[14px] font-semibold text-brand hover:underline focus-visible:outline-2 focus-visible:outline-ring"
                >
                    Describe it in your own words →
                </button>
            </div>
        );
    }

    return (
        <div className="space-y-4">
            {filters.length > 0 && (
                <div role="group" aria-label="Show" className="flex flex-wrap gap-2">
                    {filters.map((value) => (
                        <button
                            key={value}
                            type="button"
                            aria-pressed={filter === value}
                            onClick={() => setFilter(value)}
                            className={cn(
                                'h-8 rounded-full border px-3.5 text-[13px] transition-colors focus-visible:outline-2 focus-visible:outline-ring',
                                filter === value
                                    ? 'border-brand bg-brand-dim font-semibold text-brand'
                                    : 'border-line bg-card font-medium text-ink-2 hover:text-ink',
                            )}
                        >
                            {TEMPLATE_FILTER_LABEL[value]}
                        </button>
                    ))}
                </div>
            )}
            <ul className={cn('grid gap-3', shown.length >= 3 ? 'sm:grid-cols-3' : 'sm:grid-cols-2')}>
                {shown.map((template) => (
                    <li key={template.id} className="relative">
                        <button
                            type="button"
                            onClick={() => onPick(template)}
                            className="flex h-full min-h-[196px] w-full flex-col gap-3 rounded-lg border border-line bg-card p-4 text-left transition-colors hover:border-brand hover:bg-brand-dim focus-visible:outline-2 focus-visible:outline-ring"
                        >
                            <span className="flex items-center justify-between gap-2">
                                <span className="flex size-10 items-center justify-center rounded-[10px] bg-brand-dim text-brand">
                                    <TemplateIcon name={template.icon} />
                                </span>
                                {template.featured && (
                                    <span className="text-[11px] font-semibold uppercase tracking-[0.04em] text-brand">
                                        Most popular
                                    </span>
                                )}
                            </span>
                            <span className="flex flex-col gap-1">
                                <span className="text-[15px] font-semibold text-ink">{template.template_name}</span>
                                <span className="line-clamp-3 text-[13px] leading-[1.45] text-ink-2">
                                    {template.template_description}
                                </span>
                            </span>
                            {/* Leaves room for the sample button, which sits over the card. */}
                            <span className={cn('mt-auto text-[12px] text-ink-3', template.sample_audio_url && 'pr-20')}>
                                {templateMeta(template)}
                            </span>
                        </button>
                        {template.sample_audio_url && (
                            <button
                                type="button"
                                onClick={() => toggleSample(template)}
                                aria-label={`${playing === template.id ? 'Stop' : 'Play'} a sample call of ${template.template_name}`}
                                className="absolute right-3 bottom-3 inline-flex h-7 items-center gap-1.5 rounded-md px-1.5 text-[12px] font-semibold text-brand hover:bg-brand-dim focus-visible:outline-2 focus-visible:outline-ring"
                            >
                                {playing === template.id ? (
                                    <Square size={11} fill="currentColor" aria-hidden />
                                ) : (
                                    <Play size={11} fill="currentColor" aria-hidden />
                                )}
                                {playing === template.id ? 'Stop' : 'Hear it'}
                            </button>
                        )}
                    </li>
                ))}
            </ul>
        </div>
    );
}
