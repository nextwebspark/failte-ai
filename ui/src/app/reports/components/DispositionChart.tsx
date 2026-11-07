'use client';

import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
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

/**
 * One series (calls per outcome), so one hue: the outcome's name on the axis
 * carries its identity. Colouring bars by their rank painted the same outcome
 * a different colour on different days. The count sits at each bar's end.
 */
export function DispositionChart({ data }: DispositionChartProps) {
  const chartData = data.map((item) => ({
    ...item,
    label: outcomeLabel(item.disposition),
  }));
  // Room for the longest outcome name at 13px, so a phone keeps its bars.
  const labelWidth = Math.min(160, Math.max(72, Math.max(0, ...chartData.map((d) => d.label.length)) * 7.4 + 8));

  const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: Array<{ payload: DispositionData & { label: string } }> }) => {
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
        <CardTitle className="font-display text-title font-semibold">How calls ended</CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <div className="flex h-[300px] items-center justify-center text-sm text-ink-3">
            No call outcomes for this day
          </div>
        ) : (
          // Bars run sideways so each outcome's name reads in full, even on a phone.
          <ResponsiveContainer width="100%" height={Math.max(180, chartData.length * 48 + 40)}>
            <BarChart
              data={chartData}
              layout="vertical"
              margin={{ top: 4, right: 40, left: 8, bottom: 4 }}
            >
              <CartesianGrid stroke="var(--line-soft)" horizontal={false} />
              <XAxis
                type="number"
                allowDecimals={false}
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 12, fill: 'var(--ink-3)' }}
              />
              <YAxis
                type="category"
                dataKey="label"
                width={labelWidth}
                interval={0}
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 13, fill: 'var(--ink-2)' }}
              />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: 'var(--brand-dim)' }} />
              <Bar dataKey="count" fill="var(--brand)" radius={[0, 4, 4, 0]} maxBarSize={20}>
                <LabelList
                  dataKey="count"
                  position="right"
                  style={{ fontSize: 13, fontWeight: 600, fill: 'var(--ink)' }}
                />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
