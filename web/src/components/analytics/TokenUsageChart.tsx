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

import type { DailyTokenUsage } from "@/utils/api";

export type { DailyTokenUsage } from "@/utils/api";

/** Props for the token usage stacked bar chart. */
export interface TokenUsageChartProps {
  /** Daily token usage data for the selected range. */
  data: DailyTokenUsage[];
}

const chartConfig: ChartConfig = {
  prompt: {
    label: "Prompt",
    color: "oklch(var(--chart-4))",
  },
  completion: {
    label: "Completion",
    color: "oklch(var(--chart-3))",
  },
  cached: {
    label: "Cached",
    color: "oklch(var(--chart-2))",
  },
};

/** Stacked bar chart showing daily token usage broken down by type. */
export function TokenUsageChart({ data }: TokenUsageChartProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">Token Usage Trend</CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No token usage data for this period.
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
              <YAxis tickLine={false} axisLine={false} width={50} allowDecimals={false} />
              <ChartTooltip content={<ChartTooltipContent />} />
              <ChartLegend content={<ChartLegendContent />} />
              <Bar
                dataKey="prompt"
                stackId="tokens"
                fill="var(--color-prompt)"
              />
              <Bar
                dataKey="completion"
                stackId="tokens"
                fill="var(--color-completion)"
              />
              <Bar
                dataKey="cached"
                stackId="tokens"
                fill="var(--color-cached)"
              />
            </BarChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  );
}
