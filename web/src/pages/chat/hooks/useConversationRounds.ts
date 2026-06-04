import { useMemo } from "react";

import type { TaskSummary } from "@/utils/api/react";

export interface ConversationRound {
  taskId: string;
  userMessageId: string;
  preview: string;
  roundNumber: number;
  isLoaded: boolean;
}

/**
 * Derives conversation rounds from task summaries for anchor navigation.
 * Each round represents one user request. `isLoaded` indicates whether the
 * task data is present in the rendered message list.
 */
export function useConversationRounds(
  taskSummaries: TaskSummary[],
  loadedTaskIds: Set<string>,
): ConversationRound[] {
  return useMemo(() => {
    return taskSummaries.map((summary, i) => ({
      taskId: summary.task_id,
      userMessageId: `user-${summary.task_id}`,
      preview: summary.preview,
      roundNumber: i + 1,
      isLoaded: loadedTaskIds.has(summary.task_id),
    }));
  }, [taskSummaries, loadedTaskIds]);
}
