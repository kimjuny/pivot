import type {
  ChatFileAsset,
  RecursionDetail,
  TaskAttachmentAsset,
  TaskMessage,
} from "@/utils/api";

import type {
  ChatAttachment,
  AssistantAttachment,
  ChatMessage,
  ChatPendingUserAction,
  ReactStreamEvent,
  TokenUsage,
} from "../types";
import { toPendingUserAction } from "./chatSelectors";

const CLIPBOARD_FILE_EXTENSION_BY_MIME: Record<string, string> = {
  "image/jpeg": "jpg",
  "image/png": "png",
  "image/webp": "webp",
  "application/pdf": "pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation":
    "pptx",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
  "text/markdown": "md",
  "text/x-markdown": "md",
  "text/plain": "md",
};

/**
 * Safely parses JSON payloads coming from the backend.
 */
export function parseJson(text: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

/**
 * Narrows unknown payloads to plain object records before field access.
 */
export function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

/**
 * Normalizes streamed error payloads so retryable recursion failures do not
 * masquerade as terminal task failures in the chat timeline.
 */
export function getStreamErrorData(data: unknown): {
  message: string | undefined;
  terminal: boolean;
} {
  const record = asRecord(data);
  const errorMessage =
    typeof record?.error === "string" && record.error.trim().length > 0
      ? record.error
      : typeof record?.message === "string" && record.message.trim().length > 0
        ? record.message
        : undefined;

  return {
    message: errorMessage,
    terminal: typeof record?.terminal === "boolean" ? record.terminal : true,
  };
}

/**
 * Guards streamed backend payloads before the container mutates UI state.
 */
export function isReactStreamEvent(value: unknown): value is ReactStreamEvent {
  const record = asRecord(value);
  if (!record) {
    return false;
  }

  const traceId = record.trace_id;
  return (
    typeof record.type === "string" &&
    typeof record.task_id === "string" &&
    (traceId === undefined || typeof traceId === "string" || traceId === null) &&
    typeof record.iteration === "number" &&
    typeof record.timestamp === "string"
  );
}

/**
 * Extracts token-rate data while suppressing malformed SSE payloads.
 */
export function parseTokenRateData(data: unknown): {
  tokensPerSecond: number;
  estimatedCompletionTokens: number;
} | null {
  const record = asRecord(data);
  if (!record) {
    return null;
  }

  const rawRate = record.tokens_per_second;
  const rawEstimated = record.estimated_completion_tokens;
  if (typeof rawRate !== "number" || typeof rawEstimated !== "number") {
    return null;
  }

  return {
    tokensPerSecond: Math.max(rawRate, 0),
    estimatedCompletionTokens: Math.max(Math.round(rawEstimated), 0),
  };
}

/**
 * Converts API attachment payloads into the stable UI model used across chat views.
 */
export function toChatAttachment(
  file: ChatFileAsset,
  previewUrl?: string,
): ChatAttachment {
  return {
    fileId: file.file_id,
    kind: file.kind,
    originalName: file.original_name,
    mimeType: file.mime_type,
    format: file.format,
    extension: file.extension,
    width: file.width,
    height: file.height,
    sizeBytes: file.size_bytes,
    pageCount: file.page_count,
    canExtractText: file.can_extract_text,
    suspectedScanned: file.suspected_scanned,
    textEncoding: file.text_encoding,
    previewUrl,
  };
}

/**
 * Converts API task-attachment payloads into the assistant artifact model.
 */
export function toAssistantAttachment(
  attachment: TaskAttachmentAsset,
): AssistantAttachment {
  return {
    attachmentId: attachment.attachment_id,
    displayName: attachment.display_name,
    originalName: attachment.original_name,
    mimeType: attachment.mime_type,
    extension: attachment.extension,
    sizeBytes: attachment.size_bytes,
    renderKind: attachment.render_kind,
    workspaceRelativePath: attachment.workspace_relative_path,
    createdAt: attachment.created_at,
  };
}

/**
 * Restores a stable clipboard filename so upload APIs receive predictable extensions.
 */
export function normalizeClipboardFile(file: File, index: number): File {
  if (file.name) {
    return file;
  }

  const inferredExtension =
    CLIPBOARD_FILE_EXTENSION_BY_MIME[file.type] ||
    file.type.split("/")[1] ||
    "bin";

  return new File([file], `clipboard-${Date.now()}-${index}.${inferredExtension}`, {
    type: file.type || "application/octet-stream",
  });
}

/**
 * Extracts clipboard files once so screenshot pastes do not duplicate the same blob.
 */
export function getUniqueClipboardFiles(clipboardData: DataTransfer): File[] {
  const uniqueFiles = new Map<string, File>();
  const fileItems = Array.from(clipboardData.items).filter(
    (item) => item.kind === "file",
  );
  const rawFiles =
    fileItems.length > 0
      ? fileItems
          .map((item) => item.getAsFile())
          .filter((file): file is File => file instanceof File)
      : Array.from(clipboardData.files);

  rawFiles.forEach((file) => {
    const dedupeKey = file.name
      ? [file.name, file.size, file.type, file.lastModified].join(":")
      : ["clipboard", file.size, file.type].join(":");
    if (!uniqueFiles.has(dedupeKey)) {
      uniqueFiles.set(dedupeKey, file);
    }
  });

  return Array.from(uniqueFiles.values()).map((file, index) =>
    normalizeClipboardFile(file, index),
  );
}

/**
 * Extracts persisted assistant copy from task history, including clarify prompts.
 */
function buildAssistantContent(task: TaskMessage): string {
  if (typeof task.agent_answer === "string" && task.agent_answer.trim().length > 0) {
    return task.agent_answer;
  }

  const pendingUserAction =
    task.status === "waiting_input"
      ? toPendingUserAction(task.pending_user_action)
      : undefined;
  if (pendingUserAction?.kind === "skill_change_approval") {
    const { question, message } = pendingUserAction.approvalRequest;
    return message && message.trim().length > 0
      ? `${question}\n\n${message}`
      : question;
  }

  if (task.status !== "waiting_input") {
    return "";
  }

  for (let index = task.recursions.length - 1; index >= 0; index -= 1) {
    const recursion = task.recursions[index];
    if (recursion.action_type !== "CLARIFY" || !recursion.action_output) {
      continue;
    }

    const actionOutput = asRecord(parseJson(recursion.action_output));
    const question = actionOutput?.question;
    if (typeof question === "string" && question.trim().length > 0) {
      return question;
    }
  }

  return "";
}

/**
 * Reads the latest persisted recursion error so failed tasks can render an
 * explicit error block without pretending the error is a final answer.
 */
function getLatestTaskErrorMessage(task: TaskMessage): string | undefined {
  for (let index = task.recursions.length - 1; index >= 0; index -= 1) {
    const errorLog = task.recursions[index]?.error_log;
    if (typeof errorLog === "string" && errorLog.trim().length > 0) {
      return errorLog;
    }
  }

  return undefined;
}

/**
 * Maps persisted task history into the same message model used by live streaming updates.
 */
export function buildMessagesFromHistory(tasks: TaskMessage[]): ChatMessage[] {
  const loadedMessages: ChatMessage[] = [];

  for (const task of tasks) {
    const pendingUserAction: ChatPendingUserAction | undefined =
      task.status === "waiting_input"
        ? toPendingUserAction(task.pending_user_action)
        : undefined;

    loadedMessages.push({
      id: `user-${task.task_id}`,
      role: "user",
      content: task.user_message,
      attachments: (task.files ?? []).map((file) => toChatAttachment(file)),
      timestamp: task.created_at,
    });

    const recursions = task.recursions.map((recursion: RecursionDetail) => {
      const events: ReactStreamEvent[] = [];

      if (recursion.action_type === "CALL_TOOL") {
        let toolCalls: unknown[] = [];
        let toolResults: unknown[] = [];

        if (recursion.action_output) {
          const actionData = asRecord(parseJson(recursion.action_output));
          if (actionData && Array.isArray(actionData.tool_calls)) {
            toolCalls = actionData.tool_calls;
          }
        }

        if (recursion.tool_call_results) {
          const parsedResults = parseJson(recursion.tool_call_results);
          if (Array.isArray(parsedResults)) {
            toolResults = parsedResults;
          }
        }

        if (toolCalls.length > 0 || toolResults.length > 0) {
          events.push({
            type: "tool_call",
            task_id: task.task_id,
            trace_id: recursion.trace_id,
            iteration: recursion.iteration,
            data: {
              tool_calls: toolCalls,
              tool_results: toolResults,
            },
            timestamp: recursion.updated_at,
          });
        }
      }

      if (
        (recursion.action_type === "RE_PLAN" ||
          recursion.action_type === "PLAN") &&
        recursion.action_output
      ) {
        const planData = parseJson(recursion.action_output);
        if (planData !== null) {
          events.push({
            type: "plan_update",
            task_id: task.task_id,
            trace_id: recursion.trace_id,
            iteration: recursion.iteration,
            data: planData,
            timestamp: recursion.updated_at,
          });
        }
      }

      if (recursion.action_type === "CLARIFY" && recursion.action_output) {
        const clarifyData = parseJson(recursion.action_output);
        if (clarifyData !== null) {
          events.push({
            type: "clarify",
            task_id: task.task_id,
            trace_id: recursion.trace_id,
            iteration: recursion.iteration,
            data: clarifyData,
            timestamp: recursion.updated_at,
          });
        }
      }

      const recursionStatus =
        task.status === "cancelled" && recursion.status === "running"
          ? ("stopped" as const)
          : recursion.status === "done"
            ? ("completed" as const)
            : recursion.status === "running"
              ? ("running" as const)
              : recursion.status === "error"
                ? ("error" as const)
                : ("completed" as const);

      return {
        uid: `history-${task.task_id}-${recursion.trace_id || `iter-${recursion.iteration}`}`,
        iteration: recursion.iteration,
        trace_id: recursion.trace_id,
        thinking: recursion.thinking || undefined,
        observe: recursion.observe || undefined,
        reason: recursion.reason || undefined,
        summary: recursion.summary || undefined,
        action: recursion.action_type || undefined,
        events,
        status: recursionStatus,
        errorLog: recursion.error_log || undefined,
        startTime: recursion.created_at,
        endTime:
          recursionStatus === "running"
            ? undefined
            : task.status === "cancelled" && recursion.status === "running"
              ? task.updated_at
              : recursion.updated_at,
        tokens: {
          prompt_tokens: recursion.prompt_tokens,
          completion_tokens: recursion.completion_tokens,
          total_tokens: recursion.total_tokens,
          cached_input_tokens: recursion.cached_input_tokens ?? 0,
        },
      };
    });

    const aggregatedTaskTokens = recursions.reduce<TokenUsage>(
      (accumulator, recursion) => ({
        prompt_tokens:
          accumulator.prompt_tokens + (recursion.tokens?.prompt_tokens ?? 0),
        completion_tokens:
          accumulator.completion_tokens +
          (recursion.tokens?.completion_tokens ?? 0),
        total_tokens:
          accumulator.total_tokens + (recursion.tokens?.total_tokens ?? 0),
        cached_input_tokens:
          (accumulator.cached_input_tokens ?? 0) +
          (recursion.tokens?.cached_input_tokens ?? 0),
      }),
      {
        prompt_tokens: 0,
        completion_tokens: 0,
        total_tokens: 0,
        cached_input_tokens: 0,
      },
    );

    loadedMessages.push({
      id: `assistant-${task.task_id}`,
      role: "assistant",
      content: buildAssistantContent(task),
      errorMessage: task.status === "failed" ? getLatestTaskErrorMessage(task) : undefined,
      assistantAttachments: (task.assistant_attachments ?? []).map((attachment) =>
        toAssistantAttachment(attachment),
      ),
      timestamp: task.updated_at,
      task_id: task.task_id,
      pendingUserAction,
      currentPlan: task.current_plan,
      recursions,
      status:
        task.status === "completed"
          ? ("completed" as const)
          : task.status === "cancelled"
            ? ("stopped" as const)
            : task.status === "failed"
            ? ("error" as const)
            : task.status === "waiting_input"
              ? ("waiting_input" as const)
              : task.status === "running" || task.status === "pending"
                ? ("running" as const)
                : ("completed" as const),
      totalTokens: {
        prompt_tokens: aggregatedTaskTokens.prompt_tokens,
        completion_tokens: aggregatedTaskTokens.completion_tokens,
        total_tokens: aggregatedTaskTokens.total_tokens || task.total_tokens,
        cached_input_tokens: aggregatedTaskTokens.cached_input_tokens ?? 0,
      },
    });
  }

  return loadedMessages;
}
