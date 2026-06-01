import type { Agent } from "@/types";
import type { ChatSessionType } from "@/utils/agentTestSnapshot";
import { apiRequest } from "@/utils/api";

/**
 * Automation entity returned by the client API.
 */
export interface ClientAutomation {
  id: number;
  automation_id: string;
  name: string;
  agent_id: number;
  release_id: number;
  trigger_type: string;
  trigger_config: string;
  prompt_template: string;
  session_strategy: "reuse" | "isolate" | "this_session";
  status: "active" | "paused" | "disabled";
  max_iterations: number | null;
  timeout_seconds: number;
  notify_on_completion: boolean;
  notify_on_failure: boolean;
  channel_session_id: number | null;
  channel_key: string | null;
  channel_name: string | null;
  channel_logo_url: string | null;
  last_run_at: string | null;
  next_run_at: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Automation run execution record.
 */
export interface ClientAutomationRun {
  id: number;
  run_id: string;
  automation_id: number;
  scheduled_at: string;
  session_id: number;
  session_uuid: string | null;
  task_id: string | null;
  status: "pending" | "running" | "completed" | "failed" | "timeout" | "cancelled";
  started_at: string | null;
  finished_at: string | null;
  result_summary: string | null;
  error_message: string | null;
  token_usage: string | null;
  delivery_status: string | null;
  delivery_error: string | null;
}

/**
 * Paginated automation list response.
 */
export interface ClientAutomationListResponse {
  automations: ClientAutomation[];
  total: number;
}

/**
 * Paginated automation run list response.
 */
export interface ClientAutomationRunListResponse {
  runs: ClientAutomationRun[];
  total: number;
}

/**
 * Payload for creating a new automation.
 */
export interface ClientAutomationCreatePayload {
  name: string;
  agent_id: number;
  prompt_template: string;
  trigger_config: string;
  session_strategy?: "reuse" | "isolate" | "this_session";
  max_iterations?: number | null;
  timeout_seconds?: number;
  notify_on_completion?: boolean;
  notify_on_failure?: boolean;
  channel_session_id?: number | null;
}

/**
 * Payload for updating an automation (all fields optional).
 */
export type ClientAutomationUpdatePayload = Partial<ClientAutomationCreatePayload> & {
  status?: "active" | "paused" | "disabled";
};

/**
 * Aggregated automation statistics for the current user.
 */
export interface ClientAutomationStats {
  total_automations: number;
  active_count: number;
  paused_count: number;
  runs_last_7_days: number;
  success_rate: number;
  total_tokens_last_7_days: number;
}

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
  channel_key?: string | null;
  channel_logo_url?: string | null;
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

// ── Automations ──────────────────────────────────────────────

/**
 * Fetch aggregated automation statistics for the current user.
 */
export async function getClientAutomationStats(): Promise<ClientAutomationStats> {
  return apiRequest("/client/automations/stats") as Promise<ClientAutomationStats>;
}

/**
 * Fetch all automations owned by the current user.
 */
export async function getClientAutomations(
  status?: string,
): Promise<ClientAutomationListResponse> {
  const params = status ? `?status=${status}` : "";
  return apiRequest(`/client/automations${params}`) as Promise<ClientAutomationListResponse>;
}

/**
 * Create a new automation.
 */
export async function createClientAutomation(
  payload: ClientAutomationCreatePayload,
): Promise<ClientAutomation> {
  return apiRequest("/client/automations", {
    method: "POST",
    body: JSON.stringify(payload),
  }) as Promise<ClientAutomation>;
}

/**
 * Update an existing automation.
 */
export async function updateClientAutomation(
  automationId: string,
  payload: ClientAutomationUpdatePayload,
): Promise<ClientAutomation> {
  return apiRequest(`/client/automations/${automationId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  }) as Promise<ClientAutomation>;
}

/**
 * Delete an automation.
 */
export async function deleteClientAutomation(
  automationId: string,
): Promise<void> {
  await apiRequest(`/client/automations/${automationId}`, { method: "DELETE" });
}

/**
 * Manually trigger an automation run.
 */
export async function triggerClientAutomation(
  automationId: string,
): Promise<ClientAutomationRun> {
  return apiRequest(`/client/automations/${automationId}/trigger`, {
    method: "POST",
  }) as Promise<ClientAutomationRun>;
}

/**
 * Fetch execution runs for an automation.
 */
export async function getClientAutomationRuns(
  automationId: string,
  limit: number = 50,
  offset: number = 0,
): Promise<ClientAutomationRunListResponse> {
  return apiRequest(
    `/client/automations/${automationId}/runs?limit=${limit}&offset=${offset}`,
  ) as Promise<ClientAutomationRunListResponse>;
}
