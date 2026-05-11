import { useCallback, useEffect, useState } from "react";

import { AlertCircle } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import {
  getAgentAnalyticsOverview,
  getAgentSessionTrends,
  getAgentTaskStats,
  getAgentTokenUsage,
  getAgentIterationDistribution,
  getAgentTopUsers,
  getAgentReleases,
  getAgentConsumerUsage,
  getAgentChannelActivity,
  type AgentOverview,
  type TaskStats,
  type DailySessionCount,
  type DailyTokenUsage,
  type IterationBucket,
  type AgentUserStats,
  type AgentReleaseItem,
  type DailyConsumerUsage,
  type ChannelActivityItem,
} from "@/utils/api";

import { DateRangeSelector } from "./DateRangeSelector";
import { KpiCard } from "./KpiCard";
import { SessionTrendChart } from "./SessionTrendChart";
import { TaskStatusChart } from "./TaskStatusChart";
import { TokenUsageChart } from "./TokenUsageChart";
import { IterationDistributionChart } from "./IterationDistributionChart";
import { TopUsersTable } from "./TopUsersTable";
import { ReleaseTimeline } from "./ReleaseTimeline";
import { ConsumerUsageChart } from "./ConsumerUsageChart";
import { ChannelActivityCard } from "./ChannelActivityCard";

/** Props for the agent analytics tab. */
export interface AgentAnalyticsTabProps {
  /** The agent ID to fetch analytics for. */
  agentId: number;
}

/** Container component that fetches and renders agent-scoped analytics. */
export function AgentAnalyticsTab({ agentId }: AgentAnalyticsTabProps) {
  const [dateRange, setDateRange] = useState("7d");
  const [overview, setOverview] = useState<AgentOverview | null>(null);
  const [sessionTrends, setSessionTrends] = useState<DailySessionCount[]>([]);
  const [taskStats, setTaskStats] = useState<TaskStats | null>(null);
  const [tokenUsage, setTokenUsage] = useState<DailyTokenUsage[]>([]);
  const [iterations, setIterations] = useState<IterationBucket[]>([]);
  const [topUsers, setTopUsers] = useState<AgentUserStats[]>([]);
  const [releases, setReleases] = useState<AgentReleaseItem[]>([]);
  const [consumerUsage, setConsumerUsage] = useState<DailyConsumerUsage[]>([]);
  const [channelActivity, setChannelActivity] = useState<ChannelActivityItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async (range: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const [
        overviewData,
        trendsData,
        statsData,
        tokenData,
        iterData,
        usersData,
        releasesData,
        consumerData,
        channelData,
      ] = await Promise.all([
        getAgentAnalyticsOverview(agentId, range),
        getAgentSessionTrends(agentId, range),
        getAgentTaskStats(agentId, range),
        getAgentTokenUsage(agentId, range),
        getAgentIterationDistribution(agentId, range),
        getAgentTopUsers(agentId, range),
        getAgentReleases(agentId),
        getAgentConsumerUsage(agentId, range),
        getAgentChannelActivity(agentId, range),
      ]);
      setOverview(overviewData);
      setSessionTrends(trendsData);
      setTaskStats(statsData);
      setTokenUsage(tokenData);
      setIterations(iterData);
      setTopUsers(usersData);
      setReleases(releasesData);
      setConsumerUsage(consumerData);
      setChannelActivity(channelData);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load analytics";
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    void fetchData(dateRange);
  }, [dateRange, fetchData]);

  const handleRangeChange = useCallback((range: string) => {
    setDateRange(range);
  }, []);

  if (isLoading && !overview) {
    return (
      <div className="space-y-6 p-6">
        <div className="flex items-center justify-between">
          <Skeleton className="h-6 w-32" />
          <Skeleton className="h-8 w-48" />
        </div>
        <div className="grid grid-cols-5 gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
        <div className="grid grid-cols-2 gap-4">
          <Skeleton className="h-[280px]" />
          <Skeleton className="h-[280px]" />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6 overflow-y-auto h-full">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Analytics</h2>
        <DateRangeSelector value={dateRange} onChange={handleRangeChange} />
      </div>

      {error && (
        <div className="flex items-center gap-3 rounded-lg border border-destructive/50 bg-destructive/5 px-4 py-3">
          <AlertCircle className="size-4 shrink-0 text-destructive" />
          <p className="text-sm text-destructive flex-1">{error}</p>
          <button
            type="button"
            onClick={() => void fetchData(dateRange)}
            className="text-sm font-medium text-destructive hover:underline"
          >
            Retry
          </button>
        </div>
      )}

      {/* KPI Cards */}
      {overview && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          <KpiCard title="Sessions" value={overview.sessions.toLocaleString()} />
          <KpiCard title="Tasks" value={overview.tasks.toLocaleString()} />
          <KpiCard title="Success Rate" value={`${overview.success_rate}%`} />
          <KpiCard title="Avg Tokens" value={overview.avg_tokens.toLocaleString()} />
          <KpiCard title="Avg Iterations" value={overview.avg_iterations.toString()} />
        </div>
      )}

      {/* Row 1: Session Timeline + Task Status */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <SessionTrendChart data={sessionTrends} />
        {taskStats && <TaskStatusChart data={taskStats} />}
      </div>

      {/* Row 2: Token Usage + Iteration Distribution */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <IterationDistributionChart data={iterations} />
      </div>

      {/* Row 3: Consumer Usage + Channel Activity */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ConsumerUsageChart data={consumerUsage} />
        <ChannelActivityCard data={channelActivity} />
      </div>

      {/* Row 4: Top Users + Release Timeline */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <TopUsersTable data={topUsers} />
        <ReleaseTimeline data={releases} />
      </div>
    </div>
  );
}
