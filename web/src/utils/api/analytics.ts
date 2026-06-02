import { apiRequest } from './core';

export interface StudioOverview {
  agents_total: number;
  agents_new: number;
  sessions_total: number;
  sessions_delta: number;
  users_total: number;
  users_new: number;
  tasks_total: number;
  tasks_daily_avg: number;
  success_rate: number;
  success_rate_delta: number;
}

export interface DailySessionCount {
  date: string;
  client: number;
  studio_test: number;
  automation: number;
}

export interface TaskStats {
  completed: number;
  failed: number;
  cancelled: number;
  running: number;
  pending: number;
}

export interface DailyTokenUsage {
  date: string;
  uncached_input: number;
  cached_input: number;
  output: number;
}

export interface AgentPopularity {
  agent_id: number;
  agent_name: string;
  model_name: string;
  session_count: number;
  task_count: number;
}

export interface RuntimeHealth {
  active_sandboxes: number;
  storage_status: string;
  failed_tasks_24h: number;
}

export interface RecentActivityItem {
  session_id: string;
  title: string;
  agent_name: string;
  model_name: string;
  username: string;
  session_type: string;
  status: string;
  created_at: string;
}

export interface DailyUserActivity {
  date: string;
  dau: number;
  wau: number;
  mau: number;
}

export interface DailyUserGrowth {
  date: string;
  new_users: number;
}

export interface AgentOverview {
  sessions: number;
  tasks: number;
  success_rate: number;
  avg_tokens: number;
  avg_iterations: number;
}

export interface IterationBucket {
  range: string;
  count: number;
}

export interface AgentUserStats {
  user_id: number;
  username: string;
  sessions: number;
  tasks: number;
  total_tokens: number;
  last_active: string;
}

export interface AgentReleaseItem {
  version: number;
  release_note: string | null;
  change_summary: string[];
  published_by: string | null;
  created_at: string;
}

export interface DailyClientUsage {
  date: string;
  sessions: number;
  dau: number;
}

export interface ChannelActivityItem {
  channel_key: string;
  channel_name: string;
  inbound_events: number;
  active_sessions: number;
  last_event_at: string;
}

// Studio dashboard

export const getStudioOverview = async (range: string): Promise<StudioOverview> => {
  return apiRequest(`/analytics/studio/overview?range=${encodeURIComponent(range)}`) as Promise<StudioOverview>;
};

export const getStudioSessionTrends = async (range: string): Promise<DailySessionCount[]> => {
  return apiRequest(`/analytics/studio/session-trends?range=${encodeURIComponent(range)}`) as Promise<DailySessionCount[]>;
};

export const getStudioTaskStats = async (range: string): Promise<TaskStats> => {
  return apiRequest(`/analytics/studio/task-stats?range=${encodeURIComponent(range)}`) as Promise<TaskStats>;
};

export const getStudioTokenUsage = async (range: string): Promise<DailyTokenUsage[]> => {
  return apiRequest(`/analytics/studio/token-usage?range=${encodeURIComponent(range)}`) as Promise<DailyTokenUsage[]>;
};

export const getStudioAgentPopularity = async (range: string, limit: number = 10): Promise<AgentPopularity[]> => {
  return apiRequest(`/analytics/studio/agent-popularity?range=${encodeURIComponent(range)}&limit=${limit}`) as Promise<AgentPopularity[]>;
};

export const getStudioRuntimeHealth = async (): Promise<RuntimeHealth> => {
  return apiRequest('/analytics/studio/runtime-health') as Promise<RuntimeHealth>;
};

export const getStudioRecentActivity = async (limit: number = 5): Promise<RecentActivityItem[]> => {
  return apiRequest(`/analytics/studio/recent-activity?limit=${limit}`) as Promise<RecentActivityItem[]>;
};

export const getStudioUserActivity = async (range: string): Promise<DailyUserActivity[]> => {
  return apiRequest(`/analytics/studio/user-activity?range=${encodeURIComponent(range)}`) as Promise<DailyUserActivity[]>;
};

export const getStudioUserGrowth = async (range: string): Promise<DailyUserGrowth[]> => {
  return apiRequest(`/analytics/studio/user-growth?range=${encodeURIComponent(range)}`) as Promise<DailyUserGrowth[]>;
};

// Agent analytics

export const getAgentAnalyticsOverview = async (agentId: number, range: string): Promise<AgentOverview> => {
  return apiRequest(`/analytics/agents/${agentId}/overview?range=${encodeURIComponent(range)}`) as Promise<AgentOverview>;
};

export const getAgentSessionTrends = async (agentId: number, range: string): Promise<DailySessionCount[]> => {
  return apiRequest(`/analytics/agents/${agentId}/session-trends?range=${encodeURIComponent(range)}`) as Promise<DailySessionCount[]>;
};

export const getAgentTaskStats = async (agentId: number, range: string): Promise<TaskStats> => {
  return apiRequest(`/analytics/agents/${agentId}/task-stats?range=${encodeURIComponent(range)}`) as Promise<TaskStats>;
};

export const getAgentTokenUsage = async (agentId: number, range: string): Promise<DailyTokenUsage[]> => {
  return apiRequest(`/analytics/agents/${agentId}/token-usage?range=${encodeURIComponent(range)}`) as Promise<DailyTokenUsage[]>;
};

export const getAgentIterationDistribution = async (agentId: number, range: string): Promise<IterationBucket[]> => {
  return apiRequest(`/analytics/agents/${agentId}/iteration-distribution?range=${encodeURIComponent(range)}`) as Promise<IterationBucket[]>;
};

export const getAgentTopUsers = async (agentId: number, range: string, limit: number = 20): Promise<AgentUserStats[]> => {
  return apiRequest(`/analytics/agents/${agentId}/top-users?range=${encodeURIComponent(range)}&limit=${limit}`) as Promise<AgentUserStats[]>;
};

export const getAgentReleases = async (agentId: number): Promise<AgentReleaseItem[]> => {
  return apiRequest(`/analytics/agents/${agentId}/releases`) as Promise<AgentReleaseItem[]>;
};

export const getAgentClientUsage = async (agentId: number, range: string): Promise<DailyClientUsage[]> => {
  return apiRequest(`/analytics/agents/${agentId}/client-usage?range=${encodeURIComponent(range)}`) as Promise<DailyClientUsage[]>;
};

export const getAgentChannelActivity = async (agentId: number, range: string): Promise<ChannelActivityItem[]> => {
  return apiRequest(`/analytics/agents/${agentId}/channel-activity?range=${encodeURIComponent(range)}`) as Promise<ChannelActivityItem[]>;
};
