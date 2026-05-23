import { useMemo } from "react";

import type { ChatMessage } from "../types";

export interface ConversationRound {
  taskId: string;
  userMessageId: string;
  preview: string;
  roundNumber: number;
}

/**
 * Derives conversation rounds from chat messages by grouping by task_id.
 * Each round represents one user request (the first user message for a given
 * task_id). The preview is capped at 100 characters; the UI component truncates
 * further via CSS.
 */
export function useConversationRounds(
  messages: ChatMessage[],
): ConversationRound[] {
  return useMemo(() => {
    const seen = new Set<string>();
    const rounds: ConversationRound[] = [];

    for (const msg of messages) {
      if (msg.role !== "user" || !msg.task_id || seen.has(msg.task_id)) {
        continue;
      }
      seen.add(msg.task_id);
      rounds.push({
        taskId: msg.task_id,
        userMessageId: msg.id,
        preview: msg.content.slice(0, 100),
        roundNumber: rounds.length + 1,
      });
    }

    return rounds;
  }, [messages]);
}
