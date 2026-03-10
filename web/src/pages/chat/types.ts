import type { FileUploadSource } from "@/utils/api";

/**
 * Props accepted by the page-scoped ReAct chat container.
 */
export interface ReactChatInterfaceProps {
  /** Unique identifier of the agent backing the conversation. */
  agentId: number;
  /** Display name shown in empty state and dialog title copy. */
  agentName?: string;
  /** Primary LLM configuration used to gate image upload affordances. */
  primaryLlmId?: number;
}

/**
 * All stream event labels emitted by the ReAct backend.
 */
export type ReactStreamEventType =
  | "skill_resolution_start"
  | "skill_resolution_result"
  | "token_rate"
  | "recursion_start"
  | "reasoning"
  | "observe"
  | "thought"
  | "abstract"
  | "progress_update"
  | "action"
  | "tool_call"
  | "plan_update"
  | "reflect"
  | "answer"
  | "clarify"
  | "task_complete"
  | "error";

/**
 * Token accounting metadata surfaced by task and recursion events.
 */
export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cached_input_tokens?: number;
}

/**
 * Runtime shape of a backend stream event after guard validation.
 */
export interface ReactStreamEvent {
  type: ReactStreamEventType;
  task_id: string;
  trace_id?: string | null;
  iteration: number;
  delta?: string | null;
  data?: unknown;
  timestamp: string;
  created_at?: string;
  updated_at?: string;
  tokens?: TokenUsage;
  total_tokens?: TokenUsage;
}

/**
 * Plan step payload emitted by RE_PLAN output.
 */
export interface PlanStepData {
  step_id: string;
  general_goal: string;
  specific_description: string;
  completion_criteria: string;
  status: string;
}

/**
 * Accumulated recursion state rendered inside an assistant message.
 */
export interface RecursionRecord {
  uid: string;
  iteration: number;
  trace_id: string | null;
  thinking?: string;
  observe?: string;
  thought?: string;
  abstract?: string;
  progressUpdate?: string;
  action?: string;
  events: ReactStreamEvent[];
  status: "running" | "completed" | "error";
  errorLog?: string;
  startTime: string;
  endTime?: string;
  tokens?: TokenUsage;
  liveTokensPerSecond?: number;
  estimatedCompletionTokens?: number;
  hasSeenPositiveRate?: boolean;
  zeroRateStreak?: number;
}

/**
 * Skill matching summary shown before recursive execution starts.
 */
export interface SkillSelectionState {
  status: "loading" | "done";
  count: number;
  selectedSkills: string[];
  durationMs?: number;
  tokens?: TokenUsage;
}

/**
 * Normalized attachment shape shared by message history and composer queue.
 */
export interface ChatAttachment {
  fileId: string;
  kind: "image" | "document";
  originalName: string;
  mimeType: string;
  format: string;
  extension: string;
  width: number;
  height: number;
  sizeBytes: number;
  pageCount?: number | null;
  canExtractText?: boolean;
  suspectedScanned?: boolean;
  textEncoding?: string | null;
  previewUrl?: string;
}

/**
 * Upload queue item that keeps local UI state beside persisted file metadata.
 */
export interface PendingUploadItem extends ChatAttachment {
  clientId: string;
  source: FileUploadSource;
  status: "uploading" | "ready" | "error";
  errorMessage?: string;
}

/**
 * Renderable chat message used by the conversation timeline.
 */
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  attachments?: ChatAttachment[];
  timestamp: string;
  task_id?: string;
  recursions?: RecursionRecord[];
  status?:
    | "running"
    | "skill_resolving"
    | "completed"
    | "error"
    | "waiting_input";
  totalTokens?: TokenUsage;
  skillSelection?: SkillSelectionState;
}
