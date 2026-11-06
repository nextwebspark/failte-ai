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
        <div className="rounded-lg border border-line bg-popover p-3 text-popover-foreground shadow-lg">
          <p className="font-semibold">{data.label}</p>
          <p className="text-sm">{data.count} {data.count === 1 ? 'call' : 'calls'}</p>
          <p className="text-sm">{data.percentage}% of total</p>
        </div>
      );
    }
    return null;
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>How long calls lasted</CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <div className="h-[300px] flex items-center justify-center text-muted-foreground">
            No duration data available
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart
              data={chartData}
              margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 12, fill: 'var(--ink-3)' }}
              />
              <YAxis
                tick={{ fontSize: 12, fill: 'var(--ink-3)' }}
              />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: 'var(--brand-dim)' }} />
              <Bar dataKey="count" radius={[4, 4, 0, 0]}>
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
