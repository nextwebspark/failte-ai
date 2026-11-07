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

function Metric({
  icon: Icon,
  tone,
  label,
  value,
  hint,
}: {
  icon: LucideIcon;
  /** The icon chip's colours, as on Home's tiles. */
  tone: string;
  label: string;
  value: number;
  hint: string;
}) {
  return (
    <Panel className="rounded-[14px] bg-panel px-5 py-[18px]">
      <div className="flex items-start justify-between gap-3">
        <h3 className="pt-0.5 text-body font-medium text-ink-2">{label}</h3>
        <span className={`grid size-9 flex-none place-items-center rounded-[10px] ${tone}`} aria-hidden>
          <Icon className="size-[18px]" />
        </span>
      </div>
      <p className="mt-2 font-display text-kpi font-semibold leading-none tracking-[-0.02em] tabular-nums">
        {value.toLocaleString('en-IE')}
      </p>
      <p className="mt-2.5 text-caption text-ink-2">{hint}</p>
    </Panel>
  );
}

export function MetricsCards({ metrics, isToday }: MetricsCardsProps) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <Metric
        icon={Phone}
        tone="bg-sky-dim text-sky"
        label="Calls"
        value={metrics.total_runs}
        hint={isToday ? 'All calls so far today' : 'All calls on this day'}
      />
      <Metric
        icon={PhoneForwarded}
        tone="bg-amber-dim text-amber"
        label="Passed to your team"
        value={metrics.xfer_count}
        hint="Calls your agent transferred to a person"
      />
    </div>
  );
}
