/** Studio Operations API — admin-scoped session inspection. */

import { apiRequest } from "@/utils/api";

/**
 * Latest error signal attached to one Operations session.
 */
export interface OperationsSessionLatestError {
  /** Task that emitted the latest visible failure signal. */
  task_id: string | null;
  /** Recursion trace associated with the latest failure, when available. */
  trace_id: string | null;
  /** Human-readable diagnostics message for the latest failure. */
  message: string | null;
  /** ISO 8601 UTC timestamp for the latest failure signal. */
  timestamp: string | null;
}

/**
 * Compact diagnostics summary attached to one Operations session.
 */
export interface OperationsSessionDiagnostics {
  /** Total number of tasks inside the session. */
  task_count: number;
  /** Number of tasks that completed successfully. */
  completed_task_count: number;
  /** Number of tasks still actively executing. */
  active_task_count: number;
  /** Number of tasks paused for user input. */
  waiting_input_task_count: number;
  /** Number of tasks that failed terminally. */
  failed_task_count: number;
  /** Number of tasks cancelled before completion. */
  cancelled_task_count: number;
  /** Number of tasks that currently deserve operator attention. */
  attention_task_count: number;
  /** Number of recursions that ended in error. */
  failed_recursion_count: number;
  /** Latest visible failure signal for quick triage. */
  latest_error: OperationsSessionLatestError | null;
}

/**
 * One session row returned by the Operations list endpoint.
 */
export interface OperationsSession {
  /** Session UUID. */
  session_id: string;
  /** Agent primary key. */
  agent_id: number;
  /** Agent display name (joined server-side). */
  agent_name: string;
  /** Release foreign key, if pinned. */
  release_id: number | null;
  /** Agent-scoped version number, if pinned. */
  release_version: number | null;
  /** Session type discriminator. */
  type: "consumer" | "studio_test";
  /** Username that owns the session. */
  user: string;
  /** Session lifecycle status. */
  status: string;
  /** User-defined session display title. */
  title: string | null;
  /** Number of tasks within this session. */
  task_count: number;
  /** Compact diagnostics summary used for list-page triage. */
  diagnostics: OperationsSessionDiagnostics;
  /** ISO 8601 UTC creation timestamp. */
  created_at: string;
  /** ISO 8601 UTC last-activity timestamp. */
  updated_at: string;
}

/**
 * Paginated response shape for the Operations session list.
 */
export interface OperationsSessionListResponse {
  sessions: OperationsSession[];
  total: number;
  page: number;
  page_size: number;
}

/**
 * Session metadata returned by the Operations detail endpoint.
 */
export interface OperationsSessionDetail {
  session_id: string;
  agent_id: number;
  agent_name: string;
  release_version: number | null;
  type: "consumer" | "studio_test";
  user: string;
  status: string;
  title: string | null;
  diagnostics: OperationsSessionDiagnostics;
  created_at: string;
  updated_at: string;
}

/**
 * Full Operations session detail response including task history.
 */
export interface OperationsSessionDetailResponse {
  session: OperationsSessionDetail;
  tasks: OperationsTaskMessage[];
}

/**
 * Task message in the operations detail response.
 *
 * Mirrors the same shape as the user-scoped TaskMessage so
 * buildMessagesFromHistory() can consume it without adaptation.
 */
export interface OperationsTaskMessage {
  task_id: string;
  user_message: string;
  files: unknown[];
  agent_answer: string | null;
  status: string;
  total_tokens: number;
  pending_user_action: unknown;
  current_plan: unknown[];
  recursions: OperationsRecursion[];
  created_at: string;
  updated_at: string;
}

/**
 * Recursion step in the operations detail response.
 */
export interface OperationsRecursion {
  iteration: number;
  trace_id: string;
  input_message_json: string | null;
  observe: string | null;
  thinking: string | null;
  reason: string | null;
  summary: string | null;
  action_type: string | null;
  action_output: string | null;
  tool_call_results: string | null;
  status: string;
  error_log: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cached_input_tokens: number;
  created_at: string;
  updated_at: string;
}

/**
 * Fetch paginated sessions for the Studio Operations view.
 *
 * @param params - Filter and pagination options.
 * @returns Paginated session list.
 */
export const listOperationsSessions = async (params?: {
  agent_id?: number;
  status?: string;
  session_type?: string;
  page?: number;
  page_size?: number;
}): Promise<OperationsSessionListResponse> => {
  const searchParams = new URLSearchParams();
  if (params?.agent_id !== undefined) {
    searchParams.set("agent_id", String(params.agent_id));
  }
  if (params?.status) {
    searchParams.set("status", params.status);
  }
  if (params?.session_type) {
    searchParams.set("session_type", params.session_type);
  }
  if (params?.page !== undefined) {
    searchParams.set("page", String(params.page));
  }
  if (params?.page_size !== undefined) {
    searchParams.set("page_size", String(params.page_size));
  }
  const query = searchParams.toString();
  const endpoint = `/operations/sessions${query ? `?${query}` : ""}`;
  return apiRequest(endpoint) as Promise<OperationsSessionListResponse>;
};

/**
 * Fetch full session detail for the Studio Operations view.
 *
 * @param sessionId - Session UUID to inspect.
 * @returns Session metadata and full conversation history.
 */
export const getOperationsSessionDetail = async (
  sessionId: string,
): Promise<OperationsSessionDetailResponse> => {
  return apiRequest(
    `/operations/sessions/${sessionId}`,
  ) as Promise<OperationsSessionDetailResponse>;
};
