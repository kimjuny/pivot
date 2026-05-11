import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ChartContainer,
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
    color: "hsl(var(--chart-2))",
  },
  failed: {
    label: "Failed",
    color: "hsl(var(--chart-destructive))",
  },
  cancelled: {
    label: "Cancelled",
    color: "hsl(var(--chart-5))",
  },
  running: {
    label: "Running",
    color: "hsl(var(--chart-3))",
  },
  pending: {
    label: "Pending",
    color: "hsl(var(--chart-4))",
  },
};

const COLORS = [
  "var(--color-completed)",
  "var(--color-failed)",
  "var(--color-cancelled)",
  "var(--color-running)",
  "var(--color-pending)",
];

/** Donut chart showing task status breakdown. */
export function TaskStatusChart({ data }: TaskStatusChartProps) {
  const total = data.completed + data.failed + data.cancelled + data.running + data.pending;
  const chartData = [
    { name: "Completed", value: data.completed, key: "completed" },
    { name: "Failed", value: data.failed, key: "failed" },
    { name: "Cancelled", value: data.cancelled, key: "cancelled" },
    { name: "Running", value: data.running, key: "running" },
    { name: "Pending", value: data.pending, key: "pending" },
  ].filter((d) => d.value > 0);

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
          <div className="relative">
            <ChartContainer config={chartConfig} className="mx-auto h-[220px] w-full">
              <PieChart>
                <ChartTooltip content={<ChartTooltipContent />} />
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
                  {chartData.map((_, idx) => (
                    <Cell key={chartData[idx].key} fill={COLORS[["completed", "failed", "cancelled", "running", "pending"].indexOf(chartData[idx].key)]} />
                  ))}
                </Pie>
              </PieChart>
            </ChartContainer>
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <span className="text-2xl font-bold">{total.toLocaleString()}</span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
