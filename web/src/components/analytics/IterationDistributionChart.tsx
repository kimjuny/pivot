import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { Bar, BarChart, XAxis, YAxis } from "recharts";

import type { IterationBucket } from "@/utils/api";

export type { IterationBucket } from "@/utils/api";

/** Props for the iteration distribution bar chart. */
export interface IterationDistributionChartProps {
  /** Task counts grouped by iteration ranges. */
  data: IterationBucket[];
}

const chartConfig: ChartConfig = {
  count: {
    label: "Tasks",
    color: "oklch(var(--chart-4))",
  },
};

/** Bar chart showing task counts by iteration range. */
export function IterationDistributionChart({ data }: IterationDistributionChartProps) {
  const total = data.reduce((sum, item) => sum + item.count, 0);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">Iteration Distribution</CardTitle>
      </CardHeader>
      <CardContent>
        {total === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No task data in this period.
          </p>
        ) : (
          <ChartContainer config={chartConfig} className="h-[250px] w-full">
            <BarChart data={data}>
              <XAxis
                dataKey="range"
                tickLine={false}
                axisLine={false}
              />
              <YAxis tickLine={false} axisLine={false} width={40} allowDecimals={false} />
              <ChartTooltip content={<ChartTooltipContent />} />
              <ChartLegend content={<ChartLegendContent />} />
              <Bar
                dataKey="count"
                fill="var(--color-count)"
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  );
}
