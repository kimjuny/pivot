import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { Bar, BarChart, XAxis, YAxis } from "recharts";

import type { AgentPopularity } from "@/utils/api";

export type { AgentPopularity } from "@/utils/api";

/** Props for the agent popularity horizontal bar chart. */
export interface AgentPopularityChartProps {
  /** Top agents ranked by consumer session count. */
  data: AgentPopularity[];
}

const chartConfig: ChartConfig = {
  session_count: {
    label: "Sessions",
    color: "hsl(var(--chart-1))",
  },
};

/** Horizontal bar chart showing top agents by consumer session count. */
export function AgentPopularityChart({ data }: AgentPopularityChartProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">Agent Popularity</CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No consumer sessions in this period.
          </p>
        ) : (
          <ChartContainer config={chartConfig} className="h-[250px] w-full">
            <BarChart data={data} layout="vertical">
              <XAxis type="number" tickLine={false} axisLine={false} />
              <YAxis
                type="category"
                dataKey="agent_name"
                tickLine={false}
                axisLine={false}
                width={100}
              />
              <ChartTooltip content={<ChartTooltipContent />} />
              <Bar
                dataKey="session_count"
                fill="var(--color-session_count)"
                radius={[0, 4, 4, 0]}
              />
            </BarChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  );
}
