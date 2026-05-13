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
  uncached_input: {
    label: "Uncached Input",
    color: "oklch(var(--chart-4))",
  },
  cached_input: {
    label: "Cached Input",
    color: "oklch(var(--chart-3))",
  },
  output: {
    label: "Output",
    color: "oklch(var(--chart-2))",
  },
};

const compactFormatter = new Intl.NumberFormat(undefined, {
  notation: "compact",
  maximumFractionDigits: 1,
});

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
              <YAxis
                tickLine={false}
                axisLine={false}
                width={52}
                allowDecimals={false}
                tickFormatter={(v: number) => compactFormatter.format(v)}
              />
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    formatter={(value, name, item, index) => (
                      <>
                        <div
                          className="h-2.5 w-2.5 shrink-0 rounded-[2px]"
                          style={{ backgroundColor: `var(--color-${name})` }}
                        />
                        {chartConfig[name as keyof typeof chartConfig]?.label ?? String(name)}
                        <div className="ml-auto font-mono font-medium tabular-nums text-foreground">
                          {typeof value === "number" ? value.toLocaleString() : String(value)}
                        </div>
                        {index === 2 && (
                          <div className="mt-1.5 flex basis-full items-center border-t pt-1.5 text-xs font-medium text-foreground">
                            Total
                            <div className="ml-auto font-mono font-medium tabular-nums">
                              {(() => {
                                const p = item.payload as Record<string, unknown>;
                                const total =
                                  Number(p.uncached_input ?? 0) +
                                  Number(p.cached_input ?? 0) +
                                  Number(p.output ?? 0);
                                return total.toLocaleString();
                              })()}
                            </div>
                          </div>
                        )}
                      </>
                    )}
                  />
                }
              />
              <ChartLegend content={<ChartLegendContent />} />
              <Bar dataKey="uncached_input" stackId="tokens" fill="var(--color-uncached_input)" />
              <Bar dataKey="cached_input" stackId="tokens" fill="var(--color-cached_input)" />
              <Bar dataKey="output" stackId="tokens" fill="var(--color-output)" />
            </BarChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  );
}
