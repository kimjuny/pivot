import type {
  ChatPendingUserAction,
  ChatMessage,
  RecursionRecord,
  SkillChangeApprovalRequest,
  TaskPlanSnapshot,
} from "../types";
import { deriveComposerTaskPlan as deriveComposerTaskPlanSnapshot } from "./chatPlan";

/**
 * Number of consecutive zero-rate events required before rendering a visible zero throughput.
 */
export const ZERO_RATE_STREAK_TO_RENDER = 2;

/**
 * Formats token counts with locale separators for compact UI display.
 */
export function formatTokenCount(count: number): string {
  return count.toLocaleString();
}

/**
 * Calculates recursion duration in seconds for completed timeline rows.
 */
export function calculateDuration(startTime: string, endTime?: string): number {
  if (!endTime) {
    return 0;
  }

  const start = new Date(startTime).getTime();
  const end = new Date(endTime).getTime();
  return Math.max(0, Math.round(((end - start) / 1000) * 10) / 10);
}

/**
 * Detects whether a recursion completed with at least one failed tool result.
 */
export function hasFailedTools(recursion: RecursionRecord): boolean {
  const toolCallEvents = recursion.events.filter((event) => event.type === "tool_call");

  for (const event of toolCallEvents) {
    const toolData = event.data as
      | {
          tool_results?: Array<{ success: boolean }>;
        }
      | undefined;

    if (toolData?.tool_results?.some((result) => !result.success)) {
      return true;
    }
  }

  return false;
}

/**
 * Produces the display status that the recursion card should render.
 */
export function getRecursionStatus(
  recursion: RecursionRecord,
): "running" | "completed" | "warning" | "error" | "stopped" {
  if (recursion.status === "running") {
    return "running";
  }

  if (recursion.status === "stopped") {
    return "stopped";
  }

  if (recursion.status === "error") {
    return "error";
  }

  return hasFailedTools(recursion) ? "warning" : "completed";
}

/**
 * Returns the last recursion in a message so clarify flows can inspect the terminal action.
 */
export function getLastRecursion(
  message: ChatMessage,
): RecursionRecord | undefined {
  return message.recursions?.[message.recursions.length - 1];
}

/**
 * Centralizes clarify detection so assistant rendering does not repeat fragile array logic.
 */
export function isClarifyMessage(message: ChatMessage): boolean {
  return (
    message.status === "waiting_input" ||
    getLastRecursion(message)?.action === "CLARIFY" ||
    getLastRecursion(message)?.events.some((event) => event.type === "clarify") ===
      true
  );
}

/**
 * Guard unknown values before reading structured clarify payloads.
 */
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Validates one structured skill-change approval request embedded in clarify data.
 */
export function toSkillChangeApprovalRequest(
  value: unknown,
): SkillChangeApprovalRequest | undefined {
  if (!isRecord(value)) {
    return undefined;
  }

  const submissionId = value.submission_id;
  const skillName = value.skill_name;
  const changeType = value.change_type;
  const question = value.question;
  if (
    typeof submissionId !== "number" ||
    typeof skillName !== "string" ||
    (changeType !== "create" && changeType !== "update") ||
    typeof question !== "string"
  ) {
    return undefined;
  }

  return {
    submission_id: submissionId,
    skill_name: skillName,
    change_type: changeType,
    question,
    message: typeof value.message === "string" ? value.message : undefined,
    file_count: typeof value.file_count === "number" ? value.file_count : undefined,
    total_bytes:
      typeof value.total_bytes === "number" ? value.total_bytes : undefined,
  };
}

/**
 * Reads one system-owned pending user action from an unknown value.
 */
export function toPendingUserAction(
  value: unknown,
): ChatPendingUserAction | undefined {
  if (!isRecord(value) || value.kind !== "skill_change_approval") {
    return undefined;
  }

  const approvalRequest = toSkillChangeApprovalRequest(value.approval_request);
  if (!approvalRequest) {
    return undefined;
  }

  return {
    kind: "skill_change_approval",
    approvalRequest,
  };
}

/**
 * Reads the structured approval request attached to one clarify payload.
 */
export function extractSkillChangeApprovalRequestFromClarifyData(
  value: unknown,
): SkillChangeApprovalRequest | undefined {
  if (!isRecord(value)) {
    return undefined;
  }

  return toSkillChangeApprovalRequest(value.approval_request);
}

/**
 * Reads the task-owned structured approval request attached to one message.
 */
export function extractSkillChangeApprovalRequest(
  message: ChatMessage,
): SkillChangeApprovalRequest | undefined {
  if (message.pendingUserAction?.kind === "skill_change_approval") {
    return message.pendingUserAction.approvalRequest;
  }
  return undefined;
}

/**
 * Exposes the latest visible task plan for the composer without leaking plan-wiring details.
 */
export function deriveComposerTaskPlan(
  messages: ChatMessage[],
): TaskPlanSnapshot | null {
  return deriveComposerTaskPlanSnapshot(messages);
}
