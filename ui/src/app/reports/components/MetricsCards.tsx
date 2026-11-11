import { type LucideIcon, Phone, PhoneForwarded } from 'lucide-react';

import { Panel } from '@/components/ui/panel';

interface MetricsCardsProps {
  metrics: {
    total_runs: number;
    xfer_count: number;
  };
  /** True when the report is for today, in the report's timezone. */
  isToday: boolean;
}

function Metric({ icon: Icon, label, value, hint }: { icon: LucideIcon; label: string; value: number; hint: string }) {
  return (
    <Panel className="bg-panel">
      <div className="flex items-start gap-3.5">
        <span className="grid size-10 flex-none place-items-center rounded-lg bg-brand-dim text-brand" aria-hidden>
          <Icon className="size-5" />
        </span>
        <div className="min-w-0">
          <h3 className="text-sm font-medium text-ink-2">{label}</h3>
          <p className="mt-0.5 text-[26px] font-bold leading-tight tabular-nums">{value.toLocaleString('en-IE')}</p>
          <p className="text-[13px] text-ink-3">{hint}</p>
        </div>
      </div>
    </Panel>
  );
}

export function MetricsCards({ metrics, isToday }: MetricsCardsProps) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <Metric
        icon={Phone}
        label="Calls"
        value={metrics.total_runs}
        hint={isToday ? 'All calls so far today' : 'All calls on this day'}
      />
      <Metric
        icon={PhoneForwarded}
        label="Passed to your team"
        value={metrics.xfer_count}
        hint="Calls your agent transferred to a person"
      />
    </div>
  );
}
