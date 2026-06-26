import type { ChatSessionType, StudioTestSnapshotPayload } from '@/utils/agentTestSnapshot';
import { apiRequest } from './core';
import type { ChatFileAsset, TaskAttachmentAsset } from './sessions';
import type { OperationRefPayload } from './surfaces';

export interface RecursionDetail {
  iteration: number;
  trace_id: string;
  input_message_json: string | null;
  thinking: string | null;
  message: string | null;
  action_type: string | null;
  action_output: string | null;
  tool_call_results: string | null;
  status: string;
  error_log: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cached_input_tokens?: number;
  created_at: string;
  updated_at: string;
}

export interface CurrentPlanStep {
  step_id: string;
  subject: string;
  description?: string;
  status: string;
}

export interface TaskMessage {
  task_id: string;
  user_message: string;
  files?: ChatFileAsset[];
  mandatory_skills?: Array<{
    name: string;
    path: string;
  }>;
  assistant_attachments?: TaskAttachmentAsset[];
  agent_answer: string | null;
  status: string;
  total_tokens: number;
  pending_user_action?: {
    kind: string;
    approval_request?: {
      submission_id: number;
      skill_name: string;
      change_type: string;
      question: string;
      message?: string;
      file_count?: number;
      total_bytes?: number;
    } | null;
  } | null;
  current_steps?: CurrentPlanStep[];
  recursions: RecursionDetail[];
  created_at: string;
  updated_at: string;
}

export interface TaskSummary {
  task_id: string;
  preview: string;
  status: string;
  created_at: string;
}

export interface FullSessionHistoryResponse {
  session_id: string;
  total_task_count: number;
  has_more_older: boolean;
  task_summaries: TaskSummary[];
  tasks: TaskMessage[];
  last_event_id: number;
  resume_from_event_id: number;
}

export interface ReactTaskStartResponse {
  task_id: string;
  session_id: string | null;
  status: string;
  cursor_before_start: number;
}

export interface ReactTaskCancelResponse {
  task_id: string;
  status: string;
  cancel_requested: boolean;
}

export interface ReactPendingUserActionResponse {
  task_id: string;
  session_id: string | null;
  status: string;
  cursor_before_start: number;
}

export interface ReactRuntimeSkillItem {
  name: string;
  description: string;
  path: string;
}

export interface ReactContextUsageSummary {
  task_id: string | null;
  session_id: string | null;
  estimation_mode: string;
  message_count: number;
  session_message_count: number;
  used_tokens: number;
  remaining_tokens: number;
  max_context_tokens: number;
  used_percent: number;
  remaining_percent: number;
  system_tokens: number;
  conversation_tokens: number;
  session_tokens: number;
  preview_tokens: number;
  tools_tokens: number;
  bootstrap_tokens: number;
  draft_tokens: number;
  includes_task_bootstrap: boolean;
  cache_hit_rate: number | null;
}

export interface ReactSessionRuntimeDebug {
  session_id: string;
  runtime_message_count: number;
  runtime_message_roles: string[];
  has_compact_result: boolean;
  compact_result: Record<string, unknown> | Array<unknown> | string | null;
  compact_result_raw: string | null;
  exact_prompt_tokens: number | null;
  exact_prompt_message_count: number | null;
  updated_at: string;
  file_read_tracker: Record<
    string,
    {
      hash?: string;
      total_lines?: number;
      read_ranges?: number[][];
    }
  > | null;
}

export interface ReactSessionCompactResponse {
  session_id: string;
  status: "completed" | "noop";
  compacted: boolean;
  reason: string;
  usage_before: ReactContextUsageSummary;
  usage_after: ReactContextUsageSummary;
}

export const getFullSessionHistory = async (
  sessionId: string,
  options?: { limit?: number; beforeTaskId?: string },
): Promise<FullSessionHistoryResponse> => {
  const params = new URLSearchParams();
  if (options?.limit) params.set("limit", String(options.limit));
  if (options?.beforeTaskId) params.set("before_task_id", options.beforeTaskId);
  const qs = params.toString();
  return apiRequest(`/sessions/${sessionId}/full-history${qs ? `?${qs}` : ""}`) as Promise<FullSessionHistoryResponse>;
};

export const startReactTask = async (payload: {
  agent_id: number;
  message: string;
  task_id?: string | null;
  session_id?: string | null;
  file_ids?: string[];
  web_search_provider?: string | null;
  thinking_enabled?: boolean;
  mandatory_skill_names?: string[];
  action_refs?: OperationRefPayload[];
}): Promise<ReactTaskStartResponse> => {
  return apiRequest('/react/tasks', {
    method: 'POST',
    body: JSON.stringify(payload),
  }) as Promise<ReactTaskStartResponse>;
};

export const cancelReactTask = async (
  taskId: string,
): Promise<ReactTaskCancelResponse> => {
  return apiRequest(`/react/tasks/${taskId}/cancel`, {
    method: 'POST',
  }) as Promise<ReactTaskCancelResponse>;
};

export const submitReactUserAction = async (
  taskId: string,
  decision: "approve" | "reject",
): Promise<ReactPendingUserActionResponse> => {
  return apiRequest(`/react/tasks/${taskId}/user-action`, {
    method: 'POST',
    body: JSON.stringify({ decision }),
  }) as Promise<ReactPendingUserActionResponse>;
};

export const submitMidTaskInput = async (
  taskId: string,
  message: string,
): Promise<{ queue_id: string; status: string }> => {
  return apiRequest(`/react/tasks/${taskId}/mid-task-input`, {
    method: 'POST',
    body: JSON.stringify({ message }),
  }) as Promise<{ queue_id: string; status: string }>;
};

export const getTaskPlan = async (
  taskId: string,
): Promise<{ plan_text: string | null; steps: Array<{ step_id: string; subject: string; status: string }> }> => {
  return apiRequest(`/react/tasks/${taskId}/plan`) as Promise<{
    plan_text: string | null;
    steps: Array<{ step_id: string; subject: string; status: string }>;
  }>;
};

export const updatePlanText = async (
  taskId: string,
  planText: string,
): Promise<{ success: boolean }> => {
  return apiRequest(`/react/tasks/${taskId}/plan`, {
    method: 'PUT',
    body: JSON.stringify({ plan_text: planText }),
  }) as Promise<{ success: boolean }>;
};

export const getReactContextUsage = async (payload: {
  agent_id: number;
  session_id?: string | null;
  task_id?: string | null;
  draft_message?: string;
  file_ids?: string[];
  session_type?: ChatSessionType;
  test_snapshot?: StudioTestSnapshotPayload | null;
  mandatory_skill_names?: string[];
}): Promise<ReactContextUsageSummary> => {
  return apiRequest('/react/context-usage', {
    method: 'POST',
    body: JSON.stringify(payload),
  }) as Promise<ReactContextUsageSummary>;
};

export const getReactRuntimeSkills = async (payload: {
  agent_id: number;
  session_id?: string | null;
  session_type?: ChatSessionType;
  test_snapshot?: StudioTestSnapshotPayload | null;
}): Promise<ReactRuntimeSkillItem[]> => {
  return apiRequest('/react/runtime-skills', {
    method: 'POST',
    body: JSON.stringify(payload),
  }) as Promise<ReactRuntimeSkillItem[]>;
};

export const getReactSessionRuntimeDebug = async (
  sessionId: string,
): Promise<ReactSessionRuntimeDebug> => {
  return apiRequest(
    `/react/sessions/${sessionId}/runtime-debug`,
  ) as Promise<ReactSessionRuntimeDebug>;
};

export const compactReactSession = async (
  sessionId: string,
  instruction: string,
): Promise<ReactSessionCompactResponse> => {
  return apiRequest(`/react/sessions/${sessionId}/compact`, {
    method: "POST",
    body: JSON.stringify({ instruction }),
  }) as Promise<ReactSessionCompactResponse>;
};

export const editReactTask = async (
  taskId: string,
  newMessage: string,
  rewindScope: "conversation" | "full" = "conversation",
): Promise<ReactTaskStartResponse> => {
  return apiRequest(`/react/tasks/${taskId}/edit`, {
    method: "POST",
    body: JSON.stringify({
      new_message: newMessage,
      rewind_scope: rewindScope,
    }),
  }) as Promise<ReactTaskStartResponse>;
};
