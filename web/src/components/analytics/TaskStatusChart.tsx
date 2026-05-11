import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { Cell, Pie, PieChart } from "recharts";

import type { TaskStats } from "@/utils/api";

/** Props for the task status donut chart. */
export interface TaskStatusChartProps {
  /** Status counts from the backend. */
  data: TaskStats;
}

const chartConfig: ChartConfig = {
  completed: {
    label: "Completed",
    color: "oklch(var(--chart-4))",
  },
  failed: {
    label: "Failed",
    color: "oklch(var(--destructive))",
  },
  cancelled: {
    label: "Cancelled",
    color: "oklch(var(--chart-5))",
  },
  running: {
    label: "Running",
    color: "oklch(var(--chart-3))",
  },
  pending: {
    label: "Pending",
    color: "oklch(var(--chart-2))",
  },
};

const STATUS_KEYS = ["completed", "failed", "cancelled", "running", "pending"] as const;
const COLORS = STATUS_KEYS.map((key) => `var(--color-${key})`);

/** Donut chart showing task status breakdown. */
export function TaskStatusChart({ data }: TaskStatusChartProps) {
  const total = data.completed + data.failed + data.cancelled + data.running + data.pending;
  const chartData = STATUS_KEYS
    .filter((key) => data[key as keyof TaskStats] > 0)
    .map((key) => ({
      name: chartConfig[key].label as string,
      value: data[key as keyof TaskStats],
      key,
    }));

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">Task Status Breakdown</CardTitle>
      </CardHeader>
      <CardContent>
        {total === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No tasks in this period.
          </p>
        ) : (
          <div>
            <ChartContainer config={chartConfig} className="mx-auto h-[220px] w-full">
              <PieChart>
                <ChartTooltip content={<ChartTooltipContent />} />
                <ChartLegend content={<ChartLegendContent />} />
                <Pie
                  data={chartData}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  innerRadius={55}
                  outerRadius={85}
                  strokeWidth={2}
                >
                  {chartData.map((item) => (
                    <Cell key={item.key} fill={COLORS[STATUS_KEYS.indexOf(item.key)]} />
                  ))}
                </Pie>
              </PieChart>
            </ChartContainer>
            <div className="pointer-events-none -mt-[138px] flex items-center justify-center pb-[138px]">
              <span className="text-2xl font-bold">{total.toLocaleString()}</span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
