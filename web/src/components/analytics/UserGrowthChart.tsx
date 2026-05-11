import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { Bar, BarChart, XAxis, YAxis } from "recharts";

import type { DailyUserGrowth } from "@/utils/api";

export type { DailyUserGrowth } from "@/utils/api";

/** Props for the user growth bar chart. */
export interface UserGrowthChartProps {
  /** Daily new user registration counts. */
  data: DailyUserGrowth[];
}

const chartConfig: ChartConfig = {
  new_users: {
    label: "New Users",
    color: "hsl(var(--chart-1))",
  },
};

/** Bar chart showing daily new user registrations. */
export function UserGrowthChart({ data }: UserGrowthChartProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">New User Trend</CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No new user data for this period.
          </p>
        ) : (
          <ChartContainer config={chartConfig} className="h-[250px] w-full">
            <BarChart data={data}>
              <XAxis
                dataKey="date"
                tickLine={false}
                axisLine={false}
                tickFormatter={(v: string) => v.slice(5)}
              />
              <YAxis tickLine={false} axisLine={false} width={40} />
              <ChartTooltip content={<ChartTooltipContent />} />
              <Bar
                dataKey="new_users"
                fill="var(--color-new_users)"
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  );
}
