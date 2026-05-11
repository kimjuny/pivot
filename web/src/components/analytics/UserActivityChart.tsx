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

import type { DailyUserActivity } from "@/utils/api";

export type { DailyUserActivity } from "@/utils/api";

/** Props for the user activity line chart. */
export interface UserActivityChartProps {
  /** Daily DAU/WAU/MAU data for the selected range. */
  data: DailyUserActivity[];
}

const chartConfig: ChartConfig = {
  dau: {
    label: "DAU",
    color: "hsl(var(--chart-1))",
  },
  wau: {
    label: "WAU",
    color: "hsl(var(--chart-2))",
  },
  mau: {
    label: "MAU",
    color: "hsl(var(--chart-3))",
  },
};

/** Line chart showing DAU/WAU/MAU trend over time. */
export function UserActivityChart({ data }: UserActivityChartProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">User Activity</CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No user activity data for this period.
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
              <YAxis tickLine={false} axisLine={false} width={40} />
              <ChartTooltip content={<ChartTooltipContent />} />
              <ChartLegend content={<ChartLegendContent />} />
              <Line
                type="monotone"
                dataKey="dau"
                stroke="var(--color-dau)"
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="wau"
                stroke="var(--color-wau)"
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="mau"
                stroke="var(--color-mau)"
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
