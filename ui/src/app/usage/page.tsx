"use client";

import { ArrowDown, ArrowUp, ArrowUpDown, ChevronDown, ChevronLeft, ChevronRight, Download, Globe, PhoneCall, PhoneOff, RefreshCw, Search, ShieldCheck, SlidersHorizontal, X } from 'lucide-react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { type ComponentProps, type FormEvent, useCallback, useEffect, useId, useMemo, useState } from 'react';
import TimezoneSelect, { type ITimezoneOption } from 'react-timezone-select';
import { toast } from 'sonner';

import { downloadUsageRunsReportApiV1OrganizationsUsageRunsReportGet, getDailyUsageBreakdownApiV1OrganizationsUsageDailyBreakdownGet, getPreferencesApiV1OrganizationsPreferencesGet, getUsageHistoryApiV1OrganizationsUsageRunsGet, getWorkflowsSummaryApiV1WorkflowSummaryGet, savePreferencesApiV1OrganizationsPreferencesPut } from '@/client/sdk.gen';
import type { DailyUsageBreakdownResponse, OrganizationPreferences, UsageHistoryResponse, WorkflowRunUsageResponse, WorkflowSummaryResponse } from '@/client/types.gen';
import { CallTypeCell } from '@/components/CallTypeCell';
import { DailyUsageTable } from '@/components/DailyUsageTable';
import { FilterBuilder } from '@/components/filters/FilterBuilder';
import { runDetailHref } from '@/components/layout/shellContext';
import { MediaPreviewButton, MediaPreviewDialog } from '@/components/MediaPreviewDialog';
import { EmptyState } from '@/components/page-states/EmptyState';
import { CallerDataRequestDialog } from '@/components/privacy/CallerDataRequestDialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table';
import { useAppConfig } from '@/context/AppConfigContext';
import { useUserConfig } from '@/context/UserConfigContext';
import { useIsMobile } from '@/hooks/use-mobile';
import { useDispositionCodes } from '@/hooks/useDispositionCodes';
import { useFeatureEnabled } from '@/hooks/useFeatureFlags';
import { detailFromError } from '@/lib/apiError';
import { useAuth } from '@/lib/auth';
import { formatDateTime, getLocalTimezone } from '@/lib/dateTime';
import { getUsageFilterAttributes, withDispositionCodeOptions } from '@/lib/filterAttributes';
import { decodeFiltersFromURL, encodeFiltersToURL } from '@/lib/filters';
import { ROW_LINK } from '@/lib/rowLink';
import type { ActiveFilter, DateRangeValue, FilterAttribute, NumberFilterOption } from '@/types/filters';

import { CallCards } from './CallCards';
import {
    applyQuickSearch,
    EMPTY_QUICK_SEARCH,
    formatDuration,
    hasAdvancedFilters,
    outcomeLabel,
    type QuickSearch,
    quickSearchFrom,
    type QuickWhen,
    WHEN_OPTIONS,
} from './callsView';

const buildUsageFilterAttributes = (
    agentOptions: NumberFilterOption[] | null,
    isLoadingAgentOptions: boolean,
    dispositionCodes: string[],
    campaignsEnabled: boolean,
): FilterAttribute[] => {
    return withDispositionCodeOptions(getUsageFilterAttributes(campaignsEnabled), dispositionCodes).map(attribute => {
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

export default function UsagePage() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const { organizationPricing, can } = useUserConfig();
    const auth = useAuth();
    const { config: appConfig } = useAppConfig();
    // Under Stripe billing each run carries the EUR charged to the credit balance.
    const showEurCharge = appConfig?.billingProvider === 'stripe';

    // Usage history state
    const [usageHistory, setUsageHistory] = useState<UsageHistoryResponse | null>(null);
    // Starts true so the first paint is the list's skeleton, not "No calls yet".
    const [isLoadingHistory, setIsLoadingHistory] = useState(true);
    const [historyFailed, setHistoryFailed] = useState(false);
    const isMobile = useIsMobile();
    const [currentPage, setCurrentPage] = useState(() => {
        const pageParam = searchParams.get('page');
        return pageParam ? parseInt(pageParam, 10) : 1;
    });
    const [isExecutingFilters, setIsExecutingFilters] = useState(false);
    // Sort state (initialized from URL). Sorting is server-side because the
    // listing is paginated — sorting the current page client-side would only
    // reorder the 50 rows in hand.
    const [sortBy, setSortBy] = useState<string | null>(() => {
        return searchParams.get('sort_by') || null;
    });
    const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>(() => {
        return searchParams.get('sort_order') === 'asc' ? 'asc' : 'desc';
    });
    const [isDownloadingReport, setIsDownloadingReport] = useState(false);
    const [agentFilterOptions, setAgentFilterOptions] = useState<NumberFilterOption[] | null>(null);
    const [isLoadingAgentFilterOptions, setIsLoadingAgentFilterOptions] = useState(false);
    const { codes: dispositionCodes } = useDispositionCodes();
    const campaignsEnabled = useFeatureEnabled('campaigns');
    const availableUsageFilterAttributes = useMemo(
        () => buildUsageFilterAttributes(agentFilterOptions, isLoadingAgentFilterOptions, dispositionCodes, campaignsEnabled),
        [agentFilterOptions, isLoadingAgentFilterOptions, dispositionCodes, campaignsEnabled]
    );

    // Daily usage breakdown state (only for paid orgs)
    const [dailyUsage, setDailyUsage] = useState<DailyUsageBreakdownResponse | null>(null);
    const [isLoadingDaily, setIsLoadingDaily] = useState(false);

    // Initialize filters from URL. `activeFilters` tracks the in-progress
    // edits in the FilterBuilder; `appliedFilters` is what's actually been
    // committed via Apply (and what drives fetching + the download button).
    const [activeFilters, setActiveFilters] = useState<ActiveFilter[]>(() => {
        return decodeFiltersFromURL(searchParams, availableUsageFilterAttributes);
    });
    const [appliedFilters, setAppliedFilters] = useState<ActiveFilter[]>(() => {
        return decodeFiltersFromURL(searchParams, availableUsageFilterAttributes);
    });

    // The simple search (phone, when, outcome) and the More panel, where the
    // expert tools live: full filters, time zone, caller data requests.
    const [quick, setQuick] = useState<QuickSearch>(() => quickSearchFrom(appliedFilters));
    const [moreOpen, setMoreOpen] = useState(() => hasAdvancedFilters(appliedFilters));
    useEffect(() => {
        setQuick(quickSearchFrom(appliedFilters));
    }, [appliedFilters]);

    // Media preview dialog
    const mediaPreview = MediaPreviewDialog();

    // Timezone state - initialize with empty string to avoid hydration mismatch
    const localTimezone = getLocalTimezone();
    const [selectedTimezone, setSelectedTimezone] = useState<ITimezoneOption | string>('');
    const [savingTimezone, setSavingTimezone] = useState(false);
    const [preferences, setPreferences] = useState<OrganizationPreferences>({});
    const [preferencesLoading, setPreferencesLoading] = useState(true);
    const timezoneSelectId = useId(); // Stable ID for react-select to prevent hydration mismatch

    // Translate the FilterBuilder state into the query-param shape the
    // backend expects. Shared between the listing fetch and the CSV export
    // so they stay in lockstep.
    const buildUsageQueryParams = (filters?: ActiveFilter[]) => {
        let filterParam: string | undefined;
        let startDate = '';
        let endDate = '';

        if (filters && filters.length > 0) {
            const dateRangeFilter = filters.find(f => f.attribute.id === 'dateRange');
            if (dateRangeFilter && dateRangeFilter.value) {
                const dateValue = dateRangeFilter.value as DateRangeValue;
                if (dateValue.from) startDate = dateValue.from.toISOString();
                if (dateValue.to) endDate = dateValue.to.toISOString();
            }

            const otherFilters = filters.filter(f => f.attribute.id !== 'dateRange');
            if (otherFilters.length > 0) {
                const filterData = otherFilters.map(filter => ({
                    attribute: filter.attribute.id,
                    type: filter.attribute.type === 'numberSelect' ? 'number' : filter.attribute.type,
                    value: filter.value,
                }));
                filterParam = JSON.stringify(filterData);
            }
        }

        return {
            ...(startDate && { start_date: startDate }),
            ...(endDate && { end_date: endDate }),
            ...(filterParam && { filters: filterParam }),
        };
    };

    // Fetch usage history
    const fetchUsageHistory = useCallback(async (
        page: number,
        filters?: ActiveFilter[],
        sortByParam?: string | null,
        sortOrderParam?: 'asc' | 'desc'
    ) => {
        if (!auth.isAuthenticated) return;
        setIsLoadingHistory(true);
        try {
            const response = await getUsageHistoryApiV1OrganizationsUsageRunsGet({
                query: {
                    page,
                    limit: 50,
                    ...buildUsageQueryParams(filters),
                    ...(sortByParam && { sort_by: sortByParam }),
                    ...(sortOrderParam && { sort_order: sortOrderParam }),
                },
            });

            if (response.data) {
                setUsageHistory(response.data);
                setHistoryFailed(false);
            } else {
                setHistoryFailed(true);
            }
        } catch (error) {
            console.error('Failed to fetch usage history:', error);
            setHistoryFailed(true);
        } finally {
            setIsLoadingHistory(false);
        }
    }, [auth.isAuthenticated]);

    // Fetch daily usage breakdown
    const fetchDailyUsage = useCallback(async () => {
        if (!auth.isAuthenticated || !organizationPricing?.price_per_second_usd) return;

        setIsLoadingDaily(true);
        try {
            const response = await getDailyUsageBreakdownApiV1OrganizationsUsageDailyBreakdownGet({
                query: { days: 7 },
            });

            if (response.data) {
                setDailyUsage(response.data);
            }
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
            const response = await getWorkflowsSummaryApiV1WorkflowSummaryGet({
                query: {
                    status: 'active',
                },
            });
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

    // Download a CSV of all runs matching the current filters.
    const handleDownloadReport = async () => {
        if (!auth.isAuthenticated) return;
        setIsDownloadingReport(true);
        try {
            const response = await downloadUsageRunsReportApiV1OrganizationsUsageRunsReportGet({
                query: buildUsageQueryParams(appliedFilters),
                parseAs: 'blob',
            });

            if (response.data) {
                const blob = response.data as Blob;
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'usage_runs_report.csv';
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
            } else {
                toast.error('Failed to download report');
            }
        } catch (error) {
            console.error('Failed to download usage report:', error);
            toast.error('Failed to download report');
        } finally {
            setIsDownloadingReport(false);
        }
    };

    // Handle timezone change
    const handleTimezoneChange = async (timezone: ITimezoneOption | string) => {
        setSelectedTimezone(timezone);
        setSavingTimezone(true);
        const previousTimezone = preferences.timezone || localTimezone;
        try {
            const tzValue = typeof timezone === 'string' ? timezone : timezone.value;
            const response = await savePreferencesApiV1OrganizationsPreferencesPut({
                body: {
                    timezone: tzValue,
                },
            });
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

    // Update timezone when organization preferences load.
    useEffect(() => {
        fetchPreferences();
    }, [fetchPreferences]);

    useEffect(() => {
        fetchAgentFilterOptions();
    }, [fetchAgentFilterOptions]);

    useEffect(() => {
        setActiveFilters(currentFilters => {
            let changed = false;
            const nextFilters = currentFilters.map(filter => {
                const updatedAttribute = availableUsageFilterAttributes.find(
                    attribute => attribute.id === filter.attribute.id
                );

                if (!updatedAttribute || updatedAttribute === filter.attribute) {
                    return filter;
                }

                changed = true;
                return {
                    ...filter,
                    attribute: updatedAttribute,
                };
            });

            return changed ? nextFilters : currentFilters;
        });
    }, [availableUsageFilterAttributes]);

    // Initial load - fetch when auth becomes available
    useEffect(() => {
        if (auth.isAuthenticated) {
            fetchUsageHistory(currentPage, appliedFilters, sortBy, sortOrder);
        }
    }, [auth.isAuthenticated, currentPage, appliedFilters, sortBy, sortOrder, fetchUsageHistory]);

    // Fetch daily usage when organizationPricing becomes available
    useEffect(() => {
        if (auth.isAuthenticated && organizationPricing?.price_per_second_usd) {
            fetchDailyUsage();
        }
    }, [auth.isAuthenticated, organizationPricing, fetchDailyUsage]);

    // Update URL with query parameters
    const updateUrlParams = useCallback((params: {
        page?: number;
        filters?: ActiveFilter[];
        sortBy?: string | null;
        sortOrder?: 'asc' | 'desc';
    }) => {
        const newParams = new URLSearchParams();

        if (params.page !== undefined) {
            newParams.set('page', params.page.toString());
        }

        if (params.sortBy) {
            newParams.set('sort_by', params.sortBy);
            newParams.set('sort_order', params.sortOrder || 'desc');
        }

        // Add filters to URL if present
        if (params.filters && params.filters.length > 0) {
            const filterString = encodeFiltersToURL(params.filters);
            if (filterString) {
                const filterParams = new URLSearchParams(filterString);
                filterParams.forEach((value, key) => newParams.set(key, value));
            }
        }

        router.push(`/usage?${newParams.toString()}`);
    }, [router]);

    const handleApplyFilters = useCallback(async (override?: ActiveFilter[]) => {
        const filters = override ?? activeFilters;
        setIsExecutingFilters(true);
        setCurrentPage(1); // Reset to first page when applying filters
        setActiveFilters(filters);
        setAppliedFilters(filters);
        updateUrlParams({ page: 1, filters, sortBy, sortOrder });
        await fetchUsageHistory(1, filters, sortBy, sortOrder);
        setIsExecutingFilters(false);
    }, [activeFilters, fetchUsageHistory, updateUrlParams, sortBy, sortOrder]);

    const handleQuickSearch = (event: FormEvent) => {
        event.preventDefault();
        void handleApplyFilters(applyQuickSearch(activeFilters, quick, availableUsageFilterAttributes, new Date()));
    };

    const handleFiltersChange = useCallback((filters: ActiveFilter[]) => {
        setActiveFilters(filters);
    }, []);

    const handleClearFilters = useCallback(async () => {
        setIsExecutingFilters(true);
        setCurrentPage(1);
        setActiveFilters([]);
        setAppliedFilters([]);
        updateUrlParams({ page: 1, filters: [], sortBy, sortOrder }); // Clear filters from URL
        await fetchUsageHistory(1, [], sortBy, sortOrder); // Fetch all runs without filters
        setIsExecutingFilters(false);
    }, [fetchUsageHistory, updateUrlParams, sortBy, sortOrder]);

    // Handle page change
    const handlePageChange = (newPage: number) => {
        setCurrentPage(newPage);
        updateUrlParams({ page: newPage, filters: appliedFilters, sortBy, sortOrder });
        fetchUsageHistory(newPage, appliedFilters, sortBy, sortOrder);
    };

    // Toggle sort direction on repeat clicks, otherwise start descending.
    // The fetch effect above picks up the new state; page resets to 1 because
    // the ordering of every page changes.
    const handleSort = useCallback((field: string) => {
        const newSortOrder = sortBy === field && sortOrder === 'desc' ? 'asc' : 'desc';
        setSortBy(field);
        setSortOrder(newSortOrder);
        setCurrentPage(1);
        updateUrlParams({ page: 1, filters: appliedFilters, sortBy: field, sortOrder: newSortOrder });
    }, [sortBy, sortOrder, appliedFilters, updateUrlParams]);

    // Each call links to its run screen, which keeps this screen's shell and
    // links back to this exact list (filters included): see shellContext.
    const runHref = (run: WorkflowRunUsageResponse) => {
        const query = searchParams.toString();
        return runDetailHref(run.workflow_id, run.id, `/usage${query ? `?${query}` : ''}`);
    };

    const timezoneValue = typeof selectedTimezone === 'string' ? selectedTimezone : selectedTimezone.value;
    const effectiveTimezone = timezoneValue || localTimezone;

    const quickActive = appliedFilters.length > 0;
    const runs = usageHistory?.runs ?? [];
    const outcomeOptions = dispositionCodes.includes(quick.outcome) || quick.outcome === 'any'
        ? dispositionCodes
        : [...dispositionCodes, quick.outcome];

    return (
        <div className="page-body">
            <div className="mx-auto flex max-w-6xl flex-col gap-6">
                {/* Everyday search first: a number, a time, an outcome. */}
                <form
                    role="search"
                    aria-label="Find calls"
                    onSubmit={handleQuickSearch}
                    className="rounded-xl border border-line bg-gradient-to-br from-brand-dim via-panel to-panel px-5 py-5 sm:px-6"
                >
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)_auto] lg:items-end">
                        <div className="flex flex-col gap-1.5 sm:col-span-2 lg:col-span-1">
                            <Label htmlFor="calls-phone">Phone number</Label>
                            <Input
                                id="calls-phone"
                                type="search"
                                inputMode="tel"
                                autoComplete="off"
                                placeholder="e.g. 087 123 4567"
                                value={quick.phone}
                                onChange={(event) => setQuick({ ...quick, phone: event.target.value })}
                                className="h-10 bg-panel font-mono"
                            />
                        </div>
                        <div className="flex flex-col gap-1.5">
                            <Label htmlFor="calls-when">When</Label>
                            <Select
                                value={quick.when}
                                onValueChange={(value) => setQuick({ ...quick, when: value as QuickWhen })}
                            >
                                <SelectTrigger id="calls-when" className="h-10 w-full bg-panel">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {WHEN_OPTIONS.map((option) => (
                                        <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                                    ))}
                                    {quick.when === 'custom' && <SelectItem value="custom">Dates set under More</SelectItem>}
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="flex flex-col gap-1.5">
                            <Label htmlFor="calls-outcome">Outcome</Label>
                            <Select value={quick.outcome} onValueChange={(value) => setQuick({ ...quick, outcome: value })}>
                                <SelectTrigger id="calls-outcome" className="h-10 w-full bg-panel">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="any">Any outcome</SelectItem>
                                    {outcomeOptions.map((code) => (
                                        <SelectItem key={code} value={code}>{outcomeLabel(code)}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                        <Button type="submit" className="h-10 sm:col-span-2 lg:col-span-1" disabled={isExecutingFilters}>
                            <Search aria-hidden />
                            Search
                        </Button>
                    </div>
                    <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                            {quickActive && (
                                <Button
                                    type="button"
                                    variant="ghost"
                                    className="h-10 sm:h-8"
                                    onClick={() => {
                                        setQuick(EMPTY_QUICK_SEARCH);
                                        void handleClearFilters();
                                    }}
                                >
                                    <X aria-hidden />
                                    Clear search
                                </Button>
                            )}
                        </div>
                        <Button
                            type="button"
                            variant="outline"
                            className="h-10 bg-panel sm:h-8"
                            aria-expanded={moreOpen}
                            aria-controls="calls-more"
                            onClick={() => setMoreOpen((open) => !open)}
                        >
                            <SlidersHorizontal aria-hidden />
                            More
                            <ChevronDown
                                aria-hidden
                                className={moreOpen ? 'rotate-180 transition-transform motion-reduce:transition-none' : 'transition-transform motion-reduce:transition-none'}
                            />
                        </Button>
                    </div>
                </form>

                {moreOpen && (
                    <section
                        id="calls-more"
                        aria-label="More options"
                        className="flex flex-col gap-5 rounded-xl border border-line bg-panel px-5 py-5 sm:px-6"
                    >
                        <div className="flex flex-col gap-3">
                            <div>
                                <h2 className="text-[14.5px] font-semibold">More filters</h2>
                                <p className="text-[13px] text-ink-3">
                                    Narrow the list by call length, direction, agent and more. Choose a filter, then Apply.
                                </p>
                            </div>
                            <FilterBuilder
                                availableAttributes={availableUsageFilterAttributes}
                                activeFilters={activeFilters}
                                onFiltersChange={handleFiltersChange}
                                onApplyFilters={() => void handleApplyFilters()}
                                onClearFilters={handleClearFilters}
                                isExecuting={isExecutingFilters}
                            />
                        </div>

                        <div className="grid gap-5 border-t border-line-soft pt-5 md:grid-cols-2">
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

                            <div className="flex flex-col gap-2">
                                <h2 className="text-[14.5px] font-semibold">Download</h2>
                                <p className="text-[13px] text-ink-3">
                                    A spreadsheet (CSV) of the calls that match your search.
                                </p>
                                <div>
                                    <Button
                                        variant="outline"
                                        className="h-10 sm:h-9"
                                        onClick={handleDownloadReport}
                                        disabled={isDownloadingReport || runs.length === 0}
                                    >
                                        <Download aria-hidden />
                                        {isDownloadingReport ? 'Preparing…' : 'Download calls'}
                                    </Button>
                                </div>
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

                <section aria-labelledby="calls-heading" className="flex flex-col gap-3">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <h2 id="calls-heading" className="text-base font-bold">
                            {quickActive ? 'Matching calls' : 'All calls'}
                        </h2>
                        {usageHistory && !isLoadingHistory && !historyFailed && runs.length > 0 && (
                            <span className="text-[13px] text-ink-3">
                                {usageHistory.total_count.toLocaleString('en-IE')} {usageHistory.total_count === 1 ? 'call' : 'calls'}
                                {' · '}
                                {formatDuration(usageHistory.total_duration_seconds)} in total
                            </span>
                        )}
                    </div>

                    {isLoadingHistory ? (
                        <div className="flex flex-col gap-2" aria-busy="true" aria-label="Loading calls">
                            {[...Array(5)].map((_, i) => (
                                <Skeleton key={i} className="h-[60px] w-full rounded-lg" />
                            ))}
                        </div>
                    ) : historyFailed ? (
                        <EmptyState
                            tone="amber"
                            icon={PhoneOff}
                            as="h3"
                            role="alert"
                            title="We couldn't load your calls"
                            action={
                                <Button
                                    className="h-10 sm:h-9"
                                    onClick={() => void fetchUsageHistory(currentPage, appliedFilters, sortBy, sortOrder)}
                                >
                                    <RefreshCw aria-hidden />
                                    Try again
                                </Button>
                            }
                        >
                            Something went wrong on our side. Your calls are safe; try again in a moment.
                        </EmptyState>
                    ) : runs.length === 0 ? (
                        quickActive ? (
                            <EmptyState
                                icon={Search}
                                as="h3"
                                title="No calls match your search"
                                action={
                                    <Button
                                        variant="outline"
                                        className="h-10 sm:h-9"
                                        onClick={() => {
                                            setQuick(EMPTY_QUICK_SEARCH);
                                            void handleClearFilters();
                                        }}
                                    >
                                        Show all calls
                                    </Button>
                                }
                            >
                                Try a shorter part of the number, or a longer time.
                            </EmptyState>
                        ) : (
                            <EmptyState icon={PhoneCall} as="h3" title="No calls yet">
                                When your agent answers or makes a call, it shows up here with how it went.
                                Try a test call from your agent&apos;s page.
                            </EmptyState>
                        )
                    ) : isMobile ? (
                        <CallCards
                            runs={runs}
                            timezone={effectiveTimezone}
                            hrefFor={runHref}
                            onOpenPreview={mediaPreview.openPreview}
                        />
                    ) : (
                        <div className="overflow-x-auto rounded-lg border border-line bg-panel">
                            <Table>
                                <TableHeader>
                                    <TableRow className="bg-panel-2">
                                        <TableHead className="font-semibold">Call</TableHead>
                                        <TableHead className="font-semibold">When</TableHead>
                                        <TableHead className="font-semibold">Phone number</TableHead>
                                        <TableHead className="font-semibold">Outcome</TableHead>
                                        <TableHead
                                            className="font-semibold text-right"
                                            aria-sort={sortBy === 'duration' ? (sortOrder === 'asc' ? 'ascending' : 'descending') : undefined}
                                        >
                                            <button
                                                type="button"
                                                className="ml-auto flex items-center justify-end gap-1 rounded px-1 outline-none hover:bg-muted/50 focus-visible:ring-[3px] focus-visible:ring-ring/40"
                                                onClick={() => handleSort('duration')}
                                            >
                                                Length
                                                {sortBy === 'duration' ? (
                                                    sortOrder === 'asc' ? <ArrowUp className="h-4 w-4" aria-hidden /> : <ArrowDown className="h-4 w-4" aria-hidden />
                                                ) : (
                                                    <ArrowUpDown className="h-4 w-4 text-muted-foreground" aria-hidden />
                                                )}
                                                <span className="sr-only">, sort by call length</span>
                                            </button>
                                        </TableHead>
                                        <TableHead className="font-semibold">Agent</TableHead>
                                        <TableHead className="font-semibold">Type</TableHead>
                                        {organizationPricing?.price_per_second_usd && (
                                            <TableHead className="font-semibold text-right">Cost (USD)</TableHead>
                                        )}
                                        {showEurCharge && (
                                            <TableHead className="font-semibold text-right">Cost (EUR)</TableHead>
                                        )}
                                        <TableHead className="font-semibold"><span className="sr-only">Recording</span></TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {runs.map((run) => (
                                        <TableRow
                                            key={run.id}
                                            // The call number is a real link stretched over the row.
                                            className="relative hover:bg-brand-dim/40 focus-within:bg-brand-dim/40"
                                        >
                                            <TableCell className="font-mono text-sm">
                                                <Link
                                                    href={runHref(run)}
                                                    aria-label={`Open call #${run.id}`}
                                                    className={ROW_LINK}
                                                >
                                                    #{run.id}
                                                </Link>
                                            </TableCell>
                                            <TableCell className="whitespace-nowrap text-sm">{formatDateTime(run.created_at, effectiveTimezone)}</TableCell>
                                            <TableCell className="whitespace-nowrap font-mono text-sm">
                                                {(run.call_type === 'inbound'
                                                    ? run.caller_number
                                                    : run.called_number) || <span className="font-sans text-ink-3">Not known</span>}
                                            </TableCell>
                                            <TableCell>
                                                {run.disposition ? (
                                                    <Badge variant="secondary">{outcomeLabel(run.disposition)}</Badge>
                                                ) : (
                                                    <span className="text-sm text-ink-3">Not recorded</span>
                                                )}
                                            </TableCell>
                                            <TableCell className="text-right font-mono text-sm tabular-nums">
                                                {formatDuration(run.call_duration_seconds)}
                                            </TableCell>
                                            <TableCell className="text-sm">{run.workflow_name || 'Unknown'}</TableCell>
                                            <TableCell>
                                                <CallTypeCell mode={run.mode} callType={run.call_type} />
                                            </TableCell>
                                            {organizationPricing?.price_per_second_usd && (
                                                <TableCell className="text-right font-mono text-sm">
                                                    {run.charge_usd !== undefined && run.charge_usd !== null
                                                        ? `$${run.charge_usd.toFixed(2)}`
                                                        : '-'
                                                    }
                                                </TableCell>
                                            )}
                                            {showEurCharge && (
                                                <TableCell className="text-right font-mono text-sm">
                                                    {run.charge_eur !== undefined && run.charge_eur !== null
                                                        ? new Intl.NumberFormat('en-IE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 4 }).format(run.charge_eur)
                                                        : '-'
                                                    }
                                                </TableCell>
                                            )}
                                            <TableCell className="relative z-10">
                                                <MediaPreviewButton
                                                    recordingUrl={run.recording_url}
                                                    transcriptUrl={run.transcript_url}
                                                    runId={run.id}
                                                    onOpenPreview={mediaPreview.openPreview}
                                                />
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </div>
                    )}

                    {/* Pagination */}
                    {!isLoadingHistory && !historyFailed && usageHistory && usageHistory.total_pages > 1 && (
                        <nav aria-label="Pages of calls" className="mt-2 flex flex-wrap items-center justify-between gap-3">
                            <p className="text-sm text-ink-3">
                                Page {usageHistory.page} of {usageHistory.total_pages}
                            </p>
                            <div className="flex gap-2">
                                <Button
                                    variant="outline"
                                    className="h-10 sm:h-8"
                                    onClick={() => handlePageChange(currentPage - 1)}
                                    disabled={currentPage === 1}
                                >
                                    <ChevronLeft aria-hidden />
                                    Previous
                                </Button>
                                <Button
                                    variant="outline"
                                    className="h-10 sm:h-8"
                                    onClick={() => handlePageChange(currentPage + 1)}
                                    disabled={currentPage === usageHistory.total_pages}
                                >
                                    Next
                                    <ChevronRight aria-hidden />
                                </Button>
                            </div>
                        </nav>
                    )}
                </section>

                {/* Daily usage and cost: only for organisations on per-second pricing. */}
                {organizationPricing?.price_per_second_usd && (
                    <DailyUsageTable data={dailyUsage} isLoading={isLoadingDaily} />
                )}

                {mediaPreview.dialog}
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
