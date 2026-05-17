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

/** Props for the agent popularity horizontal bar chart. */
export interface AgentPopularityChartProps {
  /** Top agents ranked by client session count. */
  data: AgentPopularity[];
}

const chartConfig: ChartConfig = {
  session_count: {
    label: "Sessions",
    color: "oklch(var(--chart-4))",
  },
};

/** Pad agent data to always show 5 slots so bars don't fill the chart. */
function padToSlots(data: AgentPopularity[], slots: number): AgentPopularity[] {
  const padded = [...data];
  while (padded.length < slots) {
    padded.push({
      agent_id: -(padded.length),
      agent_name: "",
      model_name: "",
      session_count: 0,
    });
  }
  return padded;
}

/** Create a custom tick component with access to agent data for icons. */
function createAgentTick(agents: AgentPopularity[]) {
  function AgentTick(props: { x: number; y: number; payload?: { value: string } }) {
    const { x, y, payload } = props;
    if (!payload?.value) return <g />;

    const agent = agents.find((a) => a.agent_name === payload.value);

    return (
      <g transform={`translate(${x},${y})`}>
        <foreignObject x={-96} y={-9} width={92} height={18} style={{ overflow: "hidden" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "4px", overflow: "hidden" }}>
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
            <span style={{ fontSize: 12, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {payload.value}
            </span>
          </div>
        </foreignObject>
      </g>
    );
  }
  return AgentTick;
}

/** Horizontal bar chart showing top agents by client session count. */
export function AgentPopularityChart({ data }: AgentPopularityChartProps) {
  const displayData = padToSlots(data, 5);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">Agent Popularity</CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No client sessions in this period.
          </p>
        ) : (
          <ChartContainer config={chartConfig} className="h-[250px] w-full">
            <BarChart data={displayData} layout="vertical">
              <XAxis type="number" tickLine={false} axisLine={false} allowDecimals={false} />
              <YAxis
                type="category"
                dataKey="agent_name"
                tickLine={false}
                axisLine={false}
                width={100}
                tick={createAgentTick(data)}
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
