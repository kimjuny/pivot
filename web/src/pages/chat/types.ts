import type {
  FileUploadSource,
  ReactSessionRuntimeDebug,
  TaskAttachmentAsset,
} from "@/utils/api";
import type {
  ChatSessionType,
  StudioTestSnapshotPayload,
} from "@/utils/agentTestSnapshot";

import type { ReactNode } from "react";

/**
 * One workspace-level shortcut rendered above the session list.
 */
export interface ChatSidebarNavigationItem {
  /** Stable key used for React rendering. */
  key: string;
  /** Human-readable label shown in the expanded sidebar. */
  label: string;
  /** Icon rendered in both expanded and collapsed modes. */
  icon: ReactNode;
  /** Whether this destination matches the currently visible workspace. */
  isActive: boolean;
  /** Callback invoked when the user selects the destination. */
  onSelect: () => void | Promise<void>;
}

/**
 * Props accepted by the page-scoped ReAct chat container.
 */
export interface ReactChatInterfaceProps {
  /** Unique identifier of the agent backing the conversation. */
  agentId: number;
  /** Session namespace used by this chat surface. */
  sessionType?: ChatSessionType;
  /** Optional session UUID that should be opened first when available. */
  initialSessionId?: string | null;
  /** Optional Studio working-copy snapshot used to create test sessions. */
  testSnapshot?: StudioTestSnapshotPayload | null;
  /** Optional Studio working-copy hash used to restore matching test sessions. */
  testSnapshotHash?: string | null;
  /** Display name shown in empty state and dialog title copy. */
  agentName?: string;
  /**
   * Serialized tool allowlist from ``agent.tool_ids``.
   * ``null`` means unrestricted, while a JSON array limits visible tools.
   */
  agentToolIds?: string | null;
  /** Primary LLM configuration used to gate image upload affordances. */
  primaryLlmId?: number;
  /** Minutes of inactivity before chat rolls over into a new session. */
  sessionIdleTimeoutMinutes?: number;
  /** Optional workspace shortcuts shown above the session list. */
  sidebarNavigationItems?: ChatSidebarNavigationItem[];
  /** Optional identity icon shown beside the sidebar title. */
  sidebarTitleIcon?: ReactNode;
  /** Optional sidebar identity title shown above navigation controls. */
  sidebarTitle?: string;
  /** Optional footer renderer anchored to the bottom of the left sidebar. */
  sidebarFooter?: (isCollapsed: boolean) => ReactNode;
  /** Whether the floating compact debug affordance should be shown. */
  showCompactDebug?: boolean;
}

/**
 * One enabled web-search provider that can be selected from the chat composer.
 */
export interface ChatWebSearchProviderOption {
  /** Stable provider key sent to the backend task launch payload. */
  key: string;
  /** Human-readable provider name shown in the selector. */
  name: string;
  /** Optional provider logo served from the backend. */
  logoUrl?: string | null;
}

/**
 * Runtime debug snapshot pushed upward from the page-scoped chat container.
 */
export interface ChatRuntimeDebugState {
  /** Currently selected session UUID, if any. */
  currentSessionId: string | null;
  /** Whether a compact cycle is actively in progress. */
  isCompacting: boolean;
  /** User-visible compact progress copy, when present. */
  compactStatusMessage: string | null;
  /** Lifecycle state of the runtime debug payload loader. */
  loadState: "idle" | "loading" | "ready" | "error";
  /** Latest fetched runtime debug payload for the current session. */
  runtimeDebug: ReactSessionRuntimeDebug | null;
  /** Loader or fetch error for the runtime debug payload. */
  error: string | null;
}

/**
 * Internal props accepted by the page-scoped chat shell.
 */
export interface ChatPageProps extends ReactChatInterfaceProps {
  /** Optional upward callback used by the outer shell to render debug affordances. */
  onRuntimeDebugChange?: (state: ChatRuntimeDebugState) => void;
}

/**
 * All stream event labels emitted by the ReAct backend.
 */
export type ReactStreamEventType =
  | "skill_resolution_start"
  | "skill_resolution_result"
  | "token_rate"
  | "compact_start"
  | "compact_complete"
  | "compact_failed"
  | "recursion_start"
  | "reasoning"
  | "observe"
  | "reason"
  | "summary"
  | "action"
  | "tool_call"
  | "plan_update"
  | "reflect"
  | "answer"
  | "clarify"
  | "task_cancelled"
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
  event_id?: number;
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
  recursion_history?: Array<{
    iteration?: number | null;
    summary: string;
  }>;
}

/**
 * Canonical task-plan states rendered by the composer-adjacent plan panel.
 */
export type TaskPlanStepStatus = "pending" | "running" | "done" | "error";

/**
 * Normalized task-plan step used by the Codex-style composer panel.
 */
export interface TaskPlanStep {
  stepId: string;
  title: string;
  description: string;
  completionCriteria: string;
  status: TaskPlanStepStatus;
}

/**
 * Snapshot of the latest visible task plan shown above the composer.
 */
export interface TaskPlanSnapshot {
  messageId: string;
  taskId?: string;
  taskStatus?: ChatMessage["status"];
  steps: TaskPlanStep[];
}

/**
 * Active clarify question currently bound to the composer reply flow.
 */
export interface SkillChangeApprovalRequest {
  /** Persisted submission identifier reviewed by the user. */
  submission_id: number;
  /** Target skill name shown in the approval modal. */
  skill_name: string;
  /** Whether the submission creates or updates a skill. */
  change_type: "create" | "update";
  /** User-facing approval copy generated by the backend/tool. */
  question: string;
  /** Optional agent-authored explanation displayed to the reviewer. */
  message?: string;
  /** Number of files frozen into the submission snapshot. */
  file_count?: number;
  /** Total snapshot bytes frozen into the submission snapshot. */
  total_bytes?: number;
}

/**
 * System-owned waiting action attached to a task while execution is paused.
 */
export interface ChatPendingUserAction {
  /** Stable action kind so the UI can dispatch the correct controls. */
  kind: "skill_change_approval";
  /** Structured approval request for one staged skill submission. */
  approvalRequest: SkillChangeApprovalRequest;
}

/**
 * Active clarify question currently bound to the composer reply flow.
 */
export interface ChatReplyTarget {
  /** Task ID that the follow-up answer should continue. */
  taskId: string;
  /** Latest clarify question content shown as compact reply context. */
  question: string;
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
  reason?: string;
  summary?: string;
  action?: string;
  events: ReactStreamEvent[];
  status: "running" | "completed" | "error" | "stopped";
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
 * Assistant-generated artifact rendered below one final answer.
 */
export interface AssistantAttachment {
  attachmentId: string;
  displayName: string;
  originalName: string;
  mimeType: string;
  extension: string;
  sizeBytes: number;
  renderKind: TaskAttachmentAsset["render_kind"];
  workspaceRelativePath: string;
  createdAt: string;
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
  errorMessage?: string;
  attachments?: ChatAttachment[];
  assistantAttachments?: AssistantAttachment[];
  timestamp: string;
  task_id?: string;
  /** Latest current-plan snapshot attached to this task, when available. */
  currentPlan?: PlanStepData[];
  recursions?: RecursionRecord[];
  pendingUserAction?: ChatPendingUserAction;
  status?:
    | "running"
    | "skill_resolving"
    | "completed"
    | "stopped"
    | "error"
    | "waiting_input";
  totalTokens?: TokenUsage;
  skillSelection?: SkillSelectionState;
}
