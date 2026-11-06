import { Phone,PhoneForwarded } from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface MetricsCardsProps {
  metrics: {
    total_runs: number;
    xfer_count: number;
  };
  /** True when the report is for today, in the report's timezone. */
  isToday: boolean;
}

export function MetricsCards({ metrics, isToday }: MetricsCardsProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Calls</CardTitle>
          <Phone className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">{metrics.total_runs.toLocaleString()}</div>
          <p className="text-xs text-muted-foreground">
            {isToday ? 'All calls so far today' : 'All calls on this day'}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Passed to your team</CardTitle>
          <PhoneForwarded className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">{metrics.xfer_count.toLocaleString()}</div>
          <p className="text-xs text-muted-foreground">
            Calls your agent transferred to a person
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
