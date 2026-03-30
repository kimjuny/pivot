import type {
  ChatMessage,
  PlanStepData,
  TaskPlanSnapshot,
  TaskPlanStep,
  TaskPlanStepStatus,
} from "../types";

interface PlanEventPayload {
  plan?: PlanStepData[];
}

interface SummaryEventPayload {
  current_plan?: PlanStepData[];
}

const DONE_PLAN_STATUSES = new Set(["done", "completed"]);
const RUNNING_PLAN_STATUSES = new Set(["running", "in_progress", "active"]);
const ERROR_PLAN_STATUSES = new Set(["failed", "error"]);

/**
 * Returns the latest assistant task plan that should be rendered above the composer.
 */
export function deriveComposerTaskPlan(
  messages: ChatMessage[],
): TaskPlanSnapshot | null {
  const latestAssistantMessage = [...messages]
    .reverse()
    .find((message) => message.role === "assistant");

  if (!latestAssistantMessage) {
    return null;
  }

  return deriveTaskPlanSnapshot(latestAssistantMessage);
}

/**
 * Builds a plan snapshot from one assistant message using persisted or streamed plan state.
 */
export function deriveTaskPlanSnapshot(
  message: ChatMessage,
): TaskPlanSnapshot | null {
  const recursions = message.recursions ?? [];
  let latestPlanSteps: TaskPlanStep[] | null = null;
  let latestIteration = -1;

  recursions.forEach((recursion) => {
    recursion.events.forEach((event) => {
      const normalizedSteps = extractPlanStepsFromEvent(event);
      if (normalizedSteps.length === 0) {
        return;
      }

      if (recursion.iteration >= latestIteration) {
        latestIteration = recursion.iteration;
        latestPlanSteps = normalizedSteps;
      }
    });
  });

  if (latestPlanSteps) {
    return {
      messageId: message.id,
      taskId: message.task_id,
      taskStatus: message.status,
      steps: applyTaskPlanHeuristics(latestPlanSteps, message.status),
    };
  }

  const persistedPlan = normalizePlanSteps(message.currentPlan);
  if (persistedPlan.length === 0) {
    return null;
  }

  return {
    messageId: message.id,
    taskId: message.task_id,
    taskStatus: message.status,
    steps: applyTaskPlanHeuristics(persistedPlan, message.status),
  };
}

/**
 * Narrows unknown event payloads to the minimal RE_PLAN output shape the UI can consume.
 */
function asPlanEventPayload(value: unknown): PlanEventPayload | undefined {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return undefined;
  }

  return value as PlanEventPayload;
}

/**
 * Narrows summary payloads to the current-plan shape emitted by the live stream.
 */
function asSummaryEventPayload(value: unknown): SummaryEventPayload | undefined {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return undefined;
  }

  return value as SummaryEventPayload;
}

/**
 * Extracts plan-step data from either an explicit plan update or a summary snapshot.
 */
function extractPlanStepsFromEvent(
  event: { type: string; data?: unknown },
): TaskPlanStep[] {
  if (event.type === "plan_update") {
    return normalizePlanSteps(asPlanEventPayload(event.data)?.plan);
  }

  if (event.type === "summary") {
    return normalizePlanSteps(asSummaryEventPayload(event.data)?.current_plan);
  }

  return [];
}

/**
 * Normalizes raw backend plan-step payloads into a small UI-specific shape.
 */
function normalizePlanSteps(rawSteps: PlanStepData[] | undefined): TaskPlanStep[] {
  if (!Array.isArray(rawSteps)) {
    return [];
  }

  return rawSteps
    .filter((step): step is PlanStepData => {
      return (
        typeof step?.step_id === "string" &&
        typeof step?.general_goal === "string" &&
        typeof step?.specific_description === "string" &&
        typeof step?.completion_criteria === "string" &&
        typeof step?.status === "string"
      );
    })
    .map((step, index) => ({
      stepId: step.step_id || String(index + 1),
      title:
        step.general_goal.trim() ||
        step.specific_description.trim() ||
        `Step ${index + 1}`,
      description: step.specific_description.trim(),
      completionCriteria: step.completion_criteria.trim(),
      status: normalizeTaskPlanStatus(step.status),
    }));
}

/**
 * Maps backend plan-step status labels into the four visual states used in the composer.
 */
function normalizeTaskPlanStatus(status: string): TaskPlanStepStatus {
  const normalizedStatus = status.trim().toLowerCase();

  if (DONE_PLAN_STATUSES.has(normalizedStatus)) {
    return "done";
  }

  if (RUNNING_PLAN_STATUSES.has(normalizedStatus)) {
    return "running";
  }

  if (ERROR_PLAN_STATUSES.has(normalizedStatus)) {
    return "error";
  }

  return "pending";
}

/**
 * Smooths plan rendering when history does not yet include every later step-status update.
 */
function applyTaskPlanHeuristics(
  steps: TaskPlanStep[],
  messageStatus: ChatMessage["status"],
): TaskPlanStep[] {
  const nextSteps = steps.map((step) => ({ ...step }));

  if (messageStatus === "completed") {
    return nextSteps.map((step) =>
      step.status === "error" || step.status === "done"
        ? step
        : { ...step, status: "done" },
    );
  }

  if (messageStatus === "error") {
    if (!nextSteps.some((step) => step.status === "error")) {
      const firstIncompleteIndex = nextSteps.findIndex(
        (step) => step.status !== "done",
      );
      if (firstIncompleteIndex >= 0) {
        nextSteps[firstIncompleteIndex] = {
          ...nextSteps[firstIncompleteIndex],
          status: "error",
        };
      }
    }

    return nextSteps;
  }

  if (
    messageStatus === "running" ||
    messageStatus === "waiting_input" ||
    messageStatus === "skill_resolving"
  ) {
    if (!nextSteps.some((step) => step.status === "running")) {
      const firstPendingIndex = nextSteps.findIndex(
        (step) => step.status === "pending",
      );
      if (firstPendingIndex >= 0) {
        nextSteps[firstPendingIndex] = {
          ...nextSteps[firstPendingIndex],
          status: "running",
        };
      }
    }
  }

  return nextSteps;
}
