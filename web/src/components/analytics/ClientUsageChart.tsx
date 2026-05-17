import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { Line, LineChart, XAxis, YAxis } from "recharts";

import type { DailyClientUsage } from "@/utils/api";

export type { DailyClientUsage } from "@/utils/api";

/** Props for the client usage line chart. */
export interface ClientUsageChartProps {
  /** Daily client sessions and distinct users for an agent. */
  data: DailyClientUsage[];
}

const chartConfig: ChartConfig = {
  sessions: {
    label: "Sessions",
    color: "oklch(var(--chart-4))",
  },
  dau: {
    label: "Distinct Users",
    color: "oklch(var(--chart-2))",
  },
};

/** Line chart showing daily client sessions and distinct users for one agent. */
export function ClientUsageChart({ data }: ClientUsageChartProps) {
  const totalSessions = data.reduce((sum, d) => sum + d.sessions, 0);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">Client Usage</CardTitle>
      </CardHeader>
      <CardContent>
        {totalSessions === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No client sessions in this period.
          </p>
        ) : (
          <ChartContainer config={chartConfig} className="h-[250px] w-full">
            <LineChart data={data}>
              <XAxis
                dataKey="date"
                tickLine={false}
                axisLine={false}
                tickFormatter={(v: string) => v.slice(5)}
              />
              <YAxis tickLine={false} axisLine={false} width={40} allowDecimals={false} />
              <ChartTooltip content={<ChartTooltipContent />} />
              <ChartLegend content={<ChartLegendContent />} />
              <Line
                type="monotone"
                dataKey="sessions"
                stroke="var(--color-sessions)"
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="dau"
                stroke="var(--color-dau)"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  );
}
