import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { Cell, Label, Pie, PieChart, Sector } from "recharts";

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

/** Donut chart showing task status breakdown. */
export function TaskStatusChart({ data }: TaskStatusChartProps) {
  const [activeIndex, setActiveIndex] = useState(-1);
  const total = data.completed + data.failed + data.cancelled + data.running + data.pending;
  const chartData = STATUS_KEYS
    .filter((key) => data[key as keyof TaskStats] > 0)
    .map((key) => ({
      name: chartConfig[key].label as string,
      value: data[key as keyof TaskStats],
      fill: `var(--color-${key})`,
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
          <ChartContainer config={chartConfig} className="mx-auto aspect-square max-h-[220px]">
            <PieChart>
              <ChartTooltip content={<ChartTooltipContent />} />
              <Pie
                data={chartData}
                dataKey="value"
                nameKey="name"
                innerRadius={55}
                outerRadius={85}
                strokeWidth={2}
                activeIndex={activeIndex >= 0 ? activeIndex : undefined}
                activeShape={(props: unknown) => {
                  const { outerRadius = 0, ...rest } = props as Record<string, unknown>;
                  return (
                    <Sector
                      {...rest}
                      outerRadius={(outerRadius as number) + 6}
                      style={{
                        filter: "drop-shadow(0 2px 4px rgba(0, 0, 0, 0.15))",
                        animation: "donut-sector-activate 200ms cubic-bezier(0.34, 1.56, 0.64, 1)",
                      }}
                    />
                  );
                }}
                onMouseEnter={(_: Record<string, unknown>, index: number) => setActiveIndex(index)}
                onMouseLeave={() => setActiveIndex(-1)}
              >
                {chartData.map((_, index) => (
                  <Cell
                    key={`cell-${index}`}
                    style={{
                      opacity: activeIndex >= 0 && index !== activeIndex ? 0.45 : 1,
                      transition: "opacity 200ms cubic-bezier(0.22, 1, 0.36, 1)",
                    }}
                  />
                ))}
                <Label
                  content={({ viewBox }) => {
                    if (viewBox && "cx" in viewBox && "cy" in viewBox) {
                      return (
                        <text
                          x={viewBox.cx}
                          y={viewBox.cy}
                          textAnchor="middle"
                          dominantBaseline="middle"
                        >
                          <tspan
                            x={viewBox.cx}
                            y={viewBox.cy}
                            className="fill-foreground text-2xl font-bold"
                          >
                            {total.toLocaleString()}
                          </tspan>
                          <tspan
                            x={viewBox.cx}
                            y={(viewBox.cy || 0) + 20}
                            className="fill-muted-foreground text-xs"
                          >
                            Tasks
                          </tspan>
                        </text>
                      );
                    }
                  }}
                />
              </Pie>
            </PieChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  );
}
