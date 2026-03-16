import type { ChatFileAsset, RecursionDetail, TaskMessage } from "@/utils/api";

import type {
  ChatAttachment,
  ChatMessage,
  ReactStreamEvent,
  SkillSelectionState,
  TokenUsage,
} from "../types";

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
 * Rebuilds persisted skill matching results into the timeline UI model.
 */
export function buildSkillSelectionFromTask(
  task: TaskMessage,
): SkillSelectionState | undefined {
  const raw = task.skill_selection_result;
  if (!raw || typeof raw !== "object") {
    return undefined;
  }

  const selectedSkills = Array.isArray(raw.selected_skills)
    ? raw.selected_skills.filter(
        (item): item is string => typeof item === "string" && item.length > 0,
      )
    : [];
  const count = typeof raw.count === "number" ? raw.count : selectedSkills.length;
  const durationMs =
    typeof raw.duration_ms === "number" ? raw.duration_ms : undefined;

  const rawTokens = raw.tokens;
  const tokens: TokenUsage | undefined =
    rawTokens &&
    typeof rawTokens === "object" &&
    typeof rawTokens.prompt_tokens === "number" &&
    typeof rawTokens.completion_tokens === "number" &&
    typeof rawTokens.total_tokens === "number"
      ? {
          prompt_tokens: rawTokens.prompt_tokens,
          completion_tokens: rawTokens.completion_tokens,
          total_tokens: rawTokens.total_tokens,
          cached_input_tokens:
            typeof rawTokens.cached_input_tokens === "number"
              ? rawTokens.cached_input_tokens
              : 0,
        }
      : undefined;

  return {
    status: "done",
    count,
    selectedSkills,
    durationMs,
    tokens,
  };
}

/**
 * Maps persisted task history into the same message model used by live streaming updates.
 */
export function buildMessagesFromHistory(tasks: TaskMessage[]): ChatMessage[] {
  const loadedMessages: ChatMessage[] = [];

  for (const task of tasks) {
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

      return {
        uid: `history-${task.task_id}-${recursion.trace_id || `iter-${recursion.iteration}`}`,
        iteration: recursion.iteration,
        trace_id: recursion.trace_id,
        thinking: recursion.thinking || undefined,
        observe: recursion.observe || undefined,
        thought: recursion.thought || undefined,
        abstract: recursion.abstract || undefined,
        summary: recursion.summary || undefined,
        action: recursion.action_type || undefined,
        events,
        status:
          recursion.status === "done"
            ? ("completed" as const)
            : recursion.status === "error"
              ? ("error" as const)
              : ("completed" as const),
        errorLog: recursion.error_log || undefined,
        startTime: recursion.created_at,
        endTime: recursion.updated_at,
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
      content: task.agent_answer || "",
      timestamp: task.updated_at,
      task_id: task.task_id,
      recursions,
      skillSelection: buildSkillSelectionFromTask(task),
      status:
        task.status === "completed"
          ? ("completed" as const)
          : task.status === "failed"
            ? ("error" as const)
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
