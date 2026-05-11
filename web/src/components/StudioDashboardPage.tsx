import { useCallback, useEffect, useState } from "react";

import { ActivityFeed } from "@/components/analytics/ActivityFeed";
import { AgentPopularityChart } from "@/components/analytics/AgentPopularityChart";
import { DateRangeSelector } from "@/components/analytics/DateRangeSelector";
import { KpiCard, type KpiTrend } from "@/components/analytics/KpiCard";
import { RuntimeHealthCard } from "@/components/analytics/RuntimeHealthCard";
import {
  SessionTrendChart,
  type DailySessionCount,
} from "@/components/analytics/SessionTrendChart";
import { TaskStatusChart } from "@/components/analytics/TaskStatusChart";
import { TokenUsageChart } from "@/components/analytics/TokenUsageChart";
import { UserActivityChart } from "@/components/analytics/UserActivityChart";
import { UserGrowthChart } from "@/components/analytics/UserGrowthChart";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getStudioAgentPopularity,
  getStudioOverview,
  getStudioRecentActivity,
  getStudioRuntimeHealth,
  getStudioSessionTrends,
  getStudioTaskStats,
  getStudioTokenUsage,
  getStudioUserActivity,
  getStudioUserGrowth,
  type AgentPopularity,
  type DailyTokenUsage,
  type DailyUserActivity,
  type DailyUserGrowth,
  type RecentActivityItem,
  type RuntimeHealth,
  type StudioOverview,
  type TaskStats,
} from "@/utils/api";

/** Loading fallback for a chart card area. */
function ChartSkeleton() {
  return (
    <div className="space-y-2 rounded-lg border p-4">
      <Skeleton className="h-3 w-28" />
      <Skeleton className="h-[250px] w-full" />
    </div>
  );
}

/** Studio-level dashboard showing KPI cards, charts, and activity. */
function StudioDashboardPage() {
  const [dateRange, setDateRange] = useState("30d");
  const [overview, setOverview] = useState<StudioOverview | null>(null);
  const [trends, setTrends] = useState<DailySessionCount[]>([]);
  const [taskStats, setTaskStats] = useState<TaskStats | null>(null);
  const [tokenUsage, setTokenUsage] = useState<DailyTokenUsage[]>([]);
  const [agentPopularity, setAgentPopularity] = useState<AgentPopularity[]>([]);
  const [runtimeHealth, setRuntimeHealth] = useState<RuntimeHealth | null>(null);
  const [recentActivity, setRecentActivity] = useState<RecentActivityItem[]>([]);
  const [userActivity, setUserActivity] = useState<DailyUserActivity[]>([]);
  const [userGrowth, setUserGrowth] = useState<DailyUserGrowth[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async (range: string) => {
    setLoading(true);
    try {
      const [
        ov,
        tr,
        ts,
        tu,
        ap,
        rh,
        ra,
        ua,
        ug,
      ] = await Promise.all([
        getStudioOverview(range),
        getStudioSessionTrends(range),
        getStudioTaskStats(range),
        getStudioTokenUsage(range),
        getStudioAgentPopularity(range),
        getStudioRuntimeHealth(),
        getStudioRecentActivity(),
        getStudioUserActivity(range),
        getStudioUserGrowth(range),
      ]);
      setOverview(ov);
      setTrends(tr);
      setTaskStats(ts);
      setTokenUsage(tu);
      setAgentPopularity(ap);
      setRuntimeHealth(rh);
      setRecentActivity(ra);
      setUserActivity(ua);
      setUserGrowth(ug);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchData(dateRange);
  }, [dateRange, fetchData]);

  function buildTrend(current: number, delta: number): KpiTrend | undefined {
    if (delta === 0) return undefined;
    const prev = current - delta;
    if (prev === 0) return undefined;
    const pct = Math.round((delta / prev) * 100);
    return {
      value: pct,
      direction: delta > 0 ? "up" : "down",
    };
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-6 py-8">
      <div className="flex items-start justify-between">
        <div>
          <Badge variant="outline" className="w-fit">
            Studio
          </Badge>
          <h1 className="mt-3 text-xl font-semibold text-foreground">
            Dashboard
          </h1>
          <p className="mt-0.5 max-w-3xl text-sm leading-6 text-muted-foreground">
            Platform overview: health, usage, and engagement metrics.
          </p>
        </div>
        <DateRangeSelector value={dateRange} onChange={setDateRange} />
      </div>

      {loading || !overview ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="space-y-2 rounded-lg border p-4">
              <Skeleton className="h-3 w-16" />
              <Skeleton className="h-7 w-20" />
              <Skeleton className="h-3 w-24" />
            </div>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          <KpiCard
            title="Agents"
            value={overview.agents_total}
            subtitle={
              overview.agents_new > 0
                ? `+${overview.agents_new} new`
                : undefined
            }
          />
          <KpiCard
            title="Sessions"
            value={overview.sessions_total.toLocaleString()}
            subtitle={`${overview.sessions_delta >= 0 ? "+" : ""}${overview.sessions_delta} vs prev`}
            trend={buildTrend(
              overview.sessions_total,
              overview.sessions_delta,
            )}
          />
          <KpiCard
            title="Users"
            value={overview.users_total}
            subtitle={
              overview.users_new > 0
                ? `+${overview.users_new} new`
                : undefined
            }
          />
          <KpiCard
            title="Tasks"
            value={overview.tasks_total.toLocaleString()}
            subtitle={`${overview.tasks_daily_avg}/day avg`}
          />
          <KpiCard
            title="Success Rate"
            value={`${overview.success_rate}%`}
            trend={
              overview.success_rate_delta !== 0
                ? {
                    value: Math.abs(
                      Math.round(overview.success_rate_delta * 10) / 10,
                    ),
                    direction:
                      overview.success_rate_delta > 0 ? "up" : "down",
                  }
                : undefined
            }
          />
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {loading ? (
          <>
            <ChartSkeleton />
            <ChartSkeleton />
          </>
        ) : (
          <>
            <SessionTrendChart data={trends} />
            {taskStats && <TaskStatusChart data={taskStats} />}
          </>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {loading ? (
          <>
            <ChartSkeleton />
            <ChartSkeleton />
          </>
        ) : (
          <>
            <TokenUsageChart data={tokenUsage} />
            <AgentPopularityChart data={agentPopularity} />
          </>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {loading || !runtimeHealth ? (
          <>
            <ChartSkeleton />
            <ChartSkeleton />
          </>
        ) : (
          <>
            <RuntimeHealthCard data={runtimeHealth} />
            <ActivityFeed data={recentActivity} />
          </>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {loading ? (
          <>
            <ChartSkeleton />
            <ChartSkeleton />
          </>
        ) : (
          <>
            <UserActivityChart data={userActivity} />
            <UserGrowthChart data={userGrowth} />
          </>
        )}
      </div>
    </div>
  );
}

export default StudioDashboardPage;
