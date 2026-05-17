import type { Agent } from "@/types";
import type { ChatSessionType } from "@/utils/agentTestSnapshot";
import { apiRequest } from "@/utils/api";

/**
 * Lightweight Client session summary used by the recent sessions surfaces.
 */
export interface ClientSessionListItem {
  session_id: string;
  agent_id: number;
  type: ChatSessionType;
  agent_name: string;
  agent_description: string | null;
  release_id?: number | null;
  latest_release_id?: number | null;
  is_stale?: boolean;
  migrated_to_session_id?: string | null;
  status: string;
  runtime_status?: "idle" | "running" | "waiting_input";
  title: string | null;
  is_pinned: boolean;
  created_at: string;
  updated_at: string;
}

/**
 * Recent-session response for the Client product shell.
 */
export interface ClientSessionListResponse {
  sessions: ClientSessionListItem[];
  total: number;
}

/**
 * Fetch all agents currently visible in the Client product.
 *
 * @returns Promise resolving to published serving agents only.
 */
export async function getClientAgents(): Promise<Agent[]> {
  return apiRequest("/client/agents") as Promise<Agent[]>;
}

/**
 * Fetch one Client-visible agent by identifier.
 *
 * @param agentId - Stable agent identifier.
 * @returns Promise resolving to the published serving agent.
 */
export async function getClientAgentById(agentId: number): Promise<Agent> {
  return apiRequest(`/client/agents/${agentId}`) as Promise<Agent>;
}

/**
 * Fetch recent sessions that still belong to Client-visible agents.
 *
 * @param limit - Maximum number of sessions to return.
 * @returns Promise resolving to recent Client sessions.
 */
export async function getClientSessions(
  limit: number = 20,
): Promise<ClientSessionListResponse> {
  return apiRequest(`/client/sessions?limit=${limit}`) as Promise<ClientSessionListResponse>;
}
