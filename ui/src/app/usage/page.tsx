"use client";

import { Download, Globe, PhoneCall, PhoneOff, RefreshCw, Search, ShieldCheck } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { type ComponentProps, useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import TimezoneSelect, { type ITimezoneOption } from 'react-timezone-select';
import { toast } from 'sonner';

import { downloadUsageRunsReportApiV1OrganizationsUsageRunsReportGet, getDailyUsageBreakdownApiV1OrganizationsUsageDailyBreakdownGet, getPreferencesApiV1OrganizationsPreferencesGet, getUsageHistoryApiV1OrganizationsUsageRunsGet, getWorkflowsSummaryApiV1WorkflowSummaryGet, savePreferencesApiV1OrganizationsPreferencesPut } from '@/client/sdk.gen';
import type { DailyUsageBreakdownResponse, OrganizationPreferences, WorkflowRunUsageResponse, WorkflowSummaryResponse } from '@/client/types.gen';
import { DailyUsageTable } from '@/components/DailyUsageTable';
import { FilterBuilder } from '@/components/filters/FilterBuilder';
import { runDetailHref } from '@/components/layout/shellContext';
import { EmptyState } from '@/components/page-states/EmptyState';
import { CallerDataRequestDialog } from '@/components/privacy/CallerDataRequestDialog';
import { Button } from '@/components/ui/button';
import { PageHeader } from '@/components/ui/page-header';
import { useUserConfig } from '@/context/UserConfigContext';
import { useIsMobile } from '@/hooks/use-mobile';
import { useDispositionCodes } from '@/hooks/useDispositionCodes';
import { useFeatureEnabled } from '@/hooks/useFeatureFlags';
import { detailFromError } from '@/lib/apiError';
import { useAuth } from '@/lib/auth';
import { getLocalTimezone } from '@/lib/dateTime';
import { getUsageFilterAttributes, withDispositionCodeOptions } from '@/lib/filterAttributes';
import { decodeFiltersFromURL, encodeFiltersToURL } from '@/lib/filters';
import { cn } from '@/lib/utils';
import type { ActiveFilter, FilterAttribute, NumberFilterOption } from '@/types/filters';

import { CallCards, CallCardsSkeleton } from './CallCards';
import { CallPanel } from './CallPanel';
import { CallsFilterBar, CallsTabs } from './CallsFilters';
import { CallsPager } from './CallsPager';
import { CallsTable, CallsTableSkeleton } from './CallsTable';
import {
    type ApiFilter,
    CALLS_TABS,
    type CallsQuery,
    callsQueryFromParams,
    callsQueryToParams,
    type CallsTab,
    chipFilters,
    dateRangeFor,
    DEFAULT_QUERY,
    isNarrowed,
    PAGE_SIZE,
    tabFilter,
    whenPhrase,
} from './callsView';

/**
 * The expert filters behind "More filters": everything the API can filter
 * on, minus the dates (the date chip owns those), in plain words.
 */
const buildExpertAttributes = (
    agentOptions: NumberFilterOption[] | null,
    isLoadingAgentOptions: boolean,
    dispositionCodes: string[],
    campaignsEnabled: boolean,
): FilterAttribute[] => {
    return withDispositionCodeOptions(getUsageFilterAttributes(campaignsEnabled), dispositionCodes)
        .filter(attribute => attribute.id !== 'dateRange')
        .map(attribute => {
            if (attribute.id === 'runId') {
                return { ...attribute, label: 'Call ID', config: { ...attribute.config, placeholder: 'Enter a call ID' } };
            }
            if (attribute.id !== 'workflowId') {
                return attribute;
            }
            return {
                ...attribute,
                label: 'Agent',
                type: 'numberSelect',
                config: {
                    ...attribute.config,
                    placeholder: 'Select an agent',
                    numberSelectLabel: 'Agent',
                    ...(agentOptions || isLoadingAgentOptions
                        ? {
                            numberSelectOptions: agentOptions ?? [],
                            numberSelectOptionsLoading: isLoadingAgentOptions,
                        }
                        : {}),
                },
            } satisfies FilterAttribute;
        });
};

/** The expert filters as the API takes them. */
function expertApiFilters(filters: ActiveFilter[]): ApiFilter[] {
    return filters.map(filter => ({
        attribute: filter.attribute.id,
        type: filter.attribute.type === 'numberSelect' ? 'number' : filter.attribute.type,
        value: filter.value,
    }));
}

/** start_date / end_date / filters for one request. */
function requestQuery(query: CallsQuery, extra: ApiFilter[], now: Date) {
    const range = dateRangeFor(query, now);
    return {
        ...(range && { start_date: range.from.toISOString(), end_date: range.to.toISOString() }),
        ...(extra.length > 0 && { filters: JSON.stringify(extra) }),
    };
}

/** Whether the window is at least `px` wide. */
function useMinWidth(px: number): boolean {
    const [wide, setWide] = useState(false);
    useEffect(() => {
        const query = window.matchMedia(`(min-width: ${px}px)`);
        const update = () => setWide(query.matches);
        update();
        query.addEventListener('change', update);
        return () => query.removeEventListener('change', update);
    }, [px]);
    return wide;
}

type ListState =
    | { state: 'loading' }
    | { state: 'error' }
    | { state: 'ready'; runs: WorkflowRunUsageResponse[]; total: number; anyCalls: boolean };

export default function UsagePage() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const { organizationPricing, can } = useUserConfig();
    const auth = useAuth();
    const isPhone = useIsMobile();
    // A computer: the call opens in a column beside the list.
    const isWide = useMinWidth(1440);
    // Narrower than this (phones, tablets), the list is cards, not a table.
    const tableFits = useMinWidth(1100);
    const listId = useId();

    // The URL is the source of truth: tabs, search, chips, page, expert
    // filters and the open call all live there, so Back, Forward and a
    // shared link show the same list.
    const paramsKey = searchParams.toString();
    const query = useMemo(() => callsQueryFromParams(new URLSearchParams(paramsKey)), [paramsKey]);
    const callParam = Number.parseInt(searchParams.get('call') ?? '', 10);
    const openCallId = Number.isFinite(callParam) && callParam > 0 ? callParam : null;
    const autoplay = searchParams.get('play') === '1';

    const [agentFilterOptions, setAgentFilterOptions] = useState<NumberFilterOption[] | null>(null);
    const [isLoadingAgentFilterOptions, setIsLoadingAgentFilterOptions] = useState(false);
    const { codes: dispositionCodes } = useDispositionCodes();
    const campaignsEnabled = useFeatureEnabled('campaigns');
    const expertAttributes = useMemo(
        () => buildExpertAttributes(agentFilterOptions, isLoadingAgentFilterOptions, dispositionCodes, campaignsEnabled),
        [agentFilterOptions, isLoadingAgentFilterOptions, dispositionCodes, campaignsEnabled]
    );
    const filtersParam = searchParams.get('filters');
    const appliedExpert = useMemo(
        () => decodeFiltersFromURL(new URLSearchParams(filtersParam ? { filters: filtersParam } : {}), expertAttributes),
        [filtersParam, expertAttributes]
    );
    // In-progress edits in the FilterBuilder; committed with its Apply button.
    const [draftExpert, setDraftExpert] = useState<ActiveFilter[]>(appliedExpert);
    useEffect(() => setDraftExpert(appliedExpert), [appliedExpert]);
    const [expertOpen, setExpertOpen] = useState(() => appliedExpert.length > 0);

    const [list, setList] = useState<ListState>({ state: 'loading' });
    const [counts, setCounts] = useState<Partial<Record<CallsTab, number>>>({});
    const [reloadKey, setReloadKey] = useState(0);
    const [isDownloading, setIsDownloading] = useState(false);
    // A call opened from a deep link that isn't on this page of the list.
    const [linkedRun, setLinkedRun] = useState<WorkflowRunUsageResponse | null>(null);
    // Set when a row is opened from this list, so closing the call goes Back.
    const openedHere = useRef(false);
    // Closing the call on a computer also stops the first call showing by itself.
    const [previewDismissed, setPreviewDismissed] = useState(false);

    // Daily usage breakdown (only for organisations on per-second pricing)
    const [dailyUsage, setDailyUsage] = useState<DailyUsageBreakdownResponse | null>(null);
    const [isLoadingDaily, setIsLoadingDaily] = useState(false);

    // Time zone for call times
    const localTimezone = getLocalTimezone();
    const [selectedTimezone, setSelectedTimezone] = useState<ITimezoneOption | string>('');
    const [savingTimezone, setSavingTimezone] = useState(false);
    const [preferences, setPreferences] = useState<OrganizationPreferences>({});
    const [preferencesLoading, setPreferencesLoading] = useState(true);
    const timezoneSelectId = useId(); // Stable ID for react-select to prevent hydration mismatch
    const timezoneValue = typeof selectedTimezone === 'string' ? selectedTimezone : selectedTimezone.value;
    const effectiveTimezone = timezoneValue || localTimezone;

    const expertKey = JSON.stringify(expertApiFilters(appliedExpert));

    // The list, the tab totals, and (when the list is empty) whether there are any calls at all.
    useEffect(() => {
        if (!auth.isAuthenticated) return;
        let cancelled = false;
        const now = new Date();
        const expert = JSON.parse(expertKey) as ApiFilter[];
        const shared = [...chipFilters(query), ...expert];
        const withTab = (tab: CallsTab) => {
            const filter = tabFilter(tab);
            return filter ? [filter, ...shared] : shared;
        };
        setList({ state: 'loading' });
        setCounts({});

        const load = async () => {
            try {
                const response = await getUsageHistoryApiV1OrganizationsUsageRunsGet({
                    query: { page: query.page, limit: PAGE_SIZE, ...requestQuery(query, withTab(query.tab), now) },
                });
                if (cancelled) return;
                if (!response.data) {
                    setList({ state: 'error' });
                    return;
                }
                const { runs, total_count: total } = response.data;
                let anyCalls = total > 0;
                if (!anyCalls) {
                    const everything = await getUsageHistoryApiV1OrganizationsUsageRunsGet({ query: { page: 1, limit: 1 } });
                    anyCalls = (everything.data?.total_count ?? 1) > 0;
                }
                if (cancelled) return;
                setList({ state: 'ready', runs, total, anyCalls });
                setCounts(current => ({ ...current, [query.tab]: total }));
            } catch (error) {
                console.error('Failed to fetch calls:', error);
                if (!cancelled) setList({ state: 'error' });
            }
        };

        // Each tab's total is a one-row request with the same filters.
        const loadCounts = () => {
            CALLS_TABS.filter(({ value }) => value !== query.tab).forEach(({ value }) => {
                getUsageHistoryApiV1OrganizationsUsageRunsGet({
                    query: { page: 1, limit: 1, ...requestQuery(query, withTab(value), now) },
                })
                    .then(response => {
                        if (!cancelled && response.data) {
                            setCounts(current => ({ ...current, [value]: response.data!.total_count }));
                        }
                    })
                    .catch(() => undefined);
            });
        };

        void load();
        loadCounts();
        return () => {
            cancelled = true;
        };
    }, [auth.isAuthenticated, query, expertKey, reloadKey]);

    const runs = useMemo(() => (list.state === 'ready' ? list.runs : []), [list]);

    // A linked call that isn't on this page: look it up by its ID.
    useEffect(() => {
        if (!auth.isAuthenticated || !openCallId || list.state !== 'ready') return;
        if (runs.some(run => run.id === openCallId) || linkedRun?.id === openCallId) return;
        let cancelled = false;
        getUsageHistoryApiV1OrganizationsUsageRunsGet({
            query: {
                page: 1,
                limit: 1,
                filters: JSON.stringify([{ attribute: 'runId', type: 'number', value: { value: openCallId } }]),
            },
        })
            .then(response => {
                if (cancelled) return;
                const found = response.data?.runs[0] ?? null;
                setLinkedRun(found);
                if (!found) toast.error("We couldn't find that call.");
            })
            .catch(() => undefined);
        return () => {
            cancelled = true;
        };
    }, [auth.isAuthenticated, openCallId, list.state, runs, linkedRun?.id]);

    // On a computer the first call shows beside the list until another is chosen.
    const openRun = openCallId
        ? runs.find(run => run.id === openCallId) ?? (linkedRun?.id === openCallId ? linkedRun : null)
        : isWide && !previewDismissed
            ? runs.find(run => run.recording_url) ?? runs[0] ?? null
            : null;
    const panelLayout = isWide ? 'column' : 'overlay';
    const overlayOpen = Boolean(openRun) && panelLayout === 'overlay';

    // Keep the page behind the full-screen call still.
    useEffect(() => {
        if (!overlayOpen) return;
        const previous = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        return () => {
            document.body.style.overflow = previous;
        };
    }, [overlayOpen]);

    const hrefWith = useCallback(
        (next: CallsQuery, call?: number | null) => {
            const params = callsQueryToParams(next, { filters: filtersParam, call });
            const qs = params.toString();
            return `/usage${qs ? `?${qs}` : ''}`;
        },
        [filtersParam]
    );

    /** Change the controls: back to page 1, and the open call closes. */
    const navigate = useCallback(
        (change: Partial<CallsQuery>, options: { replace?: boolean } = {}) => {
            const next = { ...query, page: 1, ...change };
            const href = hrefWith(next);
            if (options.replace) router.replace(href, { scroll: false });
            else router.push(href, { scroll: false });
        },
        [query, hrefWith, router]
    );

    const callHref = useCallback((run: WorkflowRunUsageResponse) => hrefWith(query, run.id), [hrefWith, query]);

    const playRun = useCallback(
        (run: WorkflowRunUsageResponse) => {
            openedHere.current = true;
            router.push(`${hrefWith(query, run.id)}&play=1`, { scroll: false });
        },
        [hrefWith, query, router]
    );

    const closeCall = useCallback(() => {
        setPreviewDismissed(true);
        if (!openCallId) return;
        if (openedHere.current) {
            openedHere.current = false;
            router.back();
        } else {
            router.replace(hrefWith(query), { scroll: false });
        }
    }, [openCallId, router, hrefWith, query]);

    const applyExpert = useCallback(
        (filters: ActiveFilter[]) => {
            const encoded = filters.length > 0 ? new URLSearchParams(encodeFiltersToURL(filters)).get('filters') : null;
            const params = callsQueryToParams({ ...query, page: 1 }, { filters: encoded });
            router.push(`/usage${params.toString() ? `?${params}` : ''}`, { scroll: false });
        },
        [query, router]
    );

    const clearAll = useCallback(() => {
        setDraftExpert([]);
        router.push(`/usage?${callsQueryToParams({ ...DEFAULT_QUERY, when: 'all' })}`, { scroll: false });
    }, [router]);

    const fetchDailyUsage = useCallback(async () => {
        if (!auth.isAuthenticated || !organizationPricing?.price_per_second_usd) return;
        setIsLoadingDaily(true);
        try {
            const response = await getDailyUsageBreakdownApiV1OrganizationsUsageDailyBreakdownGet({ query: { days: 7 } });
            if (response.data) setDailyUsage(response.data);
        } catch (error) {
            console.error('Failed to fetch daily usage:', error);
        } finally {
            setIsLoadingDaily(false);
        }
    }, [auth.isAuthenticated, organizationPricing]);

    const fetchAgentFilterOptions = useCallback(async () => {
        if (!auth.isAuthenticated) return;
        setIsLoadingAgentFilterOptions(true);
        try {
            const response = await getWorkflowsSummaryApiV1WorkflowSummaryGet({ query: { status: 'active' } });
            if (response.error) {
                throw new Error(detailFromError(response.error, 'Failed to load agents'));
            }
            const options = [...(response.data ?? [])]
                .sort((a: WorkflowSummaryResponse, b: WorkflowSummaryResponse) => (
                    a.name.localeCompare(b.name) || a.id - b.id
                ))
                .map((workflow: WorkflowSummaryResponse) => ({
                    label: `${workflow.name || 'Untitled agent'} (#${workflow.id})`,
                    value: workflow.id,
                }));
            setAgentFilterOptions(options);
        } catch (error) {
            console.error('Failed to fetch agent filter options:', error);
            setAgentFilterOptions(null);
        } finally {
            setIsLoadingAgentFilterOptions(false);
        }
    }, [auth.isAuthenticated]);

    const fetchPreferences = useCallback(async () => {
        if (!auth.isAuthenticated) return;
        setPreferencesLoading(true);
        try {
            const response = await getPreferencesApiV1OrganizationsPreferencesGet();
            const nextPreferences: OrganizationPreferences = response.data || {};
            setPreferences(nextPreferences);
            setSelectedTimezone(nextPreferences.timezone || localTimezone);
        } catch (error) {
            console.error('Failed to fetch organization preferences:', error);
            setSelectedTimezone(localTimezone);
        } finally {
            setPreferencesLoading(false);
        }
    }, [auth.isAuthenticated, localTimezone]);

    useEffect(() => {
        fetchPreferences();
    }, [fetchPreferences]);

    useEffect(() => {
        fetchAgentFilterOptions();
    }, [fetchAgentFilterOptions]);

    useEffect(() => {
        if (auth.isAuthenticated && organizationPricing?.price_per_second_usd) {
            fetchDailyUsage();
        }
    }, [auth.isAuthenticated, organizationPricing, fetchDailyUsage]);

    // A spreadsheet of every call the list is showing (all pages).
    const handleDownload = async () => {
        if (!auth.isAuthenticated) return;
        setIsDownloading(true);
        try {
            const filter = tabFilter(query.tab);
            const filters = [...(filter ? [filter] : []), ...chipFilters(query), ...expertApiFilters(appliedExpert)];
            const response = await downloadUsageRunsReportApiV1OrganizationsUsageRunsReportGet({
                query: requestQuery(query, filters, new Date()),
                parseAs: 'blob',
            });
            if (response.data) {
                const url = window.URL.createObjectURL(response.data as Blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'calls.csv';
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
            } else {
                toast.error("We couldn't make the list. Please try again.");
            }
        } catch (error) {
            console.error('Failed to download calls:', error);
            toast.error("We couldn't make the list. Please try again.");
        } finally {
            setIsDownloading(false);
        }
    };

    const handleTimezoneChange = async (timezone: ITimezoneOption | string) => {
        setSelectedTimezone(timezone);
        setSavingTimezone(true);
        const previousTimezone = preferences.timezone || localTimezone;
        try {
            const tzValue = typeof timezone === 'string' ? timezone : timezone.value;
            const response = await savePreferencesApiV1OrganizationsPreferencesPut({ body: { timezone: tzValue } });
            if (response.error) {
                throw new Error('Failed to save timezone');
            }
            setPreferences(response.data || { ...preferences, timezone: tzValue });
        } catch (error) {
            console.error('Failed to save timezone:', error);
            setSelectedTimezone(previousTimezone);
        } finally {
            setSavingTimezone(false);
        }
    };

    const narrowed = isNarrowed(query, appliedExpert.length);
    const fullPageHref = openRun
        ? runDetailHref(openRun.workflow_id, openRun.id, hrefWith(query, openRun.id))
        : '';
    const rowProps = {
        runs,
        timezone: effectiveTimezone,
        selectedId: openRun?.id ?? null,
        hrefFor: callHref,
        onPlay: playRun,
        onOpen: () => {
            openedHere.current = true;
        },
    };

    return (
        <div className="page-body">
            <div className={cn('mx-auto flex flex-col gap-6', isWide && openRun ? 'max-w-[1400px]' : 'max-w-6xl')}>
                <div inert={overlayOpen} className="flex flex-col">
                    <PageHeader
                        className="mb-0"
                        title="Calls"
                        description="Every call your agent answered, with the recording and what was said."
                        action={
                            <Button variant="outline" className="h-10 bg-panel sm:h-9" onClick={handleDownload} disabled={isDownloading}>
                                <Download aria-hidden />
                                {isDownloading ? 'Preparing…' : 'Download list'}
                            </Button>
                        }
                    />
                </div>

                <div
                    className={cn(
                        'grid items-start gap-4',
                        isWide && openRun && 'grid-cols-[minmax(0,1fr)_380px]'
                    )}
                >
                    <div inert={overlayOpen} className="flex min-w-0 flex-col gap-4">
                        <section aria-label="Calls" className="overflow-hidden rounded-xl border border-line bg-panel">
                            <div className="border-b border-line-soft pt-1">
                                <CallsTabs
                                    tab={query.tab}
                                    counts={counts}
                                    listId={listId}
                                    onChange={tab => navigate({ tab })}
                                />
                            </div>
                            <CallsFilterBar
                                query={query}
                                outcomeCodes={dispositionCodes}
                                expertCount={appliedExpert.length}
                                expertOpen={expertOpen}
                                onChange={navigate}
                                onToggleExpert={() => setExpertOpen(open => !open)}
                            />

                            {expertOpen && (
                                <div id="calls-more-filters" className="border-t border-line-soft bg-panel-2/60 px-4 py-4">
                                    <FilterBuilder
                                        availableAttributes={expertAttributes}
                                        activeFilters={draftExpert}
                                        onFiltersChange={setDraftExpert}
                                        onApplyFilters={() => applyExpert(draftExpert)}
                                        onClearFilters={() => {
                                            setDraftExpert([]);
                                            applyExpert([]);
                                        }}
                                    />
                                </div>
                            )}

                            <div id={listId} aria-busy={list.state === 'loading'} className="border-t border-line-soft">
                                {list.state === 'loading' ? (
                                    <>
                                        <span className="sr-only" role="status">Loading calls</span>
                                        {tableFits ? <CallsTableSkeleton /> : <CallCardsSkeleton />}
                                    </>
                                ) : list.state === 'error' ? (
                                    <EmptyState
                                        tone="amber"
                                        icon={PhoneOff}
                                        as="h2"
                                        role="alert"
                                        title="We couldn't load your calls"
                                        className="rounded-none border-0"
                                        action={
                                            <Button className="h-10 sm:h-9" onClick={() => setReloadKey(key => key + 1)}>
                                                <RefreshCw aria-hidden />
                                                Try again
                                            </Button>
                                        }
                                    >
                                        Something went wrong on our side. Please try again in a moment.
                                    </EmptyState>
                                ) : runs.length === 0 ? (
                                    !list.anyCalls ? (
                                        <EmptyState icon={PhoneCall} as="h2" title="No calls yet" className="rounded-none border-0">
                                            When your agent answers a call, it shows up here with the recording and what was said.
                                            Try ringing your agent&apos;s number, or test it from your agent&apos;s page.
                                        </EmptyState>
                                    ) : (
                                        <EmptyState
                                            icon={Search}
                                            as="h2"
                                            title="No calls match"
                                            className="rounded-none border-0"
                                            action={
                                                narrowed ? (
                                                    <Button variant="outline" className="h-10 sm:h-9" onClick={clearAll}>
                                                        Clear filters
                                                    </Button>
                                                ) : undefined
                                            }
                                        >
                                            {query.q.trim()
                                                ? `Nothing for “${query.q.trim()}” ${whenPhrase(query)}.`
                                                : `No calls ${whenPhrase(query)}${query.outcome || query.who || appliedExpert.length ? ' with these filters' : ''}.`}
                                        </EmptyState>
                                    )
                                ) : !tableFits ? (
                                    <CallCards {...rowProps} />
                                ) : (
                                    <CallsTable {...rowProps} />
                                )}
                            </div>

                            {list.state === 'ready' && list.total > 0 && (
                                <CallsPager
                                    page={query.page}
                                    pageSize={PAGE_SIZE}
                                    total={list.total}
                                    onPage={page => router.push(hrefWith({ ...query, page }), { scroll: false })}
                                />
                            )}
                        </section>

                        {expertOpen && (
                            <section
                                aria-label="More options"
                                className="flex flex-col gap-5 rounded-xl border border-line bg-panel px-5 py-5 sm:px-6"
                            >
                                <div className="flex flex-col gap-2">
                                    <h2 className="text-[14.5px] font-semibold">
                                        <label htmlFor={`${timezoneSelectId}-input`} className="inline-flex items-center gap-1.5">
                                            <Globe className="size-4 text-ink-3" aria-hidden />
                                            Time zone for call times
                                        </label>
                                    </h2>
                                    <div className="w-full max-w-sm">
                                        <TimezoneSelect
                                            instanceId={timezoneSelectId}
                                            inputId={`${timezoneSelectId}-input`}
                                            value={selectedTimezone}
                                            onChange={handleTimezoneChange}
                                            isDisabled={savingTimezone || preferencesLoading}
                                            placeholder={preferencesLoading ? 'Loading…' : 'Choose a time zone'}
                                            styles={TIMEZONE_STYLES}
                                        />
                                    </div>
                                </div>

                                {/* Callers' access and erasure requests (GDPR) are admin-only. */}
                                {can('org:manage') && (
                                    <div className="flex flex-col gap-2 border-t border-line-soft pt-5 sm:flex-row sm:items-center sm:justify-between">
                                        <div className="flex items-start gap-3">
                                            <ShieldCheck className="mt-0.5 size-5 flex-none text-ink-3" aria-hidden />
                                            <div>
                                                <h2 className="text-[14.5px] font-semibold">A caller wants their data</h2>
                                                <p className="text-[13px] text-ink-3">
                                                    If someone asks for a copy of their calls, or for them to be deleted, start here.
                                                </p>
                                            </div>
                                        </div>
                                        <CallerDataRequestDialog />
                                    </div>
                                )}
                            </section>
                        )}

                        {/* Daily usage and cost: only for organisations on per-second pricing. */}
                        {organizationPricing?.price_per_second_usd && (
                            <DailyUsageTable data={dailyUsage} isLoading={isLoadingDaily} />
                        )}
                    </div>

                    {openRun && (
                        <>
                            {overlayOpen && (
                                <div className="fixed inset-0 z-40 hidden bg-black/30 md:block" aria-hidden onClick={closeCall} />
                            )}
                            <CallPanel
                                key={openRun.id}
                                run={openRun}
                                timezone={effectiveTimezone}
                                autoplay={autoplay && openRun.id === openCallId}
                                focusOnOpen={openRun.id === openCallId}
                                layout={panelLayout}
                                isPhone={isPhone}
                                fullPageHref={fullPageHref}
                                onClose={closeCall}
                            />
                        </>
                    )}
                </div>
            </div>
        </div>
    );
}

type TimezoneStyles = NonNullable<ComponentProps<typeof TimezoneSelect>['styles']>;

const TIMEZONE_STYLES: TimezoneStyles = {
    control: (base, state) => ({
        ...base,
        minHeight: '40px',
        fontSize: '14px',
        backgroundColor: 'var(--background)',
        borderColor: state.isFocused ? 'var(--ring)' : 'var(--border)',
        boxShadow: state.isFocused ? '0 0 0 2px color-mix(in srgb, var(--ring) 20%, transparent)' : 'none',
        '&:hover': {
            borderColor: 'var(--border)',
        },
    }),
    menu: (base) => ({
        ...base,
        zIndex: 9999,
        backgroundColor: 'var(--popover)',
        border: '1px solid var(--border)',
        boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)',
    }),
    menuList: (base) => ({
        ...base,
        backgroundColor: 'var(--popover)',
        padding: 0,
    }),
    option: (base, state) => ({
        ...base,
        backgroundColor: state.isSelected || state.isFocused ? 'var(--accent)' : 'var(--popover)',
        color: 'var(--foreground)',
        cursor: 'pointer',
        '&:active': {
            backgroundColor: 'var(--accent)',
        },
    }),
    singleValue: (base) => ({ ...base, color: 'var(--foreground)' }),
    input: (base) => ({ ...base, color: 'var(--foreground)' }),
    placeholder: (base) => ({ ...base, color: 'var(--muted-foreground)' }),
    indicatorSeparator: (base) => ({ ...base, backgroundColor: 'var(--border)' }),
    dropdownIndicator: (base) => ({
        ...base,
        color: 'var(--muted-foreground)',
        '&:hover': { color: 'var(--foreground)' },
    }),
};
