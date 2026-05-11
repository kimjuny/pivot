import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle } from "lucide-react";

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

/** Compose the `--reveal-index` CSS variable for a staged reveal slot. */
function revealStyle(index: number): React.CSSProperties {
  return { "--reveal-index": index } as React.CSSProperties;
}

/** Studio-level dashboard showing KPI cards, charts, and activity. */
function StudioDashboardPage() {
  const [dateRange, setDateRange] = useState("7d");
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
  const [error, setError] = useState<string | null>(null);
  /**
   * Bumped on every successful fetch so that section containers and KPI cards
   * keyed off this value remount, replaying the staged reveal animation and
   * restarting every count-up from zero. This is what makes a 7d/30d switch
   * feel like a fresh page render rather than a silent in-place data swap.
   */
  const [revealToken, setRevealToken] = useState(0);
  /**
   * StrictMode in development runs effects twice on mount, which would
   * otherwise trigger two consecutive fetches and replay the staged-reveal
   * animation twice. This ref records the last range we kicked off so the
   * second invocation of the same effect is a no-op.
   */
  const lastRequestedRange = useRef<string | null>(null);

  const fetchData = useCallback(async (range: string) => {
    setLoading(true);
    setError(null);
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
      setRevealToken((t) => t + 1);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load dashboard data";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (lastRequestedRange.current === dateRange) return;
    lastRequestedRange.current = dateRange;
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

  // While a refresh is in flight and prior data is still showing, dim every
  // panel slightly so the user sees that the dataset is being replaced. Once
  // the fetch resolves the revealToken bump remounts each section fresh.
  const refreshing = loading && overview !== null;
  const sectionClass = refreshing ? "section-stale" : "section-fresh";

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-6 py-8">
      <div
        className="dashboard-reveal flex items-start justify-between"
        style={revealStyle(0)}
      >
        <div>
          <h1 className="text-xl font-semibold text-foreground">
            Dashboard
          </h1>
          <p className="mt-0.5 max-w-3xl text-sm leading-6 text-muted-foreground">
            Platform overview: health, usage, and engagement metrics.
          </p>
        </div>
        <DateRangeSelector value={dateRange} onChange={setDateRange} />
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

      {overview && (
        <>
          <div
            key={`kpi-${revealToken}`}
            className={`dashboard-reveal grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5 ${sectionClass}`}
            style={revealStyle(1)}
          >
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

          <div
            key={`r1-${revealToken}`}
            className={`dashboard-reveal grid grid-cols-1 gap-4 lg:grid-cols-2 ${sectionClass}`}
            style={revealStyle(2)}
          >
            <SessionTrendChart data={trends} />
            {taskStats && <TaskStatusChart data={taskStats} />}
          </div>

          <div
            key={`r2-${revealToken}`}
            className={`dashboard-reveal grid grid-cols-1 gap-4 lg:grid-cols-2 ${sectionClass}`}
            style={revealStyle(3)}
          >
            <TokenUsageChart data={tokenUsage} />
            <AgentPopularityChart data={agentPopularity} />
          </div>

          <div
            key={`r3-${revealToken}`}
            className={`dashboard-reveal grid grid-cols-1 gap-4 lg:grid-cols-2 ${sectionClass}`}
            style={revealStyle(4)}
          >
            <RuntimeHealthCard data={runtimeHealth ?? { active_sandboxes: -1, storage_status: "unknown", failed_tasks_24h: 0 }} />
            <ActivityFeed data={recentActivity} />
          </div>

          <div
            key={`r4-${revealToken}`}
            className={`dashboard-reveal grid grid-cols-1 gap-4 lg:grid-cols-2 ${sectionClass}`}
            style={revealStyle(5)}
          >
            <UserActivityChart data={userActivity} />
            <UserGrowthChart data={userGrowth} />
          </div>
        </>
      )}
    </div>
  );
}

export default StudioDashboardPage;
