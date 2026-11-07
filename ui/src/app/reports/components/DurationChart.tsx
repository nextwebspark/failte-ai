'use client';

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface DurationData {
  bucket: string;
  range_start: number;
  range_end: number | null;
  count: number;
  percentage: number;
}

interface DurationChartProps {
  data: DurationData[];
}

// One theme colour, deeper for longer calls; reads in light and dark mode.
const OPACITY: Record<string, number> = {
  '0-10': 0.35,
  '10-30': 0.48,
  '30-60': 0.6,
  '60-120': 0.72,
  '120-180': 0.86,
  '>180': 1,
};

export function DurationChart({ data }: DurationChartProps) {
  const chartData = data.map((item) => ({
    ...item,
    label: `${item.bucket}s`,
    opacity: OPACITY[item.bucket] ?? 1,
  }));

  const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: Array<{ payload: DurationData & { label: string; opacity: number } }> }) => {
    if (active && payload && payload[0]) {
      const data = payload[0].payload;
      return (
        <div className="rounded-lg border border-line bg-popover px-3 py-2 text-popover-foreground shadow-md">
          <p className="text-sm font-semibold">{data.label}</p>
          <p className="text-caption tabular-nums text-ink-2">
            {data.count} {data.count === 1 ? 'call' : 'calls'} · {data.percentage}% of the day
          </p>
        </div>
      );
    }
    return null;
  };

  return (
    <Card className="rounded-[14px]">
      <CardHeader className="pb-4">
        <CardTitle className="font-display text-title font-semibold">How long calls lasted</CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <div className="flex h-[300px] items-center justify-center text-sm text-ink-3">
            No duration data available
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart
              data={chartData}
              margin={{ top: 20, right: 8, left: -12, bottom: 4 }}
            >
              <CartesianGrid stroke="var(--line-soft)" vertical={false} />
              <XAxis
                dataKey="label"
                axisLine={{ stroke: 'var(--line)' }}
                tickLine={false}
                tick={{ fontSize: 12, fill: 'var(--ink-3)' }}
              />
              <YAxis
                allowDecimals={false}
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 12, fill: 'var(--ink-3)' }}
              />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: 'var(--brand-dim)' }} />
              <Bar dataKey="count" radius={[4, 4, 0, 0]} maxBarSize={44}>
                {chartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill="var(--brand)" fillOpacity={entry.opacity} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
