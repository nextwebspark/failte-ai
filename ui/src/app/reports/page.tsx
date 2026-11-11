'use client';

import { format } from 'date-fns';
import { CalendarDays, Download, FileWarning, Mail, PhoneCall, RefreshCw, Settings2 } from 'lucide-react';
import Link from 'next/link';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { DateRange } from 'react-day-picker';
import { toast } from 'sonner';

import {
    emailMeThisReportApiV1OrganizationsReportsEmailMePost,
    getReportCallsApiV1OrganizationsReportsCallsGet,
    getReportOverviewApiV1OrganizationsReportsOverviewGet,
} from '@/client/sdk.gen';
import type { ReportLayoutView, ReportOverviewResponse, ReportRange } from '@/client/types.gen';
import { AddAnswerDialog } from '@/components/dashboard/AddAnswerDialog';
import { RESULT_WORDS } from '@/components/dashboard/dashboardView';
import { EmptyState } from '@/components/page-states/EmptyState';
import { Button } from '@/components/ui/button';
import { Calendar as CalendarPicker } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { useOrgConfig } from '@/context/OrgConfigContext';
import { useAuth } from '@/lib/auth';
import { cn } from '@/lib/utils';

import { CustomiseDrawer } from './components/CustomiseDrawer';
import { ReportCard } from './components/ReportCard';
import { CSV_HEADERS, csvCell } from './csv';
import { comparedWith, RANGE_OPTIONS, reportTitle, shownCards } from './reportView';

const LOAD_FAILED = "We couldn't load this report";

type Query = {
    range: ReportRange;
    start_date?: string;
    end_date?: string;
    workflow_id?: number;
};

function ReportSkeleton() {
    return (
        <div className="flex flex-col gap-4" aria-busy="true" aria-label="Loading the report">
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
                {Array.from({ length: 5 }, (_, i) => (
                    <Skeleton key={i} className="h-[150px] rounded-[14px]" />
                ))}
            </div>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
                <Skeleton className="h-[380px] rounded-[14px] lg:col-span-2" />
                <Skeleton className="h-[380px] rounded-[14px]" />
            </div>
        </div>
    );
}

export default function ReportsPage() {
    const auth = useAuth();
    const { can } = useOrgConfig();
    const [range, setRange] = useState<ReportRange>('7d');
    const [custom, setCustom] = useState<DateRange | undefined>();
    const [pickerOpen, setPickerOpen] = useState(false);
    const [agent, setAgent] = useState('all');
    const [report, setReport] = useState<ReportOverviewResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [attempt, setAttempt] = useState(0);
    const [customising, setCustomising] = useState(false);
    const [answering, setAnswering] = useState<{ run_id: number; workflow_id: number; questions: string[] } | null>(null);
    const [downloading, setDownloading] = useState(false);
    const downloadingRef = useRef(false);
    const [emailing, setEmailing] = useState(false);
    const [now] = useState(() => new Date());

    const query = useMemo<Query | null>(() => {
        const workflow_id = agent === 'all' ? undefined : Number(agent);
        if (range !== 'custom') return { range, workflow_id };
        if (!custom?.from) return null;
        return {
            range,
            start_date: format(custom.from, 'yyyy-MM-dd'),
            end_date: format(custom.to ?? custom.from, 'yyyy-MM-dd'),
            workflow_id,
        };
    }, [range, custom, agent]);

    useEffect(() => {
        if (!auth.isAuthenticated || !query) return;
        let stale = false;
        setLoading(true);
        setError(null);
        getReportOverviewApiV1OrganizationsReportsOverviewGet({ query })
            .then((response) => {
                if (stale) return;
                if (response.data) setReport(response.data);
                else {
                    setReport(null);
                    setError(LOAD_FAILED);
                }
            })
            .catch(() => {
                if (!stale) {
                    setReport(null);
                    setError(LOAD_FAILED);
                }
            })
            .finally(() => {
                if (!stale) setLoading(false);
            });
        return () => {
            stale = true;
        };
    }, [auth.isAuthenticated, query, attempt]);

    const onLayoutSaved = useCallback(
        (layout: ReportLayoutView) => {
            setReport((current) => (current ? { ...current, layout } : current));
            // A new average or a card switched on may need numbers counted afresh.
            setAttempt((n) => n + 1);
        },
        [],
    );

    // The days and agent on screen, sent now to your own sign-in address.
    const emailMe = async () => {
        if (!auth.isAuthenticated || !query || emailing || !report) return;
        setEmailing(true);
        try {
            const response = await emailMeThisReportApiV1OrganizationsReportsEmailMePost({ query });
            if (response.error || !response.data) {
                const detail = (response.error as { detail?: unknown } | undefined)?.detail;
                toast.error(typeof detail === 'string' ? detail : "Couldn't send the report. Please try again.");
                return;
            }
            toast.success(`Sent to ${response.data.sent_to}. It can take a minute to arrive.`);
        } catch {
            toast.error("Couldn't send the report. Please try again.");
        } finally {
            setEmailing(false);
        }
    };

    const download = async () => {
        if (!auth.isAuthenticated || !query || downloadingRef.current || !report) return;
        downloadingRef.current = true;
        setDownloading(true);
        try {
            const response = await getReportCallsApiV1OrganizationsReportsCallsGet({ query });
            if (response.error || !response.data) {
                toast.error("Couldn't download the calls. Please try again.");
                return;
            }
            const calls = response.data.calls;
            if (!calls.length) {
                toast.info('There are no calls to download for this period.');
                return;
            }
            const zone = response.data.timezone;
            const when = new Intl.DateTimeFormat('en-IE', {
                timeZone: zone,
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                hourCycle: 'h23',
            });
            const rows = calls.map((call) => [
                when.format(new Date(call.created_at)),
                call.workflow_name,
                call.caller_number ?? '',
                call.caller_name ?? '',
                RESULT_WORDS[call.result]?.label ?? call.result,
                call.reason_label ?? '',
                call.duration_seconds != null ? String(Math.round(call.duration_seconds)) : '',
                `${window.location.origin}/workflow/${call.workflow_id}/run/${call.run_id}`,
            ]);
            const csv = [CSV_HEADERS.map(csvCell).join(','), ...rows.map((row) => row.map(csvCell).join(','))].join('\n');
            const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            const agentName =
                agent === 'all' ? 'all_agents' : report.agents.find((a) => String(a.id) === agent)?.name.replace(/\s+/g, '_') || 'agent';
            const first = response.data.start.slice(0, 10);
            link.setAttribute('href', url);
            link.setAttribute('download', `calls_${first}_${range}_${agentName}.csv`);
            link.style.visibility = 'hidden';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(url);
            toast.success('Your calls are downloading.');
        } catch {
            toast.error("Couldn't download the calls. Please try again.");
        } finally {
            downloadingRef.current = false;
            setDownloading(false);
        }
    };

    const cards = report ? shownCards(report.layout.cards, report.layout.average) : [];
    const kpis = cards.filter((c) => c.size === 'kpi');
    const panels = cards.filter((c) => c.size !== 'kpi');
    const ctx = report
        ? {
              report,
              now,
              onAddAnswer: can('agents:facts')
                  ? (q: { run_id: number; workflow_id: number; question: string }) =>
                        setAnswering({ run_id: q.run_id, workflow_id: q.workflow_id, questions: [q.question] })
                  : undefined,
          }
        : null;

    return (
        <div className="page-body">
            <div className="flex flex-col gap-5">
                <header className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
                    <div className="min-w-0">
                        <p className="text-meta font-semibold uppercase tracking-[0.08em] text-ink-3">
                            Reports{report ? ` · ${report.pack_label} pack` : ''}
                        </p>
                        <h1 className="mt-1 font-display text-[24px] font-semibold tracking-[-0.015em] sm:text-page">
                            {report ? reportTitle(report) : 'Reports'}
                        </h1>
                        <p className="mt-1 max-w-2xl text-body text-ink-2">
                            {report ? `Compared with ${comparedWith(report)}. ` : ''}
                            {report?.layout.can_customise
                                ? 'Every card below can be hidden, moved or sent in your email report.'
                                : 'How your phone agent did, in your business’s own numbers.'}
                        </p>
                    </div>
                    <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center xl:justify-end">
                        <div role="group" aria-label="Period" className="flex w-full rounded-[10px] border border-line bg-panel p-[3px] sm:w-auto">
                            {RANGE_OPTIONS.map((option) => {
                                const pressed = range === option.value;
                                const button = (
                                    <button
                                        key={option.value}
                                        type="button"
                                        aria-pressed={pressed}
                                        onClick={() => {
                                            setRange(option.value);
                                            if (option.value === 'custom') setPickerOpen(true);
                                        }}
                                        className={cn(
                                            'flex-1 whitespace-nowrap rounded-[7px] px-3 py-1.5 text-body font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring/50 sm:flex-none',
                                            pressed ? 'bg-foreground text-background' : 'text-ink-2 hover:bg-panel-2',
                                        )}
                                    >
                                        {option.label}
                                    </button>
                                );
                                if (option.value !== 'custom') return button;
                                return (
                                    <Popover key={option.value} open={pickerOpen} onOpenChange={setPickerOpen}>
                                        <PopoverTrigger asChild>{button}</PopoverTrigger>
                                        <PopoverContent align="end" className="w-auto p-0">
                                            <CalendarPicker
                                                mode="range"
                                                selected={custom}
                                                onSelect={(value) => setCustom(value)}
                                                disabled={(date) => date > new Date()}
                                                numberOfMonths={1}
                                            />
                                            <div className="flex items-center justify-between gap-2 border-t border-line px-3 py-2">
                                                <span className="text-caption text-ink-3">
                                                    {custom?.from
                                                        ? `${format(custom.from, 'd MMM')}${custom.to ? ` – ${format(custom.to, 'd MMM')}` : ''}`
                                                        : 'Pick the first and last day'}
                                                </span>
                                                <Button size="sm" onClick={() => setPickerOpen(false)} disabled={!custom?.from}>
                                                    Show
                                                </Button>
                                            </div>
                                        </PopoverContent>
                                    </Popover>
                                );
                            })}
                        </div>
                        <div className="flex flex-wrap gap-2 sm:flex-nowrap">
                            <Select value={agent} onValueChange={setAgent}>
                                <SelectTrigger className="w-full min-w-0 bg-panel data-[size=default]:h-10 sm:w-[180px]" aria-label="Agent">
                                    <SelectValue placeholder="All agents" />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="all">All agents</SelectItem>
                                    {(report?.agents ?? []).map((a) => (
                                        <SelectItem key={a.id} value={String(a.id)}>
                                            {a.name}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                            <Button variant="outline" className="h-10 flex-1 bg-panel sm:flex-none" onClick={download} disabled={downloading || !report}>
                                <Download aria-hidden />
                                {downloading ? 'Preparing…' : 'Download'}
                            </Button>
                            <Button variant="outline" className="h-10 flex-1 bg-panel sm:flex-none" onClick={emailMe} disabled={emailing || !report}>
                                <Mail aria-hidden />
                                {emailing ? 'Sending…' : 'Email me'}
                            </Button>
                            {report?.layout.can_customise ? (
                                <Button className="h-10 flex-1 sm:flex-none" onClick={() => setCustomising(true)}>
                                    <Settings2 aria-hidden />
                                    Customise
                                </Button>
                            ) : null}
                        </div>
                    </div>
                </header>

                {range === 'custom' && !query ? (
                    <EmptyState icon={CalendarDays} title="Pick the days to report on">
                        Choose a first and last day under Custom.
                    </EmptyState>
                ) : loading && !report ? (
                    <ReportSkeleton />
                ) : error ? (
                    <EmptyState
                        tone="amber"
                        icon={FileWarning}
                        role="alert"
                        title={error}
                        action={
                            <Button className="h-10 sm:h-9" onClick={() => setAttempt((n) => n + 1)}>
                                <RefreshCw aria-hidden />
                                Try again
                            </Button>
                        }
                    >
                        Something went wrong on our side. Please try again in a moment.
                    </EmptyState>
                ) : report && ctx && !report.has_calls ? (
                    <EmptyState icon={PhoneCall} title="No calls yet">
                        Your report fills in as soon as your agent takes its first call.
                    </EmptyState>
                ) : report && ctx ? (
                    <div className={cn('flex flex-col gap-4 transition-opacity', loading && 'opacity-60')} aria-busy={loading}>
                        {report.calls === 0 ? (
                            <p className="rounded-xl border border-line bg-panel px-4 py-3 text-body text-ink-2">
                                No calls in this period. Try a longer period, or another agent.
                            </p>
                        ) : null}
                        {kpis.length ? (
                            <div className="grid grid-cols-2 gap-3 sm:grid-cols-[repeat(auto-fit,minmax(190px,1fr))] sm:gap-4">
                                {kpis.map((c) => (
                                    <ReportCard key={c.key} cardKey={c.key} title={c.title} ctx={ctx} />
                                ))}
                            </div>
                        ) : null}
                        {panels.length ? (
                            <div className="grid grid-flow-row-dense grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
                                {panels.map((c) => (
                                    <div key={c.key} className={cn('min-w-0 [&>section]:h-full', c.size === 'wide' && 'lg:col-span-2')}>
                                        <ReportCard cardKey={c.key} title={c.title} ctx={ctx} />
                                    </div>
                                ))}
                            </div>
                        ) : null}
                        {!cards.length ? (
                            <EmptyState icon={Settings2} title="Every card is switched off">
                                Switch some back on in Customise.
                            </EmptyState>
                        ) : null}
                        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-caption text-ink-3">
                            <span>Times in {report.timezone.replace(/_/g, ' ')} time.</span>
                            <Link href="/settings/reports" className="inline-flex items-center gap-1 font-medium text-brand hover:underline">
                                <Mail className="size-3.5" aria-hidden />
                                Get it every day or week by email
                            </Link>
                        </p>
                    </div>
                ) : null}
            </div>
            {report ? (
                <CustomiseDrawer
                    open={customising}
                    onOpenChange={setCustomising}
                    layout={report.layout}
                    packLabel={report.pack_label}
                    workflowId={report.workflow_id ?? null}
                    onSaved={onLayoutSaved}
                />
            ) : null}
            <AddAnswerDialog item={answering} onClose={() => setAnswering(null)} onSaved={() => setAttempt((n) => n + 1)} />
        </div>
    );
}
