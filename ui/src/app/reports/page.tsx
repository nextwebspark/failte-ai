'use client';

import { addDays, format, subDays } from 'date-fns';
import { Calendar, ChevronLeft, ChevronRight, Download, FileWarning, PhoneCall, RefreshCw } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import {
  getDailyReportApiV1OrganizationsReportsDailyGet,
  getDailyRunsDetailApiV1OrganizationsReportsDailyRunsGet,
  getPreferencesApiV1OrganizationsPreferencesGet,
  getWorkflowOptionsApiV1OrganizationsReportsWorkflowsGet
} from '@/client/sdk.gen';
import type { WorkflowRunDetail } from '@/client/types.gen';
import { EmptyState } from '@/components/page-states/EmptyState';
import { Button } from '@/components/ui/button';
import { Calendar as CalendarPicker } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { useAuth } from '@/lib/auth';
import { getLocalTimezone } from '@/lib/dateTime';

import { DispositionChart } from './components/DispositionChart';
import { DurationChart } from './components/DurationChart';
import { MetricsCards } from './components/MetricsCards';
import { CSV_HEADERS, csvCell } from './csv';

const LOAD_FAILED = "We couldn't load this report";

interface WorkflowOption {
  id: number;
  name: string;
}

interface DailyReport {
  date: string;
  timezone: string;
  workflow_id: number | null;
  metrics: {
    total_runs: number;
    xfer_count: number;
  };
  disposition_distribution: Array<{
    disposition: string;
    count: number;
    percentage: number;
  }>;
  call_duration_distribution: Array<{
    bucket: string;
    range_start: number;
    range_end: number | null;
    count: number;
    percentage: number;
  }>;
}

export default function ReportsPage() {
  const [selectedDate, setSelectedDate] = useState<Date>(new Date());
  const [selectedWorkflow, setSelectedWorkflow] = useState<string>('all');
  const [workflows, setWorkflows] = useState<WorkflowOption[]>([]);
  const [report, setReport] = useState<DailyReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // The browser's zone until the workspace's own is known; the report waits for it.
  const [timezone, setTimezone] = useState(() => getLocalTimezone());
  const [timezoneReady, setTimezoneReady] = useState(false);
  // Bumped by "Try again" to fetch the same report again.
  const [attempt, setAttempt] = useState(0);
  const [downloading, setDownloading] = useState(false);
  // Guards against a double click before the disabled state renders.
  const downloadingRef = useRef(false);
  const auth = useAuth();

  // Fetch workflows on mount
  useEffect(() => {
    const fetchWorkflows = async () => {
      if (!auth.isAuthenticated) return;

      try {
        const response = await getWorkflowOptionsApiV1OrganizationsReportsWorkflowsGet({
        });
        if (response.data) {
          setWorkflows(response.data);
        }
      } catch (err) {
        console.error('Failed to fetch workflows:', err);
      }
    };
    fetchWorkflows();
  }, [auth.isAuthenticated]);

  useEffect(() => {
    const fetchPreferences = async () => {
      if (!auth.isAuthenticated) return;

      try {
        const response = await getPreferencesApiV1OrganizationsPreferencesGet();
        if (response.data?.timezone) {
          setTimezone(response.data.timezone);
        }
      } catch (err) {
        console.error('Failed to fetch organization preferences:', err);
      } finally {
        setTimezoneReady(true);
      }
    };
    fetchPreferences();
  }, [auth.isAuthenticated]);

  // Fetch report data when date or workflow changes
  useEffect(() => {
    const fetchReport = async () => {
      if (!auth.isAuthenticated || !timezoneReady) return;

      setLoading(true);
      setError(null);

      try {
        const dateStr = format(selectedDate, 'yyyy-MM-dd');
        const workflowId = selectedWorkflow === 'all' ? undefined : parseInt(selectedWorkflow);

        const response = await getDailyReportApiV1OrganizationsReportsDailyGet({
          query: {
            date: dateStr,
            timezone,
            ...(workflowId && { workflow_id: workflowId })
          },
        });

        if (response.data) {
          setReport(response.data as DailyReport);
        } else {
          setReport(null);
          setError(LOAD_FAILED);
        }
      } catch (err) {
        console.error('Failed to fetch report:', err);
        setReport(null);
        setError(LOAD_FAILED);
      } finally {
        setLoading(false);
      }
    };

    fetchReport();
  }, [selectedDate, selectedWorkflow, timezone, timezoneReady, auth.isAuthenticated, attempt]);

  const handlePreviousDay = () => {
    setSelectedDate(subDays(selectedDate, 1));
  };

  const handleNextDay = () => {
    setSelectedDate(addDays(selectedDate, 1));
  };

  const handleDownloadCSV = async () => {
    if (!auth.isAuthenticated || downloadingRef.current) return;

    downloadingRef.current = true;
    setDownloading(true);
    try {
      const dateStr = format(selectedDate, 'yyyy-MM-dd');
      const workflowId = selectedWorkflow === 'all' ? undefined : parseInt(selectedWorkflow);

      // Fetch detailed runs data
      const response = await getDailyRunsDetailApiV1OrganizationsReportsDailyRunsGet({
        query: {
          date: dateStr,
          timezone,
          ...(workflowId && { workflow_id: workflowId })
        },
      });

      if (response.error) {
        toast.error("Couldn't download the calls. Please try again.");
        return;
      }
      if (response.data && response.data.length > 0) {
        const rows = response.data.map((run: WorkflowRunDetail) => {
          const url = `${window.location.origin}/workflow/${run.workflow_id}/run/${run.run_id}`;
          return [
            run.phone_number || '',
            run.disposition || '',
            run.duration_seconds.toString(),
            url
          ];
        });

        // Create CSV content
        const csvContent = [
          CSV_HEADERS.map(csvCell).join(','),
          ...rows.map((row: string[]) => row.map(csvCell).join(','))
        ].join('\n');

        // Create blob and download
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement('a');
        const url = URL.createObjectURL(blob);

        const workflowName = selectedWorkflow === 'all'
          ? 'all_agents'
          : workflows.find(w => w.id.toString() === selectedWorkflow)?.name?.replace(/\s+/g, '_') || 'agent';

        link.setAttribute('href', url);
        link.setAttribute('download', `calls_${dateStr}_${workflowName}.csv`);
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        toast.success('Your calls are downloading.');
      } else {
        toast.info('There are no calls to download for this day.');
      }
    } catch (err) {
      console.error('Failed to download CSV:', err);
      toast.error("Couldn't download the calls. Please try again.");
    } finally {
      downloadingRef.current = false;
      setDownloading(false);
    }
  };

  const isToday = format(selectedDate, 'yyyy-MM-dd') === format(new Date(), 'yyyy-MM-dd');

  const dayLong = format(selectedDate, 'EEEE d MMMM yyyy');
  const agentName = selectedWorkflow === 'all'
    ? null
    : workflows.find((w) => w.id.toString() === selectedWorkflow)?.name ?? null;
  const hasCalls = Boolean(report && report.metrics.total_runs > 0);

  return (
    <div className="page-body">
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        {/* What this page is, and the two choices: which day, which agent. */}
        <section
          aria-labelledby="report-day"
          className="rounded-xl border border-line bg-gradient-to-br from-brand-dim via-panel to-panel px-5 py-5 sm:px-6"
        >
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <h2 id="report-day" className="text-[22px] font-bold tracking-tight">
                {isToday ? `Today, ${format(selectedDate, 'EEE d MMM')}` : format(selectedDate, 'EEEE d MMMM')}
              </h2>
              <p className="mt-1 max-w-xl text-[15px] text-ink-2">
                A one-page summary of a day: how many calls came in, how they ended and how long they lasted.
                You can download the day&apos;s calls as a spreadsheet.
              </p>
            </div>

            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <Select value={selectedWorkflow} onValueChange={setSelectedWorkflow}>
                <SelectTrigger className="w-full bg-panel data-[size=default]:h-10 sm:w-[200px]" aria-label="Agent">
                  <SelectValue placeholder="All agents" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All agents</SelectItem>
                  {workflows.map((workflow) => (
                    <SelectItem key={workflow.id} value={workflow.id.toString()}>
                      {workflow.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="icon"
                  className="size-10 flex-none bg-panel"
                  onClick={handlePreviousDay}
                  aria-label="Previous day"
                >
                  <ChevronLeft aria-hidden />
                </Button>

                <Popover>
                  <PopoverTrigger asChild>
                    <Button
                      variant="outline"
                      className="h-10 flex-1 bg-panel sm:w-[180px] sm:flex-none"
                      aria-label={`Pick a day, showing ${dayLong}`}
                    >
                      <Calendar aria-hidden />
                      {format(selectedDate, 'EEE d MMM yyyy')}
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-auto p-0">
                    <CalendarPicker
                      mode="single"
                      selected={selectedDate}
                      onSelect={(date) => date && setSelectedDate(date)}
                      disabled={(date) => date > new Date()}
                    />
                  </PopoverContent>
                </Popover>

                <Button
                  variant="outline"
                  size="icon"
                  className="size-10 flex-none bg-panel"
                  onClick={handleNextDay}
                  disabled={isToday}
                  aria-label="Next day"
                >
                  <ChevronRight aria-hidden />
                </Button>
              </div>
            </div>
          </div>

          <div className="mt-4 flex flex-col gap-3 border-t border-line-soft pt-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-[13px] text-ink-3">
              Times in {timezone.replace(/_/g, ' ')} time
              {agentName && <> · {agentName} only</>}
            </p>
            {!loading && hasCalls && (
              <Button
                variant="outline"
                className="h-10 bg-panel sm:h-8"
                onClick={handleDownloadCSV}
                disabled={downloading}
              >
                <Download aria-hidden />
                {downloading ? 'Preparing…' : 'Download calls (CSV)'}
              </Button>
            )}
          </div>
        </section>

        {loading ? (
          <div className="flex flex-col gap-6" aria-busy="true" aria-label="Loading the report">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <Skeleton className="h-[104px] rounded-lg" />
              <Skeleton className="h-[104px] rounded-lg" />
            </div>
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <Skeleton className="h-[360px] rounded-lg" />
              <Skeleton className="h-[360px] rounded-lg" />
            </div>
          </div>
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
        ) : report && hasCalls ? (
          <>
            <MetricsCards metrics={report.metrics} isToday={isToday} />
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <DispositionChart data={report.disposition_distribution} />
              <DurationChart data={report.call_duration_distribution} />
            </div>
          </>
        ) : report ? (
          <EmptyState
            icon={PhoneCall}
            title={`No calls on ${format(selectedDate, 'EEEE d MMMM')}${agentName ? ` for ${agentName}` : ''}`}
            action={
              <Button variant="outline" className="h-10 sm:h-9" onClick={handlePreviousDay}>
                <ChevronLeft aria-hidden />
                See the day before
              </Button>
            }
          >
            {isToday
              ? 'Calls your agent takes today will show up here as they happen.'
              : 'Pick another day with the arrows or the calendar above.'}
          </EmptyState>
        ) : null}
      </div>
    </div>
  );
}
