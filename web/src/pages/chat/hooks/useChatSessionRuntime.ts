import { useCallback, useMemo, useReducer, useRef } from "react";

import type { TaskMessage, TaskSummary } from "@/utils/api";

export type OlderHistoryStatus =
  | "uninitialized"
  | "idle"
  | "loading"
  | "exhausted";

export interface ChatSessionRuntime {
  sessionId: string;
  taskSummaries: TaskSummary[];
  loadedTaskIds: Set<string>;
  oldestLoadedTaskId: string | null;
  olderStatus: OlderHistoryStatus;
  pageSize: number;
}

type ChatSessionRuntimeAction =
  | { type: "RESET_DRAFT" }
  | { type: "INIT_SESSION"; sessionId: string; pageSize: number }
  | {
      type: "HYDRATE_HISTORY";
      sessionId: string;
      taskSummaries: TaskSummary[];
      tasks: TaskMessage[];
      hasMoreOlder: boolean;
      pageSize: number;
    }
  | { type: "START_LOAD_OLDER"; sessionId: string }
  | {
      type: "APPLY_OLDER_PAGE";
      sessionId: string;
      tasks: TaskMessage[];
      hasMoreOlder: boolean;
    }
  | { type: "FAIL_LOAD_OLDER"; sessionId: string }
  | {
      type: "REGISTER_NEW_TASK";
      sessionId: string;
      task: TaskSummary;
      isBrandNewSession: boolean;
      pageSize: number;
    };

function olderStatusForPage(
  oldestLoadedTaskId: string | null,
  hasMoreOlder: boolean,
): OlderHistoryStatus {
  return oldestLoadedTaskId && hasMoreOlder ? "idle" : "exhausted";
}

function taskIdsFromTasks(tasks: TaskMessage[]): Set<string> {
  return new Set(tasks.map((task) => task.task_id));
}

function upsertTaskSummary(
  summaries: TaskSummary[],
  nextSummary: TaskSummary,
): TaskSummary[] {
  const existingIndex = summaries.findIndex(
    (summary) => summary.task_id === nextSummary.task_id,
  );
  if (existingIndex === -1) {
    return [...summaries, nextSummary];
  }

  return summaries.map((summary, index) =>
    index === existingIndex ? nextSummary : summary,
  );
}

function chatSessionRuntimeReducer(
  runtime: ChatSessionRuntime | null,
  action: ChatSessionRuntimeAction,
): ChatSessionRuntime | null {
  switch (action.type) {
    case "RESET_DRAFT":
      return null;

    case "INIT_SESSION":
      return {
        sessionId: action.sessionId,
        taskSummaries: [],
        loadedTaskIds: new Set(),
        oldestLoadedTaskId: null,
        olderStatus: "uninitialized",
        pageSize: action.pageSize,
      };

    case "HYDRATE_HISTORY": {
      const oldestLoadedTaskId = action.tasks[0]?.task_id ?? null;
      return {
        sessionId: action.sessionId,
        taskSummaries: action.taskSummaries,
        loadedTaskIds: taskIdsFromTasks(action.tasks),
        oldestLoadedTaskId,
        olderStatus: olderStatusForPage(
          oldestLoadedTaskId,
          action.hasMoreOlder,
        ),
        pageSize: action.pageSize,
      };
    }

    case "START_LOAD_OLDER":
      if (!runtime || runtime.sessionId !== action.sessionId) {
        return runtime;
      }
      if (
        runtime.olderStatus !== "idle" ||
        runtime.oldestLoadedTaskId === null
      ) {
        return runtime;
      }
      return { ...runtime, olderStatus: "loading" };

    case "APPLY_OLDER_PAGE": {
      if (!runtime || runtime.sessionId !== action.sessionId) {
        return runtime;
      }
      if (action.tasks.length === 0) {
        return { ...runtime, olderStatus: "exhausted" };
      }

      const loadedTaskIds = new Set(runtime.loadedTaskIds);
      action.tasks.forEach((task) => loadedTaskIds.add(task.task_id));
      const oldestLoadedTaskId = action.tasks[0]?.task_id ?? null;
      return {
        ...runtime,
        loadedTaskIds,
        oldestLoadedTaskId,
        olderStatus: olderStatusForPage(
          oldestLoadedTaskId,
          action.hasMoreOlder,
        ),
      };
    }

    case "FAIL_LOAD_OLDER":
      if (!runtime || runtime.sessionId !== action.sessionId) {
        return runtime;
      }
      return {
        ...runtime,
        olderStatus: runtime.oldestLoadedTaskId ? "idle" : "exhausted",
      };

    case "REGISTER_NEW_TASK": {
      if (!runtime || runtime.sessionId !== action.sessionId) {
        const loadedTaskIds = new Set([action.task.task_id]);
        return {
          sessionId: action.sessionId,
          taskSummaries: [action.task],
          loadedTaskIds,
          oldestLoadedTaskId: action.task.task_id,
          olderStatus: "exhausted",
          pageSize: action.pageSize,
        };
      }

      const loadedTaskIds = new Set(runtime.loadedTaskIds);
      loadedTaskIds.add(action.task.task_id);

      if (action.isBrandNewSession || runtime.oldestLoadedTaskId === null) {
        return {
          ...runtime,
          taskSummaries: upsertTaskSummary(runtime.taskSummaries, action.task),
          loadedTaskIds,
          oldestLoadedTaskId: action.task.task_id,
          olderStatus: "exhausted",
        };
      }

      return {
        ...runtime,
        taskSummaries: upsertTaskSummary(runtime.taskSummaries, action.task),
        loadedTaskIds,
      };
    }

    default:
      return runtime;
  }
}

export function useChatSessionRuntime() {
  const [runtime, rawDispatch] = useReducer(chatSessionRuntimeReducer, null);
  const runtimeRef = useRef<ChatSessionRuntime | null>(null);
  runtimeRef.current = runtime;

  const dispatch = useCallback((action: ChatSessionRuntimeAction) => {
    runtimeRef.current = chatSessionRuntimeReducer(runtimeRef.current, action);
    rawDispatch(action);
  }, []);

  return useMemo(
    () => ({
      runtime,
      runtimeRef,
      dispatch,
    }),
    [runtime, dispatch],
  );
}
