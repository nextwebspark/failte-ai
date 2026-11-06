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

import { outcomeLabel } from '@/app/usage/callsView';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface DispositionData {
  disposition: string;
  count: number;
  percentage: number;
}

interface DispositionChartProps {
  data: DispositionData[];
}

// Theme colours, so the bars read in light and dark mode alike.
const COLORS = [
  'var(--brand)',
  'var(--sky)',
  'var(--amber)',
  'var(--live)',
  'var(--danger)',
  'var(--ink-3)',
];

export function DispositionChart({ data }: DispositionChartProps) {
  const chartData = data.map((item, index) => ({
    ...item,
    label: outcomeLabel(item.disposition),
    fill: COLORS[index % COLORS.length],
  }));

  const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: Array<{ payload: DispositionData & { label: string; fill: string } }> }) => {
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
        <CardTitle>How calls ended</CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <div className="h-[300px] flex items-center justify-center text-muted-foreground">
            No call outcomes for this day
          </div>
        ) : (
          // Bars run sideways so each outcome's name reads in full, even on a phone.
          <ResponsiveContainer width="100%" height={Math.max(160, chartData.length * 44 + 40)}>
            <BarChart
              data={chartData}
              layout="vertical"
              margin={{ top: 5, right: 24, left: 8, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" horizontal={false} />
              <XAxis
                type="number"
                allowDecimals={false}
                tick={{ fontSize: 12, fill: 'var(--ink-3)' }}
              />
              <YAxis
                type="category"
                dataKey="label"
                width={120}
                interval={0}
                tick={{ fontSize: 12, fill: 'var(--ink-2)' }}
              />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: 'var(--brand-dim)' }} />
              <Bar dataKey="count" radius={[0, 4, 4, 0]} maxBarSize={28}>
                {chartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
