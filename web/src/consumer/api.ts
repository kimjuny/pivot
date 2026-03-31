import type { Agent } from "@/types";
import type { ChatSessionType } from "@/utils/agentTestSnapshot";
import { apiRequest } from "@/utils/api";

/**
 * Lightweight Consumer session summary used by the recent sessions surfaces.
 */
export interface ConsumerSessionListItem {
  session_id: string;
  agent_id: number;
  type: ChatSessionType;
  agent_name: string;
  agent_description: string | null;
  release_id?: number | null;
  status: string;
  runtime_status?: "idle" | "running" | "waiting_input";
  title: string | null;
  is_pinned: boolean;
  created_at: string;
  updated_at: string;
}

/**
 * Recent-session response for the Consumer product shell.
 */
export interface ConsumerSessionListResponse {
  sessions: ConsumerSessionListItem[];
  total: number;
}

/**
 * Fetch all agents currently visible in the Consumer product.
 *
 * @returns Promise resolving to published serving agents only.
 */
export async function getConsumerAgents(): Promise<Agent[]> {
  return apiRequest("/consumer/agents") as Promise<Agent[]>;
}

/**
 * Fetch one Consumer-visible agent by identifier.
 *
 * @param agentId - Stable agent identifier.
 * @returns Promise resolving to the published serving agent.
 */
export async function getConsumerAgentById(agentId: number): Promise<Agent> {
  return apiRequest(`/consumer/agents/${agentId}`) as Promise<Agent>;
}

/**
 * Fetch recent sessions that still belong to Consumer-visible agents.
 *
 * @param limit - Maximum number of sessions to return.
 * @returns Promise resolving to recent Consumer sessions.
 */
export async function getConsumerSessions(
  limit: number = 20,
): Promise<ConsumerSessionListResponse> {
  return apiRequest(`/consumer/sessions?limit=${limit}`) as Promise<ConsumerSessionListResponse>;
}
