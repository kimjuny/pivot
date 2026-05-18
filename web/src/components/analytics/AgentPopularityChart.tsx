import { useMemo, useState } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { LLMBrandAvatar } from "@/components/LLMBrandAvatar";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { Bot } from "lucide-react";
import { Bar, BarChart, XAxis, YAxis } from "recharts";

import type { AgentPopularity } from "@/utils/api";

export type { AgentPopularity } from "@/utils/api";

/** Dimension toggle for the popularity ranking. */
type PopularityDimension = "sessions" | "tasks";

/** Props for the agent popularity horizontal bar chart. */
export interface AgentPopularityChartProps {
  /** Top agents with session and task counts. */
  data: AgentPopularity[];
}

const chartConfig: ChartConfig = {
  sessions: {
    label: "Sessions",
    color: "oklch(var(--chart-4))",
  },
  tasks: {
    label: "Tasks",
    color: "oklch(var(--chart-4))",
  },
};

/** Pad agent data to always show 5 slots so bars don't fill the chart. */
function padToSlots(
  data: AgentPopularity[],
  dimension: PopularityDimension,
  slots: number,
): (AgentPopularity & { metric: number })[] {
  const keyed = data.map((d) => ({
    ...d,
    metric: dimension === "sessions" ? d.session_count : d.task_count,
  }));
  while (keyed.length < slots) {
    keyed.push({
      agent_id: -(keyed.length),
      agent_name: "",
      model_name: "",
      session_count: 0,
      task_count: 0,
      metric: 0,
    });
  }
  return keyed;
}

/** Create a custom tick component with access to agent data for icons. */
function createAgentTick(agents: AgentPopularity[]) {
  function AgentTick(props: {
    x: number;
    y: number;
    payload?: { value: string };
  }) {
    const { x, y, payload } = props;
    if (!payload?.value) return <g />;

    const agent = agents.find((a) => a.agent_name === payload.value);

    return (
      <g transform={`translate(${x},${y})`}>
        <foreignObject
          x={-96}
          y={-9}
          width={92}
          height={18}
          style={{ overflow: "hidden" }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "4px",
              overflow: "hidden",
            }}
          >
            {agent ? (
              <LLMBrandAvatar
                model={agent.model_name}
                containerClassName="w-4 h-4 rounded flex items-center justify-center flex-shrink-0 bg-primary/10"
                imageClassName="w-3 h-3"
                fallback={<Bot className="w-3 h-3 text-primary" />}
              />
            ) : (
              <Bot className="w-3 h-3 text-muted-foreground flex-shrink-0" />
            )}
            <span
              style={{
                fontSize: 12,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {payload.value}
            </span>
          </div>
        </foreignObject>
      </g>
    );
  }
  return AgentTick;
}

/** Horizontal bar chart showing top agents ranked by sessions or tasks. */
export function AgentPopularityChart({ data }: AgentPopularityChartProps) {
  const [dimension, setDimension] = useState<PopularityDimension>("sessions");

  const sorted = useMemo(() => {
    const key = dimension === "sessions" ? "session_count" : "task_count";
    return [...data].sort((a, b) => b[key] - a[key]);
  }, [data, dimension]);

  const displayData = padToSlots(sorted, dimension, 5);
  const dataKey = dimension === "sessions" ? "session_count" : "task_count";
  const hasData = data.some(
    dimension === "sessions"
      ? (d) => d.session_count > 0
      : (d) => d.task_count > 0,
  );

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">Agent Popularity</CardTitle>
          <div className="flex rounded-md border bg-muted/50 p-0.5">
            {(["sessions", "tasks"] as const).map((dim) => (
              <button
                key={dim}
                type="button"
                onClick={() => setDimension(dim)}
                className={`rounded-sm px-2.5 py-0.5 text-xs font-medium transition-colors ${
                  dimension === dim
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {dim === "sessions" ? "Sessions" : "Tasks"}
              </button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {hasData ? (
          <ChartContainer config={chartConfig} className="h-[250px] w-full">
            <BarChart data={displayData} layout="vertical">
              <XAxis
                type="number"
                tickLine={false}
                axisLine={false}
                allowDecimals={false}
              />
              <YAxis
                type="category"
                dataKey="agent_name"
                tickLine={false}
                axisLine={false}
                width={100}
                tick={createAgentTick(sorted)}
              />
              <ChartTooltip content={<ChartTooltipContent />} />
              <Bar
                dataKey={dataKey}
                fill="var(--color-sessions)"
                radius={[0, 4, 4, 0]}
              />
            </BarChart>
          </ChartContainer>
        ) : (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No {dimension === "sessions" ? "client sessions" : "tasks"} in this
            period.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
