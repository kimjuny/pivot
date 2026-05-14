import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { Area, AreaChart, XAxis, YAxis } from "recharts";

/** One day's session counts by type. */
export interface DailySessionCount {
  date: string;
  consumer: number;
  studio_test: number;
}

/** Props for the session activity area chart. */
export interface SessionTrendChartProps {
  /** Daily session counts for the selected range. */
  data: DailySessionCount[];
}

const chartConfig: ChartConfig = {
  consumer: {
    label: "Client",
    color: "oklch(var(--chart-4))",
  },
  studio_test: {
    label: "Studio",
    color: "oklch(var(--chart-2))",
  },
};

/** Stacked area chart showing daily session counts by type. */
export function SessionTrendChart({ data }: SessionTrendChartProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">Session Activity</CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No session data for this period.
          </p>
        ) : (
          <ChartContainer config={chartConfig} className="h-[250px] w-full">
            <AreaChart data={data}>
              <XAxis
                dataKey="date"
                tickLine={false}
                axisLine={false}
                tickFormatter={(v: string) => v.slice(5)}
              />
              <YAxis tickLine={false} axisLine={false} width={40} allowDecimals={false} />
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
                        {index === 1 && (
                          <div className="mt-1.5 flex basis-full items-center border-t pt-1.5 text-xs font-medium text-foreground">
                            Total
                            <div className="ml-auto font-mono font-medium tabular-nums">
                              {(() => {
                                const p = item.payload as Record<string, unknown>;
                                const total =
                                  Number(p.consumer ?? 0) + Number(p.studio_test ?? 0);
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
              <Area
                type="monotone"
                dataKey="consumer"
                stackId="sessions"
                stroke="var(--color-consumer)"
                fill="var(--color-consumer)"
                fillOpacity={0.4}
              />
              <Area
                type="monotone"
                dataKey="studio_test"
                stackId="sessions"
                stroke="var(--color-studio_test)"
                fill="var(--color-studio_test)"
                fillOpacity={0.4}
              />
            </AreaChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  );
}
