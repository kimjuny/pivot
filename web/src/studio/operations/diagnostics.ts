import type {
  OperationsSessionDiagnostics,
  OperationsSessionLatestError,
  OperationsTaskMessage,
} from "@/studio/operations/api";

/**
 * One task-level issue surfaced in the Operations diagnostics sidebar.
 */
export interface OperationsIssueTask {
  /** Stable task identifier used for copy/paste and backend lookups. */
  taskId: string;
  /** Persisted task lifecycle status. */
  status: string;
  /** Original user request that triggered the task. */
  userMessage: string;
  /** Timestamp of the latest task update. */
  updatedAt: string;
  /** Number of failed recursions observed in the task. */
  failedRecursionCount: number;
  /** Latest task-scoped error when one exists. */
  latestError: OperationsSessionLatestError | null;
  /** Iteration index associated with the latest task-scoped recursion error. */
  latestErrorIteration: number | null;
}

/**
 * Derived diagnostics summary used by the Operations detail page.
 */
export interface OperationsTaskDiagnosticsSummary {
  /** Total number of tasks inside the session. */
  taskCount: number;
  /** Number of completed tasks. */
  completedTaskCount: number;
  /** Number of actively running or pending tasks. */
  activeTaskCount: number;
  /** Number of tasks waiting for user input. */
  waitingInputTaskCount: number;
  /** Number of failed tasks. */
  failedTaskCount: number;
  /** Number of cancelled tasks. */
  cancelledTaskCount: number;
  /** Number of tasks that deserve operator attention. */
  attentionTaskCount: number;
  /** Total recursions across all tasks. */
  totalRecursionCount: number;
  /** Number of failed recursions across all tasks. */
  failedRecursionCount: number;
  /** Total token usage summed across tasks. */
  totalTokens: number;
  /** Latest visible error across all tasks. */
  latestError: OperationsSessionLatestError | null;
  /** Task-level issue summaries sorted by newest update first. */
  issueTasks: OperationsIssueTask[];
}

function isNewerTimestamp(
  candidateTimestamp: string | null,
  currentTimestamp: string | null,
): boolean {
  if (candidateTimestamp === null) {
    return false;
  }
  if (currentTimestamp === null) {
    return true;
  }

  return new Date(candidateTimestamp).getTime() > new Date(currentTimestamp).getTime();
}

function getLatestErrorTimestamp(
  latestError: OperationsSessionLatestError | null,
): string | null {
  return latestError?.timestamp ?? null;
}

function buildTaskFallbackError(task: OperationsTaskMessage): OperationsSessionLatestError | null {
  if (task.status === "failed") {
    return {
      task_id: task.task_id,
      trace_id: null,
      message: "Task failed without a persisted recursion error.",
      timestamp: task.updated_at,
    };
  }

  if (task.status === "cancelled") {
    return {
      task_id: task.task_id,
      trace_id: null,
      message: "Task was cancelled before it completed.",
      timestamp: task.updated_at,
    };
  }

  return null;
}

function buildTaskLatestError(
  task: OperationsTaskMessage,
): {
  failedRecursionCount: number;
  latestError: OperationsSessionLatestError | null;
  latestErrorIteration: number | null;
} {
  let failedRecursionCount = 0;
  let latestError: OperationsSessionLatestError | null = null;
  let latestErrorIteration: number | null = null;

  task.recursions.forEach((recursion) => {
    if (recursion.status === "error") {
      failedRecursionCount += 1;
    }

    const message =
      recursion.error_log?.trim() ||
      (recursion.status === "error"
        ? "Recursion failed without an error log."
        : null);

    if (message === null) {
      return;
    }

    const candidate: OperationsSessionLatestError = {
      task_id: task.task_id,
      trace_id: recursion.trace_id,
      message,
      timestamp: recursion.updated_at,
    };

    if (isNewerTimestamp(candidate.timestamp, latestError?.timestamp ?? null)) {
      latestError = candidate;
      latestErrorIteration = recursion.iteration;
    }
  });

  const fallbackError = buildTaskFallbackError(task);
  if (
    fallbackError !== null &&
    isNewerTimestamp(fallbackError.timestamp, getLatestErrorTimestamp(latestError))
  ) {
    latestError = fallbackError;
  }

  return {
    failedRecursionCount,
    latestError,
    latestErrorIteration,
  };
}

/**
 * Summarize task history into a diagnostics payload for session detail triage.
 *
 * Why: the detail page needs a compact, operator-friendly overview before the
 * reader dives into the full conversation transcript.
 *
 * @param tasks - Session task history returned by the Operations detail API.
 * @returns Aggregated task and recursion diagnostics.
 */
export function summarizeOperationsTasks(
  tasks: OperationsTaskMessage[],
): OperationsTaskDiagnosticsSummary {
  let completedTaskCount = 0;
  let activeTaskCount = 0;
  let waitingInputTaskCount = 0;
  let failedTaskCount = 0;
  let cancelledTaskCount = 0;
  let failedRecursionCount = 0;
  let totalRecursionCount = 0;
  let totalTokens = 0;
  let latestError: OperationsSessionLatestError | null = null;
  const issueTasks: OperationsIssueTask[] = [];

  tasks.forEach((task) => {
    if (task.status === "completed") {
      completedTaskCount += 1;
    } else if (task.status === "waiting_input") {
      waitingInputTaskCount += 1;
    } else if (task.status === "failed") {
      failedTaskCount += 1;
    } else if (task.status === "cancelled") {
      cancelledTaskCount += 1;
    } else if (task.status === "pending" || task.status === "running") {
      activeTaskCount += 1;
    }

    totalRecursionCount += task.recursions.length;
    totalTokens += task.total_tokens;

    const taskDiagnostics = buildTaskLatestError(task);
    failedRecursionCount += taskDiagnostics.failedRecursionCount;

    if (
      taskDiagnostics.latestError !== null &&
      isNewerTimestamp(
        taskDiagnostics.latestError.timestamp,
        latestError?.timestamp ?? null,
      )
    ) {
      latestError = taskDiagnostics.latestError;
    }

    const needsAttention =
      task.status === "failed" ||
      task.status === "waiting_input" ||
      taskDiagnostics.failedRecursionCount > 0;

    if (!needsAttention) {
      return;
    }

    issueTasks.push({
      taskId: task.task_id,
      status: task.status,
      userMessage: task.user_message,
      updatedAt: task.updated_at,
      failedRecursionCount: taskDiagnostics.failedRecursionCount,
      latestError: taskDiagnostics.latestError,
      latestErrorIteration: taskDiagnostics.latestErrorIteration,
    });
  });

  issueTasks.sort(
    (left, right) =>
      new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime(),
  );

  return {
    taskCount: tasks.length,
    completedTaskCount,
    activeTaskCount,
    waitingInputTaskCount,
    failedTaskCount,
    cancelledTaskCount,
    attentionTaskCount: issueTasks.length,
    totalRecursionCount,
    failedRecursionCount,
    totalTokens,
    latestError,
    issueTasks,
  };
}

/**
 * Merge API-provided session diagnostics with task-derived issue details.
 *
 * Why: the list page already receives a compact summary from the backend, while
 * the detail page also needs issue-task drill-down derived from task history.
 *
 * @param diagnostics - Session-level diagnostics returned by the API.
 * @param tasks - Session tasks returned by the detail API.
 * @returns A unified diagnostics summary for detail rendering.
 */
export function buildOperationsDetailDiagnostics(
  diagnostics: OperationsSessionDiagnostics,
  tasks: OperationsTaskMessage[],
): OperationsTaskDiagnosticsSummary {
  const taskSummary = summarizeOperationsTasks(tasks);

  return {
    ...taskSummary,
    taskCount: diagnostics.task_count,
    completedTaskCount: diagnostics.completed_task_count,
    activeTaskCount: diagnostics.active_task_count,
    waitingInputTaskCount: diagnostics.waiting_input_task_count,
    failedTaskCount: diagnostics.failed_task_count,
    cancelledTaskCount: diagnostics.cancelled_task_count,
    attentionTaskCount: diagnostics.attention_task_count,
    failedRecursionCount: diagnostics.failed_recursion_count,
    latestError: diagnostics.latest_error ?? taskSummary.latestError,
  };
}
