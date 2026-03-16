import type {
  ChatMessage,
  RecursionRecord,
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
  return Math.round(((end - start) / 1000) * 10) / 10;
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
): "running" | "completed" | "warning" | "error" {
  if (recursion.status === "running") {
    return "running";
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
    message.status === "waiting_input" || getLastRecursion(message)?.action === "CLARIFY"
  );
}

/**
 * Exposes the latest visible task plan for the composer without leaking plan-wiring details.
 */
export function deriveComposerTaskPlan(
  messages: ChatMessage[],
): TaskPlanSnapshot | null {
  return deriveComposerTaskPlanSnapshot(messages);
}
