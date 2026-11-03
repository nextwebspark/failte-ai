'use client';

import {
    Activity,
    BellRing,
    Bot,
    CalendarCheck,
    Check,
    type LucideIcon,
    MessageSquare,
    Moon,
    Phone,
    PhoneIncoming,
    PhoneOutgoing,
    Play,
    Scissors,
    Square,
    Star,
    Utensils,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';

import type { WorkflowTemplateResponse } from '@/client/types.gen';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import {
    filterTemplates,
    GOOGLE_CALENDAR,
    INTEGRATION_LABEL,
    sortTemplates,
    TEMPLATE_CATEGORY_LABEL,
    TEMPLATE_FILTER_LABEL,
    templateCategories,
    type TemplateCategory,
    type TemplateDirectionFilter,
    templateFilters,
    templateFlowSteps,
    templateGreeting,
    templateHighlights,
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
    scissors: Scissors,
};

export function TemplateIcon({ name, size = 20 }: { name?: string | null; size?: number }) {
    const Icon = (name && ICONS[name]) || Bot;
    return <Icon size={size} strokeWidth={1.8} aria-hidden />;
}

interface TemplateGalleryProps {
    templates: WorkflowTemplateResponse[] | null;
    /** The list couldn't load: say so, rather than claiming there are none. */
    loadFailed?: boolean;
    onRetry?: () => void;
    selectedId?: number | null;
    onSelect: (template: WorkflowTemplateResponse) => void;
    onContinue: () => void;
    onDescribe: () => void;
}

/** Ready-made agents with a full-height preview rail on the right. */
export function TemplateGallery({
    templates,
    loadFailed = false,
    onRetry,
    selectedId = null,
    onSelect,
    onContinue,
    onDescribe,
}: TemplateGalleryProps) {
    const [direction, setDirection] = useState<TemplateDirectionFilter>('all');
    const [category, setCategory] = useState<TemplateCategory>('all');
    const sorted = useMemo(() => sortTemplates(templates ?? []), [templates]);
    const directions = useMemo(() => templateFilters(sorted), [sorted]);
    const categories = useMemo(() => templateCategories(sorted), [sorted]);
    const shown = filterTemplates(sorted, direction, category);
    // Only preview a card the user can see, so "Use this template" never
    // continues with one the filters hid.
    const selected = shown.find((t) => t.id === selectedId) ?? null;

    const applyFilters = (nextDirection: TemplateDirectionFilter, nextCategory: TemplateCategory) => {
        setDirection(nextDirection);
        setCategory(nextCategory);
        const visible = filterTemplates(sorted, nextDirection, nextCategory);
        if (visible.length > 0 && !visible.some((t) => t.id === selectedId)) onSelect(visible[0]);
    };

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

    if (loadFailed) {
        return (
            <div
                role="alert"
                className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-line bg-panel-2 px-6 py-10 text-center"
            >
                <p className="max-w-sm text-[14px] text-ink-2">
                    Couldn’t load the ready-made agents. Check your connection and try again, or describe
                    your agent in your own words.
                </p>
                <div className="flex flex-wrap items-center justify-center gap-3">
                    {onRetry && (
                        <Button variant="outline" onClick={onRetry}>
                            Try again
                        </Button>
                    )}
                    <button
                        type="button"
                        onClick={onDescribe}
                        className="text-[14px] font-semibold text-brand hover:underline focus-visible:outline-2 focus-visible:outline-ring"
                    >
                        Describe it in your own words →
                    </button>
                </div>
            </div>
        );
    }

    if (templates === null) {
        return (
            <div className="grid min-h-[28rem] gap-0 lg:grid-cols-[minmax(0,1fr)_400px]" aria-busy="true">
                <div className="grid gap-3 p-1 sm:grid-cols-2">
                    {[0, 1, 2, 3].map((i) => (
                        <Skeleton key={i} className="h-[168px] rounded-lg" />
                    ))}
                </div>
                <Skeleton className="hidden h-full min-h-[28rem] rounded-lg lg:block" />
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

    const greeting = selected ? templateGreeting(selected) : null;
    const flowSteps = selected ? templateFlowSteps(selected) : [];
    const highlights = selected ? templateHighlights(selected) : [];

    return (
        <div className="grid min-h-[min(70vh,40rem)] overflow-hidden rounded-lg border border-line lg:grid-cols-[minmax(0,1fr)_minmax(360px,420px)]">
            <div className="min-w-0 space-y-4 bg-card p-4 sm:p-5">
                {(directions.length > 0 || categories.length > 0) && (
                    <div className="flex flex-col gap-3">
                        {categories.length > 0 && (
                            <div role="group" aria-label="Industry" className="flex flex-wrap gap-2">
                                {categories.map((value) => (
                                    <button
                                        key={value}
                                        type="button"
                                        aria-pressed={category === value}
                                        onClick={() => applyFilters(direction, value)}
                                        className={cn(
                                            'h-8 rounded-full border px-3.5 text-[13px] transition-colors focus-visible:outline-2 focus-visible:outline-ring',
                                            category === value
                                                ? 'border-brand bg-brand-dim font-semibold text-brand'
                                                : 'border-line bg-card font-medium text-ink-2 hover:text-ink',
                                        )}
                                    >
                                        {value === 'all'
                                            ? 'All industries'
                                            : (TEMPLATE_CATEGORY_LABEL[
                                                  value as Exclude<TemplateCategory, 'all'>
                                              ] ?? value)}
                                    </button>
                                ))}
                            </div>
                        )}
                        {directions.length > 0 && (
                            <div role="group" aria-label="Show" className="flex flex-wrap gap-2">
                                {directions.map((value) => (
                                    <button
                                        key={value}
                                        type="button"
                                        aria-pressed={direction === value}
                                        onClick={() => applyFilters(value, category)}
                                        className={cn(
                                            'h-8 rounded-full border px-3.5 text-[13px] transition-colors focus-visible:outline-2 focus-visible:outline-ring',
                                            direction === value
                                                ? 'border-brand bg-brand-dim font-semibold text-brand'
                                                : 'border-line bg-card font-medium text-ink-2 hover:text-ink',
                                        )}
                                    >
                                        {TEMPLATE_FILTER_LABEL[value]}
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>
                )}
                <ul className="grid gap-3 sm:grid-cols-2">
                    {shown.map((template) => {
                        const isSelected = template.id === selectedId;
                        return (
                            <li key={template.id} className="relative">
                                <button
                                    type="button"
                                    aria-pressed={isSelected}
                                    onClick={() => onSelect(template)}
                                    onDoubleClick={() => {
                                        onSelect(template);
                                        onContinue();
                                    }}
                                    className={cn(
                                        'flex h-full min-h-[148px] w-full flex-col gap-2.5 rounded-lg border p-4 text-left transition-colors focus-visible:outline-2 focus-visible:outline-ring',
                                        isSelected
                                            ? 'border-brand bg-brand-dim shadow-[inset_0_0_0_1px_var(--brand)]'
                                            : 'border-line bg-card hover:border-brand hover:bg-brand-dim/40',
                                    )}
                                >
                                    <span className="flex items-center justify-between gap-2">
                                        <span className="flex size-9 items-center justify-center rounded-[10px] bg-brand-dim text-brand">
                                            <TemplateIcon name={template.icon} size={18} />
                                        </span>
                                        {template.featured && (
                                            <span className="text-[11px] font-semibold uppercase tracking-[0.04em] text-brand">
                                                Most popular
                                            </span>
                                        )}
                                    </span>
                                    <span className="flex flex-col gap-1">
                                        <span className="text-[14.5px] font-semibold text-ink">
                                            {template.template_name}
                                        </span>
                                        <span className="line-clamp-2 text-[12.5px] leading-[1.45] text-ink-2">
                                            {template.template_description}
                                        </span>
                                    </span>
                                    <span
                                        className={cn(
                                            'mt-auto text-[11.5px] text-ink-3',
                                            template.sample_audio_url && 'pr-20',
                                        )}
                                    >
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
                        );
                    })}
                </ul>
                {shown.length === 0 && (
                    <p className="rounded-lg border border-dashed border-line bg-panel-2 px-4 py-8 text-center text-[13.5px] text-ink-2">
                        No agents match these filters. Try All industries or another call type.
                    </p>
                )}
            </div>

            <aside
                aria-label="Template preview"
                className="flex min-h-[24rem] flex-col border-t border-line bg-panel-2 lg:min-h-0 lg:border-t-0 lg:border-l"
            >
                {selected ? (
                    <>
                        <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-5 sm:p-6">
                            <div className="flex items-start gap-3.5">
                                <span className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-brand-dim text-brand">
                                    <TemplateIcon name={selected.icon} size={24} />
                                </span>
                                <div className="min-w-0 flex flex-col gap-1.5">
                                    <h3 className="font-display text-[20px] leading-tight tracking-[-0.02em] text-ink">
                                        {selected.template_name}
                                    </h3>
                                    <p className="text-[13.5px] leading-[1.5] text-ink-2">
                                        {selected.template_description}
                                    </p>
                                </div>
                            </div>

                            <dl className="grid grid-cols-2 gap-3 rounded-lg border border-line bg-card p-3.5 text-[13px]">
                                <div className="flex flex-col gap-0.5">
                                    <dt className="text-[11px] font-medium uppercase tracking-[0.06em] text-ink-3">
                                        Type
                                    </dt>
                                    <dd className="font-semibold text-ink">
                                        {selected.call_type === 'outbound' ? 'Makes calls' : 'Answers calls'}
                                    </dd>
                                </div>
                                <div className="flex flex-col gap-0.5">
                                    <dt className="text-[11px] font-medium uppercase tracking-[0.06em] text-ink-3">
                                        Industry
                                    </dt>
                                    <dd className="font-semibold text-ink">
                                        {selected.category && selected.category in TEMPLATE_CATEGORY_LABEL
                                            ? TEMPLATE_CATEGORY_LABEL[
                                                  selected.category as Exclude<TemplateCategory, 'all'>
                                              ]
                                            : 'General'}
                                    </dd>
                                </div>
                                <div className="col-span-2 flex flex-col gap-0.5 border-t border-line-soft pt-3">
                                    <dt className="text-[11px] font-medium uppercase tracking-[0.06em] text-ink-3">
                                        Setup
                                    </dt>
                                    <dd className="font-semibold text-ink">{templateMeta(selected)}</dd>
                                </div>
                            </dl>

                            {highlights.length > 0 && (
                                <div className="flex flex-col gap-2.5">
                                    <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-3">
                                        What it does
                                    </span>
                                    <ul className="flex flex-col gap-2">
                                        {highlights.map((item) => (
                                            <li key={item} className="flex items-start gap-2 text-[13.5px] text-ink">
                                                <Check
                                                    size={15}
                                                    className="mt-0.5 shrink-0 text-brand"
                                                    strokeWidth={2.4}
                                                    aria-hidden
                                                />
                                                <span className="leading-[1.45]">{item}</span>
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            )}

                            {flowSteps.length > 0 && (
                                <div className="flex flex-col gap-2.5">
                                    <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-3">
                                        Call flow
                                    </span>
                                    <ol className="flex flex-col gap-2">
                                        {flowSteps.map((step, index) => (
                                            <li
                                                key={`${index}-${step}`}
                                                className="flex items-center gap-2.5 text-[13.5px] text-ink"
                                            >
                                                <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-card font-mono text-[11px] font-semibold text-ink-2 ring-1 ring-line">
                                                    {index + 1}
                                                </span>
                                                <span className="leading-[1.4] first-letter:uppercase">{step}</span>
                                            </li>
                                        ))}
                                    </ol>
                                </div>
                            )}

                            {(selected.integrations?.length ?? 0) > 0 && (
                                <div className="flex flex-col gap-2">
                                    <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-3">
                                        Optional connects
                                    </span>
                                    <div className="flex flex-wrap gap-1.5">
                                        {selected.integrations!.map((provider) => (
                                            <span
                                                key={provider}
                                                className="rounded-full border border-line bg-card px-2.5 py-1 text-[12px] font-medium text-ink-2"
                                            >
                                                {INTEGRATION_LABEL[provider] ?? provider}
                                                {provider === GOOGLE_CALENDAR ? ' (optional)' : ''}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {greeting && (
                                <div className="flex flex-col gap-2">
                                    <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-3">
                                        How it will sound
                                    </span>
                                    <p className="rounded-[14px_14px_14px_4px] border border-line bg-card px-4 py-3.5 text-[14px] leading-[1.5] text-ink shadow-sm">
                                        {greeting.replace(/\{\{\s*([a-z][a-z0-9_]*)[^}]*\}\}/g, '[$1]')}
                                    </p>
                                    <span className="text-[12px] text-ink-3">
                                        The opening line on{' '}
                                        {selected.call_type === 'outbound' ? 'outbound' : 'inbound'} calls.
                                    </span>
                                </div>
                            )}
                        </div>
                        <div className="sticky bottom-0 border-t border-line bg-panel-2 p-4 sm:p-5">
                            <Button size="lg" className="h-11 w-full text-[14.5px]" onClick={onContinue}>
                                Use this template
                            </Button>
                            <p className="mt-2 text-center text-[12px] text-ink-3">
                                Next: add your business details
                                {(selected.integrations?.length ?? 0) > 0 ? ' and optional calendar' : ''}.
                            </p>
                        </div>
                    </>
                ) : (
                    <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 py-16 text-center">
                        <span className="mb-2 flex size-12 items-center justify-center rounded-xl bg-card text-ink-3 ring-1 ring-line">
                            <Phone size={22} strokeWidth={1.8} aria-hidden />
                        </span>
                        <p className="text-[15px] font-semibold text-ink">Pick a ready-made agent</p>
                        <p className="max-w-[240px] text-[13.5px] leading-[1.45] text-ink-2">
                            Select a card to preview what it says, how the call flows, and what you&apos;ll set up.
                        </p>
                    </div>
                )}
            </aside>
        </div>
    );
}
